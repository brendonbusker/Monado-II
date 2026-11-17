// [XCDE] User settings: xcde.ini in the working directory, written by the launcher (tools/launcher) and read when the
// window opens. "key = value" lines; unknown keys are ignored, missing ones keep their defaults. Key bindings use the
// LAS format (bind_key_<action> / bind_pad_<action>, runtime/hle/bindings.c).
#include <stdio.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include "../input_bind.h"
#include "../settings.h"
#include "../cheats_options.h"
#include "../quality_policy.h"
#include "../gpu_selection.h"
#ifdef __linux__
#include "run_diagnostics_linux.h"
#endif

const char *const g_language_codes[N_LANGUAGES] = {"", "ja", "en-US", "fr", "de", "it", "es", "zh-CN", "ko", "nl", "pt", "ru"};
const char *const g_language_names[N_LANGUAGES] = {"Auto", "Japanese", "English", "French", "German", "Italian", "Spanish",
                                                   "Chinese", "Korean", "Dutch", "Portuguese", "Russian"};
Settings g_settings = {.aspect = ASPECT_ORIGINAL, .fps = 30, .volume = 1.0f, .movie_audio = true, .res_mode = RES_MATCH, .upscaler = UPSCALE_BILINEAR, .upscale_quality = UQ_QUALITY, .game_blur = true, .vsync = true, .ui_lang = 1,
    // [XCDE] LINUX-072: slider positions are remembered independently of enable flags.
    .upscale_sharpness = -1.f, .quality_preset = QUALITY_CUSTOM, .grass_lod = GRASS_ORIGINAL,
    .cheat_damage_dealt_percent = 100, .cheat_damage_received_percent = 100,
    .cheat_exp_percent = 100, .cheat_ap_percent = 100, .cheat_sp_percent = 100, .cheat_gold_percent = 100, .cheat_movement_speed_percent = 100, .cheat_enemy_health_percent = 100};
int g_window_w = 1280, g_window_h = 720;  // windowed size (settings.h)

// [XCDE] Mods (runtime/services/romfs_virtual.c): xcde.ini `mod_<folder> = 0/1`; a folder not listed is on.
bool g_party_switch;  // [XCDE] party mod: xcde.ini party_switch = 0/1 (off by default; runtime/hle/party.c)
static struct { char name[96]; bool on; } g_mods[128];
static int g_nmods;
static void mod_set(const char *name, bool on) {
    for (int i = 0; i < g_nmods; i++) if (!strcmp(g_mods[i].name, name)) { g_mods[i].on = on; return; }
    if (g_nmods == 128) return;
    snprintf(g_mods[g_nmods].name, sizeof g_mods[g_nmods].name, "%s", name);
    g_mods[g_nmods++].on = on;
}
bool settings_mod_enabled(const char *name) {
    for (int i = 0; i < g_nmods; i++) if (!strcmp(g_mods[i].name, name)) return g_mods[i].on;
    return strncmp(name, "icons_", 6) != 0;  // [XCDE] button prompt packs (mods/icons_xbox...): only the one the launcher turns on
}
static char g_button_icons[16] = "auto";  // [XCDE] the launcher's choice (button_icons), kept when the game saves

static const char *ini_path(void) {
    const char *e = getenv("XCDE_INI");
    return e ? e : "xcde.ini";
}

static char *trim(char *s) {
    while (*s == ' ' || *s == '\t') s++;
    char *e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = 0;
    return s;
}

static int lang_index(const char *v) {
    for (int i = 0; i < N_LANGUAGES; i++)
        if (!strcmp(v, i ? g_language_codes[i] : "auto")) return i;
    return LANG_AUTO;
}

// [XCDE] LINUX-072: reject malformed, overflowing and out-of-range cheat values.
// A stale enabled preference must never survive a reload of a missing/invalid key.
static bool cheat_enabled(const char *value) {
    return !strcmp(value, "1") || !strcmp(value, "true");
}
// [XCDE] LINUX-129: Enemy health has an independent0.1x minimum; other ranges stay unchanged.
static int cheat_percent_bound(int value, int minimum) {
    return value >= minimum && value <= 2000 ? value : 100;
}
static int cheat_percent(const char *value, int minimum) {
    if (!*value) return 100;
    for (const char *p = value; *p; ++p) if (*p < '0' || *p > '9') return 100;
    errno = 0;
    char *end;
    long n = strtol(value, &end, 10);
    return errno || end == value || *end || n < minimum || n > 2000 ? 100 : (int)n;
}
#define XCDE_CHEAT_MULTIPLIERS(X) \
    X(damage_dealt, 0) X(damage_received, 0) X(exp, 0) X(ap, 0) X(sp, 0) X(gold, 0) X(movement_speed, 0) X(enemy_health, 10)

// [XCDE] LINUX-089: exact opt-ins, shared ordering with ASPECT_*; unknown values
// preserve original framing, including after reloading a previously fixed ratio.
static const char *const aspect_values[N_ASPECTS] = {"native", "original", "16:10", "21:9", "32:9"};
static int aspect_index(const char *value) {
    for (int i = 0; i < N_ASPECTS; ++i) if (!strcmp(value, aspect_values[i])) return i;
    return ASPECT_ORIGINAL;
}

static void settings_load_values(void) {
    // [XCDE] LINUX-089: native aspect is opt-in, including reload/missing files.
    g_settings.aspect = ASPECT_ORIGINAL;
    xcde_quality_defaults(&g_settings);
    g_settings.gpu_uuid[0]=0;
    // [XCDE] LINUX-014: absent/invalid new preference defaults to Normal on each
    // load, including a reload after a previously selected Fast preference.
    g_settings.menu_navigation_speed = MENU_NAV_NORMAL;
    g_settings.quickstep_slot = false; // [XCDE] LINUX-039: absent/invalid always OFF
    g_settings.show_fps_overlay = false;
    g_settings.fps_overlay_mode = FPS_OVERLAY_OFF; // [XCDE] LINUX-124: absent files remain opt-out.
    // [XCDE] LINUX-097: old, missing and reloaded files never opt into a new FG method.
    g_settings.frame_gen = false;
    g_settings.cutscene_mode = 0;
    g_settings.frame_gen_smooth_motion = false;
    g_settings.frame_gen_match_display = false;
    // [XCDE] LINUX-072: all cheats are opt-in, including absent-file/hidden runs.
#define RESET_CHEAT(name, minimum) g_settings.cheat_##name = false; g_settings.cheat_##name##_percent = 100;
    XCDE_CHEAT_MULTIPLIERS(RESET_CHEAT)
#undef RESET_CHEAT
    g_settings.cheat_no_fall_damage = false;
    // test runs (hidden window, deterministic, scripted input) ignore the player's settings unless XCDE_INI names a file
    if (!getenv("XCDE_INI") && (getenv("LARECOMP_HIDDEN") || getenv("XCDE_DETERMINISTIC") || getenv("XCDE_INPUT_REPLAY"))) return;
    FILE *f = fopen(ini_path(), "r");
    if (!f) return;
    bool overlay_mode_present = false;
    char line[512];
    while (fgets(line, sizeof line, f)) {
        char *s = line;
        if (!memcmp(s, "\xEF\xBB\xBF", 3)) s += 3;  // [XCDE] a UTF-8 BOM (Notepad) before the first key
        s = trim(s);
        if (!*s || *s == '#' || *s == ';' || *s == '[') continue;
        char *eq = strchr(s, '=');
        if (!eq) continue;
        *eq = 0;
        char *k = trim(s), *v = trim(eq + 1);
        if (!strcmp(k, "aspect_ratio")) g_settings.aspect = aspect_index(v);
        else if (!strcmp(k, "fullscreen")) g_settings.fullscreen = atoi(v) != 0;
        else if (!strcmp(k, "window")) sscanf(v, "%dx%d", &g_window_w, &g_window_h);
        else if (!strcmp(k, "resolution")) {  // match | 1x..4x | 75% | 50% | 25% | dynamic
            if (!strcmp(v, "match")) g_settings.res_mode = RES_MATCH;
            else if (!strcmp(v, "dynamic")) g_settings.res_mode = RES_DYNAMIC;
            else if (!strcmp(v, "75%")) g_settings.res_mode = RES_Q75;
            else if (!strcmp(v, "50%")) g_settings.res_mode = RES_Q50;
            else if (!strcmp(v, "25%")) g_settings.res_mode = RES_Q25;
            else if (atoi(v) >= 1 && atoi(v) <= 8) g_settings.res_mode = atoi(v);
        } else if (!strcmp(k, "upscaler")) {
            g_settings.upscaler = !strcmp(v, "fsr") ? UPSCALE_FSR1 : !strcmp(v, "fsr3") ? UPSCALE_FSR3
                                : !strcmp(v, "dlss") ? UPSCALE_DLSS : !strcmp(v,"fsr4_lite") ? UPSCALE_FSR4_LITE : UPSCALE_BILINEAR;
        } else if (!strcmp(k, "upscale_quality")) {
            static const char *q[] = {"native", "quality", "balanced", "performance", "ultra"};
            for (int i = 0; i < 5; i++) if (!strcmp(v, q[i])) g_settings.upscale_quality = i;
        } else if (!strcmp(k, "frame_gen")) g_settings.frame_gen = atoi(v) != 0;
        else if (!strcmp(k, "frame_gen_smooth_motion")) g_settings.frame_gen_smooth_motion = cheat_enabled(v);
        else if (!strcmp(k, "frame_gen_match_display")) g_settings.frame_gen_match_display = cheat_enabled(v);
        else if (!strcmp(k, "cutscenes")) g_settings.cutscene_mode = !strcmp(v, "30") ? 1 : !strcmp(v, "30fg") ? 2 : 0;
        else if (!strcmp(k, "antialias")) g_settings.antialias = !strcmp(v, "smaa") ? AA_SMAA : AA_OFF;
        else if (!strcmp(k, "depth_of_field")) g_settings.dof_off = atoi(v) == 0;
        else if (!strcmp(k, "game_blur")) g_settings.game_blur = atoi(v) != 0;
        else if (!strcmp(k, "vsync")) g_settings.vsync = atoi(v) != 0;
        else if (!strcmp(k, "launcher_lang")) g_settings.ui_lang = !strcmp(v, "es") ? 0 : 1;
        else if (!strcmp(k, "stick_deadzone")) { int d = atoi(v); g_settings.stick_deadzone = d < 0 ? 0 : d > 30 ? 30 : d; }
        else if (!strcmp(k, "party_switch")) g_party_switch = atoi(v) != 0;  // [XCDE] party mod (runtime/hle/party.c)
        else if (!strcmp(k, "volume")) g_settings.volume = (float)atof(v) / 100.0f;
        else if (!strcmp(k, "movie_audio")) g_settings.movie_audio = atoi(v) != 0;
        else if (!strcmp(k, "show_fps")) g_settings.show_fps = atoi(v) != 0;
        else if (!strcmp(k, "show_fps_overlay")) g_settings.show_fps_overlay = !strcmp(v, "1") || !strcmp(v, "true");
        else if (!strcmp(k, "fps_overlay_mode")) {
            overlay_mode_present = true;
            g_settings.fps_overlay_mode = xcde_fps_overlay_mode_parse(v);
        }
        else if (!strcmp(k, "fps")) g_settings.fps = !strcmp(v, "unlimited") ? 0 : atoi(v);
        else if (!strcmp(k, "menu_navigation_speed"))
            g_settings.menu_navigation_speed = !strcmp(v, "fast") ? MENU_NAV_FAST : MENU_NAV_NORMAL;
        else if (!strcmp(k, "quickstep_slot")) g_settings.quickstep_slot = !strcmp(v, "1");
        // [XCDE] LINUX-072: config agrees with the launcher's exact 1/true opt-in.
#define LOAD_CHEAT(name, minimum) \
        else if (!strcmp(k, "cheat_" #name)) g_settings.cheat_##name = cheat_enabled(v); \
        else if (!strcmp(k, "cheat_" #name "_percent")) g_settings.cheat_##name##_percent = cheat_percent(v, minimum);
        XCDE_CHEAT_MULTIPLIERS(LOAD_CHEAT)
#undef LOAD_CHEAT
        else if (!strcmp(k, "cheat_no_fall_damage")) g_settings.cheat_no_fall_damage = cheat_enabled(v);
        else if (!strcmp(k, "language")) g_settings.language = lang_index(v);
        else if (!strncmp(k, "mod_", 4)) mod_set(k + 4, atoi(v) != 0);
        else if (!strcmp(k, "button_icons")) snprintf(g_button_icons, sizeof g_button_icons, "%s", v);
        else if (!strcmp(k,"gpu_uuid")) {
            if(!monado_gpu_uuid_normalize(v,g_settings.gpu_uuid))fprintf(stderr,"[settings] invalid GPU UUID; using automatic selection\n");
        }
        else if (!xcde_quality_load(&g_settings,k,v)) bind_settings_load(k, v);
    }
    fclose(f);
    // Explicit mode wins in either key order; old enabled counters migrate to Compact.
    if (!overlay_mode_present) g_settings.fps_overlay_mode = g_settings.show_fps_overlay ? FPS_OVERLAY_COMPACT : FPS_OVERLAY_OFF;
    g_settings.show_fps_overlay = g_settings.fps_overlay_mode != FPS_OVERLAY_OFF;
    xcde_quality_bounds(&g_settings);
    // [XCDE] LINUX-097: malformed mixed-backend files retain the existing FSR
    // request and disable external FG. Cutscene-only FG also owns that choice.
    if (g_settings.frame_gen || g_settings.cutscene_mode == 2) g_settings.frame_gen_smooth_motion = false;
#ifdef __linux__
    // [XCDE] LINUX-006: imported Windows options must not reduce render resolution
    // for an unavailable temporal provider. Preserve enum/parser compatibility,
    // report the effective spatial mode, and leave the input config unchanged.
    if (false
#ifndef XCDE_LINUX_FSR3
        || g_settings.upscaler == UPSCALE_FSR3
#endif
#ifndef XCDE_LINUX_FSR4
        || g_settings.upscaler == UPSCALE_FSR4_LITE
#endif
#ifndef XCDE_LINUX_DLSS
        || g_settings.upscaler == UPSCALE_DLSS
#endif
    ) {
        fprintf(stderr, "[settings] %s unavailable on Linux; using FSR 1 spatial scaling\n",
                g_settings.upscaler == UPSCALE_DLSS ? "DLSS" : g_settings.upscaler==UPSCALE_FSR4_LITE ? "FSR4 Lite" : "FSR 3");
        g_settings.upscaler = UPSCALE_FSR1;
    }
    // [XCDE] LINUX-020: only a source-built provider plus the implemented DLSS temporal-input path can generate.
    bool framegen_supported = false;
#ifdef XCDE_LINUX_FRAMEGEN
    framegen_supported = g_settings.upscaler == UPSCALE_DLSS;
#ifdef XCDE_LINUX_FSR3
    framegen_supported |= g_settings.upscaler == UPSCALE_FSR3;
#endif
#ifdef XCDE_LINUX_FSR4
    framegen_supported |= g_settings.upscaler == UPSCALE_FSR4_LITE;
#endif
#endif
    if (!framegen_supported && (g_settings.frame_gen || g_settings.cutscene_mode == 2)) {
        fprintf(stderr, "[settings] frame generation unavailable on Linux; generated frames disabled\n");
        g_settings.frame_gen = false;
        if (g_settings.cutscene_mode == 2) g_settings.cutscene_mode = 1;
    }
#endif
    if (g_window_w < 320) g_window_w = 320;
    if (g_window_h < 180) g_window_h = 180;
    if (g_settings.volume < 0) g_settings.volume = 0;
    if (g_settings.volume > 2) g_settings.volume = 2;
}

void settings_load(void) {
    settings_load_values();
    xcde_cheats_publish(&g_settings); // Publish before any guest event can consume these preferences.
#ifdef __linux__
    // [XCDE] LINUX-099: report parsed/fallback defaults even when input is
    // missing or intentionally ignored. This never rewrites the settings file.
    run_diag_settings("settings-loaded");
#endif
}

void settings_save(void) {
    FILE *f = fopen(ini_path(), "w");
    if (!f) return;
    static const char *res[] = {"match", "1", "2", "3", "4", "5", "6", "7", "8", "dynamic", "75%", "25%", "50%"};
    fprintf(f, "# Monado settings (the launcher writes this file)\n");
    fprintf(f, "fullscreen = %d\nwindow = %dx%d\n", g_settings.fullscreen, g_window_w, g_window_h);
    fprintf(f, "aspect_ratio = %s\n", aspect_values[g_settings.aspect >= 0 && g_settings.aspect < N_ASPECTS ? g_settings.aspect : ASPECT_ORIGINAL]); // [XCDE] LINUX-089
    fprintf(f, "resolution = %s\n", g_settings.res_mode >= 0 && g_settings.res_mode <= 12 ? res[g_settings.res_mode] : "match");
    static const char *up[] = {"bilinear", "bilinear", "fsr", "fsr3", "dlss", "fsr4_lite"};
    static const char *uq[] = {"native", "quality", "balanced", "performance", "ultra"};
    fprintf(f, "upscaler = %s\nantialias = %s\n", up[g_settings.upscaler >= 0 && g_settings.upscaler <= 5 ? g_settings.upscaler : 0],
            g_settings.antialias == AA_SMAA ? "smaa" : "off");
    fprintf(f, "upscale_quality = %s\nframe_gen = %d\n",
            uq[g_settings.upscale_quality >= 0 && g_settings.upscale_quality <= 4 ? g_settings.upscale_quality : 1], g_settings.frame_gen);
    fprintf(f, "frame_gen_smooth_motion = %d\nframe_gen_match_display = %d\n",
            g_settings.frame_gen_smooth_motion && !g_settings.frame_gen && g_settings.cutscene_mode != 2,
            g_settings.frame_gen_match_display);
    fprintf(f, "depth_of_field = %d\n", !g_settings.dof_off);
    fprintf(f, "game_blur = %d\n", g_settings.game_blur);
    xcde_quality_save(f,&g_settings);
    fprintf(f,"gpu_uuid = %s\n",*g_settings.gpu_uuid?g_settings.gpu_uuid:"auto");
    fprintf(f, "vsync = %d\n", g_settings.vsync);
    if (g_settings.stick_deadzone) fprintf(f, "stick_deadzone = %d\n", g_settings.stick_deadzone);
    fprintf(f, "launcher_lang = %s\n", g_settings.ui_lang ? "en" : "es");  // (the launcher's key: kept when the game saves)
    fprintf(f, "cutscenes = %s\n", g_settings.cutscene_mode == 1 ? "30" : g_settings.cutscene_mode == 2 ? "30fg" : "same");
    fprintf(f, "party_switch = %d\n", g_party_switch);
    fprintf(f, "quickstep_slot = %d\n", g_settings.quickstep_slot); // [XCDE] LINUX-039
    // [XCDE] LINUX-072: preserve all cheat preferences when the game saves F1 settings.
#define SAVE_CHEAT(name, minimum) fprintf(f, "cheat_" #name " = %d\ncheat_" #name "_percent = %d\n", \
        g_settings.cheat_##name, cheat_percent_bound(g_settings.cheat_##name##_percent, minimum));
    XCDE_CHEAT_MULTIPLIERS(SAVE_CHEAT)
#undef SAVE_CHEAT
    fprintf(f, "cheat_no_fall_damage = %d\n", g_settings.cheat_no_fall_damage);
    fprintf(f, "volume = %d\nmovie_audio = %d\nshow_fps = %d\n", (int)(g_settings.volume * 100 + 0.5f), g_settings.movie_audio,
            g_settings.show_fps);
    int overlay_mode = g_settings.fps_overlay_mode >= FPS_OVERLAY_OFF && g_settings.fps_overlay_mode < FPS_OVERLAY_COUNT ? g_settings.fps_overlay_mode : FPS_OVERLAY_OFF;
    fprintf(f, "show_fps_overlay = %d\nfps_overlay_mode = %s\n", overlay_mode != FPS_OVERLAY_OFF,
            xcde_fps_overlay_mode_name(overlay_mode)); // legacy readers retain visibility.
    if (g_settings.fps) fprintf(f, "fps = %d\n", g_settings.fps); else fprintf(f, "fps = unlimited\n");
    // [XCDE] LINUX-014: retain the launcher-only preference when F1 saves settings.
    fprintf(f, "menu_navigation_speed = %s\n", g_settings.menu_navigation_speed == MENU_NAV_FAST ? "fast" : "normal");
    fprintf(f, "language = %s\n", g_settings.language > 0 && g_settings.language < N_LANGUAGES ? g_language_codes[g_settings.language] : "auto");
    for (int i = 0; i < g_nmods; i++) fprintf(f, "mod_%s = %d\n", g_mods[i].name, g_mods[i].on);
    fprintf(f, "button_icons = %s\n", g_button_icons);
    bind_settings_save(f);
    fclose(f);
}

// The language served to the game: the setting; "auto" stays English (what every test route was recorded with).
const char *settings_language(void) {
    if (g_settings.language > 0 && g_settings.language < N_LANGUAGES) return g_language_codes[g_settings.language];
    return "en-US";
}

const char *settings_language_name(void) {
    const char *c = settings_language();
    for (int i = 1; i < N_LANGUAGES; i++)
        if (!strcmp(c, g_language_codes[i])) return g_language_names[i];
    return "English";
}
