// Output resolution, shared by the Metal and Vulkan backends (each calls output_scale() once per presented frame).
// Render targets the game sizes for the Switch's 1920x1080 screen are allocated at (sx, sy) times their size; the
// image is then drawn into (vx, vy, vw, vh) of the window. Video tab "Internal resolution" (g_settings.res_mode):
//   Match display  render at the window's own pixel size (default)
//   1x .. 4x       N times the Switch's docked image: 1080 lines x N (wide windows keep their shape: 32:9 at 2x =
//                  7680 x 2160); capped to the GPU's 16384-pixel texture limit
//   .75x / .50x / .25x  of Match display (scaled up to the window - with MetalFX on macOS when chosen)
//   Dynamic        Match display, lowered in steps while the GPU can't hold 60 fps and raised again when it can
//                  (each change reallocates the render targets: a short hitch, so it changes rarely, with hysteresis)
// Test overrides: LARECOMP_SCALE=<f> (render height = 1080 x f), LARECOMP_WIDE_TEST=<f> (forced shape).
#include <math.h>
#include <stdlib.h>

#include "../hle.h"
#include "../settings.h"
#include "output_scale.h"
#include "../host/xcde_aspect.h" // [XCDE] LINUX-089: unsupported window shapes retain 16:9.

#define MAX_TEX 16384.0

// Dynamic resolution: a factor on the Match display scale, 0.5 .. 1 in 0.05 steps.
static double g_dyn = 1.0;
static double g_dyn_gpu_sum, g_dyn_dt_sum, g_last_t;
static int g_dyn_n, g_dyn_gpu_n, g_dyn_good;
static double g_dyn_cool_until, g_dyn_probe_wait = 5.0, g_dyn_probe_at;
static double g_dyn_last_raise = -100;

static void dyn_update(double now, double gpu_ms) {
    double dt = g_last_t > 0 ? (now - g_last_t) * 1000.0 : 16.7;
    g_last_t = now;
    if (dt > 250) return;  // (loading, menus, a stall: not the GPU's steady state)
    g_dyn_dt_sum += dt;
    g_dyn_n++;
    if (gpu_ms >= 0) { g_dyn_gpu_sum += gpu_ms; g_dyn_gpu_n++; }
    if (g_dyn_n < 30) return;  // decide every ~half second
    double avg_dt = g_dyn_dt_sum / g_dyn_n, avg_gpu = g_dyn_gpu_n ? g_dyn_gpu_sum / g_dyn_gpu_n : -1;
    g_dyn_dt_sum = g_dyn_gpu_sum = 0;
    g_dyn_n = g_dyn_gpu_n = 0;
    if (now < g_dyn_cool_until) return;
    double prev = g_dyn;
    bool slow = avg_dt > 17.4 || (avg_gpu >= 0 && avg_gpu > 14.5);
    if (slow) {
        g_dyn = fmax(0.5, g_dyn - (avg_dt > 22 ? 0.1 : 0.05));
        g_dyn_good = 0;
        if (now - g_dyn_last_raise < 3.0) g_dyn_probe_wait = fmin(g_dyn_probe_wait * 2, 60.0);  // raised too eagerly
    } else if (g_dyn < 1.0) {
        g_dyn_good++;
        // with GPU timing: raise when there is clear headroom; without (Vulkan): probe upwards now and then
        bool room = avg_gpu >= 0 ? avg_gpu < 10.5 && g_dyn_good >= 4 : now >= g_dyn_probe_at && g_dyn_good >= 2 * (int)g_dyn_probe_wait;
        if (room) { g_dyn = fmin(1.0, g_dyn + 0.05); g_dyn_good = 0; g_dyn_last_raise = now; g_dyn_probe_at = now + g_dyn_probe_wait; }
    }
    g_dyn = round(g_dyn * 20) / 20;
    if (g_dyn != prev) {
        g_dyn_cool_until = now + 1.5;
        LOG("[dynres] %.2f -> %.2f (frame %.1f ms, gpu %.1f ms)\n", prev, g_dyn, avg_dt, avg_gpu);
    }
}

double output_scale_dynamic_factor(void) { return g_dyn; }

// [XCDE] T146: the size the game renders its frame for. LASRecomp's game drew for the Switch's 1920x1080; XCDE's window
// textures are 1280x720, so with 1080 as the base a 720p window rendered everything (scene and HUD) at 853x480 and
// scaled it up. The NVN window's texture size sets it (nvnWindowInitialize); 1920x1080 until then.
static double g_base_w = 1920.0, g_base_h = 1080.0;
void output_scale_set_base(int w, int h) {
    if (w <= 0 || h <= 0 || (g_base_w == w && g_base_h == h)) return;
    g_base_w = w, g_base_h = h;
    LOG("[scale] the game renders for %dx%d\n", w, h);
}

void output_scale(double dw, double dh, bool reshape_allowed, double now, double gpu_ms, OutScale *o) {
    double fit = fmin(dw / g_base_w, dh / g_base_h);
    static double forced = -1, wide_test = -1;
    if (forced < 0) forced = getenv("LARECOMP_SCALE") ? atof(getenv("LARECOMP_SCALE")) : 0;
    if (wide_test < 0) wide_test = getenv("LARECOMP_WIDE_TEST") ? atof(getenv("LARECOMP_WIDE_TEST")) : 0;
    double shape = wide_test > 0 ? wide_test : xcde_aspect_target_factor((dw / dh) / (16.0 / 9.0));
    bool reshape = reshape_allowed && xcde_aspect_supported_factor((float)shape) && fabs(shape - 1.0) > 0.005;
    if (!reshape) shape = 1.0;
    // [XCDE] LINUX-090: a selected ratio is a content canvas, independent of
    // the screen/window. Render and present the same fitted canvas with bars.
    // Retain the exact original and Match display arithmetic for existing users.
    bool fixed_canvas = reshape && g_settings.aspect != ASPECT_UNLOCKED;
    double canvas_fit = fixed_canvas ? fmin(dw / (g_base_w * shape), dh / g_base_h) : fit;
    // render height in units of the Switch's 1080 lines
    double h;
    int mode = g_settings.res_mode;
    // [XCDE] LINUX-017: DLAA is native resolution, never an undersized SR input.
    if (g_settings.upscaler == UPSCALE_DLSS && g_settings.upscale_quality == UQ_NATIVE) mode = RES_MATCH;
    if (forced > 0) h = forced;
    else if (mode >= 1 && mode <= 8) h = mode;
    else {
        h = fixed_canvas ? canvas_fit : reshape ? dh / g_base_h : fit;
        if (mode == RES_DYNAMIC) { dyn_update(now, gpu_ms); h *= g_dyn; }
        else if (mode == RES_Q75) h *= 0.75;
        else if (mode == RES_Q25) h *= 0.25;
        else if (mode == RES_Q50) h *= 0.5;
        // [XCDE] temporal upscalers (FSR 3 / DLSS): Match display at the quality mode's render size
        else if (mode == RES_MATCH && (g_settings.upscaler == UPSCALE_FSR3 || g_settings.upscaler == UPSCALE_DLSS)) {
            static const double ratio[] = {1.0, 1.5, 1.7, 2.0, 3.0};
            int q = g_settings.upscale_quality;
            h /= ratio[q >= 0 && q <= 4 ? q : 1];
        }
    }
    h = fmax(h, 0.1);  // (.25x of a small window)
    double sx = h * shape, sy = h;
    double cap = fmin(MAX_TEX / (g_base_w * sx), MAX_TEX / (g_base_h * sy));
    if (cap < 1.0) { sx *= cap; sy *= cap; }
    o->sx = sx; o->sy = sy; o->shape = shape;
    // where the image goes in the window: fills it when reshaped, else a fitted 16:9 box
    if (fixed_canvas) { o->vw = g_base_w * shape * canvas_fit; o->vh = g_base_h * canvas_fit; }
    else if (reshape) { o->vw = dw; o->vh = dh; }
    else { o->vw = g_base_w * fit; o->vh = g_base_h * fit; }
    if (wide_test > 0) {
        double f2 = fmin(dw / (g_base_w * wide_test), dh / g_base_h);
        o->vw = g_base_w * wide_test * f2; o->vh = g_base_h * f2;
    }
    // [XCDE] LINUX-017: match the integer viewport BEFORE narrowing scale to
    // float. Half-pixel fitted extents otherwise round differently in textures
    // and present (e.g. 1304x744 -> 1304x734), violating DLAA's 1:1 contract.
    if (g_settings.upscaler == UPSCALE_DLSS && g_settings.upscale_quality == UQ_NATIVE && forced <= 0) {
        o->sx = fmin(round((float)o->vw), MAX_TEX) / g_base_w;
        o->sy = fmin(round((float)o->vh), MAX_TEX) / g_base_h;
    }
    o->vx = (dw - o->vw) / 2; o->vy = (dh - o->vh) / 2;
}
