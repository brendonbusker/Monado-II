// [XCDE] LINUX-120: scale the native party locomotion result once, immediately
// before its ordinary movement-component store. Native stats, Quick Step caps,
// environment modifiers, timing, vertical physics and enemy/NPC speed stay native.
#include "../hle.h"
#include "../cheats_options.h"
#include "cheats_movement.h"
#include <fenv.h>
#include <float.h>

#pragma STDC FENV_ACCESS ON

// Checked DE 2.0.0 PcStatus virtual kind method: returns kind 2. Match the
// audited method identity, not a guessed character ID or mutable party leader.
// The generator also guards both instructions of this native method.
#define PC_STATUS_KIND UINT64_C(0x700047f750)

static bool movement_range(uint64_t address, uint64_t size) {
    return address >= GUEST_LO && address < GUEST_HI && size <= GUEST_HI - address;
}

void xcde_cheats_movement_speed(Cpu *c) {
    XcdeCheats options = xcde_cheats_snapshot();
    int percent = xcde_cheats_effective_percent(&options, XCDE_CHEAT_MOVEMENT_SPEED);
    if (percent == 100) return; // Disabled/1x: no guest reads or FP operation.
    uint64_t status = c->x[21], movement = c->x[19];
    if (!movement_range(status, 0x10) || !movement_range(movement, 0x34)) return;
    uint64_t vtable = LD64(status);
    if (!movement_range(vtable, 0x10) || LD64(vtable + 8) != PC_STATUS_KIND) return;

    uint32_t original;
    memcpy(&original, &c->v[0], sizeof original);
    // Preserve negative, zero and nonfinite native results byte for byte. In
    // particular, do not raise an invalid exception by comparing a NaN as float.
    if (!original || original >= UINT32_C(0x7f800000)) return;
    uint32_t adjusted = 0;
    if (percent) {
        fenv_t environment;
        if (feholdexcept(&environment) || fesetround(FE_TONEAREST))
            FATAL("[cheats] cannot preserve movement FP environment\n");
        float native;
        memcpy(&native, &original, sizeof native);
        double scaled = (double)native * percent / 100.0;
        // The preference itself is clamped, but a corrupt native magnitude must
        // not turn a finite input into infinity during optional multiplication.
        volatile float result = scaled >= FLT_MAX ? FLT_MAX : (float)scaled;
        float value = result;
        memcpy(&adjusted, &value, sizeof adjusted);
        if (fesetenv(&environment)) FATAL("[cheats] cannot restore movement FP environment\n");
    }
    // Keep the other 96 bits of V0 and every other guest register/flag intact.
    // The checked original STR still performs the sole movement-memory write.
    memcpy(&c->v[0], &adjusted, sizeof adjusted);
}
