// [XCDE] LINUX-093: authored compositor metadata. No game code or assets.
#include "../../Monado_Linux/runtime/nvn/aspect_composite.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static AspectCompositeDraw draw(void) {
    return (AspectCompositeDraw){.width=1280,.height=720,.count=3,.instances=1,.mode=4,
        .sx=2.625f,.sy=2,.viewport={0,0,1280,720}};
}
static AspectCompositeInput source(uint32_t width, uint32_t height) {
    return (AspectCompositeInput){.width=width,.height=height,.sx=2.625f,.sy=2,
        .scene_target=true,.gpu_written=true,.color_image=true,.separate_image=true};
}
static AspectCompositeInput atlas(void) {
    return (AspectCompositeInput){.width=256,.height=256,.sx=1,.sy=1,.color_image=true,.separate_image=true};
}
static void reduced(void) {
    AspectCompositeDraw d=draw();
    const uint32_t sizes[][2]={{1280,720},{1208,680},{1128,640},{1056,592},{976,552},{896,504},{640,360},{320,180}};
    for (size_t i=0;i<sizeof sizes/sizeof *sizes;++i) {
        AspectCompositeInput inputs[]={source(sizes[i][0],sizes[i][1]),atlas()};
        assert(aspect_composite_role(&d,inputs,2)!=ASPECT_COMPOSITE_HUD);
        inputs[2-1]=inputs[0]; inputs[0]=atlas();
        assert(aspect_composite_role(&d,inputs,2)!=ASPECT_COMPOSITE_HUD);
    }
}
static void ui(void) {
    AspectCompositeDraw d=draw();
    AspectCompositeInput inputs[]={source(640,360),atlas()};
    inputs[0].scene_target=false;
    assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(192,544);inputs[0].scene_target=false;inputs[0].sx=inputs[0].sy=2;
    assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(512,512);inputs[0].scene_target=false;inputs[0].sx=inputs[0].sy=1;
    assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=atlas();
    assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
}
static void boundaries(void) {
    AspectCompositeDraw d=draw();AspectCompositeInput inputs[]={source(640,360),atlas()};
    d.instances=20;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    d=draw();d.viewport[0]=20;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    d=draw();d.viewport[2]=640;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    d=draw();d.count=100;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    d=draw();d.mode=1;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    d=draw();inputs[0].gpu_written=false;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(640,360);inputs[0].color_image=false;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(640,360);inputs[0].separate_image=false;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(640,360);inputs[0].sx=inputs[0].sy=2;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(640,360);inputs[0].sx=4;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    inputs[0]=source(640,360);inputs[0].sy=NAN;assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
    assert(aspect_composite_role(&d,NULL,0)==ASPECT_COMPOSITE_HUD);
}
static void transitions(void) {
    const float factors[]={.9f,21.f/16.f,3440.f/2560.f,2.f};
    for (size_t k=0;k<sizeof factors/sizeof *factors;++k) {
        AspectCompositeDraw d=draw();d.sx=d.sy*factors[k];
        for (unsigned i=0;i<64;++i) {
            AspectCompositeInput inputs[]={source((i&1)?1280:896,(i&1)?720:504),atlas()};
            inputs[0].sx=d.sx;
            assert(aspect_composite_role(&d,inputs,2)!=ASPECT_COMPOSITE_HUD);
            inputs[0]=atlas();assert(aspect_composite_role(&d,inputs,2)==ASPECT_COMPOSITE_HUD);
        }
    }
}
static void inherited(void) {
    AspectCompositeDraw d=draw();AspectCompositeInput i=source(1280,720);
    assert(aspect_composite_role(&d,&i,1)==ASPECT_COMPOSITE_NATIVE_SIZE);
    i.sx=i.sy=1;assert(aspect_composite_role(&d,&i,1)==ASPECT_COMPOSITE_HUD);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"reduced"))reduced();
    else if(!strcmp(argv[1],"ui"))ui();
    else if(!strcmp(argv[1],"boundaries"))boundaries();
    else if(!strcmp(argv[1],"transitions"))transitions();
    else if(!strcmp(argv[1],"inherited"))inherited();
    else assert(!"unknown scenario");
    puts("native aspect compositor: PASS");return 0;
}
