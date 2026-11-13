// Authored headless SDL virtual-controller integration; no game/renderer/saves.
// Include the production input implementation so its actual Npad ABI can be read
// without constructing a guest. Only unrelated guest callbacks are boundaries.
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../Monado_Linux/runtime/hle/input.c"

Settings g_settings;
bool g_party_switch;
uint64_t g_watch_lo, g_watch_hi, g_stick_freeze_until;
int32_t g_stick_lx, g_stick_ly;
static bool captured;
static int switches, last_switch;
static uint64_t present;
bool menu_input_captured(void) { return captured; }
void party_switch_request(int step) { if (g_party_switch) { ++switches; last_switch = step; } }
void party_art_request(int slot) { (void)slot; }
void party_game_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void warp_game_tick(Cpu *c) { (void)c; }
void give_item_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void chamber_game_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void digs_game_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void qol_tick(void) {}
void pets_game_tick(Cpu *c) { (void)c; }
uint64_t renderer_present_count(void) { return present; }
bool party_camera_direct(uint64_t frame) { (void)frame; return false; }
bool mirror_input(void) { return false; }
uint64_t pets_menu_input(uint64_t buttons, int32_t sticks[4]) { (void)sticks; return buttons; }
void diag_input(uint64_t frame, uint64_t *buttons, int32_t *lx, int32_t *ly, int32_t *rx, int32_t *ry) {
    (void)frame; (void)buttons; (void)lx; (void)ly; (void)rx; (void)ry;
}
void input_note_rstick(int32_t ry) { (void)ry; }
uint64_t party_macro_buttons(void) { return 0; }
void vk_rec_toggle(void) {}

typedef struct {
    int64_t sample;
    uint64_t buttons;
    int32_t lx, ly, rx, ry;
    uint32_t attributes, padding;
} PadState;
_Static_assert(sizeof(PadState) == 0x28, "actual Npad state ABI");
static SDL_JoystickID primary_id, other_id;
static SDL_Joystick *primary, *other;
static SDL_Gamepad *other_pad;
static unsigned other_button_down;

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL %s:%d: %s (SDL: %s)\n", __FILE__, __LINE__, #condition, SDL_GetError()); \
    return false; \
} } while (0)

static bool pad_event(const SDL_Event *event) {
    switch (event->type) {
    case SDL_EVENT_GAMEPAD_ADDED: case SDL_EVENT_GAMEPAD_REMOVED:
        return event->gdevice.which == primary_id || event->gdevice.which == other_id;
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN: case SDL_EVENT_GAMEPAD_BUTTON_UP:
        return event->gbutton.which == primary_id || event->gbutton.which == other_id;
    case SDL_EVENT_GAMEPAD_AXIS_MOTION:
        return event->gaxis.which == primary_id || event->gaxis.which == other_id;
    default: return false;
    }
}

static void pump(void) {
    SDL_UpdateJoysticks();
    SDL_Event event;
    unsigned bound = 0;
    while (SDL_PollEvent(&event)) {
        if (++bound > 4096) { fprintf(stderr, "unbounded SDL fixture event queue\n"); exit(2); }
        if (!pad_event(&event)) continue; // Never route the user's physical input.
        if (event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN && event.gbutton.which == other_id) ++other_button_down;
        // The real menu consumes gamepad input before input_handle_event.
        if (captured && event.type != SDL_EVENT_GAMEPAD_ADDED && event.type != SDL_EVENT_GAMEPAD_REMOVED) continue;
        input_handle_event(&event);
    }
}

static bool attach(SDL_JoystickID *id, SDL_Joystick **joystick, const char *name) {
    SDL_VirtualJoystickDesc description;
    SDL_INIT_INTERFACE(&description);
    description.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    description.naxes = SDL_GAMEPAD_AXIS_COUNT;
    description.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    description.axis_mask = (1u << SDL_GAMEPAD_AXIS_COUNT) - 1u;
    description.button_mask = (1u << SDL_GAMEPAD_BUTTON_COUNT) - 1u;
    description.name = name;
    *id = SDL_AttachVirtualJoystick(&description);
    CHECK(*id != 0);
    *joystick = SDL_OpenJoystick(*id);
    CHECK(*joystick != NULL);
    CHECK(SDL_SetJoystickVirtualAxis(*joystick, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_JOYSTICK_AXIS_MIN));
    CHECK(SDL_SetJoystickVirtualAxis(*joystick, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, SDL_JOYSTICK_AXIS_MIN));
    return true;
}

static bool setup(void) {
    CHECK(getenv("LARECOMP_HOST_INPUT") == NULL);
    CHECK(getenv("LARECOMP_INPUT") == NULL);
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    CHECK(SDL_Init(SDL_INIT_GAMEPAD | SDL_INIT_EVENTS));
    CHECK(attach(&primary_id, &primary, "Monado authored primary controller"));
    // Set the production selected pad explicitly. SDL may enumerate real pads,
    // but their state/events never enters this fixture's actual input route.
    pad = SDL_OpenGamepad(primary_id);
    CHECK(pad != NULL);
    pump();
    g_mouse_look = 0;
    input_reset();
    CHECK(!host_test);
    CHECK(SDL_GetGamepadID(pad) == primary_id);
    CHECK(SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) == 0);
    SDL_ClearError(); // UDEV may be unavailable; the virtual device is verified.
    return true;
}

static bool axis(int number, Sint16 value) {
    CHECK(SDL_SetJoystickVirtualAxis(primary, number, value));
    pump();
    return true;
}
static bool button(int number, bool held) {
    CHECK(SDL_SetJoystickVirtualButton(primary, number, held));
    pump();
    return true;
}
static PadState state(void) {
    PadState output;
    uint32_t id = 0;
    Cpu cpu = {0};
    cpu.x[0] = (uintptr_t)&output;
    cpu.x[1] = (uintptr_t)&id;
    ++present;
    fill_state(&cpu);
    return output;
}
static bool held(int logical) { return (state().buttons & (1ull << logical)) != 0; }
static bool release_trigger(void) { return axis(SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_JOYSTICK_AXIS_MIN); }
static bool press_trigger(void) { return axis(SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_JOYSTICK_AXIS_MAX); }
static void idle_wait(void) { SDL_Delay(100); }
static void sync_pad(void) {
    // Settings/remapping apply on an input event in the real SDL loop. Sample
    // the selected device while neutral before beginning each intended hold.
    SDL_Event event = {0}; event.type = SDL_EVENT_GAMEPAD_AXIS_MOTION;
    event.gaxis.which = primary_id; event.gaxis.axis = SDL_GAMEPAD_AXIS_LEFTX;
    input_handle_event(&event);
}
static void party_option(bool enabled) { g_party_switch = enabled; sync_pad(); }
static void key(SDL_Scancode scancode, bool down) {
    SDL_Event event = {0}; event.type = down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
    event.key.scancode = scancode; input_handle_event(&event);
}

static bool vanilla(void) {
    party_option(false);
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_ZL)); CHECK(state().rx > 16000);
    idle_wait(); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool immediate_hold(void) {
    party_option(true);
    CHECK(press_trigger());
    // Native HUD/camera help must see held ZL before any camera movement.
    CHECK(held(BIND_ZL)); CHECK(state().rx == 0 && state().ry == 0);
    idle_wait(); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    idle_wait(); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool camera_stick(void) {
    party_option(true);
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000));
    CHECK(held(BIND_ZL)); CHECK(state().rx > 16000);
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 0)); CHECK(held(BIND_ZL));
    idle_wait(); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool preexisting_motion(void) {
    party_option(true);
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTY, -24000));
    CHECK(!held(BIND_ZL)); CHECK(state().ry > 16000);
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool camera_dpad(void) {
    party_option(true); g_settings.dpad_move = true;
    CHECK(press_trigger());
    CHECK(button(SDL_GAMEPAD_BUTTON_DPAD_UP, true));
    CHECK(held(BIND_ZL)); CHECK(held(BIND_UP));
    CHECK(state().lx == 0 && state().ly == 0);
    CHECK(button(SDL_GAMEPAD_BUTTON_DPAD_UP, false)); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool drift_deadzone(void) {
    party_option(true); g_settings.stick_deadzone = 25;
    CHECK(press_trigger());
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 8000));
    CHECK(state().rx == 0); CHECK(held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 10000));
    CHECK(state().rx > 0 && state().rx < 4915); CHECK(held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 8000)); CHECK(state().rx == 0); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool transition_held(void) {
    party_option(false);
    CHECK(press_trigger()); CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_ZL));
    party_option(true); CHECK(!held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    party_option(false); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    party_option(true); CHECK(press_trigger()); CHECK(held(BIND_ZL));
    CHECK(bind_settings_load("bind_pad_zl", "back"));
    CHECK(bind_settings_load("bind_pad_a", "ltrigger")); sync_pad();
    CHECK(!held(BIND_ZL) && !held(BIND_A));
    CHECK(release_trigger()); CHECK(!held(BIND_A));
    CHECK(press_trigger()); CHECK(held(BIND_A) && !held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_A)); CHECK(switches == 0);
    return true;
}
static bool tap(void) {
    party_option(true);
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    idle_wait(); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    idle_wait(); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool chord(int shoulder, int direction, bool trigger_first_release) {
    party_option(true);
    CHECK(press_trigger()); CHECK(button(shoulder, true));
    CHECK(switches == 1 && last_switch == direction);
    CHECK(held(BIND_ZL) && !held(BIND_L) && !held(BIND_R));
    // Repeated axis events and reads cannot repeat the switch.
    CHECK(axis(SDL_GAMEPAD_AXIS_LEFTX, 12000)); CHECK(switches == 1);
    if (trigger_first_release) {
        CHECK(release_trigger()); CHECK(!held(BIND_ZL));
        CHECK(!held(BIND_L) && !held(BIND_R));
        CHECK(button(shoulder, false));
    } else {
        CHECK(button(shoulder, false)); CHECK(release_trigger());
    }
    CHECK(!held(BIND_ZL)); CHECK(switches == 1);
    return true;
}
static bool queued_chord(void) {
    party_option(true);
    const int shoulders[] = {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER};
    for (int i = 0; i < 2; ++i) {
        CHECK(press_trigger());
        CHECK(SDL_SetJoystickVirtualButton(primary, shoulders[i], true));
        SDL_UpdateJoysticks(); // Physical sample is newer than the pending SDL DOWN edge.
        if (i == 0) key(SDL_SCANCODE_H, true);
        else sync_pad(); // Exercise both key and axis events arriving first.
        CHECK(!held(BIND_L) && !held(BIND_R)); CHECK(switches == i);
        pump(); CHECK(switches == i + 1 && last_switch == (i ? 1 : -1));
        CHECK(!held(BIND_L) && !held(BIND_R));
        if (i == 0) key(SDL_SCANCODE_H, false);
        CHECK(button(shoulders[i], false)); CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    }
    return true;
}
static bool remapped(void) {
    g_party_switch = true;
    CHECK(bind_settings_load("bind_pad_zl", "back"));
    CHECK(bind_settings_load("bind_pad_a", "ltrigger"));
    sync_pad();
    CHECK(press_trigger()); CHECK(held(BIND_A) && !held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000));
    CHECK(held(BIND_A)); CHECK(!held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_A));
    CHECK(button(SDL_GAMEPAD_BUTTON_BACK, true)); CHECK(held(BIND_ZL));
    CHECK(button(SDL_GAMEPAD_BUTTON_BACK, false)); CHECK(!held(BIND_ZL));
    CHECK(switches == 0);
    return true;
}
static bool remapped_direction(void) {
    party_option(true);
    CHECK(bind_settings_load("bind_pad_zl", "back"));
    CHECK(bind_settings_load("bind_pad_up", "ltrigger")); sync_pad();
    CHECK(press_trigger()); CHECK(held(BIND_UP) && !held(BIND_ZL));
    idle_wait(); CHECK(held(BIND_UP));
    CHECK(release_trigger()); CHECK(!held(BIND_UP));
    idle_wait(); CHECK(!held(BIND_UP));
    CHECK(press_trigger()); CHECK(held(BIND_UP));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_UP) && !held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_UP));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 0));
    CHECK(press_trigger()); CHECK(held(BIND_UP));
    CHECK(button(SDL_GAMEPAD_BUTTON_DPAD_RIGHT, true));
    CHECK(held(BIND_RIGHT) && held(BIND_UP) && !held(BIND_ZL));
    CHECK(button(SDL_GAMEPAD_BUTTON_DPAD_RIGHT, false)); CHECK(held(BIND_UP));
    CHECK(release_trigger()); CHECK(!held(BIND_UP)); CHECK(switches == 0);
    return true;
}
static bool keyboard(void) {
    party_option(true);
    SDL_Event event = {0}; event.type = SDL_EVENT_KEY_DOWN; event.key.scancode = SDL_SCANCODE_C;
    input_handle_event(&event); CHECK(held(BIND_ZL));
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    event.type = SDL_EVENT_KEY_UP; input_handle_event(&event); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    idle_wait(); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool keyboard_camera(void) {
    party_option(true);
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    key(SDL_SCANCODE_KP_6, true); CHECK(held(BIND_ZL)); CHECK(state().rx > 16000);
    key(SDL_SCANCODE_KP_6, false); CHECK(state().rx == 0); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}
static bool scripted_without_pad(void) {
    party_option(true); host_test = true;
    test_pad = 1u << PADB_LTRIGGER; test_lx = 12000; test_ly = -14000; sync_pad();
    CHECK(held(BIND_ZL)); CHECK(state().lx == test_lx && state().ly == test_ly);
    SDL_CloseGamepad(pad); pad = NULL;
    CHECK(SDL_DetachVirtualJoystick(primary_id));
    SDL_CloseJoystick(primary); primary = NULL; pump();
    CHECK(held(BIND_ZL)); CHECK(state().lx == test_lx && state().ly == test_ly);
    test_pad = 0; sync_pad(); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    host_test = false; test_lx = test_ly = 0;
    key(SDL_SCANCODE_C, true); CHECK(held(BIND_ZL));
    key(SDL_SCANCODE_C, false); CHECK(!held(BIND_ZL));
    return true;
}
static bool reset_boundary(bool focus) {
    party_option(true);
    CHECK(press_trigger()); CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_ZL));
    if (focus) {
        SDL_Event event = {0}; event.type = SDL_EVENT_WINDOW_FOCUS_LOST;
        input_handle_event(&event);
    } else {
        captured = true; input_reset();
        CHECK(!held(BIND_ZL));
        captured = false; input_reset();
    }
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 0));
    idle_wait(); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    if (focus) {
        CHECK(press_trigger()); CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(!held(BIND_ZL));
        SDL_Event event = {0}; event.type = SDL_EVENT_WINDOW_FOCUS_GAINED;
        input_handle_event(&event); CHECK(!held(BIND_ZL));
        CHECK(release_trigger()); CHECK(!held(BIND_ZL));
        CHECK(press_trigger()); CHECK(held(BIND_ZL));
        CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    }
    return true;
}
static bool wrong_device(void) {
    party_option(true);
    CHECK(attach(&other_id, &other, "Monado authored secondary controller")); pump();
    other_pad = SDL_OpenGamepad(other_id); CHECK(other_pad != NULL);
    CHECK(press_trigger());
    CHECK(SDL_SetJoystickVirtualButton(other, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, true)); pump();
    CHECK(other_button_down > 0);
    CHECK(switches == 0);
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    idle_wait(); CHECK(!held(BIND_ZL));
    return true;
}
static bool disconnect(void) {
    party_option(true);
    CHECK(press_trigger()); CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_ZL));
    CHECK(SDL_DetachVirtualJoystick(primary_id));
    SDL_CloseJoystick(primary); primary = NULL; pump();
    CHECK(!held(BIND_ZL)); CHECK(pad == NULL);
    CHECK(attach(&primary_id, &primary, "Monado authored replacement controller"));
    pad = SDL_OpenGamepad(primary_id); CHECK(pad != NULL); pump();
    CHECK(!held(BIND_ZL));
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); idle_wait(); CHECK(!held(BIND_ZL));
    return true;
}
static _Atomic bool cancellation_started;
static int SDLCALL cancellation_worker(void *unused) {
    (void)unused;
    // Exercise the actual render-thread cancellation boundary directly, without
    // input_reset's older keyboard/mouse globals entering this concurrency test.
    for (int i = 0; i < 12000; ++i) {
        cancel_pad_modifier();
        atomic_store(&cancellation_started, true);
        if (!(i & 63)) SDL_Delay(0);
    }
    return 0;
}
static bool concurrent_cancellation(void) {
    party_option(true);
    CHECK(press_trigger()); CHECK(axis(SDL_GAMEPAD_AXIS_RIGHTX, 24000)); CHECK(held(BIND_ZL));
    SDL_Thread *worker = SDL_CreateThread(cancellation_worker, "Monado input cancellation fixture", NULL);
    CHECK(worker != NULL);
    uint64_t deadline = SDL_GetTicks() + 2000;
    while (!atomic_load(&cancellation_started) && SDL_GetTicks() < deadline) SDL_Delay(1);
    bool started = atomic_load(&cancellation_started), stable = true;
    for (int i = 0; i < 12000; ++i) {
        recompute_pad(0);
        if (input_buttons_now() & (1ull << BIND_ZL)) stable = false;
        if (!(i & 63)) SDL_Delay(0);
    }
    int status = -1; SDL_WaitThread(worker, &status);
    CHECK(started && status == 0 && stable);
    CHECK(release_trigger()); CHECK(!held(BIND_ZL));
    CHECK(press_trigger()); CHECK(held(BIND_ZL));
    CHECK(release_trigger()); CHECK(!held(BIND_ZL)); CHECK(switches == 0);
    return true;
}

int main(int argc, char **argv) {
    if (argc != 2 || !setup()) return 2;
    const char *name = argv[1]; bool ok = false;
    if (!strcmp(name, "vanilla")) ok = vanilla();
    else if (!strcmp(name, "immediate-hold")) ok = immediate_hold();
    else if (!strcmp(name, "camera-stick")) ok = camera_stick();
    else if (!strcmp(name, "preexisting-motion")) ok = preexisting_motion();
    else if (!strcmp(name, "camera-dpad")) ok = camera_dpad();
    else if (!strcmp(name, "drift-deadzone")) ok = drift_deadzone();
    else if (!strcmp(name, "transition-held")) ok = transition_held();
    else if (!strcmp(name, "tap")) ok = tap();
    else if (!strcmp(name, "chord-left")) ok = chord(SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, -1, false);
    else if (!strcmp(name, "chord-right")) ok = chord(SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, 1, false);
    else if (!strcmp(name, "chord-trigger-release")) ok = chord(SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, -1, true);
    else if (!strcmp(name, "queued-chord")) ok = queued_chord();
    else if (!strcmp(name, "remapped")) ok = remapped();
    else if (!strcmp(name, "remapped-direction")) ok = remapped_direction();
    else if (!strcmp(name, "keyboard")) ok = keyboard();
    else if (!strcmp(name, "keyboard-camera")) ok = keyboard_camera();
    else if (!strcmp(name, "scripted-without-pad")) ok = scripted_without_pad();
    else if (!strcmp(name, "menu-reset")) ok = reset_boundary(false);
    else if (!strcmp(name, "focus-reset")) ok = reset_boundary(true);
    else if (!strcmp(name, "wrong-device")) ok = wrong_device();
    else if (!strcmp(name, "disconnect")) ok = disconnect();
    else if (!strcmp(name, "concurrent-cancellation")) ok = concurrent_cancellation();
    if (pad) { SDL_CloseGamepad(pad); pad = NULL; }
    if (primary) SDL_CloseJoystick(primary);
    if (other_pad) SDL_CloseGamepad(other_pad);
    if (other) SDL_CloseJoystick(other);
    if (SDL_IsJoystickVirtual(primary_id)) SDL_DetachVirtualJoystick(primary_id);
    if (other_id && SDL_IsJoystickVirtual(other_id)) SDL_DetachVirtualJoystick(other_id);
    SDL_Quit();
    if (ok) printf("native SDL camera input: PASS %s (real production route, host_test=false)\n", name);
    return ok ? 0 : 1;
}
