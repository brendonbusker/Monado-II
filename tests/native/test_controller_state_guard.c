// [XCDE] LINUX-077: authored device-policy fixture, no actual controller I/O.
#ifndef MONADO_GUARD_SOURCE
#define MONADO_GUARD_SOURCE "../../Monado_Linux/runtime/platform/linux_state_guard.c"
#endif
#include MONADO_GUARD_SOURCE
#include <assert.h>

static void denied_write(const char *path) {
    errno = 0;
    int fd = open(path, O_RDWR | O_CLOEXEC);
    assert(fd < 0 && errno == EACCES);
    errno = 0;
    fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
    assert(fd < 0 && errno == EACCES);
}

int main(int argc, char **argv) {
    assert(argc >= 2);
#ifndef MONADO_GUARD_BASELINE
    if (!strcmp(argv[1], "names")) {
        const char *valid[] = {"hidraw0", "hidraw1", "hidraw999", "hidraw0001"};
        const char *invalid[] = {"", "hidraw", "hidraw-1", "hidraw1x", "hidraw/1", "HIDRAW1", "hidraw1\n"};
        for (size_t i = 0; i < sizeof valid / sizeof *valid; ++i) assert(hidraw_name(valid[i]));
        for (size_t i = 0; i < sizeof invalid / sizeof *invalid; ++i) assert(!hidraw_name(invalid[i]));
        puts("controller state guard: PASS names"); return 0;
    }
#endif
    assert(argc == 5);
    const char *state = argv[2], *protected = argv[3], *node = argv[4];
    int inherited = -1;
    if (!strcmp(argv[1], "inherit")) {
        inherited = open(protected, O_RDWR | O_CLOEXEC);
        assert(inherited >= 0);
    }
    char error[512];
    bool guarded = rt_linux_state_guard(state, error, sizeof error);
    if (inherited >= 0) {
        assert(!guarded && strstr(error, "writable inherited fd")); close(inherited);
        puts("controller state guard: PASS inherit"); return 0;
    }
    if (!guarded && strstr(error, "Landlock ABI >=3 required")) { fprintf(stderr, "%s\n", error); return 77; }
    if (!guarded) { fprintf(stderr, "%s\n", error); return 1; }
    // /dev/full is only opened, never written. Binding /dev/null here would
    // alias an already-whitelisted inode and conceal the original guard bug.
    if (!strcmp(argv[1], "allow") || !strcmp(argv[1], "baseline")) {
        struct stat a, b; assert(!stat("/dev/null", &a) && !stat(node, &b));
        assert(a.st_dev != b.st_dev || a.st_ino != b.st_ino);
    }
    int device = open(node, O_RDWR | O_CLOEXEC);
    if (!strcmp(argv[1], "allow")) { assert(device >= 0); close(device); }
    else { assert(device < 0 && errno == EACCES); }
    denied_write(protected);
    errno = 0; assert(unlink(protected) < 0 && errno == EACCES);
    char local[PATH_MAX]; assert(snprintf(local, sizeof local, "%s/ordinary", state) < (int)sizeof local);
    int own = open(local, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    assert(own >= 0 && write(own, "authored", 8) == 8); close(own);
    errno = 0; assert(rename(protected, local) < 0 && errno == EACCES);
    assert(!unlink(local));
    int read_only = open(protected, O_RDONLY | O_CLOEXEC); assert(read_only >= 0); close(read_only);
    printf("controller state guard: PASS %s\n", argv[1]); return 0;
}
