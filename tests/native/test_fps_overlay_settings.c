// [XCDE] LINUX-094: actual runtime opt-in persistence, authored config only.
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../Monado_Linux/runtime/settings.h"
#include "../../Monado_Linux/runtime/input_bind.h"

bool bind_settings_load(const char *key, const char *value) { (void)key; (void)value; return false; }
void bind_settings_save(FILE *file) { fputs("bind_key_a = Return\n", file); }

static const char *ini;
static void write_config(const char *text) {
    FILE *file=fopen(ini,"w"); assert(file);
    assert(fputs(text,file)>=0); assert(!fclose(file));
}
static void check_serialized(bool overlay, bool title) {
    FILE *file=fopen(ini,"r"); assert(file);
    char text[8192]; size_t length=fread(text,1,sizeof text-1,file);
    assert(!ferror(file) && length<sizeof text-1); text[length]=0; assert(!fclose(file));
    const char *key="show_fps_overlay = "; char line[64];
    snprintf(line,sizeof line,"%s%d\n",key,overlay);
    const char *at=strstr(text,line); assert(at && !strstr(at+strlen(line),key));
    snprintf(line,sizeof line,"show_fps = %d\n",title); assert(strstr(text,line));
}
int main(int argc,char **argv) {
    assert(argc==2); ini=argv[1]; assert(!setenv("XCDE_INI",ini,1));
    assert(!g_settings.show_fps_overlay); g_settings.show_fps_overlay=true;
    remove(ini); settings_load(); assert(!g_settings.show_fps_overlay);
    const char *values[]={"0","1","true","false","","2","-1","yes","TRUE","1junk"};
    for (unsigned i=0;i<sizeof values/sizeof *values;++i) {
        for (int title=0;title<2;++title) {
            char text[256]; snprintf(text,sizeof text,"show_fps = %d\nshow_fps_overlay = %s\nfps = 144\nvolume = 37\n",title,values[i]);
            write_config(text); g_settings.show_fps_overlay=true; settings_load();
            bool expected=i==1 || i==2;
            assert(g_settings.show_fps_overlay==expected && g_settings.show_fps==title);
            assert(g_settings.fps==144 && g_settings.volume>0.369f && g_settings.volume<0.371f);
            settings_save(); check_serialized(expected,title);
            g_settings.show_fps_overlay=!expected; g_settings.show_fps=!title;
            settings_load(); assert(g_settings.show_fps_overlay==expected && g_settings.show_fps==title);
        }
    }
    write_config("show_fps = 1\n"); settings_load(); assert(g_settings.show_fps && !g_settings.show_fps_overlay);
    write_config("show_fps_overlay = 0\nshow_fps_overlay = 1\nshow_fps = 0\n"); settings_load();
    assert(g_settings.show_fps_overlay && !g_settings.show_fps);
    write_config("show_fps_overlay = 1\nshow_fps_overlay = invalid\n"); settings_load(); assert(!g_settings.show_fps_overlay);
    write_config("show_fps_overlay = 1\n"); settings_load(); assert(g_settings.show_fps_overlay);
    remove(ini); settings_load(); assert(!g_settings.show_fps_overlay);
    puts("FPS overlay runtime config: defaults, independent title option, strict values, reload and roundtrip PASS");
    return 0;
}
