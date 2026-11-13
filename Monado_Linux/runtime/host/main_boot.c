// Headless boot host (M3a): loads the modules, sets up the kernel and runs nn::init::Start, with strict logging of
// every service, SVC and import the game touches. No window, no renderer. Derived from LASRecomp runtime/main.c (MIT). [XCDE]
#include "../diag/diag.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#else
// [XCDE] LINUX-003: preserve startup/retry and diagnostic behavior on Linux.
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#endif

#include "../gamelib.h"
#include "../hle.h"
#include "../kernel.h"
#include "../rt.h"
#ifdef __linux__
#include "../paths.h"
#include "../platform/linux_state_guard.h"
#include "../platform/linux_activity.h"  // [XCDE] LINUX-018
#ifdef XCDE_GFX
#include "../nvn/vulkan/radv_dcc_compat.h"  // [XCDE] LINUX-075
#endif
#endif

const char *g_romfs_dir;

#if defined(XCDE_GFX) && defined(_WIN32)
// [XCDE] T194: laptops with two GPUs (NVIDIA Optimus / AMD switchable graphics) run a program on the integrated one
// unless the exe exports these; the driver reads them at start. (device.c then picks the discrete GPU among those
// Vulkan lists; LARECOMP_GPU=<n> overrides.)
__declspec(dllexport) DWORD NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;
#endif

static void run_array(Cpu *c, uint64_t arr, uint64_t size) {
    for (uint64_t i = 0; i < size / 8; i++) {
        uint64_t fn = ((uint64_t *)arr)[i];
        if (fn) guest_call(c, fn);
    }
}
static void module_init(Cpu *c, Module *m) {
    LOG("init %s (DT_INIT %llx, %llu init_array entries)\n", m->name, (unsigned long long)m->init,
        (unsigned long long)(m->init_array_sz / 8));
    if (m->init) guest_call(c, m->init);
    else run_array(c, m->init_array, m->init_array_sz);
}
static void rtld_init_sdk(Cpu *c) { module_init(c, &g_modules[1]); }
static void rtld_init_main(Cpu *c) { module_init(c, &g_modules[0]); }

__attribute__((constructor(101))) static void reserve_guest_space(void) {
    if (!plat_reserve_guest(GUEST_LO, GUEST_HI)) {
        // [XCDE] T135: something the loader placed at random (ASLR) sits in the guest range in ~1 of 5 starts. A new
        // process gets a new layout: start this one again (same command line, same console), up to 8 times.
        char n[16] = "0";
#ifdef _WIN32
        GetEnvironmentVariableA("XCDE_RELAUNCH", n, sizeof n);
        int tries = atoi(n);
#else
        const char *retry = getenv("XCDE_RELAUNCH");
        char *end = NULL;
        errno = 0;
        long value = retry ? strtol(retry, &end, 10) : 0;
        if (retry && (!*retry || *end || errno || value < 0 || value > 8)) {
            fprintf(stderr, "FATAL: invalid XCDE_RELAUNCH retry count\n");
            exit(1);
        }
        int tries = (int)value;
#endif
        fprintf(stderr, "[boot] guest address range %llx-%llx is not free (try %d)%s\n", (unsigned long long)GUEST_LO,
                (unsigned long long)GUEST_HI, tries + 1, tries < 8 ? ": starting again" : "");
        if (tries < 8) {
            snprintf(n, sizeof n, "%d", tries + 1);
#ifdef _WIN32
            SetEnvironmentVariableA("XCDE_RELAUNCH", n);
            STARTUPINFOA si = {.cb = sizeof si};
            PROCESS_INFORMATION pi;
            char exe[MAX_PATH];
            GetModuleFileNameA(NULL, exe, sizeof exe);
            // the new process dies with this one (a test's timeout or a closed console must not leave it running)
            HANDLE job = CreateJobObjectA(NULL, NULL);
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION jl = {0};
            jl.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if (job) SetInformationJobObject(job, JobObjectExtendedLimitInformation, &jl, sizeof jl);
            if (CreateProcessA(exe, GetCommandLineA(), NULL, NULL, TRUE, CREATE_SUSPENDED, NULL, NULL, &si, &pi)) {
                if (job) AssignProcessToJobObject(job, pi.hProcess);
                ResumeThread(pi.hThread);
                WaitForSingleObject(pi.hProcess, INFINITE);
                DWORD code = 1;
                GetExitCodeProcess(pi.hProcess, &code);
                ExitProcess(code);
            }
#else
            // Same PID/process group: a timeout still owns the relaunched image.
            if (setenv("XCDE_RELAUNCH", n, 1) == 0) plat_exec(NULL);
            fprintf(stderr, "[boot] cannot re-execute after reservation failure: %s\n", strerror(errno));
#endif
        }
        fprintf(stderr, "FATAL: guest address range %llx-%llx is not free\n", (unsigned long long)GUEST_LO,
                (unsigned long long)GUEST_HI);
        exit(1);
    }
}

// [XCDE] Watchdog (T027, first version): every few seconds the state of every guest thread; XCDE_WATCHDOG=<seconds>.
#ifdef _WIN32
static DWORD WINAPI watchdog_main(LPVOID p) {
#else
static void *watchdog_main(void *p) {
#endif
    unsigned secs = (unsigned)(uintptr_t)p;
    for (;;) {
#ifdef _WIN32
        Sleep(secs * 1000);
#else
        plat_sleep_until_ns(plat_now_ns() + (uint64_t)secs * 1000000000ull);
#endif
        LOG("[wd] ---- %u s ----"" %c", secs, 10);
        kernel_dump_threads(stderr);
    }
}


int main(int argc, char **argv) {
#ifdef __linux__
    // [XCDE] LINUX-004: resolve both roots before changing cwd, opening logs,
    // starting diagnostics or dispatching the precompiler. No implicit old state.
    int arg = 1;
    const char *state = getenv("MONADO_STATE_ROOT");
    if (argc > arg && !strcmp(argv[arg], "--state-root")) {
        if (argc <= arg + 1) { fprintf(stderr, "--state-root requires a directory\n"); return 2; }
        state = argv[arg + 1]; arg += 2;
    }
    bool precompile = argc > arg && !strcmp(argv[arg], "--precompile");
    if (precompile) arg++;
    if (argc <= arg || !strcmp(argv[arg], "--help")) {
        fprintf(stderr, "usage: xcde_boot --state-root <Linux state dir> [--precompile] <dump dir with exefs/ and romfs/> [seconds]\n");
        return 2;
    }
    char error[1024];
    if (!rt_paths_init_linux(argv[arg], state, error, sizeof error) ||
        !rt_linux_state_guard(rt_data_root(), error, sizeof error) ||
        !rt_linux_activity_acquire(rt_data_root(), error, sizeof error)) {
        fprintf(stderr, "FATAL: Linux state isolation: %s\n", error);
        return 1;
    }
    const char *root = rt_input_root();
    int seconds = argc > arg + 1 ? atoi(argv[arg + 1]) : 20;
#ifdef XCDE_GFX
    // [XCDE] LINUX-075: RADV reads its driver flags when Vulkan initializes.
    // Prepare them while still single-threaded, including the precompile path;
    // never mutate the environment later in SDL/render/guest workers.
    if (rt_radv_dcc_prepare(error, sizeof error) < 0) {
        fprintf(stderr, "FATAL: RADV DCC compatibility: %s\n", error);
        return 1;
    }
#endif
    plat_init();
    setvbuf(stderr, NULL, _IONBF, 0);
    if (precompile) {
#ifdef XCDE_GFX
        extern int vk_precompile_main(const char *root);
        return vk_precompile_main(root);
#else
        fprintf(stderr, "precompile requires the graphics build\n");
        return 2;
#endif
    }
#else
    if (argc >= 6 && !strcmp(argv[1], "--minidump")) return diag_minidump_helper(argc, argv);  // [XCDE] T028: crash helper process
#ifdef XCDE_GFX
    if (argc >= 3 && !strcmp(argv[1], "--precompile")) {  // [XCDE] T187: fill the shader cache from the RomFS, then exit
        extern int vk_precompile_main(const char *root);
        return vk_precompile_main(argv[2]);
    }
#endif
    plat_init();
    setvbuf(stderr, NULL, _IONBF, 0);
    if (argc < 2) { fprintf(stderr, "usage: xcde_boot <dump dir with exefs/ and romfs/> [seconds]\n"); return 2; }
    const char *root = argv[1];
    int seconds = argc > 2 ? atoi(argv[2]) : 20;
#endif
    char exefs[1024], romfs[1024], npdm_path[1024];
    // [XCDE] LINUX-004: truncated input paths must never select a different file.
    if (snprintf(exefs, sizeof exefs, "%s/exefs", root) >= (int)sizeof exefs ||
        snprintf(romfs, sizeof romfs, "%s/romfs", root) >= (int)sizeof romfs ||
        snprintf(npdm_path, sizeof npdm_path, "%s/main.npdm", exefs) >= (int)sizeof npdm_path) {
        fprintf(stderr, "FATAL: game input path is too long\n");
        return 1;
    }
    g_romfs_dir = strdup(romfs);
    if (!g_romfs_dir) { fprintf(stderr, "FATAL: cannot retain RomFS path\n"); return 1; }

    diag_watchdog_start();
    if (getenv("XCDE_WATCHDOG")) {
#ifdef _WIN32
        CreateThread(NULL, 0, watchdog_main, (LPVOID)(uintptr_t)atoi(getenv("XCDE_WATCHDOG")), 0, NULL);
#else
        const char *value = getenv("XCDE_WATCHDOG");
        char *end;
        errno = 0;
        unsigned long parsed = strtoul(value, &end, 10);
        if (*value < '0' || *value > '9' || *end || errno || !parsed || parsed > UINT_MAX)
            FATAL("XCDE_WATCHDOG must specify a positive interval in seconds (1..%u)\n", UINT_MAX);
        unsigned secs = (unsigned)parsed;
        pthread_t thread;
        int rc = pthread_create(&thread, NULL, watchdog_main, (void *)(uintptr_t)secs);
        if (rc) FATAL("cannot start periodic watchdog: %s\n", strerror(rc));
        // Process-lifetime diagnostic worker, as in the original Windows host.
        rc = pthread_detach(thread);
        if (rc) FATAL("cannot detach periodic watchdog: %s\n", strerror(rc));
#endif
    }
    loader_load(exefs);
    kernel_init();
    dispatch_init();

    uint32_t stack_size = 0x100000;
    int prio = 44;
    FILE *f = fopen(npdm_path, "rb");
    if (f) {
        uint8_t meta[0x80];
        if (fread(meta, 1, sizeof meta, f) == sizeof meta && !memcmp(meta, "META", 4)) {
            prio = meta[0xE];
            stack_size = *(uint32_t *)(meta + 0x1C);
        }
        fclose(f);
    }
    LOG("main thread: prio %d, stack 0x%x\n", prio, stack_size);

    uint64_t start = loader_find_symbol("_ZN2nn4init5StartEmmPFvvES2_");
    if (!start) FATAL("nn::init::Start not found\n");
    uint64_t init_fn = hle_register("<rtld_init_sdk>", rtld_init_sdk);
    uint64_t fini_fn = hle_register("<rtld_init_main>", rtld_init_main);
    KThread *t = kernel_create_main_thread(start, stack_size, prio);
    kernel_run_main(t, t->handle, 0, init_fn, fini_fn);
#ifdef XCDE_GFX
    extern int ui_run(void);  // window + Vulkan presenter on the main thread (runtime/nvn/vulkan/device.c)
    LOG("[boot] running with the window\n");
    (void)seconds;
    return ui_run();
#else
    LOG("[boot] running; stopping after %d s\n", seconds);
    plat_sleep_until_ns(plat_now_ns() + (uint64_t)seconds * 1000000000ull);
    LOG("[boot] timeout reached, exiting\n");
    return 0;
#endif
}
