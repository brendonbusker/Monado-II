// [XCDE] LINUX-075: RADV reads this environment at Vulkan instance creation.
// Call only during single-threaded startup, before SDL/NGX/Vulkan or workers.
#define _POSIX_C_SOURCE 200809L
#include "radv_dcc_compat.h"
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool separator(char c) {
    // Conservative common Mesa separators. Odd whitespace remains untouched;
    // append a canonical token rather than incorrectly claiming it is active.
    return c == ',' || c == ' ';
}

bool rt_radv_dcc_active(void) {
    const char *cursor = getenv("RADV_DEBUG");
    if (!cursor) return false;
    while (*cursor) {
        while (separator(*cursor)) ++cursor;
        const char *start = cursor;
        while (*cursor && !separator(*cursor)) ++cursor;
        if (cursor - start == 5 && memcmp(start, "nodcc", 5) == 0) return true;
    }
    return false;
}

static int failure(char *error, size_t size, const char *operation, int code) {
    if (error && size) snprintf(error, size, "%s: %s", operation, strerror(code));
    errno = code;
    return -1;
}

int rt_radv_dcc_prepare(char *error, size_t error_size) {
    if (error && error_size) error[0] = '\0';
    const char *policy = getenv("XCDE_RADV_DCC_WORKAROUND");
    if (policy && strcmp(policy, "0") && strcmp(policy, "1"))
        return failure(error, error_size,
                       "XCDE_RADV_DCC_WORKAROUND must be 0 or 1", EINVAL);
    // Opt-out does not remove flags explicitly supplied by a diagnostic caller.
    if ((policy && !strcmp(policy, "0")) || rt_radv_dcc_active()) return 0;
    const char *previous = getenv("RADV_DEBUG");
    size_t length = previous ? strlen(previous) : 0;
    if (length > SIZE_MAX - 7)
        return failure(error, error_size, "RADV_DEBUG is too long", EOVERFLOW);
    char *value = malloc(length + 7);
    if (!value) return failure(error, error_size, "allocate RADV_DEBUG", ENOMEM);
    if (length) {
        memcpy(value, previous, length);
        value[length] = ',';
        memcpy(value + length + 1, "nodcc", 6);
    } else {
        memcpy(value, "nodcc", 6);
    }
    if (setenv("RADV_DEBUG", value, 1)) {
        int saved_errno = errno;
        free(value);
        return failure(error, error_size, "set RADV_DEBUG", saved_errno);
    }
    free(value);
    return 0;
}
