// [XCDE] LINUX-126: authored real-device sink for production snapshot functions.
// Vulkan dispatch pointers bypass the recorder's interposed copy/barrier names.
#define main unrelated_feedback_framegen_main
#include "test_framegen_linux.cpp"
#undef main
#include "test_renderer_feedback_gpu_bridge.h"
struct SnapshotAllocation {VkImage image;VkDeviceMemory memory;};
static std::vector<SnapshotAllocation> snapshot_allocations;
static PFN_vkCmdCopyImage copy_image;
static PFN_vkCmdPipelineBarrier2 pipeline_barrier;
static uint64_t oracle_hash=14695981039346656037ull;
extern "C" VkCommandBuffer feedback_gpu_command(void){return command;}
extern "C" VkResult feedback_gpu_create(const VkImageCreateInfo *info,VkImage *image){
    VkImageCreateInfo ci=*info;
    // Readback is an authored test oracle, not an added production image use.
    ci.usage|=VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    VkResult result=vkCreateImage(device,&ci,nullptr,image);if(result!=VK_SUCCESS)return result;
    VkMemoryRequirements r;vkGetImageMemoryRequirements(device,*image,&r);
    VkMemoryAllocateInfo allocation{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};allocation.allocationSize=r.size;
    allocation.memoryTypeIndex=memory_type(r.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,0);
    VkDeviceMemory memory;VK_OK(vkAllocateMemory(device,&allocation,nullptr,&memory));VK_OK(vkBindImageMemory(device,*image,memory,0));
    snapshot_allocations.push_back({*image,memory});return VK_SUCCESS;
}
extern "C" void feedback_gpu_init(VkImage image,VkImageAspectFlags aspect){
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};b.srcStageMask=VK_PIPELINE_STAGE_2_NONE;b.dstStageMask=VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.dstAccessMask=VK_ACCESS_2_MEMORY_READ_BIT|VK_ACCESS_2_MEMORY_WRITE_BIT;b.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;b.newLayout=VK_IMAGE_LAYOUT_GENERAL;
    b.srcQueueFamilyIndex=b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.image=image;b.subresourceRange={aspect,0,VK_REMAINING_MIP_LEVELS,0,VK_REMAINING_ARRAY_LAYERS};
    VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};d.imageMemoryBarrierCount=1;d.pImageMemoryBarriers=&b;pipeline_barrier(command,&d);
}
extern "C" void feedback_gpu_barrier(void){
    VkMemoryBarrier2 b{VK_STRUCTURE_TYPE_MEMORY_BARRIER_2};b.srcStageMask=b.dstStageMask=VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    b.srcAccessMask=VK_ACCESS_2_MEMORY_WRITE_BIT;b.dstAccessMask=VK_ACCESS_2_MEMORY_READ_BIT|VK_ACCESS_2_MEMORY_WRITE_BIT;
    VkDependencyInfo d{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};d.memoryBarrierCount=1;d.pMemoryBarriers=&b;pipeline_barrier(command,&d);
}
extern "C" void feedback_gpu_copy(VkImage source,VkImage destination,uint32_t count,const VkImageCopy *regions){copy_image(command,source,VK_IMAGE_LAYOUT_GENERAL,destination,VK_IMAGE_LAYOUT_GENERAL,count,regions);}
extern "C" void feedback_gpu_clear(VkImage image,unsigned color){
    feedback_gpu_barrier();VkClearColorValue value{};CHECK(color<3);value.float32[color]=1;value.float32[3]=1;
    VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};vkCmdClearColorImage(command,image,VK_IMAGE_LAYOUT_GENERAL,&value,1,&range);
}
extern "C" void feedback_gpu_expect(VkImage image,unsigned width,unsigned height,unsigned color){
    CHECK(color<3);Buffer staging(size_t(width)*height*4);feedback_gpu_barrier();
    VkBufferImageCopy copy{};copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};copy.imageExtent={width,height,1};
    vkCmdCopyImageToBuffer(command,image,VK_IMAGE_LAYOUT_GENERAL,staging.buffer,1,&copy);finish();staging.sync(false);
    for(size_t pixel=0;pixel<size_t(width)*height;pixel++)for(unsigned channel=0;channel<4;channel++) {
        unsigned char expected=(channel==color || channel==3)?255:0;CHECK(staging.host[pixel*4+channel]==expected);
    }
    oracle_hash^=hash(staging.host,size_t(width)*height*4);oracle_hash*=1099511628211ull;begin();
}
int main(int argc,char **argv){
    CHECK(argc==2);private_state(argv[1]);create_device(false,false);
    CHECK(vkGetDeviceProcAddr(device,"vkCmdCopyImage") && vkGetDeviceProcAddr(device,"vkCmdPipelineBarrier2"));
    copy_image=reinterpret_cast<PFN_vkCmdCopyImage>(vkGetDeviceProcAddr(device,"vkCmdCopyImage"));
    pipeline_barrier=reinterpret_cast<PFN_vkCmdPipelineBarrier2>(vkGetDeviceProcAddr(device,"vkCmdPipelineBarrier2"));
    begin();int result=feedback_snapshot_gpu_cases();finish();CHECK(!result && !validation_errors);
    for(auto allocation:snapshot_allocations){vkDestroyImage(device,allocation.image,nullptr);vkFreeMemory(device,allocation.memory,nullptr);}
    printf("SNAPSHOT_GPU exact pixel-sequence hash=%016llx validation_errors=%u\n",(unsigned long long)oracle_hash,validation_errors);
    shutdown();return result;
}
