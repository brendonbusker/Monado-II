// [XCDE] LINUX-089: native aspect projection and centered 16:9 HUD policy.
#pragma once
#include <stdbool.h>
#include <stdint.h>

// The renderer publishes content aspect / (16/9). Only 16:10 through 32:9
// are qualified by this implementation. Unsupported/invalid factors reset to 1.
bool xcde_aspect_enabled(void);
// LINUX-090: same selected shape for first camera and per-present render/fit.
// Match display keeps the drawable factor; explicit ratios ignore it.
double xcde_aspect_target_factor(double drawable_factor);
bool xcde_aspect_supported_factor(float factor);
void xcde_aspect_set_factor(float factor);
bool xcde_aspect_active(void);
float xcde_aspect_ratio(float original_aspect);
float xcde_aspect_fov(float original_radians, float original_aspect);

// Checked scalar guest instructions retain their original load/store, then
// adapt its low 32 bits. Original mode and unsupported cameras are bit-exact.
uint32_t xcde_aspect_ratio_bits(uint32_t original_bits);
// LINUX-093: only the checked renderer-camera hook supplies the corresponding
// logical camera aspect. Render-size alignment must not decide camera identity.
uint32_t xcde_aspect_render_ratio_bits(uint32_t original_bits, uint32_t logical_aspect_bits);
uint32_t xcde_aspect_fov_degrees_bits(uint32_t original_bits, uint32_t original_aspect_bits);
uint32_t xcde_aspect_render_fov_degrees_bits(uint32_t original_bits, uint32_t logical_aspect_bits);
uint32_t xcde_aspect_hud_ratio_bits(uint32_t original_bits, bool horizontal);
