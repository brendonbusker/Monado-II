// Output resolution (runtime/nvn/output_scale.c), shared by the Metal and Vulkan backends.
#pragma once
#include <stdbool.h>

typedef struct {
    double sx, sy;             // render-target scale (relative to the game's frame size, output_scale_set_base)
    double shape;              // selected content aspect / 16:9 when adapted, else 1
    double vx, vy, vw, vh;     // where the image is drawn in the window (pixels)
} OutScale;

// dw x dh: the window's drawable size in pixels; now: seconds; gpu_ms: GPU time of the last frame (< 0: unknown)
void output_scale(double dw, double dh, bool reshape_allowed, double now, double gpu_ms, OutScale *o);
double output_scale_dynamic_factor(void);
// [XCDE] T146: the game's own frame size (its NVN window textures); the scale is relative to it (default 1920x1080)
void output_scale_set_base(int w, int h);
