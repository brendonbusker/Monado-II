// [XCDE] LINUX-103: actual production feedback functions inserted by renderer_tests_linux.py.
// Deterministic Vulkan recording mocks, authored descriptors only; no game/image inputs.
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nvn/vulkan/vk.h"
#include "settings.h"
#include "quality_policy.h"
#ifdef FEEDBACK_GPU_BRIDGE
#include "test_renderer_feedback_gpu_bridge.h"
#endif
VkG g_vk;Settings g_settings;
static struct {
 uint64_t tex[3][32],img[3][8];NvnDescPool *tpool;
 struct {int ncolor;NvnTexture *color[8],*depth;NvnTextureView cview[8],dview;bool has_cview[8],has_dview;}rt;
 uint32_t channel_mask;bool ds[2],rt_dirty;
} st;
typedef struct {ShaderInfo *vi,*fi,*gi;uint64_t code[2];} Prog;
static bool in_pass;static unsigned ends,barriers,copies,images,retired;
static uint64_t stat_feedback_copies,frame=10;
static VkImageCreateInfo last_image;static VkImageCopy regions[64];static VkImageMemoryBarrier2 last_layout[8];static unsigned nlayout;
void rt_fatal_trace(void){abort();}void vk_device_fault_report(void){abort();}
VkCommandBuffer vk_cmd(void){
#ifdef FEEDBACK_GPU_BRIDGE
 return feedback_gpu_command();
#else
 return(VkCommandBuffer)(uintptr_t)1;
#endif
}
void vk_end_pass(void){if(in_pass){ends++;in_pass=false;}}
void vk_full_barrier(VkCommandBuffer command){assert(command==vk_cmd());barriers++;
#ifdef FEEDBACK_GPU_BRIDGE
 feedback_gpu_barrier();
#endif
}
uint64_t renderer_present_count(void){return frame;}
TexBackend *vk_tex(NvnTexture *texture,bool render){assert(render && texture && texture->backend);return texture->backend;}
void vk_views_forget(TexBackend *image){assert(image);}
void vk_defer_image(VkImage image,VmaAllocation allocation){(void)allocation;assert(image);retired++;}
void vk_image_init_layout(VkCommandBuffer command,VkImage image,VkImageAspectFlags aspect){assert(command==vk_cmd()&&image&&aspect);
#ifdef FEEDBACK_GPU_BRIDGE
 feedback_gpu_init(image,aspect);
#endif
}
VKAPI_ATTR VkResult VKAPI_CALL vmaCreateImage(VmaAllocator allocator,const VkImageCreateInfo *info,const VmaAllocationCreateInfo *memory,VkImage *image,VmaAllocation *allocation,VmaAllocationInfo *details){
 (void)allocator;(void)memory;(void)details;last_image=*info;*image=(VkImage)(uintptr_t)(++images+100);*allocation=(VmaAllocation)(uintptr_t)images;
#ifdef FEEDBACK_GPU_BRIDGE
 return feedback_gpu_create(info,image);
#else
 return VK_SUCCESS;
#endif
}
VKAPI_ATTR void VKAPI_CALL vkCmdCopyImage(VkCommandBuffer command,VkImage source,VkImageLayout source_layout,VkImage destination,VkImageLayout destination_layout,uint32_t count,const VkImageCopy *copy){
 assert(command==vk_cmd() && source && destination && source!=destination && source_layout==VK_IMAGE_LAYOUT_GENERAL && destination_layout==VK_IMAGE_LAYOUT_GENERAL);
 assert(copies+count<=64);for(unsigned i=0;i<count;i++){assert(copy[i].srcSubresource.aspectMask && !(copy[i].srcSubresource.aspectMask&(copy[i].srcSubresource.aspectMask-1)));regions[copies++]=copy[i];}
#ifdef FEEDBACK_GPU_BRIDGE
 feedback_gpu_copy(source,destination,count,copy);
#endif
}
VKAPI_ATTR void VKAPI_CALL vkCmdPipelineBarrier2(VkCommandBuffer command,const VkDependencyInfo *info){
 assert(command==vk_cmd());barriers++;nlayout=info->imageMemoryBarrierCount;assert(nlayout<=8);for(unsigned i=0;i<nlayout;i++)last_layout[i]=info->pImageMemoryBarriers[i];
 if(info->memoryBarrierCount){assert(in_pass && info->dependencyFlags==VK_DEPENDENCY_BY_REGION_BIT);assert(info->pMemoryBarriers[0].srcStageMask==VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT);}
}
static uint32_t level_extent(uint32_t x,uint32_t level){return x>>level?x>>level:1;}
static bool ct_on(void){return false;}
static void fb_stat_add(const char *key){assert(key);}
static void vk_watch(VkImage image,const char *site){assert(image && site);}
static const bool g_debug_frame=false;
static void debug_save_depth(TexBackend *image,const char *path){assert(image && path);}
// GENERATED_PRODUCTION_FUNCTIONS
static unsigned sharpen_images,sharpen_passes;static float sharp_parameter;static TexBackend sharp_output;
static TexBackend *post_image(int slot,uint32_t width,uint32_t height){assert(slot==4 && width==320 && height==180);sharpen_images++;return &sharp_output;}
static VkImageView post_view(TexBackend *image){assert(image==&sharp_output);return (VkImageView)(uintptr_t)1000;}
static void post_pass(VkCommandBuffer command,const char *name,const VkImageView *input,int count,TexBackend *output,const float *parameter,bool clear){
 assert(command==vk_cmd() && !strcmp(name,"rcas.frag") && count==1 && input[0]==(VkImageView)(uintptr_t)2000 && output==&sharp_output && !clear);
 assert(parameter[4]==320 && parameter[5]==180);sharpen_passes++;sharp_parameter=parameter[0];
}
// GENERATED_SHARPEN_FUNCTION
static TexBackend backend={.image=(VkImage)(uintptr_t)10,.width=16,.height=8,.depth=1,.layers=1,.levels=1,.samples=1,.format=VK_FORMAT_R8G8B8A8_UNORM,.aspect=VK_IMAGE_ASPECT_COLOR_BIT,.base_type=VK_IMAGE_VIEW_TYPE_2D,.feedback_usage=true};
static NvnTexture texture;static NvnTexEntry entries[2];static NvnDescPool pool;static ShaderInfo vertex,fragment,geometry;static Prog program;
static void reset(void){memset(&st,0,sizeof st);memset(&texture,0,sizeof texture);memset(&vertex,0,sizeof vertex);memset(&fragment,0,sizeof fragment);memset(&geometry,0,sizeof geometry);
 texture.backend=&backend;texture.levels=backend.levels;texture.layout.layers=backend.layers;texture.depth=backend.depth;entries[1]=(NvnTexEntry){.tex=&texture};pool=(NvnDescPool){.count=2,.entries=entries};st.tpool=&pool;st.tex[1][0]=1;st.rt.color[0]=&texture;st.rt.ncolor=1;st.channel_mask=15;
 fragment.ntex=1;fragment.tex[0]=(ShaderTexture){.handle_offset=0x20,.type=TEXTYPE_2D};program=(Prog){.vi=&vertex,.fi=&fragment};draw_feedback_mask=0;pass_nfeedback=0;nfeedback=0;in_pass=false;copies=0;barriers=0;ends=0;vk_feedback_boundary();
}
// GENERATED_PERFORMANCE_TESTS
#ifdef FEEDBACK_GPU_BRIDGE
#include "test_renderer_feedback_gpu_cases_linux.h"
#else
int main(void){
 // Missing extension must copy, unlike the old GENERAL-only direct path.
 reset();g_vk.feedback_loop=false;resolve_feedback(&program);assert(copies==1 && nfeedback==1 && draw_feedback_mask==0);assert(last_image.extent.width==16);
 // Extension alone is insufficient when image wasn't created with legal usage.
 reset();g_vk.feedback_loop=true;backend.feedback_usage=false;resolve_feedback(&program);assert(copies==1);backend.feedback_usage=true;
 // Read-only fragment feedback chooses native and records proper whole-image transitions.
 reset();resolve_feedback(&program);assert(copies==0 && nfeedback==0 && draw_feedback_mask==1);
 pass_feedback[0]=&backend;pass_nfeedback=1;feedback_layout(true);assert(nlayout==1 && last_layout[0].oldLayout==VK_IMAGE_LAYOUT_GENERAL && last_layout[0].newLayout==VK_IMAGE_LAYOUT_ATTACHMENT_FEEDBACK_LOOP_OPTIMAL_EXT);
 assert(last_layout[0].srcQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED && last_layout[0].subresourceRange.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT);
 assert(feedback_sample_layout(&backend)==VK_IMAGE_LAYOUT_ATTACHMENT_FEEDBACK_LOOP_OPTIMAL_EXT);feedback_layout(false);assert(last_layout[0].newLayout==VK_IMAGE_LAYOUT_GENERAL);pass_nfeedback=0;
 // Self-written output is snapshotted once per guest visibility interval, not once per draw.
 reset();fragment.out_mask=15;resolve_feedback(&program);assert(copies==1 && draw_feedback_mask==0);feedback_written(&texture);resolve_feedback(&program);assert(copies==1);
 vk_feedback_boundary();resolve_feedback(&program);assert(copies==2);frame++;resolve_feedback(&program);assert(copies==3);backend.image=(VkImage)(uintptr_t)11;resolve_feedback(&program);assert(copies==4);
 vk_feedback_texture_gone(&texture);resolve_feedback(&program);assert(copies==5);
 backend.image_identity++;resolve_feedback(&program);assert(copies==6); // same Vulkan handle, a different allocation
 // Match the actual pipeline's any-output-nibble + channel-mask write policy.
 reset();fragment.out_mask=1;st.channel_mask=2;resolve_feedback(&program);assert(copies==1 && draw_feedback_mask==0);
 // Unchanged read-only snapshots reuse; an intervening write must invalidate them.
 reset();g_vk.feedback_loop=false;resolve_feedback(&program);resolve_feedback(&program);assert(copies==1);snapshots_invalidate(&texture);resolve_feedback(&program);assert(copies==2);
 // Vertex feedback must copy even with extension support.
 reset();g_vk.feedback_loop=true;vertex=fragment;fragment.ntex=0;st.tex[0][0]=1;resolve_feedback(&program);assert(copies==1 && draw_feedback_mask==0);
 // Storage alias prohibits the native sampled path; it advances visibility.
 reset();vertex.ntex=1;vertex.tex[0]=(ShaderTexture){.handle_offset=0x120,.type=TEXTYPE_2D,.is_image=true,.image_store=true};st.img[0][0]=1;uint64_t visibility=feedback_visibility;resolve_feedback(&program);assert(copies==1 && draw_feedback_mask==0 && feedback_visibility!=visibility);
 // Storage writes invalidate a former attachment even when not currently bound as a target.
 st.rt.color[0]=NULL;visibility=feedback_visibility;fragment.ntex=0;resolve_feedback(&program);assert(feedback_visibility!=visibility);
 // Depth/stencil copies use separate aspects; preserve mip/layer extent instead of silent level0/2D.
 reset();backend.aspect=VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT;backend.format=VK_FORMAT_D32_SFLOAT_S8_UINT;backend.levels=2;backend.layers=3;backend.base_type=VK_IMAGE_VIEW_TYPE_2D_ARRAY;
 texture.levels=2;texture.layout.layers=3;st.rt.color[0]=NULL;st.rt.ncolor=0;st.rt.depth=&texture;fragment.tex[0].type=TEXTYPE_2D_ARRAY;resolve_feedback(&program);
 assert(copies==4 && last_image.mipLevels==2 && last_image.arrayLayers==3 && regions[2].extent.width==8 && regions[2].extent.height==4 && regions[2].srcSubresource.layerCount==3);
 // Non-overlapping mip views are not feedback, preserving downsample pass performance.
 reset();texture.levels=backend.levels;entries[1].has_view=true;entries[1].view=(NvnTextureView){.setmask=1,.base_level=0,.num_levels=1};st.rt.has_cview[0]=true;st.rt.cview[0]=(NvnTextureView){.setmask=1,.base_level=1,.num_levels=1};resolve_feedback(&program);assert(copies==0 && draw_feedback_mask==0);
 // An unchanged native mask is read-only, so no per-draw copy/restart is needed.
 backend.aspect=VK_IMAGE_ASPECT_COLOR_BIT;backend.format=VK_FORMAT_R8G8B8A8_UNORM;backend.levels=backend.layers=1;backend.base_type=VK_IMAGE_VIEW_TYPE_2D;
 reset();g_vk.feedback_loop=true;resolve_feedback(&program);in_pass=true;unsigned before=barriers;resolve_feedback(&program);assert(in_pass && barriers==before);
 resolve_feedback(&program);assert(in_pass && ends==0);
 in_pass=true;unsigned old_ends=ends;assert(!feedback_load_clear_ready(vk_cmd(),true) && !in_pass && ends==old_ends+1 && st.rt_dirty && !pass_feedback_clear_only);
 in_pass=true;unsigned old_barriers=barriers;assert(!feedback_load_clear_ready(vk_cmd(),true) && !in_pass && barriers==old_barriers);assert(feedback_load_clear_ready(vk_cmd(),false) && barriers==old_barriers);
 g_settings.upscale_sharpness=0;assert(fsr1_sharpen(vk_cmd(),(VkImageView)(uintptr_t)2000,320,180)==(VkImageView)(uintptr_t)2000 && !sharpen_images && !sharpen_passes);
 g_settings.upscale_sharpness=.9f;assert(fsr1_sharpen(vk_cmd(),(VkImageView)(uintptr_t)2000,320,180)==(VkImageView)(uintptr_t)1000 && sharpen_images==1 && sharpen_passes==1);assert(fabsf(sharp_parameter-exp2f(-.2f))<1e-6f);
 g_settings.upscale_sharpness=1.f;fsr1_sharpen(vk_cmd(),(VkImageView)(uintptr_t)2000,320,180);assert(sharp_parameter==1.f && sharpen_passes==2);
 feedback_performance_tests();
 puts("PASS production feedback: feature/usage eligibility, read/write distinction, visibility/frame/image/lifetime invalidation, vertex/storage fallback, full mip/layer/aspect copies, native layouts/dependencies");return 0;
}
#endif
