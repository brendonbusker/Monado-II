// [XCDE] LINUX-075: authored environment tests; no game, driver or profile.
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int fail_allocation, fail_environment, allocations, writes;
static void *fixture_malloc(size_t size) {
    ++allocations;
    return fail_allocation ? NULL : malloc(size);
}
static int fixture_setenv(const char *key, const char *value, int overwrite) {
    ++writes;
    if (fail_environment) { errno = ENOMEM; return -1; }
    return setenv(key, value, overwrite);
}
#define malloc fixture_malloc
#define setenv fixture_setenv
#include "../../runtime/nvn/vulkan/radv_dcc_compat.c"
#undef malloc
#undef setenv

static void reset(const char *flags, const char *policy) {
    assert(!unsetenv("RADV_DEBUG"));
    assert(!unsetenv("XCDE_RADV_DCC_WORKAROUND"));
    if (flags) assert(!setenv("RADV_DEBUG", flags, 1));
    if (policy) assert(!setenv("XCDE_RADV_DCC_WORKAROUND", policy, 1));
    fail_allocation = fail_environment = allocations = writes = 0;
}
static void same(const char *expected) {
    const char *actual = getenv("RADV_DEBUG");
    assert(expected ? actual && !strcmp(actual, expected) : !actual);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    char error[160];
    const char *scenario = argv[1];
    if (!strcmp(scenario, "append")) {
        const char *cases[] = {NULL, "", "info,shaders", "nodccmsaa", "-nodcc", "info\tnodcc"};
        const char *expected[] = {"nodcc", "nodcc", "info,shaders,nodcc", "nodccmsaa,nodcc", "-nodcc,nodcc", "info\tnodcc,nodcc"};
        for (size_t i = 0; i < sizeof(cases)/sizeof(*cases); ++i) {
            reset(cases[i], NULL);
            assert(!rt_radv_dcc_active());
            assert(!rt_radv_dcc_prepare(error, sizeof(error)) && !*error);
            same(expected[i]);
            assert(rt_radv_dcc_active());
            assert(allocations == 1 && writes == 1);
            assert(!rt_radv_dcc_prepare(error, sizeof(error)));
            assert(allocations == 1 && writes == 1);
        }
    } else if (!strcmp(scenario, "existing")) {
        const char *cases[] = {"nodcc", "info,nodcc,shaders", " nodcc ", ",,nodcc,,"};
        for (size_t i = 0; i < sizeof(cases)/sizeof(*cases); ++i) {
            reset(cases[i], NULL);
            assert(rt_radv_dcc_active());
            assert(!rt_radv_dcc_prepare(error, sizeof(error)));
            same(cases[i]);
            assert(!allocations && !writes);
        }
    } else if (!strcmp(scenario, "policy")) {
        reset(NULL, "0");
        assert(!rt_radv_dcc_prepare(error, sizeof(error)));
        same(NULL); assert(!allocations && !writes && !rt_radv_dcc_active());
        reset("info,nodcc", "0");
        assert(!rt_radv_dcc_prepare(error, sizeof(error)));
        same("info,nodcc"); assert(!writes && rt_radv_dcc_active());
        reset("info", "1");
        assert(!rt_radv_dcc_prepare(NULL, 0)); same("info,nodcc");
        const char *invalid[] = {"", "true", "2", " 0", "01"};
        for (size_t i = 0; i < sizeof(invalid)/sizeof(*invalid); ++i) {
            reset("info", invalid[i]);
            assert(rt_radv_dcc_prepare(error, sizeof(error)) == -1);
            assert(errno == EINVAL && strstr(error, "must be 0 or 1"));
            same("info"); assert(!allocations && !writes);
        }
    } else if (!strcmp(scenario, "failures")) {
        reset("info", NULL); fail_allocation = 1;
        assert(rt_radv_dcc_prepare(error, sizeof(error)) == -1);
        assert(errno == ENOMEM && strstr(error, "allocate"));
        same("info"); assert(!writes);
        reset("info", NULL); fail_environment = 1;
        assert(rt_radv_dcc_prepare(error, sizeof(error)) == -1);
        assert(errno == ENOMEM && strstr(error, "set RADV_DEBUG"));
        same("info"); assert(writes == 1);
        char tiny[1];
        assert(rt_radv_dcc_prepare(tiny, sizeof(tiny)) == -1 && !tiny[0]);
    } else return 2;
    printf("RADV DCC compatibility: PASS %s\n", scenario);
    return 0;
}
