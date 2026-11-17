// Authored synthetic actor/stat fixtures, no game functions or assets.
#define _GNU_SOURCE
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include "../../runtime/hle/cheats_enemy_health.h"
#include "../../runtime/cheats_options.h"

Settings g_settings;
void rt_fatal_trace(void) { _Exit(86); }
extern void (*__start_resets[])(void);
extern void (*__stop_resets[])(void);

static const uint64_t base = UINT64_C(0x7002000000);
static const uint64_t table = UINT64_C(0x7002001000);
static const uint64_t actor = UINT64_C(0x7002004000);
static const uint64_t second = UINT64_C(0x7002008000);
static const uint64_t stats_offset = 0x149c;
static unsigned checks;
static uint64_t pending_native_init;

static void request(int percent, bool enabled) {
    g_settings.cheat_enemy_health = enabled;
    g_settings.cheat_enemy_health_percent = percent;
    xcde_cheats_publish(&g_settings);
}
static Cpu cpu(void) {
    Cpu c; memset(&c, 0x37, sizeof c); c.sp = base + 0x20000;
    c.fpcr = 0; c.fpsr = 0;
    return c;
}
static uint64_t stats(uint64_t a) { return a + stats_offset; }
static uint32_t hp(uint64_t a) { return LD32(stats(a) + 8); }
static uint32_t maxhp(uint64_t a) { return LD32(stats(a) + 0xe8); }
static void check_cpu(const Cpu *got, const Cpu *want) {
    assert(!memcmp(got, want, sizeof *got)); ++checks;
}
static void construct(uint64_t a) {
    Cpu c = cpu(); c.x[0] = a; Cpu before = c;
    xcde_cheats_enemy_health_construct(&c); check_cpu(&c, &before);
    memset((void *)(uintptr_t)a, 0, 0x1700); ST64(a, table);
    if (pending_native_init == a) pending_native_init = 0;
}
static void begin_init(uint64_t a, uint32_t current) {
    Cpu c = cpu(); c.x[0] = a; Cpu before = c;
    xcde_cheats_enemy_health_initialize(&c); check_cpu(&c, &before);
    ST32(stats(a) + 8, current); ST32(stats(a) + 0x40, current);
    pending_native_init = a;
}
static void recompute(uint64_t a, uint32_t native, uint32_t want_max, uint32_t want_hp) {
    Cpu c = cpu(); c.x[0] = stats(a); c.x[3] = a; Cpu before = c;
    c.x[30] = pending_native_init == a ? UINT64_C(0x700047ebc0) : UINT64_C(0x700047fcfc);
    before = c;
    xcde_cheats_enemy_health_recompute_begin(&c); check_cpu(&c, &before);
    // The native recompute overwrites derived storage from its fresh base before
    // the final result. This poison catches reading the old maximum too late.
    ST32(stats(a) + 0xe8, 0x76543210);
    c.sp -= 0xb0; c.x[19] = stats(a); c.x[20] = a; c.x[8] = native;
    before = c; before.x[8] = want_max;
    xcde_cheats_enemy_health_max(&c); check_cpu(&c, &before);
    ST32(stats(a) + 0xe8, (uint32_t)c.x[8]); // authored original STR continuation
    assert(maxhp(a) == want_max && hp(a) == want_hp); ++checks;
    if (pending_native_init == a) pending_native_init = 0;
}
static void update(uint64_t a, bool dirty) {
    ST64(a + 0x1030, 0x1234);
    Cpu c = cpu(); c.x[19] = a; Cpu before = c;
    xcde_cheats_enemy_health_update(&c); check_cpu(&c, &before);
    assert(LD64(a + 0x1030) == (UINT64_C(0x1234) | (dirty ? UINT64_C(1) << 32 : 0)));
    ++checks;
}
static void dispose(uint64_t a, bool component) {
    Cpu c = cpu(); c.x[0] = component ? a - 0x60 : a; Cpu before = c;
    if (component) xcde_cheats_enemy_health_destroy_component(&c);
    else xcde_cheats_enemy_health_destroy(&c);
    check_cpu(&c, &before);
    if (pending_native_init == a) pending_native_init = 0;
}

static void early_refresh(uint64_t a, uint32_t native) {
    uint32_t old_hp = hp(a);
    Cpu c = cpu(); c.x[0] = stats(a); c.x[3] = a;
    c.x[30] = UINT64_C(0x700047fcfc); Cpu before = c;
    xcde_cheats_enemy_health_recompute_begin(&c); check_cpu(&c, &before);
    // An ordinary loading refresh can compute native minimum1 before base HP
    // initialization. The cheat must neither scale it nor read prior HP as live.
    ST32(stats(a) + 0xe8, native);
    c.sp -= 0xb0; c.x[19] = stats(a); c.x[20] = a; c.x[8] = native; before = c;
    xcde_cheats_enemy_health_max(&c); check_cpu(&c, &before);
    assert(hp(a) == old_hp && maxhp(a) == native); ++checks;
}

static void invalid_ready_hp(uint32_t current, uint32_t maximum, uint32_t native) {
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        ST32(stats(actor) + 8, current); ST32(stats(actor) + 0xe8, maximum);
        request(200, true);
        Cpu c = cpu(); c.x[0] = stats(actor); c.x[3] = actor; c.x[30] = UINT64_C(0x700047fcfc);
        xcde_cheats_enemy_health_recompute_begin(&c);
        c.sp -= 0xb0; c.x[19] = stats(actor); c.x[20] = actor; c.x[8] = native;
        xcde_cheats_enemy_health_max(&c);
        _Exit(1); // Invalid initialized HP must still fail closed.
    }
    int status = 0; assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 86); ++checks;
}
static uint32_t expected_max(uint32_t n, unsigned percent) {
    uint64_t value = (uint64_t)n * percent / 100;
    uint32_t floor = n < 100 ? n : 100;
    return value < floor ? floor : value > INT32_MAX ? INT32_MAX : (uint32_t)value;
}

int main(void) {
    assert(mmap((void *)(uintptr_t)base, 0x40000, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) == (void *)(uintptr_t)base);
    ST64(table + 8, UINT64_C(0x700047f780));
    ST64(table + 0xc8, UINT64_C(0x700047f2b0));

    // Regression for the real loading crash: construction leaves HP storage
    // uninitialized. Generic refresh is legal before the base initializer and
    // can observe0, poison, or unsigned-looking values at2x/20x/Off/explicit1x.
    const uint32_t loading_values[] = {0, 1, UINT32_MAX, UINT32_C(0xa5a5a5a5)};
    const int loading_percent[] = {200, 2000, 100, 100};
    for (unsigned mode = 0; mode < 4; ++mode) for (unsigned i = 0; i < 4; ++i)
      for (unsigned j = 0; j < 4; ++j) {
        request(loading_percent[mode], mode != 2); construct(actor);
        ST32(stats(actor) + 8, loading_values[i]); ST32(stats(actor) + 0xe8, loading_values[j]);
        update(actor, false); early_refresh(actor, 1); update(actor, false);
        request(10, true); update(actor, false); early_refresh(actor, 1);
        request(loading_percent[mode], mode != 2);
        begin_init(actor, 1000);
        // A generic refresh during base initialization cannot complete readiness.
        early_refresh(actor, 1); update(actor, false);
        uint32_t amount = expected_max(1000, (unsigned)loading_percent[mode]);
        recompute(actor, 1000, amount, amount); update(actor, false);
        dispose(actor, (mode & 1) != 0);
    }
    // Once a genuine native initialization has completed, corrupt live HP is
    // still an error. The lifecycle correction does not weaken arithmetic guards.
    request(100, false); construct(actor); begin_init(actor, 1000);
    recompute(actor, 1000, 1000, 1000);
    invalid_ready_hp(UINT32_MAX, 1000, 1000);
    invalid_ready_hp(100, 0, 1000);
    invalid_ready_hp(100, UINT32_MAX, 1000);
    invalid_ready_hp(100, 1000, 0);
    invalid_ready_hp(100, 1000, UINT32_MAX);

    // Every slider position, fresh lifetime at a reused pointer, full health.
    for (int p = 10; p <= 2000; ++p) {
        request(p, true); construct(actor); begin_init(actor, 1200);
        uint32_t amount = expected_max(1200, (unsigned)p);
        recompute(actor, 1200, amount, amount); update(actor, false);
        dispose(actor, (p & 1) != 0);
    }
    // Default/off and explicit1x are exact guest/CPU no-ops, including native
    // current HP above a buff-reduced maximum. No unsolicited heal/clamp.
    for (unsigned on = 0; on < 2; ++on) {
        request(100, on != 0); construct(actor); begin_init(actor, 1200);
        recompute(actor, 1000, 1000, 1200); update(actor, false);
    }
    // Native init current is based on the base HP. Preserve native fraction
    // relative to the fresh derived maximum rather than blindly filling it.
    request(200, true); construct(actor); begin_init(actor, 1000);
    recompute(actor, 1200, 2400, 2000);
    ST32(stats(actor) + 8, 600); update(actor, false);
    recompute(actor, 1500, 3000, 600); // unchanged option: native buff policy
    recompute(actor, 1500, 3000, 600); // no compounding or repeated healing
    request(10, true); update(actor, true); recompute(actor, 1500, 150, 30);
    request(2000, true); update(actor, true); recompute(actor, 1500, 30000, 6000);
    request(777, false); update(actor, true); recompute(actor, 1500, 1500, 300);
    update(actor, false);
    // Dead stays dead across downscale, restore and native buff refresh.
    ST32(stats(actor) + 8, 0); request(200, true); update(actor, true);
    recompute(actor, 1500, 3000, 0); request(100, false); update(actor, true);
    recompute(actor, 1500, 1500, 0);

    // Quantization floor never raises the original tiny maximum. At1000 native
    // HP, the requested0.1x still yields100, allowing1HP to reach1%.
    const uint32_t small[] = {1, 99, 100, 999, 1000};
    for (unsigned i = 0; i < sizeof small / sizeof *small; ++i) {
        request(10, true); construct(actor); begin_init(actor, small[i]);
        uint32_t amount = expected_max(small[i], 10);
        recompute(actor, small[i], amount, amount);
        request(100, false); update(actor, amount != small[i] || 10 != 100);
        recompute(actor, small[i], small[i], small[i]);
    }
    // Large maxima saturate safely, never wrap into a smaller/negative maximum.
    request(2000, true); construct(actor); begin_init(actor, INT32_MAX);
    recompute(actor, INT32_MAX, INT32_MAX, INT32_MAX);
    const int32_t old[] = {INT32_MAX, 100, 0, 100, INT32_MAX};
    const int32_t delta[] = {INT32_MAX, INT32_MIN, -1, 9, -INT32_MAX};
    const uint32_t result[] = {INT32_MAX, 0, 0, 109, 0};
    for (unsigned i = 0; i < 5; ++i) {
        Cpu c = cpu(); c.x[19] = actor; c.x[8] = (uint32_t)old[i]; c.x[20] = (uint32_t)delta[i];
        Cpu expected = c; expected.x[20] = result[i];
        assert(xcde_cheats_enemy_health_add(&c)); check_cpu(&c, &expected);
    }
    // The protection floor keeps native FP conversion/multiply and FPSR updates,
    // but its integer product is wide and the eventual floor is within max.
    const uint16_t params[] = {1, 20, 50, 100, 65535};
    for (unsigned i = 0; i < sizeof params / sizeof *params; ++i) {
        Cpu c = cpu(); c.x[0] = stats(actor); c.x[19] = actor; c.x[9] = params[i];
        c.x[8] = (uint32_t)((uint64_t)INT32_MAX * params[i]);
        Cpu expected = c; expected.v[0] = fb_s(fromint_s(&expected, (uint64_t)INT32_MAX * params[i], 64, 1, 0));
        assert(xcde_cheats_enemy_health_floor_convert(&c)); check_cpu(&c, &expected);
        c.v[1] = 0x3c23d70a; fp_op_s(&c, FOP_MUL, 0, 0, 1);
        float native_floor; uint32_t floor_bits = (uint32_t)c.v[0]; memcpy(&native_floor, &floor_bits, sizeof native_floor);
        c.x[22] = (uint32_t)toint_s(&c, native_floor, 3, 0, 32, 1);
        expected = c; if (expected.x[22] > INT32_MAX) expected.x[22] = INT32_MAX;
        xcde_cheats_enemy_health_floor_clamp(&c); check_cpu(&c, &expected);
    }
    // Off/explicit1x preserve even an untracked native EnemyStatus, including
    // while another actor still has a scaled maximum awaiting its own update.
    uint64_t untracked = base + 0xc000;
    ST64(untracked, table); ST32(stats(untracked) + 8, 77);
    ST32(stats(untracked) + 0xe8, 1000);
    for (unsigned on = 0; on < 2; ++on) {
        request(100, on != 0); update(untracked, false);
        Cpu c = cpu(); c.x[0] = stats(untracked); c.x[3] = untracked; Cpu before = c;
        xcde_cheats_enemy_health_recompute_begin(&c); check_cpu(&c, &before);
        c.sp -= 0xb0; c.x[19] = stats(untracked); c.x[20] = untracked;
        c.x[8] = 1000; before = c;
        xcde_cheats_enemy_health_max(&c); check_cpu(&c, &before);
        assert(hp(untracked) == 77 && maxhp(untracked) == 1000);
    }
    request(2000, true);
    // Distinct actors, destruction paths and same-address construction/initialization
    // invalidate the former lifetime. A still-active request must scale anew.
    construct(second); begin_init(second, 1000); recompute(second, 1000, 20000, 20000);
    dispose(actor, false); construct(actor); begin_init(actor, 1000);
    recompute(actor, 1000, 20000, 20000); dispose(actor, true);
    begin_init(second, 400); recompute(second, 400, 8000, 8000);
    dispose(second, false);
    for (unsigned i = 0; i < 2; ++i) {
        Cpu c = cpu(); c.x[19] = actor; c.x[8] = 17; c.x[20] = 19; Cpu expected = c;
        assert(!xcde_cheats_enemy_health_add(&c)); check_cpu(&c, &expected);
    }
    // Party/NPC/unknown virtual kind identities are not treated as enemies.
    for (unsigned kind = 0; kind < 3; ++kind) {
        ST64(actor, table + 0x200); ST64(table + 0x208, UINT64_C(0x7000100000) + kind);
        ST64(table + 0x2c8, UINT64_C(0x700047f2b0));
        Cpu c = cpu(); c.x[19] = actor; c.x[3] = actor; c.x[0] = stats(actor); Cpu before = c;
        xcde_cheats_enemy_health_update(&c); check_cpu(&c, &before);
        xcde_cheats_enemy_health_recompute_begin(&c); check_cpu(&c, &before);
        c.x[20] = actor; c.x[19] = stats(actor); before = c;
        xcde_cheats_enemy_health_max(&c); check_cpu(&c, &before);
    }
    // Reset follows the actual runtime section contract after guest shutdown.
    for (void (**fn)(void) = __start_resets; fn != __stop_resets; ++fn) (*fn)();
    request(100, false); construct(actor); begin_init(actor, 1000);
    recompute(actor, 1000, 1000, 1000); update(actor, false);
    assert(!munmap((void *)(uintptr_t)base, 0x40000));
    printf("PASS enemy health: %u CPU/numeric/lifetime checks; all1991sliderpositions, floors, restore, no-revive, overflow\n", checks);
}
