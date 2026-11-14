// [XCDE] LINUX-089: event-thread controller health/discovery scheduling.
// Shared by the game input owner and launcher (whose ImGui backend owns pads).
// A focus return permits one immediate check. Ordinary ticks inspect/retry at
// most once a second; a healthy connected handle must never be reopened merely
// because this timer is due. Pass monotonic SDL_GetTicks(), not frame counts.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define RT_CONTROLLER_RECOVERY_INTERVAL_MS UINT64_C(1000)

typedef struct RtControllerRecovery {
    uint64_t next_poll_ms;
    bool started;
    bool requested;
} RtControllerRecovery;

static inline void rt_controller_recovery_request(RtControllerRecovery *state) {
    state->requested = true;
}

static inline void rt_controller_recovery_scanned(RtControllerRecovery *state, uint64_t now_ms) {
    state->next_poll_ms = now_ms > UINT64_MAX - RT_CONTROLLER_RECOVERY_INTERVAL_MS
        ? UINT64_MAX : now_ms + RT_CONTROLLER_RECOVERY_INTERVAL_MS;
    state->started = true;
    state->requested = false;
}

static inline bool rt_controller_recovery_due(RtControllerRecovery *state, uint64_t now_ms) {
    if (state->started && !state->requested && now_ms < state->next_poll_ms) return false;
    rt_controller_recovery_scanned(state, now_ms);
    return true;
}
