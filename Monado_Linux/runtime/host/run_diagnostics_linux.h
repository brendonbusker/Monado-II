// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-099: bounded local run diagnostics. No paths or private controls
// are accepted from the environment; a host-generated 32-hex ID joins records.
#pragma once
#ifdef __linux__
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "../settings.h"

static inline const char *run_diag_id(void) {
    const char *id = getenv("MONADO_RUN_ID");
    if (!id || strlen(id) != 32) return "direct";
    for (unsigned i = 0; i < 32; ++i)
        if (!((id[i] >= '0' && id[i] <= '9') || (id[i] >= 'a' && id[i] <= 'f'))) return "direct";
    return id;
}
static inline unsigned long long run_diag_utc(void) {
    struct timespec now = {0};
    return timespec_get(&now, TIME_UTC) == TIME_UTC && now.tv_sec > 0 ? (unsigned long long)now.tv_sec : 0;
}
static inline void run_diag_begin(bool precompile) {
    fprintf(stderr, "[run] id=%s utc_epoch=%llu event=runtime-start pid=%ld kind=%s\n",
        run_diag_id(), run_diag_utc(), (long)getpid(), precompile ? "shader-precompile" : "game");
}
static inline void run_diag_safe(char *out, size_t size, const char *text) {
    if (!size) return;
    size_t n = 0;
    if (text) for (; n + 1 < size && text[n]; ++n) {
        unsigned char c = (unsigned char)text[n];
        out[n] = c >= 32 && c < 127 && c != '"' && c != '\\' ? (char)c : '?';
    }
    out[n] = 0;
}
static inline const char *run_diag_method(void) {
    const char *external = getenv("NVPRESENT_ENABLE_SMOOTH_MOTION");
    if (external && !strcmp(external, "1")) return "nvidia-external-requested";
    if (g_settings.frame_gen || g_settings.cutscene_mode == 2) return "fsr-requested";
    if (g_settings.frame_gen_smooth_motion) return "nvidia-selected-inactive";
    return "off";
}
static inline float run_diag_number(float value) { return isfinite(value) ? value : -1.f; }

// Snapshot only known non-private options. This is the effective parsed runtime
// view, separate from the requested source lines recorded by the host wrapper.
typedef struct RunDiagSettings {
    int window_w, window_h, aspect, resolution, upscaler, quality, fps, antialias;
    int fullscreen, vsync, fsr, smooth, external, match, cutscene, overlay, overlay_mode;
    int dof, blur, navigation, quickstep, party, language, movie_audio;
    float volume;
    int cheat_on[9], cheat_percent[8];
    int period_override, interval_override, ini_override, hidden, precompile;
} RunDiagSettings;
static inline void run_diag_settings_snapshot(RunDiagSettings *row) {
    memset(row, 0, sizeof *row);
    row->window_w = g_window_w; row->window_h = g_window_h;
    row->aspect = g_settings.aspect; row->resolution = g_settings.res_mode;
    row->upscaler = g_settings.upscaler; row->quality = g_settings.upscale_quality;
    row->fps = g_settings.fps; row->antialias = g_settings.antialias;
    row->fullscreen = g_settings.fullscreen; row->vsync = g_settings.vsync;
    row->fsr = g_settings.frame_gen; row->smooth = g_settings.frame_gen_smooth_motion;
    const char *external = getenv("NVPRESENT_ENABLE_SMOOTH_MOTION");
    row->external = external && !strcmp(external, "1");
    row->match = g_settings.frame_gen_match_display; row->cutscene = g_settings.cutscene_mode;
    row->overlay = g_settings.show_fps_overlay; row->overlay_mode = g_settings.fps_overlay_mode; row->dof = !g_settings.dof_off;
    row->blur = g_settings.game_blur; row->navigation = g_settings.menu_navigation_speed;
    row->quickstep = g_settings.quickstep_slot;
    extern bool g_party_switch;
    row->party = g_party_switch; row->language = g_settings.language;
    row->movie_audio = g_settings.movie_audio; row->volume = run_diag_number(g_settings.volume);
    row->cheat_on[0] = g_settings.cheat_damage_dealt; row->cheat_percent[0] = g_settings.cheat_damage_dealt_percent;
    row->cheat_on[1] = g_settings.cheat_damage_received; row->cheat_percent[1] = g_settings.cheat_damage_received_percent;
    row->cheat_on[2] = g_settings.cheat_exp; row->cheat_percent[2] = g_settings.cheat_exp_percent;
    row->cheat_on[3] = g_settings.cheat_ap; row->cheat_percent[3] = g_settings.cheat_ap_percent;
    row->cheat_on[4] = g_settings.cheat_sp; row->cheat_percent[4] = g_settings.cheat_sp_percent;
    row->cheat_on[5] = g_settings.cheat_gold; row->cheat_percent[5] = g_settings.cheat_gold_percent;
    row->cheat_on[6] = g_settings.cheat_no_fall_damage;
    row->cheat_on[7] = g_settings.cheat_movement_speed; row->cheat_percent[6] = g_settings.cheat_movement_speed_percent;
    row->cheat_on[8] = g_settings.cheat_enemy_health; row->cheat_percent[7] = g_settings.cheat_enemy_health_percent;
    row->period_override = getenv("XCDE_FPS_PERIOD_SCALE") != NULL;
    row->interval_override = getenv("XCDE_FPS_INTERVAL") != NULL;
    row->ini_override = getenv("XCDE_INI") != NULL;
    row->hidden = getenv("LARECOMP_HIDDEN") != NULL;
    row->precompile = getenv("XCDE_PRECOMPILING") != NULL;
}
static inline void run_diag_settings(const char *event) {
    static RunDiagSettings last;
    static bool have;
    static unsigned rows;
    RunDiagSettings row;
    run_diag_settings_snapshot(&row);
    if (have && !memcmp(&last, &row, sizeof row)) return;
    last = row; have = true;
    if (rows >= 32) {
        if (rows == 32) { rows = 33; fprintf(stderr, "[run] id=%s event=settings-limit further changes suppressed\n", run_diag_id()); }
        return;
    }
    ++rows;
    char safe_event[48]; run_diag_safe(safe_event, sizeof safe_event, event);
    fprintf(stderr, "[run] id=%s utc_epoch=%llu event=%s method=%s window=%dx%d fullscreen=%d aspect=%d resolution=%d upscaler=%d quality=%d configured_fps=%d vsync=%d fsr=%d smooth_selected=%d smooth_driver_flag=%d match_display=%d cutscene_mode=%d fps_overlay=%d fps_overlay_mode=%d antialias=%d dof=%d game_blur=%d navigation=%d quickstep=%d party_switch=%d language=%d movie_audio=%d volume=%g cheat_enabled=%d,%d,%d,%d,%d,%d,%d,%d,%d cheat_percent=%d,%d,%d,%d,%d,%d,%d,%d period_override=%d interval_override=%d ini_override=%d hidden=%d precompile=%d\n",
        run_diag_id(), run_diag_utc(), safe_event, run_diag_method(), row.window_w, row.window_h,
        row.fullscreen, row.aspect, row.resolution, row.upscaler, row.quality, row.fps, row.vsync,
        row.fsr, row.smooth, row.external, row.match, row.cutscene, row.overlay, row.overlay_mode, row.antialias,
        row.dof, row.blur, row.navigation, row.quickstep, row.party, row.language, row.movie_audio,
        (double)row.volume, row.cheat_on[0], row.cheat_on[1], row.cheat_on[2], row.cheat_on[3],
        row.cheat_on[4], row.cheat_on[5], row.cheat_on[6], row.cheat_on[7], row.cheat_on[8], row.cheat_percent[0], row.cheat_percent[1],
        row.cheat_percent[2], row.cheat_percent[3], row.cheat_percent[4], row.cheat_percent[5], row.cheat_percent[6], row.cheat_percent[7],
        row.period_override, row.interval_override, row.ini_override, row.hidden, row.precompile);
}
// Render thread only. Event/mode/GPU strings are bounded and control-safe. A
// fresh row captures unknown/zero display/cap/readiness, not only qualified FG.
static inline void run_diag_renderer(const char *event, const char *gpu, const char *present_mode,
                              unsigned width, unsigned height, float display_hz,
                              float effective_fps, float qualified_cap, bool fg_ready) {
    typedef struct { char event[48], gpu[160], mode[32], method[40]; unsigned w, h; float hz, fps, cap; int ready; } Row;
    static Row last;
    static bool have;
    static unsigned rows;
    Row row; memset(&row, 0, sizeof row);
    run_diag_safe(row.event, sizeof row.event, event); run_diag_safe(row.gpu, sizeof row.gpu, gpu);
    run_diag_safe(row.mode, sizeof row.mode, present_mode);
    run_diag_safe(row.method, sizeof row.method, run_diag_method());
    row.w = width; row.h = height; row.hz = run_diag_number(display_hz);
    row.fps = run_diag_number(effective_fps); row.cap = run_diag_number(qualified_cap); row.ready = fg_ready;
    run_diag_settings("effective-settings");
    if (have && !memcmp(&last, &row, sizeof row)) return;
    last = row; have = true;
    if (rows >= 32) {
        if (rows == 32) { rows = 33; fprintf(stderr, "[run] id=%s event=renderer-limit further changes suppressed\n", run_diag_id()); }
        return;
    }
    ++rows;
    fprintf(stderr, "[run] id=%s utc_epoch=%llu event=%s gpu=\"%s\" app_present=%s output=%ux%u display_hz=%.6g policy_target_fps=%.6g qualified_fg_cap=%.6g fg_ready=%d method=%s\n",
        run_diag_id(), run_diag_utc(), row.event, row.gpu, row.mode, row.w, row.h,
        (double)row.hz, (double)row.fps, (double)row.cap, row.ready, row.method);
}
// Game limiter thread only; effective target transitions are independent of
// render-side settings snapshots and do not alter any timing value.
static inline void run_diag_pacing(float effective_fps, bool cutscene_30) {
    typedef struct { float effective; int configured, cut, fsr, smooth, match, period_override, interval_override; } Row;
    static Row last;
    static bool have;
    static unsigned rows;
    Row row; memset(&row, 0, sizeof row);
    row.effective = run_diag_number(effective_fps); row.configured = g_settings.fps;
    row.cut = cutscene_30; row.fsr = g_settings.frame_gen; row.smooth = g_settings.frame_gen_smooth_motion;
    row.match = g_settings.frame_gen_match_display;
    row.period_override = getenv("XCDE_FPS_PERIOD_SCALE") != NULL;
    row.interval_override = getenv("XCDE_FPS_INTERVAL") != NULL;
    if (have && !memcmp(&last, &row, sizeof row)) return;
    last = row; have = true;
    if (rows >= 32) {
        if (rows == 32) { rows = 33; fprintf(stderr, "[run] id=%s event=pacing-limit further changes suppressed\n", run_diag_id()); }
        return;
    }
    ++rows;
    fprintf(stderr, "[run] id=%s utc_epoch=%llu event=effective-target configured_fps=%d policy_target_fps=%.6g cutscene_30=%d fsr=%d smooth_selected=%d match_display=%d period_override=%d interval_override=%d\n",
        run_diag_id(), run_diag_utc(), row.configured, (double)row.effective, row.cut,
        row.fsr, row.smooth, row.match, row.period_override, row.interval_override);
}
static inline void run_diag_limiter(int interval, float base_period, float applied_period) {
    typedef struct { int interval; float base, applied; } Row;
    static Row last;
    static bool have;
    static unsigned rows;
    Row row; memset(&row, 0, sizeof row);
    row.interval = interval; row.base = run_diag_number(base_period); row.applied = run_diag_number(applied_period);
    if (have && !memcmp(&last, &row, sizeof row)) return;
    last = row; have = true;
    if (rows >= 32) {
        if (rows == 32) { rows = 33; fprintf(stderr, "[run] id=%s event=limiter-limit further changes suppressed\n", run_diag_id()); }
        return;
    }
    ++rows;
    double nominal = row.interval > 0 && row.base > 0.f && row.applied > 0.f
        ? 60.0 * row.base / row.applied / row.interval : 0.0;
    fprintf(stderr, "[run] id=%s utc_epoch=%llu event=applied-limiter interval=%d base_period=%.9g applied_period=%.9g nominal_fps=%.6g measured_fps=no\n",
        run_diag_id(), run_diag_utc(), row.interval, (double)row.base, (double)row.applied, nominal);
}
#endif
