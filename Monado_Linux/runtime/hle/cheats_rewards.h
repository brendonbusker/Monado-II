// [XCDE] LINUX-072: opt-in positive reward adapters; native saves stay unchanged.
#pragma once
#include <stdbool.h>
#include "../cpu.h"

// Called at checked award BL sites after setting their original link register.
// False means execute the exact original call; true means that same native
// function ran once with a private scaled input. Expert-mode transfers bypass it.
bool xcde_cheats_rewards_call(Cpu *c);
void xcde_cheats_gold(Cpu *c);
