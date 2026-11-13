// [XCDE] LINUX-077: actual pinned SDL reads the inherited Steam acceptance hint.
// No SDL subsystem initialization, hardware, window, game input or profile.
#include <SDL3/SDL.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    bool expected_allowed = argv[1][0] == '1';
    bool actual = SDL_GetHintBoolean("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD", false);
    printf("SDL inherited Steam controller context: allowed=%d expected=%d\n", actual, expected_allowed);
    return actual == expected_allowed ? 0 : 1;
}
