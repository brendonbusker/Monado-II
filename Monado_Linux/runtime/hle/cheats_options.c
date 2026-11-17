// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-120: render-thread publication to guest event consumers.
#include "../cheats_options.h"
#include <pthread.h>
#include <stdatomic.h>

static pthread_mutex_t request_lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int enemy_health_percent = 100;
static XcdeCheats request = {.percent = {100, 100, 100, 100, 100, 100, 100, 100}};

void xcde_cheats_publish(const Settings *settings) {
    XcdeCheats next = {.percent = {100, 100, 100, 100, 100, 100, 100, 100}};
    if (settings) {
#define COPY(kind, name) next.enabled[kind] = settings->cheat_##name; \
    next.percent[kind] = settings->cheat_##name##_percent >= xcde_cheats_minimum_percent(kind) && settings->cheat_##name##_percent <= 2000 \
        ? settings->cheat_##name##_percent : 100;
        COPY(XCDE_CHEAT_DAMAGE_DEALT, damage_dealt)
        COPY(XCDE_CHEAT_DAMAGE_RECEIVED, damage_received)
        COPY(XCDE_CHEAT_EXP, exp)
        COPY(XCDE_CHEAT_AP, ap)
        COPY(XCDE_CHEAT_SP, sp)
        COPY(XCDE_CHEAT_GOLD, gold)
        COPY(XCDE_CHEAT_MOVEMENT_SPEED, movement_speed)
        COPY(XCDE_CHEAT_ENEMY_HEALTH, enemy_health)
#undef COPY
        next.no_fall_damage = settings->cheat_no_fall_damage;
    }
    // Hold only for the copy: reward callbacks can yield or re-enter guest hooks.
    pthread_mutex_lock(&request_lock);
    request = next;
    atomic_store_explicit(&enemy_health_percent,
        xcde_cheats_effective_percent(&next, XCDE_CHEAT_ENEMY_HEALTH), memory_order_release);
    pthread_mutex_unlock(&request_lock);
}

int xcde_cheats_enemy_health_percent(void) {
    return atomic_load_explicit(&enemy_health_percent, memory_order_acquire);
}

XcdeCheats xcde_cheats_snapshot(void) {
    pthread_mutex_lock(&request_lock);
    XcdeCheats result = request;
    pthread_mutex_unlock(&request_lock);
    return result;
}
