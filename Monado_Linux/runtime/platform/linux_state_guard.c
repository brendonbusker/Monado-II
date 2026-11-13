// [XCDE] LINUX-004: write confinement for shared immutable game input.
// Landlock ABI 3 supplies both cross-directory REFER and TRUNCATE enforcement.
// See https://docs.kernel.org/userspace-api/landlock.html . Apply before threads;
// descriptors opened before enforcement retain their rights, so audit them first.
#define _GNU_SOURCE
#include "linux_state_guard.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/landlock.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static bool fail(char *error, size_t size, const char *format, ...) {
    va_list args;
    va_start(args, format);
    if (error && size) vsnprintf(error, size, format, args);
    va_end(args);
    return false;
}

static bool below(const char *path, const char *root) {
    size_t n = strlen(root);
    return !strncmp(path, root, n) && (path[n] == '/' || path[n] == 0);
}

static bool single_thread(char *error, size_t size) {
    DIR *dir = opendir("/proc/self/task");
    if (!dir) return fail(error, size, "cannot inspect runtime threads: %s", strerror(errno));
    unsigned count = 0;
    struct dirent *entry;
    while ((entry = readdir(dir))) if (entry->d_name[0] >= '0' && entry->d_name[0] <= '9') count++;
    closedir(dir);
    return count == 1 || fail(error, size, "state guard must precede runtime threads (found %u)", count);
}

static bool inherited_files(const char *state, char *error, size_t size) {
    DIR *dir = opendir("/proc/self/fd");
    if (!dir) return fail(error, size, "cannot inspect inherited files: %s", strerror(errno));
    struct dirent *entry;
    bool ok = true;
    while (ok && (entry = readdir(dir))) {
        char *end;
        long fd = strtol(entry->d_name, &end, 10);
        if (*end || fd < 0 || fd > INT_MAX) continue;
        struct stat st;
        int flags = fcntl((int)fd, F_GETFL);
        if (flags < 0 || fstat((int)fd, &st)) { ok = fail(error, size, "cannot inspect inherited fd %ld", fd); break; }
        if (!S_ISREG(st.st_mode) || (flags & O_ACCMODE) == O_RDONLY) continue;
        char link[64], path[PATH_MAX];
        snprintf(link, sizeof link, "/proc/self/fd/%ld", fd);
        ssize_t n = readlink(link, path, sizeof path - 1);
        if (n < 0 || n >= (ssize_t)sizeof path - 1) { ok = fail(error, size, "cannot resolve writable fd %ld", fd); break; }
        path[n] = 0;
        if (!below(path, state) || st.st_nlink != 1)
            ok = fail(error, size, "writable inherited fd %ld is outside isolated state or multiply linked", fd);
    }
    closedir(dir);
    return ok;
}

static int add_path(int ruleset, const char *path, uint64_t access, bool device) {
    int fd = open(path, O_PATH | O_CLOEXEC);
    if (fd < 0) return device && errno == ENOENT ? 0 : -1;
    struct stat st;
    if (fstat(fd, &st)) { close(fd); return -1; }
    if (device && !S_ISCHR(st.st_mode)) { close(fd); return 0; }
    struct landlock_path_beneath_attr rule = {.allowed_access = access, .parent_fd = fd};
    int result = (int)syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0);
    int saved = errno;
    close(fd); errno = saved;
    return result;
}

static int devices_in(int ruleset, const char *path, const char *prefix) {
    DIR *dir = opendir(path);
    if (!dir) return errno == ENOENT ? 0 : -1;
    struct dirent *entry;
    int result = 0;
    while ((entry = readdir(dir))) {
        if (entry->d_name[0] == '.' || (prefix && strncmp(entry->d_name, prefix, strlen(prefix)))) continue;
        char name[PATH_MAX];
        if (snprintf(name, sizeof name, "%s/%s", path, entry->d_name) >= (int)sizeof name) { errno = ENAMETOOLONG; result = -1; break; }
        if (add_path(ruleset, name, LANDLOCK_ACCESS_FS_WRITE_FILE, true)) { result = -1; break; }
    }
    int saved = errno; closedir(dir); errno = saved;
    return result;
}

// [XCDE] LINUX-077: SDL's HIDAPI opens controller nodes read/write, including
// the Deck's built-in controller. Admit existing hidraw character devices only;
// neither a prefix lookalike nor a symlink may widen the writable file policy.
static bool hidraw_name(const char *name) {
    if (strncmp(name, "hidraw", 6) || name[6] < '0' || name[6] > '9') return false;
    for (const char *p = name + 7; *p; ++p)
        if (*p < '0' || *p > '9') return false;
    return true;
}

static int hidraw_devices(int ruleset) {
    DIR *dir = opendir("/dev");
    if (!dir) return -1;
    struct dirent *entry;
    int result = 0;
    while ((entry = readdir(dir))) {
        if (!hidraw_name(entry->d_name)) continue;
        int fd = openat(dirfd(dir), entry->d_name, O_PATH | O_NOFOLLOW | O_CLOEXEC);
        // A device disappearing while enumerating is normal hotplug behavior.
        if (fd < 0) {
            if (errno == ENOENT) continue;
            result = -1; break;
        }
        struct stat st;
        if (fstat(fd, &st)) { int saved = errno; close(fd); errno = saved; result = -1; break; }
        if (S_ISCHR(st.st_mode)) {
            struct landlock_path_beneath_attr rule = {
                .allowed_access = LANDLOCK_ACCESS_FS_WRITE_FILE, .parent_fd = fd
            };
            result = (int)syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0);
        }
        int saved = errno; close(fd); errno = saved;
        if (result) break;
    }
    int saved = errno; closedir(dir); errno = saved;
    return result;
}

bool rt_linux_state_guard(const char *state, char *error, size_t size) {
    char canonical[PATH_MAX];
    struct stat st;
    if (!state || state[0] != '/' || !realpath(state, canonical) || strcmp(state, canonical) ||
        !strcmp(state, "/") || stat(state, &st) || !S_ISDIR(st.st_mode))
        return fail(error, size, "state guard requires an existing canonical state directory");
    if (!single_thread(error, size) || !inherited_files(state, error, size)) return false;
    int abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 3) return fail(error, size, "Landlock ABI >=3 required for state isolation (available %d, %s)", abi, strerror(errno));
    const uint64_t writes = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
        LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_REFER |
        LANDLOCK_ACCESS_FS_TRUNCATE;
    struct landlock_ruleset_attr rules = {.handled_access_fs = writes};
    int fd = (int)syscall(SYS_landlock_create_ruleset, &rules, sizeof rules, 0);
    if (fd < 0) return fail(error, size, "cannot create state guard: %s", strerror(errno));
    // Creating device nodes is unnecessary even inside state; ordinary files,
    // directories, symlinks and Unix sockets support caches and runtime services.
    uint64_t allowed = writes & ~(LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_BLOCK);
    int rc = add_path(fd, state, allowed, false);
    const char *devices[] = {"/dev/null", "/dev/zero", "/dev/tty", "/dev/ptmx"};
    for (size_t i = 0; !rc && i < sizeof devices / sizeof devices[0]; ++i)
        rc = add_path(fd, devices[i], LANDLOCK_ACCESS_FS_WRITE_FILE, true);
    if (!rc) rc = devices_in(fd, "/dev", "nvidia");
    if (!rc) rc = hidraw_devices(fd);
    const char *directories[] = {"/dev/dri", "/dev/nvidia-caps", "/dev/snd", "/dev/input"};
    for (size_t i = 0; !rc && i < sizeof directories / sizeof directories[0]; ++i)
        rc = devices_in(fd, directories[i], NULL);
    if (!rc) rc = prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);
    if (!rc) rc = (int)syscall(SYS_landlock_restrict_self, fd, 0);
    int saved = errno; close(fd);
    if (rc) return fail(error, size, "cannot enforce state guard: %s", strerror(saved));
    if (error && size) error[0] = 0;
    fprintf(stderr, "[paths] state write guard active (Landlock ABI %d)\n", abi);
    return true;
}
