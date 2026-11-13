// [XCDE] Party mod: Xenoblade 3-style switching of the controlled character (docs/plan_party_switch.md,
// docs/party_switch_research.md). The game's own leader change, as its Party menu does it on closing: the live party
// list (u16 character ids, leader first; u32 count at +0x18) is reordered and the party manager's set-leader routine
// rebuilds the player's control (pad, camera, action handlers) on the new leader; the old one becomes a follower.
//   f_70000b6790(party manager)    -> the live party list (game data + 0x1545e0)
//   f_70004c5710(party manager, id) set the leader (the Party menu's call: f_7000541e10+0x1672)
//   party manager = the unique object of class vtable 0x7000b35210, + 0x20
// Runs on the game's main thread from the pad read (runtime/hle/input.c fill_state), between the game's own updates.
// XCDE_PARTY_SWITCH_AT=<frame>[,<frame>...]: switch to the next member at those presented frames (tests).
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <fenv.h>

#include "../rt.h"
#include "../cpu.h"
#include "../diag/diag.h"
#include "../platform.h"
#include "../settings.h"
#include "../hle.h"

#ifdef __linux__
#include <errno.h>
#include <sys/mman.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>
#include "../kernel.h"
#endif

#ifdef _WIN32
#include <windows.h>
#endif

#define PARTY_LIST_FN 0x70000b6790ull
#define SET_LEADER_FN 0x70004c5710ull
#define FOCUS_FN 0x70000507e0ull       // (party manager, entity handle): the Party menu calls it just before

static _Atomic int g_switch_req;  // members to advance (set from the input thread: a key / button)

// From the keys / pad (runtime/hle/input.c): only with the option on (launcher: Controls, xcde.ini party_switch = 1)
void party_switch_request(int step) {
    extern bool g_party_switch;
    if (g_party_switch) g_switch_req = step ? step : 1;
}

// The guest-heap objects the switch needs, found by class (vtable) with a scan of the whole heap (~0.3 s). The scan runs
// on a thread of its own (party_scanner) ahead of time and again whenever an object is gone or a battle starts: a scan
// on the game's thread is a visible hitch (measured 0.17 - 0.6 s on the first switches). The game's thread only reads
// the result and checks each object's vtable before using it.
#define FIELD_VTABLE 0x7000b35210ull   // the object holding the party manager at +0x20
// The HUD (field and battle: portraits, arts palette): it shows the character whose entity handle is at +0x2d0 (its
// sub-object at +0x2c0: party manager, ?, u32 handle) - set at the battle's start to the leader's, so a switch must
// move it too.
#define HUD_VTABLE 0x7000b63248ull
// The player object (one, vtable 0x7000b3c740): +0xc 1.0 and +0x10 0 while the player has control (field and battle);
// the main menu sets them to 0 / 1.
#define PLAYER_VTABLE 0x7000b3c740ull
// Battle HP gauges (one per character in the battle - party and enemies): -0x38 the entity handle, -0x10 the current HP.
#define GAUGE_VTABLE 0x7000b44b08ull

// The battle arts palette: +0x1c8 the selected slot, left to right (0-3 the left arts, 4 the talent art, 5-8 the right)
#define PALETTE_VTABLE 0x7000b4ac68ull
// [XCDE] T236: the player camera: +0x1f0 / +0x1f4 the yaw, +0x1f8 / +0x1fc the pitch (radians; the right stick turns
// them, the game rebuilds the view from them each frame and clamps the pitch to about -0.99 .. 1.19). Found with
// XCDE_FLOATFIND (colony9 field: the right stick held right 20 frames then left 10 -> exactly -0.5 of the turn back);
// writing +0x1f0 turns the camera that much the next frame.
#define CAMERA_VTABLE 0x7000b381f0ull
// [XCDE] T240: the map jump manager's holder (f_7000542870 reads +0x58 from it; found by its vtable with
// LARECOMP_FNPROF_BT=7000542870 while a save loads)
#define WARP_VTABLE 0x7000b654a0ull

enum { K_FIELD, K_HUD, K_PLAYER, K_GAUGE, K_PAL, K_CAM, K_WARP, K_N };
static const uint64_t k_vtables[K_N] = {FIELD_VTABLE, HUD_VTABLE, PLAYER_VTABLE, GAUGE_VTABLE, PALETTE_VTABLE, CAMERA_VTABLE, WARP_VTABLE};
#define SET_MAX 32
typedef struct { uint64_t obj[K_N][SET_MAX]; int n[K_N]; } Found;

static Found g_found;               // the last scan (under g_found_lock)
static _Atomic bool g_cam_used;    // (the direct mouse camera asked for the camera object)
static _Atomic bool g_warp_used;   // (XCDE_WARP: the map jump manager)
static _Atomic int g_rescan;       // the game's thread asks the scanner for a new scan
static _Atomic uint64_t g_party_epoch;
static void party_actions_reset(void);
#ifdef _WIN32
static SRWLOCK g_found_lock = SRWLOCK_INIT;
#endif

#ifdef __linux__
// [XCDE] LINUX-055 R2: only our currently declared guest heap is eligible.
// Self process_vm_readv reports unreadable/racing protection instead of faulting
// the input thread or worker. No foreign process or arbitrary host address read.
static bool party_range(uint64_t address, size_t bytes) {
    uint64_t size = kernel_heap_size();
    return size && size <= HEAP_MAX && address >= HEAP_BASE &&
           address - HEAP_BASE < size && bytes <= size - (address - HEAP_BASE);
}
static bool party_read(uint64_t address, void *out, size_t bytes) {
    if (!bytes || !party_range(address, bytes)) return false;
    struct iovec local = {out, bytes}, remote = {(void *)(uintptr_t)address, bytes};
    ssize_t got = process_vm_readv(getpid(), &local, 1, &remote, 1, 0);
    if (got >= 0 && got != (ssize_t)bytes) errno = EFAULT;
    return got == (ssize_t)bytes;
}
// Pointers returned by the original native party functions may name writable
// module data or an alias as well as the heap. Keep discovery heap-only, but
// validate these typed native returns against the complete claimed guest window.
static bool party_native_read(uint64_t address, void *out, size_t bytes) {
    if (!bytes || address < GUEST_LO || address >= GUEST_HI || bytes > GUEST_HI - address) return false;
    struct iovec local = {out, bytes}, remote = {(void *)(uintptr_t)address, bytes};
    ssize_t got = process_vm_readv(getpid(), &local, 1, &remote, 1, 0);
    if (got >= 0 && got != (ssize_t)bytes) errno = EFAULT;
    return got == (ssize_t)bytes;
}
static bool party_writable(uint64_t address, size_t bytes) {
    if (!bytes || address < GUEST_LO || address >= GUEST_HI || bytes > GUEST_HI - address) return false;
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return false;
    char line[1024];
    uint64_t cursor = address, end = address + bytes;
    size_t budget = 0;
    while (budget < 131072 && fgets(line, sizeof line, maps)) {
        budget += strlen(line);
        unsigned long long lo, hi; char permissions[5];
        if (sscanf(line, "%llx-%llx %4s", &lo, &hi, permissions) != 3 || hi <= cursor) continue;
        if (lo > cursor || permissions[0] != 'r' || permissions[1] != 'w') break;
        cursor = hi < end ? hi : end;
        if (cursor == end) break;
    }
    fclose(maps);
    return cursor == end;
}
static bool party_group_valid(uint64_t group) {
    uint64_t table;
    if (!party_writable(group, 0x734) || !party_native_read(group, &table, sizeof table)) return false;
    const unsigned offsets[] = {0x18, 0x20, 0x28, 0x40};
    for (unsigned i = 0; i < sizeof offsets / sizeof offsets[0]; ++i) {
        uint64_t address = table + offsets[i], function;
        if (address < table || (!party_writable(address, sizeof function) &&
            !(address >= MAIN_BASE && address <= SDK_BASE - sizeof function))) return false;
        struct iovec local = {&function, sizeof function}, remote = {(void *)(uintptr_t)address, sizeof function};
        if (process_vm_readv(getpid(), &local, 1, &remote, 1, 0) != sizeof function ||
            function < MAIN_BASE || function >= SDK_BASE) return false;
    }
    return true;
}
static pthread_mutex_t g_found_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_scan_cond;
static pthread_once_t g_scan_once = PTHREAD_ONCE_INIT;
static pthread_t g_scan_thread;
static bool g_scan_started, g_scan_failed, g_scan_atexit;
static _Atomic bool g_scan_stop;
static _Atomic unsigned g_scan_failures;
static void scan_failure(const char *operation) {
    if (atomic_fetch_add(&g_scan_failures, 1) < 4)
        LOG("[party] Linux %s could not read an owned heap range; discovery deferred (%s)\n", operation, strerror(errno));
}
static void scan_cond_init(void) {
    pthread_condattr_t attr;
    if (pthread_condattr_init(&attr) || pthread_condattr_setclock(&attr, CLOCK_MONOTONIC) ||
        pthread_cond_init(&g_scan_cond, &attr)) FATAL("[party] cannot initialize Linux scanner condition\n");
    pthread_condattr_destroy(&attr);
}
#endif

static bool obj_ok(uint64_t o, int k) {
#ifdef __linux__
    static const size_t span[K_N] = {0x28, 0x338, 0x1a0, 8, 0x1cc, 0x200, 0x60};
    unsigned char image[0x338], gauge_prefix[0x40];
    uint64_t value;
    if (k < 0 || k >= K_N || !party_read(o, image, span[k]) ||
        (k == K_GAUGE && !party_read(o - 0x38, gauge_prefix, sizeof gauge_prefix))) return false;
    memcpy(&value, image, sizeof value);
    return value == k_vtables[k];
#else
    return o && *(volatile uint64_t *)(uintptr_t)o == k_vtables[k];
#endif
}

#ifdef __linux__
static void scan_words(Found *f, uint64_t address, const uint64_t *words, size_t bytes) {
    for (size_t n = 0; n < bytes / sizeof(uint64_t); ++n) {
        uint64_t value = words[n];
        if (value >> 32 != 0x70) continue;
        for (int k = 0; k < K_N; ++k)
            if (value == k_vtables[k] && f->n[k] < SET_MAX)
                f->obj[k][f->n[k]++] = address + n * sizeof(uint64_t);
    }
}
#endif

static void heap_scan(Found *f) {
    memset(f, 0, sizeof *f);
#ifdef _WIN32
    for (uint64_t a = HEAP_BASE; a < HEAP_BASE + HEAP_MAX;) {
        MEMORY_BASIC_INFORMATION mi;
        if (!VirtualQuery((void *)(uintptr_t)a, &mi, sizeof mi) || !mi.RegionSize) break;
        uint64_t base = (uint64_t)(uintptr_t)mi.BaseAddress, end = base + mi.RegionSize;
        if (mi.State == MEM_COMMIT && (mi.Protect & 0xFF) == PAGE_READWRITE)
            for (const volatile uint64_t *p = (const volatile uint64_t *)(uintptr_t)base; (uint64_t)(uintptr_t)(p + 1) <= end; p++) {
                uint64_t v = *p;
                if ((v >> 32) != 0x70) continue;  // (every vtable is in the game's image at 0x70_0000_0000)
                for (int k = 0; k < K_N; k++)
                    if (v == k_vtables[k] && f->n[k] < SET_MAX) f->obj[k][f->n[k]++] = (uint64_t)(uintptr_t)p;
            }
        a = end;
    }
#elif defined(__linux__)
    uint64_t size = kernel_heap_size();
    long page = sysconf(_SC_PAGESIZE);
    if (!size || size > HEAP_MAX) return;
    if (page < 4096 || page > 65536 || (0x100000 % page)) { errno = EINVAL; scan_failure("page size"); return; }
    uint64_t words[8192];
    unsigned char resident[256];
    // Residency avoids faulting in the untouched MAP_NORESERVE window merely
    // to search it. Both mincore and reads are bounded, and shutdown interrupts
    // the scan between blocks/runs rather than waiting for the entire heap.
    for (uint64_t block = 0; block < size && !atomic_load(&g_scan_stop); block += 0x100000) {
        size_t bytes = size - block < 0x100000 ? (size_t)(size - block) : 0x100000;
        if (mincore((void *)(uintptr_t)(HEAP_BASE + block), bytes, resident)) { scan_failure("mincore"); continue; }
        size_t pages = (bytes + (size_t)page - 1) / (size_t)page;
        for (size_t i = 0; i < pages && !atomic_load(&g_scan_stop);) {
            if (!(resident[i] & 1)) { ++i; continue; }
            size_t first = i++;
            while (i < pages && resident[i] & 1 && (i - first + 1) * (size_t)page <= sizeof words) ++i;
            size_t count = (i - first) * (size_t)page;
            size_t offset = first * (size_t)page;
            if (count > bytes - offset) count = bytes - offset;
            uint64_t address = HEAP_BASE + block + offset;
            if (party_read(address, words, count)) scan_words(f, address, words, count);
            else {
                // A protected page must not hide healthy objects in adjacent
                // resident pages from the same coalesced run.
                scan_failure("read");
                for (size_t off = 0; off < count && !atomic_load(&g_scan_stop); off += (size_t)page) {
                    size_t part = count - off < (size_t)page ? count - off : (size_t)page;
                    if (party_read(address + off, words, part)) scan_words(f, address + off, words, part);
                }
            }
        }
    }
#endif
}

#if defined(_WIN32) || defined(__linux__)
// Everything still there? (a scanned object freed or reused, a battle's gauges not created yet)
static bool found_stale(const Found *f) {
    for (int k = 0; k < K_N; k++)
        for (int i = 0; i < f->n[k]; i++)
            if (!obj_ok(f->obj[k][i], k)) return true;
    for (int k = 0; k < K_GAUGE; k++) if (!f->n[k]) return true;
    if (g_cam_used && !f->n[K_CAM]) return true;
    if (g_warp_used && !f->n[K_WARP]) return true;
    if (f->n[K_GAUGE] && !f->n[K_PAL]) return true;  // (a battle without its palette)
    uint64_t hud = f->obj[K_HUD][0];
    uint64_t battle = 0;
#ifdef __linux__
    if (hud && !party_read(hud + 0x2c0, &battle, sizeof battle)) return true;
#else
    if (hud) battle = *(volatile uint64_t *)(uintptr_t)(hud + 0x2c0);
#endif
    return battle && !f->n[K_GAUGE];  // (a battle without its gauges)
}

#ifdef _WIN32
static DWORD WINAPI party_scanner(LPVOID arg) {
    (void)arg;
    static Found scan;
    for (;;) {
        AcquireSRWLockShared(&g_found_lock);
        bool stale = found_stale(&g_found);
        ReleaseSRWLockShared(&g_found_lock);
        if (stale || g_rescan) {
            g_rescan = 0;
            heap_scan(&scan);
            AcquireSRWLockExclusive(&g_found_lock);
            g_found = scan;
            ReleaseSRWLockExclusive(&g_found_lock);
            // (at most one scan a second; every 4 s while there's no party yet: title screen, loading)
            Sleep(scan.n[K_FIELD] ? 1000 : 4000);
        } else {
            Sleep(250);
        }
    }
    return 0;
}
#else
static void *party_scanner(void *arg) {
    (void)arg;
    plat_thread_name("monado-party");
    plat_thread_background();
    Found scan;
    unsigned summaries = 0;
    int previous[K_N];
    for (int k = 0; k < K_N; ++k) previous[k] = -1;
    while (!atomic_load(&g_scan_stop)) {
        pthread_mutex_lock(&g_found_lock);
        bool stale = found_stale(&g_found);
        pthread_mutex_unlock(&g_found_lock);
        bool requested = atomic_exchange(&g_rescan, 0) != 0;
        unsigned wait_ms = 250;
        if (stale || requested) {
            uint64_t started = plat_now_ns();
            heap_scan(&scan);
            pthread_mutex_lock(&g_found_lock);
            if (!atomic_load(&g_scan_stop)) g_found = scan;
            pthread_mutex_unlock(&g_found_lock);
            if (summaries < 8 && memcmp(previous, scan.n, sizeof previous)) {
                memcpy(previous, scan.n, sizeof previous);
                ++summaries;
                LOG("[party] Linux scan heap=%llu bytes field=%d hud=%d player=%d gauges=%d palette=%d camera=%d warp=%d time=%llu ms\n",
                    (unsigned long long)kernel_heap_size(), scan.n[K_FIELD], scan.n[K_HUD], scan.n[K_PLAYER],
                    scan.n[K_GAUGE], scan.n[K_PAL], scan.n[K_CAM], scan.n[K_WARP],
                    (unsigned long long)((plat_now_ns() - started) / 1000000));
            }
            wait_ms = scan.n[K_FIELD] ? 1000 : 4000;
        }
        struct timespec deadline;
        clock_gettime(CLOCK_MONOTONIC, &deadline);
        deadline.tv_sec += wait_ms / 1000;
        deadline.tv_nsec += (long)(wait_ms % 1000) * 1000000;
        if (deadline.tv_nsec >= 1000000000) { deadline.tv_nsec -= 1000000000; ++deadline.tv_sec; }
        pthread_mutex_lock(&g_found_lock);
        if (!atomic_load(&g_scan_stop) && !atomic_load(&g_rescan))
            pthread_cond_timedwait(&g_scan_cond, &g_found_lock, &deadline);
        pthread_mutex_unlock(&g_found_lock);
    }
    return NULL;
}
static void party_scanner_shutdown(void) {
    pthread_mutex_lock(&g_found_lock);
    bool join = g_scan_started;
    atomic_store(&g_scan_stop, true);
    if (join) pthread_cond_broadcast(&g_scan_cond);
    pthread_mutex_unlock(&g_found_lock);
    if (join) pthread_join(g_scan_thread, NULL);
    pthread_mutex_lock(&g_found_lock);
    g_scan_started = g_scan_failed = false;
    memset(&g_found, 0, sizeof g_found);
    pthread_mutex_unlock(&g_found_lock);
    g_switch_req = g_rescan = 0;
    g_cam_used = g_warp_used = false;
    party_actions_reset();
}
static void party_scanner_start(void) {
    pthread_once(&g_scan_once, scan_cond_init);
    pthread_mutex_lock(&g_found_lock);
    if (!g_scan_started && !g_scan_failed) {
        atomic_store(&g_scan_stop, false);
        int error = pthread_create(&g_scan_thread, NULL, party_scanner, NULL);
        if (error) { g_scan_failed = true; LOG("[party] cannot start Linux discovery worker: %s\n", strerror(error)); }
        else {
            g_scan_started = true;
            if (!g_scan_atexit) {
                if (atexit(party_scanner_shutdown)) FATAL("[party] cannot register Linux scanner shutdown\n");
                g_scan_atexit = true;
            }
        }
    }
    pthread_mutex_unlock(&g_found_lock);
}
RT_ON_RESET(party_linux_reset) { party_scanner_shutdown(); }
#endif
#endif

// The game's thread: a copy of the last scan (a few hundred bytes)
static void found_get(Found *f) {
#ifdef _WIN32
    AcquireSRWLockShared(&g_found_lock);
    *f = g_found;
    ReleaseSRWLockShared(&g_found_lock);
#elif defined(__linux__)
    pthread_mutex_lock(&g_found_lock);
    *f = g_found;
    pthread_mutex_unlock(&g_found_lock);
#else
    memset(f, 0, sizeof *f);
#endif
}
static uint64_t found_one(const Found *f, int k) {
    for (int i = 0; i < f->n[k]; i++) if (obj_ok(f->obj[k][i], k)) return f->obj[k][i];
    g_rescan = 1;
#ifdef __linux__
    pthread_mutex_lock(&g_found_lock);
    if (g_scan_started) pthread_cond_signal(&g_scan_cond);
    pthread_mutex_unlock(&g_found_lock);
#endif
    return 0;
}
// -1: no gauge for that entity (not in a battle, or not scanned yet)
static int64_t battle_hp(const Found *f, uint32_t handle) {
    for (int i = 0; i < f->n[K_GAUGE]; i++) {
        uint64_t o = f->obj[K_GAUGE][i];
#ifdef __linux__
        uint32_t owner, hp;
        if (obj_ok(o, K_GAUGE) && party_read(o - 0x38, &owner, sizeof owner) && owner == handle &&
            party_read(o - 0x10, &hp, sizeof hp)) return hp;
#else
        if (obj_ok(o, K_GAUGE) && *(volatile uint32_t *)(uintptr_t)(o - 0x38) == handle) return *(volatile uint32_t *)(uintptr_t)(o - 0x10);
#endif
    }
    return -1;
}

// A guest function called from the host on the game's thread: every register restored afterwards (the caller is an
// HLE import, so the game only expects what the import itself returns).
static uint64_t call_guest(Cpu *c, uint64_t fn, uint64_t x0, uint64_t x1) {
    Cpu saved = *c;
#ifdef __linux__
    uint64_t fpcr = rt_get_fpcr(), fpsr = rt_get_fpsr();
    fenv_t environment;
    if (fegetenv(&environment)) FATAL("[party] cannot save host FP environment\n");
#endif
    c->x[0] = x0;
    c->x[1] = x1;
    c->sp = (c->sp - 0x400) & ~15ull;  // (room below whatever the caller has on the stack)
    guest_call(c, fn);
    uint64_t r = c->x[0];
    *c = saved;
#ifdef __linux__
    if (fesetenv(&environment)) FATAL("[party] cannot restore host FP environment\n");
    rt_set_fpcr(fpcr); rt_set_fpsr(fpsr);
#endif
    return r;
}
static uint64_t call_guest3(Cpu *c, uint64_t fn, uint64_t x0, uint64_t x1, uint64_t x2) {
    Cpu saved = *c;
#ifdef __linux__
    uint64_t fpcr = rt_get_fpcr(), fpsr = rt_get_fpsr();
    fenv_t environment;
    if (fegetenv(&environment)) FATAL("[party] cannot save host FP environment\n");
#endif
    c->x[0] = x0;
    c->x[1] = x1;
    c->x[2] = x2;
    c->sp = (c->sp - 0x400) & ~15ull;
    guest_call(c, fn);
    uint64_t r = c->x[0];
    *c = saved;
#ifdef __linux__
    if (fesetenv(&environment)) FATAL("[party] cannot restore host FP environment\n");
    rt_set_fpcr(fpcr); rt_set_fpsr(fpsr);
#endif
    return r;
}

// The field party group (followers): the deployed members' entity handles in party order (entries of 0x30 at +0x6a0,
// count at +0x730), slot 0 the leader the others follow. The Party menu's close (f_70005419e0) rebuilds it in the new
// order - clear (vtable +0x20), then add each member's handle (vtable +0x28 = f_70004cf9a0) - before its leader change;
// without that the followers keep following the old leader (the old one stays first).
//   group = f_7000593120(&party manager)->+0x40 - 8
static uint64_t field_group(Cpu *c, uint64_t pm) {
    uint64_t slot = ((c->sp - 0x100) & ~15ull);  // (above the callee's frames: call_guest starts them at sp - 0x400)
    *(volatile uint64_t *)(uintptr_t)slot = pm;
    uint64_t holder = call_guest(c, 0x7000593120ull, slot, 0);
    uint64_t g = 0;
#ifdef __linux__
    if (!holder || !party_native_read(holder + 0x40, &g, sizeof g) || g < 8 || !party_writable(g - 8, 8)) return 0;
#else
    if (holder) g = *(volatile uint64_t *)(uintptr_t)(holder + 0x40);
#endif
    return g ? g - 8 : 0;
}
// A party member's entity handle (0: none) - the game's own lookup (f_70004c5490(party manager, character id), as the
// Party menu's close uses it through f_7000541c00): the entity whose battle arts control's +0x8 is that character id.
static uint32_t member_handle(Cpu *c, uint64_t pm, uint16_t id) { return (uint32_t)call_guest(c, 0x70004c5490ull, pm, id); }
static void group_rebuild(Cpu *c, uint64_t g, const uint32_t *handles, uint64_t n) {
    uint64_t vt = *(volatile uint64_t *)(uintptr_t)g;
    call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x20), g, 0);
    for (uint64_t i = 0; i < n; i++) call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x28), g, handles[i]);
    uint64_t m = (uint32_t)call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x18), g, 0);
    uint64_t e0 = m ? call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x40), g, 0) : 0;
    LOG("[party] field group: %llu member(s), first %#x\n", (unsigned long long)m, e0 ? *(volatile uint32_t *)(uintptr_t)e0 : 0);
}

// A follower's movement component (party character object, class vtable 0x7000b5de38, + 0x1a38) holds the "follow
// the leader" move it is doing as a pending per-frame callback (+0x198 the bound call, +0x1a0 its invoker
// f_700042d3d0; run by f_700042a280 while set). Made leader while following, the character keeps doing that move and
// ignores the stick until it ends (~0.7 s, measured: running straight, the new leader stops for 20 frames at 30 fps).
// Dropping it hands the movement to the pad at once (the game clears the same invoker when the move ends).
#define CHARA_OBJ_VTABLE 0x7000b5de38ull
#define FOLLOW_MOVE_INVOKER 0x700042d3d0ull
static void drop_follow_move(Cpu *c, uint64_t pm, uint32_t handle) {
    uint64_t scratch = ((c->sp - 0x100) & ~15ull);  // (above the callee's frames: call_guest3 starts them at sp - 0x400)
    memset((void *)(uintptr_t)scratch, 0, 0x20);
    call_guest3(c, 0x700049f8c0ull, scratch, pm, handle);  // (entity handle -> its object, as the game resolves it)
    uint64_t obj = *(volatile uint64_t *)(uintptr_t)scratch;
#ifdef __linux__
    uint64_t vt;
    if (!party_read(obj, &vt, sizeof vt) || vt != CHARA_OBJ_VTABLE ||
        !party_writable(obj + 0x1a38 + 0x1a0, sizeof(uint64_t))) return;
#else
    if (!obj || *(volatile uint64_t *)(uintptr_t)obj != CHARA_OBJ_VTABLE) return;
#endif
    volatile uint64_t *invoker = (volatile uint64_t *)(uintptr_t)(obj + 0x1a38 + 0x1a0);
    if (*invoker == FOLLOW_MOVE_INVOKER) *invoker = 0;
}

// A switch at any other time than with the player in control is ignored (the menu would keep showing the old leader;
// loading screens have no party yet).
static bool player_in_control(uint64_t p) {
    if (!p) return false;
#ifdef __linux__
    uint32_t on_bits, disabled;
    if (!obj_ok(p, K_PLAYER) || !party_read(p + 0xc, &on_bits, sizeof on_bits) ||
        !party_read(p + 0x10, &disabled, sizeof disabled) || on_bits != 0x3f800000u || disabled) return false;
#else
    float on;
    memcpy(&on, (const void *)(uintptr_t)(p + 0xc), 4);
    if (on != 1.0f || *(volatile uint32_t *)(uintptr_t)(p + 0x10) != 0) return false;
#endif
    // +0x120 .. +0x1a0: a u32 per player action whose upper half counts the locks on it. These are 0 in the field and in
    // battle and non-zero while the main menu or a cutscene holds the controls (measured: faces_1515 field / menu,
    // colony9 battle, a Colony 9 cutscene)
    static const uint16_t locks[] = {0x136, 0x13a, 0x13e, 0x142, 0x146, 0x14a, 0x14e, 0x156, 0x15a, 0x15e, 0x176, 0x17a, 0x19e};
    for (size_t i = 0; i < sizeof locks / sizeof locks[0]; i++)
    {
#ifdef __linux__
        uint16_t lock;
        if (!party_read(p + locks[i], &lock, sizeof lock) || lock) return false;
#else
        if (*(volatile uint16_t *)(uintptr_t)(p + locks[i])) return false;
#endif
    }
    return true;
}

static void switch_leader(Cpu *c, int step) {
    static Found f;
    found_get(&f);
    uint64_t fo = found_one(&f, K_FIELD);
    if (!fo) { LOG("[party] not ready yet\n"); return; }
    if (!player_in_control(found_one(&f, K_PLAYER))) { LOG("[party] not now (menu / cutscene / loading)\n"); return; }
    uint64_t list = call_guest(c, PARTY_LIST_FN, fo + 0x20, 0);
    if (!list) return;
    uint16_t *ids = (uint16_t *)(uintptr_t)list;
#ifdef __linux__
    uint64_t n;
    if (!party_native_read(list + 0x18, &n, sizeof n)) { LOG("[party] invalid Linux party list\n"); return; }
#else
    uint64_t n = *(uint64_t *)(uintptr_t)(list + 0x18);
#endif
    if (n < 2 || n > 16) { LOG("[party] %llu member(s): no switch\n", (unsigned long long)n); return; }
#ifdef __linux__
    if (!party_writable(list, (size_t)n * sizeof *ids)) { LOG("[party] Linux party list is not writable\n"); return; }
#endif
    // the list holds the whole roster: the deployed party (the first 3 - the Party menu's slots 1-2-3) and then the
    // reserve. Only the deployed ones take turns (as in Xenoblade 3); the reserve stays as it is.
    uint64_t total = n;
    if (n > 3) n = 3;
    uint64_t hud = found_one(&f, K_HUD);
#ifdef __linux__
    uint64_t battle_part = 0;
    if (hud && !party_read(hud + 0x2c0, &battle_part, sizeof battle_part)) return;
    bool battle = battle_part != 0;
    if (battle && (!party_writable(hud + 0x2d0, 4) || !party_writable(hud + 0x330, 1))) return;
#else
    bool battle = hud && *(volatile uint64_t *)(uintptr_t)(hud + 0x2c0);  // (the HUD's battle part is set up)
#endif
    uint64_t group = field_group(c, fo + 0x20);
    if (!group) { LOG("[party] no field group\n"); return; }
#ifdef __linux__
    if (!party_group_valid(group)) { LOG("[party] invalid Linux field group\n"); return; }
#endif
    // the next member able to fight leads (in battle a member at 0 HP is skipped, as Xenoblade 3 does); the order of the
    // others is kept (the list rotated left)
    uint16_t old[3];
    memcpy(old, ids, n * 2);
    uint64_t k = 0;
    for (uint64_t t = 1; t < n && !k; t++) {
        // [XCDE] step < 0 (L2 + L1, as Xenoblade 3): the member above - the last one - leads (the list rotated right)
        uint64_t cand = step < 0 ? n - t : t % n;
        if (!cand) continue;
        if (battle) {
            int64_t hp = battle_hp(&f, member_handle(c, fo + 0x20, old[cand]));
            static int test_down = -1;  // (tests: XCDE_PARTY_TEST_DOWN=<character id> counts as down)
            if (test_down < 0) test_down = getenv("XCDE_PARTY_TEST_DOWN") ? atoi(getenv("XCDE_PARTY_TEST_DOWN")) : 0;
            if (test_down && old[cand] == test_down) hp = 0;
            if (hp == 0) { LOG("[party] member %u is down: skipped\n", old[cand]); continue; }
        }
        k = cand;
    }
    if (!k) { LOG("[party] nobody to switch to\n"); return; }
    uint32_t handles[3];
    for (uint64_t i = 0; i < n; i++) {
        handles[i] = member_handle(c, fo + 0x20, old[(i + k) % n]);
        if (!handles[i]) { LOG("[party] member %u has no entity\n", old[(i + k) % n]); return; }
    }
    uint32_t handle = handles[0];
    for (uint64_t i = 0; i < n; i++) ids[i] = old[(i + k) % n];
    LOG("[party] leader %u -> %u (party %u %u %u, %llu in the roster), entity %#x\n", old[0], ids[0], ids[0], n > 1 ? ids[1] : 0,
        n > 2 ? ids[2] : 0, (unsigned long long)total, handle);
    group_rebuild(c, group, handles, n);
    call_guest(c, FOCUS_FN, fo + 0x20, handle);  // (as the Party menu does first: the new leader's entity)
    call_guest(c, SET_LEADER_FN, fo + 0x20, ids[0]);
    drop_follow_move(c, fo + 0x20, handle);
    if (battle) {
        *(volatile uint32_t *)(uintptr_t)(hud + 0x2d0) = handle;
        // bit 1 of +0x330 (the sub-object's +0x70): "rebuild" - its per-frame update (f_7000550b00) then rebuilds the
        // arts palette and portraits for that character (f_700054fbe0) and clears the bit
        *(volatile uint8_t *)(uintptr_t)(hud + 0x330) |= 2;
    }
}

// (tests) Each deployed member's position: field group slot i -> entity handle -> its object (f_700049f8c0, as the game
// resolves it) -> vtable +0x38 -> the entity, position at +0x110.
static void party_probe(Cpu *c, uint64_t frame) {
    Found f;
    found_get(&f);
    uint64_t fo = found_one(&f, K_FIELD);
    uint64_t g = fo ? field_group(c, fo + 0x20) : 0;
    if (!g) return;
    uint64_t vt = *(volatile uint64_t *)(uintptr_t)g;
    uint64_t n = (uint32_t)call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x18), g, 0);
    for (uint64_t i = 0; i < n && i < 3; i++) {
        uint64_t e = call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x40), g, i);
        uint32_t h = e ? *(volatile uint32_t *)(uintptr_t)e : 0;
        if (!h) continue;
        uint64_t scratch = ((c->sp - 0x100) & ~15ull);
        memset((void *)(uintptr_t)scratch, 0, 0x20);
        call_guest3(c, 0x700049f8c0ull, scratch, fo + 0x20, h);
        uint64_t obj = *(volatile uint64_t *)(uintptr_t)scratch;
        if (!obj || *(volatile uint64_t *)(uintptr_t)obj != CHARA_OBJ_VTABLE) continue;
        uint64_t ent = call_guest(c, *(volatile uint64_t *)(uintptr_t)(CHARA_OBJ_VTABLE + 0x38), obj, 0);
        const float *pos = (const float *)(uintptr_t)(ent + 0x110);
        LOG("[party] pos f%llu slot %llu h %#x %.2f %.2f %.2f\n", (unsigned long long)frame, (unsigned long long)i, h, pos[0], pos[1], pos[2]);
    }
}

// [XCDE] Arts hotkeys (keyboard 1-8 / T, runtime/hle/input.c): select a palette slot and use it the way a player does -
// the d-pad moves the palette cursor one art at a time (empty slots skipped, wrapping around), A uses the selected one.
// The cursor (the palette's +0x1c8) is read before each press; writing it doesn't move the game's own selection
// (measured). Only in battle with the player in control; the presses go out through party_macro_buttons.
enum { MACRO_A = 0, MACRO_LEFT = 12, MACRO_RIGHT = 14 };
#define MACRO_HOLD 4  // frames a press is held / released
static _Atomic int g_art_req = -1;
static _Atomic bool g_art_used;  // (the scanner starts on the first request)
static _Atomic uint64_t g_macro_buttons;
void party_art_request(int slot) {
    if (slot < 0 || slot > 8) return;
    g_art_used = true;
    g_art_req = slot;
}
static volatile uint64_t g_tour_buttons;  // (XCDE_TOUR: A pulses that close tutorial windows and dialogue)
uint64_t party_macro_buttons(void) { return g_macro_buttons | g_tour_buttons; }

static void art_macro(uint64_t frame) {
    static int target = -1, presses, last, dir;
    static bool fire;
    static uint64_t next, asked;
    static uint64_t epoch;
    uint64_t current_epoch = atomic_load(&g_party_epoch);
    if (epoch != current_epoch) {
        epoch = current_epoch;
        target = -1; presses = last = dir = 0; fire = false; next = asked = 0;
    }
    static int dbg = -1;
    if (dbg < 0) dbg = getenv("XCDE_ART_AT") != NULL;
    int r = atomic_exchange(&g_art_req, -1);
    if (r >= 0) { target = r; presses = 0; last = -1; fire = false; next = asked = frame; }
    if (target < 0 || frame < next) return;
    if (g_macro_buttons) {  // release, then look again
        g_macro_buttons = 0;
        next = frame + MACRO_HOLD;
        if (fire) target = -1;
        return;
    }
    Found f;
    found_get(&f);
    uint64_t pal = found_one(&f, K_PAL), hud = found_one(&f, K_HUD);
    if (!pal || !hud || !*(volatile uint64_t *)(uintptr_t)(hud + 0x2c0) || !player_in_control(found_one(&f, K_PLAYER))) {
        // not in battle / not in control: the key does nothing (a first press waits ~1 s for the scanner's first scan)
        if (dbg) LOG("[party] art f%llu: not now (pal %llx hud %llx)\n", (unsigned long long)frame, (unsigned long long)pal, (unsigned long long)hud);
        if (presses || frame - asked > 60) target = -1;
        return;
    }
    int cur = (int)*(volatile uint32_t *)(uintptr_t)(pal + 0x1c8);
    if (dbg) LOG("[party] art f%llu: slot %d -> %d\n", (unsigned long long)frame, cur, target);
    if (cur < 0 || cur > 8) { target = -1; return; }
    if (cur == target) {
        g_macro_buttons = 1ull << MACRO_A;
        fire = true;
        next = frame + MACRO_HOLD;
        return;
    }
    // the cursor went past the target: that slot is empty
    if (last >= 0 && ((dir > 0 && (target - last + 9) % 9 < (cur - last + 9) % 9) || (dir < 0 && (last - target + 9) % 9 < (last - cur + 9) % 9))) {
        LOG("[party] art slot %d is empty\n", target);
        target = -1;
        return;
    }
    if (presses++ >= 9) { target = -1; return; }
    if (last < 0) dir = (target - cur + 9) % 9 <= 4 ? 1 : -1;  // the shorter way round
    last = cur;
    g_macro_buttons = 1ull << (dir > 0 ? MACRO_RIGHT : MACRO_LEFT);
    next = frame + MACRO_HOLD;
}

// [XCDE] T236: the mouse camera as a PC game's - the mouse's pixels added to the camera's yaw / pitch (0.0025 rad a pixel
// at mouse_sens 50), no stick in between: no dead zone, curve or top speed. The game's thread, each pad read.
static _Atomic uint64_t g_cam_direct_frame;
static void party_actions_reset(void) {
    g_art_req = -1;
    g_art_used = false;
    g_macro_buttons = 0;
    g_tour_buttons = 0;
    g_cam_direct_frame = 0;
    atomic_fetch_add(&g_party_epoch, 1);
}
bool party_camera_direct(uint64_t frame) { return g_cam_direct_frame && frame - g_cam_direct_frame <= 1; }
static void mouse_camera(uint64_t frame) {
    extern bool input_mouse_take(uint64_t frame, float *dx, float *dy), input_mouse_on(void);
    extern int g_mouse_sens;
    extern bool g_mouse_invert;
    if (!input_mouse_on()) return;  // (the mouse camera off, or the cursor not captured: no scans for it)
    g_cam_used = true;
    Found f;
    found_get(&f);
    uint64_t cam = found_one(&f, K_CAM);
    if (!cam || !player_in_control(found_one(&f, K_PLAYER))) return;  // (the stick fallback moves it, if anything)
#ifdef __linux__
    if (!party_writable(cam + 0x1f0, 0x10)) return;
#endif
    float dx, dy;
    if (!input_mouse_take(frame, &dx, &dy)) return;
    g_cam_direct_frame = frame;
    if (dx == 0 && dy == 0) return;
    float k = 0.0025f * g_mouse_sens / 50;
    volatile float *v = (volatile float *)(uintptr_t)(cam + 0x1f0);
    float yaw = v[0] - dx * k, pitch = v[2] + dy * k * (g_mouse_invert ? -1 : 1);
    if (pitch < -0.98f) pitch = -0.98f;
    if (pitch > 1.18f) pitch = 1.18f;
    v[0] = v[1] = yaw;
    v[2] = v[3] = pitch;
}

// T210: frame-count thresholds of the game's logic at its own 30 fps above 30 fps. Some checks count frames, tuned
// for 30 fps; at 60 they trip in half the time. games/xcde/patches.py routes such compares through xcde_frames_gt(n)
// ("more than n frames at 30 fps" -> the same time at the current rate). Known one: a field follower restarts its
// "follow while running" move when its movement component counted more than 9 frames of a condition
// (f_70004439f0, cmp at 0x7000443b9c) - at 60 fps every ~11 frames, so followers never got past a walk and fell
// behind (measured 2 -> 17.5 m in 200 frames at 60 fps vs a steady 6.5 m at 30).
// g_frames_per_30: game frames per 1/30 s - the fps option at 30 / 60 (1 / 2); above (120, 144, unlimited) measured
// on the main thread (a 60 Hz display caps a 120 setting at 60). XCDE_FRAMES30_OFF=1: off (thresholds as the game has them).
static volatile uint32_t g_frames_per_30 = 1;
uint32_t xcde_frames_gt(uint32_t n) { return (n + 1) * g_frames_per_30 - 1; }
static void frames30_update(uint64_t frame) {
    static uint64_t last = ~0ull, t_last;
    static double avg;  // (seconds per frame, smoothed)
    static int off = -1;
    if (off < 0) off = getenv("XCDE_FRAMES30_OFF") != NULL;
    if (frame == last) return;  // (the pad is read more than once in some frames)
    last = frame;
    int fps = g_settings.fps;
    uint32_t k = 1;
    if (off || fps == 30) k = 1;
    else if (fps == 60) k = 2;
    else {
        uint64_t now = plat_now_ns();
        double dt = t_last ? (now - t_last) / 1e9 : 1.0 / 60;
        t_last = now;
        if (dt > 0 && dt < 0.25) avg = avg ? avg * 0.95 + dt * 0.05 : dt;
        k = avg > 0 ? (uint32_t)(1.0 / 30 / avg + 0.5) : 1;
        if (k < 1) k = 1;
        if (k > 8) k = 8;
    }
    g_frames_per_30 = k;
}

// [XCDE] T240 debugger: map jump on request. The scripts' "mapJump" native (f_7000512b50, script binding table at
// data 0xb61668) packs its arguments into a request and hands it to f_700051daf0, which queues it on the map jump
// manager (f_70000e19f0) - the game then fades out, loads the map and places the party. Request layout: +0 u16 area,
// +2 u16 sub-area (ma0201 = 2, 1: the game looks "ma%02d%02d" up in FLD_maplist), +0x10/14/18 x y z, +0x20 rotation
// (radians), +0x28 1.0f, +0x44 flags 0x100; the rest zero. The manager: f_700051daf0 reaches it through the script
// engine's current context (zero outside scripts); here through the scanned holder (vtable WARP_VTABLE) +0x58, as
// f_7000542870 does.
static unsigned g_warp_area, g_warp_sub;  // (the last jump's map: the battle step's jump next to an enemy stays on it)
static bool do_warp(Cpu *c, uint64_t frame, unsigned area, unsigned sub, float x, float y, float z, float deg) {
    g_warp_area = area, g_warp_sub = sub;
    Found f;
    found_get(&f);
    uint64_t hold = f.n[K_WARP] ? f.obj[K_WARP][0] : 0;
    uint64_t mgr = hold ? *(volatile uint64_t *)(uintptr_t)(hold + 0x58) : 0;
    if (!mgr) { LOG("[warp] frame %llu: no map jump manager found yet\n", (unsigned long long)frame); return false; }
    uint64_t req = (c->sp - 0x200) & ~15ull;  // (below the caller's frame, above call_guest's callee frames at sp - 0x400)
    uint8_t *r = (uint8_t *)(uintptr_t)req;
    memset(r, 0, 0x60);
    *(uint16_t *)r = (uint16_t)area;
    *(uint16_t *)(r + 2) = (uint16_t)sub;
    memcpy(r + 0x10, &x, 4), memcpy(r + 0x14, &y, 4), memcpy(r + 0x18, &z, 4);
    float rad = deg * 0.017453292f, one = 1.0f;
    memcpy(r + 0x20, &rad, 4), memcpy(r + 0x28, &one, 4);
    *(uint32_t *)(r + 0x44) = 0x100;
    LOG("[warp] frame %llu: map jump to ma%02u%02u at %.1f %.1f %.1f, %.0f deg\n", (unsigned long long)frame, area, sub, x, y, z, deg);
    call_guest(c, 0x70000e19f0ull, mgr, req);  // (queues the jump, as f_700051daf0 does)
    return true;
}

// [XCDE] T240 debugger: cutscene by name, as the scripts' "realtimeEventPlay" native (f_70005161d0, binding table at
// data 0xb61c18) starts it: a request object (0x950 bytes: +0 vtable [[0x7000b8c9a0]] + 0x10, +8 the 8 bytes at
// 0x70009cfd18, +0x10 the event name, +0x50 its length, +0x55 1, +0x60 1.0f, the rest zero) handed to
// f_70004f39e0(event manager [[0x7000b90f40]], request, 0) - not while f_7000503210(manager) says no event can start
// (the native's other check, f_700051e2b0, reads the script engine's context: zero outside scripts). Names from
// bdat_evt EVT_cs (vs01000000 ...), played on their own map.
// [XCDE] T240 debugger: cutscene by name the way the game's Event Theater plays one (menu code f_7000322ae0 at
// 0x7000323fb0): f_700032ae90(map jump manager, {name[0x80], u32 length at +0x80, u8 flag at +0x84, u32 at +0x88})
// queues a task on the map jump manager - the one the teleport uses (the scanned holder +0x58, as f_7000542870 reads
// it) - that loads the scene's map, places it and plays it once ready. The direct request (do_event) is dropped by
// the game when it isn't ready for it: scenes that "ended" after 1 s or never started from a teleport.
static bool do_theater(Cpu *c, uint64_t frame, const char *name) {
    Found f;
    found_get(&f);
    uint64_t hold = f.n[K_WARP] ? f.obj[K_WARP][0] : 0;
    uint64_t mgr = hold ? *(volatile uint64_t *)(uintptr_t)(hold + 0x58) : 0;
    if (!mgr) { LOG("[theater] frame %llu: no map jump manager found yet\n", (unsigned long long)frame); return false; }
    uint64_t req = (c->sp - 0x200) & ~15ull;
    uint8_t *r = (uint8_t *)(uintptr_t)req;
    memset(r, 0, 0x90);
    size_t n = strlen(name);
    if (n > 0x7f) n = 0x7f;
    memcpy(r, name, n);
    *(uint32_t *)(r + 0x80) = (uint32_t)n;
    uint64_t id = call_guest(c, 0x700032ae90ull, mgr, req);
    LOG("[theater] frame %llu: %s queued (task %llu)\n", (unsigned long long)frame, name, (unsigned long long)id);
    return true;
}

static bool do_event(Cpu *c, uint64_t frame, const char *name) {
    uint64_t mgr = *(volatile uint64_t *)(uintptr_t)*(volatile uint64_t *)(uintptr_t)0x7000b90f40ull;
    bool busy = !mgr || (call_guest(c, 0x7000503210ull, mgr, 0) & 1);
    LOG("[event] frame %llu: %s%s\n", (unsigned long long)frame, name, busy ? " - busy now, skipped" : "");
    if (busy) return false;
    uint64_t req = (c->sp - 0x1000) & ~15ull;  // (0x950 bytes, below the caller; the callee's frames go below it)
    uint8_t *r = (uint8_t *)(uintptr_t)req;
    memset(r, 0, 0x950);
    *(uint64_t *)r = *(volatile uint64_t *)(uintptr_t)0x7000b8c9a0ull + 0x10;
    memcpy(r + 8, (const void *)(uintptr_t)0x70009cfd18ull, 8);
    size_t n = strlen(name);
    if (n > 63) n = 63;
    memcpy(r + 0x10, name, n);
    *(uint32_t *)(r + 0x50) = (uint32_t)n;
    r[0x55] = 1;
    float one = 1.0f;
    memcpy(r + 0x60, &one, 4);
    Cpu saved = *c;
    c->x[0] = mgr, c->x[1] = req, c->x[2] = 0;
    c->sp = (req - 0x400) & ~15ull;
    guest_call(c, 0x70004f39e0ull);
    *c = saved;
    return true;
}

// Fixed frames: XCDE_WARP=<frame>:<area>:<sub>[:<x>:<y>:<z>[:<deg>]],... and XCDE_EVENT=<frame>:<name>,...
static void debug_fixed(Cpu *c, uint64_t frame) {
    static struct { uint64_t at; float v[7]; } w[64];
    static struct { uint64_t at; char name[64]; } ev[256];
    static int nw = -1, ne;
    if (nw < 0) {
        nw = ne = 0;
        for (const char *p = getenv("XCDE_WARP"); p && *p && nw < 64;) {
            char *e;
            w[nw].at = strtoull(p, &e, 10);
            int k = 0;
            while (*e == ':' && k < 7) w[nw].v[k++] = strtof(e + 1, &e);
            nw++;
            g_warp_used = true;
            for (p = e; *p == ','; p++) {}
        }
        for (const char *p = getenv("XCDE_EVENT"); p && *p && ne < 256;) {
            char *e;
            ev[ne].at = strtoull(p, &e, 10);
            int n = 0;
            if (*e == ':') for (e++; *e && *e != ',' && n < 63; e++) ev[ne].name[n++] = *e;
            ev[ne].name[n] = 0;
            ne++;
            for (p = e; *p == ','; p++) {}
        }
    }
    for (int i = 0; i < nw; i++)
        if (w[i].at == frame) do_warp(c, frame, (unsigned)w[i].v[0], (unsigned)w[i].v[1], w[i].v[2], w[i].v[3], w[i].v[4], w[i].v[5]);
    for (int i = 0; i < ne; i++)
        if (ev[i].at == frame) do_event(c, frame, ev[i].name);
}

// [XCDE] T240 debugger: XCDE_TOUR=<file> - a sequence the game follows as it gets ready, one step per line:
//   warp <area> <sub> <x> <y> <z> <deg>   map jump, then 600 frames for the fade, load and fade-in
//   event <name>                          cutscene: waits for it to start (<= 300 frames) and to end (<= 18000)
//   look <frames>                         turns the player camera a full circle over that many frames
//   wait <frames>
//   battle <frames>                       fights what is near: R targets, A attacks, an art every 3 s
//   story <n>                             sets the story progress (story-only spawns: bosses)
//   # comment / label                     logged ([tour] lines name what the recording shows)
// Outside cutscenes and videos the tour presses A for 4 frames every 90: tutorial windows (a jump into a new area
// opens them) and conversations would otherwise hold the tour. A step that can't start now (no manager yet, an
// event already playing) is retried every 30 frames.
// XCDE_TOUR_FROM=<n>: start at line n (a long tour in parts); XCDE_TOUR_START=<frame>: the first step's frame (2400);
// XCDE_TOUR_EXIT=1: end the process when the tour is done.
// [XCDE] T240 debugger: the story progress (scenario flag) - u16 at +0x14a0 of the game data object the service
// getter f_7000592b80 returns (f_70000b4220 reads it so for the enemy spawn tables' S_FLG_MIN / MAX checks). 0: not found.
static uint64_t story_ptr(Cpu *c) {
    Found f;
    found_get(&f);
    uint64_t fo = found_one(&f, K_FIELD);
    if (!fo) return 0;
    uint64_t slot = ((c->sp - 0x100) & ~15ull);
    *(volatile uint64_t *)(uintptr_t)slot = fo + 0x20;
    uint64_t g = call_guest(c, 0x7000592b80ull, slot, 0);
    return g ? g + 0x14a0 : 0;
}

// [XCDE] T240 battle tour: the character nearest the leader that isn't in the party (entity handles 1..4095 resolved as
// party_probe does; enemies are character objects too), at least 6 units away. Returns false if none within 600.
static bool nearest_other(Cpu *c, float out[3]) {
    Found f;
    found_get(&f);
    uint64_t fo = found_one(&f, K_FIELD);
    uint64_t g = fo ? field_group(c, fo + 0x20) : 0;
    if (!g) return false;
    uint64_t vt = *(volatile uint64_t *)(uintptr_t)g;
    uint64_t n = (uint32_t)call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x18), g, 0);
    uint32_t party[8] = {0};
    for (uint64_t i = 0; i < n && i < 8; i++) {
        uint64_t e = call_guest(c, *(volatile uint64_t *)(uintptr_t)(vt + 0x40), g, i);
        party[i] = e ? *(volatile uint32_t *)(uintptr_t)e : 0;
    }
    float me[3] = {0}, best = 600.0f * 600.0f;
    bool have_me = false, got = false;
    for (int pass = 0; pass < 2; pass++)
        for (uint32_t h = 1; h < 4096; h++) {
            bool mine = false;
            for (int i = 0; i < 8; i++) mine |= party[i] == h;
            if ((pass == 0) != (h == party[0])) continue;  // (pass 0: the leader's position; pass 1: the others)
            if (pass == 1 && mine) continue;
            uint64_t scratch = ((c->sp - 0x100) & ~15ull);
            memset((void *)(uintptr_t)scratch, 0, 0x20);
            call_guest3(c, 0x700049f8c0ull, scratch, fo + 0x20, h);
            uint64_t obj = *(volatile uint64_t *)(uintptr_t)scratch;
            if (!obj || *(volatile uint64_t *)(uintptr_t)obj != CHARA_OBJ_VTABLE) continue;
            uint64_t ent = call_guest(c, *(volatile uint64_t *)(uintptr_t)(CHARA_OBJ_VTABLE + 0x38), obj, 0);
            if (!ent) continue;
            const volatile float *p = (const volatile float *)(uintptr_t)(ent + 0x110);
            if (pass == 0) { me[0] = p[0], me[1] = p[1], me[2] = p[2], have_me = true; continue; }
            if (!have_me) return false;
            float dx = p[0] - me[0], dy = p[1] - me[1], dz = p[2] - me[2], d = dx * dx + dy * dy + dz * dz;
            if (d > 36.0f && d < best) best = d, out[0] = p[0], out[1] = p[1], out[2] = p[2], got = true;
        }
    return got;
}

static void debug_tour(Cpu *c, uint64_t frame) {
    static char **line;
    static int nline = -1, cur;
    static uint64_t until, deadline;
    static int phase;  // event: 0 issue, 1 waiting for the start, 2 waiting for the end
    static float spin_step;
    static uint64_t spin_until;
    if (nline < 0) {
        nline = 0;
        const char *path = getenv("XCDE_TOUR");
        FILE *fp = path ? fopen(path, "r") : NULL;
        char buf[256];
        while (fp && fgets(buf, sizeof buf, fp)) {
            buf[strcspn(buf, "\r\n")] = 0;
            if (!buf[0]) continue;
            line = realloc(line, sizeof *line * (nline + 1));
            line[nline++] = strdup(buf);
        }
        if (fp) fclose(fp);
        if (nline) { g_warp_used = g_cam_used = true; LOG("[tour] %d steps from %s\n", nline, path); }
        if (getenv("XCDE_TOUR_FROM")) cur = atoi(getenv("XCDE_TOUR_FROM"));
        until = getenv("XCDE_TOUR_START") ? strtoull(getenv("XCDE_TOUR_START"), NULL, 10) : 2400;  // (after the route's save load)
    }
    {   // (research: XCDE_DUMP_EVMGR=<frame>,...: the event manager's first 0x4000 bytes to build/evmgr_<frame>.bin)
        static uint64_t df[8];
        static int nd = -1;
        if (nd < 0) { nd = 0; for (const char *p = getenv("XCDE_DUMP_EVMGR"); p && *p && nd < 8;) { df[nd++] = strtoull(p, (char **)&p, 10); while (*p == ',') p++; } }
        for (int i = 0; i < nd; i++)
            if (df[i] == frame) {
                uint64_t m = *(volatile uint64_t *)(uintptr_t)*(volatile uint64_t *)(uintptr_t)0x7000b90f40ull;
                char path[128];
                snprintf(path, sizeof path, "build/evmgr_%llu.bin", (unsigned long long)frame);
                FILE *o = m ? fopen(path, "wb") : NULL;
                if (o) { fwrite(&m, 8, 1, o); fwrite((const void *)(uintptr_t)m, 1, 0x4000, o); fclose(o); }
            }
    }
    {   // (research: XCDE_DUMP_EVOBJ=<from>:<to> - each frame, the playing event objects (manager slots) 0x3000 bytes
        // each, appended to build/evobj.bin as {frame, present count, slot, pointer, bytes})
        static uint64_t f0, f1;
        static int on = -1;
        if (on < 0) on = getenv("XCDE_DUMP_EVOBJ") && sscanf(getenv("XCDE_DUMP_EVOBJ"), "%llu:%llu", (unsigned long long *)&f0, (unsigned long long *)&f1) == 2;
        if (on && frame >= f0 && frame <= f1) {
            extern uint64_t renderer_present_count(void);
            uint64_t m = *(volatile uint64_t *)(uintptr_t)*(volatile uint64_t *)(uintptr_t)0x7000b90f40ull;
            static FILE *o;
            if (!o) o = fopen("build/evobj.bin", "wb");
            for (int k = 0; m && o && k < 4; k++) {
                uint64_t ev = *(volatile uint64_t *)(uintptr_t)(m + 0xd8 + k * 0x60), hdr[4] = {frame, renderer_present_count(), (uint64_t)k, ev};
                if (!ev) continue;
                fwrite(hdr, 8, 4, o);
                fwrite((const void *)(uintptr_t)ev, 1, 0x3000, o);
            }
            if (o) fflush(o);
        }
    }
    if (!nline) return;
    // an event or a video running: the event manager's current event (+0xd8, 0 when none; +0x100 its state, 4 while
    // it plays - found comparing the manager idle and inside vs01040100; the framepace cutscene detector misses some
    // scenes), or a video decoder alive (FMV events such as vs01000000 leave +0xd8 at 0). Each alone missed a scene
    // (vs01050100 played after a long cutscene left +0xd8 at 0): any of them counts, the framepace detector too.
    extern bool xcde_movie_playing(void), xcde_in_cutscene(void);
    uint64_t emgr = *(volatile uint64_t *)(uintptr_t)*(volatile uint64_t *)(uintptr_t)0x7000b90f40ull;
    bool in_cut = xcde_in_cutscene();  // (stateful: called once a frame, here)
    // (the manager holds events in slots of 0x60 bytes from +0xd8, the event object first: vs01040100 played in slot 0,
    // vs01050100 after it in slot 1 at +0x138; each is cleared when its event ends)
    bool slot = false;
    for (int k = 0; emgr && k < 4; k++) slot |= *(volatile uint64_t *)(uintptr_t)(emgr + 0xd8 + k * 0x60) != 0;
    bool playing = in_cut || xcde_movie_playing() || slot;
    // (bit 0: A, every 1.5 s, also in cutscenes: their text boxes wait for it - vs01110100 and the field talk after a
    // landmark held both tours for an hour; A advances text, it doesn't skip a scene)
    g_tour_buttons = frame % 90 < 4 ? 1 : 0;
    if (spin_until > frame) {  // camera turn in progress (the game reads the yaw back each frame)
        Found f;
        found_get(&f);
        uint64_t cam = f.n[K_CAM] ? f.obj[K_CAM][0] : 0;
        if (cam) {
            volatile float *v = (volatile float *)(uintptr_t)(cam + 0x1f0);
            v[0] += spin_step, v[1] += spin_step;
        }
    }
    if (frame < until || cur >= nline) {
        static bool told;  // (>= until, once: a last step that sets no wait - a scene that never started - ended
                           // the tour with until in the past, and the run never exited)
        if (cur >= nline && frame >= until && !told) {
            told = true;
            LOG("[tour] done at frame %llu\n", (unsigned long long)frame);
            if (getenv("XCDE_TOUR_EXIT")) { fflush(stderr); plat_terminate(); }  // (XCDE_TOUR_EXIT=1: end the run)
        }
        return;
    }
    const char *l = line[cur];
    if (l[0] == '#') { LOG("[tour] frame %llu: %s\n", (unsigned long long)frame, l); cur++; return; }
    if (!strncmp(l, "warp ", 5)) {
        float v[7] = {0};
        sscanf(l + 5, "%f %f %f %f %f %f", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);
        static uint64_t wait_from;  // (a scene that doesn't end: after 60 s the jump goes anyway, logged)
        if (!wait_from) wait_from = frame;
        bool force = frame - wait_from > 3600;
        if (playing && force) LOG("[tour] frame %llu: still in a scene after 60 s, jumping anyway\n", (unsigned long long)frame);
        if ((playing && !force) || !do_warp(c, frame, (unsigned)v[0], (unsigned)v[1], v[2], v[3], v[4], v[5])) { until = frame + 30; return; }
        wait_from = 0;
        LOG("[tour] frame %llu: step %d %s\n", (unsigned long long)frame, cur, l);
        // (fade, load, fade-in; a jump inside the same map loads less: XCDE_TOUR_WARP_WAIT=<frames>, default 600)
        static int ww = -1;
        if (ww < 0) ww = getenv("XCDE_TOUR_WARP_WAIT") ? atoi(getenv("XCDE_TOUR_WARP_WAIT")) : 600;
        until = frame + (uint64_t)ww, cur++;
    } else if (!strncmp(l, "theaterq ", 9)) {  // "theaterq <name>": queue it as the theater does and go on (a teleport next)
        char qn[64] = {0};
        sscanf(l + 9, "%63s", qn);
        if (!do_theater(c, frame, qn)) { until = frame + 30; return; }
        LOG("[tour] frame %llu: step %d %s\n", (unsigned long long)frame, cur, l);
        until = frame + 30, cur++;
    } else if (!strncmp(l, "event ", 6) || !strncmp(l, "theater ", 8) || !strncmp(l, "await ", 6)) {
        // "theater <name> [<seconds>]": the same, queued as the Event Theater does (do_theater: no teleport needed);
        // "await <name> [<seconds>]": only the wait (a theaterq + teleport before it)
        bool theater = l[0] == 't', await_only = l[0] == 'a';
        // "event <name> [<seconds>]": the scene's own length (tour_gen.py: its header's frame count) sets how long
        // it may play (x1.2 + 30 s); one that ends before a quarter of it did not really play ("ended early")
        char ev_name[64] = {0};
        float ev_secs = 0;
        sscanf(l + (theater ? 8 : 6), "%63s %f", ev_name, &ev_secs);
        if (await_only && phase == 0) {
            LOG("[tour] frame %llu: step %d %s\n", (unsigned long long)frame, cur, l);
            phase = 1, deadline = frame + 1800;
            return;
        }
        static uint64_t ev_start;
        static int ev_quiet, ev_seen;
        static uint32_t ev_count0;
        if (phase == 0) {
            if (!(theater ? do_theater(c, frame, ev_name) : do_event(c, frame, ev_name))) { until = frame + 30; return; }
            LOG("[tour] frame %llu: step %d %s\n", (unsigned long long)frame, cur, l);
            // (a scene can take a while to show: the lab one, vs01110100, begins with a walk - XCDE_TOUR_EVENT_WAIT=<frames>)
            static int ew = -1;
            if (ew < 0) ew = getenv("XCDE_TOUR_EVENT_WAIT") ? atoi(getenv("XCDE_TOUR_EVENT_WAIT")) : 3600;  // (vs06060100 took 11 s)
            phase = 1, deadline = frame + (uint64_t)ew;
            ev_start = frame, ev_seen = 0, ev_quiet = 0;
            ev_count0 = emgr ? *(volatile uint32_t *)(uintptr_t)(emgr + 0x3050) : 0;
            // with its length known the scene gets all of it: the "playing" signals miss some scenes for a while
            // (vs01040100 played unseen - its end movie opened after the tour had called it "never started") and
            // blink between shots; it may end sooner only once seen, quiet for 3 s, and 80 % of its length past
            if (ev_secs > 0) phase = 2, deadline = frame + (uint64_t)(ev_secs * 69) + 2700;
        } else if (phase == 1) {
            if (playing) phase = 2, ev_start = frame, ev_seen = 1, deadline = frame + 18000;
            else if (frame >= deadline) { LOG("[tour] frame %llu: %s never started\n", (unsigned long long)frame, ev_name); phase = 0, cur++; }
        } else {
            // (also the event manager's count of scenes started, +0x3050: it goes up for the scenes the playing
            // signals miss - a zone's intro flyover, vs04010070)
            uint32_t cnt = emgr ? *(volatile uint32_t *)(uintptr_t)(emgr + 0x3050) : 0;
            if (cnt != ev_count0 && !ev_seen) {
                LOG("[tour] frame %llu: %s started (scene count %u -> %u)%c", (unsigned long long)frame, ev_name, ev_count0, cnt, 10);
                ev_seen = 1;
            }
            if (playing) ev_seen = 1, ev_quiet = 0;
            else ev_quiet++;
            float played = (float)(frame - ev_start) / 60.0f;
            bool over = ev_seen && ev_quiet >= 180 && (ev_secs <= 0 || played >= ev_secs * 0.8f);
            if (over || frame >= deadline) {
                LOG("[tour] frame %llu: %s %s after %.0f s of %.0f%s\n", (unsigned long long)frame, ev_name, over ? "ended" : "time up", played, ev_secs,
                    ev_seen ? "" : " (never seen playing)");
                phase = 0, cur++, until = frame + 90, ev_quiet = 0;
            }
        }
    } else if (!strncmp(l, "look ", 5)) {
        int n = atoi(l + 5);
        if (n < 1) n = 1;
        spin_step = 6.2831853f / n, spin_until = frame + n;
        LOG("[tour] frame %llu: step %d %s\n", (unsigned long long)frame, cur, l);
        until = frame + n, cur++;
    } else if (!strncmp(l, "battle ", 7)) {
        // "battle <frames>": fights whatever is near (the jump put the party at an enemy spawn): R targets, A attacks
        // (the A pulses above), an art every 3 s through the arts hotkeys (slots 1-8 in turn); time in battle logged
        static uint64_t b_end, b_in, b_from, b_next;
        static int b_slot, b_was, b_look;
        if (!b_end) {
            b_end = frame + (uint64_t)atoi(l + 7), b_in = 0, b_from = frame, b_slot = 0, b_was = 0;
            LOG("[tour] frame %llu: step %d %s\n", (unsigned long long)frame, cur, l);
            b_look = 1;
        }
        // next to the nearest other character (an enemy, usually): a jump within the map, 4 units off it; nobody yet
        // (spawns appear a while after a jump, some only at certain hours): looked for again every 5 s, 5 times
        if (b_look && (b_look == 1 || frame >= b_next)) {
            float e[3];
            if (nearest_other(c, e) && do_warp(c, frame, g_warp_area, g_warp_sub, e[0] + 4.0f, e[1] + 1.0f, e[2], 0)) {
                LOG("[tour] frame %llu: battle: jumping next to the character at %.0f %.0f %.0f\n", (unsigned long long)frame, e[0], e[1], e[2]);
                b_end = frame + (b_end - b_from) + 400, b_look = 0;  // (the whole fight after the jump's fade and load)
            } else if (b_look++ >= 6) {
                LOG("[tour] frame %llu: battle: nobody near\n", (unsigned long long)frame);
                b_look = 0;
            } else {
                b_next = frame + 300;
            }
        }
        Found f;
        found_get(&f);
        uint64_t hud = found_one(&f, K_HUD);
        int in = hud && *(volatile uint64_t *)(uintptr_t)(hud + 0x2c0) != 0;
        if (in != b_was) LOG("[tour] frame %llu: battle %s\n", (unsigned long long)frame, in ? "started" : "over"), b_was = in;
        b_in += in;
        // (R: the next target - also "in battle": the HUD's +0x2c0 is set in the field too, so it doesn't tell)
        if (frame % 90 >= 45 && frame % 90 < 49) g_tour_buttons |= 1ull << 7;
        if (in && frame % 180 == 0) party_art_request(1 + b_slot++ % 8);
        if (frame >= b_end) {
            LOG("[tour] frame %llu: battle step over: %.0f s of %.0f in battle\n", (unsigned long long)frame, b_in / 60.0, (frame - b_from) / 60.0);
            b_end = 0, cur++, until = frame + 60;
        }
    } else if (!strncmp(l, "story ", 6)) {  // "story <n>": set the story progress (spawns of that point of the story)
        uint64_t sp = story_ptr(c);
        if (!sp) { until = frame + 30; return; }
        uint16_t was = *(volatile uint16_t *)(uintptr_t)sp;
        *(volatile uint16_t *)(uintptr_t)sp = (uint16_t)atoi(l + 6);
        LOG("[tour] frame %llu: step %d %s (was %u)\n", (unsigned long long)frame, cur, l, was);
        cur++, until = frame + 30;
    } else if (!strncmp(l, "wait ", 5)) {
        until = frame + (uint64_t)atoi(l + 5), cur++;
    } else {
        LOG("[tour] unknown step: %s\n", l);
        cur++;
    }
}

// (research: XCDE_ENT_SCAN=<frame>,...: every entity handle 1..4095 resolved as party_probe does - object, vtable,
// and for character objects the position - to find the enemies near the player)
static void ent_scan(Cpu *c, uint64_t frame) {
    static uint64_t at[8];
    static int n = -1;
    if (n < 0) { n = 0; for (const char *p = getenv("XCDE_ENT_SCAN"); p && *p && n < 8;) { at[n++] = strtoull(p, (char **)&p, 10); while (*p == ',') p++; } }
    bool now = false;
    for (int i = 0; i < n; i++) now |= at[i] == frame;
    if (!now) return;
    Found f;
    found_get(&f);
    uint64_t fo = found_one(&f, K_FIELD);
    if (!fo) { LOG("[ents] f%llu: no field\n", (unsigned long long)frame); return; }
    int shown = 0;
    for (uint32_t h = 1; h < 4096; h++) {
        uint64_t scratch = ((c->sp - 0x100) & ~15ull);
        memset((void *)(uintptr_t)scratch, 0, 0x20);
        call_guest3(c, 0x700049f8c0ull, scratch, fo + 0x20, h);
        uint64_t obj = *(volatile uint64_t *)(uintptr_t)scratch;
        if (!obj) continue;
        uint64_t vt = *(volatile uint64_t *)(uintptr_t)obj;
        if (vt == CHARA_OBJ_VTABLE) {
            uint64_t ent = call_guest(c, *(volatile uint64_t *)(uintptr_t)(CHARA_OBJ_VTABLE + 0x38), obj, 0);
            const float *pos = ent ? (const float *)(uintptr_t)(ent + 0x110) : NULL;
            if (pos && shown++ < 200)
                LOG("[ents] f%llu h %#x chara obj %llx ent %llx pos %.1f %.1f %.1f\n", (unsigned long long)frame, h, (unsigned long long)obj,
                    (unsigned long long)ent, pos[0], pos[1], pos[2]);
        } else if (shown++ < 200) {
            LOG("[ents] f%llu h %#x obj %llx vtable %llx\n", (unsigned long long)frame, h, (unsigned long long)obj, (unsigned long long)vt);
        }
    }
    LOG("[ents] f%llu: %d objects\n", (unsigned long long)frame, shown);
}

void party_game_tick(Cpu *c, uint64_t frame) {
    ent_scan(c, frame);
    frames30_update(frame);
    debug_fixed(c, frame);
    debug_tour(c, frame);
    extern bool g_party_switch;
    static uint64_t at[16];
    static int nat = -1;
    if (nat < 0) {
        nat = 0;
        for (const char *p = getenv("XCDE_PARTY_SWITCH_AT"); p && *p && nat < 16;) {
            at[nat++] = strtoull(p, (char **)&p, 10);
            while (*p == ',') p++;
        }
    }
#ifdef _WIN32
    static bool scanner;
    if (!scanner && (g_party_switch || nat || g_art_used || g_cam_used || g_warp_used)) {  // (only with the option on: no thread, no scans otherwise)
        scanner = true;
        HANDLE t = CreateThread(NULL, 0, party_scanner, NULL, 0, NULL);
        if (t) { SetThreadPriority(t, THREAD_PRIORITY_BELOW_NORMAL); CloseHandle(t); }
    }
#elif defined(__linux__)
    if (g_party_switch || nat || g_art_used || g_cam_used || g_warp_used) party_scanner_start();
#endif
    for (int i = 0; i < nat; i++) if (at[i] == frame) { at[i] = 0; g_switch_req = 1; }
    static int probe = -1;  // (tests: XCDE_PARTY_PROBE=<n>: the deployed members' positions every n frames)
    if (probe < 0) probe = getenv("XCDE_PARTY_PROBE") ? atoi(getenv("XCDE_PARTY_PROBE")) : 0;
    if (probe && frame % (uint64_t)probe == 0) party_probe(c, frame);
    static uint64_t art_at[8], art_v[8];  // (tests: XCDE_ART_AT=<frame>:<slot>,...: an arts hotkey pressed then)
    static int nart = -1;
    if (nart < 0) {
        nart = 0;
        for (const char *p = getenv("XCDE_ART_AT"); p && *p && nart < 8;) {
            art_at[nart] = strtoull(p, (char **)&p, 10);
            art_v[nart++] = *p == ':' ? strtoull(p + 1, (char **)&p, 10) : 0;
            while (*p == ',') p++;
        }
    }
    for (int i = 0; i < nart; i++) if (art_at[i] == frame) { art_at[i] = 0; party_art_request((int)art_v[i]); }
    art_macro(frame);
    mouse_camera(frame);
    int step = atomic_exchange(&g_switch_req, 0);
    if (!step) return;
    switch_leader(c, step);
}
