// [XCDE] Linux input relocation: native folder selection without opening a profile.
// Authored code under the MIT license. Game input is validated by the parent helper.
#ifndef MONADO_LAUNCHER_INPUT_RECOVERY_H
#define MONADO_LAUNCHER_INPUT_RECOVERY_H

#include <SDL3/SDL.h>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>

namespace launcher_input_recovery {

// A single bounded UTF-8 path plus NUL is the entire stdout protocol. Control
// characters are rejected so diagnostics cannot masquerade as another selection.
static bool valid_path(const char *value) {
    if (!value || value[0] != '/') return false;
    size_t length = strnlen(value, 4096);
    if (!length || length >= 4096) return false;
    const auto *bytes = reinterpret_cast<const unsigned char *>(value);
    for (size_t i = 0; i < length;) {
        unsigned char c = bytes[i++];
        if (c < 0x20 || c == 0x7f) return false;
        if (c < 0x80) continue;
        unsigned n = c >= 0xc2 && c <= 0xdf ? 1 : c >= 0xe0 && c <= 0xef ? 2 : c >= 0xf0 && c <= 0xf4 ? 3 : 0;
        if (!n || i + n > length) return false;
        unsigned char first = bytes[i];
        if ((c == 0xe0 && first < 0xa0) || (c == 0xed && first >= 0xa0) ||
            (c == 0xf0 && first < 0x90) || (c == 0xf4 && first >= 0x90)) return false;
        for (unsigned j = 0; j < n; ++j) if ((bytes[i++] & 0xc0) != 0x80) return false;
    }
    return true;
}

struct Selection {
    std::mutex mutex;
    bool complete = false;
    std::string path, error;
};

static void SDLCALL selected(void *userdata, const char *const *files, int) {
    // SDL may call from another thread. Keep the state alive even if the event
    // loop was interrupted, and never call UI functions from the callback.
    std::unique_ptr<std::shared_ptr<Selection>> owner(static_cast<std::shared_ptr<Selection> *>(userdata));
    auto state = *owner;
    std::lock_guard<std::mutex> lock(state->mutex);
    if (!files) state->error = "The folder picker could not open. Please reopen Monado II and try again.";
    else if (files[0]) {
        if (files[1] || !valid_path(files[0])) state->error = "The folder picker returned an invalid game files path.";
        else state->path = files[0];
    }
    state->complete = true;
}

static int run(int argc, char **argv) {
    const char *missing = nullptr;
    if (argc == 4 && !strcmp(argv[2], "--missing-input") && valid_path(argv[3])) missing = argv[3];
    else if (argc != 2) {
        fprintf(stderr, "Usage: --locate-game-files [--missing-input ABSOLUTE_PATH]\n");
        return 2;
    }
    if (!SDL_Init(SDL_INIT_VIDEO)) { fprintf(stderr, "Could not open the game files picker: %s\n", SDL_GetError()); return 1; }
    std::string message = "Monado II cannot find your game files. Select their new folder containing exefs and romfs.\n\nYour installed build, saves and settings are preserved. This does not start a rebuild or launch the game.";
    if (missing) message += std::string("\n\nPrevious location: ") + missing;
    if (!SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_INFORMATION, "Monado II - Locate game files", message.c_str(), nullptr)) {
        fprintf(stderr, "Could not show the game files prompt: %s\n", SDL_GetError()); SDL_Quit(); return 1;
    }
    auto state = std::make_shared<Selection>();
    auto *callback_state = new std::shared_ptr<Selection>(state);
    SDL_ShowOpenFolderDialog(selected, callback_state, nullptr, missing, false);
    std::string path, error;
    for (;;) {
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            if (state->complete) { path = state->path; error = state->error; break; }
        }
        // XDG Portal/DBus dialogs need SDL's main-thread event pump on Linux.
        SDL_Event event;
        SDL_WaitEventTimeout(&event, 50);
    }
    SDL_Quit();
    if (!error.empty()) { fprintf(stderr, "%s\n", error.c_str()); return 1; }
    if (path.empty()) return 0; // Native Cancel is deliberately an empty response.
    if (fwrite(path.c_str(), 1, path.size() + 1, stdout) != path.size() + 1 || fflush(stdout)) {
        fprintf(stderr, "Could not return the selected game files path\n"); return 1;
    }
    return 0;
}

} // namespace launcher_input_recovery
#endif
