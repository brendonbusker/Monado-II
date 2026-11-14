// [XCDE] LINUX-094: actual launcher configuration, no SDL initialization or UI.
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <cstdio>
#include <cstdlib>
#define main launcher_main_under_test
#include "../../Monado_Linux/tools/launcher/launcher.cpp"
#undef main
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); abort(); } } while (0)

static void write_config(const std::string &text) {
    FILE *file=fopen(path("xcde.ini").c_str(),"wb"); CHECK(file);
    CHECK(fputs(text.c_str(),file)>=0); CHECK(!fclose(file));
}
static std::string contents() {
    FILE *file=fopen(path("xcde.ini").c_str(),"rb"); CHECK(file);
    std::string text; char buffer[2048]; size_t length;
    while ((length=fread(buffer,1,sizeof buffer,file))) text.append(buffer,length);
    CHECK(!ferror(file)); CHECK(!fclose(file)); return text;
}
static void reset() { g=Cfg{}; g_custom.clear(); g_extra.clear(); g_mods.clear(); g.icons=1; }
static void check_serialized(bool overlay,bool title) {
    const std::string text=contents(), key="show_fps_overlay = ", line=key+(overlay?"1\n":"0\n");
    size_t at=text.find(line); CHECK(at!=std::string::npos && text.find(key,at+line.size())==std::string::npos);
    CHECK(text.find(std::string("show_fps = ")+(title?"1\n":"0\n"))!=std::string::npos);
}
int main(int argc,char **argv) {
    CHECK(argc==2 && mkdir(argv[1],0700)==0); g_root=argv[1];
    CHECK(!SDL_WasInit(0) && !SDL_GetCurrentVideoDriver());
    CHECK(!Cfg{}.show_fps_overlay); g.show_fps_overlay=true; load(); CHECK(!g.show_fps_overlay);
    const char *values[]={"0","1","true","false","","2","-1","yes","TRUE","1junk"};
    for (unsigned i=0;i<sizeof values/sizeof *values;++i) for (int title=0;title<2;++title) {
        reset(); g.show_fps_overlay=true;
        std::string text=std::string("show_fps = ")+(title?"1\n":"0\n")+"show_fps_overlay = "+values[i]+"\nfps = 75\ncustom_key = kept\n";
        write_config(text); load(); bool expected=i==1 || i==2;
        CHECK(g.show_fps_overlay==expected && g.show_fps==title);
        CHECK(!g_extra.count("show_fps_overlay") && !g_custom.count("show_fps_overlay"));
        CHECK(contents()==text && g_custom.at("fps")=="75"); CHECK(save()); check_serialized(expected,title);
        reset(); load(); CHECK(g.show_fps_overlay==expected && g.show_fps==title);
        CHECK(g_custom.at("fps")=="75" && g_extra.at("custom_key")=="kept");
    }
    write_config("show_fps = 1\n"); load(); CHECK(g.show_fps && !g.show_fps_overlay);
    write_config("show_fps_overlay = 0\nshow_fps_overlay = 1\n"); load(); CHECK(g.show_fps_overlay);
    write_config("show_fps_overlay = 1\nshow_fps_overlay = invalid\n"); load(); CHECK(!g.show_fps_overlay);
    write_config("show_fps_overlay = 1\n"); load(); CHECK(g.show_fps_overlay);
    write_config("show_fps = 0\n"); reload_after_game(); CHECK(!g.show_fps_overlay && !g.show_fps);
    CHECK(remove(path("xcde.ini").c_str())==0); g.show_fps_overlay=true; load(); CHECK(!g.show_fps_overlay);
    g.ui_lang=1; CHECK(!strcmp(T("Mostrar FPS en pantalla"),"Show FPS on screen"));
    g.ui_lang=0; CHECK(!strcmp(T("Mostrar FPS en pantalla"),"Mostrar FPS en pantalla"));
    CHECK(!SDL_WasInit(0) && !SDL_GetCurrentVideoDriver());
    puts("FPS overlay launcher config: defaults, title independence, roundtrip, extras/custom preservation, reload and translations PASS");
}
