// [XCDE] LINUX-072: scale new awards once, retaining native eligibility, level-up,
// bonus-EXP behavior, skill handling, notifications and caps. No balance edits.
#include "../hle.h"
#include "../settings.h"
#include "cheats_math.h"
#include "cheats_rewards.h"

#define REWARD_FUNCTION 0x70000ba860ull
#define REWARD_BYTES 0x14u
#define REWARD_STACK 0x1000u
#define EXP_CAP 199999998u
#define AP_CAP 99999999u
#define SP_CAP 999999u
#define GOLD_CAP 999999999u

static bool range(uint64_t address, uint64_t size) {
    return address >= GUEST_LO && address < GUEST_HI && size <= GUEST_HI - address;
}

static bool changed_setting(bool enabled, int percent) {
    return enabled && percent >= 0 && percent <= 2000 && percent != 100;
}

bool xcde_cheats_rewards_call(Cpu *c) {
    const bool enabled[3] = {
        changed_setting(g_settings.cheat_exp, g_settings.cheat_exp_percent),
        changed_setting(g_settings.cheat_ap, g_settings.cheat_ap_percent),
        changed_setting(g_settings.cheat_sp, g_settings.cheat_sp_percent),
    };
    if (!enabled[0] && !enabled[1] && !enabled[2]) return false;
    uint64_t input = c->x[1];
    if (!range(input, REWARD_BYTES)) FATAL("[cheats] invalid native reward input\n");
    // Native eligibility remains authoritative. These are the playable IDs in
    // the two stories; ordinary rejected IDs keep their exact original call.
    uint16_t character = LD16(input);
    if (!(character >= 1 && character <= 8) && character != 14 && character != 15)
        return false;
    const int percent[3] = {g_settings.cheat_exp_percent,
                           g_settings.cheat_ap_percent, g_settings.cheat_sp_percent};
    const uint32_t cap[3] = {EXP_CAP, AP_CAP, SP_CAP};
    uint8_t record[REWARD_BYTES];
    memcpy(record, (const void *)(uintptr_t)input, sizeof record);
    bool changed = false;
    for (unsigned i = 0; i < 3; ++i) {
        uint32_t before;
        memcpy(&before, record + 4 + i * 4, sizeof before);
        // The native award interface carries unsigned magnitudes. Preserve any
        // signed-negative sentinel/correction rather than turning it into a gain.
        if (!enabled[i] || !before || (before & 0x80000000u)) continue;
        uint32_t after = (uint32_t)xcde_cheat_scale(before, percent[i], cap[i]);
        memcpy(record + 4 + i * 4, &after, sizeof after);
        changed |= before != after;
    }
    if (!changed) return false;

    // Each checked caller owns its input above SP. Reserve separate guest stack
    // storage so callers, other threads and yields never observe a mutated input.
    // The native callee grows below the lowered SP; the copied record sits above
    // it. No global/TLS lease is needed, so fiber switches cannot mix ownership.
    const uint64_t old_sp = c->sp, old_pc = c->pc;
    if ((old_sp & 15) || old_sp < GUEST_LO + REWARD_STACK ||
        !range(old_sp - REWARD_STACK, REWARD_STACK) ||
        input < old_sp || input - old_sp >= REWARD_STACK)
        FATAL("[cheats] invalid native reward stack/layout\n");
    const uint64_t scratch = old_sp - 0x20;
    uint8_t previous[REWARD_BYTES];
    memcpy(previous, (const void *)(uintptr_t)scratch, sizeof previous);
    memcpy((void *)(uintptr_t)scratch, record, sizeof record);
    c->sp = old_sp - REWARD_STACK;
    c->x[1] = scratch;
    guest_call(c, REWARD_FUNCTION);
    if (c->sp != old_sp - REWARD_STACK)
        FATAL("[cheats] native reward call changed its stack\n");
    memcpy((void *)(uintptr_t)scratch, previous, sizeof previous);
    c->sp = old_sp;
    c->pc = old_pc;
    c->x[1] = input;
    return true;
}

void xcde_cheats_gold(Cpu *c) {
    if (!changed_setting(g_settings.cheat_gold, g_settings.cheat_gold_percent)) return;
    uint32_t amount = (uint32_t)c->x[1];
    if (!amount || (amount & 0x80000000u)) return;
    // The native add path caps the resulting balance separately. Capping this
    // one gain first also prevents its 32-bit balance+award addition overflowing.
    c->x[1] = xcde_cheat_scale(amount, g_settings.cheat_gold_percent, GOLD_CAP);
}
