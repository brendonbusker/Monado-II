// [XCDE] LINUX-055 r2: keep native held-L2 camera/HUD input while routing the
// optional physical-L2 party chord. Pure event state: no SDL or guest memory.
#ifndef MONADO_PAD_MODIFIER_H
#define MONADO_PAD_MODIFIER_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool initialized, enabled, connected, blocked_until_release;
    uint32_t consumed_shoulders;
    uint64_t bindings;
} PadModifierState;

typedef struct {
    bool enabled, captured, connected, lt;
    uint32_t shoulders, pressed;  // normalized: 1 left, 2 right; valid selected-pad DOWN edges
    uint64_t bindings;           // guest bits driven by physical L2; changes cancel an existing hold
} PadModifierInput;

typedef struct {
    bool forward_lt;
    uint32_t consumed;
    int party_step;
} PadModifierResult;

static inline void pad_modifier_cancel(PadModifierState *state, bool lt, uint32_t shoulders) {
    state->blocked_until_release = lt;
    state->consumed_shoulders = shoulders & 3u;
}

static inline PadModifierResult pad_modifier_step(PadModifierState *state, const PadModifierInput *input) {
    PadModifierResult result = {0};
    uint32_t shoulders = input->shoulders & 3u;
    if (state->initialized) {
        if (state->enabled != input->enabled || state->connected != input->connected ||
            state->bindings != input->bindings)
            pad_modifier_cancel(state, input->lt, shoulders);
    } else {
        // Explicit cancellation before the first sample must still block an
        // already-held trigger. Otherwise the first sample is native input.
        state->initialized = true;
    }
    state->enabled = input->enabled;
    state->connected = input->connected;
    state->bindings = input->bindings;
    state->consumed_shoulders &= shoulders;

    if (!input->enabled) {
        // Native and scripted-host passthrough must not require a physical pad.
        pad_modifier_cancel(state, input->lt, 0);
        result.forward_lt = input->lt;
        return result;
    }
    if (!input->connected) {
        pad_modifier_cancel(state, input->lt, 0);
        return result;
    }
    if (input->captured) {
        pad_modifier_cancel(state, input->lt, shoulders);
        result.consumed = state->consumed_shoulders;
        return result;
    }

    if (input->lt && !state->blocked_until_release) {
        // The game's normal held state drives both its camera controls and its
        // control-help display. Never defer it until movement or synthesize a
        // second press after release, even when a party chord is used.
        result.forward_lt = true;
        uint32_t pressed = input->pressed & 3u & ~state->consumed_shoulders;
        if (pressed) {
            state->consumed_shoulders |= pressed;
            if (pressed == 1u) result.party_step = -1;
            else if (pressed == 2u) result.party_step = 1;
            // Simultaneous opposite edges are ambiguous; consume both without
            // inventing a switch direction. A queued release may already be
            // reflected by the current sampled shoulder state.
        }
    } else if (!input->lt) {
        state->blocked_until_release = false;
    }
    result.consumed = state->consumed_shoulders;
    return result;
}

#endif
