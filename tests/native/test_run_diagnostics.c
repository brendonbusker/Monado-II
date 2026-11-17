// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-099: actual parser and passive local diagnostics, no game/SDL.
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../Monado_Linux/runtime/input_bind.h"
#include "../../Monado_Linux/runtime/host/run_diagnostics_linux.h"
bool bind_settings_load(const char *key, const char *value) { (void)key; (void)value; return false; }
void bind_settings_save(FILE *file) { (void)file; }
static void put(const char *path, const char *text) { FILE *file = fopen(path, "w"); assert(file); assert(fputs(text, file) >= 0); assert(!fclose(file)); }
int main(int argc, char **argv) {
    assert(argc == 3);
    const char *path = argv[1], *scenario = argv[2];
    assert(!setenv("MONADO_RUN_ID", "0123456789abcdef0123456789abcdef", 1));
    assert(!setenv("XCDE_INI", path, 1));
    if (!strcmp(scenario, "parsed")) {
        put(path, "fullscreen = 1\nwindow = 2560x1440\nupscaler = dlss\nupscale_quality = native\nfps = 120\nframe_gen = 1\nframe_gen_match_display = 1\nvsync = 1\ncutscenes = same\nshow_fps_overlay = 1\nfps_overlay_mode = detailed\nquickstep_slot = 1\ncheat_exp = 1\ncheat_exp_percent = 225\ncheat_enemy_health = 1\ncheat_enemy_health_percent = 175\n");
        run_diag_begin(false); settings_load();
        assert(g_settings.upscaler == UPSCALE_DLSS && g_settings.fps == 120);
        Settings before = g_settings;
        run_diag_renderer("frame-policy", "NVIDIA authored GPU", "fifo", 2560, 1440, 180.f, 120.f, 0.f, false);
        run_diag_pacing(120.f, false);
        run_diag_limiter(1, .997f, .4985f);
        run_diag_renderer("frame-policy", "NVIDIA authored GPU", "fifo", 2560, 1440, 180.f, 90.f, 90.f, true);
        run_diag_pacing(90.f, false);
        run_diag_limiter(1, .997f, .997f * (60.f / 90.f));
        assert(!memcmp(&before, &g_settings, sizeof before));
    } else if (!strcmp(scenario, "missing")) {
        remove(path); settings_load(); assert(!g_settings.frame_gen && g_settings.fps == 30);
    } else if (!strcmp(scenario, "ignored")) {
        put(path, "frame_gen = 1\nfps = 120\n"); unsetenv("XCDE_INI"); setenv("LARECOMP_HIDDEN", "1", 1);
        settings_load(); assert(!g_settings.frame_gen && g_settings.fps == 30);
    } else if (!strcmp(scenario, "external")) {
        put(path, "frame_gen = 0\nframe_gen_smooth_motion = 1\nfps = unlimited\nvsync = 1\n");
        setenv("NVPRESENT_ENABLE_SMOOTH_MOTION", "1", 1); settings_load();
        run_diag_renderer("frame-policy", "NVIDIA authored GPU", "mailbox", 2560, 1440, 180.f, 0.f, 0.f, false);
        run_diag_pacing(0.f, false);
    } else if (!strcmp(scenario, "bounded")) {
        settings_load();
        for (unsigned i = 0; i < 1000; ++i) {
            g_settings.fps = (int)i;
            run_diag_settings("fixture-settings");
            run_diag_pacing((float)i, false);
            run_diag_limiter(1, .997f, .997f / (float)(i + 1));
            run_diag_renderer("frame-policy", "authored", "fifo", 2560, 1440, 180.f, (float)i, 90.f, true);
        }
    } else if (!strcmp(scenario, "sanitize")) {
        setenv("MONADO_RUN_ID", "/untrusted\nSECRET_ID", 1);
        run_diag_begin(true);
        run_diag_renderer("frame\npolicy", "GPU\nforged=1\\\"", "mailbox\nforged", 1, 2, 0.f, 0.f, 0.f, false);
    } else assert(!"unknown scenario");
    puts("actual parsed settings and passive run diagnostics PASS");
    return 0;
}
