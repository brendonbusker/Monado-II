// [XCDE] LINUX-094: actual FPS UI with authored clocks/backend seams, no window/game.
#include "imgui.h"
#include "fps_fonts.h"
#include "imgui_impl_vulkan.h"
#include "../../Monado_Linux/runtime/ui/fps_overlay_draw.h"
#include "../../Monado_Linux/runtime/settings.h"
#include "../../Monado_Linux/runtime/nvn/vulkan/present_observer_linux.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

Settings g_settings{};
static uint64_t clock_ns = 1;
static unsigned backend_starts, render_calls;
static bool fail_backend, fail_fonts;
static unsigned backend_stops;
static int rendered_vertices;
static float target_w, target_h;
static bool driver_available, driver_ready;
static void show(bool enabled, int mode = FPS_OVERLAY_COMPACT) {
    g_settings.show_fps_overlay = enabled;
    g_settings.fps_overlay_mode = enabled ? mode : FPS_OVERLAY_OFF;
}
static double driver_rate;
static unsigned driver_reads;

extern "C" void fps_overlay_frame(uint64_t);
extern "C" void fps_overlay_reset(void);
extern "C" void fps_overlay_generation(bool,bool);
extern "C" void fps_overlay_present(uint64_t,bool,bool);
extern "C" bool fps_overlay_visible(void);
extern "C" void fps_overlay_render(void *, uint32_t, uint32_t);
extern "C" void fps_overlay_diagnostics(uint64_t,unsigned,bool);
extern "C" Uint64 SDL_GetTicksNS(void) { return clock_ns; }
extern "C" bool vk_imgui_backend_init(void) { backend_starts++; return !fail_backend; }
extern "C" void vk_imgui_backend_shutdown(void) { backend_stops++; }
extern "C" bool vk_external_fps(double *value,bool *ready) {
    *value=driver_rate;*ready=driver_ready;return driver_available;
}
extern "C" bool vk_external_fps_snapshot(MonadoPresentObserverSnapshot *snapshot,uint64_t *now) {
    ++driver_reads;*snapshot={};*now=UINT64_C(1000000000000)+clock_ns;
    if(!driver_available)return false;
    snapshot->abi=MONADO_PRESENT_OBSERVER_ABI;snapshot->bytes=sizeof *snapshot;
    snapshot->flags=MONADO_PRESENT_OBSERVER_ATTACHED|(driver_ready?MONADO_PRESENT_OBSERVER_READY:0);
    snapshot->accepted=1234;snapshot->failed=7;snapshot->window_ns=500000000;
    snapshot->last_accepted_ns=*now-5;snapshot->output_fps=driver_rate;
    return true;
}
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
    if (!io.Fonts->IsBuilt()) {
        ImFontConfig cfg{};cfg.SizePixels=72;cfg.FontDataOwnedByAtlas=false;
        static const ImWchar glyphs[]={0x20,0xff,0};
        io.Fonts->AddFontFromMemoryTTF((void *)fps_font_sans,sizeof fps_font_sans,32,&cfg,glyphs);
        io.Fonts->AddFontFromMemoryTTF((void *)fps_font_serif,sizeof fps_font_serif,72,&cfg,glyphs);
        unsigned char *p;int x,y;io.Fonts->GetTexDataAsRGBA32(&p,&x,&y);io.Fonts->SetTexID(1);
    }
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
static void dual_layout() {
    ImGuiContext *ctx=ImGui::CreateContext();
    const unsigned sizes[][2]={{1280,720},{1280,800},{2560,1440},{3440,1440},{5120,1440},{3840,2160},{64,32}};
    for(const auto &size:sizes)for(unsigned mode=0;mode<10;mode++) {
        prepare(ctx,(float)size[0],(float)size[1]);ImGui::NewFrame();
        fps_overlay_detail::Rates rates;
        rates.generation=true;rates.external=mode==2||(mode>=4&&mode<=6);rates.game_ready=mode!=0;rates.game=90;
        rates.external_measured=mode>=4&&mode<=6;
        rates.output_ready=mode!=0&&mode!=5;rates.output=mode==3||mode==6?NAN:mode>=4&&mode<=6?228:180;
        rates.generated_ready=rates.output_ready;rates.generated=mode==7?200:mode==8?NAN:mode==9?-1:90;
        auto shape=fps_overlay_detail::draw(true,rates,(float)size[0],(float)size[1]);
        const char *expected=mode==0?"Game -- FPS\nOutput -- FPS (submitted)\nGenerated -- FPS":mode==2?"Game 90 FPS\nOutput external (unavailable)":
            mode==3?"Game 90 FPS\nOutput -- FPS (submitted)\nGenerated -- FPS":mode==4?"Game 90 FPS\nOutput 228 FPS (driver submitted)\nGenerated unavailable":mode>=5&&mode<=6?"Game 90 FPS\nOutput -- FPS (driver submitted)\nGenerated unavailable":mode>=7?"Game 90 FPS\nOutput 180 FPS (submitted)\nGenerated -- FPS":"Game 90 FPS\nOutput 180 FPS (submitted)\nGenerated 90 FPS";
        assert(shape.visible && !strcmp(shape.text,expected));
        assert(shape.minimum.x>=0&&shape.minimum.y>=0&&shape.maximum.x<=size[0]&&shape.maximum.y<=size[1]);
        ImGui::Render();assert(ImGui::GetDrawData()->TotalVtxCount>0);
    }
    ImGui::DestroyContext(ctx);
}

static void modes() {
    ImGuiContext *ctx=ImGui::CreateContext();
    const unsigned sizes[][2]={{1280,720},{1280,800},{1920,1080},{2560,1440},{3440,1440},{5120,1440},{3840,2160},{64,32}};
    for (const auto &extent:sizes) for (int mode=0;mode<=3;mode++) for (int external=0;external<=2;external++) {
        prepare(ctx,extent[0],extent[1]);ImGui::NewFrame();
        fps_overlay_detail::Rates r;r.game_ready=true;r.game=120;r.generation=true;
        r.output_ready=true;r.output=180;r.generated_ready=true;r.generated=60;
        r.external=external!=0;r.external_measured=external==2;
        auto p=fps_overlay_detail::draw(mode,r,extent[0],extent[1],
                                       ImGui::GetIO().Fonts->Fonts[1],ImGui::GetIO().Fonts->Fonts[0]);
        ImGui::Render();auto *draw=ImGui::GetDrawData();
        if(mode==0){assert(!p.visible && draw->TotalVtxCount==0);continue;}
        assert(p.visible && p.maximum.x<=extent[0] && p.maximum.y<=extent[1]);
        if(mode==1) {assert(!strcmp(p.text,"120"));assert(draw->TotalVtxCount==3*4*2);}
        for(int i=0;i<draw->CmdListsCount;i++)for(const auto &v:draw->CmdLists[i]->VtxBuffer)
            assert(v.pos.x>=0&&v.pos.y>=0&&v.pos.x<=extent[0]&&v.pos.y<=extent[1]);
    }
    // Ordinary three/four digit changes never shift a panel's column boundaries.
    for(int mode=2;mode<=3;mode++) {
        float width=0;
        for(double value:{30.,99.,120.,999.}) {
            prepare(ctx,1920,1080);ImGui::NewFrame();
            fps_overlay_detail::Rates r;r.game_ready=true;r.game=value;
            auto p=fps_overlay_detail::draw(mode,r,1920,1080,
                ImGui::GetIO().Fonts->Fonts[1],ImGui::GetIO().Fonts->Fonts[0]);
            if(width)assert(fabsf(width-(p.maximum.x-p.minimum.x))<0.01f);
            width=p.maximum.x-p.minimum.x;ImGui::Render();
        }
    }
    prepare(ctx,1920,1080);ImGui::NewFrame();fps_overlay_detail::Rates r;
    assert(!fps_overlay_detail::draw(99,r,1920,1080).visible);
    ImGui::Render();ImGui::DestroyContext(ctx);
}

static void output_lifecycle() {
    show(true);fps_overlay_reset();fps_overlay_generation(true,false);
    fps_overlay_frame(1);target_w=1280;target_h=720;
    for(unsigned i=0;i<=180;i++) {
        if(i%2==0)fps_overlay_frame(1+uint64_t(i)*1000000000ull/180);
        fps_overlay_present(1+uint64_t(i)*1000000000ull/180,i%2!=0,false);
    }
    clock_ns=1000000001;fps_overlay_render(nullptr,1280,720);assert(render_calls==1);
    int dual_vertices=rendered_vertices;
    fps_overlay_generation(false,false);fps_overlay_render(nullptr,1280,720);
    assert(render_calls==2 && rendered_vertices<dual_vertices);
    // External generation never displays an invented doubled value.
    fps_overlay_generation(true,true);fps_overlay_render(nullptr,1280,720);assert(render_calls==3);
    // A real downstream reading is independent of Game*2 and can be unavailable.
    driver_available=driver_ready=true;driver_rate=227.4;
    g_settings.frame_gen_smooth_motion=true;
    fps_overlay_diagnostics(clock_ns,2,false);
    fps_overlay_render(nullptr,1280,720);assert(render_calls==4);
    driver_available=false;
    g_settings.frame_gen_smooth_motion=false;
    fps_overlay_generation(true,false); // integrated re-enable starts fresh output window
    fps_overlay_present(clock_ns+1,true,true); // invalid classification ignored safely
    fps_overlay_present(clock_ns+2,false,true);fps_overlay_render(nullptr,1280,720);assert(render_calls==5);
    show(false);fps_overlay_frame(clock_ns+3);fps_overlay_present(clock_ns+4,true,false);
    fps_overlay_render(nullptr,1280,720);assert(!fps_overlay_visible()&&render_calls==5);
    show(true);fps_overlay_generation(true,false);fps_overlay_frame(clock_ns+5);
    fps_overlay_render(nullptr,1280,720);assert(render_calls==6);
}
static void telemetry(bool precompile,bool fsr) {
    if(precompile)assert(setenv("XCDE_PRECOMPILING","1",1)==0);
    assert(setenv("MONADO_RUN_ID","0123456789abcdef0123456789abcdef",1)==0);
    show(false);g_settings.frame_gen=fsr;g_settings.frame_gen_smooth_motion=!fsr;
    fps_overlay_reset();fps_overlay_generation(true,!fsr);
    driver_available=true;driver_ready=false;driver_rate=0;
    const unsigned output_hz=fsr?180:60;
    for(unsigned i=0;i<=output_hz*3;i++) {
        clock_ns=1+uint64_t(i)*1000000000ull/output_hz;
        if(!fsr||i%2==0)fps_overlay_frame(clock_ns);
        if(fsr)fps_overlay_present(clock_ns,i%2!=0,false);
        if(i>output_hz) {driver_ready=true;driver_rate=227.4;}
        if(!fsr||i%2==0)fps_overlay_diagnostics(clock_ns,fsr?1:2,true);
        fps_overlay_render(nullptr,1280,720);
    }
    assert(!backend_starts&&!render_calls&&!ImGui::GetCurrentContext()&&!fps_overlay_visible());
    assert(driver_reads==(precompile||fsr?0u:2u));
    // Reset and ordinary fallback do not reset the independent two-second log
    // clock. FSR's movie-like path measures native output, not invented FG.
    if(fsr&&!precompile) {
        fps_overlay_generation(false,false);
        for(unsigned i=0;i<=240;i++) {
            clock_ns=3000000002ull+uint64_t(i)*1000000000ull/120;
            fps_overlay_frame(clock_ns);fps_overlay_present(clock_ns,false,false);
            fps_overlay_diagnostics(clock_ns,1,false);
        }
    } else {
        fps_overlay_reset();fps_overlay_generation(true,!fsr);fps_overlay_frame(clock_ns+1);
        fps_overlay_diagnostics(clock_ns+1,fsr?1:2,false);
        assert(driver_reads==(precompile||fsr?0u:2u));
    }
    unsigned reads=driver_reads;
    fps_overlay_diagnostics(clock_ns+9000000000ull,0,false);assert(driver_reads==reads);
}
static void disabled() {
    assert(ImGui::GetCurrentContext()==nullptr);show(false);
    fps_overlay_reset();fps_overlay_frame(1);assert(!fps_overlay_visible());
    fps_overlay_render(nullptr,1280,720);assert(!backend_starts && !render_calls && !ImGui::GetCurrentContext());
    ImGuiContext *ctx=ImGui::CreateContext();prepare(ctx,1280,720);ImGui::NewFrame();
    assert(!fps_overlay_detail::draw(false,true,60,1280,720).visible);
    assert(!fps_overlay_detail::draw(true,true,60,0,720).visible);
    ImGui::Render();assert(ImGui::GetDrawData()->TotalVtxCount==0);ImGui::DestroyContext(ctx);
}
static void runtime() {
    ImGuiContext *previous=ImGui::CreateContext();show(true);fps_overlay_reset();
    assert(!fps_overlay_visible());fps_overlay_render(nullptr,1280,720);assert(!backend_starts);
    fps_overlay_frame(1);assert(fps_overlay_visible());target_w=1280;target_h=720;
    fps_overlay_render(nullptr,1280,720);assert(backend_starts==1 && render_calls==1 && rendered_vertices>0);
    assert(ImGui::GetCurrentContext()==previous);
    for (unsigned i=1;i<=60;i++)fps_overlay_frame(1+uint64_t(i)*1000000000ull/60);
    clock_ns+=1000000000;target_w=3440;target_h=1440;fps_overlay_render(nullptr,3440,1440);
    assert(render_calls==2 && backend_starts==1 && ImGui::GetCurrentContext()==previous);
    for (int mode : {FPS_OVERLAY_NUMBER,FPS_OVERLAY_DETAILED,FPS_OVERLAY_COMPACT}) {
        show(true,mode);fps_overlay_render(nullptr,3440,1440);
        assert(backend_starts==1 && ImGui::GetCurrentContext()==previous);
    }
    assert(render_calls==5);render_calls=2;
    show(false);fps_overlay_frame(clock_ns);assert(!fps_overlay_visible());
    fps_overlay_render(nullptr,3440,1440);assert(render_calls==2 && ImGui::GetCurrentContext()==previous);
    show(true);fps_overlay_reset();assert(!fps_overlay_visible());
    fps_overlay_frame(clock_ns+1);assert(fps_overlay_visible());fps_overlay_render(nullptr,3440,1440);assert(render_calls==3);
    ImGui::DestroyContext(previous);ImGui::SetCurrentContext(nullptr);
    clock_ns+=1000000000;fps_overlay_render(nullptr,3440,1440);assert(render_calls==4 && ImGui::GetCurrentContext()==nullptr);
}
static void failure(bool fonts) {
    ImGuiContext *previous=ImGui::CreateContext();
    fail_backend=!fonts;fail_fonts=fonts;show(true);
    fps_overlay_frame(1);assert(fps_overlay_visible());
    fps_overlay_render(nullptr,1280,720);
    assert(backend_starts==1 && backend_stops==(fonts?1u:0u) && !render_calls && !fps_overlay_visible());
    assert(ImGui::GetCurrentContext()==previous);
    fps_overlay_render(nullptr,1280,720);assert(backend_starts==1 && !render_calls);
    ImGui::DestroyContext(previous);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"modes"))modes();else if(!strcmp(argv[1],"layout"))layout();else if(!strcmp(argv[1],"dual-layout"))dual_layout();else if(!strcmp(argv[1],"output-lifecycle"))output_lifecycle();else if(!strcmp(argv[1],"disabled"))disabled();else if(!strcmp(argv[1],"runtime"))runtime();
    else if(!strcmp(argv[1],"init-failure"))failure(false);else if(!strcmp(argv[1],"font-failure"))failure(true);
    else if(!strcmp(argv[1],"telemetry-nvidia"))telemetry(false,false);
    else if(!strcmp(argv[1],"telemetry-fsr"))telemetry(false,true);
    else if(!strcmp(argv[1],"telemetry-precompile"))telemetry(true,false);
    else assert(!"unknown scenario");
    puts("native FPS overlay UI: PASS");return 0;
}
