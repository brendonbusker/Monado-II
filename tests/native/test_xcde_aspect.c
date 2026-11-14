// [XCDE] LINUX-089: authored perspective/frustum/safe-HUD fixtures, no game data.
#include "host/xcde_aspect.h"
#include "settings.h"
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

Settings g_settings;
static const float original_aspect = 16.0f / 9.0f;
static const float pi = 3.14159265358979323846f;
static uint32_t bits(float f) { uint32_t u; memcpy(&u, &f, sizeof u); return u; }
static float scalar(uint32_t u) { float f; memcpy(&f, &u, sizeof f); return f; }
static int close_to(float a, float b) { return fabsf(a-b) < 0.0001f * fmaxf(1.0f, fabsf(b)); }

static void identity(void) {
    const uint32_t values[] = {0, UINT32_C(0x80000000), UINT32_C(0x7fc12345), UINT32_C(0x7f800000),
                              UINT32_C(0xff800000), UINT32_C(0x3fe38e39), UINT32_C(0x42820000)};
    for (int pass=0; pass<2; ++pass) {
        g_settings.aspect = pass ? ASPECT_UNLOCKED : ASPECT_ORIGINAL;
        xcde_aspect_set_factor(pass ? 1.0f : 2.0f);
        assert(!xcde_aspect_active());
        for (unsigned i=0;i<sizeof values/sizeof *values;++i) {
            uint32_t v=values[i];
            assert(xcde_aspect_ratio_bits(v)==v);
            assert(xcde_aspect_fov_degrees_bits(v,bits(original_aspect))==v);
            assert(xcde_aspect_render_fov_degrees_bits(v,bits(original_aspect))==v);
            assert(xcde_aspect_hud_ratio_bits(v,0)==v && xcde_aspect_hud_ratio_bits(v,1)==v);
        }
    }
}

static void bounds(void) {
    const float accepted[]={0.9f,1.0f,1.25f,1.34375f,2.0f};
    for (unsigned i=0;i<sizeof accepted/sizeof *accepted;++i) assert(xcde_aspect_supported_factor(accepted[i]));
    const float refused[]={0.0f,-1.0f,0.89f,2.01f,INFINITY,-INFINITY,NAN};
    g_settings.aspect=ASPECT_UNLOCKED;
    for (unsigned i=0;i<sizeof refused/sizeof *refused;++i) {
        assert(!xcde_aspect_supported_factor(refused[i]));
        xcde_aspect_set_factor(refused[i]);
        assert(!xcde_aspect_active());
        assert(xcde_aspect_ratio_bits(bits(original_aspect))==bits(original_aspect));
    }
}

static void deadband(void) {
    g_settings.aspect=ASPECT_UNLOCKED;
    const float fitted[]={0.996f,0.999f,1.0f,1.001f,1.004f};
    for (unsigned i=0;i<sizeof fitted/sizeof *fitted;++i) {
        xcde_aspect_set_factor(fitted[i]);
        assert(!xcde_aspect_active());
        assert(xcde_aspect_ratio_bits(bits(original_aspect))==bits(original_aspect));
        assert(xcde_aspect_fov_degrees_bits(bits(65),bits(original_aspect))==bits(65));
    }
    xcde_aspect_set_factor(0.994f);assert(xcde_aspect_active());
    xcde_aspect_set_factor(1.006f);assert(xcde_aspect_active());
}

static void camera(float factor) {
    g_settings.aspect=ASPECT_UNLOCKED;
    xcde_aspect_set_factor(factor);
    float old_fov=65.0f*pi/180.0f;
    float aspect=xcde_aspect_ratio(original_aspect);
    float fov=xcde_aspect_fov(old_fov,original_aspect);
    assert(close_to(aspect,original_aspect*factor));
    float degrees=scalar(xcde_aspect_fov_degrees_bits(bits(65.0f),bits(original_aspect)));
    float render_degrees=scalar(xcde_aspect_render_fov_degrees_bits(bits(65.0f),bits(aspect)));
    assert(close_to(degrees*pi/180.0f,fov));
    assert(close_to(render_degrees,degrees));
    float old_h=2.0f*atanf(tanf(old_fov/2.0f)*original_aspect);
    float new_h=2.0f*atanf(tanf(fov/2.0f)*aspect);
    if (factor>1.0f) {
        assert(bits(fov)==bits(old_fov));
        assert(new_h>old_h);
        // A point beyond the original side plane becomes visible. CPU frustum
        // and render projection use the same native aspect and vertical FOV.
        float x=tanf(old_fov/2.0f)*original_aspect*1.05f;
        assert(x/(tanf(old_fov/2.0f)*original_aspect)>1.0f);
        assert(x/(tanf(fov/2.0f)*aspect)<1.0f);
    } else if (factor<1.0f) {
        assert(fov>old_fov && close_to(new_h,old_h));
        float y=tanf(old_fov/2.0f)*1.05f;
        assert(y/tanf(old_fov/2.0f)>1.0f);
        assert(y/tanf(fov/2.0f)<1.0f);
    }
    // Leave non-reference/square shadow or offscreen cameras unchanged.
    assert(bits(xcde_aspect_ratio(1.0f))==bits(1.0f));
    assert(bits(xcde_aspect_fov(old_fov,1.0f))==bits(old_fov));
    assert(xcde_aspect_fov_degrees_bits(bits(65.0f),bits(1.0f))==bits(65.0f));
    assert(xcde_aspect_hud_ratio_bits(bits(1.0f),0)==bits(1.0f));
    assert(xcde_aspect_hud_ratio_bits(bits(1.0f),1)==bits(1.0f));
}

static void hud(void) {
    const float factors[]={0.9f,1.0f,1.25f,1.34375f,2.0f};
    const float points[][2]={{0.0f,0.0f},{0.25f,0.5f},{-0.9f,-0.3f}};
    g_settings.aspect=ASPECT_UNLOCKED;
    for (unsigned i=0;i<sizeof factors/sizeof *factors;++i) {
        xcde_aspect_set_factor(factors[i]);
        float asp=xcde_aspect_ratio(original_aspect);
        float fov=xcde_aspect_fov(65*pi/180.0f,original_aspect);
        float cot=1.0f/tanf(fov/2);
        float w=asp*720,h=720,safe_w=fminf(w,original_aspect*h),safe_h=safe_w/original_aspect;
        float ax=scalar(xcde_aspect_hud_ratio_bits(bits(original_aspect),1));
        float ay=scalar(xcde_aspect_hud_ratio_bits(bits(original_aspect),0));
        for (unsigned j=0;j<sizeof points/sizeof *points;++j) {
            float x=points[j][0],y=points[j][1];
            float world_x=x*cot/asp*w/2,world_y=y*cot*h/2;
            // The native auxiliary matrix's diagonals are cot and cot/aspect;
            // world-to-screen then divides X and multiplies Y by its axis ratio.
            float hud_x=(x*cot/ax)*safe_w/2,hud_y=(y*cot/asp*ay)*safe_h/2;
            assert(fabsf(hud_x-world_x)<0.001f && fabsf(hud_y-world_y)<0.001f);
        }
    }
}

static void invalid(void) {
    const uint32_t fov[]={0,UINT32_C(0x80000000),UINT32_C(0x7fc12345),UINT32_C(0x7f800000),
                          UINT32_C(0xbf800000),UINT32_C(0x43340000)};
    xcde_aspect_set_factor(0.9f);g_settings.aspect=ASPECT_UNLOCKED;
    for (unsigned i=0;i<sizeof fov/sizeof *fov;++i)
        assert(xcde_aspect_fov_degrees_bits(fov[i],bits(original_aspect))==fov[i]);
    const uint32_t asp[]={0,UINT32_C(0x80000000),UINT32_C(0x7fc12345),UINT32_C(0x7f800000),bits(1.0f)};
    for (unsigned i=0;i<sizeof asp/sizeof *asp;++i) {
        assert(xcde_aspect_ratio_bits(asp[i])==asp[i]);
        assert(xcde_aspect_fov_degrees_bits(bits(65),asp[i])==bits(65));
    }
    for (int i=0;i<100;++i) { camera(2.0f);camera(0.9f);camera(1.0f); }
}

static _Atomic bool stop;
static void *publisher(void *unused) {
    (void)unused;
    for (int i=0;i<20000;++i) { xcde_aspect_set_factor(0.9f);xcde_aspect_set_factor(2.0f);xcde_aspect_set_factor(NAN); }
    atomic_store(&stop,true);return NULL;
}
static void concurrent(void) {
    g_settings.aspect=ASPECT_UNLOCKED;xcde_aspect_set_factor(1);pthread_t thread;
    assert(pthread_create(&thread,NULL,publisher,NULL)==0);
    do {
        float result=xcde_aspect_ratio(original_aspect);
        assert(isfinite(result));
        assert(close_to(result,original_aspect)||close_to(result,original_aspect*0.9f)||close_to(result,original_aspect*2));
    } while (!atomic_load(&stop));
    assert(pthread_join(thread,NULL)==0);
}

int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"identity")) identity();
    else if (!strcmp(argv[1],"bounds")) bounds();
    else if (!strcmp(argv[1],"deadband")) deadband();
    else if (!strcmp(argv[1],"16:10")) camera(0.9f);
    else if (!strcmp(argv[1],"21:9")) camera(21.0f/16.0f);
    else if (!strcmp(argv[1],"32:9")) camera(2.0f);
    else if (!strcmp(argv[1],"hud")) hud();
    else if (!strcmp(argv[1],"invalid")) invalid();
    else if (!strcmp(argv[1],"concurrent")) concurrent();
    else assert(!"unknown fixture");
    puts("native XCDE aspect: PASS");return 0;
}
