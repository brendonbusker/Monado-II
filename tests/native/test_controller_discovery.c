// [XCDE] LINUX-077: authored SDL virtual pads through the production input.c.
// The fixture restricts discovery to its own IDs and can refuse one open.
#include <SDL3/SDL.h>
static SDL_JoystickID allowed[4], refused;
static unsigned refused_attempts, open_attempts, enumeration_attempts;
static Uint64 discovery_now = 100;
static Uint64 discovery_ticks(void) { return discovery_now; }
static SDL_Gamepad *discovery_open(SDL_JoystickID id) {
    ++open_attempts;
    if (id == refused) {
        ++refused_attempts;
        SDL_SetError("authored gamepad open refusal");
        return NULL;
    }
    return SDL_OpenGamepad(id);
}
static SDL_JoystickID *discovery_ids(int *count) {
    ++enumeration_attempts;
    int n = 0;
    SDL_JoystickID *actual = SDL_GetGamepads(&n);
    SDL_JoystickID *result = SDL_calloc(5, sizeof(*result));
    if (!result) { *count = 0; SDL_free(actual); return NULL; }
    *count = 0;
    for (unsigned i = 0; i < 4; ++i)
        for (int j = 0; actual && allowed[i] && j < n; ++j)
            if (actual[j] == allowed[i]) { result[(*count)++] = allowed[i]; break; }
    SDL_free(actual);
    return result;
}
#define SDL_OpenGamepad discovery_open
#define SDL_GetGamepads discovery_ids
#define SDL_GetTicks discovery_ticks
#define main retained_camera_fixture_main
#include "test_input_camera.c"
#undef main
#undef SDL_GetGamepads
#undef SDL_OpenGamepad
#undef SDL_GetTicks

static void initial_event(void) {
    SDL_Event event = {0}; event.type = SDL_EVENT_KEY_UP;
    event.key.scancode = SDL_SCANCODE_UNKNOWN;
    input_handle_event(&event);
}
static void drain_without_guest(void) {
    SDL_UpdateJoysticks();
    SDL_Event event;
    while (SDL_PollEvent(&event)) {}
}
static void focus_event(bool gained) {
    SDL_Event event = {0};
    event.type = gained ? SDL_EVENT_WINDOW_FOCUS_GAINED : SDL_EVENT_WINDOW_FOCUS_LOST;
    input_handle_event(&event);
}
static bool add_primary(void) {
    CHECK(attach(&primary_id, &primary, "Monado discovery primary"));
    allowed[0] = primary_id;
    return true;
}
static bool add_other(void) {
    CHECK(attach(&other_id, &other, "Monado discovery secondary"));
    allowed[1] = other_id;
    return true;
}
static bool run_discovery(const char *name) {
    if (!strcmp(name, "startup")) {
        CHECK(add_primary()); drain_without_guest(); initial_event();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
    } else if (!strcmp(name, "delayed")) {
        initial_event(); CHECK(pad == NULL);
        CHECK(add_primary()); pump();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
    } else if (!strcmp(name, "failed-first")) {
        CHECK(add_primary()); CHECK(add_other()); refused = primary_id;
        drain_without_guest(); initial_event();
        CHECK(refused_attempts == 1);
        CHECK(pad && SDL_GetGamepadID(pad) == other_id);
    } else if (!strcmp(name, "all-failed")) {
        CHECK(add_primary()); refused = primary_id;
        drain_without_guest(); initial_event(); CHECK(pad == NULL);
        CHECK(state().buttons == 0);
        refused = 0;
        SDL_Event event = {0}; event.type = SDL_EVENT_GAMEPAD_ADDED;
        event.gdevice.which = primary_id; input_handle_event(&event);
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
    } else if (!strcmp(name, "multiple")) {
        CHECK(add_primary()); pump();
        CHECK(add_other()); pump();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        CHECK(SDL_SetJoystickVirtualButton(other, SDL_GAMEPAD_BUTTON_SOUTH, true));
        pump(); CHECK(!held(BIND_B));
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
    } else if (!strcmp(name, "replacement")) {
        CHECK(add_primary()); CHECK(add_other()); pump();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        CHECK(SDL_DetachVirtualJoystick(primary_id)); pump();
        CHECK(pad && SDL_GetGamepadID(pad) == other_id);
        CHECK(!held(BIND_B));
        CHECK(SDL_SetJoystickVirtualButton(other, SDL_GAMEPAD_BUTTON_SOUTH, true));
        pump(); CHECK(held(BIND_B));
    } else if (!strcmp(name, "reconnect")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        CHECK(SDL_DetachVirtualJoystick(primary_id)); pump();
        CHECK(pad == NULL && !held(BIND_B));
        SDL_CloseJoystick(primary); primary = NULL;
        CHECK(add_primary()); pump();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id && !held(BIND_B));
    } else if (!strcmp(name, "focus-retry")) {
        CHECK(add_primary()); refused = primary_id;
        drain_without_guest(); initial_event(); CHECK(pad == NULL);
        refused = 0; focus_event(true);
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
    } else if (!strcmp(name, "focus-replacement")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        CHECK(SDL_DetachVirtualJoystick(primary_id)); drain_without_guest();
        SDL_CloseJoystick(primary); primary = NULL;
        CHECK(add_primary()); drain_without_guest(); focus_event(true);
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        CHECK(!held(BIND_B));
    } else if (!strcmp(name, "focus-healthy")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        SDL_Gamepad *original = pad; unsigned attempts = open_attempts;
        focus_event(false); focus_event(true);
        CHECK(pad == original && open_attempts == attempts);
        CHECK(held(BIND_B));
    } else if (!strcmp(name, "focus-release")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        CHECK(SDL_SetJoystickVirtualButton(primary, SDL_GAMEPAD_BUTTON_SOUTH, false));
        drain_without_guest(); focus_event(true);
        CHECK(!held(BIND_B));
    } else if (!strcmp(name, "periodic-discovery")) {
        initial_event(); CHECK(pad == NULL);
        CHECK(add_primary()); drain_without_guest();
        unsigned attempts = open_attempts, scans = enumeration_attempts;
        for (unsigned i = 0; i < 10000; ++i) input_poll_controller();
        CHECK(pad == NULL && open_attempts == attempts && enumeration_attempts == scans);
        discovery_now += 999; input_poll_controller(); CHECK(pad == NULL);
        ++discovery_now; input_poll_controller();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        CHECK(!held(BIND_B));
    } else if (!strcmp(name, "periodic-replacement")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        CHECK(axis(SDL_GAMEPAD_AXIS_LEFTX, 24000)); CHECK(state().lx > 16000);
        CHECK(SDL_DetachVirtualJoystick(primary_id)); drain_without_guest();
        SDL_CloseJoystick(primary); primary = NULL;
        CHECK(add_primary()); drain_without_guest();
        discovery_now += 1000; input_poll_controller();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        CHECK(!held(BIND_B) && state().lx == 0);
    } else if (!strcmp(name, "periodic-disconnected")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        CHECK(axis(SDL_GAMEPAD_AXIS_LEFTX, 24000)); CHECK(state().lx > 16000);
        CHECK(SDL_DetachVirtualJoystick(primary_id)); drain_without_guest();
        discovery_now += 1000; input_poll_controller();
        CHECK(pad == NULL && !held(BIND_B) && state().lx == 0);
    } else if (!strcmp(name, "retry-backoff")) {
        CHECK(add_primary()); refused = primary_id;
        drain_without_guest(); initial_event(); CHECK(pad == NULL && refused_attempts == 1);
        for (unsigned i = 0; i < 999; ++i) { ++discovery_now; input_poll_controller(); }
        CHECK(pad == NULL && refused_attempts == 1);
        ++discovery_now; input_poll_controller(); CHECK(pad == NULL && refused_attempts == 2);
        refused = 0;
        discovery_now += 999; input_poll_controller(); CHECK(pad == NULL);
        ++discovery_now; input_poll_controller();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id && open_attempts == 3);
    } else if (!strcmp(name, "healthy-ticks")) {
        CHECK(add_primary()); pump();
        CHECK(button(SDL_GAMEPAD_BUTTON_SOUTH, true)); CHECK(held(BIND_B));
        SDL_Gamepad *original = pad;
        unsigned attempts = open_attempts, scans = enumeration_attempts;
        for (unsigned i = 0; i < 100000; ++i) { ++discovery_now; input_poll_controller(); }
        CHECK(pad == original && open_attempts == attempts && enumeration_attempts == scans);
        CHECK(held(BIND_B));
    } else if (!strcmp(name, "idle-startup")) {
        CHECK(add_primary()); drain_without_guest();
        input_poll_controller();
        CHECK(pad && SDL_GetGamepadID(pad) == primary_id);
        unsigned attempts = open_attempts; initial_event();
        CHECK(open_attempts == attempts);
    } else if (!strcmp(name, "diagnostics")) {
        char clean[97], long_name[200];
        CHECK(!strcmp(rt_input_log_name("name\nforged\tline\r", clean), "name?forged?line?"));
        memset(long_name, 'a', sizeof(long_name) - 1); long_name[sizeof(long_name) - 1] = 0;
        CHECK(strlen(rt_input_log_name(long_name, clean)) == 96);
        char error[193], long_error[300];
        memset(long_error, 'b', sizeof(long_error) - 1); long_error[sizeof(long_error) - 1] = 0;
        CHECK(!strcmp(rt_input_log_error("open\nrefused\tdevice\r", error), "open?refused?device?"));
        CHECK(strlen(rt_input_log_error(long_error, error)) == 192);
        char *text = NULL; size_t length = 0;
        FILE *output = open_memstream(&text, &length); CHECK(output != NULL);
        for (int i = 0; i < 100; ++i) rt_input_inventory(output, "fixture", "bounded inventory");
        CHECK(!fclose(output));
        unsigned reports = 0;
        for (const char *cursor = text; (cursor = strstr(cursor, "bounded inventory")); ++cursor) ++reports;
        CHECK(reports == 16 && length < 65536);
        CHECK(strstr(text, "SDL compiled=") != NULL);
        free(text);
    } else return false;
    return true;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (!SDL_Init(SDL_INIT_GAMEPAD | SDL_INIT_EVENTS)) return 2;
    bool ok = run_discovery(argv[1]);
    if (pad) { SDL_CloseGamepad(pad); pad = NULL; }
    if (primary) SDL_CloseJoystick(primary);
    if (other) SDL_CloseJoystick(other);
    if (primary_id && SDL_IsJoystickVirtual(primary_id)) SDL_DetachVirtualJoystick(primary_id);
    if (other_id && SDL_IsJoystickVirtual(other_id)) SDL_DetachVirtualJoystick(other_id);
    SDL_Quit();
    if (ok) printf("native SDL controller discovery: PASS %s\n", argv[1]);
    return ok ? 0 : 1;
}
