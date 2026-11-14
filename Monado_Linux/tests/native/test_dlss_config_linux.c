// [XCDE] LINUX-017: actual settings/parser, F1 option values and output scaling, no GPU/game/UI.
#define main original_settings_test_main
#include "test_launcher_settings_linux.c"
#undef main
#ifndef TEST_OUTPUT_SCALE_SOURCE
#define TEST_OUTPUT_SCALE_SOURCE "../../runtime/nvn/output_scale.c"
#endif
#include TEST_OUTPUT_SCALE_SOURCE
#include "../../runtime/ui/graphics_options.h"

static void runtime_options(void) {
    const char *quality[] = {"native", "quality", "balanced", "performance", "ultra"};
    for (int q = 0; q < 5; q++) {
        reset(); char ini[256];
        snprintf(ini, sizeof ini, "upscaler = dlss\nupscale_quality = %s\nframe_gen = 1\ncutscenes = 30fg\nfps = 165\n", quality[q]);
        load(ini);
#ifdef XCDE_LINUX_DLSS
        assert(g_settings.upscaler == UPSCALE_DLSS);
#else
        assert(g_settings.upscaler == UPSCALE_FSR1);
#endif
#ifdef XCDE_LINUX_FRAMEGEN
        assert(g_settings.upscale_quality == q && g_settings.frame_gen && g_settings.cutscene_mode == 2 && g_settings.fps == 165);
#else
        assert(g_settings.upscale_quality == q && !g_settings.frame_gen && g_settings.cutscene_mode == 1 && g_settings.fps == 165);
#endif
        char *before = read_all("xcde.ini"); assert(!strcmp(before, ini)); free(before);
        settings_save(); reset(); settings_load();
#ifdef XCDE_LINUX_DLSS
        assert(g_settings.upscaler == UPSCALE_DLSS);
#else
        assert(g_settings.upscaler == UPSCALE_FSR1);
#endif
#ifdef XCDE_LINUX_FRAMEGEN
        assert(g_settings.upscale_quality == q && g_settings.frame_gen && g_settings.cutscene_mode == 2);
#else
        assert(g_settings.upscale_quality == q && !g_settings.frame_gen && g_settings.cutscene_mode == 1);
#endif
    }
    reset(); load("upscaler = fsr3\nframe_gen = 1\ncutscenes = 30fg\n");
    assert(g_settings.upscaler == UPSCALE_FSR1 && !g_settings.frame_gen && g_settings.cutscene_mode == 1);
#ifdef XCDE_LINUX_FRAMEGEN
    reset(); load("upscaler = dlss\nframe_gen = 0\ncutscenes = 30fg\n");
    assert(!g_settings.frame_gen && g_settings.cutscene_mode == 2);
    reset(); load("upscaler = dlss\nframe_gen = 0\ncutscenes = same\n");
    assert(!g_settings.frame_gen && !g_settings.cutscene_mode);
#endif
    reset(); load("upscaler = bilinear\n"); assert(g_settings.upscaler == UPSCALE_BILINEAR);
    reset(); load("upscaler = fsr\n"); assert(g_settings.upscaler == UPSCALE_FSR1);
    assert(menu_upscale_values[0] == UPSCALE_BILINEAR && menu_upscale_values[1] == UPSCALE_FSR1);
    assert(sizeof menu_upscale_names / sizeof *menu_upscale_names == MENU_UPSCALER_COUNT);
#ifdef XCDE_LINUX_DLSS
    assert(MENU_UPSCALER_COUNT == 3 && menu_upscale_values[2] == UPSCALE_DLSS && menu_upscale_values[2] == 4);
#else
    assert(MENU_UPSCALER_COUNT == 2);
#endif
    puts("actual runtime DLSS qualities/save/reload/default fallback/FSR3-FG disable/F1 enum mapping passed");
}
static void scaling(void) {
    g_settings.upscaler = UPSCALE_DLSS;
    const int modes[] = {RES_MATCH,1,2,3,RES_Q75,RES_Q50,RES_Q25,RES_DYNAMIC};
    const double sizes[][2] = {{1280,720},{1920,1080},{2560,1440},{3440,1440},{1920,1200}};
    const double ratios[] = {1,1.5,1.7,2,3};
    for (int base = 0; base < 2; base++) {
        output_scale_set_base(base ? 1920 : 1280, base ? 1080 : 720);
        for (unsigned i = 0; i < sizeof sizes / sizeof *sizes; i++) for (int reshape = 0; reshape < 2; reshape++) {
            g_settings.aspect = reshape ? ASPECT_UNLOCKED : ASPECT_ORIGINAL;
            for (unsigned k = 0; k < sizeof modes / sizeof *modes; k++) {
                g_settings.upscale_quality = UQ_NATIVE; g_settings.res_mode = modes[k];
                OutScale o; output_scale(sizes[i][0],sizes[i][1],reshape,1,-1,&o);
                assert(fabs(g_base_w * o.sx - o.vw) < 1e-8 && fabs(g_base_h * o.sy - o.vh) < 1e-8);
            }
            for (int q = 1; q < 5; q++) {
                g_settings.upscale_quality = q; g_settings.res_mode = RES_MATCH;
                OutScale o; output_scale(sizes[i][0],sizes[i][1],reshape,1,-1,&o);
                assert(fabs(g_base_w * o.sx * ratios[q] - o.vw) < 1e-8);
                assert(fabs(g_base_h * o.sy * ratios[q] - o.vh) < 1e-8);
            }
        }
    }
    output_scale_set_base(1280,720); g_settings.res_mode = RES_Q50;
    g_settings.upscale_quality = UQ_QUALITY;
    OutScale o; output_scale(2560,1440,true,1,-1,&o);
    assert(o.sx == 1 && o.sy == 1); // explicit resolution remains authoritative for SR
    g_settings.upscale_quality = UQ_NATIVE;
    output_scale(2560,1440,true,1,-1,&o); assert(o.sx == 2 && o.sy == 2);
    g_dyn = .5; g_settings.res_mode = RES_DYNAMIC;
    output_scale(2560,1440,true,1,-1,&o); assert(o.sx == 2 && o.sy == 2 && g_dyn == .5);
    puts("DLAA native policy across 2 bases/5 windows/2 aspect policies/8 resolution modes; 4 SR ratios; dynamic bypass passed");
}
static void roundoff_probe(void) {
    output_scale_set_base(1280,720);
    g_settings.upscaler = UPSCALE_DLSS; g_settings.upscale_quality = UQ_NATIVE; g_settings.res_mode = RES_MATCH;
    OutScale o; output_scale(1304,744,false,1,-1,&o);
    // Exact production boundary: renderer_set_scale casts double to float; textures.c create_image uses lroundf.
    long render_w = lroundf(1280 * (float)o.sx), render_h = lroundf(720 * (float)o.sy);
    // device.c passes float viewport dimensions; exec.c rounds the present output size.
    long out_w = lround((float)o.vw), out_h = lround((float)o.vh);
    printf("DLAA fitted1304x744: render %ldx%ld versus output %ldx%ld (scale %.17g, float %.9g)\n",
           render_w,render_h,out_w,out_h,o.sy,(float)o.sy); fflush(stdout);
    assert(render_w == out_w && render_h == out_h);
    unsigned checked = 0;
    for (int base = 0; base < 2; base++) {
        const int bw = base ? 1920 : 1280, bh = base ? 1080 : 720;
        output_scale_set_base(bw,bh);
        for (int w = 320; w <= 7680; w++) for (int reshape = 0; reshape < 2; reshape++) {
            g_settings.aspect = reshape ? ASPECT_UNLOCKED : ASPECT_ORIGINAL;
            const int h = (int)ceil(w * 9.0 / 16) + 10;
            output_scale(w,h,reshape,1,-1,&o);
            assert(lroundf(bw * (float)o.sx) == lround((float)o.vw));
            assert(lroundf(bh * (float)o.sy) == lround((float)o.vh));
            checked++;
        }
    }
    printf("DLAA integer render/output extent agreement: %u additional size/aspect/base cases passed\n", checked);
    // LINUX-090: fixed choices on another display ratio must quantize the
    // fitted content canvas, not silently return to full-window dimensions.
    unsigned fixed_checked = 0;
    for (int base=0;base<2;++base) {
        const int bw=base?1920:1280,bh=base?1080:720;output_scale_set_base(bw,bh);
        for(int aspect=ASPECT_16_10;aspect<=ASPECT_32_9;++aspect) {
            g_settings.aspect=aspect;
            for(int w=320;w<=7680;++w) {
                const int h=(int)ceil(w*9.0/16)+10;output_scale(w,h,true,1,-1,&o);
                assert(lroundf(bw*(float)o.sx)==lround((float)o.vw));
                assert(lroundf(bh*(float)o.sy)==lround((float)o.vh));
                assert(o.vx>=-1e-8 && o.vy>=-1e-8 && o.vw<=w+1e-8 && o.vh<=h+1e-8);
                fixed_checked++;
            }
        }
    }
    printf("DLAA explicit fitted aspect extent agreement: %u additional size/aspect/base cases passed\n",fixed_checked);
}
int main(int argc, char **argv) {
    if (argc > 2) return original_settings_test_main(argc, argv);
    assert(argc == 2); defaults = g_settings;
    unsetenv("XCDE_INI"); unsetenv("LARECOMP_HIDDEN"); unsetenv("XCDE_DETERMINISTIC"); unsetenv("XCDE_INPUT_REPLAY");
    unsetenv("LARECOMP_SCALE"); unsetenv("LARECOMP_WIDE_TEST");
    if (!strcmp(argv[1],"runtime")) runtime_options();
    else if (!strcmp(argv[1],"scale")) scaling();
    else if (!strcmp(argv[1],"roundoff")) roundoff_probe();
    else if (!strcmp(argv[1],"forced-scale")) {
        setenv("LARECOMP_SCALE","0.5",1); output_scale_set_base(1280,720);
        g_settings.upscaler = UPSCALE_DLSS; g_settings.upscale_quality = UQ_NATIVE; g_settings.res_mode = RES_MATCH;
        OutScale o; output_scale(2560,1440,true,1,-1,&o); assert(o.sx == .5 && o.sy == .5);
        puts("explicit developer LARECOMP_SCALE override retains precedence over DLAA; provider must reject nonnative input");
    } else assert(!"unknown case");
    return 0;
}
