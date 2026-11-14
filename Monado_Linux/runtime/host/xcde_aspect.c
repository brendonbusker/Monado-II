// [XCDE] LINUX-089: keep the original 16:9 view, adding horizontal space on
// wider displays or vertical space on taller ones. No game memory is written.
#include "xcde_aspect.h"
#include "../settings.h"
#include <math.h>
#include <stdatomic.h>
#include <string.h>

static const float reference_aspect = 16.0f / 9.0f;
static const float pi = 3.14159265358979323846f;
static _Atomic uint32_t published_factor = UINT32_C(0x3f800000);

static uint32_t bits(float value) { uint32_t result; memcpy(&result, &value, sizeof result); return result; }
static float scalar(uint32_t value) { float result; memcpy(&result, &value, sizeof result); return result; }

bool xcde_aspect_enabled(void) {
    switch (g_settings.aspect) {
    case ASPECT_UNLOCKED: case ASPECT_16_10: case ASPECT_21_9: case ASPECT_32_9: return true;
    default: return false;
    }
}

double xcde_aspect_target_factor(double drawable_factor) {
    switch (g_settings.aspect) {
    case ASPECT_UNLOCKED: return drawable_factor;
    case ASPECT_16_10: return 0.9;
    case ASPECT_21_9: return 21.0 / 16.0;
    case ASPECT_32_9: return 2.0;
    default: return 1.0;
    }
}

bool xcde_aspect_supported_factor(float factor) {
    // Allow harmless float rounding at the exact 16:10 and 32:9 boundaries.
    return isfinite(factor) && factor >= 0.9f - 0.00001f && factor <= 2.0f + 0.00001f;
}

void xcde_aspect_set_factor(float factor) {
    if (!xcde_aspect_supported_factor(factor)) factor = 1.0f;
    if (factor < 0.9f) factor = 0.9f;
    if (factor > 2.0f) factor = 2.0f;
    // Match output_scale's fitted-16:9 deadband, including before the first
    // presented frame when the renderer publishes the swapchain dimensions.
    if (fabsf(factor - 1.0f) <= 0.005f) factor = 1.0f;
    atomic_store_explicit(&published_factor, bits(factor), memory_order_relaxed);
}

static float factor_now(void) {
    if (!xcde_aspect_enabled()) return 1.0f;
    return scalar(atomic_load_explicit(&published_factor, memory_order_relaxed));
}

bool xcde_aspect_active(void) { return factor_now() != 1.0f; }

static bool reference_camera(float aspect) {
    return isfinite(aspect) && fabsf(aspect - reference_aspect) <= 0.0001f;
}

float xcde_aspect_ratio(float original_aspect) {
    float factor = factor_now();
    if (factor == 1.0f || !reference_camera(original_aspect)) return original_aspect;
    return original_aspect * factor;
}

static float fov_for_factor(float radians, float aspect, float factor) {
    if (factor >= 1.0f || !reference_camera(aspect) || !isfinite(radians) || radians <= 0.001f || radians >= pi - 0.001f)
        return radians;
    float result = 2.0f * atanf(tanf(radians * 0.5f) / factor);
    return isfinite(result) && result > 0.0f && result < pi ? result : radians;
}

float xcde_aspect_fov(float original_radians, float original_aspect) {
    return fov_for_factor(original_radians, original_aspect, factor_now());
}

uint32_t xcde_aspect_ratio_bits(uint32_t original_bits) {
    if (!xcde_aspect_active()) return original_bits;
    return bits(xcde_aspect_ratio(scalar(original_bits)));
}

static uint32_t degrees_bits(uint32_t original_bits, float original_aspect, float factor) {
    float degrees = scalar(original_bits);
    if (factor >= 1.0f || !reference_camera(original_aspect) || !isfinite(degrees) || degrees <= 0.001f || degrees >= 179.9f)
        return original_bits;
    float radians = degrees * (pi / 180.0f);
    float adapted = fov_for_factor(radians, original_aspect, factor) * (180.0f / pi);
    return isfinite(adapted) && adapted > 0.0f && adapted < 180.0f ? bits(adapted) : original_bits;
}

uint32_t xcde_aspect_fov_degrees_bits(uint32_t original_bits, uint32_t original_aspect_bits) {
    return degrees_bits(original_bits, scalar(original_aspect_bits), factor_now());
}

uint32_t xcde_aspect_render_fov_degrees_bits(uint32_t original_bits, uint32_t rendered_aspect_bits) {
    float factor = factor_now();
    if (factor >= 1.0f) return original_bits;
    // The preceding checked renderer-camera store already contains the target
    // aspect. Recover its reference only for this camera's FOV qualification.
    return degrees_bits(original_bits, scalar(rendered_aspect_bits) / factor, factor);
}

uint32_t xcde_aspect_hud_ratio_bits(uint32_t original_bits, bool horizontal) {
    float factor = factor_now();
    float original = scalar(original_bits);
    if (factor == 1.0f || !reference_camera(original)) return original_bits;
    // World-to-screen uses the camera's swapped-axis auxiliary matrix. Its
    // aspect compensation must also map into the centered, uniformly scaled
    // 16:9 HUD canvas: min(reference,target) for X; max for Y. Rendering that
    // canvas stretched would invalidate this policy and must remain forbidden.
    float axis_factor = horizontal ? fminf(1.0f, factor) : fmaxf(1.0f, factor);
    return axis_factor == 1.0f ? original_bits : bits(original * axis_factor);
}
