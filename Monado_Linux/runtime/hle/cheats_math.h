// [XCDE] LINUX-072: authored fixed-point cheat arithmetic, no game data.
#pragma once
#include <stdint.h>

// Scale a positive magnitude by an integer percentage, flooring fractional
// units. Quotient/remainder arithmetic avoids overflow even at UINT64_MAX.
// Callers preserve the original instruction path when disabled or at 100%.
static inline uint64_t xcde_cheat_scale(uint64_t value, int percent, uint64_t cap) {
    if (percent < 0 || percent > 2000) percent = 100;
    if (!percent) return 0;
    uint64_t p = (unsigned)percent, whole = value / 100;
    if (whole > cap / p) return cap;
    uint64_t scaled = whole * p, tail = ((value % 100) * p) / 100;
    return tail > cap - scaled ? cap : scaled + tail;
}
