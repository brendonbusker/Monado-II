// [XCDE] LINUX-129: checked DE2.0.0 enemy stat/lifetime adapters.
#pragma once
#include "../cpu.h"
#include <stdbool.h>

void xcde_cheats_enemy_health_construct(Cpu *c);
void xcde_cheats_enemy_health_initialize(Cpu *c);
void xcde_cheats_enemy_health_destroy(Cpu *c);
void xcde_cheats_enemy_health_destroy_component(Cpu *c);
void xcde_cheats_enemy_health_update(Cpu *c);
void xcde_cheats_enemy_health_recompute_begin(Cpu *c);
void xcde_cheats_enemy_health_max(Cpu *c);
bool xcde_cheats_enemy_health_add(Cpu *c);
bool xcde_cheats_enemy_health_floor_convert(Cpu *c);
void xcde_cheats_enemy_health_floor_clamp(Cpu *c);
