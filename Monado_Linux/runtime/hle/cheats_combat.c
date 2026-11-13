// [XCDE] LINUX-072: authored adapters for checked DE 2.0.0 combat dispatch.
#include "../hle.h"
#include "../settings.h"
#include "cheats_combat.h"
#include "cheats_math.h"
#include <limits.h>

static bool combat_range(uint64_t address, size_t bytes) {
    return address >= GUEST_LO && address < GUEST_HI && bytes <= GUEST_HI - address;
}

static bool combat_active(void) {
    return (g_settings.cheat_damage_dealt && g_settings.cheat_damage_dealt_percent != 100) ||
           (g_settings.cheat_damage_received && g_settings.cheat_damage_received_percent != 100);
}

static void combat_scale(uint64_t event, uint64_t source_ref, uint64_t target_ref) {
    uint64_t source = LD64(source_ref), target = LD64(target_ref);
    uint32_t source_type = LD32(source_ref + 8), target_type = LD32(target_ref + 8);
    if (!source || !target) return;
    int percent = 100;
    if (source_type == 2 && target_type == 4 && g_settings.cheat_damage_dealt)
        percent = g_settings.cheat_damage_dealt_percent;
    else if (source_type == 4 && target_type == 2 && g_settings.cheat_damage_received)
        percent = g_settings.cheat_damage_received_percent;
    else return; // Ally-to-ally, enemy-to-enemy, NPC and unknown cases stay native.

    // Native event 9 delivers this signed amount to the target's HP consumer,
    // which negates it before HPdelta (+0x30). Its flags choose side effects or
    // suppress the delivery; none turns a positive amount into healing. Native
    // effect/healing event 10 follows a separate dispatcher that is not hooked.
    // Signed zero/negative amounts and the exact1x path therefore stay native.
    int32_t amount = (int32_t)LD32(event + 0x20);
    if (amount <= 0 || percent == 100) return;
    ST32(event + 0x20, (uint32_t)xcde_cheat_scale((uint32_t)amount, percent, INT32_MAX));
}

void cheats_combat_hit(Cpu *c) {
    if (!combat_active()) return; // Disabled/1x never touches guest state.
    // Both handles were resolved by the original code before this hook. Entity
    // kinds 2 (PcStatus) and 4 (EnemyStatus) include party AI and both stories.
    uint64_t frame = c->x[29], event = c->x[21];
    if (!combat_range(c->sp, 0x180) || frame != c->sp + 0x170 ||
        !combat_range(event, 0x38)) FATAL("[cheats] native combat dispatch ABI changed\n");
    if (c->x[20] & 1) return; // Native presentation-only/rehearsal event, no HP loss.
    combat_scale(event, frame - 0x50, frame - 0x60);
}

void cheats_combat_linked_hit(Cpu *c) {
    if (!combat_active()) return;
    // Native alternate dispatch resolves/remaps source and target handles itself
    // before copying this local record. Use those final references, not the
    // initial leader/selected target or a guessed party-character identifier.
    uint64_t frame = c->x[29], event = c->x[22];
    if (!combat_range(c->sp, 0x3c10) || frame != c->sp + 0x3c00 ||
        event != frame - 0xb0 || !combat_range(event, 0x38))
        FATAL("[cheats] native linked combat dispatch ABI changed\n");
    if (LD32(c->sp + 0x24) & 1) return;
    combat_scale(event, frame - 0xd0, frame - 0xc0);
}

bool cheats_skip_fall_damage(Cpu *c) {
    // Checked native landing calculation, before ordinary and lethal drop paths
    // diverge. The game has already obtained status kind into w23 and its
    // forced collision/death flag into w22. Do not intercept forced events.
    // The emitter uses the original no-damage return path; the caller retains
    // landing animation, movement resets and post-landing state transitions.
    return g_settings.cheat_no_fall_damage && (uint32_t)c->x[23] == 2 && !(c->x[22] & 1);
}
