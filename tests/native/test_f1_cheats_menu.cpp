// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-120: whole production F1 menu and tab, authored backend seams only.
#include "imgui.h"
#include "imgui_internal.h"
#include "imgui_impl_vulkan.h"
#include "../../Monado_Linux/runtime/cheats_options.h"
#include <SDL3/SDL.h>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <set>
#include <string>
#include <vector>
Settings g_settings{};
int g_window_w=1280,g_window_h=960;
static unsigned saves;
static Uint64 clock_ns=1;
struct Item {ImGuiID id;std::string label;ImRect box;};
static std::vector<Item> items;
// Tab labels are announced before ItemAdd; update their rectangle by stable ID.
void ImGuiTestEngineHook_ItemAdd(ImGuiContext *ctx,ImGuiID id,const ImRect &box,const ImGuiLastItemData*) {
 for(auto&i:items)if(i.id==id)i.box=box;
 // ImGui's Combo uses ItemAdd but does not emit an ItemInfo label hook.
 if(ctx->CurrentWindow&&ctx->CurrentWindow->IDStack.Size&&id==ctx->CurrentWindow->GetID("Show FPS on screen"))
     items.push_back({id,"Show FPS on screen",box});
}
void ImGuiTestEngineHook_ItemInfo(ImGuiContext *ctx,ImGuiID id,const char *label,ImGuiItemStatusFlags){items.push_back({id,label,ctx->LastItemData.Rect});}
void ImGuiTestEngineHook_Log(ImGuiContext*,const char*,...){}
const char *ImGuiTestEngine_FindItemDebugLabel(ImGuiContext*,ImGuiID){return "";}
extern "C" {
void menu_test_open(void);
void menu_render(void *,uint32_t,uint32_t);
bool vk_imgui_backend_init(void){return true;}
void vk_imgui_backend_shutdown(void){}
void input_reset(void){}
void vk_request_swapchain_recreate(void){}
bool dlss_available(void){return false;}
void fps_overlay_frame(uint64_t);
bool fps_overlay_visible(void);
bool tmp_fg_supported(void){return false;}
void xcde_graphics_publish(const GraphicsOptions *){}
void settings_save(void){++saves;}
Uint64 SDL_GetTicksNS(void){return clock_ns;}
SDL_Window *SDL_GetWindowFromID(SDL_WindowID){return nullptr;}
bool SDL_GetWindowSize(SDL_Window*,int*,int*){assert(false);return false;}
}
void ImGui_ImplVulkan_NewFrame(){}
bool ImGui_ImplVulkan_CreateFontsTexture(){unsigned char *p;int w,h;ImGui::GetIO().Fonts->GetTexDataAsRGBA32(&p,&w,&h);return p&&w&&h;}
void ImGui_ImplVulkan_RenderDrawData(ImDrawData *data,VkCommandBuffer,VkPipeline){assert(data&&data->Valid);}
static void frame(){items.clear();clock_ns+=16666667;menu_render(nullptr,(uint32_t)g_window_w,(uint32_t)g_window_h);}
static Item named(const char *label){for(const auto&i:items)if(i.label==label)return i;fprintf(stderr,"missing UI item: %s (%zu items)\n",label,items.size());for(const auto&i:items)fprintf(stderr,"item %s\n",i.label.c_str());assert(false);return{};}
static void click(const char *label){auto p=named(label).box.GetCenter();auto&io=ImGui::GetIO();io.AddMousePosEvent(p.x,p.y);frame();io.AddMouseButtonEvent(0,true);frame();io.AddMouseButtonEvent(0,false);frame();}
static void scroll(bool bottom) {
 auto *window=ImGui::FindWindowByName("Options  (F1 / Esc to go back to the game)");assert(window);
 ImGui::SetScrollY(window,bottom?window->ScrollMax.y:0.f);frame();frame();
}
int main(int argc,char **argv){
 if(argc==2) {g_window_h=std::atoi(argv[1]);assert(g_window_h==720||g_window_h==960);}
 g_settings.ui_lang=1;g_settings.cheat_movement_speed_percent=g_settings.cheat_enemy_health_percent=100;
 xcde_cheats_publish(&g_settings);menu_test_open();frame();GImGui->TestEngineHookItems=true;frame();
 named("Cheats");click("Cheats");frame();
 // The tab must expose all nine toggles and its Save action even at720p.
 const char *toggles[]={"Party damage dealt","Party damage received","Enemy health","EXP gained","AP gained","SP gained","Gold gained","Movement speed","No fall damage"};
 std::set<std::string> seen;
 auto collect=[&](){for(const auto &i:items)for(const char *label:toggles)if(i.label==label)seen.insert(label);};
 collect();scroll(true);collect();assert(seen.size()==9);
 named("Movement speed");named("No fall damage");
 click("Movement speed");assert(g_settings.cheat_movement_speed&&xcde_cheats_snapshot().enabled[XCDE_CHEAT_MOVEMENT_SPEED]);
 scroll(false);click("Enemy health");assert(g_settings.cheat_enemy_health&&xcde_cheats_enemy_health_percent()==100);
 scroll(true);click("Save");assert(saves==1);
 scroll(false);
 // Switching to another tab and returning retains the published live setting.
 click("Audio");frame();click("Cheats");frame();assert(g_settings.cheat_movement_speed&&g_settings.cheat_enemy_health);
 // LINUX-124: operate the actual live Graphics dropdown with mouse events.
 click("Graphics");frame();
 auto *window=ImGui::FindWindowByName("Options  (F1 / Esc to go back to the game)");assert(window);
 ImGui::SetScrollY(window,window->ScrollMax.y);frame();frame();
 const char *modes[]={"Number only","Compact HUD","Detailed panel","Off"};
 const int expected[]={FPS_OVERLAY_NUMBER,FPS_OVERLAY_COMPACT,FPS_OVERLAY_DETAILED,FPS_OVERLAY_OFF};
 for(int i=0;i<4;i++) {
     click("Show FPS on screen");frame();click(modes[i]);frame();
     assert(g_settings.fps_overlay_mode==expected[i]);
     assert(g_settings.show_fps_overlay==(expected[i]!=FPS_OVERLAY_OFF));
     fps_overlay_frame(++clock_ns);assert(fps_overlay_visible()==(expected[i]!=FPS_OVERLAY_OFF));
 }
 click("Show FPS on screen");frame();click("Detailed panel");frame();
 click("Save");assert(saves==2&&g_settings.fps_overlay_mode==FPS_OVERLAY_DETAILED);
 printf("whole F1 menu: Cheats tab, nine toggles, Save accessibility at%dp, actual publication, tab-return and live FPS modes PASS\n",g_window_h);
}
