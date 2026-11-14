// [XCDE] LINUX-089: authored virtual controllers through the real ImGui SDL3
// backend and ImGui core. SDL dummy video; no game, renderer, human input/state.
#include <SDL3/SDL.h>
#include "imgui.h"
#include "imgui_internal.h"
#include <cstdio>
#include <cstring>

static SDL_JoystickID allowed[4], refused;
static unsigned opens, closes, scans;
static Uint64 now_ms = 100;
static Uint64 fixture_ticks() { return now_ms; }
static SDL_Gamepad *fixture_open(SDL_JoystickID id) {
    ++opens;
    if (id == refused) { SDL_SetError("authored transient open refusal"); return nullptr; }
    return SDL_OpenGamepad(id);
}
static void fixture_close(SDL_Gamepad *pad) { ++closes; SDL_CloseGamepad(pad); }
static SDL_JoystickID *fixture_ids(int *count) {
    ++scans;
    int actual_count = 0;
    SDL_JoystickID *actual = SDL_GetGamepads(&actual_count);
    auto *result = static_cast<SDL_JoystickID *>(SDL_calloc(5, sizeof(SDL_JoystickID)));
    *count = 0;
    for (unsigned i = 0; result && i < 4; ++i)
        for (int j = 0; allowed[i] && actual && j < actual_count; ++j)
            if (allowed[i] == actual[j]) { result[(*count)++] = allowed[i]; break; }
    SDL_free(actual);
    return result;
}
#define SDL_OpenGamepad fixture_open
#define SDL_CloseGamepad fixture_close
#define SDL_GetGamepads fixture_ids
#define SDL_GetTicks fixture_ticks
#include "../../Monado_Linux/third_party/imgui/backends/imgui_impl_sdl3.cpp"
#undef SDL_GetTicks
#undef SDL_GetGamepads
#undef SDL_CloseGamepad
#undef SDL_OpenGamepad

#define CHECK(condition) do { if (!(condition)) { \
    std::fprintf(stderr, "FAIL %s:%d: %s (SDL: %s)\n", __FILE__, __LINE__, #condition, SDL_GetError()); \
    return false; \
} } while (0)

static SDL_JoystickID primary_id, other_id;
static SDL_Joystick *primary, *other;
static SDL_Gamepad *manual;
static SDL_Window *window;
static bool attach(SDL_JoystickID *id, SDL_Joystick **joystick, unsigned index) {
    SDL_VirtualJoystickDesc description;
    SDL_INIT_INTERFACE(&description);
    description.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    description.naxes = SDL_GAMEPAD_AXIS_COUNT;
    description.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    description.axis_mask = (1u << SDL_GAMEPAD_AXIS_COUNT) - 1u;
    description.button_mask = (1u << SDL_GAMEPAD_BUTTON_COUNT) - 1u;
    description.name = "Monado authored ImGui controller";
    *id = SDL_AttachVirtualJoystick(&description); CHECK(*id);
    *joystick = SDL_OpenJoystick(*id); CHECK(*joystick);
    CHECK(SDL_SetJoystickVirtualAxis(*joystick, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, SDL_JOYSTICK_AXIS_MIN));
    CHECK(SDL_SetJoystickVirtualAxis(*joystick, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, SDL_JOYSTICK_AXIS_MIN));
    allowed[index] = *id;
    return true;
}
static void drain() {
    SDL_UpdateGamepads();
    SDL_Event event;
    while (SDL_PollEvent(&event)) {} // Deliberately simulate events consumed by another loop/overlay.
}
static void tick(Uint64 elapsed = 0) { now_ms += elapsed; ImGui_ImplSDL3_UpdateGamepads(); }
static void focus(bool gain) {
    SDL_Event event = {};
    event.type = gain ? SDL_EVENT_WINDOW_FOCUS_GAINED : SDL_EVENT_WINDOW_FOCUS_LOST;
    event.window.windowID = SDL_GetWindowID(window);
    ImGui_ImplSDL3_ProcessEvent(&event);
}
static bool latest_key_down(ImGuiKey key) {
    ImGuiContext *context = ImGui::GetCurrentContext();
    for (int i = context->InputEventsQueue.Size - 1; i >= 0; --i) {
        const ImGuiInputEvent &event = context->InputEventsQueue[i];
        if (event.Type == ImGuiInputEventType_Key && event.Key.Key == key) return event.Key.Down;
    }
    return false;
}
static bool run(const char *name) {
    auto *data = ImGui_ImplSDL3_GetBackendData(); CHECK(data);
    if (!std::strcmp(name, "delayed")) {
        tick(); CHECK(data->Gamepads.Size == 0);
        CHECK(attach(&primary_id, &primary, 0)); drain();
        tick(1000); CHECK(data->Gamepads.Size == 1);
        CHECK(SDL_GetGamepadID(data->Gamepads[0]) == primary_id);
    } else if (!std::strcmp(name, "focus-retry")) {
        CHECK(attach(&primary_id, &primary, 0)); drain(); refused = primary_id;
        tick(); CHECK(data->Gamepads.Size == 0 && opens == 1);
        refused = 0; focus(true); tick();
        CHECK(data->Gamepads.Size == 1 && SDL_GetGamepadID(data->Gamepads[0]) == primary_id);
    } else if (!std::strcmp(name, "replacement")) {
        CHECK(attach(&primary_id, &primary, 0)); drain(); tick();
        CHECK(data->Gamepads.Size == 1);
        CHECK(SDL_DetachVirtualJoystick(primary_id)); drain();
        SDL_CloseJoystick(primary); primary = nullptr;
        CHECK(attach(&primary_id, &primary, 0)); drain(); tick(1000);
        CHECK(data->Gamepads.Size == 1 && SDL_GetGamepadID(data->Gamepads[0]) == primary_id);
    } else if (!std::strcmp(name, "healthy")) {
        CHECK(attach(&primary_id, &primary, 0)); drain(); tick();
        auto *original = data->Gamepads[0]; unsigned first_opens = opens, first_closes = closes;
        CHECK(attach(&other_id, &other, 1)); drain();
        allowed[0] = other_id; allowed[1] = primary_id; // New enumeration order must not steal AutoFirst.
        SDL_Event event = {}; event.type = SDL_EVENT_GAMEPAD_ADDED; event.gdevice.which = other_id;
        ImGui_ImplSDL3_ProcessEvent(&event); focus(false); focus(true); tick();
        CHECK(data->Gamepads.Size == 1 && data->Gamepads[0] == original);
        CHECK(opens == first_opens && closes == first_closes);
        unsigned first_scans = scans;
        for (unsigned i = 0; i < 100000; ++i) tick(1);
        CHECK(opens == first_opens && closes == first_closes && scans == first_scans);
    } else if (!std::strcmp(name, "all")) {
        ImGui_ImplSDL3_SetGamepadMode(ImGui_ImplSDL3_GamepadMode_AutoAll);
        CHECK(attach(&primary_id, &primary, 0)); CHECK(attach(&other_id, &other, 1)); drain(); tick();
        CHECK(data->Gamepads.Size == 2); auto *healthy = data->Gamepads[1];
        CHECK(SDL_DetachVirtualJoystick(primary_id)); drain();
        SDL_CloseJoystick(primary); primary = nullptr;
        CHECK(attach(&primary_id, &primary, 0)); drain(); tick(1000);
        CHECK(data->Gamepads.Size == 2 && data->Gamepads[0] == healthy);
        CHECK(SDL_GetGamepadID(data->Gamepads[1]) == primary_id && closes == 1);
    } else if (!std::strcmp(name, "manual")) {
        CHECK(attach(&primary_id, &primary, 0)); drain();
        manual = SDL_OpenGamepad(primary_id); CHECK(manual);
        ImGui_ImplSDL3_SetGamepadMode(ImGui_ImplSDL3_GamepadMode_Manual, &manual, 1);
        CHECK(attach(&other_id, &other, 1)); drain();
        unsigned first_scans = scans, first_opens = opens, first_closes = closes;
        focus(true); for (unsigned i = 0; i < 10; ++i) tick(1000);
        CHECK(data->Gamepads.Size == 1 && data->Gamepads[0] == manual);
        CHECK(scans == first_scans && opens == first_opens && closes == first_closes);
    } else if (!std::strcmp(name, "release")) {
        CHECK(attach(&primary_id, &primary, 0)); drain(); tick();
        CHECK(SDL_SetJoystickVirtualButton(primary, SDL_GAMEPAD_BUTTON_SOUTH, true)); drain(); tick();
        CHECK(latest_key_down(ImGuiKey_GamepadFaceDown));
        CHECK(SDL_DetachVirtualJoystick(primary_id)); drain();
        SDL_Event event = {}; event.type = SDL_EVENT_GAMEPAD_REMOVED; event.gdevice.which = primary_id;
        ImGui_ImplSDL3_ProcessEvent(&event); tick(1000);
        CHECK(data->Gamepads.Size == 0);
        CHECK(!latest_key_down(ImGuiKey_GamepadFaceDown));
        CHECK(!(ImGui::GetIO().BackendFlags & ImGuiBackendFlags_HasGamepad));
    } else if (!std::strcmp(name, "retry-backoff")) {
        CHECK(attach(&primary_id, &primary, 0)); drain(); refused = primary_id;
        tick(); CHECK(opens == 1 && data->Gamepads.Size == 0);
        for (unsigned i = 0; i < 10000; ++i) tick();
        tick(999); CHECK(opens == 1 && data->Gamepads.Size == 0);
        tick(1); CHECK(opens == 2 && data->Gamepads.Size == 0);
        refused = 0; tick(1000); CHECK(data->Gamepads.Size == 1);
    } else if (!std::strcmp(name, "all-addition")) {
        ImGui_ImplSDL3_SetGamepadMode(ImGui_ImplSDL3_GamepadMode_AutoAll);
        CHECK(attach(&primary_id, &primary, 0)); drain(); tick();
        auto *original = data->Gamepads[0];
        CHECK(attach(&other_id, &other, 1)); drain(); tick(1000);
        CHECK(data->Gamepads.Size == 2 && data->Gamepads[0] == original && closes == 0);
    } else return false;
    return true;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD | SDL_INIT_EVENTS)) return 2;
    window = SDL_CreateWindow("Monado authored backend fixture", 32, 32, SDL_WINDOW_HIDDEN);
    if (!window) return 2;
    IMGUI_CHECKVERSION(); ImGui::CreateContext();
    ImGui::GetIO().IniFilename = nullptr;
    ImGui::GetIO().ConfigFlags |= ImGuiConfigFlags_NavEnableGamepad;
    if (!ImGui_ImplSDL3_InitForOther(window)) return 2;
    SDL_ClearError(); // Dummy video deliberately does not implement OS cursors.
    bool ok = run(argv[1]);
    unsigned before_shutdown = closes;
    bool manual_mode = ImGui_ImplSDL3_GetBackendData()->GamepadMode == ImGui_ImplSDL3_GamepadMode_Manual;
    ImGui_ImplSDL3_Shutdown();
    if (manual_mode && (closes != before_shutdown || !SDL_GamepadConnected(manual))) ok = false;
    if (manual) SDL_CloseGamepad(manual);
    ImGui::DestroyContext(); SDL_DestroyWindow(window);
    if (primary) SDL_CloseJoystick(primary);
    if (other) SDL_CloseJoystick(other);
    if (primary_id && SDL_IsJoystickVirtual(primary_id)) SDL_DetachVirtualJoystick(primary_id);
    if (other_id && SDL_IsJoystickVirtual(other_id)) SDL_DetachVirtualJoystick(other_id);
    SDL_Quit();
    if (ok) std::printf("native ImGui controller recovery: PASS %s\n", argv[1]);
    return ok ? 0 : 1;
}
