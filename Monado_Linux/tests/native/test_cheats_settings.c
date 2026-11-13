// [XCDE] LINUX-072: actual settings load/save and fixed-point math, authored data only.
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../runtime/settings.h"
#include "../../runtime/input_bind.h"
#include "../../runtime/hle/cheats_math.h"

extern bool g_party_switch;
bool bind_settings_load(const char *k, const char *v) { (void)k; (void)v; return false; }
void bind_settings_save(FILE *f) { fputs("bind_key_a = Return\n", f); }
#define CHEATS(X) X(damage_dealt) X(damage_received) X(exp) X(ap) X(sp) X(gold)
#define NAME(x) #x,
static const char *names[] = { CHEATS(NAME) };
#undef NAME
#define ENABLE(x) offsetof(Settings, cheat_##x),
static const size_t enables[] = { CHEATS(ENABLE) };
#undef ENABLE
#define PERCENT(x) offsetof(Settings, cheat_##x##_percent),
static const size_t percents[] = { CHEATS(PERCENT) };
#undef PERCENT
static bool *enabled(unsigned n) { return (bool *)((char *)&g_settings + enables[n]); }
static int *percent(unsigned n) { return (int *)((char *)&g_settings + percents[n]); }
static const char *ini;
static void write_all(const char *on, const char *amount) {
    FILE *f = fopen(ini, "w"); assert(f);
    for (unsigned i = 0; i < 6; ++i)
        fprintf(f, "cheat_%s = %s\ncheat_%s_percent = %s\n", names[i], on, names[i], amount);
    fprintf(f, "cheat_no_fall_damage = %s\nparty_switch = 1\nquickstep_slot = 1\n", on);
    assert(!fclose(f));
}
static void expect(bool on, int amount) {
    for (unsigned i = 0; i < 6; ++i) { assert(*enabled(i) == on); assert(*percent(i) == amount); }
    assert(g_settings.cheat_no_fall_damage == on);
}
int main(int argc, char **argv) {
    assert(argc == 2); ini = argv[1]; assert(!setenv("XCDE_INI", ini, 1));
    remove(ini); settings_load(); expect(false, 100);
    const char *bad[] = {"", "-1", "+100", "2001", "nan", "1.5", "100junk", "999999999999999999999999999999999999999999"};
    for (unsigned i = 0; i < sizeof bad / sizeof *bad; ++i) {
        write_all("true", bad[i]); settings_load(); expect(true, 100);
    }
    const char *off[] = {"", "0", "false", "2", "TRUE", "1junk", "-1"};
    for (unsigned i = 0; i < sizeof off / sizeof *off; ++i) {
        write_all(off[i], "125"); settings_load(); expect(false, 125);
    }
    for (int n = 0; n <= 2000; ++n) {
        char text[32]; snprintf(text, sizeof text, "%d", n);
        write_all("1", text); settings_load(); expect(true, n);
        settings_save();
        for (unsigned i = 0; i < 6; ++i) { *enabled(i) = false; *percent(i) = 100; }
        g_settings.cheat_no_fall_damage = false;
        settings_load(); expect(true, n);
        assert(g_party_switch && g_settings.quickstep_slot);
    }
    // Enabling one cheat never enables another; slider positions survive while off.
    write_all("0", "150"); settings_load();
    g_settings.cheat_exp = true; g_settings.cheat_exp_percent = 201;
    settings_save(); settings_load();
    for (unsigned i = 0; i < 6; ++i) {
        assert(*enabled(i) == (i == 2)); assert(*percent(i) == (i == 2 ? 201 : 150));
    }
    remove(ini); settings_load(); expect(false, 100);
    // Oracle uses wider arithmetic only in this fixture, including extreme bounds.
    const uint64_t values[] = {0, 1, 2, 99, 100, 101, 999999, UINT32_MAX, UINT64_MAX - 1, UINT64_MAX};
    const uint64_t caps[] = {0, 1, 999, UINT32_MAX, UINT64_MAX};
    for (int p = 0; p <= 2000; ++p) for (unsigned i = 0; i < sizeof values / sizeof *values; ++i)
        for (unsigned j = 0; j < sizeof caps / sizeof *caps; ++j) {
            __uint128_t exact = (__uint128_t)values[i] * (unsigned)p / 100;
            uint64_t want = exact > caps[j] ? caps[j] : (uint64_t)exact;
            assert(xcde_cheat_scale(values[i], p, caps[j]) == want);
        }
    assert(xcde_cheat_scale(123, -1, UINT64_MAX) == 123);
    assert(xcde_cheat_scale(123, 2001, UINT64_MAX) == 123);
    puts("cheats settings: all 2001 positions round-trip, independent flags/defaults and 100050 arithmetic cases PASS");
    return 0;
}
