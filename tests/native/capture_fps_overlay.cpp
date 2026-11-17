// [XCDE] LINUX-124: actual authored HUD capture to an offscreen software surface.
// No window, game files, game process, configuration or save profile is used.
#include "imgui.h"
#include "imgui_impl_sdlrenderer3.h"
#include "fps_fonts.h"
#include "../../Monado_Linux/runtime/ui/fps_overlay_draw.h"
#include <SDL3/SDL.h>
#include <cstdio>
#include <cstdlib>
#include <filesystem>

int main(int argc,char **argv) {
    if(argc!=5)return 2;
    const int w=atoi(argv[2]),h=atoi(argv[3]),mode=atoi(argv[4]);
    if(w<64||w>7680||h<32||h>4320||mode<0||mode>3||std::filesystem::exists(argv[1]))return 2;
    if(!SDL_Init(0))return 3;
    auto *surface=SDL_CreateSurface(w,h,SDL_PIXELFORMAT_RGBA8888);
    if(!surface)return 3;
    auto *renderer=SDL_CreateSoftwareRenderer(surface);
    if(!renderer)return 3;
    ImGui::CreateContext();auto &io=ImGui::GetIO();
    io.IniFilename=nullptr;io.LogFilename=nullptr;io.DisplaySize=ImVec2(w,h);io.DeltaTime=1.f/60;
    io.ConfigFlags=ImGuiConfigFlags_NoMouse|ImGuiConfigFlags_NoKeyboard|ImGuiConfigFlags_NoMouseCursorChange;
    ImFontConfig cfg{};cfg.FontDataOwnedByAtlas=false;
    static const ImWchar glyphs[]={0x20,0xff,0};
    auto *labels=io.Fonts->AddFontFromMemoryTTF((void*)fps_font_sans,sizeof fps_font_sans,32,&cfg,glyphs);
    auto *numbers=io.Fonts->AddFontFromMemoryTTF((void*)fps_font_serif,sizeof fps_font_serif,72,&cfg,glyphs);
    if(!ImGui_ImplSDLRenderer3_Init(renderer))return 3;
    ImGui_ImplSDLRenderer3_NewFrame();ImGui::NewFrame();
    fps_overlay_detail::Rates rates;rates.game_ready=true;rates.game=120;
    rates.generation=true;rates.output_ready=true;rates.output=180;
    rates.generated_ready=true;rates.generated=60;
    auto result=fps_overlay_detail::draw(mode,rates,w,h,numbers,labels);
    ImGui::Render();
    SDL_SetRenderDrawColor(renderer,52,83,88,255);SDL_RenderClear(renderer);
    // A purely authored neutral backdrop gives text contrast without game data.
    for(int y=0;y<h;y+=32){SDL_SetRenderDrawColor(renderer,Uint8(52+y*35/h),Uint8(83+y*32/h),Uint8(88+y*20/h),255);SDL_FRect stripe={0.f,float(y),float(w),32.f};SDL_RenderFillRect(renderer,&stripe);}
    ImGui_ImplSDLRenderer3_RenderDrawData(ImGui::GetDrawData(),renderer);
    // SDL batches software rendering too; flush before reading the surface.
    if(!SDL_FlushRenderer(renderer))return 3;
    const bool saved=SDL_SaveBMP(surface,argv[1]);
    printf("mode=%d visible=%d bounds=%.2f,%.2f..%.2f,%.2f atlas=%dx%d vertices=%d saved=%d\n",mode,result.visible,
        result.minimum.x,result.minimum.y,result.maximum.x,result.maximum.y,io.Fonts->TexWidth,io.Fonts->TexHeight,
        ImGui::GetDrawData()->TotalVtxCount,saved);
    ImGui_ImplSDLRenderer3_Shutdown();ImGui::DestroyContext();SDL_DestroyRenderer(renderer);SDL_DestroySurface(surface);SDL_Quit();
    return saved?0:4;
}
