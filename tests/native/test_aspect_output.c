// [XCDE] LINUX-089: actual config/output/canvas integration, authored values.
// No guest, renderer, game files or user profile. Only binding serialization is
// an external boundary; settings, aspect publication and output sizing are real.
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "../../Monado_Linux/runtime/settings.h"
#include "../../Monado_Linux/runtime/host/xcde_aspect.h"
#include "../../Monado_Linux/runtime/nvn/output_scale.h"
#include "../../Monado_Linux/runtime/nvn/aspect_canvas.h"

bool bind_settings_load(const char *key, const char *value) { (void)key; (void)value; return false; }
void bind_settings_save(FILE *file) { (void)file; }
extern bool widescreen_allowed(void);
extern void widescreen_set_factor(float factor);

static Settings defaults;
static void reset(void) {
    g_settings = defaults;
    g_window_w = 1280; g_window_h = 720;
    output_scale_set_base(1280, 720);
    widescreen_set_factor(1.0f);
}
static void put(const char *text) {
    FILE *file = fopen("aspect.ini", "w"); assert(file);
    assert(fputs(text, file) >= 0); assert(fclose(file) == 0);
}
static char *read_all(void) {
    FILE *file = fopen("aspect.ini", "rb"); assert(file);
    assert(fseek(file, 0, SEEK_END) == 0); long size = ftell(file); assert(size >= 0);
    rewind(file); char *text = malloc((size_t)size + 1); assert(text);
    assert(fread(text, 1, (size_t)size, file) == (size_t)size); text[size] = 0;
    assert(fclose(file) == 0); return text;
}
static void config_defaults(void) {
    assert(g_settings.aspect == ASPECT_ORIGINAL && !widescreen_allowed());
    g_settings.aspect = ASPECT_UNLOCKED;
    settings_load(); assert(g_settings.aspect == ASPECT_ORIGINAL && !widescreen_allowed());
    static const char *invalid[] = {"", "original", "NATIVE", "nativejunk", "1", "0", "true", "16:11", "21/9", "32:09"};
    for (unsigned i = 0; i < sizeof invalid / sizeof *invalid; ++i) {
        char text[128]; snprintf(text, sizeof text, "aspect_ratio = %s\n", invalid[i]); put(text);
        g_settings.aspect = ASPECT_UNLOCKED; settings_load();
        assert(g_settings.aspect == ASPECT_ORIGINAL && !widescreen_allowed());
        char *after = read_all(); assert(strcmp(after, text) == 0); free(after);
    }
    put("fps = 120\n"); g_settings.aspect = ASPECT_UNLOCKED; settings_load();
    assert(g_settings.aspect == ASPECT_ORIGINAL && g_settings.fps == 120);
    put("aspect_ratio = native\n"); settings_load(); assert(widescreen_allowed());
    assert(unlink("aspect.ini") == 0); settings_load(); assert(!widescreen_allowed());
    // Hidden test sessions without an explicit config must never inherit opt-in.
    assert(unsetenv("XCDE_INI") == 0); assert(setenv("LARECOMP_HIDDEN", "1", 1) == 0);
    g_settings.aspect = ASPECT_UNLOCKED; settings_load(); assert(!widescreen_allowed());
    assert(unsetenv("LARECOMP_HIDDEN") == 0);
}
static void config_roundtrip(void) {
    static const char *modes[] = {"native", "original", "16:10", "21:9", "32:9"};
    for (unsigned i = 0; i < sizeof modes / sizeof *modes; ++i) {
        char text[200]; snprintf(text, sizeof text,
            "\xef\xbb\xbf# authored settings\r\n aspect_ratio = %s \r\nfps = 120\nvolume = 73\n", modes[i]);
        put(text); settings_load();
        int expected = (int)i;
        assert(g_settings.aspect == expected && g_settings.fps == 120);
        assert(fabsf(g_settings.volume - .73f) < .000001f);
        settings_save(); char *saved = read_all();
        char needle[80]; snprintf(needle, sizeof needle, "aspect_ratio = %s\n", modes[i]);
        char *at = strstr(saved, needle); assert(at && strstr(at + strlen(needle), "aspect_ratio = ") == NULL);
        reset(); settings_load(); assert(g_settings.aspect == expected && g_settings.fps == 120);
        assert(fabsf(g_settings.volume - .73f) < .000001f); free(saved);
    }
    put("aspect_ratio = native\naspect_ratio = nonsense\n"); settings_load(); assert(!widescreen_allowed());
    put("aspect_ratio = nonsense\naspect_ratio = native\n"); settings_load(); assert(widescreen_allowed());
}
static OutScale scale(double w, double h) {
    OutScale result;
    output_scale(w, h, widescreen_allowed(), 1.0, -1.0, &result);
    widescreen_set_factor((float)result.shape);
    return result;
}
static void exact(const OutScale *value, const double expected[7]) {
    const double actual[] = {value->sx, value->sy, value->shape, value->vx, value->vy, value->vw, value->vh};
    for (unsigned i = 0; i < 7; ++i) assert(memcmp(&actual[i], &expected[i], sizeof(double)) == 0);
}
static void original(void) {
    struct Sample { double w, h; int mode; double values[7]; };
    // Authored 018 original-mode viewport goldens; exact double values, not a
    // second implementation of the scaling algorithm.
    static const struct Sample samples[] = {
        {2560,1440,RES_MATCH,{2,2,1,0,0,2560,1440}},
        {3440,1440,RES_MATCH,{2,2,1,440,0,2560,1440}},
        {1280,800,RES_MATCH,{1,1,1,0,40,1280,720}},
        {5120,1440,RES_MATCH,{2,2,1,1280,0,2560,1440}},
        {3440,1440,RES_Q50,{1,1,1,440,0,2560,1440}},
        {3440,1440,2,{2,2,1,440,0,2560,1440}},
    };
    reset();
    for (unsigned i = 0; i < sizeof samples / sizeof *samples; ++i) {
        g_settings.res_mode = samples[i].mode;
        OutScale out = scale(samples[i].w, samples[i].h); exact(&out, samples[i].values);
        assert(!xcde_aspect_active());
    }
    g_settings.upscaler = UPSCALE_DLSS; g_settings.upscale_quality = UQ_NATIVE;
    g_settings.res_mode = RES_Q50;
    OutScale odd = scale(1304,744);
    const double expected[] = {1304.0/1280.0,734.0/720.0,1,0,5.25,1304,733.5};
    exact(&odd, expected);
}
static void native_windows(void) {
    static const double windows[][2] = {{1280,800},{1920,1200},{3360,1440},{3440,1440},{5120,1440},{7680,2160},{2560,1440}};
    for (unsigned base = 0; base < 2; ++base) {
        reset(); g_settings.aspect = ASPECT_UNLOCKED;
        const int bw = base ? 1920 : 1280, bh = base ? 1080 : 720;
        output_scale_set_base(bw, bh);
        for (unsigned i = 0; i < sizeof windows / sizeof *windows; ++i) {
            OutScale out = scale(windows[i][0], windows[i][1]);
            assert(out.vx == 0 && out.vy == 0 && out.vw == windows[i][0] && out.vh == windows[i][1]);
            assert(fabs(bw * out.sx - windows[i][0]) < 1e-8);
            assert(fabs(bh * out.sy - windows[i][1]) < 1e-8);
            assert(fabs(out.shape - (windows[i][0] / windows[i][1]) / (16.0 / 9.0)) < 1e-12);
            assert(xcde_aspect_active() == (windows[i][0] != 2560));
        }
    }
}
static void explicit_ratios(void) {
    // Hand-authored cases include ratios unlike their monitors. The complete
    // selected view must fit, with bars rather than stretch or camera crop.
    static const struct { int mode; double w,h,cw,ch,x,y; float aspect; } cases[] = {
        {ASPECT_16_10,1920,1080,1728,1080,96,0,16.f/10.f},
        {ASPECT_21_9,2560,1440,2560,7680.0/7.0,0,1200.0/7.0,21.f/9.f},
        {ASPECT_32_9,1280,800,1280,360,0,220,32.f/9.f},
        {ASPECT_16_10,1280,800,1280,800,0,0,16.f/10.f},
        {ASPECT_21_9,3440,1440,3360,1440,40,0,21.f/9.f},
        {ASPECT_32_9,5120,1440,5120,1440,0,0,32.f/9.f},
        {ASPECT_16_10,5120,1440,2304,1440,1408,0,16.f/10.f},
        {ASPECT_32_9,7680,2160,7680,2160,0,0,32.f/9.f},
    };
    for (unsigned base=0; base<2; ++base) for (unsigned i=0;i<sizeof cases/sizeof *cases;++i) {
        reset(); const int bw=base?1920:1280,bh=base?1080:720;output_scale_set_base(bw,bh);
        g_settings.aspect=cases[i].mode;assert(widescreen_allowed());
        // Startup publication and subsequent frame publication agree even
        // when the actual drawable has another ratio or changes on resize.
        xcde_aspect_set_factor((float)xcde_aspect_target_factor(cases[i].w/cases[i].h/(16.0/9.0)));
        float first=xcde_aspect_ratio(16.f/9.f);
        OutScale out=scale(cases[i].w,cases[i].h);
        assert(fabs(first-cases[i].aspect)<1e-6 && xcde_aspect_ratio(16.f/9.f)==first);
        assert(fabs(out.vw-cases[i].cw)<1e-8 && fabs(out.vh-cases[i].ch)<1e-8);
        assert(fabs(out.vx-cases[i].x)<1e-8 && fabs(out.vy-cases[i].y)<1e-8);
        assert(fabs(bw*out.sx-out.vw)<1e-8 && fabs(bh*out.sy-out.vh)<1e-8);
        const double resized[][2]={{1304,744},{1920,1080},{1280,800},{3440,1440}};
        for (unsigned j=0;j<sizeof resized/sizeof *resized;++j) {
            out=scale(resized[j][0],resized[j][1]);
            assert(xcde_aspect_ratio(16.f/9.f)==first);
            assert(fabs(out.vw/out.vh-(double)out.shape*(16.0/9.0))<1e-12);
            assert(out.vx>=-1e-8 && out.vy>=-1e-8);
            assert(fabs(out.vw+2*out.vx-resized[j][0])<1e-8);
            assert(fabs(out.vh+2*out.vy-resized[j][1])<1e-8);
            assert(fabs(out.vw-resized[j][0])<1e-8 || fabs(out.vh-resized[j][1])<1e-8);
        }
    }
    reset();g_settings.aspect=999;OutScale invalid=scale(3440,1440);
    assert(!widescreen_allowed() && !xcde_aspect_active() && invalid.shape==1);
    assert(invalid.vw==2560 && invalid.vh==1440 && invalid.vx==440);
    g_settings.aspect=ASPECT_32_9;
    output_scale(1280,800,false,1,-1,&invalid);
    assert(invalid.shape==1 && invalid.vw==1280 && invalid.vh==720);
}
static void explicit_quality(void) {
    static const int aspects[]={ASPECT_16_10,ASPECT_21_9,ASPECT_32_9};
    static const double windows[][2]={{1280,800},{1920,1080},{1304,744},{3440,1440}};
    static const double ratios[]={1,1.5,1.7,2,3};
    static const int modes[]={RES_MATCH,1,2,RES_Q75,RES_Q50,RES_Q25,RES_DYNAMIC};
    for(unsigned a=0;a<3;++a) for(unsigned w=0;w<4;++w) {
        reset();g_settings.aspect=aspects[a];
        OutScale reference=scale(windows[w][0],windows[w][1]);
        g_settings.upscaler=UPSCALE_DLSS;g_settings.upscale_quality=UQ_NATIVE;
        for(unsigned m=0;m<sizeof modes/sizeof *modes;++m) {
            g_settings.res_mode=modes[m];OutScale out=scale(windows[w][0],windows[w][1]);
            assert(lroundf(1280*(float)out.sx)==lroundf((float)out.vw));
            assert(lroundf(720*(float)out.sy)==lroundf((float)out.vh));
            assert(out.vw==reference.vw && out.vh==reference.vh);
        }
        g_settings.res_mode=RES_MATCH;
        const int providers[]={UPSCALE_DLSS,UPSCALE_FSR3};
        for(unsigned p=0;p<2;++p) for(int q=UQ_QUALITY;q<=UQ_ULTRA;++q) {
            g_settings.upscaler=providers[p];g_settings.upscale_quality=q;
            OutScale out=scale(windows[w][0],windows[w][1]);
            assert(fabs(1280*out.sx*ratios[q]-out.vw)<1e-8);
            assert(fabs(720*out.sy*ratios[q]-out.vh)<1e-8);
            assert(out.vw==reference.vw && out.vh==reference.vh);
        }
        g_settings.upscaler=UPSCALE_FSR1;g_settings.res_mode=RES_Q50;
        OutScale half=scale(windows[w][0],windows[w][1]);
        assert(fabs(1280*half.sx*2-half.vw)<1e-8 && fabs(720*half.sy*2-half.vh)<1e-8);
        // The UI is fitted inside content, then the entire content is fitted
        // into the display. Authored squares stay square in both transforms.
        float u,x,y;
        assert(xcde_aspect_canvas(1280,720,1280*half.sx,720*half.sy,half.sx,half.sy,&u,&x,&y));
        double pxscale=half.vw/(1280*half.sx),pyscale=half.vh/(720*half.sy);
        assert(fabs(48*u*pxscale-48*u*pyscale)<1e-5);
    }
    reset();g_settings.aspect=ASPECT_32_9;OutScale cap=scale(60000,18000);
    assert(fabs(1280*cap.sx-16384)<1e-8 && fabs(720*cap.sy-4608)<1e-8);
    assert(cap.vw==60000 && cap.vh==16875 && cap.vy==562.5);
}
static void qualities(void) {
    const int modes[] = {RES_MATCH,1,2,3,RES_Q75,RES_Q50,RES_Q25,RES_DYNAMIC};
    const double ratio[] = {1,1.5,1.7,2,3};
    const double windows[][2] = {{1280,800},{3440,1440},{5120,1440}};
    reset(); g_settings.aspect = ASPECT_UNLOCKED; g_settings.upscaler = UPSCALE_DLSS;
    for (unsigned i = 0; i < sizeof windows / sizeof *windows; ++i) {
        g_settings.upscale_quality = UQ_NATIVE;
        for (unsigned m = 0; m < sizeof modes / sizeof *modes; ++m) {
            g_settings.res_mode = modes[m]; OutScale out = scale(windows[i][0], windows[i][1]);
            assert(lroundf(1280 * (float)out.sx) == (long)windows[i][0]);
            assert(lroundf(720 * (float)out.sy) == (long)windows[i][1]);
        }
        g_settings.res_mode = RES_MATCH;
        for (int q = UQ_QUALITY; q <= UQ_ULTRA; ++q) {
            g_settings.upscale_quality = q; OutScale out = scale(windows[i][0], windows[i][1]);
            assert(fabs(1280 * out.sx * ratio[q] - windows[i][0]) < 1e-8);
            assert(fabs(720 * out.sy * ratio[q] - windows[i][1]) < 1e-8);
            assert(out.vw == windows[i][0] && out.vh == windows[i][1]);
        }
    }
    // Spatial scaling keeps explicit resolution authoritative.
    g_settings.upscaler = UPSCALE_FSR1; g_settings.res_mode = RES_Q50;
    OutScale half = scale(3440,1440);
    assert(fabs(1280 * half.sx - 1720) < 1e-8 && fabs(720 * half.sy - 720) < 1e-8);
}
static void bounds(void) {
    reset(); g_settings.aspect = ASPECT_UNLOCKED;
    const double unsupported[][2] = {{720,1280},{1280,1024},{7680,1440}};
    for (unsigned i = 0; i < sizeof unsupported / sizeof *unsupported; ++i) {
        OutScale out = scale(unsupported[i][0], unsupported[i][1]);
        assert(out.shape == 1 && !xcde_aspect_active());
        assert(out.sx == out.sy && fabs(out.vw / out.vh - 16.0/9.0) < 1e-12);
        assert(out.vx >= 0 && out.vy >= 0);
    }
    OutScale cap = scale(60000,18000);
    assert(fabs(1280 * cap.sx - 16384) < 1e-8 && 720 * cap.sy < 16384);
    assert(fabs(cap.sx / cap.sy - cap.shape) < 1e-12);
    assert(cap.vw == 60000 && cap.vh == 18000);
    // Provider-independent render sizing obeys both texture dimensions.
    cap = scale(20000,12500);
    assert(1280 * cap.sx <= 16384 + 1e-8 && 720 * cap.sy <= 16384 + 1e-8);
}
static void canvas(void) {
    const float cases[][7] = {
        {3440,1440,2.6875f,2,2,440,0},
        {1280,800,1,800.f/720.f,1,0,40},
        {5120,1440,4,2,2,1280,0},
        {2560,1440,2,2,2,0,0},
    };
    for (unsigned i = 0; i < sizeof cases / sizeof *cases; ++i) {
        float u = -1, x = -1, y = -1;
        assert(xcde_aspect_canvas(1280,720,cases[i][0],cases[i][1],cases[i][2],cases[i][3],&u,&x,&y));
        assert(u == cases[i][4] && x == cases[i][5] && y == cases[i][6]);
        // A 48x48 authored UI square remains square and centered; inverse
        // projection returns the same logical hit-test point.
        float left = 616*u + x, top = 336*u + y;
        float right = 664*u + x, bottom = 384*u + y;
        assert(fabsf((right-left) - (bottom-top)) < .001f);
        assert(fabsf((right-left) - 48*cases[i][4]) < .001f);
        assert(fabsf((left - x)/u - 616) < .001f);
        assert(fabsf((top - y)/u - 336) < .001f);
        assert(fabsf(left + 24*u - cases[i][0]/2) < .001f);
        assert(fabsf(top + 24*u - cases[i][1]/2) < .001f);
    }
    const float bad[] = {0,-1,NAN,INFINITY};
    for (unsigned i = 0; i < 4; ++i) for (unsigned field = 0; field < 6; ++field) {
        float dimensions[] = {1280,720,3440,1440,2.6875f,2}; dimensions[field] = bad[i];
        float u = 17, x = 18, y = 19;
        assert(!xcde_aspect_canvas(dimensions[0],dimensions[1],dimensions[2],dimensions[3],dimensions[4],dimensions[5],&u,&x,&y));
        assert(u == 17 && x == 18 && y == 19);
    }
}
int main(int argc, char **argv) {
    assert(argc == 2); defaults = g_settings;
    assert(getenv("LARECOMP_SCALE") == NULL && getenv("LARECOMP_WIDE_TEST") == NULL);
    assert(setenv("XCDE_INI", "aspect.ini", 1) == 0);
    if (!strcmp(argv[1],"defaults")) config_defaults();
    else if (!strcmp(argv[1],"roundtrip")) config_roundtrip();
    else if (!strcmp(argv[1],"original")) original();
    else if (!strcmp(argv[1],"native")) native_windows();
    else if (!strcmp(argv[1],"explicit")) explicit_ratios();
    else if (!strcmp(argv[1],"explicit-quality")) explicit_quality();
    else if (!strcmp(argv[1],"quality")) qualities();
    else if (!strcmp(argv[1],"bounds")) bounds();
    else if (!strcmp(argv[1],"canvas")) canvas();
    else return 2;
    puts("native aspect output/config integration: PASS"); return 0;
}
