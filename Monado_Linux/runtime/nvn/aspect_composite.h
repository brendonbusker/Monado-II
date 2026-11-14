// [XCDE] LINUX-093: scene-composite classification, independent of Vulkan.
// Inputs describe actual renderer allocation metadata, not screenshot pixels.
#ifndef MONADO_ASPECT_COMPOSITE_H
#define MONADO_ASPECT_COMPOSITE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <math.h>

typedef struct {
    uint32_t width, height;
    float sx, sy;
    bool scene_target, gpu_written, color_image, separate_image;
} AspectCompositeInput;

typedef struct {
    uint32_t width, height, count, instances, mode;
    float sx, sy, viewport[4];
} AspectCompositeDraw;

typedef enum {
    ASPECT_COMPOSITE_HUD,
    ASPECT_COMPOSITE_NATIVE_SIZE,
    ASPECT_COMPOSITE_SCENE_SOURCE,
    ASPECT_COMPOSITE_LEGACY_SINGLE
} AspectCompositeRole;

static inline bool aspect_composite_scene_source(const AspectCompositeDraw *draw, const AspectCompositeInput *input) {
    if (!input->scene_target || !input->gpu_written || !input->color_image || !input->separate_image ||
        !input->width || !input->height || !isfinite(input->sx) || !isfinite(input->sy) || input->sx <= 0 || input->sy <= 0)
        return false;
    // Portrait targets use uniform scaling; ordinary CPU textures and square
    // minimap targets are not scene allocations. Neither widens a HUD draw.
    float target_shape = draw->sx / draw->sy, source_shape = input->sx / input->sy;
    return fabsf(source_shape - 1.0f) > 0.01f && fabsf(source_shape - target_shape) <= 0.01f * target_shape;
}

static inline AspectCompositeRole aspect_composite_role(const AspectCompositeDraw *draw,
                                                        const AspectCompositeInput *inputs, size_t count) {
    // Retain existing native-size and one-input treatment. Some scene readers
    // use a smaller dynamic target plus a LUT/bloom/other auxiliary input. Their
    // scene input is identified by actual GPU allocation metadata below, not
    // by a texture-count limit or exact equality with the output dimensions.
    for (size_t i = 0; i < count; ++i)
        if ((inputs[i].sx != 1 || inputs[i].sy != 1) && inputs[i].width == draw->width && inputs[i].height == draw->height)
            return ASPECT_COMPOSITE_NATIVE_SIZE;
    bool fullscreen = draw->count <= 6 && draw->viewport[0] == 0 && draw->viewport[1] == 0 &&
                      draw->viewport[2] >= draw->width && draw->viewport[3] >= draw->height;
    if (fullscreen && count == 1 && (inputs[0].sx != 1 || inputs[0].sy != 1)) return ASPECT_COMPOSITE_LEGACY_SINGLE;
    bool simple_quad = fullscreen && draw->count >= 3 && draw->instances == 1 && (draw->mode == 4 || draw->mode == 5);
    if (!simple_quad || !isfinite(draw->sx) || !isfinite(draw->sy) || draw->sx <= 0 || draw->sy <= 0)
        return ASPECT_COMPOSITE_HUD;
    for (size_t i = 0; i < count; ++i)
        if (aspect_composite_scene_source(draw, &inputs[i]))
            return ASPECT_COMPOSITE_SCENE_SOURCE;
    return ASPECT_COMPOSITE_HUD;
}
#endif
