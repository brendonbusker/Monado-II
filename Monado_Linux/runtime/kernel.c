// A small Horizon kernel: handles, threads, synchronization, memory, and the SVC dispatcher.
#include "diag/diag.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "hle.h"
#include "hle/fibers.h"  // [XCDE] LINUX-003: native fiber lifecycle at thread/reboot boundaries
#include "kernel.h"

// ------------------------------------------------------------------ results
#undef R_OK
#define R_OK 0
#define R_TIMEOUT 0xEA01
#define R_CANCELLED 0xEC01
#define R_INVALID_HANDLE 0xE401
#define R_INVALID_STATE 0xFA01
#define R_INVALID_ADDRESS 0xCC01
#define R_NOT_FOUND 0xF201
#define R_INVALID_ENUM 0xF001
#define R_OUT_OF_RESOURCE 0xD001

#define PSEUDO_THREAD 0xFFFF8000u
#define PSEUDO_PROCESS 0xFFFF8001u
#define WAITERS_BIT 0x40000000u

pthread_mutex_t g_klock = PTHREAD_MUTEX_INITIALIZER;
static __thread KThread *t_cur;

// ------------------------------------------------------------------ handle table
#define MAX_HANDLES 4096
static KObject *handles[MAX_HANDLES];

static uint32_t handle_alloc(KObject *o) {
    for (int i = 1; i < MAX_HANDLES; i++) {
        if (!handles[i]) {
            handles[i] = o;
            o->refs++;
            return 0x100 + i;
        }
    }
    FATAL("out of handles\n");
}

KObject *handle_get(uint32_t h) {
    if (h == PSEUDO_THREAD) return &t_cur->obj;
    if (h < 0x101 || h >= 0x100 + MAX_HANDLES) return NULL;
    return handles[h - 0x100];
}

uint32_t kernel_new_handle(KObject *o) {
    pthread_mutex_lock(&g_klock);
    uint32_t h = handle_alloc(o);
    pthread_mutex_unlock(&g_klock);
    return h;
}

static void handle_close(uint32_t h) {
    KObject *o = handle_get(h);
    if (!o || h == PSEUDO_THREAD) return;
    handles[h - 0x100] = NULL;
    o->refs--;
}

// Threads blocked in WaitSynchronization; object signals wake only these (caller holds g_klock).
static KThread *g_syncwaiters;

// ------------------------------------------------------------------ deterministic scheduler (T029)
// Only the baton holder runs guest code. Everything below runs with g_klock held.
static bool g_det;
static KThread *g_baton;
// [XCDE] LINUX-008: virtual timers signal events from inside the dispatcher.
// Protected by g_klock; an external wake must not recursively grant a baton.
static bool g_det_dispatching;
static uint64_t g_det_seq;
static uint64_t g_vnow = 1000000000ull;  // virtual ns (starts at 1 s: some code treats 0 as "never")
typedef struct { uint64_t when, seq; void (*fn)(void *); void *arg; } DetTimer;
static DetTimer g_timers[32];
static int g_ntimers;

bool kernel_det(void) { return g_det; }
static uint64_t g_det_digest = 0xcbf29ce484222325ull;
uint64_t kernel_det_digest(void) { return g_det_digest; }
uint64_t kernel_vnow(int tick) { return tick ? __atomic_add_fetch(&g_vnow, 1000, __ATOMIC_RELAXED) : __atomic_load_n(&g_vnow, __ATOMIC_RELAXED); }

void kernel_timer_at(uint64_t when, void (*fn)(void *), void *arg) {
    if (g_ntimers == 32) FATAL("too many virtual timers\n");
    g_timers[g_ntimers++] = (DetTimer){when, g_det_seq++, fn, arg};
}

void kernel_timer_cancel(void *arg) {  // caller holds g_klock
    for (int i = 0; i < g_ntimers;) { if (g_timers[i].arg == arg) g_timers[i] = g_timers[--g_ntimers]; else i++; }
}

static void det_runnable(KThread *t) { t->det_state = 1; t->det_seq = g_det_seq++; }

static KThread *det_pick(void);
static void det_dispatch(void);

static void wake(KThread *t) {
    if (g_det && t->started) { if (t->det_state == 3) det_runnable(t); return; }
    pthread_cond_signal(&t->cond);
}

void kernel_signal(KObject *o) {
    // caller holds g_klock
    o->signaled = true;
    for (KThread *t = g_syncwaiters; t; t = t->snext) wake(t);
    // [XCDE] LINUX-008: a native UI/device event can wake the last blocked
    // guest. Runnable alone is insufficient when no thread owns the baton.
    // Timer callbacks already have a dispatcher responsible for selecting it.
    if (g_syncwaiters && g_det && !g_baton && !g_det_dispatching) det_dispatch();
}

// ------------------------------------------------------------------ time

uint64_t rt_ticks(void) {
    // 19.2 MHz system tick
    uint64_t ns = diag_deterministic() ? diag_now_ns() : plat_now_ns();  // [XCDE] T029: virtual clock
    static double scale = -1;
    if (scale < 0) scale = getenv("LARECOMP_TICK_SCALE") ? atof(getenv("LARECOMP_TICK_SCALE")) : 1.0;
    if (scale != 1.0) ns = (uint64_t)(ns * scale);
    return ns / 625 * 12 + ns % 625 * 12 / 625;  // = ns * 192 / 10000 exactly, in 64 bits ([XCDE] perf: no 128-bit division)
}

static void deadline(struct timespec *ts, int64_t timeout_ns) {
    if (g_det) {  // virtual deadline, carried in the timespec as ns
        uint64_t v = kernel_vnow(0) + (uint64_t)timeout_ns;
        ts->tv_sec = (time_t)(v / 1000000000ull), ts->tv_nsec = (long)(v % 1000000000ull);
        return;
    }
    clock_gettime(CLOCK_REALTIME, ts);
    ts->tv_sec += timeout_ns / 1000000000;
    ts->tv_nsec += timeout_ns % 1000000000;
    if (ts->tv_nsec >= 1000000000) { ts->tv_sec++; ts->tv_nsec -= 1000000000; }
}

// Sleep on the current thread's condition. Returns false on timeout. Caller holds g_klock.
static pthread_cond_t g_nothread_cond = PTHREAD_COND_INITIALIZER;
// Time this thread spent blocked in the kernel (waits, sleeps): idle, not work. Frame pacing (exec.c vk_pace_frame)
// takes the presenting thread's: a frame's busy time is its period minus this.
__thread uint64_t g_blocked_ns;

static bool det_block(int64_t deadline_vns);  // (below)
static bool kwait(int64_t timeout_ns, const struct timespec *ts) {
    if (g_det && t_cur && t_cur->det_state == 2)
        return det_block(timeout_ns < 0 ? -1 : (int64_t)ts->tv_sec * 1000000000ll + ts->tv_nsec);
    pthread_cond_t *cv = t_cur ? &t_cur->cond : &g_nothread_cond;
    uint64_t t0 = plat_now_ns();
    bool r = true;
    if (timeout_ns < 0) pthread_cond_wait(cv, &g_klock);
    else r = pthread_cond_timedwait(cv, &g_klock, ts) == 0;
    g_blocked_ns += plat_now_ns() - t0;
    return r;
}

// ------------------------------------------------------------------ memory map
typedef struct { uint64_t addr, size; uint32_t type, perm; } Region;
// [XCDE] 16384 entries (was 1024): other runtimes passed a few thousand regions within minutes of play (WindowSmash
// 2a7bb23: ~2,500 after one minute of menus, the 4,096 limit after ten minutes of matches). Entries are 24 bytes.
#define MAX_REGIONS 16384
static Region regions[MAX_REGIONS];
static int nregions;
// [XCDE] LINUX-005: render-worker heap import reads this outside the guest lock.
// Publish SetHeapSize/reset without a C data race; guest region locking is unchanged.
static _Atomic uint64_t heap_size;
static uint64_t tls_next = TLS_BASE;
uint64_t kernel_heap_size(void) { return heap_size; }  // bytes from HEAP_BASE set by SetHeapSize
// Writable guest data regions (heap, mapped/physical memory, module .data): for debug/runtime memory scans.
int kernel_data_regions(uint64_t *addr, uint64_t *size, int max) {
    int n = 0;
    for (int i = 0; i < nregions && n < max; i++)
        if ((regions[i].perm & 2) && regions[i].type != 0xB && regions[i].type != 0xC) {
            addr[n] = regions[i].addr; size[n] = regions[i].size; n++;
        }
    return n;
}

static void region_add(uint64_t addr, uint64_t size, uint32_t type, uint32_t perm) {
    if (nregions == MAX_REGIONS) FATAL("too many regions\n");
    if (nregions + 1 == 1024 || nregions + 1 == 4096 || nregions + 1 == 12000)  // (long-session growth shows in the log)
        LOG("[kernel] %d memory regions\n", nregions + 1);
    plat_commit(addr, size);  // back it before the OS writes there (Windows: file reads into the heap)
    int i = nregions++;
    while (i > 0 && regions[i - 1].addr > addr) { regions[i] = regions[i - 1]; i--; }
    regions[i] = (Region){addr, size, type, perm};
}

static void region_remove(uint64_t addr) {
    for (int i = 0; i < nregions; i++) {
        if (regions[i].addr == addr) {
            memmove(&regions[i], &regions[i + 1], (nregions - i - 1) * sizeof(Region));
            nregions--;
            return;
        }
    }
}

static void query_memory(uint64_t addr, uint64_t out) {
    uint64_t prev_end = 0;
    uint64_t info[5] = {0};  // addr, size, type|attr<<32, perm|ipc<<32, device|pad<<32
    for (int i = 0; i < nregions; i++) {
        Region *r = &regions[i];
        if (addr >= r->addr && addr < r->addr + r->size) {
            info[0] = r->addr;
            info[1] = r->size;
            info[2] = r->type;
            info[3] = r->perm;
            memcpy((void *)out, info, 0x28);
            return;
        }
        if (addr < r->addr) {
            info[0] = prev_end;
            info[1] = r->addr - prev_end;
            memcpy((void *)out, info, 0x28);
            return;
        }
        prev_end = r->addr + r->size;
    }
    info[0] = prev_end;
    info[1] = (1ull << 39) - prev_end;
    memcpy((void *)out, info, 0x28);
}

// ------------------------------------------------------------------ threads
static uint64_t next_thread_id = 0x50;

// ------------------------------------------------------------------ in-place reboot
// Recompiled guest code can't be killed from outside, so a reboot (runtime/main.c) sets g_rt_unwind, wakes every
// waiting thread, and each guest thread longjmps back to thread_main at its next safe point: rt_svc (entry and
// exit), an HLE call (runtime/dispatch.c), or a kernel wait (which returns early while g_rt_unwind is set). The
// frames dropped are recompiled code (its state lives in guest memory, which is wiped next) and HLE functions;
// none of those hold a host lock across a call into the guest, so nothing stays locked. svcExitThread ends a
// thread the same way.
// [XCDE] LINUX-003: cooperative stop is shared across pthreads; volatile was a data race.
int g_rt_unwind;
static bool unwind_requested(void) { return __atomic_load_n(&g_rt_unwind, __ATOMIC_ACQUIRE) != 0; }
static KThread *g_threads;  // every thread of this boot (g_klock)

void rt_unwind_point(void) {
    if (__builtin_expect(unwind_requested(), 0) && t_cur) longjmp(t_cur->unwind, 1);
}

static KThread *det_pick(void) {
    KThread *best = NULL;
    for (KThread *t = g_threads; t; t = t->anext)
        if (t->det_state == 1 && (!best || t->det_seq < best->det_seq)) best = t;  // FIFO, not by priority: one baton stands for 4 cores, so strict priorities starve the loaders
    return best;
}

// The baton is free: hand it to the best runnable thread. With none, time passes: jump to the earliest timer or timeout.
static void det_dispatch(void) {
    g_det_dispatching = true;
    g_baton = NULL;
    for (;;) {
        // everything already due (time moved on while threads were running or yielding) fires before anyone is picked
        for (;;) {
            int di = -1;
            for (int i = 0; i < g_ntimers; i++)
                if (g_timers[i].when <= kernel_vnow(0) && (di < 0 || g_timers[i].when < g_timers[di].when || (g_timers[i].when == g_timers[di].when && g_timers[i].seq < g_timers[di].seq))) di = i;
            KThread *dt = NULL;
            for (KThread *t = g_threads; t; t = t->anext)
                if (t->det_state == 3 && t->det_deadline >= 0 && (uint64_t)t->det_deadline <= kernel_vnow(0) && (!dt || t->det_deadline < dt->det_deadline || (t->det_deadline == dt->det_deadline && t->id < dt->id))) dt = t;
            if (di >= 0 && (!dt || (int64_t)g_timers[di].when <= dt->det_deadline)) {
                DetTimer tm = g_timers[di];
                g_timers[di] = g_timers[--g_ntimers];
                tm.fn(tm.arg);
            } else if (dt) {
                dt->det_timed_out = true;
                det_runnable(dt);
            } else break;
        }
        KThread *n = det_pick();
        if (n) {
            static int tr = -1;
            static unsigned long ntr;
            if (tr < 0) tr = getenv("XCDE_DET_TRACE") != NULL;
            if (tr && ntr++ < 400) fprintf(stderr, "[det] -> t%llu (prio %d) vnow %llu\n", (unsigned long long)n->id, n->prio, (unsigned long long)kernel_vnow(0));
            n->det_state = 2, g_baton = n, n->det_granted = true;
            pthread_cond_signal(&n->cond);
            g_det_dispatching = false;
            return;
        }
        int ti = -1;
        for (int i = 0; i < g_ntimers; i++)
            if (ti < 0 || g_timers[i].when < g_timers[ti].when || (g_timers[i].when == g_timers[ti].when && g_timers[i].seq < g_timers[ti].seq)) ti = i;
        KThread *bt = NULL;
        for (KThread *t = g_threads; t; t = t->anext)
            if (t->det_state == 3 && t->det_deadline >= 0 && (!bt || t->det_deadline < bt->det_deadline || (t->det_deadline == bt->det_deadline && t->id < bt->id))) bt = t;
        if (ti < 0 && !bt) {
            g_det_dispatching = false;
            return;  // every thread is blocked for good (or none exists yet)
        }
        if (ti >= 0 && (!bt || (int64_t)g_timers[ti].when <= bt->det_deadline)) {
            DetTimer tm = g_timers[ti];
            g_timers[ti] = g_timers[--g_ntimers];
            if (tm.when > kernel_vnow(0)) g_vnow = tm.when;
            tm.fn(tm.arg);
        } else {
            if ((uint64_t)bt->det_deadline > kernel_vnow(0)) g_vnow = (uint64_t)bt->det_deadline;
            bt->det_timed_out = true;
            det_runnable(bt);
        }
    }
}

// Give up the baton and wait to get it back; deadline_vns < 0: no timeout. Returns false if the wait timed out.
static bool det_block(int64_t deadline_vns) {
    KThread *t = t_cur;
    static int tr2 = -1;
    static unsigned long ntr2;
    if (tr2 < 0) tr2 = getenv("XCDE_DET_TRACE") != NULL;
    if (tr2 && ntr2++ < 400) fprintf(stderr, "[det] t%llu blocks (svc %02x, deadline %lld)\n", (unsigned long long)t->id, t->last_svc, (long long)deadline_vns);
    t->det_state = 3, t->det_deadline = deadline_vns, t->det_timed_out = false, t->det_granted = false;
    det_dispatch();
    while (!t->det_granted) pthread_cond_wait(&t->cond, &g_klock);
    t->det_deadline = -1;
    return !t->det_timed_out;
}

static void det_yield(uint64_t cost_ns) {  // lock held; the yielding thread "used" cost_ns of virtual time
    KThread *t = t_cur;
    __atomic_add_fetch(&g_vnow, cost_ns, __ATOMIC_RELAXED);
    det_runnable(t);
    t->det_granted = false;
    det_dispatch();
    while (!t->det_granted) pthread_cond_wait(&t->cond, &g_klock);
}

// [XCDE] T122: a host mutex in HLE code that may be held across a guest call (an SVC there can hand the baton to
// another thread). In the deterministic mode a guest thread that finds it busy must not block holding the baton (the
// holder waits for the baton: the movie decoder deadlocked at frame 5245); it yields until the mutex is free.
void kernel_det_mutex_lock(pthread_mutex_t *m) {
    if (!g_det || !t_cur) { pthread_mutex_lock(m); return; }
    while (pthread_mutex_trylock(m) != 0) {
        pthread_mutex_lock(&g_klock);
        det_yield(1000);
        pthread_mutex_unlock(&g_klock);
    }
}

static void *thread_main(void *arg) {
    KThread *t = arg;
    t_cur = t;
    crash_handler_install();
#ifdef __linux__
    // [XCDE] LINUX-007: portable helpers require a known host FP environment.
    if (!plat_guest_fp_init()) FATAL("[kernel] cannot establish guest thread host FP environment\n");
#else
    rt_set_fpcr(0);
#endif
    { char nm[64]; snprintf(nm, sizeof nm, "guest t%llu p%d f_%llx", (unsigned long long)t->id, t->prio, (unsigned long long)t->entry); plat_thread_name(nm); }
    if (g_det) {  // runnable since thread_start (made so by the starter, in a deterministic order); wait for the baton
        pthread_mutex_lock(&g_klock);
        while (!t->det_granted) pthread_cond_wait(&t->cond, &g_klock);
        pthread_mutex_unlock(&g_klock);
    }
    if (!setjmp(t->unwind)) guest_call(&t->cpu, t->entry);
#if defined(__linux__) && defined(__x86_64__)
    // Back on the native stack after normal return, ExitThread or reboot unwind.
    fibers_thread_cleanup();
#endif
#ifdef __linux__
    plat_crash_handler_uninstall();
#endif
    pthread_mutex_lock(&g_klock);
    t->finished = true;
    kernel_signal(&t->obj);
    if (g_det) { t->det_state = 0; det_dispatch(); }
    pthread_mutex_unlock(&g_klock);
    t_cur = NULL;
    return NULL;
}

static KThread *thread_new(uint64_t entry, uint64_t arg, uint64_t stack_top, int prio, int core) {
    KThread *t = calloc(1, sizeof *t);
    pthread_cond_init(&t->cond, NULL);
    t->obj.type = KOBJ_THREAD;
    t->entry = entry;
    t->prio = prio;
    t->core = core < 0 ? 0 : core;
    t->id = next_thread_id++;
    t->cpu.x[0] = arg;
    t->cpu.sp = stack_top & ~15ull;
    t->cpu.excl_addr = ~0ull;
    t->tlr = tls_next;
    tls_next += 0x200;
    t->cpu.tpidrro = t->tlr;
    t->cpu.thread = t;
    pthread_mutex_lock(&g_klock);
    t->anext = g_threads;
    g_threads = t;
    pthread_mutex_unlock(&g_klock);
    return t;
}

static void thread_start(KThread *t) {
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    // guest recursion runs on the host stack: 256 MB. [XCDE] On Windows (winpthreads) an explicit stack size is committed
    // up front - ~38 guest threads committed ~10 GB, and with the commit limit reached pthread_create failed silently:
    // in the deterministic mode the new thread then held the baton with no host thread (hang at frame 7, two runs in
    // parallel). There the threads take the executable's default stack, a 256 MB reservation (link -Wl,--stack).
#ifndef _WIN32
    pthread_attr_setstacksize(&attr, 256ull << 20);
#endif
    pthread_mutex_lock(&g_klock);
    t->started = true;
    if (g_det) {
        det_runnable(t);
        if (!g_baton) det_dispatch();  // nobody is running (the very first thread)
    }
    pthread_mutex_unlock(&g_klock);
    int err = pthread_create(&t->host, &attr, thread_main, t);
    pthread_attr_destroy(&attr);
    if (err) {  // a guest thread that cannot exist would hang the game (or the deterministic baton) later, silently
        LOG("FATAL: cannot create the host thread for guest thread %llu (entry %llx): error %d\n", (unsigned long long)t->id,
            (unsigned long long)t->entry, err);
        abort();
    }
}

KThread *kernel_create_main_thread(uint64_t entry, uint64_t stack_size, int prio) {
    uint64_t stack = STACK_BASE + STACK_SIZE - ((stack_size + 0xFFFF) & ~0xFFFFull);
    region_add(stack, stack_size, 0xB, 3);
    KThread *t = thread_new(entry, 0, stack + stack_size, prio, 0);
    t->handle = kernel_new_handle(&t->obj);
    return t;
}

void kernel_run_main(KThread *t, uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3) {
    t->cpu.x[0] = x0; t->cpu.x[1] = x1; t->cpu.x[2] = x2; t->cpu.x[3] = x3;
    thread_start(t);  // the host main thread goes on to run the window event loop
}

// [XCDE] LINUX-003: a guest fiber may resume on another pthread. Do not inline or
// hoist these TLS reads across a transfer, including in unity/LTO test builds.
__attribute__((noinline)) KThread *kernel_current_thread(void) {
    __asm__ volatile("" ::: "memory");
    return t_cur;
}
uint32_t kernel_current_thread_handle(void) {
    KThread *thread = kernel_current_thread();
    return thread ? thread->handle : 0;
}
Cpu *kernel_current_cpu(void) {
    KThread *thread = kernel_current_thread();
    return thread ? &thread->cpu : NULL;
}

// ------------------------------------------------------------------ mutex / condvar (Horizon semantics)
// Mutex word: owner handle | WAITERS_BIT. Waiting threads sleep on the global cond and are handed ownership.

static uint32_t *u32p(uint64_t a) { return (uint32_t *)(uintptr_t)a; }

// Try to take mutex `m` for `tag`, or mark it contended. Returns true if acquired. Uses CAS so a
// concurrent user-space unlock (owner storing 0) is never overwritten.
static bool mutex_acquire_or_mark(uint64_t m, uint32_t tag) {
    for (;;) {
        uint32_t v = __atomic_load_n(u32p(m), __ATOMIC_SEQ_CST);
        if (v == 0) {
            if (__atomic_compare_exchange_n(u32p(m), &v, tag, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) return true;
        } else {
            if ((v & WAITERS_BIT) ||
                __atomic_compare_exchange_n(u32p(m), &v, v | WAITERS_BIT, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST))
                return false;
        }
    }
}

// Pick a thread waiting on mutex `addr` and give it ownership. Caller holds g_klock.
static void mutex_release(uint64_t addr) {
    KThread *next = NULL;
    int count = 0;
    for (KThread *t = g_waitlist; t; t = t->wnext) {
        if (t->wait_kind == WAIT_MUTEX && t->wait_addr == addr) {
            if (!next || t->prio < next->prio) next = t;
            count++;
        }
    }
    if (!next) {
        __atomic_store_n(u32p(addr), 0, __ATOMIC_SEQ_CST);
        return;
    }
    __atomic_store_n(u32p(addr), next->handle | (count > 1 ? WAITERS_BIT : 0), __ATOMIC_SEQ_CST);
    next->wait_kind = WAIT_NONE;
    next->wait_result = R_OK;
    wake(next);
}

KThread *g_waitlist;

static void waitlist_add(KThread *t) { t->wnext = g_waitlist; g_waitlist = t; }
static void waitlist_remove(KThread *t) {
    for (KThread **p = &g_waitlist; *p; p = &(*p)->wnext)
        if (*p == t) { *p = t->wnext; return; }
}

// Block until wait_kind is cleared by a waker, timeout, or cancel. Caller holds g_klock.
static uint32_t block_current(int64_t timeout_ns) {
    KThread *t = t_cur;
    struct timespec ts;
    if (timeout_ns >= 0) deadline(&ts, timeout_ns);
    waitlist_add(t);
    while (t->wait_kind != WAIT_NONE) {
        if (unwind_requested()) {  // reboot: give up the wait (the thread unwinds when its svc returns)
            t->wait_kind = WAIT_NONE;
            t->wait_result = R_CANCELLED;
            break;
        }
        if (t->cancel) {
            t->cancel = false;
            t->wait_kind = WAIT_NONE;
            t->wait_result = R_CANCELLED;
            break;
        }
        if (!kwait(timeout_ns, &ts)) {
            // [XCDE] T067: ETIMEDOUT can race with a waker that already completed this wait under g_klock (a condvar
            // signal that handed us the mutex). Overwriting that with R_TIMEOUT returned "no mutex" to a thread that owned
            // it, which then waited on its own lock forever. A signaled wait that is still queued for the mutex (the
            // timeout only covers the condvar part) keeps waiting for it.
            if (t->wait_kind == WAIT_NONE) break;
            if (t->wait_kind == WAIT_MUTEX) { timeout_ns = -1; continue; }
            t->wait_kind = WAIT_NONE;
            t->wait_result = R_TIMEOUT;
            break;
        }
    }
    waitlist_remove(t);
    return t->wait_result;
}

static uint32_t svc_arbitrate_lock(uint32_t owner, uint64_t addr, uint32_t tag) {
    pthread_mutex_lock(&g_klock);
    uint32_t v = __atomic_load_n(u32p(addr), __ATOMIC_SEQ_CST);
    if (v != (owner | WAITERS_BIT)) {
        pthread_mutex_unlock(&g_klock);
        return R_OK;
    }
    KThread *t = t_cur;
    t->wait_kind = WAIT_MUTEX;
    t->wait_addr = addr;
    t->wait_tag = tag;
    uint32_t r = block_current(-1);
    pthread_mutex_unlock(&g_klock);
    return r == R_CANCELLED ? R_OK : r;
}

static uint32_t svc_arbitrate_unlock(uint64_t addr) {
    pthread_mutex_lock(&g_klock);
    mutex_release(addr);
    pthread_mutex_unlock(&g_klock);
    return R_OK;
}

static uint32_t svc_wait_process_wide_key(uint64_t mutex, uint64_t key, uint32_t tag, int64_t timeout) {
    pthread_mutex_lock(&g_klock);
    KThread *t = t_cur;
    t->wait_kind = WAIT_CONDVAR;
    t->wait_addr = key;
    t->wait_mutex = mutex;
    t->wait_tag = tag;
    // [XCDE] the key ("has waiters") is set BEFORE the mutex is released, as Horizon does: nn::os's Signal reads the key
    // without the kernel lock and skips the svc while it is 0. Released first, a thread that took the mutex in that gap
    // and signalled saw 0 and woke nobody: a lost wakeup, the waiter asleep for good (PokeZ-ARecomp 52359cc).
    __atomic_store_n(u32p(key), 1, __ATOMIC_SEQ_CST);
    mutex_release(mutex);
    uint32_t r = block_current(timeout);
    // [XCDE] A wait that times out (or is cancelled) returns WITHOUT the mutex, as Horizon does: nn::os takes it again
    // itself on R_TIMEOUT (libnx condvar.c does the same). Re-taking it here as well left the thread waiting on its own
    // lock forever (LASRecomp #74/#88; first XCDE boot: main thread stuck on a mutex owned by a thread blocked on it).
    // A signaled wait gets the mutex from svc_signal_process_wide_key.
    pthread_mutex_unlock(&g_klock);
    return r;
}

static void svc_signal_process_wide_key(uint64_t key, int32_t count) {
    pthread_mutex_lock(&g_klock);
    int woken = 0;
    bool any_left = false;
    for (;;) {
        if (count > 0 && woken >= count) break;
        KThread *best = NULL;
        for (KThread *t = g_waitlist; t; t = t->wnext)
            if (t->wait_kind == WAIT_CONDVAR && t->wait_addr == key && (!best || t->prio < best->prio)) best = t;
        if (!best) break;
        woken++;
        // the woken thread must reacquire its mutex
        uint64_t m = best->wait_mutex;
        best->wait_result = R_OK;
        if (mutex_acquire_or_mark(m, best->wait_tag)) {
            best->wait_kind = WAIT_NONE;
            wake(best);
        } else {
            best->wait_kind = WAIT_MUTEX;
            best->wait_addr = m;
        }
    }
    for (KThread *t = g_waitlist; t; t = t->wnext)
        if (t->wait_kind == WAIT_CONDVAR && t->wait_addr == key) any_left = true;
    if (!any_left) __atomic_store_n(u32p(key), 0, __ATOMIC_SEQ_CST);
    pthread_mutex_unlock(&g_klock);
}

// ------------------------------------------------------------------ address arbiter
enum { ARB_WAIT_LESS = 0, ARB_DEC_WAIT_LESS = 1, ARB_WAIT_EQ = 2 };
enum { ARB_SIGNAL = 0, ARB_SIGNAL_INC_EQ = 1, ARB_SIGNAL_MOD_EQ = 2 };

static uint32_t svc_wait_for_address(uint64_t addr, uint32_t type, int32_t value, int64_t timeout) {
    pthread_mutex_lock(&g_klock);
    int32_t cur = (int32_t)__atomic_load_n(u32p(addr), __ATOMIC_SEQ_CST);
    bool wait;
    if (type == ARB_WAIT_LESS) wait = cur < value;
    else if (type == ARB_DEC_WAIT_LESS) {
        // [XCDE] one compare-and-swap, as the kernel's exclusive load / store: the game changes this word with its own
        // atomics (LDXR/STXR) outside the kernel lock, and a plain load + store lost those updates (LASRecomp 1144aea)
        for (;;) {
            wait = cur < value;
            if (!wait || __atomic_compare_exchange_n(u32p(addr), (uint32_t *)&cur, (uint32_t)(cur - 1), false, __ATOMIC_SEQ_CST,
                                                     __ATOMIC_SEQ_CST))
                break;
        }
    } else if (type == ARB_WAIT_EQ) wait = cur == value;
    else { pthread_mutex_unlock(&g_klock); return R_INVALID_ENUM; }
    if (!wait) { pthread_mutex_unlock(&g_klock); return R_INVALID_STATE; }
    if (timeout == 0) { pthread_mutex_unlock(&g_klock); return R_TIMEOUT; }
    t_cur->wait_kind = WAIT_ARBITER;
    t_cur->wait_addr = addr;
    uint32_t r = block_current(timeout);
    pthread_mutex_unlock(&g_klock);
    return r;
}

static int arbiter_wake(uint64_t addr, int32_t count) {
    int woken = 0;
    for (KThread *t = g_waitlist; t; t = t->wnext) {
        if (count > 0 && woken >= count) break;
        if (t->wait_kind == WAIT_ARBITER && t->wait_addr == addr) {
            t->wait_kind = WAIT_NONE;
            t->wait_result = R_OK;
            wake(t);
            woken++;
        }
    }
    return woken;
}

static uint32_t svc_signal_to_address(uint64_t addr, uint32_t type, int32_t value, int32_t count) {
    pthread_mutex_lock(&g_klock);
    uint32_t r = R_OK;
    int32_t cur = (int32_t)__atomic_load_n(u32p(addr), __ATOMIC_SEQ_CST);
    if (type == ARB_SIGNAL) {
        arbiter_wake(addr, count);
    } else if (type == ARB_SIGNAL_INC_EQ) {
        // [XCDE] compare-and-swap (see svc_wait_for_address): the word changes under us without the kernel lock
        uint32_t expect = (uint32_t)value;
        if (!__atomic_compare_exchange_n(u32p(addr), &expect, (uint32_t)(value + 1), false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST))
            r = R_INVALID_STATE;
        else arbiter_wake(addr, count);
    } else if (type == ARB_SIGNAL_MOD_EQ) {
        int waiting = 0;
        for (KThread *t = g_waitlist; t; t = t->wnext)
            if (t->wait_kind == WAIT_ARBITER && t->wait_addr == addr) waiting++;
        int32_t nv;
        if (count <= 0) nv = waiting > 0 ? value - 2 : value + 1;
        else nv = waiting == 0 ? value + 1 : (waiting <= count ? value - 1 : value);
        uint32_t expect = (uint32_t)value;
        if (!__atomic_compare_exchange_n(u32p(addr), &expect, (uint32_t)nv, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST))
            r = R_INVALID_STATE;
        else arbiter_wake(addr, count);
    } else {
        r = R_INVALID_ENUM;
    }
    pthread_mutex_unlock(&g_klock);
    return r;
}

// ------------------------------------------------------------------ wait synchronization

static uint32_t svc_wait_synchronization(uint64_t handles_ptr, int32_t count, int64_t timeout, int32_t *index) {
    pthread_mutex_lock(&g_klock);
    struct timespec ts;
    if (timeout > 0) deadline(&ts, timeout);
    KThread *t = t_cur;
    uint32_t *hs = (uint32_t *)(uintptr_t)handles_ptr;
    uint32_t r;
    if (ENV("LARECOMP_VSYNC_BT")) {  // (debug) who waits for the display's vsync event: the game's frame loop
        extern uint32_t vi_vsync_handle(void);
        static int shown;
        for (int i = 0; i < count && shown < 2; i++)
            if (hs[i] && hs[i] == vi_vsync_handle()) {
                shown++;
                LOG("[vsync-bt] wait on vsync (%d handles, timeout %lld) lr %llx:\n", count, (long long)timeout,
                    (unsigned long long)(t ? t->cpu.x[30] : 0));
                plat_print_backtrace();
            }
    }
    for (;;) {
        for (int i = 0; i < count; i++) {
            KObject *o = handle_get(hs[i]);
            if (!o) { r = R_INVALID_HANDLE; goto out; }
            if (o->signaled) { *index = i; r = R_OK; goto out; }
        }
        if (t->cancel) { t->cancel = false; r = R_CANCELLED; goto out; }
        if (unwind_requested()) { r = R_CANCELLED; goto out; }
        if (timeout == 0) { r = R_TIMEOUT; goto out; }
        t->in_sync_wait = true;
        t->snext = g_syncwaiters;
        g_syncwaiters = t;
        bool ok = kwait(timeout < 0 ? -1 : timeout, &ts);
        for (KThread **p = &g_syncwaiters; *p; p = &(*p)->snext)
            if (*p == t) { *p = t->snext; break; }
        t->in_sync_wait = false;
        if (!ok) { r = R_TIMEOUT; goto out; }
    }
out:
    pthread_mutex_unlock(&g_klock);
    return r;
}

// ------------------------------------------------------------------ debug output
static void debug_string(uint64_t p, uint64_t len) {
    fprintf(stderr, "[guest] %.*s", (int)len, (const char *)(uintptr_t)p);
    if (len && ((const char *)(uintptr_t)p)[len - 1] != '\n') fputc('\n', stderr);
}

// ------------------------------------------------------------------ SVC dispatch
static int trace_svc = -1;

static void svc_impl(Cpu *c, uint32_t imm, uint64_t pc);

static _Atomic uint64_t svc_wait_ns[32][0x80], svc_calls[32][0x80];
static int prof_svc = -1;

static void svc_entry(Cpu *c, uint32_t imm, uint64_t pc);
void rt_svc(Cpu *c, uint32_t imm, uint64_t pc) {
    if (diag_usage_on()) diag_use_svc(imm);  // [XCDE] T034
    if (t_cur) { t_cur->last_svc = imm; t_cur->last_lr = c->x[30]; t_cur->last_svc_ns = plat_now_ns(); }  // [XCDE] watchdog
    if (g_det && t_cur) {  // [XCDE] T122: digest of the guest's SVC stream (diag.c logs it per frame: XCDE_DET_DIGEST=1)
        uint64_t v[5] = {t_cur->id, imm, c->x[0], c->x[1], c->x[30]};
        for (int i = 0; i < 5; i++) g_det_digest = (g_det_digest ^ v[i]) * 0x100000001b3ull;
    }
    rt_unwind_point();
    if (g_det && t_cur && ++t_cur->det_svcs >= 4000) {
        t_cur->det_svcs = 0;
        pthread_mutex_lock(&g_klock);
        det_yield(500000);
        pthread_mutex_unlock(&g_klock);
    }
    svc_entry(c, imm, pc);
    rt_unwind_point();
}

static void svc_entry(Cpu *c, uint32_t imm, uint64_t pc) {
    if (prof_svc < 0) prof_svc = ENV("LARECOMP_PROF_SVC") != NULL;
    if (prof_svc && imm < 0x80) {
        uint64_t a0 = c->x[0], a1 = c->x[1], a2 = c->x[2], a3 = c->x[3], lr = c->x[30];
        uint32_t h0 = imm == 0x18 && a2 ? *(uint32_t *)(uintptr_t)a1 : 0;
        uint64_t t0 = plat_now_ns();
        svc_impl(c, imm, pc);
        uint64_t dt = plat_now_ns() - t0;
        static _Atomic int nslow;
        if (((t_cur && t_cur->id == 80 && (imm == 0x18 || imm == 0x34)) || (dt > 10000000 && imm != 0x0b && imm != 0x1c)) && nslow < 20000) {
            nslow++;
            LOG("[slow] t%llu svc%02x %llums a=%llx,%llx,%llx,%llx h0=%x lr=%llx\n", (unsigned long long)(t_cur ? t_cur->id : 0), imm,
                (unsigned long long)(dt / 1000000), (unsigned long long)a0, (unsigned long long)a1, (unsigned long long)a2, (unsigned long long)a3, h0, (unsigned long long)lr);
        }
        unsigned tid = t_cur ? (unsigned)(t_cur->id & 31) : 31;
        svc_wait_ns[tid][imm] += dt;
        svc_calls[tid][imm]++;
        static _Atomic uint64_t last;
        uint64_t now = plat_now_ns();
        if (now - last > 2000000000ull) {
            last = now;
            for (int t = 0; t < 32; t++) {
                int any = 0;
                for (int i = 0; i < 0x80; i++)
                    if (svc_calls[t][i]) {
                        if (!any) { LOG("[svcprof] t%d", t); any = 1; }
                        LOG(" %02x:%llu/%llums", i, (unsigned long long)svc_calls[t][i], (unsigned long long)(svc_wait_ns[t][i] / 1000000));
                        svc_calls[t][i] = 0; svc_wait_ns[t][i] = 0;
                    }
                if (any) LOG("\n");
            }
        }
        return;
    }
    if (trace_svc < 0) trace_svc = getenv("LARECOMP_TRACE_SVC") != NULL;
    {   // [XCDE] T240 XCDE_TRACE_TIMEOUT=<from>:<to> (presented frames): the waits that ended on their timeout (a render
        // thread that stopped waiting for its game thread on a heavy frame draws the scene state it already had)
        static long tf = -1, tt;
        if (tf < 0) { tf = 0; if (!getenv("XCDE_TRACE_TIMEOUT") || sscanf(getenv("XCDE_TRACE_TIMEOUT"), "%ld:%ld", &tf, &tt) != 2) tf = tt = 0; }
        if (tt && (imm == 0x18 || imm == 0x1C || imm == 0x34)) {
            extern uint64_t renderer_present_count(void);
            uint64_t in[4] = {c->x[0], c->x[1], c->x[2], c->x[3]};
            svc_impl(c, imm, pc);
            long f = (long)renderer_present_count();
            if ((uint32_t)c->x[0] == R_TIMEOUT && f >= tf && f <= tt && (imm == 0x18 ? (int64_t)in[3] : (int64_t)in[3]) != 0)
                LOG("[timeout] frame %ld: t%llu svc %02x timeout %lld ns lr %llx (args %llx %llx %llx)\n", f, (unsigned long long)(t_cur ? t_cur->id : 0), imm,
                    (long long)in[3], (unsigned long long)c->x[30], (unsigned long long)in[0], (unsigned long long)in[1], (unsigned long long)in[2]);
            return;
        }
    }
    if (!trace_svc) return svc_impl(c, imm, pc);
    uint64_t in[4] = {c->x[0], c->x[1], c->x[2], c->x[3]};
    svc_impl(c, imm, pc);
    LOG("[svc] t%llu %02x(%llx, %llx, %llx, %llx) -> %llx %llx %llx  @%llx lr=%llx\n", (unsigned long long)(t_cur ? t_cur->id : 0), imm,
        (unsigned long long)in[0], (unsigned long long)in[1], (unsigned long long)in[2], (unsigned long long)in[3],
        (unsigned long long)c->x[0], (unsigned long long)c->x[1], (unsigned long long)c->x[2],
        (unsigned long long)pc, (unsigned long long)c->x[30]);  // [XCDE] LINUX-003: LP64 format types; caller (lr) in trace
}

static void svc_impl(Cpu *c, uint32_t imm, uint64_t pc) {
    uint64_t *x = c->x;
    switch (imm) {
    case 0x01: {  // SetHeapSize
        uint64_t size = x[1];
        if (size > HEAP_MAX) { x[0] = R_OUT_OF_RESOURCE; break; }
#if defined(__linux__) && defined(XCDE_LINUX_RADV_HEAP)
        // [XCDE] LINUX-070: choose backing before publishing the first heap.
        // The guest starts before the UI's Vulkan device is ready; a later
        // remap at first draw would discard data the guest has already written.
        extern void backend_guest_heap_prepare(uint64_t size);
        backend_guest_heap_prepare(size);
#endif
        heap_size = size;
        diag_use("mem", "SetHeapSize 0x%llx", (unsigned long long)size);
        region_remove(HEAP_BASE);
        if (size) region_add(HEAP_BASE, size, 5, 3);
        x[0] = R_OK;
        x[1] = HEAP_BASE;
        break;
    }
    case 0x02: case 0x03: x[0] = R_OK; break;  // SetMemoryPermission / SetMemoryAttribute
    case 0x04:  // MapMemory(dst, src, size): src is inaccessible while mapped, so copying is equivalent
        memcpy((void *)x[0], (void *)x[1], x[2]);
        region_add(x[0], x[2], 0xB, 3);
        x[0] = R_OK;
        break;
    case 0x05:  // UnmapMemory(dst, src, size): copy back
        memcpy((void *)x[1], (void *)x[0], x[2]);
        region_remove(x[0]);
        x[0] = R_OK;
        break;
    case 0x06:  // QueryMemory(out_info, _, addr)
        query_memory(x[2], x[0]);
        x[0] = R_OK;
        x[1] = 0;
        break;
    case 0x07: LOG("ExitProcess\n"); exit(0);
    case 0x08: {  // CreateThread(_, entry, arg, stack_top, prio, core)
        KThread *t = thread_new(x[1], x[2], x[3], (int)x[4], (int)(int32_t)x[5]);
        t->handle = kernel_new_handle(&t->obj);
        LOG("[kernel] CreateThread entry=%llx stack=%llx prio=%d -> %x\n", x[1], x[3], (int)x[4], t->handle);
        x[0] = R_OK;
        x[1] = t->handle;
        break;
    }
    case 0x09: {  // StartThread
        KObject *o = handle_get((uint32_t)x[0]);
        if (!o || o->type != KOBJ_THREAD) { x[0] = R_INVALID_HANDLE; break; }
        thread_start((KThread *)o);
        x[0] = R_OK;
        break;
    }
    case 0x0A: longjmp(t_cur->unwind, 1);  // ExitThread: back to thread_main, which signals the thread object
    case 0x0B: {  // SleepThread (in slices of at most 50 ms: a reboot doesn't wait out a long sleep)
        int64_t ns = (int64_t)x[0];
        if (g_det) {
            pthread_mutex_lock(&g_klock);
            if (ns <= 0) det_yield(20000);
            else {
                uint64_t end = kernel_vnow(0) + (uint64_t)ns;
                while (!unwind_requested() && kernel_vnow(0) < end) det_block((int64_t)end);
            }
            pthread_mutex_unlock(&g_klock);
            break;
        }
        if (ns <= 0) { sched_yield(); break; }
        for (uint64_t end = plat_now_ns() + (uint64_t)ns, now; !unwind_requested() && (now = plat_now_ns()) < end;) {
            uint64_t d = end - now < 50000000 ? end - now : 50000000;
            struct timespec ts = {(time_t)(d / 1000000000), (long)(d % 1000000000)};
            nanosleep(&ts, NULL);
            g_blocked_ns += plat_now_ns() - now;
        }
        break;
    }
    case 0x0C: {  // GetThreadPriority(_, handle)
        KObject *o = handle_get((uint32_t)x[1]);
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        x[1] = o ? (uint64_t)((KThread *)o)->prio : 0;
        break;
    }
    case 0x0D: {  // SetThreadPriority
        KObject *o = handle_get((uint32_t)x[0]);
        if (o) ((KThread *)o)->prio = (int)x[1];
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        break;
    }
    case 0x0E: {  // GetThreadCoreMask(_, _, handle)
        KObject *o = handle_get((uint32_t)x[2]);
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        x[1] = o ? (uint64_t)((KThread *)o)->core : 0;
        x[2] = 0xF;
        break;
    }
    case 0x0F: x[0] = R_OK; break;  // SetThreadCoreMask
    case 0x10: x[0] = t_cur->core; break;  // GetCurrentProcessorNumber
    case 0x11: case 0x12: case 0x17: {  // SignalEvent / ClearEvent / ResetSignal
        pthread_mutex_lock(&g_klock);
        KObject *o = handle_get((uint32_t)x[0]);
        if (!o) x[0] = R_INVALID_HANDLE;
        else {
            KObject *ev = o->type == KOBJ_EVENT ? o : NULL;
            if (!ev) x[0] = R_INVALID_HANDLE;
            else {
                if (imm == 0x11) kernel_signal(ev);
                else if (imm == 0x17 && !ev->signaled) { x[0] = R_INVALID_STATE; pthread_mutex_unlock(&g_klock); break; }
                else ev->signaled = false;
                x[0] = R_OK;
            }
        }
        pthread_mutex_unlock(&g_klock);
        break;
    }
    case 0x13: {  // MapSharedMemory(handle, addr, size, perm)
        KObject *o = handle_get((uint32_t)x[0]);
        if (!o || o->type != KOBJ_SHMEM) { x[0] = R_INVALID_HANDLE; break; }
        KSharedMem *s = (KSharedMem *)o;
        memset((void *)x[1], 0, x[2]);
        s->guest_addr = x[1];  // HLE services write straight into the guest's mapping
        region_add(x[1], x[2], 6, 3);
        if (s->on_map) s->on_map(s);
        x[0] = R_OK;
        break;
    }
    case 0x14: region_remove(x[1]); x[0] = R_OK; break;  // UnmapSharedMemory
    case 0x15: {  // CreateTransferMemory(_, addr, size, perm)
        KTransferMem *t = calloc(1, sizeof *t);
        t->obj.type = KOBJ_TMEM;
        t->addr = x[1];
        t->size = x[2];
        x[0] = R_OK;
        x[1] = kernel_new_handle(&t->obj);
        break;
    }
    case 0x16:  // CloseHandle
        pthread_mutex_lock(&g_klock);
        handle_close((uint32_t)x[0]);
        pthread_mutex_unlock(&g_klock);
        x[0] = R_OK;
        break;
    case 0x18: {  // WaitSynchronization(_, handles, count, timeout)
        int32_t idx = -1;
        x[0] = svc_wait_synchronization(x[1], (int32_t)x[2], (int64_t)x[3], &idx);
        x[1] = (uint32_t)idx;
        break;
    }
    case 0x19: {  // CancelSynchronization
        pthread_mutex_lock(&g_klock);
        KObject *o = handle_get((uint32_t)x[0]);
        if (o && o->type == KOBJ_THREAD) {
            ((KThread *)o)->cancel = true;
            wake((KThread *)o);
            x[0] = R_OK;
        } else x[0] = R_INVALID_HANDLE;
        pthread_mutex_unlock(&g_klock);
        break;
    }
    case 0x1A: x[0] = svc_arbitrate_lock((uint32_t)x[0], x[1], (uint32_t)x[2]); break;
    case 0x1B: x[0] = svc_arbitrate_unlock(x[0]); break;
    case 0x1C: x[0] = svc_wait_process_wide_key(x[0], x[1], (uint32_t)x[2], (int64_t)x[3]); break;
    case 0x1D: svc_signal_process_wide_key(x[0], (int32_t)x[1]); x[0] = R_OK; break;
    case 0x1E: x[0] = rt_ticks(); break;
    case 0x1F: {  // ConnectToNamedPort(_, name)
        uint32_t h = ipc_connect_named_port((const char *)(uintptr_t)x[1]);
        x[0] = h ? R_OK : R_NOT_FOUND;
        x[1] = h;
        break;
    }
    case 0x21: x[0] = ipc_handle_request(c, (uint32_t)x[0]); break;  // SendSyncRequest
    case 0x22: {  // SendSyncRequestWithUserBuffer(buf, size, handle)
        uint64_t saved = c->tpidrro;
        c->tpidrro = x[0];
        x[0] = ipc_handle_request(c, (uint32_t)x[2]);
        c->tpidrro = saved;
        break;
    }
    case 0x24: x[0] = R_OK; x[1] = 0x81; break;  // GetProcessId
    case 0x25: {  // GetThreadId(_, handle)
        KObject *o = handle_get((uint32_t)x[1]);
        x[0] = o ? R_OK : R_INVALID_HANDLE;
        x[1] = o ? ((KThread *)o)->id : 0;
        break;
    }
    case 0x26:  // Break
        if (x[0] & 0x80000000u) { LOG("[kernel] Break notification %llx\n", x[0]); x[0] = R_OK; break; }
        FATAL("svcBreak(reason=%llx, info=%llx, size=%llx) at %llx\n", x[0], x[1], x[2], pc);
    case 0x27: debug_string(x[0], x[1]); x[0] = R_OK; break;
    case 0x29: {  // GetInfo(_, id0, handle, id1)
        uint32_t id0 = (uint32_t)x[1];
        uint64_t v = 0;
        uint32_t r = R_OK;
        switch (id0) {
        case 0: v = 0xF; break;
        case 1: v = 0xFFFFFFFFFFFFFFFFull; break;
        case 2: v = ALIAS_BASE; break;
        case 3: v = ALIAS_SIZE; break;
        case 4: v = HEAP_BASE; break;
        case 5: v = HEAP_MAX; break;
        case 6: case 21: v = 0xCD500000ull; break;  // application memory (3.2 GB, as on hardware)
        case 7: case 22: v = heap_size + 0x4000000; break;
        case 8: v = 0; break;
        case 9: v = 0; break;
        case 11: v = diag_random64(); break;
        case 12: v = GUEST_LO; break;
        case 13: v = GUEST_HI - GUEST_LO; break;
        case 14: v = STACK_BASE; break;
        case 15: v = STACK_SIZE; break;
        case 16: case 17: v = 0; break;
        case 18: v = 0x01006BB00C6F0000ull; break;
        case 20: v = 0; break;
        default: r = R_INVALID_ENUM; LOG("[kernel] GetInfo unknown id %u/%llu\n", id0, x[3]);
        }
        x[0] = r;
        x[1] = v;
        break;
    }
    case 0x2C:  // MapPhysicalMemory(addr, size)
        memset((void *)x[0], 0, x[1]);
        region_add(x[0], x[1], 0x7, 3);
        x[0] = R_OK;
        break;
    case 0x2D:  // UnmapPhysicalMemory
        region_remove(x[0]);
        x[0] = R_OK;
        break;
    case 0x34: x[0] = svc_wait_for_address(x[0], (uint32_t)x[1], (int32_t)x[2], (int64_t)x[3]); break;
    case 0x35: x[0] = svc_signal_to_address(x[0], (uint32_t)x[1], (int32_t)x[2], (int32_t)x[3]); break;
    case 0x45: {  // CreateEvent -> w1 writable, w2 readable
        KObject *ev = calloc(1, sizeof *ev);
        ev->type = KOBJ_EVENT;
        x[0] = R_OK;
        x[1] = kernel_new_handle(ev);
        x[2] = kernel_new_handle(ev);
        if (ENV("LARECOMP_PROF_SVC")) LOG("[evt] guest w=%llx r=%llx lr=%llx\n", (unsigned long long)x[1], (unsigned long long)x[2], (unsigned long long)x[30]);
        break;
    }
    default:
        diag_hle_hit("svc", "unimplemented");
        FATAL("unimplemented svc 0x%x at %llx (x0=%llx x1=%llx x2=%llx)\n", imm, pc, x[0], x[1], x[2]);
    }
}

// Reboot, step 1: stop every guest thread (see rt_unwind_point) and join it. `idle` keeps the window responsive.
void kernel_stop_threads(void (*idle)(void)) {
    __atomic_store_n(&g_rt_unwind, 1, __ATOMIC_RELEASE);
    uint64_t t0 = plat_now_ns(), logged = t0;
    for (;;) {
        int live = 0;
        pthread_mutex_lock(&g_klock);
        for (KThread *t = g_threads; t; t = t->anext)
            if (t->started && !t->finished) { live++; wake(t); }
        // [XCDE] LINUX-003: with every deterministic worker blocked, wake only
        // makes it runnable. Grant the free baton so it can observe stop/unwind.
        // Never take the baton away from a currently executing worker.
        if (live && g_det && !g_baton) det_dispatch();
        pthread_cond_broadcast(&g_nothread_cond);
        pthread_mutex_unlock(&g_klock);
        if (!live) break;
        uint64_t now = plat_now_ns();
        if (now - logged > 3000000000ull) {  // (a thread that never reaches a safe point: who and where)
            logged = now;
            LOG("[reboot] still waiting for %d guest threads after %llums:\n", live, (unsigned long long)((now - t0) / 1000000));
            for (KThread *t = g_threads; t; t = t->anext)
                if (t->started && !t->finished)
                    LOG("[reboot]   thread %llu (entry %llx) pc %llx lr %llx wait %d sync %d\n", (unsigned long long)t->id,
                        (unsigned long long)t->entry, (unsigned long long)t->cpu.pc, (unsigned long long)t->cpu.x[30],
                        t->wait_kind, t->in_sync_wait);
        }
        if (idle) idle();
        usleep(2000);
    }
    int n = 0;
    for (KThread *t = g_threads; t; t = t->anext)
        if (t->started) { pthread_join(t->host, NULL); n++; }
#if defined(__linux__) && defined(__x86_64__)
    // All native roots have been cleaned up and joined; suspended/abandoned
    // contexts may now be unmapped before guest memory is reset for reboot.
    size_t fibers = fibers_reset();
    LOG("[reboot] reclaimed %zu Linux fibers\n", fibers);
#endif
    LOG("[reboot] %d guest threads stopped in %llums\n", n, (unsigned long long)((plat_now_ns() - t0) / 1000000));
}

// Reboot, step 2 (threads stopped): a fresh kernel. Kernel objects are leaked rather than freed: host statics
// can still point at some (vi.c's vsync event, signalled by its host timer thread).
void kernel_reset(void) {
    pthread_mutex_lock(&g_klock);
    for (KThread *t = g_threads, *next; t; t = next) {
        next = t->anext;
        pthread_cond_destroy(&t->cond);
        free(t);
    }
    g_threads = NULL;
    g_waitlist = NULL;
    g_syncwaiters = NULL;
    memset(handles, 0, sizeof handles);
    nregions = 0;
    heap_size = 0;
    tls_next = TLS_BASE;
    next_thread_id = 0x50;
    __atomic_store_n(&g_rt_unwind, 0, __ATOMIC_RELEASE);
    pthread_mutex_unlock(&g_klock);
}

void kernel_init(void) {
    g_det = diag_deterministic();  // [XCDE] T029
    // Reserve the heap, alias, stack, and TLS regions.
    region_add(TLS_BASE, TLS_SIZE, 0xC, 3);
    for (int i = 0; i < g_nmodules; i++) {
        Module *m = &g_modules[i];
        region_add(m->base + m->text_off, m->ro_off - m->text_off, 3, 5);
        region_add(m->base + m->ro_off, m->data_off - m->ro_off, 3, 1);
        region_add(m->base + m->data_off, m->size - m->data_off, 4, 3);
    }
}

KEvent *kernel_create_event_pair(uint32_t *w, uint32_t *r) {
    KObject *ev = calloc(1, sizeof *ev);
    ev->type = KOBJ_EVENT;
    *w = kernel_new_handle(ev);
    *r = kernel_new_handle(ev);
    if (ENV("LARECOMP_PROF_SVC")) { const char *s = plat_symbol((uint64_t)(uintptr_t)__builtin_return_address(0), NULL); LOG("[evt] hle w=%x r=%x from %s\n", *w, *r, s ? s : "?"); }
    return ev;
}

KSharedMem *kernel_create_shared_memory(uint64_t size, void (*on_map)(KSharedMem *), uint32_t *handle) {
    KSharedMem *s = calloc(1, sizeof *s);
    s->obj.type = KOBJ_SHMEM;
    s->size = size;
    s->on_map = on_map;
    *handle = kernel_new_handle(&s->obj);
    return s;
}

// [XCDE] Watchdog support (T027): one line per thread of this boot, with the guest function that made its last SVC, the owner
// of the mutex it waits on and a note for the classic deadlocks (a thread waiting on a mutex it owns itself, or two threads
// waiting on each other's).
static KThread *thread_by_handle(uint32_t h) {
    for (KThread *t = g_threads; t; t = t->anext) if (t->handle == h) return t;
    return NULL;
}

const char *(*kernel_sym_hook)(uint64_t pc, uint64_t *offset);  // dispatch.c: names host frames in thread dumps
void kernel_dump_threads(FILE *out) {
    uint64_t now = plat_now_ns();
    // Bound lock acquisition: Linux reports unavailable details if the kernel is
    // stuck; the inherited Windows path retains its best-effort unlocked dump.
    bool locked = false;
    for (int i = 0; i < 20 && !(locked = pthread_mutex_trylock(&g_klock) == 0); i++) plat_sleep_until_ns(plat_now_ns() + 50000000ull);
    if (!locked) {
#ifdef __linux__
        // [XCDE] LINUX-003: reset frees this list under g_klock. An unlocked
        // diagnostic walk can race it and dereference freed threads/guest memory.
        // Preserve bounded reporting, but explicitly report unavailable data.
        fprintf(out, "[wd] WARNING g_klock is held; thread details unavailable without a safe snapshot\n");
        return;
#else
        fprintf(out, "[wd] WARNING g_klock is held by someone (dumping without it)\n");
#endif
    }
    int nthreads = 0, nwait = 0;
    fprintf(out, "[wd] anchor kernel_dump_threads=%p (host frames: nm on the running executable)\n", (void *)kernel_dump_threads);
    for (KThread *t = g_threads; t; t = t->anext) {
        nthreads++;
        const char *w = t->finished ? "finished" : t->wait_kind == WAIT_MUTEX ? "mutex" : t->wait_kind == WAIT_CONDVAR ? "condvar"
                       : t->wait_kind == WAIT_ARBITER ? "arbiter" : t->in_sync_wait ? "syncwait" : "running";
        nwait += t->wait_kind != WAIT_NONE || t->in_sync_wait;
        uint32_t mval = ((t->wait_kind == WAIT_MUTEX || t->last_svc == 0x1a) && t->wait_addr) ? *(volatile uint32_t *)(uintptr_t)t->wait_addr : 0;
        uint64_t off = 0;
        const char *sym = t->last_lr ? loader_symbol_at(t->last_lr, &off) : NULL;
        fprintf(out, "[wd] thread %llu h=%x prio %d entry %llx: %s%s wait_addr=%llx[%x] last_svc=%02x lr=%llx%s%s (%llu ms ago)\n",
                (unsigned long long)t->id, t->handle, t->prio, (unsigned long long)t->entry, w,
                !g_det ? "" : t->det_state == 1 ? " [det:runnable]" : t->det_state == 2 ? " [det:BATON]" : t->det_state == 3 ? " [det:blocked]" : " [det:-]",
                (unsigned long long)t->wait_addr, mval,
                t->last_svc, (unsigned long long)t->last_lr, sym ? " in " : "", sym ? sym : "",
                t->last_svc_ns ? (unsigned long long)((now - t->last_svc_ns) / 1000000) : 0ull);
        // [XCDE] T122: a thread running with no SVC for over a second: where its host thread is (spin loops)
        if (!t->finished && t->wait_kind == WAIT_NONE && !t->in_sync_wait && t->last_svc_ns && now - t->last_svc_ns > 1000000000ull) {
            uint64_t pcs[32];
            int n = plat_thread_backtrace(&t->host, pcs, 32);
            for (int k = 0; k < n; k++) {
                uint64_t off = 0;
                const char *s = kernel_sym_hook ? kernel_sym_hook(pcs[k], &off) : NULL;
                fprintf(out, "[wd]   #%d %llx %s+%llx\n", k, (unsigned long long)pcs[k], s ? s : "?", (unsigned long long)off);
            }
        }
        if (t->wait_kind == WAIT_MUTEX && mval) {
            uint32_t owner = mval & ~WAITERS_BIT;
            KThread *o = thread_by_handle(owner);
            fprintf(out, "[wd]   mutex %llx owner h=%x%s%s\n", (unsigned long long)t->wait_addr, owner, o ? "" : " (no such thread)",
                    o && o != t && (o->wait_kind == WAIT_MUTEX) ? " (itself waiting on a mutex)" : "");
            if (owner == t->handle) fprintf(out, "[wd]   DEADLOCK: this thread waits on a mutex it owns\n");
            else if (o && o->wait_kind == WAIT_MUTEX) {
                uint32_t mv2 = o->wait_addr ? *(volatile uint32_t *)(uintptr_t)o->wait_addr : 0;
                if ((mv2 & ~WAITERS_BIT) == t->handle) fprintf(out, "[wd]   DEADLOCK: h=%x and h=%x wait on each other's mutex\n", t->handle, owner);
            }
        }
    }
    fprintf(out, "[wd] %d threads, %d blocked in the kernel\n", nthreads, nwait);
    if (locked) pthread_mutex_unlock(&g_klock);
}
