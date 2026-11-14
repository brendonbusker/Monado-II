// [XCDE] LINUX-077: bounded SDL discovery diagnostics, on the SDL event thread.
#pragma once
#include <SDL3/SDL.h>
#include <stdio.h>

// Device names may be supplied by hardware or a virtual controller. Keep one
// bounded line per device without serial numbers, paths or control characters.
static inline const char *rt_input_log_name(const char *name, char text[97]) {
    unsigned n = 0;
    if (!name) name = "(unknown)";
    while (*name && n < 96) {
        unsigned char value = (unsigned char)*name++;
        text[n++] = value < 32 || value == 127 ? '?' : (char)value;
    }
    text[n] = 0;
    return text;
}

// [XCDE] LINUX-089: driver/open errors can include a virtual device's text too.
static inline const char *rt_input_log_error(const char *error, char text[193]) {
    unsigned n = 0;
    if (!error) error = "(unknown)";
    while (*error && n < 192) {
        unsigned char value = (unsigned char)*error++;
        text[n++] = value < 32 || value == 127 ? '?' : (char)value;
    }
    text[n] = 0;
    return text;
}

static inline void rt_input_inventory(FILE *output, const char *component, const char *reason) {
    static unsigned reports;
    if (!output || reports >= 16) return;
    if (!reports++)
        fprintf(output, "[input:%s] SDL compiled=%d runtime=%d; Steam virtual gamepad allowed=%s\n",
                component, SDL_VERSION, SDL_GetVersion(),
                SDL_GetHintBoolean("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD", false) ? "yes" : "no");
    int joysticks = 0, gamepads = 0;
    SDL_JoystickID *ids = SDL_GetJoysticks(&joysticks);
    SDL_JoystickID *mapped = SDL_GetGamepads(&gamepads);
    fprintf(output, "[input:%s] %s: joysticks=%d mapped-gamepads=%d\n",
            component, reason, joysticks, gamepads);
    for (int i = 0; ids && i < joysticks && i < 16; ++i) {
        char guid[33], name[97];
        SDL_GUIDToString(SDL_GetJoystickGUIDForID(ids[i]), guid, sizeof guid);
        fprintf(output, "[input:%s] id=%u name=%s vid=%04x pid=%04x guid=%s mapped=%s\n",
                component, (unsigned)ids[i], rt_input_log_name(SDL_GetJoystickNameForID(ids[i]), name),
                (unsigned)SDL_GetJoystickVendorForID(ids[i]), (unsigned)SDL_GetJoystickProductForID(ids[i]), guid,
                SDL_IsGamepad(ids[i]) ? "yes" : "no");
    }
    if (joysticks > 16) fprintf(output, "[input:%s] remaining inventory omitted\n", component);
    SDL_free(ids);
    SDL_free(mapped);
}
