// [XCDE] LINUX-072: authored synthetic combat events; no game bytes or saves.
#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); abort(); } } while (0)
#define GUEST_LO 0x7000000000ull
#define GUEST_HI 0x8000000000ull
#include "../../runtime/cpu.h"
#undef LD32
#undef LD64
#undef ST32
#define LD32(a) (*(uint32_t *)(uintptr_t)(a))
#define LD64(a) (*(uint64_t *)(uintptr_t)(a))
#define ST32(a,v) (*(uint32_t *)(uintptr_t)(a) = (uint32_t)(v))
#define FATAL(...) do { fprintf(stderr,__VA_ARGS__); _Exit(86); } while(0)
static struct {
    bool cheat_damage_dealt, cheat_damage_received;
    int cheat_damage_dealt_percent, cheat_damage_received_percent;
    bool cheat_no_fall_damage;
} g_settings;
#include "cheats_math.h"
#include "combat_production.h"

static unsigned cases;
static unsigned linked, mode, flags;
static uint32_t run(unsigned from,unsigned to,int32_t amount,bool dealt,int dp,bool received,int rp) {
    Cpu cpu;memset(&cpu,0x6b,sizeof cpu);
    size_t frame_size=linked?0x3c10:0x180;
    cpu.sp=GUEST_LO+0x1000;cpu.x[29]=cpu.sp+(linked?0x3c00:0x170);
    uint64_t frame=cpu.x[29],event=linked?frame-0xb0:GUEST_LO+0x6000;
    uint64_t source_ref=frame-(linked?0xd0:0x50),target_ref=frame-(linked?0xc0:0x60);
    cpu.x[linked?22:21]=event;
    memset((void*)(uintptr_t)cpu.sp,0xab,frame_size);memset((void*)(uintptr_t)event,0xcd,0x38);
    LD64(source_ref)=GUEST_LO+0x8000;LD64(target_ref)=GUEST_LO+0x9000;
    LD32(source_ref+8)=from;LD32(target_ref+8)=to;LD32(event+0x20)=(uint32_t)amount;
    LD32(event+0x30)=flags;
    if(linked)LD32(cpu.sp+0x24)=mode;else cpu.x[20]=mode;
    Cpu before=cpu;unsigned char memory[0x10000];
    memcpy(memory,(void*)(uintptr_t)GUEST_LO,sizeof memory);
    g_settings.cheat_damage_dealt=dealt;g_settings.cheat_damage_received=received;
    g_settings.cheat_damage_dealt_percent=dp;g_settings.cheat_damage_received_percent=rp;
    if(linked)cheats_combat_linked_hit(&cpu);else cheats_combat_hit(&cpu);
    CHECK(!memcmp(&before,&cpu,sizeof cpu));
    uint32_t result=LD32(event+0x20);memcpy(memory+(size_t)(event-GUEST_LO)+0x20,&result,sizeof result);
    CHECK(!memcmp(memory,(void*)(uintptr_t)GUEST_LO,sizeof memory));cases++;return result;
}
int main(void) {
    void *memory=mmap((void*)(uintptr_t)GUEST_LO,0x10000,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);CHECK(memory==(void*)(uintptr_t)GUEST_LO);
    for(linked=0;linked<=1;linked++) {
    CHECK(run(2,4,123,false,2000,false,0)==123);
    CHECK(run(2,4,123,true,100,true,100)==123);
    CHECK(run(2,4,123,true,200,false,100)==246);
    CHECK(run(4,2,123,false,100,true,25)==30);
    CHECK(run(2,4,123,true,0,true,2000)==0);
    CHECK(run(4,2,123,true,2000,true,0)==0);
    CHECK(run(2,4,INT32_MAX,true,2000,false,100)==INT32_MAX);
    CHECK(run(4,2,INT32_MAX,false,100,true,2000)==INT32_MAX);
    CHECK(run(2,4,-7,true,2000,true,0)==(uint32_t)-7);
    CHECK(run(4,2,-7,true,0,true,2000)==(uint32_t)-7);
    CHECK(run(2,4,0,true,2000,true,2000)==0);
    CHECK(run(2,4,99,true,-1,false,100)==99);
    CHECK(run(4,2,99,false,100,true,2001)==99);
    for(unsigned from=0;from<=6;from++)for(unsigned to=0;to<=6;to++) {
        if((from==2&&to==4)||(from==4&&to==2))continue;
        CHECK(run(from,to,777,true,2000,true,0)==777);
    }
    // Exact one-percent increments throughout the user's entire slider range.
    for(int p=0;p<=2000;p++) {
        CHECK(run(2,4,100,true,p,false,100)==(uint32_t)p);
        CHECK(run(4,2,100,false,100,true,p)==(uint32_t)p);
    }
    // Presentation-only/native suppression mode never changes the amount.
    mode=1;CHECK(run(2,4,123,true,2000,true,2000)==123);mode=0;
    // Native loss packets keep their flags; no flag is rewritten/interpreted as
    // healing by the adapter. The original consumer owns those side effects.
    for(unsigned i=0;i<32;i++) {
        flags=1u<<i;CHECK(run(2,4,100,true,150,false,100)==150);
        CHECK(run(4,2,-100,false,100,true,150)==(uint32_t)-100);
    }
    flags=0;
    }
    // Disabled and exact1x paths do not dereference even an invalid frame/event.
    Cpu bad={0},snapshot=bad;g_settings=(typeof(g_settings)){0};cheats_combat_hit(&bad);cheats_combat_linked_hit(&bad);CHECK(!memcmp(&bad,&snapshot,sizeof bad));
    g_settings=(typeof(g_settings)){.cheat_damage_dealt=true,.cheat_damage_received=true,.cheat_damage_dealt_percent=100,.cheat_damage_received_percent=100};cheats_combat_hit(&bad);cheats_combat_linked_hit(&bad);CHECK(!memcmp(&bad,&snapshot,sizeof bad));
    pid_t pid=fork();CHECK(pid>=0);if(!pid){g_settings.cheat_damage_dealt_percent=200;cheats_combat_hit(&bad);_Exit(1);}
    int status;CHECK(waitpid(pid,&status,0)==pid);CHECK(WIFEXITED(status)&&WEXITSTATUS(status)==86);
    g_settings=(typeof(g_settings)){0};CHECK(!cheats_skip_fall_damage(NULL));
    for(unsigned enabled=0;enabled<2;enabled++)for(unsigned entity=0;entity<7;entity++)for(unsigned forced=0;forced<4;forced++) {
        Cpu fall;memset(&fall,0xa5,sizeof fall);fall.x[23]=entity;fall.x[22]=forced;fall.sp=1234;fall.x[0]=5678;
        Cpu previous=fall;g_settings.cheat_no_fall_damage=enabled;
        CHECK(cheats_skip_fall_damage(&fall)==(enabled&&entity==2&&!(forced&1)));
        CHECK(!memcmp(&fall,&previous,sizeof fall));
    }
    CHECK(!munmap(memory,0x10000));printf("PASS %u combat cases plus CPU/guest-memory preservation and ABI refusal\n",cases);return 0;
}
