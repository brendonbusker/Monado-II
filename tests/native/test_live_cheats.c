// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-120: actual publisher coherence, not a mirrored implementation.
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include "../../Monado_Linux/runtime/cheats_options.h"
static Settings settings(int percent) {
    Settings s = {0};
#define VALUE(name) s.cheat_##name = (percent & 1) != 0; s.cheat_##name##_percent = percent;
    VALUE(damage_dealt) VALUE(damage_received) VALUE(exp) VALUE(ap) VALUE(sp) VALUE(gold) VALUE(movement_speed) VALUE(enemy_health)
#undef VALUE
    s.cheat_no_fall_damage = (percent & 1) != 0;
    return s;
}
static void *writer(void *unused) {
    (void)unused;
    for (int n = 0; n < 60000; ++n) { Settings s = settings(n % 2001); xcde_cheats_publish(&s); }
    return NULL;
}
static void *reader(void *unused) {
    (void)unused;
    for (int n = 0; n < 60000; ++n) {
        XcdeCheats s = xcde_cheats_snapshot();
        assert(s.percent[0] >= 0 && s.percent[0] <= 2000);
        for (int i = 0; i < XCDE_CHEAT_COUNT; ++i) {
            assert(s.percent[i] == (i == XCDE_CHEAT_ENEMY_HEALTH && s.percent[0] < 10 ? 100 : s.percent[0]));
            assert(s.enabled[i] == ((s.percent[0] & 1) != 0));
        }
        assert(s.no_fall_damage == s.enabled[0]);
        int hp = xcde_cheats_enemy_health_percent(); assert(hp >= 10 && hp <= 2000);
    }
    return NULL;
}
int main(void) {
    XcdeCheats defaults = xcde_cheats_snapshot();
    for (int i = 0; i < XCDE_CHEAT_COUNT; ++i) { assert(!defaults.enabled[i]); assert(defaults.percent[i] == 100); }
    assert(!defaults.no_fall_damage); assert(xcde_cheats_enemy_health_percent() == 100);
    // Changing local UI state alone must not race/pollute an earlier request.
    Settings s = settings(501); xcde_cheats_publish(&s);
    XcdeCheats old = xcde_cheats_snapshot(); s = settings(999);
    assert(xcde_cheats_snapshot().percent[0] == 501);
    xcde_cheats_publish(&s); assert(old.percent[0] == 501); assert(xcde_cheats_snapshot().percent[0] == 999);
    s = settings(2001); xcde_cheats_publish(&s);
    XcdeCheats invalid = xcde_cheats_snapshot();
    for (int i = 0; i < XCDE_CHEAT_COUNT; ++i) assert(invalid.percent[i] == 100);
    s = settings(0); s.cheat_movement_speed = true; xcde_cheats_publish(&s);
    XcdeCheats zero = xcde_cheats_snapshot();
    assert(xcde_cheats_effective_percent(&zero, XCDE_CHEAT_MOVEMENT_SPEED) == 0);
    zero.enabled[XCDE_CHEAT_MOVEMENT_SPEED] = false;
    assert(xcde_cheats_effective_percent(&zero, XCDE_CHEAT_MOVEMENT_SPEED) == 100);
    // Enemy health has its own positive minimum; every invalid0..9 falls back to1x.
    for (int n = 0; n < 10; ++n) {
        s = settings(n); s.cheat_enemy_health = true; xcde_cheats_publish(&s);
        XcdeCheats low = xcde_cheats_snapshot(); assert(low.percent[XCDE_CHEAT_ENEMY_HEALTH] == 100);
        assert(xcde_cheats_effective_percent(&low, XCDE_CHEAT_ENEMY_HEALTH) == 100);
        assert(xcde_cheats_enemy_health_percent() == 100);
        low.percent[XCDE_CHEAT_ENEMY_HEALTH] = n;
        assert(xcde_cheats_effective_percent(&low, XCDE_CHEAT_ENEMY_HEALTH) == 100);
    }
    for (int n = 10; n <= 2000; ++n) {
        s = settings(n); s.cheat_enemy_health = true; xcde_cheats_publish(&s);
        assert(xcde_cheats_enemy_health_percent() == n);
        XcdeCheats exact = xcde_cheats_snapshot();
        assert(xcde_cheats_effective_percent(&exact, XCDE_CHEAT_ENEMY_HEALTH) == n);
        s.cheat_enemy_health = false; xcde_cheats_publish(&s); assert(xcde_cheats_enemy_health_percent() == 100);
    }
    xcde_cheats_publish(NULL); assert(xcde_cheats_enemy_health_percent() == 100);
    pthread_t threads[5]; assert(!pthread_create(&threads[0], NULL, writer, NULL));
    for (int i = 1; i < 5; ++i) assert(!pthread_create(&threads[i], NULL, reader, NULL));
    for (int i = 0; i < 5; ++i) assert(!pthread_join(threads[i], NULL));
    puts("live cheats: defaults, request isolation, clamping, zero/disabled and 240000 coherent concurrent snapshots PASS");
}
