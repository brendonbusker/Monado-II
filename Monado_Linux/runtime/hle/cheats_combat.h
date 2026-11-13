// [XCDE] LINUX-072: optional native combat event adapters.
#pragma once
#include "../cpu.h"
#include <stdbool.h>

// Called after native entity lookups, before a per-hit event is copied to its
// recipients, damage HUD and statistics. Neither calls/yields into the guest.
void cheats_combat_hit(Cpu *c);
void cheats_combat_linked_hit(Cpu *c);

// Predicate for the checked native height-based landing damage calculation.
// True selects the original no-damage return. Forced collision deaths remain.
bool cheats_skip_fall_damage(Cpu *c);
