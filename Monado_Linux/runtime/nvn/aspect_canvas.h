// [XCDE] LINUX-089: uniform original UI canvas inside a native-aspect target.
// Scene composites keep their full target viewport; only classified UI uses it.
#pragma once
#include <stdbool.h>
#include <math.h>

static inline bool xcde_aspect_canvas(float source_w, float source_h,
                                      float target_w, float target_h,
                                      float scale_x, float scale_y,
                                      float *uniform, float *offset_x, float *offset_y) {
    if (!isfinite(source_w) || !isfinite(source_h) || !isfinite(target_w) || !isfinite(target_h) ||
        !isfinite(scale_x) || !isfinite(scale_y) || source_w <= 0 || source_h <= 0 ||
        target_w <= 0 || target_h <= 0 || scale_x <= 0 || scale_y <= 0) return false;
    *uniform = fminf(scale_x, scale_y);
    *offset_x = (target_w - source_w * *uniform) * 0.5f;
    *offset_y = (target_h - source_h * *uniform) * 0.5f;
    return true;
}
