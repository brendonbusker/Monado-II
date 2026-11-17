// [XCDE] LINUX-126: bound launcher painting independently of child/IPC servicing.
// CPU/GPU work in an unfocused launcher must not compete with the running game.
#pragma once
#include <cstdint>

namespace launcher_linux {
class LoopPacing {
    uint64_t next_paint = 0;
    bool initialized = false, was_visible = false, was_focused = false, had_game = false;
public:
    bool paint(uint64_t now, bool visible, bool focused, bool game_active) {
        // Restores, focus changes and child completion get a fresh frame promptly.
        if (!initialized || visible != was_visible || focused != was_focused || game_active != had_game)
            next_paint = 0;
        initialized = true; was_visible = visible; was_focused = focused; had_game = game_active;
        if (!visible) return false;
        if (now < next_paint) return false;
        // Foreground stays responsive, including held controller navigation.
        // Background status remains visible without redrawing at monitor refresh.
        uint64_t interval = focused ? 16666667ull : game_active ? 1000000000ull : 250000000ull;
        next_paint = now + interval;
        return true;
    }
    int wait_ms(uint64_t now) const {
        // SDL events wake this early. Broker/update/child status is not an SDL
        // event source, so no idle path may wait indefinitely for user input.
        if (!was_visible) return 50;
        if (now >= next_paint) return 1;
        uint64_t ms = (next_paint - now + 999999ull) / 1000000ull;
        return (int)(ms > 50 ? 50 : ms);
    }
};
}
