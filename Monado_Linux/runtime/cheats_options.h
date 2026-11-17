// [XCDE] LINUX-120: coherent live cheat controls shared by F1 and guest hooks.
#pragma once
#include "settings.h"
#ifdef __cplusplus
extern "C" {
#endif

enum {
    XCDE_CHEAT_DAMAGE_DEALT, XCDE_CHEAT_DAMAGE_RECEIVED,
    XCDE_CHEAT_EXP, XCDE_CHEAT_AP, XCDE_CHEAT_SP, XCDE_CHEAT_GOLD,
    XCDE_CHEAT_MOVEMENT_SPEED, XCDE_CHEAT_ENEMY_HEALTH, XCDE_CHEAT_COUNT
};
typedef struct {
    bool enabled[XCDE_CHEAT_COUNT];
    int percent[XCDE_CHEAT_COUNT];
    bool no_fall_damage;
} XcdeCheats;

// Copies a complete, validated request. No lock is retained by the caller.
XcdeCheats xcde_cheats_snapshot(void);
void xcde_cheats_publish(const Settings *settings);
// [XCDE] LINUX-129: cheap coherent effective value, without a per-enemy mutex.
int xcde_cheats_enemy_health_percent(void);
static inline int xcde_cheats_minimum_percent(int kind) {
    return kind == XCDE_CHEAT_ENEMY_HEALTH ? 10 : 0;
}
static inline int xcde_cheats_effective_percent(const XcdeCheats *options, int kind) {
    if (!options || kind < 0 || kind >= XCDE_CHEAT_COUNT || !options->enabled[kind]) return 100;
    int percent = options->percent[kind];
    return percent >= xcde_cheats_minimum_percent(kind) && percent <= 2000 ? percent : 100;
}
#ifdef __cplusplus
}
#endif
