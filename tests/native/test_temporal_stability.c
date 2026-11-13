// [XCDE] LINUX-056: expose actual authored builtin GLSL to the headless GPU fixture.
// No game shader or translated program enters this test.
#include "../../Monado_Linux/runtime/nvn/vulkan/shaders.c"
const char smaa_hlsl_src[] = "";
const char *temporal_stability_source(const char *name, int *stage) {
    return builtin_src(name, stage);
}
