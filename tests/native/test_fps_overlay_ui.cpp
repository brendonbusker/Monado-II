// [XCDE] LINUX-094: actual FPS UI with authored clocks/backend seams, no window/game.
#include "imgui.h"
#include "imgui_impl_vulkan.h"
#include "../../Monado_Linux/runtime/ui/fps_overlay_draw.h"
#include "../../Monado_Linux/runtime/settings.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

Settings g_settings{};
static uint64_t clock_ns = 1;
static unsigned backend_starts, render_calls;
static bool fail_backend, fail_fonts;
static unsigned backend_stops;
static int rendered_vertices;
static float target_w, target_h;

extern "C" void fps_overlay_frame(uint64_t);
extern "C" void fps_overlay_reset(void);
extern "C" bool fps_overlay_visible(void);
extern "C" void fps_overlay_render(void *, uint32_t, uint32_t);
extern "C" Uint64 SDL_GetTicksNS(void) { return clock_ns; }
extern "C" bool vk_imgui_backend_init(void) { backend_starts++; return !fail_backend; }
extern "C" void vk_imgui_backend_shutdown(void) { backend_stops++; }
void ImGui_ImplVulkan_NewFrame() {}
bool ImGui_ImplVulkan_CreateFontsTexture() {
    if (fail_fonts) return false;
    unsigned char *pixels; int w,h;
    ImGui::GetIO().Fonts->GetTexDataAsRGBA32(&pixels,&w,&h);
    ImGui::GetIO().Fonts->SetTexID(1);
    return pixels && w>0 && h>0;
}
void ImGui_ImplVulkan_RenderDrawData(ImDrawData *data, VkCommandBuffer, VkPipeline) {
    assert(data && data->Valid && data->TotalVtxCount>0);
    assert(!ImGui::GetIO().WantCaptureMouse && !ImGui::GetIO().WantCaptureKeyboard);
    assert(ImGui::GetIO().ConfigFlags & ImGuiConfigFlags_NoMouse);
    assert(ImGui::GetIO().ConfigFlags & ImGuiConfigFlags_NoKeyboard);
    assert(ImGui::GetIO().IniFilename==nullptr && ImGui::GetIO().LogFilename==nullptr);
    for (int i=0;i<data->CmdListsCount;i++) for (const ImDrawVert &v:data->CmdLists[i]->VtxBuffer) {
        assert(v.pos.x>=-0.01f && v.pos.y>=-0.01f && v.pos.x<=target_w+0.01f && v.pos.y<=target_h+0.01f);
    }
    rendered_vertices=data->TotalVtxCount;render_calls++;
}

static void prepare(ImGuiContext *ctx,float w,float h) {
    ImGui::SetCurrentContext(ctx);ImGuiIO &io=ImGui::GetIO();
    io.DisplaySize={w,h};io.DeltaTime=1.f/60;io.IniFilename=nullptr;io.LogFilename=nullptr;
    io.ConfigFlags=ImGuiConfigFlags_NoMouse|ImGuiConfigFlags_NoKeyboard|ImGuiConfigFlags_NoMouseCursorChange;
    if (!io.Fonts->IsBuilt()) { ImFontConfig cfg{};cfg.SizePixels=48;io.Fonts->AddFontDefault(&cfg);unsigned char *p;int x,y;io.Fonts->GetTexDataAsRGBA32(&p,&x,&y);io.Fonts->SetTexID(1); }
}
static void layout() {
    ImGuiContext *ctx=ImGui::CreateContext();
    const unsigned sizes[][2]={{1280,720},{1280,800},{1920,1080},{2560,1440},{3360,1440},{3440,1440},{5120,1440},{7680,2160},{3840,2160},{64,32}};
    for (const auto &size:sizes) {
        prepare(ctx,(float)size[0],(float)size[1]);ImGui::NewFrame();
        auto shape=fps_overlay_detail::draw(true,true,120.,(float)size[0],(float)size[1]);
        assert(shape.visible && !strcmp(shape.text,"120 FPS"));
        assert(shape.minimum.x>=0 && shape.minimum.y>=0 && shape.maximum.x<=size[0] && shape.maximum.y<=size[1]);
        ImGui::Render();assert(ImGui::GetDrawData()->TotalVtxCount>0);
    }
    prepare(ctx,1280,720);ImGui::NewFrame();
    auto warm=fps_overlay_detail::draw(true,false,0,1280,720);assert(warm.visible && !strcmp(warm.text,"-- FPS"));
    ImGui::Render();
    prepare(ctx,1280,720);ImGui::NewFrame();
    auto invalid=fps_overlay_detail::draw(true,true,NAN,1280,720);assert(invalid.visible && !strcmp(invalid.text,"-- FPS"));
    ImGui::Render();ImGui::DestroyContext(ctx);
}
static void disabled() {
    assert(ImGui::GetCurrentContext()==nullptr);g_settings.show_fps_overlay=false;
    fps_overlay_reset();fps_overlay_frame(1);assert(!fps_overlay_visible());
    fps_overlay_render(nullptr,1280,720);assert(!backend_starts && !render_calls && !ImGui::GetCurrentContext());
    ImGuiContext *ctx=ImGui::CreateContext();prepare(ctx,1280,720);ImGui::NewFrame();
    assert(!fps_overlay_detail::draw(false,true,60,1280,720).visible);
    assert(!fps_overlay_detail::draw(true,true,60,0,720).visible);
    ImGui::Render();assert(ImGui::GetDrawData()->TotalVtxCount==0);ImGui::DestroyContext(ctx);
}
static void runtime() {
    ImGuiContext *previous=ImGui::CreateContext();g_settings.show_fps_overlay=true;fps_overlay_reset();
    assert(!fps_overlay_visible());fps_overlay_render(nullptr,1280,720);assert(!backend_starts);
    fps_overlay_frame(1);assert(fps_overlay_visible());target_w=1280;target_h=720;
    fps_overlay_render(nullptr,1280,720);assert(backend_starts==1 && render_calls==1 && rendered_vertices>0);
    assert(ImGui::GetCurrentContext()==previous);
    for (unsigned i=1;i<=60;i++)fps_overlay_frame(1+uint64_t(i)*1000000000ull/60);
    clock_ns+=1000000000;target_w=3440;target_h=1440;fps_overlay_render(nullptr,3440,1440);
    assert(render_calls==2 && backend_starts==1 && ImGui::GetCurrentContext()==previous);
    g_settings.show_fps_overlay=false;fps_overlay_frame(clock_ns);assert(!fps_overlay_visible());
    fps_overlay_render(nullptr,3440,1440);assert(render_calls==2 && ImGui::GetCurrentContext()==previous);
    g_settings.show_fps_overlay=true;fps_overlay_reset();assert(!fps_overlay_visible());
    fps_overlay_frame(clock_ns+1);assert(fps_overlay_visible());fps_overlay_render(nullptr,3440,1440);assert(render_calls==3);
    ImGui::DestroyContext(previous);ImGui::SetCurrentContext(nullptr);
    clock_ns+=1000000000;fps_overlay_render(nullptr,3440,1440);assert(render_calls==4 && ImGui::GetCurrentContext()==nullptr);
}
static void failure(bool fonts) {
    ImGuiContext *previous=ImGui::CreateContext();
    fail_backend=!fonts;fail_fonts=fonts;g_settings.show_fps_overlay=true;
    fps_overlay_frame(1);assert(fps_overlay_visible());
    fps_overlay_render(nullptr,1280,720);
    assert(backend_starts==1 && backend_stops==(fonts?1u:0u) && !render_calls && !fps_overlay_visible());
    assert(ImGui::GetCurrentContext()==previous);
    fps_overlay_render(nullptr,1280,720);assert(backend_starts==1 && !render_calls);
    ImGui::DestroyContext(previous);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"layout"))layout();else if(!strcmp(argv[1],"disabled"))disabled();else if(!strcmp(argv[1],"runtime"))runtime();
    else if(!strcmp(argv[1],"init-failure"))failure(false);else if(!strcmp(argv[1],"font-failure"))failure(true);else assert(!"unknown scenario");
    puts("native FPS overlay UI: PASS");return 0;
}
