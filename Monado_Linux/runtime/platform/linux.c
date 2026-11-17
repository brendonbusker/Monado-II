// Linux host layer (runtime/platform.h). x86-64 and aarch64.
#define _GNU_SOURCE
#include <SDL3/SDL.h>
#include <dlfcn.h>
#include <errno.h>
#include <execinfo.h>
#include <fenv.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/ucontext.h>
#include <time.h>
#include <unistd.h>

#include "../platform.h"
#include "../paths.h"  // [XCDE] LINUX-004: initialized canonical state before logs

#if defined(__x86_64__)
#include <cpuid.h>
#include <xmmintrin.h>
#endif

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

// [XCDE] LINUX-007: pthreads inherit their creator's FP environment. Portable
// guest helpers keep FPCR in Cpu but require host RN arithmetic and denormals.
// Establish that baseline once at guest-thread entry; fiber switches must keep
// preserving their saved host environment, including a helper's slow FP path.
bool plat_guest_fp_init(void) {
#ifdef __clang__
#pragma STDC FENV_ACCESS ON
#endif
    if (fesetenv(FE_DFL_ENV) != 0 || fegetround() != FE_TONEAREST ||
        fetestexcept(FE_ALL_EXCEPT) != 0 || fegetexcept() != 0) return false;
#if defined(__x86_64__)
    unsigned short control;
    __asm__ volatile("fnstcw %0" : "=m"(control));
    // x87: nearest and all six exception masks. SSE: all masks set, nearest,
    // flags cleared, FTZ/DAZ disabled. Refuse an incomplete libc reset.
    if ((control & 0x0c3f) != 0x003f || (_mm_getcsr() & 0xffff) != 0x1f80) return false;
#endif
    return true;
}

// ---- guest address space
// [XCDE] LINUX-002: fixed once by startup, before renderer/guest threads exist.
static uint64_t guest_lo, guest_hi;
// Everything readable/writable from the start, like macOS: the guest maps at 4K granularity, and untouched pages
// cost nothing (MAP_NORESERVE: the 12 GB window doesn't count against overcommit).
bool plat_reserve_guest(uint64_t lo, uint64_t hi) {
    void *p = mmap((void *)(uintptr_t)lo, hi - lo, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_FIXED_NOREPLACE, -1, 0);
    if (p == MAP_FAILED) return false;
    if (p != (void *)(uintptr_t)lo) { munmap(p, hi - lo); return false; }  // (kernels before 4.17: just a hint)
    guest_lo = lo;
    guest_hi = hi;
    return true;
}

// Fresh zero pages over the whole window (the old ones are released at once).
bool plat_reset_guest(uint64_t lo, uint64_t hi) {
    return mmap((void *)(uintptr_t)lo, hi - lo, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE | MAP_FIXED,
                -1, 0) == (void *)(uintptr_t)lo;
}

void plat_commit(uint64_t addr, uint64_t size) { (void)addr; (void)size; }

int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {  // (no write tracking)
    (void)addr; (void)size; (void)pages; (void)max; (void)page;
    return -1;
}

int plat_protect(uint64_t addr, uint64_t size, int prot) {
    int p = prot == PLAT_PROT_NONE ? PROT_NONE : prot == PLAT_PROT_READ ? PROT_READ : PROT_READ | PROT_WRITE;
    return mprotect((void *)(uintptr_t)addr, size, p);
}

// ---- time
uint64_t plat_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
}

void plat_sleep_until_ns(uint64_t t) {
    struct timespec ts = {.tv_sec = (time_t)(t / 1000000000u), .tv_nsec = (long)(t % 1000000000u)};
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR) {}
}

// Real-time scheduling where the user may have it (rtkit / limits.conf), else just a higher priority: keeps the
// vsync thread on time while the guest threads load every core.
void plat_thread_realtime(uint64_t period_ns) {
    (void)period_ns;
    struct sched_param sp = {.sched_priority = 1};
    if (pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp) == 0) return;
    // [XCDE] LINUX-003: syscall avoids requiring glibc's newer gettid wrapper.
    setpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid), -10);  // per thread; may fail without CAP_SYS_NICE
}

// ---- process
// [XCDE] LINUX-004: only the explicitly initialized state directory may receive
// runtime logs. Never fall back to another project's or a user's old data folder.
static char g_log_path[1024];

static void log_to_file_without_terminal(void) {
    if (isatty(STDERR_FILENO)) return;
    const char *dir = rt_data_root();
    if (!dir || !*dir || snprintf(g_log_path, sizeof g_log_path, "%s/logs/monado.log", dir) >= (int)sizeof g_log_path) {
        fprintf(stderr, "FATAL: Linux paths must be initialized before platform logging\n");
        exit(1);
    }
    // Append across runtime/precompile launches; a failed initialization must not
    // truncate the last useful diagnostic log. State initialization creates logs/.
    if (!freopen(g_log_path, "a", stderr)) { perror("cannot open Monado state log"); exit(1); }
    dup2(STDERR_FILENO, STDOUT_FILENO);
    setenv("LASRECOMP_LOG_APPEND", "1", 1);
}

#if defined(__x86_64__)
// [XCDE] LINUX-003: match Monado's x86-64-v2 build contract, not LASRecomp's v3.
// Read CPUID directly: Zig's GNU driver does not provide GCC's __cpu_model globals.
static void require_cpu(void) {
    unsigned a, b, c, d;
    const unsigned required = bit_SSE3 | bit_SSSE3 | bit_CMPXCHG16B | bit_SSE4_1 | bit_SSE4_2 | bit_POPCNT;
    if (__get_cpuid(1, &a, &b, &c, &d) && (c & required) == required &&
        __get_cpuid(0x80000001, &a, &b, &c, &d) && (c & bit_LAHF_LM)) return;
    fprintf(stderr, "FATAL: Monado needs an x86-64-v2 CPU (SSE4.2, POPCNT, CMPXCHG16B and related baseline features).\n");
    exit(1);
}
#else
static void require_cpu(void) {}
#endif

void plat_init(void) {
    log_to_file_without_terminal();
    require_cpu();
}

// (inside an AppImage: the binary in its mount, which stays mounted while this process lives - re-exec included)
bool plat_exe_path(char *buf, size_t size) {
    // [XCDE] LINUX-003: never report a truncated path as a usable executable.
    if (!buf || !size) { errno = EINVAL; return false; }
    ssize_t n = readlink("/proc/self/exe", buf, size);
    if (n <= 0 || (size_t)n >= size) {
        buf[0] = 0;
        if (n >= 0) errno = ENAMETOOLONG;
        return false;
    }
    buf[n] = 0;
    return true;
}

// Our own command line, from /proc/self/cmdline (NUL-separated).
static char **self_argv(char **storage) {  // [XCDE] LINUX-003: complete argv, including large/many arguments
    int fd = open("/proc/self/cmdline", O_RDONLY);
    if (fd < 0) return NULL;
    size_t size = 0, capacity = 4096;
    char *buf = malloc(capacity);
    if (!buf) { close(fd); return NULL; }
    for (;;) {
        if (size == capacity) {
            if (capacity > SIZE_MAX / 2) { errno = EOVERFLOW; goto fail; }
            char *larger = realloc(buf, capacity * 2);
            if (!larger) goto fail;
            buf = larger;
            capacity *= 2;
        }
        ssize_t n = read(fd, buf + size, capacity - size);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) goto fail;
        if (!n) break;
        size += (size_t)n;
    }
    close(fd);
    fd = -1;
    if (!size || buf[size - 1]) { errno = EIO; goto fail; }
    size_t count = 0;
    for (size_t i = 0; i < size; i++) if (!buf[i]) count++;
    if (count >= SIZE_MAX / sizeof(char *)) { errno = EOVERFLOW; goto fail; }
    char **argv = malloc((count + 1) * sizeof *argv);
    if (!argv) goto fail;
    size_t k = 0;
    for (char *p = buf; p < buf + size; p += strlen(p) + 1) argv[k++] = p;
    argv[count] = NULL;
    *storage = buf;
    return argv;
fail:;
    int error = errno;
    if (fd >= 0) close(fd);
    free(buf);
    errno = error;
    return NULL;
}

void plat_exec(char *const argv[]) {
    if (argv) {
        if (!argv[0] || !*argv[0]) { errno = EINVAL; return; }
        execv(argv[0], argv);
        return;
    }
    char path[4096];
    char *storage = NULL;
    char **av = self_argv(&storage);
    if (av && plat_exe_path(path, sizeof path)) execv(path, av);
    int error = errno;
    free(av);
    free(storage);
    errno = error;
}

// ---- diagnostics
// [XCDE] LINUX-002: Linux has no Windows MEM_COMMIT accounting equivalent for
// our MAP_NORESERVE window. Report private resident bytes, total RSS and guest
// resident pages, with matching Linux labels in the renderer. These are live,
// non-atomic observations, not an allocation/commit limit or a leak proof.
// smaps fields: https://docs.kernel.org/filesystems/proc.html
void plat_mem_info(uint64_t *priv, uint64_t *ws, uint64_t *guest_resident) {
    *priv = *ws = *guest_resident = 0;
    FILE *f = fopen("/proc/self/smaps_rollup", "r");
    if (!f) { perror("[mem] smaps_rollup unavailable"); return; }
    char line[256];
    unsigned long long kb;
    while (fgets(line, sizeof line, f)) {
        if (sscanf(line, "Rss: %llu kB", &kb) == 1) *ws = kb * 1024;
        else if (sscanf(line, "Private_Clean: %llu kB", &kb) == 1 ||
                 sscanf(line, "Private_Dirty: %llu kB", &kb) == 1) *priv += kb * 1024;
    }
    if (ferror(f)) { perror("[mem] smaps_rollup read failed"); *priv = *ws = 0; }
    fclose(f);
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) { fprintf(stderr, "[mem] page size unavailable\n"); return; }
    unsigned char resident[4096];
    for (uint64_t addr = guest_lo; addr < guest_hi;) {
        uint64_t size = guest_hi - addr, chunk = sizeof resident * (uint64_t)page;
        if (size > chunk) size = chunk;
        if (mincore((void *)(uintptr_t)addr, size, resident)) {
            perror("[mem] guest residency unavailable"); *guest_resident = 0; return;
        }
        for (uint64_t i = 0; i < (size + page - 1) / page; ++i)
            if (resident[i] & 1) *guest_resident += page;
        addr += size;
    }
}

typedef struct MemRegion { uint64_t lo, hi, bytes; } MemRegion;
static void mem_region_add(MemRegion region, MemRegion top[24], uint64_t *total, unsigned *count) {
    if (!region.bytes || (region.lo < guest_hi && region.hi > guest_lo)) return;
    *total += region.bytes;
    ++*count;
    for (int i = 0; i < 24; ++i) if (region.bytes > top[i].bytes) {
        MemRegion old = top[i]; top[i] = region; region = old;
    }
}

void plat_mem_map(void) {
    FILE *f = fopen("/proc/self/smaps", "r");
    if (!f) { perror("[memmap] smaps unavailable"); return; }
    MemRegion top[24] = {{0}}, current = {0};
    uint64_t total = 0;
    unsigned count = 0;
    char line[4096], perms[5];
    unsigned long long lo, hi, kb;
    while (fgets(line, sizeof line, f)) {
        if (sscanf(line, "%llx-%llx %4s", &lo, &hi, perms) == 3) {
            mem_region_add(current, top, &total, &count);
            current = (MemRegion){lo, hi, 0};
        } else if (sscanf(line, "Private_Clean: %llu kB", &kb) == 1 ||
                   sscanf(line, "Private_Dirty: %llu kB", &kb) == 1) current.bytes += kb * 1024;
    }
    mem_region_add(current, top, &total, &count);
    if (ferror(f)) { perror("[memmap] smaps read failed"); fclose(f); return; }
    fclose(f);
    fprintf(stderr, "[memmap] private resident outside guest-overlapping mappings: %.1f MB in %u regions\n",
            total / 1048576.0, count);
    for (int i = 0; i < 24 && top[i].bytes; ++i)
        fprintf(stderr, "[memmap] %#llx-%#llx %.1f MB resident\n",
                (unsigned long long)top[i].lo, (unsigned long long)top[i].hi, top[i].bytes / 1048576.0);
}

// Exported symbols only (the Makefile links with -rdynamic); frames in the generated code are left to the caller,
// which maps them to guest functions (runtime/dispatch.c). Static runtime functions come out as the nearest guest
// function, so backtrace lines also give the offset in the executable (addr2line -fe lasrecomp <offset>).
const char *plat_symbol(uint64_t pc, uint64_t *offset) {
    Dl_info di = {0};
    if (!dladdr((void *)(uintptr_t)pc, &di) || !di.dli_sname) return NULL;
    if (offset) *offset = pc - (uint64_t)(uintptr_t)di.dli_saddr;
    return di.dli_sname;
}

// Fatal error without a terminal: say so in a message box rather than vanishing (the details are in the log).
void plat_fatal_notice(void) {
    if (!g_log_path[0]) return;
    fflush(stderr);
    char text[1200];
    snprintf(text, sizeof text, "LAS Recomp stopped because of an error.\n\nDetails: %s", g_log_path);
    // [XCDE] LINUX-007: automated fatal runs retain logs/exit without a modal wait.
    const char *no_dialog = getenv("XCDE_NO_ERROR_DIALOG");
    if (!no_dialog || strcmp(no_dialog, "1"))
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "LAS Recomp", text, NULL);
}

const char *rt_host_fn_name(uint64_t pc, uint64_t *offset);  // runtime/dispatch.c

void plat_print_backtrace(void) {
    void *bt[64];
    int n = backtrace(bt, 64);
    Dl_info self = {0};
    dladdr((void *)plat_print_backtrace, &self);
    for (int i = 0; i < n; i++) {
        uint64_t pc = (uint64_t)(uintptr_t)bt[i], off = 0;
        Dl_info di = {0};
        if (!dladdr(bt[i], &di)) di.dli_fname = NULL;
        bool ours = di.dli_fbase && di.dli_fbase == self.dli_fbase;
        const char *s = plat_symbol(pc, &off);
        if (!s && ours) s = rt_host_fn_name(pc, &off);
        const char *mod = di.dli_fname ? (strrchr(di.dli_fname, '/') ? strrchr(di.dli_fname, '/') + 1 : di.dli_fname) : "?";
        uint64_t moff = pc - (uint64_t)(uintptr_t)di.dli_fbase;
        if (s && ours) fprintf(stderr, "  #%-2d %016llx %s+%llx (lasrecomp+%llx)\n", i, (unsigned long long)pc, s,
                               (unsigned long long)off, (unsigned long long)moff);
        else if (s) fprintf(stderr, "  #%-2d %016llx %s+%llx (%s)\n", i, (unsigned long long)pc, s, (unsigned long long)off, mod);
        else fprintf(stderr, "  #%-2d %016llx %s+%llx\n", i, (unsigned long long)pc, mod, (unsigned long long)moff);
    }
}

static void crash_handler(int sig, siginfo_t *si, void *ctx) {
    ucontext_t *uc = ctx;
    // [XCDE] LINUX-003: a fault while reporting must not recurse indefinitely, or
    // mistake another thread's first fault for recursion.
    static __thread volatile sig_atomic_t depth;
    if (depth++) _exit(128 + sig);
    uint64_t fa = (uint64_t)(uintptr_t)si->si_addr;
#if defined(__aarch64__)
    uint64_t pc = uc->uc_mcontext.pc, lr = uc->uc_mcontext.regs[30];
#else
    // x86-64 has no LR. Dereferencing an arbitrary interrupted SP can fault again
    // (and its value is not generally a return address); retain the reliable RIP.
    uint64_t pc = (uint64_t)uc->uc_mcontext.gregs[REG_RIP], lr = 0;
#endif
    if (rt_fault_watch(fa, pc)) { depth--; return; }
    char what[32];
    snprintf(what, sizeof what, "signal %d", sig);
    rt_fault_report(what, fa, pc, lr);
}

// [XCDE] LINUX-003: each host thread owns one alternate stack. Restore any prior
// stack on explicit cleanup; the pthread key also releases it on ordinary exit.
typedef struct CrashStack { void *memory; stack_t previous; } CrashStack;
static pthread_key_t crash_stack_key;
static pthread_once_t crash_once = PTHREAD_ONCE_INIT;
static int crash_init_error;
static __thread bool crash_stack_installed;

static void release_crash_stack(void *value) {
    CrashStack *stack = value;
    if (!stack) return;
    crash_stack_installed = false;
    if (sigaltstack(&stack->previous, NULL)) return;  // never free an active/installed stack
    free(stack->memory);
    free(stack);
}

static void init_crash_handlers(void) {
    crash_init_error = pthread_key_create(&crash_stack_key, release_crash_stack);
    if (crash_init_error) return;
    struct sigaction sa = {0};
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    const int signals[] = {SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT};
    for (size_t i = 0; i < sizeof signals / sizeof signals[0]; i++) {
        if (sigaction(signals[i], &sa, NULL)) { crash_init_error = errno; return; }
    }
}

static __attribute__((noreturn)) void crash_setup_failed(int error) {
    fprintf(stderr, "FATAL: cannot install Linux crash diagnostics: %s\n", strerror(error));
    _exit(1);
}

void plat_crash_handler_install(void) {
    int error = pthread_once(&crash_once, init_crash_handlers);
    if (error || crash_init_error) crash_setup_failed(error ? error : crash_init_error);
    if (pthread_getspecific(crash_stack_key)) return;
    CrashStack *stack = calloc(1, sizeof *stack);
    if (!stack) crash_setup_failed(ENOMEM);
    stack->memory = malloc(1 << 20);
    if (!stack->memory) { free(stack); crash_setup_failed(ENOMEM); }
    stack_t ss = {.ss_sp = stack->memory, .ss_size = 1 << 20};
    if (sigaltstack(&ss, &stack->previous)) {
        error = errno; free(stack->memory); free(stack); crash_setup_failed(error);
    }
    error = pthread_setspecific(crash_stack_key, stack);
    if (error) { release_crash_stack(stack); crash_setup_failed(error); }
    crash_stack_installed = true;
}

void plat_crash_handler_uninstall(void) {
    if (!crash_stack_installed) return;  // cleanup must not install process-wide handlers
    CrashStack *stack = pthread_getspecific(crash_stack_key);
    if (!stack) return;
    if (sigaltstack(&stack->previous, NULL)) return;
    if (pthread_setspecific(crash_stack_key, NULL)) return;
    crash_stack_installed = false;
    free(stack->memory);
    free(stack);
}

// ---- child processes
#include <ftw.h>
#include <spawn.h>
#include <sys/wait.h>
extern char **environ;

PlatProc plat_spawn(const char *const argv[], const char *log_path, bool append_log) {
    // [XCDE] LINUX-003: setup failures must not launch with inherited descriptors/group.
    if (!argv || !argv[0] || !*argv[0]) { errno = EINVAL; return 0; }
    posix_spawn_file_actions_t fa;
    int rc = posix_spawn_file_actions_init(&fa);
    if (rc) { errno = rc; return 0; }
    posix_spawnattr_t at;  // (its own process group: plat_proc_kill ends what it starts, e.g. a compiler's own child)
    rc = posix_spawnattr_init(&at);
    if (rc) { posix_spawn_file_actions_destroy(&fa); errno = rc; return 0; }
    pid_t pid = 0;
    if (!(rc = posix_spawn_file_actions_addopen(&fa, 1, log_path ? log_path : "/dev/null",
                          O_WRONLY | O_CREAT | (append_log ? O_APPEND : O_TRUNC), 0644)) &&
        !(rc = posix_spawn_file_actions_adddup2(&fa, 1, 2)) &&
        !(rc = posix_spawnattr_setflags(&at, POSIX_SPAWN_SETPGROUP)) &&
        !(rc = posix_spawnattr_setpgroup(&at, 0)))
        rc = posix_spawn(&pid, argv[0], &fa, &at, (char *const *)argv, environ);
    posix_spawnattr_destroy(&at);
    posix_spawn_file_actions_destroy(&fa);
    if (rc) errno = rc;
    return rc ? 0 : (PlatProc)pid;
}

void plat_proc_kill(PlatProc p) {
    // [XCDE] LINUX-003: zero is our failure sentinel, never a process-group wildcard.
    if (p <= 0 || p > INT_MAX) return;
    kill(-(pid_t)p, SIGKILL);
    while (waitpid((pid_t)p, NULL, 0) < 0 && errno == EINTR) {}
}

int plat_proc_wait(PlatProc p, bool block) {
    if (p <= 0 || p > INT_MAX) { errno = EINVAL; return 255; }
    int st = 0;
    pid_t r;
    do { r = waitpid((pid_t)p, &st, block ? 0 : WNOHANG); } while (r < 0 && errno == EINTR);
    if (r == 0) return -1;
    if (r < 0) return 255;
    return WIFEXITED(st) ? WEXITSTATUS(st) : 255;
}

static int rm_entry(const char *path, const struct stat *sb, int flag, struct FTW *ftw) {
    (void)sb, (void)flag, (void)ftw;
    return remove(path);
}
bool plat_remove_tree(const char *dir) { return nftw(dir, rm_entry, 16, FTW_DEPTH | FTW_PHYS) == 0; }

// End the process at once, skipping the library teardown: as on Windows, the GPU driver's threads crashed in exit()
// while the game's threads still submitted work.
void plat_terminate(void) { _exit(0); }

// [XCDE] T122: not sampled on this platform
uint64_t plat_thread_pc(void *pthread_handle) { (void)pthread_handle; return 0; }
void plat_thread_name(const char *name) {  // [XCDE] LINUX-003: Linux limits thread names to 15 bytes plus NUL.
    if (!name) return;
    char short_name[16];
    snprintf(short_name, sizeof short_name, "%s", name);
    (void)pthread_setname_np(pthread_self(), short_name);
}
void plat_thread_background(void) {}
// [XCDE] LINUX-126: only the dedicated shader-refinement worker calls this.
// Linux nice is per TID; increase it once, without changing the process, audio,
// urgent compile workers or the generic background API's existing callers.
void plat_thread_shader_background(void) {
    static _Thread_local bool attempted;
    if (attempted) return;
    attempted = true;
    int saved = errno;
    long tid = syscall(SYS_gettid);
    if (tid > 0) {
        errno = 0;
        int current = getpriority(PRIO_PROCESS, (id_t)tid);
        if (!(current == -1 && errno) && current < 5)
            (void)setpriority(PRIO_PROCESS, (id_t)tid, 5);
    }
    // A sandbox may refuse even a priority reduction. Work still runs, and the
    // queue policy still bounds refinement concurrency; never ask for privilege.
    errno = saved;
}
void plat_thread_audio(void) {}
int plat_cpu_count(void) {  // [XCDE] LINUX-003: respect the CPUs this thread may actually use.
    int count = 0;
    for (size_t bits = CPU_SETSIZE; bits <= (1u << 20); bits *= 2) {
        size_t bytes = CPU_ALLOC_SIZE(bits);
        cpu_set_t *set = CPU_ALLOC(bits);
        if (!set) break;
        CPU_ZERO_S(bytes, set);
        int rc = sched_getaffinity(0, bytes, set), error = errno;
        if (!rc) count = CPU_COUNT_S(bytes, set);
        CPU_FREE(set);
        if (!rc || error != EINVAL) break;
    }
    if (count > 0) return count;
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    return n > 0 && n <= INT_MAX ? (int)n : 1;
}

// [XCDE] T122: not available on this platform
int plat_thread_backtrace(void *pthread_handle, uint64_t *pcs, int max) { (void)pthread_handle; (void)pcs; (void)max; return 0; }
int plat_guest_find(const unsigned char *pat, unsigned long n, unsigned long long *out, int max) { (void)pat; (void)n; (void)out; (void)max; return 0; }  // [XCDE] (not wired)
unsigned long long plat_guest_dump(const char *path) { (void)path; return 0; }  // [XCDE] (not wired)
