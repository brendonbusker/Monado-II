// [XCDE] LINUX-120: authored party speed cases; no game code, files or saves.
#define _GNU_SOURCE
#include <assert.h>
#include <fenv.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "../../runtime/hle/cheats_movement.h"
#include "../../runtime/cheats_options.h"
#include "../../runtime/rt.h"
#pragma STDC FENV_ACCESS ON

Settings g_settings;
void rt_fatal_trace(void) { abort(); }
static unsigned cases;
static const uint64_t status = GUEST_LO + 0x1000, movement = GUEST_LO + 0x2000,
                      vtable = GUEST_LO + 0x3000;
static uint32_t bits(float value) { uint32_t b; memcpy(&b, &value, 4); return b; }
static float scalar(uint32_t b) { float v; memcpy(&v, &b, 4); return v; }
static void check(bool enabled, int percent, uint32_t native, uint64_t kind, int rounding) {
    memset(&g_settings, 0, sizeof g_settings);
    g_settings.cheat_movement_speed = enabled;
    g_settings.cheat_movement_speed_percent = percent;
    xcde_cheats_publish(&g_settings);
    memset((void *)(uintptr_t)GUEST_LO, 0xab, 0x4000);
    ST64(status, vtable); ST64(vtable + 8, kind);
    Cpu cpu, expected;
    memset(&cpu, 0x6b, sizeof cpu);
    cpu.x[19] = movement; cpu.x[21] = status;
    memcpy(&cpu.v[0], &native, 4);
    expected = cpu;
    uint32_t result = native;
    assert(fesetround(FE_TONEAREST) == 0);
    if (enabled && percent >= 0 && percent <= 2000 && percent != 100 &&
        kind == 0x700047f750ull && native && native < 0x7f800000u) {
        long double exact = (long double)scalar(native) * percent / 100.L;
        result = exact >= FLT_MAX ? bits(FLT_MAX) : bits((float)exact);
    }
    memcpy(&expected.v[0], &result, 4);
    unsigned char memory[0x4000]; memcpy(memory, (void *)(uintptr_t)GUEST_LO, sizeof memory);
    assert(feclearexcept(FE_ALL_EXCEPT) == 0);
    assert(feraiseexcept(FE_DIVBYZERO | FE_INEXACT) == 0);
    assert(fesetround(rounding) == 0);
    int exceptions = fetestexcept(FE_ALL_EXCEPT);
    xcde_cheats_movement_speed(&cpu);
    assert(fegetround() == rounding && fetestexcept(FE_ALL_EXCEPT) == exceptions);
    assert(!memcmp(&cpu, &expected, sizeof cpu));
    assert(!memcmp(memory, (void *)(uintptr_t)GUEST_LO, sizeof memory));
    // Model only the checked original scalar STR after the production helper.
    // All other component fields, including vertical velocity +0x134, are exact.
    memcpy((void *)(uintptr_t)(movement + 0x2c), &cpu.v[0], 4);
    memcpy(memory + (movement - GUEST_LO) + 0x2c, &result, 4);
    assert(!memcmp(memory, (void *)(uintptr_t)GUEST_LO, sizeof memory));
    ++cases;
}
int main(void) {
    void *mapped = mmap((void *)(uintptr_t)GUEST_LO, 0x4000, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    assert(mapped == (void *)(uintptr_t)GUEST_LO);
    const float native[] = {0.5f, 0.75f, 1.f, 1.2f, 1.25f, 1.5f, 2.f, 10.f};
    for (int percent = 0; percent <= 2000; ++percent)
        for (unsigned i = 0; i < sizeof native / sizeof *native; ++i)
            check(true, percent, bits(native[i]), 0x700047f750ull, FE_UPWARD);
    const uint32_t exceptional[] = {0, 0x80000000, 1, 0x007fffff, 0x7f7fffff,
                                   0xbf800000, 0x7f800000, 0xff800000, 0x7fc01234, 0x7f801234};
    for (unsigned i = 0; i < sizeof exceptional / sizeof *exceptional; ++i)
        for (int percent = 0; percent <= 2000; percent += 100)
            check(true, percent, exceptional[i], 0x700047f750ull, FE_DOWNWARD);
    const int values[] = {-1, 0, 1, 99, 100, 101, 2000, 2001};
    for (unsigned i = 0; i < sizeof values / sizeof *values; ++i) {
        check(false, values[i], bits(1.2f), 0x700047f750ull, FE_TOWARDZERO);
        check(true, values[i], bits(1.2f), 0x700047f760ull, FE_TOWARDZERO); // enemy/foreign kind
    }
    // No guest read at all when disabled/1x, even with intentionally bad pointers.
    for (unsigned enabled = 0; enabled < 2; ++enabled) {
        Cpu cpu = {0}; g_settings.cheat_movement_speed = enabled;
        g_settings.cheat_movement_speed_percent = enabled ? 100 : 2000;
        xcde_cheats_publish(&g_settings); Cpu before = cpu;
        xcde_cheats_movement_speed(&cpu); assert(!memcmp(&cpu, &before, sizeof cpu));
    }
    g_settings.cheat_movement_speed = true; g_settings.cheat_movement_speed_percent = 2000;
    xcde_cheats_publish(&g_settings);
    const uint64_t invalid[] = {0, GUEST_LO - 1, GUEST_HI - 8, GUEST_HI};
    for (unsigned i = 0; i < sizeof invalid / sizeof *invalid; ++i) {
        Cpu cpu = {0}; cpu.x[19] = movement; cpu.x[21] = invalid[i]; Cpu before = cpu;
        xcde_cheats_movement_speed(&cpu); assert(!memcmp(&cpu, &before, sizeof cpu));
    }
    assert(fesetround(FE_TONEAREST) == 0);
    assert(munmap(mapped, 0x4000) == 0);
    printf("PASS movement: %u scalar/event/FP/memory cases, all 2001 steps, identity and kind guards\n", cases);
}
