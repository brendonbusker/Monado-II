// Authored SDL callback fixture: no display, game data or real native dialog.
#include <cassert>
#include <chrono>
#include <cstdlib>
#include <thread>
#include "../../Monado_Linux/tools/launcher/input_recovery.h"

extern "C" bool SDL_Init(SDL_InitFlags flags) {
    assert(flags == SDL_INIT_VIDEO);
    assert(!getenv("MONADO_LOCATOR_FORBID_INIT"));
    return true;
}
extern "C" void SDL_Quit(void) {}
extern "C" const char *SDL_GetError(void) { return "authored SDL error"; }
extern "C" bool SDL_ShowSimpleMessageBox(SDL_MessageBoxFlags, const char *, const char *text, SDL_Window *window) {
    assert(!window && strstr(text, "saves and settings are preserved"));
    return true;
}
extern "C" bool SDL_WaitEventTimeout(SDL_Event *, Sint32) {
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
    return false;
}
extern "C" void SDL_ShowOpenFolderDialog(SDL_DialogFileCallback callback, void *userdata, SDL_Window *window, const char *, bool many) {
    assert(!window && !many);
    std::thread([callback, userdata] {
        const char *mode = getenv("MONADO_LOCATOR_FIXTURE");
        const char *selection[] = {"/tmp/Recovered Game Files/日本語", nullptr};
        const char *cancel[] = {nullptr};
        const char *relative[] = {"relative/path", nullptr};
        const char *multiple[] = {"/tmp/a", "/tmp/b", nullptr};
        callback(userdata, !mode || !strcmp(mode, "select") ? selection : !strcmp(mode, "cancel") ? cancel :
            !strcmp(mode, "relative") ? relative : !strcmp(mode, "multiple") ? multiple : nullptr, 0);
    }).detach();
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--test-validation")) {
        using launcher_input_recovery::valid_path;
        assert(valid_path("/tmp/Game Files/日本語"));
        assert(!valid_path(nullptr) && !valid_path("") && !valid_path("relative"));
        assert(!valid_path("/tmp/line\nfeed") && !valid_path("/tmp/tab\t"));
        assert(!valid_path("/tmp/\xc0\xaf") && !valid_path("/tmp/\xed\xa0\x80"));
        assert(!valid_path("/tmp/\xf4\x90\x80\x80") && !valid_path("/tmp/\xe0\x80\x80"));
        assert(!valid_path("/tmp/\xe2\x82") && !valid_path("/tmp/\xff"));
        std::string boundary(4095, 'a'); boundary[0] = '/'; assert(valid_path(boundary.c_str()));
        boundary.push_back('a'); assert(!valid_path(boundary.c_str()));
        return 0;
    }
    assert(argc > 1 && !strcmp(argv[1], "--locate-game-files"));
    return launcher_input_recovery::run(argc, argv);
}
