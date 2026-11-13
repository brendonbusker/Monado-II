// Authored controller-routing fixtures; no SDL, game input, guest or renderer.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "hle/pad_modifier.h"

#ifdef NDEBUG
#error "Controller-routing assertions must remain enabled"
#endif

static const uint64_t mapped = UINT64_C(1) << 8;
static unsigned scenarios;

static PadModifierInput sample(void) {
    PadModifierInput input = {0};
    input.enabled = input.connected = true;
    input.bindings = mapped;
    return input;
}
static void no_action(PadModifierResult result) { assert(result.party_step == 0); }

static void tap(void) {
    PadModifierState state = {0}; PadModifierInput input = sample();
    for (unsigned i = 0; i < 10; i++) {
        input.lt = true;
        PadModifierResult result = pad_modifier_step(&state, &input);
        assert(result.forward_lt && !result.consumed); no_action(result);
        input.lt = false;
        result = pad_modifier_step(&state, &input);
        assert(!result.forward_lt && !result.consumed); no_action(result);
        // An arbitrary number of polls after release never invents a new press.
        for (unsigned poll = 0; poll < 200; poll++) {
            result = pad_modifier_step(&state, &input);
            assert(!result.forward_lt && !result.consumed); no_action(result);
        }
        scenarios++;
    }
}
static void camera(void) {
    PadModifierState state = {0}; PadModifierInput input = sample();
    input.lt = true;
    // A neutral trigger hold reaches the native HUD immediately and stays held
    // without camera motion or a render-rate-dependent duration.
    for (unsigned poll = 0; poll < 10000; poll++) {
        PadModifierResult result = pad_modifier_step(&state, &input);
        assert(result.forward_lt && !result.consumed); no_action(result);
    }
    input.lt = false;
    for (unsigned poll = 0; poll < 10000; poll++) {
        PadModifierResult result = pad_modifier_step(&state, &input);
        assert(!result.forward_lt); no_action(result);
    }
    scenarios += 2;
}
static void chords(void) {
    for (uint32_t shoulder = 1; shoulder <= 2; shoulder++) {
        PadModifierState state = {0}; PadModifierInput input = sample();
        input.lt = true; assert(pad_modifier_step(&state, &input).forward_lt);
        input.shoulders = input.pressed = shoulder;
        PadModifierResult result = pad_modifier_step(&state, &input);
        assert(result.party_step == (shoulder == 1 ? -1 : 1));
        assert(result.forward_lt && result.consumed == shoulder);
        // Duplicate DOWN while held neither repeats nor leaks targeting.
        result = pad_modifier_step(&state, &input);
        assert(result.forward_lt && !result.party_step && result.consumed == shoulder);
        input.pressed = 0; input.lt = false;
        for (unsigned poll = 0; poll < 100; poll++) {
            result = pad_modifier_step(&state, &input);
            assert(!result.forward_lt && result.consumed == shoulder); no_action(result);
        }
        input.shoulders = 0;
        result = pad_modifier_step(&state, &input);
        assert(!result.consumed); no_action(result);
        // Outside L2 the same shoulder remains a native game control.
        input.shoulders = input.pressed = shoulder;
        result = pad_modifier_step(&state, &input);
        assert(!result.consumed); no_action(result);
        scenarios++;
    }
    PadModifierState state = {0}; PadModifierInput input = sample();
    input.lt = true; input.pressed = 2; input.shoulders = 0;
    PadModifierResult result = pad_modifier_step(&state, &input);
    assert(result.party_step == 1 && result.consumed == 2 && result.forward_lt);
    input.pressed = 0; input.lt = false;
    result = pad_modifier_step(&state, &input);
    assert(!result.consumed && !result.forward_lt); no_action(result); scenarios++;
    memset(&state, 0, sizeof state); input = sample();
    input.lt = true; input.pressed = input.shoulders = 3;
    result = pad_modifier_step(&state, &input);
    assert(!result.party_step && result.consumed == 3 && result.forward_lt);
    input.pressed = 0; input.lt = false;
    result = pad_modifier_step(&state, &input);
    assert(!result.forward_lt); no_action(result); scenarios++;
}
static void cancellation(void) {
    for (unsigned kind = 0; kind < 4; kind++) {
        PadModifierState state = {0}; PadModifierInput input = sample();
        input.lt = true; assert(pad_modifier_step(&state, &input).forward_lt);
        if (kind == 0) input.captured = true;
        if (kind == 1) input.connected = false;
        if (kind == 2) input.bindings <<= 1;
        if (kind == 3) input.enabled = false;
        PadModifierResult result = pad_modifier_step(&state, &input);
        no_action(result); assert(result.forward_lt == (kind == 3));
        input.enabled = input.connected = true; input.captured = false;
        result = pad_modifier_step(&state, &input);
        assert(!result.forward_lt); no_action(result);
        input.lt = false; result = pad_modifier_step(&state, &input);
        assert(!result.forward_lt); no_action(result);
        input.lt = true; result = pad_modifier_step(&state, &input);
        assert(result.forward_lt); no_action(result); scenarios++;
    }
    PadModifierState state = {0}; PadModifierInput input = sample();
    input.lt = true; assert(pad_modifier_step(&state, &input).forward_lt);
    pad_modifier_cancel(&state, true, 2);
    input.shoulders = input.pressed = 2;
    PadModifierResult result = pad_modifier_step(&state, &input);
    assert(!result.forward_lt && result.consumed == 2); no_action(result);
    input.lt = false; input.pressed = 0;
    result = pad_modifier_step(&state, &input);
    assert(!result.forward_lt && result.consumed == 2); no_action(result);
    input.shoulders = 0; assert(!pad_modifier_step(&state, &input).consumed);
    memset(&state, 0, sizeof state); pad_modifier_cancel(&state, true, 0);
    input = sample(); input.lt = true;
    assert(!pad_modifier_step(&state, &input).forward_lt);
    input.lt = false; assert(!pad_modifier_step(&state, &input).forward_lt);
    input.lt = true; assert(pad_modifier_step(&state, &input).forward_lt);
    scenarios += 2;
}
static void passthrough(void) {
    for (unsigned bits = 0; bits < 128; bits++) {
        PadModifierState state = {0}; PadModifierInput input = sample();
        input.enabled = false; input.lt = bits & 1u; input.connected = bits & 2u;
        input.captured = bits & 4u; input.shoulders = (bits >> 4) & 3u; input.pressed = (bits >> 5) & 3u;
        PadModifierResult result = pad_modifier_step(&state, &input);
        assert(result.forward_lt == input.lt && !result.consumed); no_action(result); scenarios++;
    }
    PadModifierState state = {0}; PadModifierInput input = sample();
    input.lt = true; input.pressed = input.shoulders = 1;
    assert(pad_modifier_step(&state, &input).consumed == 1);
    input.enabled = false; input.pressed = 0;
    PadModifierResult result = pad_modifier_step(&state, &input);
    assert(result.forward_lt && !result.consumed); no_action(result);
    memset(&state, 0, sizeof state); input = sample(); input.connected = false;
    no_action(pad_modifier_step(&state, &input));
    input.connected = input.lt = true;
    assert(!pad_modifier_step(&state, &input).forward_lt);
    input.lt = false; assert(!pad_modifier_step(&state, &input).forward_lt);
    input.lt = true; assert(pad_modifier_step(&state, &input).forward_lt);
    scenarios += 2;
}
static void mapping(void) {
    const uint64_t masks[] = {0, UINT64_C(1) << 1, mapped,
        (UINT64_C(1) << 63) | (UINT64_C(1) << 22) | (UINT64_C(1) << 4)};
    for (unsigned i = 0; i < sizeof masks / sizeof masks[0]; i++) {
        PadModifierState state = {0}; PadModifierInput input = sample(); input.bindings = masks[i]; input.lt = true;
        PadModifierResult result = pad_modifier_step(&state, &input);
        assert(result.forward_lt); no_action(result);
        input.lt = false; result = pad_modifier_step(&state, &input);
        assert(!result.forward_lt); no_action(result); scenarios++;
    }
    // Held behaviour is polling-independent. A fresh binding may drive any guest
    // bits, but changing it midhold must wait for release before forwarding.
    for (unsigned polls = 1; polls <= 33; polls++) {
        PadModifierState state = {0}; PadModifierInput input = sample(); input.lt = true;
        for (unsigned i = 0; i < polls; i++) assert(pad_modifier_step(&state, &input).forward_lt);
        input.bindings ^= UINT64_C(1) << 63;
        for (unsigned i = 0; i < polls; i++) assert(!pad_modifier_step(&state, &input).forward_lt);
        input.lt = false; assert(!pad_modifier_step(&state, &input).forward_lt);
        input.lt = true; assert(pad_modifier_step(&state, &input).forward_lt); scenarios++;
    }
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "tap")) tap();
    else if (!strcmp(argv[1], "camera")) camera();
    else if (!strcmp(argv[1], "chords")) chords();
    else if (!strcmp(argv[1], "cancel")) cancellation();
    else if (!strcmp(argv[1], "passthrough")) passthrough();
    else if (!strcmp(argv[1], "mapping")) mapping();
    else assert(!"unknown controller fixture case");
    printf("pad modifier: PASS %s (%u scenarios)\n", argv[1], scenarios);
    return 0;
}
