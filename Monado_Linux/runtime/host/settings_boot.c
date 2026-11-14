// Headless boot executable: fixed default settings (the window build reads xcde.ini: settings_ini.c).
#include "../settings.h"

int g_window_w = 1280, g_window_h = 720;
const char *const g_language_codes[N_LANGUAGES] = {"", "ja", "en-US", "fr", "de", "it", "es", "zh-CN", "ko", "nl", "pt", "ru"};
const char *const g_language_names[N_LANGUAGES] = {"Auto", "Japanese", "English", "French", "German", "Italian", "Spanish",
                                                   "Chinese", "Korean", "Dutch", "Portuguese", "Russian"};
Settings g_settings = {.aspect = ASPECT_ORIGINAL, .volume = 1.0f, .movie_audio = true};

void settings_load(void) {}
void settings_save(void) {}
const char *settings_language(void) { return "en-US"; }
const char *settings_language_name(void) { return "English"; }

