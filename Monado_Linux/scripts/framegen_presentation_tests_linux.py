#!/usr/bin/env python3
"""[XCDE] LINUX-020: actual monotonic helper and extracted ordinary-WSI control flow; authored Vulkan mocks, no GPU/game/UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('scripts/framegen_presentation_tests_linux.py', 'tests/native/test_framegen_pacing_linux.c',
           'runtime/nvn/vulkan/framegen_pacing_linux.h', 'runtime/nvn/vulkan/device.c',
           'tests/native/test_temporal_framegen_linux.c', 'runtime/nvn/vulkan/temporal_fg_linux.inc',
           'runtime/nvn/vulkan/framegen_linux.h', 'runtime/settings.h', 'runtime/paths.h',
           'runtime/nvn/vulkan/exec.c', 'runtime/nvn/framegen_policy.h',
           'runtime/nvn/vulkan/framegen_present_linux.h', 'tests/native/test_framegen_async_linux.c')

IDLE_HEURISTIC_HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static struct {int fps;} g_settings={30};
static __thread uint64_t g_blocked_ns;
static bool pace_slow,deterministic;
static uint64_t stat_pace_over,virtual_now=1000000000ull;
static unsigned clock_reads,environment_reads;
static bool diag_deterministic(void){return deterministic;}
static uint64_t plat_now_ns(void){clock_reads++;return virtual_now;}
static char *fixture_getenv(const char *name){
 assert(!strcmp(name,"LARECOMP_PACE")||!strcmp(name,"XCDE_FPS_INTERVAL")||!strcmp(name,"LARECOMP_LOG_PACE"));
 environment_reads++;return NULL;
}
#define getenv fixture_getenv
#define LOG(...) do{}while(0)
#include "PACE_FRAME_SOURCE"
#undef getenv
int main(int argc,char **argv){
 assert(argc==2);
 bool accounted=!strcmp(argv[1],"accounted-idle")||!strcmp(argv[1],"real-busy");
 bool real_busy=!strcmp(argv[1],"real-busy");
 deterministic=!strcmp(argv[1],"deterministic");
 assert(accounted||deterministic||!strcmp(argv[1],"unaccounted-idle"));
 uint64_t busy=real_busy?18000000ull:12000000ull,idle=10000000ull;
 if(deterministic){pace_slow=true;stat_pace_over=7;}
 vk_pace_frame(); // Establish the actual function's initial timestamp.
 for(unsigned frame=1;frame<=60;frame++){
  virtual_now+=busy+idle;
  if(accounted)g_blocked_ns+=idle;
  vk_pace_frame();
  if(!deterministic){
   bool expected_slow=(!accounted||real_busy)&&frame>=12;
   assert(pace_slow==expected_slow);
  }
 }
 if(deterministic)assert(pace_slow&&stat_pace_over==7&&!clock_reads&&!environment_reads);
 else{
  assert(clock_reads==61&&environment_reads>0);
  assert(stat_pace_over==((!accounted||real_busy)?60ull:0ull));
  assert(g_blocked_ns==(accounted?600000000ull:0ull));
 }
 printf("actual vk_pace_frame %s: real_work_ns=%llu idle_ns=%llu accounted=%d slow=%d over=%llu clocks=%u\n",argv[1],
  (unsigned long long)busy,(unsigned long long)idle,accounted,pace_slow,(unsigned long long)stat_pace_over,clock_reads);
 return 0;
}
'''

POLICY_HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#include "POLICY_HEADER"
static struct {VkPhysicalDevice phys;VkSurfaceKHR surface;} g_vk;
static struct {int fps,cutscene_mode;bool vsync,frame_gen,frame_gen_match_display;} g_settings;
static bool g_vsync_fifo,wanted,warm,deterministic,hidden,period_override,test_vsync;
static VkPresentModeKHR actual_present_mode;
static const char *override;
static _Atomic float g_framegen_cap_fps;
static float refresh;
static bool diag_deterministic(void){return deterministic;}
static bool tmp_frame_gen_wanted(void){return wanted;}
static bool tmp_fg_repeat_suppressed(void){return warm;}
static float vk_display_hz(void){return refresh;}
static const char *policy_getenv(const char *name){
 if(!strcmp(name,"LARECOMP_VK_PRESENT"))return override;
 if(!strcmp(name,"XCDE_FPS_PERIOD_SCALE"))return period_override?"1":NULL;
 if(!strcmp(name,"LARECOMP_HIDDEN"))return hidden?"1":NULL;
 if(!strcmp(name,"XCDE_VSYNC_TEST"))return test_vsync?"1":NULL;
 assert(!"unexpected policy environment");return NULL;
}
#define getenv policy_getenv
#define LOG(...) do{}while(0)
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfacePresentModesKHR(VkPhysicalDevice p,VkSurfaceKHR surface,uint32_t *n,VkPresentModeKHR *m){
 assert(p==g_vk.phys&&surface==g_vk.surface);if(m){assert(*n>=3);m[0]=VK_PRESENT_MODE_FIFO_KHR;m[1]=VK_PRESENT_MODE_MAILBOX_KHR;m[2]=VK_PRESENT_MODE_IMMEDIATE_KHR;}*n=3;return VK_SUCCESS;
}
#include "PRESENT_MODE_SOURCE"
static void publish_cap(void){
#include "CAP_SOURCE"
}
int main(void){
 unsigned cases=0;const int fps[]={-60,0,30,60,120,165};
 for(unsigned f=0;f<6;f++)for(unsigned vs=0;vs<2;vs++)for(unsigned h=0;h<2;h++)for(unsigned d=0;d<2;d++){
  g_settings.fps=fps[f];g_settings.vsync=vs;hidden=h;deterministic=d;wanted=false;
  bool fifo=vs&&fps[f]>0&&fps[f]<=60&&!h&&!d;
  assert(present_mode()==(fifo?VK_PRESENT_MODE_FIFO_KHR:VK_PRESENT_MODE_MAILBOX_KHR)&&g_vsync_fifo==fifo);cases++;
 }
 hidden=deterministic=false;g_settings.fps=120;g_settings.vsync=true;wanted=true;
 assert(present_mode()==VK_PRESENT_MODE_FIFO_KHR&&g_vsync_fifo);cases++;
 g_settings.vsync=false;assert(present_mode()==VK_PRESENT_MODE_MAILBOX_KHR&&!g_vsync_fifo);cases++;
 g_settings.vsync=true;override="immediate";assert(present_mode()==VK_PRESENT_MODE_IMMEDIATE_KHR&&!g_vsync_fifo);cases++;
 override="mailbox";assert(present_mode()==VK_PRESENT_MODE_MAILBOX_KHR);cases++;override=NULL;
 period_override=true;assert(present_mode()==VK_PRESENT_MODE_MAILBOX_KHR);cases++;period_override=false;
 hidden=true;assert(present_mode()==VK_PRESENT_MODE_MAILBOX_KHR);cases++;test_vsync=true;
 assert(present_mode()==VK_PRESENT_MODE_FIFO_KHR);cases++;hidden=test_vsync=false;
 // The exact renderer publication block changes only a qualified provider.
 g_settings.fps=120;g_settings.frame_gen_match_display=true;wanted=warm=true;refresh=180;
 publish_cap();assert(atomic_load(&g_framegen_cap_fps)==90);cases++;
 warm=false;publish_cap();assert(!atomic_load(&g_framegen_cap_fps));cases++;
 warm=true;wanted=false;publish_cap();assert(!atomic_load(&g_framegen_cap_fps));cases++;
 wanted=true;g_settings.frame_gen_match_display=false;publish_cap();assert(!atomic_load(&g_framegen_cap_fps));cases++;
 g_settings.frame_gen_match_display=true;g_settings.fps=60;publish_cap();assert(atomic_load(&g_framegen_cap_fps)==60);cases++;
 g_settings.fps=0;publish_cap();assert(atomic_load(&g_framegen_cap_fps)==90);cases++;
 refresh=59.94f;publish_cap();assert(atomic_load(&g_framegen_cap_fps)==29.97f);cases++;
 refresh=0;g_settings.fps=120;publish_cap();assert(atomic_load(&g_framegen_cap_fps)==120);cases++;
 printf("actual present-mode/cap policy: %u cases passed\n",cases);return 0;
}
'''

def policy_fragments(source, out):
    start=source.index('static VkPresentModeKHR present_mode(void) {')
    end=source.index('\n}\n',start)+3
    mode=out/'present-mode.inc';mode.write_text(source[start:end])
    start=source.index('        extern bool tmp_fg_repeat_suppressed(void), tmp_frame_gen_wanted(void);')
    end=source.index('atomic_store_explicit(&g_framegen_cap_fps, cap, memory_order_release);',start)
    end+=len('atomic_store_explicit(&g_framegen_cap_fps, cap, memory_order_release);')
    cap=out/'publish-cap.inc';cap.write_text(source[start:end])
    return mode,cap

HARNESS = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <stdlib.h>
#include <vulkan/vulkan.h>
#include <stdatomic.h>
typedef struct {VkBuffer buf;uint64_t off;void *ptr;} VkSpan;
static struct {VkDevice dev;VkQueue queue,fg_queue[3];VkSemaphore timeline;VkPhysicalDevice phys;VkSwapchainKHR swapchain;VkFormat sc_format;VkExtent2D sc_extent;VkImage sc_images[8];VkImageView sc_views[8];unsigned sc_count;} g_vk;
typedef struct {uint32_t image;VkSemaphore acquired;bool ok;} Frame;
static Frame cur_frame;
#define FRAMES 3
static VkSemaphore acquire_sem[FRAMES];
static uint64_t slot_seq[FRAMES],completed_seq;
static int slot;
static bool sc_dirty,fps_game_output,fps_repeated_output;
static struct {bool show_fps_overlay;} g_settings;
static _Atomic float g_framegen_cap_fps;
static unsigned output_calls,output_generated,output_repeated,ahead_acquires;
static bool owned[8],signaled[8];
static VkSemaphore done_sem[8];
static bool rendering,hash_flag,flicker_flag,make_pair;
static unsigned scenario,presents,submits,copies,blits,redraws,acquires,records,waits,resumes,shots,hashes,recreates,pace_waits,invalidations;
#if defined(FRAMEGEN_PACING_BASELINE) || !defined(XCDE_LINUX_FRAMEGEN)
static bool fg_present_second;
static uint64_t fg_second_deadline,fg_submitted_generated,fg_submitted_real;
#endif
static __thread uint64_t g_blocked_ns;
static unsigned colors[8],present_colors[128];
static VkImageLayout image_layouts[8]; // [XCDE] LINUX-094: validate late-overlay layout transitions.
// [XCDE] LINUX-094: host FPS is applied after generation, never to its retained
// input. This marker models overlay composition, not game image pixels.
static bool overlay_enabled;
static unsigned overlay_draws;
static uint64_t sequence=1;
static uint64_t virtual_ns,acquire_ns,copy_ns,gpu_wait_ns,oversleep_ns,slept_ns,present_ns[128];
static uint64_t expected_half_ns,present_block_ns;
static float measured_frame_ms;
static int target_fps;
static VkPresentModeKHR actual_present_mode;
static float display_refresh;
static unsigned display_refresh_queries;
static float vk_display_hz(void){display_refresh_queries++;return display_refresh;}
int xcde_present_fps(void){return target_fps;}
float xcde_effective_present_fps(void){return scenario==43?29.97f:(float)target_fps;}
bool tmp_frame_gen_wanted(void){return scenario!=45;}
static uint64_t SDL_GetTicksNS(void){return virtual_ns;}
static void fps_overlay_present(uint64_t now,bool generated,bool repeated){if(!g_settings.show_fps_overlay)return;assert(now==virtual_ns);output_calls++;output_generated+=generated;output_repeated+=repeated;}
static char events[4096];static unsigned n_events;
static void event(char c){assert(n_events+1<sizeof events);events[n_events++]=c;events[n_events]=0;}
static int mock_clock(clockid_t c,struct timespec *t){assert(c==CLOCK_MONOTONIC);*t=(struct timespec){(time_t)(virtual_ns/1000000000ull),(long)(virtual_ns%1000000000ull)};event('T');return 0;}
static int mock_sleep(clockid_t c,int flags,const struct timespec *t,struct timespec *remain){
 assert(c==CLOCK_MONOTONIC&&flags==TIMER_ABSTIME&&!remain);
 uint64_t deadline=(uint64_t)t->tv_sec*1000000000ull+(uint64_t)t->tv_nsec;
#ifdef FRAMEGEN_PACING_BASELINE
 assert(presents%2==1&&deadline==present_ns[presents-1]+expected_half_ns);
#else
 assert(deadline>=virtual_ns);
#endif
 uint64_t before=virtual_ns;if(virtual_ns<deadline)virtual_ns=deadline;virtual_ns+=oversleep_ns;slept_ns+=virtual_ns-before;
 pace_waits++;event('D');return 0;}
#define clock_gettime mock_clock
#define clock_nanosleep mock_sleep
#include "PACING_HEADER"
#undef clock_gettime
#undef clock_nanosleep
#include "ASYNC_HEADER"
static FgPresentJob captured_job;static FgPresentOps captured_ops;static bool captured;
static bool fixture_presenter_start(FgPresenter *p,const FgPresentOps *ops){(void)p;captured_ops=*ops;return scenario>=46;}
static bool fixture_presenter_enqueue(FgPresenter *p,const FgPresentJob *job,FgPresentResult *old){(void)p;assert(scenario>=46&&!captured);*old=(FgPresentResult){0};captured_job=*job;captured=true;return true;}
static void vk_queue_lock(void){}
static void vk_queue_unlock(void){}
VKAPI_ATTR VkResult VKAPI_CALL vkWaitSemaphores(VkDevice dev,const VkSemaphoreWaitInfo *wi,uint64_t timeout){assert(dev==g_vk.dev&&wi&&timeout==10000000000ull);return VK_SUCCESS;}
#define LOG(...) do{}while(0)
#define FATAL(...) do{fprintf(stderr,__VA_ARGS__);abort();}while(0)
static const char *volatile g_rq_where="caller";
static void vk_rq_at(const char *where){g_rq_where=where;}
static VkCommandBuffer vk_cmd(void){return (VkCommandBuffer)(uintptr_t)0x10;}
static uint64_t vk_pending_seq(void){return sequence;}
static uint64_t vk_completed_seq(void){return completed_seq;}
static void vk_wait_seq(uint64_t seq){assert(seq>0&&seq<sequence);waits++;virtual_ns+=gpu_wait_ns;completed_seq=seq;event('W');}
static void vk_full_barrier(VkCommandBuffer cb){assert(cb==vk_cmd()&&!rendering);}
static unsigned image_index(VkImage image){for(unsigned i=0;i<8;i++)if(g_vk.sc_images[i]==image)return i;assert(!"unknown image");return 0;}
static void image_barrier(VkCommandBuffer cb,VkImage im,VkImageLayout from,VkImageLayout to){assert(cb==vk_cmd()&&!rendering);unsigned i=image_index(im);assert(image_layouts[i]==from);image_layouts[i]=to;}
static bool diag_hash_wanted(void){return hash_flag;}
bool diag_flicker_wanted(void){return flicker_flag;}
static uint64_t diag_frame(void){return 4;}
static void diag_frame_hash(uint64_t frame,const uint8_t *p,uint32_t w,uint32_t h){assert(frame==5&&p&&w&&h);hashes++;}
void vk_save_png(const char *path,const uint8_t *p,uint32_t w,uint32_t h){assert(path&&p&&w&&h);shots++;}
void diag_flicker_check(uint64_t frame,const uint8_t *p,uint32_t w,uint32_t h,void(*save)(const char*,const uint8_t*,uint32_t,uint32_t)){
 assert(frame==5&&p&&w&&h&&save==vk_save_png);}
static void save_window_image(VkCommandBuffer cb,VkSpan *shot){static uint8_t data[4096];assert(cb==vk_cmd()&&!rendering&&image_layouts[cur_frame.image]==VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);if(overlay_enabled)assert(colors[cur_frame.image]&8);shot->ptr=data;}
static VkSemaphore binary_semaphore(void){static uintptr_t id=0x90;return (VkSemaphore)id++;}
VKAPI_ATTR void VKAPI_CALL vkCmdBeginRendering(VkCommandBuffer cb,const VkRenderingInfo *info){
 assert(cb==vk_cmd()&&!rendering&&info->pColorAttachments->loadOp==VK_ATTACHMENT_LOAD_OP_CLEAR);
 assert(image_layouts[cur_frame.image]==VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL&&owned[cur_frame.image]);
 rendering=true;colors[cur_frame.image]=0;event('H');}
VKAPI_ATTR void VKAPI_CALL vkCmdEndRendering(VkCommandBuffer cb){assert(cb==vk_cmd()&&rendering&&image_layouts[cur_frame.image]==VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);rendering=false;event('E');}
VKAPI_ATTR void VKAPI_CALL vkCmdCopyImage(VkCommandBuffer cb,VkImage src,VkImageLayout sl,VkImage dst,VkImageLayout dl,uint32_t count,const VkImageCopy *copy){
 assert(cb==vk_cmd()&&!rendering&&src==(VkImage)(uintptr_t)0x200&&sl==VK_IMAGE_LAYOUT_GENERAL&&dl==VK_IMAGE_LAYOUT_GENERAL&&count==1);
 assert(copy->extent.width<=g_vk.sc_extent.width&&copy->extent.height<=g_vk.sc_extent.height&&image_layouts[image_index(dst)]==VK_IMAGE_LAYOUT_GENERAL);
 colors[image_index(dst)]=2;copies++;virtual_ns+=copy_ns;event('C');}
static void vk_frame_resume(void){assert(!rendering&&image_layouts[cur_frame.image]==VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);rendering=true;resumes++;event('R');}
static bool fps_overlay_visible(void){return overlay_enabled;}
static void fps_overlay_render(void *cb,uint32_t w,uint32_t h){
 assert(cb==(void*)vk_cmd()&&rendering&&w==g_vk.sc_extent.width&&h==g_vk.sc_extent.height);
 assert(!(colors[cur_frame.image]&8));colors[cur_frame.image]|=8;overlay_draws++;event('O');}
void tmp_fg_invalidate(void){invalidations++;}
void vk_present_redraw(VkCommandBuffer cb){assert(cb==vk_cmd()&&rendering);colors[cur_frame.image]=2;redraws++;event('B');}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceFormatProperties(VkPhysicalDevice physical,VkFormat format,VkFormatProperties *properties){
 assert(physical==g_vk.phys&&(format==VK_FORMAT_B8G8R8A8_UNORM||format==VK_FORMAT_R8G8B8A8_UNORM));memset(properties,0,sizeof *properties);
 if(scenario!=10)properties->optimalTilingFeatures=VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT;}
VKAPI_ATTR void VKAPI_CALL vkCmdBlitImage(VkCommandBuffer cb,VkImage src,VkImageLayout sl,VkImage dst,VkImageLayout dl,uint32_t count,const VkImageBlit *region,VkFilter filter){
 assert(cb==vk_cmd()&&!rendering&&src==(VkImage)(uintptr_t)0x200&&sl==VK_IMAGE_LAYOUT_GENERAL&&dl==VK_IMAGE_LAYOUT_GENERAL&&count==1&&filter==VK_FILTER_NEAREST);
 assert(image_layouts[image_index(dst)]==VK_IMAGE_LAYOUT_GENERAL);
 assert(region->srcOffsets[1].x==4&&region->srcOffsets[1].y==4);
 assert(region->dstOffsets[1].x==(int32_t)g_vk.sc_extent.width&&region->dstOffsets[1].y==(int32_t)g_vk.sc_extent.height);
 colors[image_index(dst)]=2;blits++;event('L');}
bool tmp_fg_record_present(VkCommandBuffer cb,VkImage scene,VkImage *base,float *ms){
 assert(cb==vk_cmd()&&!rendering&&!(colors[image_index(scene)]&8));records++;event('F');if(!make_pair)return false;
 colors[image_index(scene)]=1;*base=(VkImage)(uintptr_t)0x200;*ms=measured_frame_ms;return true;}
static void vk_submit_extra(VkSemaphore wait,VkSemaphore signal,VkCommandBuffer extra){
 assert(!rendering&&wait==cur_frame.acquired&&signal==done_sem[cur_frame.image]&&!extra&&image_layouts[cur_frame.image]==VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);submits++;sequence++;signaled[cur_frame.image]=true;event('S');}
static VkResult present_mock(VkQueue queue,const VkPresentInfoKHR *p){
 assert(queue==g_vk.queue&&p->waitSemaphoreCount==1&&p->swapchainCount==1&&*p->pSwapchains==g_vk.swapchain);
 assert(*p->pWaitSemaphores==done_sem[*p->pImageIndices]);assert(submits>=presents+1&&owned[*p->pImageIndices]&&signaled[*p->pImageIndices]);
 owned[*p->pImageIndices]=false;signaled[*p->pImageIndices]=false;
 assert(image_layouts[*p->pImageIndices]==VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
 present_colors[presents]=colors[*p->pImageIndices];present_ns[presents]=virtual_ns;presents++;event('P');virtual_ns+=present_block_ns;
 if(presents==1&&scenario==2)return VK_ERROR_OUT_OF_DATE_KHR;
 if(presents==1&&(scenario==8||scenario==33))return VK_SUBOPTIMAL_KHR;
 if(presents==1&&scenario==32)return VK_ERROR_OUT_OF_DATE_KHR;
 if(presents==2&&scenario==27)return VK_ERROR_OUT_OF_DATE_KHR;
 if(presents==2&&scenario==28)return VK_SUBOPTIMAL_KHR;
 return VK_SUCCESS;}
static PFN_vkQueuePresentKHR sc_present=present_mock;
#if defined(XCDE_LINUX_FRAMEGEN) && !defined(FRAMEGEN_PACING_BASELINE)
static void fg_present_reset(void);
#endif
static void recreate_swapchain(void){for(unsigned i=0;i<8;i++)assert(!owned[i]);recreates++;g_vk.swapchain=(VkSwapchainKHR)(uintptr_t)0x35;
#if defined(XCDE_LINUX_FRAMEGEN) && !defined(FRAMEGEN_PACING_BASELINE)
 fg_present_reset();
#endif
}
static VkResult acquire_mock(VkDevice dev,VkSwapchainKHR sc,uint64_t timeout,VkSemaphore sem,VkFence fence,uint32_t *image){
 assert(dev==g_vk.dev&&sc==g_vk.swapchain&&timeout==0&&sem&&!fence);ahead_acquires++;event('a');virtual_ns+=acquire_ns;
 if(scenario==23)return VK_NOT_READY;
 if(scenario==34)return VK_ERROR_OUT_OF_DATE_KHR;
 *image=1;assert(!owned[1]);owned[1]=true;image_layouts[1]=VK_IMAGE_LAYOUT_UNDEFINED;
 return scenario==24?VK_SUBOPTIMAL_KHR:VK_SUCCESS;}
static PFN_vkAcquireNextImageKHR sc_acquire=acquire_mock;
static bool vk_frame_begin(const float clear[4]){
 assert(clear[0]==0&&clear[1]==0&&clear[2]==0&&!cur_frame.ok&&!rendering);acquires++;event('A');
 virtual_ns+=acquire_ns;
 if(scenario==3)return false;
 if(sc_dirty){sc_dirty=false;recreate_swapchain();}
 cur_frame.image=scenario==9?0:1;assert(!owned[cur_frame.image]);owned[cur_frame.image]=true;cur_frame.acquired=(VkSemaphore)(uintptr_t)(0x71+acquires);cur_frame.ok=true;rendering=true;colors[cur_frame.image]=0;
 image_layouts[cur_frame.image]=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
 if(scenario==4){g_vk.sc_extent=(VkExtent2D){6,6};g_vk.swapchain=(VkSwapchainKHR)(uintptr_t)0x36;}
 if(scenario==5||scenario==10){g_vk.sc_format=VK_FORMAT_R8G8B8A8_UNORM;g_vk.swapchain=(VkSwapchainKHR)(uintptr_t)0x37;}
 return true;}
// The production declaration comes from vk.h, outside the extracted body.
void vk_framegen_drain(void);
#include "FRAME_END_SOURCE"
static void reset(unsigned mode){
 memset(&g_vk,0,sizeof g_vk);memset(done_sem,0,sizeof done_sem);memset(colors,0,sizeof colors);memset(present_colors,0,sizeof present_colors);
 present_block_ns=0;
 g_vk.queue=(VkQueue)(uintptr_t)0x20;g_vk.phys=(VkPhysicalDevice)(uintptr_t)0x21;g_vk.swapchain=(VkSwapchainKHR)(uintptr_t)0x30;g_vk.sc_format=VK_FORMAT_B8G8R8A8_UNORM;g_vk.sc_extent=(VkExtent2D){4,4};
 for(unsigned i=0;i<8;i++)g_vk.sc_images[i]=(VkImage)(uintptr_t)(0x100+i);
 cur_frame.image=0;cur_frame.acquired=(VkSemaphore)(uintptr_t)0x70;cur_frame.ok=true;rendering=true;colors[0]=2;
 memset(image_layouts,0,sizeof image_layouts);image_layouts[0]=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
 memset(acquire_sem,0,sizeof acquire_sem);memset(slot_seq,0,sizeof slot_seq);memset(owned,0,sizeof owned);memset(signaled,0,sizeof signaled);
 completed_seq=0;slot=0;sc_dirty=false;fps_game_output=true;fps_repeated_output=false;owned[0]=true;
 g_vk.dev=(VkDevice)(uintptr_t)0x22;g_vk.sc_count=2;
 output_calls=output_generated=output_repeated=ahead_acquires=0;g_settings.show_fps_overlay=false;
#ifndef FRAMEGEN_PACING_BASELINE
#ifdef XCDE_LINUX_FRAMEGEN
 memset(&fg_timing,0,sizeof fg_timing);fg_pacing_clock_reset(&fg_output_clock);fg_submitted_repeated=0;
 memset(fg_acquire_seq,0,sizeof fg_acquire_seq);memset(fg_acquire_sem,0,sizeof fg_acquire_sem);captured=false;
#endif
#endif
 scenario=mode;fg_present_second=false;hash_flag=false;flicker_flag=false;make_pair=true;sequence=1;
 overlay_enabled=false;overlay_draws=0;
 fg_second_deadline=g_blocked_ns=0;virtual_ns=4000000000ull;acquire_ns=copy_ns=gpu_wait_ns=oversleep_ns=slept_ns=0;
 measured_frame_ms=16.f;target_fps=60;expected_half_ns=8333333ull;
 actual_present_mode=VK_PRESENT_MODE_MAILBOX_KHR;display_refresh=0.f;display_refresh_queries=0;
 memset(present_ns,0,sizeof present_ns);
 if(mode==3)acquire_ns=6000000ull;
 if(mode==11||mode==13||mode==14){acquire_ns=4000000ull;copy_ns=2000000ull;}
 if(mode==12){acquire_ns=10000000ull;copy_ns=2000000ull;}
 if(mode==13)gpu_wait_ns=5000000ull;
 if(mode==14)oversleep_ns=3000000ull;
 if(mode>=15){measured_frame_ms=40.f;target_fps=60;expected_half_ns=8333333ull;}
 if(mode==16){target_fps=30;expected_half_ns=16666666ull;}
 if(mode==17){target_fps=120;expected_half_ns=4166666ull;}
 if(mode==18){target_fps=165;expected_half_ns=3030303ull;}
 if(mode==19){measured_frame_ms=4.f;target_fps=165;expected_half_ns=3030303ull;}
 if(mode==20||mode==21){target_fps=mode==20?0:-60;expected_half_ns=20000000ull;}
 presents=submits=copies=blits=redraws=acquires=records=waits=resumes=shots=hashes=recreates=pace_waits=invalidations=n_events=0;
 fg_submitted_generated=fg_submitted_real=0;events[0]=0;
}
static void prepare_first(void){
 assert(!cur_frame.ok&&!rendering);cur_frame=(Frame){0,(VkSemaphore)(uintptr_t)0x70,true};
 assert(!owned[0]);owned[0]=true;rendering=true;colors[0]=2;image_layouts[0]=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
}
static void extended(unsigned mode,bool overlay,bool expect_fixed){
 overlay_enabled=overlay;g_settings.show_fps_overlay=overlay;
#ifdef XCDE_LINUX_FRAMEGEN
 if(mode>=40&&mode<=42){
  measured_frame_ms=16.f;target_fps=60;expected_half_ns=8333333;
#ifdef FRAMEGEN_PACING_BASELINE
  expected_half_ns=8000000;
#endif
  const uint64_t origin=virtual_ns;
  const uint64_t ready_offsets[]={0,14000000,33000000,46000000,65000000,79000000,99000000,111000000};
  for(unsigned i=0;i<8;i++){
   if(i){uint64_t desired=origin+ready_offsets[i];if(virtual_ns<desired)virtual_ns=desired;prepare_first();}
#ifndef FRAMEGEN_PACING_BASELINE
   if(mode==41&&i==4)virtual_ns+=500000000;
   if(mode==42&&i==4){target_fps=30;expected_half_ns=16666666;}
#endif
   vk_frame_end(NULL);
   assert(!cur_frame.ok&&!rendering);
  }
  assert(presents==16&&submits==16&&records==8);
  uint64_t minimum=UINT64_MAX,maximum=0;
  for(unsigned i=1;i<presents;i++) {uint64_t gap=present_ns[i]-present_ns[i-1];if(gap<minimum)minimum=gap;if(gap>maximum)maximum=gap;}
  printf("MULTI mode=%u minimum_ns=%llu maximum_ns=%llu presentations=%u\n",mode,(unsigned long long)minimum,(unsigned long long)maximum,presents);fflush(stdout);
  if(expect_fixed){assert(minimum>=8333333);assert(g_blocked_ns==slept_ns);}
#ifndef FRAMEGEN_PACING_BASELINE
  if(mode==41||mode==42)assert(fg_timing.rebases>0);
#endif
  return;
 }
#ifndef FRAMEGEN_PACING_BASELINE
 g_vk.sc_count=3;
 if(mode==25)fps_game_output=false;
 if(mode==26)fps_repeated_output=true;
 if(mode==29)fg_acquire_seq[0]=fg_acquire_seq[1]=999;
 if(mode==30||mode==44)g_vk.sc_count=2;
 if(mode==31)sc_dirty=true;
 if(mode==35)copy_ns=12000000;
 if(mode==36)gpu_wait_ns=5000000;
 if(mode==37)acquire_ns=4000000;
 if(mode==38)present_block_ns=2000000;
 if(mode==39)oversleep_ns=3000000;
 if(mode==43){target_fps=30;expected_half_ns=(uint64_t)((double)(1000.f/29.97f)*500000.);}
 if(mode==44||mode==48){
  target_fps=0;actual_present_mode=VK_PRESENT_MODE_FIFO_KHR;
  display_refresh=mode==44?90.f:59.94f;
  expected_half_ns=(uint64_t)((double)(1000.f/(display_refresh*.5f))*500000.);
 }
 if(mode==45)make_pair=false;
 vk_frame_end(NULL);
 if(mode>=46){
  assert(captured&&fg_timing.async_pairs==1&&submits==2&&presents==0&&waits==0&&pace_waits==0);
  assert(!cur_frame.ok&&!rendering&&owned[0]&&owned[1]&&signaled[0]&&signaled[1]);
  assert(captured_job.swapchain==g_vk.swapchain&&captured_job.queue==g_vk.queue&&captured_job.shared_queue);
  assert(captured_job.image[0]==0&&captured_job.image[1]==1&&captured_job.sequence==2);
  assert(captured_job.done[0]==done_sem[0]&&captured_job.done[1]==done_sem[1]);
  assert(captured_ops.wait_ready&&captured_ops.present&&captured_ops.meter_now);
  assert(display_refresh_queries==(mode==48?1u:0u));
  if(mode==48)assert(captured_job.interval_ms==1000.f/29.97f);
  // A later render-thread collection receives captured, successful-only events.
  FgPresentResult completed={.valid=true,.job=captured_job,.result={VK_SUCCESS,mode==47?VK_ERROR_OUT_OF_DATE_KHR:VK_SUCCESS}};
  fps_game_output=false;
  completed.call_ns[0]=virtual_ns;completed.meter_ns[0]=virtual_ns;
  completed.call_ns[1]=virtual_ns+expected_half_ns;completed.meter_ns[1]=virtual_ns;
  fg_result_accept(&completed);
  assert(fg_submitted_generated==1&&fg_submitted_real==(mode==47?0u:1u));
  assert(output_calls==(overlay?(mode==47?1u:2u):0u));
  assert(sc_dirty==(mode==47));
  printf("ASYNC publication mode=%u producer-returned-before-GPU-and-present successful-events=%u\n",mode,output_calls);
  puts("actual async publication passed");return;
 }
 assert(!cur_frame.ok&&!rendering&&!fg_present_second&&!fg_second_deadline);
 for(unsigned i=0;i<8;i++)assert(!owned[i]&&!signaled[i]);
 if(mode==25||mode==26||mode==45){
  assert(presents==1&&submits==1&&records==(mode==45?1u:0u)&&!ahead_acquires&&!copies);
  assert(output_calls==(overlay&&mode!=25?1u:0u));assert(!output_generated);
  if(mode==26)assert(output_repeated==(overlay?1u:0u)&&fg_submitted_repeated==1);
 }else{
  assert(presents==2&&submits==2&&records==1&&copies==1&&waits==1);
  bool fallback=mode==23||mode==29||mode==30||mode==31||mode==34||mode==44;
  assert(fg_timing.ahead==(fallback?0u:1u)&&fg_timing.serial==(fallback?1u:0u));
  assert(acquires==(fallback?1u:0u));
  if(mode!=29&&mode!=30&&mode!=31&&mode!=44)assert(ahead_acquires==1);
  else assert(!ahead_acquires);
  assert(present_colors[0]==1+(overlay?8u:0u)&&present_colors[1]==2+(overlay?8u:0u));
  assert(strchr(events,'W')<strchr(events,'P'));
  if(!fallback)assert(strrchr(events,'S')<strchr(events,'W'));
  if(mode!=27&&mode!=32){
   assert(present_ns[1]-present_ns[0]>=expected_half_ns);
   if(mode==44)assert(present_ns[1]-present_ns[0]==expected_half_ns&&display_refresh_queries==1);
   if(overlay)assert(output_calls==2&&output_generated==1&&!output_repeated);
  }else if(overlay)assert(output_calls==1&&output_generated==(mode==27?1u:0u));
  assert(g_blocked_ns==slept_ns);
  if(mode==24||mode==27||mode==28||mode==31||mode==32||mode==33)assert(recreates==1);
  else assert(!recreates);
  if(mode==35)assert(present_ns[0]>=4012000000ull);
 }
 printf("EXTENDED mode=%u ahead=%llu serial=%llu output=%u generated=%u repeats=%u events=%s\n",mode,(unsigned long long)fg_timing.ahead,(unsigned long long)fg_timing.serial,output_calls,output_generated,output_repeated,events);
#else
 assert(!"baseline only supports sustained-cadence mode40");
#endif
#else
 (void)expect_fixed;(void)mode;assert(!"extended requires LinuxFG");
#endif
}
int main(int argc,char **argv){
 assert(argc==2||argc==3);unsigned mode=(unsigned)strtoul(argv[1],NULL,10);reset(mode);
 bool baseline=false;
#ifdef FRAMEGEN_PACING_BASELINE
 baseline=argc==2;
#endif
 if(argc==3){overlay_enabled=!strcmp(argv[2],"--overlay");assert(overlay_enabled||!strcmp(argv[2],"--expect-fixed"));}g_settings.show_fps_overlay=overlay_enabled;
 if(mode>=22){extended(mode,overlay_enabled,!baseline);if(overlay_enabled){printf("OVERLAY draws=%u presents=%u records=%u\n",overlay_draws,presents,records);assert(overlay_draws==(mode>=46?submits:presents));}puts("actual extended presentation passed");return 0;}
 if(mode==1)make_pair=false;if(mode==7)hash_flag=true;
 vk_frame_end(mode==6?"authored.png":NULL);
 assert(!cur_frame.ok&&!rendering&&!fg_present_second&&!fg_second_deadline);
 if(overlay_enabled){
   printf("OVERLAY draws=%u presents=%u records=%u events=%s\n",overlay_draws,presents,records,events);fflush(stdout);
   assert(overlay_draws==presents);
   if(records)assert(strchr(events,'F')<strchr(events,'O'));
 }else assert(!overlay_draws);
#ifndef XCDE_LINUX_FRAMEGEN
 assert(presents==1&&submits==1&&!records&&!copies&&!acquires);
 assert(present_colors[0]==2+(overlay_enabled?8u:0u));
 printf("actual ordinary vk_frame_end overlay=%d passed\n",overlay_enabled);return 0;
#endif
 if(mode==0||mode==9||mode>=11){assert(presents==2&&submits==2&&records==1&&copies==1&&acquires==1&&pace_waits==((acquire_ns+copy_ns<expected_half_ns)?1u:0u)&&waits==1);
   assert(present_colors[0]==1+(overlay_enabled?8u:0u)&&present_colors[1]==2+(overlay_enabled?8u:0u));assert(strchr(events,'W')<strchr(events,'P'));}
 else if(mode==1){assert(presents==1&&records==1&&!copies&&!waits&&!pace_waits&&!acquires);assert(present_colors[0]==2+(overlay_enabled?8u:0u));}
 else if(mode==2||mode==8){assert(presents==1&&recreates==1&&!acquires&&!pace_waits);}
 else if(mode==3){assert(presents==1&&acquires==1&&!copies&&pace_waits==(baseline?1:0));}
 else if(mode==4||mode==5){assert(presents==2&&blits==1&&!copies&&!redraws&&present_colors[1]==2+(overlay_enabled?8u:0u));}
 else if(mode==10){assert(presents==2&&!blits&&!copies&&redraws==1&&present_colors[1]==2+(overlay_enabled?8u:0u));}
 else if(mode==6){assert(presents==1&&!records&&shots==1&&!copies&&!acquires);}
 else if(mode==7){assert(presents==1&&!records&&hashes==1&&!copies&&!acquires);}
 else assert(!"unknown case");
 if(mode==0||mode==4||mode==5||mode==9||mode==10||mode>=11)assert(fg_submitted_generated==1&&fg_submitted_real==1);
 if(mode==1||mode==6||mode==7)assert(fg_submitted_generated==0&&fg_submitted_real==1);
 if(overlay_enabled){unsigned accepted=presents-((mode==2)?1u:0u);assert(output_calls==accepted);assert(output_generated==((records&&make_pair&&mode!=2)?1u:0u));assert(!output_repeated);}
 if(presents==2){
   uint64_t prep=acquire_ns+copy_ns,gap=present_ns[1]-present_ns[0];
   uint64_t expected_gap=baseline?8000000ull+oversleep_ns+prep:(prep>expected_half_ns?prep:expected_half_ns)+(prep<expected_half_ns?oversleep_ns:0);
   printf("PACING mode=%u baseline=%d prep_ns=%llu gap_ns=%llu expected_gap_ns=%llu slept_ns=%llu accounted_idle_ns=%llu\n",mode,baseline,
     (unsigned long long)prep,(unsigned long long)gap,(unsigned long long)expected_gap,(unsigned long long)slept_ns,(unsigned long long)g_blocked_ns);fflush(stdout);
   assert(gap==expected_gap);
   if(baseline)assert(strchr(events,'D')<strchr(events,'A')&&!g_blocked_ns);
   else {if(pace_waits)assert(strrchr(events,'S')<strchr(events,'D')&&strchr(events,'D')<strrchr(events,'P'));assert(g_blocked_ns==slept_ns);}
   if(mode==13)assert(present_ns[0]==4005000000ull);
 }
 if(mode==3)assert(virtual_ns==4000000000ull+acquire_ns+(baseline?8000000ull:0));
 printf("actual vk_frame_end scenario %u passed: %s\n",mode,events);return 0;
}
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def presentation_fragment(source):
    start=source.index('// [XCDE] LINUX-097-BEGIN_PRESENTATION_HELPERS')
    end=source.index('\nvoid vk_save_png(',start)
    return (source[start:end].replace('#include "framegen_pacing_linux.h"','#include "'+str(ROOT/'runtime/nvn/vulkan/framegen_pacing_linux.h')+'"')
            .replace('#include "framegen_present_linux.h"','#include "'+str(ROOT/'runtime/nvn/vulkan/framegen_present_linux.h')+'"')
            .replace('fg_presenter_start(&fg_presenter,&ops)','fixture_presenter_start(&fg_presenter,&ops)')
            .replace('fg_presenter_enqueue(&fg_presenter,&job,&previous)','fixture_presenter_enqueue(&fg_presenter,&job,&previous)'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pacing-only', action='store_true')
    parser.add_argument('--ubsan', action='store_true', help='undefined-behavior sanitizer with fatal failures')
    parser.add_argument('--baseline-source', type=Path, help='saved authored device.c under this port runs/; reproduce old bubble and require fixed-contract failure')
    parser.add_argument('--evidence-root', type=Path, default=ROOT / 'runs',
                        help='existing canonical ignored runs directory for a shared-worktree evidence destination')
    args = parser.parse_args()
    evidence = args.evidence_root.absolute()
    if evidence != evidence.resolve() or not evidence.is_dir() or evidence.name != 'runs':
        parser.error('canonical existing runs directory required')
    out = args.output.absolute()
    if out != out.resolve() or out.exists() or not out.is_relative_to(evidence):
        parser.error('fresh canonical output below the evidence runs directory required')
    if args.baseline_source and (args.baseline_source.absolute()!=args.baseline_source.resolve() or
            not args.baseline_source.is_file() or not args.baseline_source.is_relative_to(evidence)):
        parser.error('baseline source must be an ordinary canonical saved file below this port runs/')
    out.mkdir(parents=True); os.umask(0o077); resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TMPDIR': str(out)}
    cc = ROOT / '.deps/bin/clang-cc'
    sysroot = Path((ROOT / '.deps/graphics/active-sysroot.txt').read_text().strip())
    receipt = {'scope': __doc__, 'status': 'running', 'host': list(platform.uname()), 'argv': os.sys.argv,
               'compiler_sha256': digest(cc), 'sources_before': {s: digest(ROOT / s) for s in SOURCES}, 'commands': []}

    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def run(name, argv, expected=0, timeout=10):
        row = {'name': name, 'argv': list(map(str, argv)), 'cwd': str(ROOT), 'environment': env,
               'timeout_seconds': timeout, 'expected_exit': expected}
        receipt['commands'].append(row); save(); started = time.monotonic()
        child = subprocess.run(row['argv'], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        row.update(exit=child.returncode, seconds=time.monotonic() - started)
        (out / (name + '.stdout.log')).write_bytes(child.stdout)
        (out / (name + '.stderr.log')).write_bytes(child.stderr); save()
        if child.returncode != expected:
            raise RuntimeError(name + ': ' + child.stdout.decode(errors='replace') + child.stderr.decode(errors='replace'))
        return child.stdout.decode()

    try:
        flags = ['-O1', '-UNDEBUG', '-march=x86_64_v2', '-ffp-contract=off', '-fno-strict-aliasing',
                 '-Werror=implicit-function-declaration', '-I' + str(sysroot / 'usr/include')]
        if args.ubsan: flags += ['-fsanitize=undefined', '-fno-sanitize-recover=all']
        for mode, define in [('mock', []), ('real', ['-DFRAMEGEN_PACING_REAL_CLOCK'])]:
            binary = out / ('pacing-' + mode)
            run('compile-pacing-' + mode, [cc, *flags, *define, ROOT / SOURCES[1], '-lm', '-o', binary], timeout=30)
            print(run('pacing-' + mode, [binary]), end='')
        if not args.pacing_only:
            run('compile-temporal-adapter', [cc, *flags, ROOT / SOURCES[4], '-lm', '-o', out / 'temporal-adapter'], timeout=30)
            print(run('temporal-adapter', [out / 'temporal-adapter']), end='')
            pace_source=(ROOT/'runtime/nvn/vulkan/exec.c').read_text()
            pace_start=pace_source.index('void vk_pace_frame(void) {')
            pace_end=pace_source.index("\n// a pair's end counter",pace_start)
            pace_fragment=out/'exec-pace-frame.inc'
            pace_fragment.write_text(pace_source[pace_start:pace_end])
            idle_harness=out/'idle-heuristic.c'
            idle_harness.write_text(IDLE_HEURISTIC_HARNESS.replace('PACE_FRAME_SOURCE',str(pace_fragment)))
            receipt['idle_heuristic_source']={'path':'runtime/nvn/vulkan/exec.c',
                'sha256':digest(ROOT/'runtime/nvn/vulkan/exec.c'),'extracted_sha256':digest(pace_fragment)}
            run('compile-idle-heuristic',[cc,*flags,idle_harness,'-o',out/'idle-heuristic'],timeout=30)
            for scenario in ('unaccounted-idle','accounted-idle','real-busy','deterministic'):
                print(run('idle-heuristic-'+scenario,[out/'idle-heuristic',scenario]),end='')
            source = (ROOT / SOURCES[3]).read_text()
            mode,cap = policy_fragments(source,out)
            policy = out/'presentation-policy.c'
            policy.write_text(POLICY_HARNESS.replace('PRESENT_MODE_SOURCE',str(mode)).replace('CAP_SOURCE',str(cap))
                              .replace('POLICY_HEADER',str(ROOT/'runtime/nvn/framegen_policy.h')))
            run('compile-presentation-policy',[cc,*flags,'-DXCDE_LINUX_FRAMEGEN',policy,'-lm','-o',out/'presentation-policy'],timeout=30)
            print(run('presentation-policy',[out/'presentation-policy']),end='')
            start = source.index('// [XCDE] LINUX-097-BEGIN_PRESENTATION_HELPERS')
            end = source.index('\nvoid vk_save_png(', start)
            extracted = presentation_fragment(source)
            (out / 'device-frame-end.inc').write_text(extracted)
            harness = HARNESS.replace('PACING_HEADER', str(ROOT / SOURCES[2])).replace('ASYNC_HEADER',str(ROOT/'runtime/nvn/vulkan/framegen_present_linux.h')).replace('FRAME_END_SOURCE', str(out / 'device-frame-end.inc'))
            harness = harness.replace('#include <stdio.h>', '#include <stdio.h>\n#include <stdlib.h>')
            (out / 'presentation.c').write_text(harness)
            run('compile-presentation', [cc, *flags, '-DXCDE_LINUX_FRAMEGEN', out / 'presentation.c', '-lm', '-o', out / 'presentation'], timeout=30)
            for mode in range(49):
                print(run('presentation-' + str(mode), [out / 'presentation', str(mode)]), end='')
            for mode in range(49):
                print(run('presentation-overlay-' + str(mode), [out / 'presentation', str(mode), '--overlay']), end='')
            if args.baseline_source:
                baseline=args.baseline_source.read_text()
                start=baseline.index('void vk_frame_end(const char *shot_path) {')
                end=baseline.index('\nvoid vk_save_png(',start)
                (out/'baseline-frame-end.inc').write_text(baseline[start:end])
                baseline_harness=harness.replace(str(out/'device-frame-end.inc'),str(out/'baseline-frame-end.inc'))
                baseline_header=args.baseline_source.with_name('framegen_pacing_linux.h')
                if baseline_header.is_file():baseline_harness=baseline_harness.replace(str(ROOT/SOURCES[2]),str(baseline_header))
                (out/'baseline-presentation.c').write_text(baseline_harness)
                receipt['baseline_source']={'path':str(args.baseline_source),'sha256':digest(args.baseline_source)}
                run('compile-baseline-presentation',[cc,*flags,'-DXCDE_LINUX_FRAMEGEN','-DFRAMEGEN_PACING_BASELINE',out/'baseline-presentation.c','-lm','-o',out/'baseline-presentation'],timeout=30)
                print(run('baseline-presentation-40',[out/'baseline-presentation','40']),end='')
                negative=run('baseline-fixed-contract-negative',[out/'baseline-presentation','40','--expect-fixed'],expected=-signal.SIGABRT)
                assert 'MULTI mode=40' in negative, 'negative control failed before actual cadence assertion'
        receipt['sources_after'] = {s: digest(ROOT / s) for s in SOURCES}
        if receipt['sources_before'] != receipt['sources_after']:
            raise RuntimeError('sources changed during focused tests')
        receipt['status'] = 'passed'
    except Exception as error:
        receipt.update(status='failed', error=str(error)); raise
    finally:
        save(); print(out)


if __name__ == '__main__':
    main()
