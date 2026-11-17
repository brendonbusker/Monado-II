// [XCDE] LINUX-126: real Vulkan sink for the extracted production recorder.
// Tests supply authored RGBA8 images only; no window, guest code or game data.
#pragma once
#include <stdint.h>
#include <vulkan/vulkan.h>
#ifdef __cplusplus
extern "C" {
#endif
VkCommandBuffer feedback_gpu_command(void);
VkResult feedback_gpu_create(const VkImageCreateInfo *info,VkImage *image);
void feedback_gpu_init(VkImage image,VkImageAspectFlags aspect);
void feedback_gpu_barrier(void);
void feedback_gpu_copy(VkImage source,VkImage destination,uint32_t count,const VkImageCopy *regions);
void feedback_gpu_clear(VkImage image,unsigned color);
void feedback_gpu_expect(VkImage image,unsigned width,unsigned height,unsigned color);
int feedback_snapshot_gpu_cases(void);
#ifdef __cplusplus
}
#endif
