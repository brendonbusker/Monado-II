// [XCDE] LINUX-072: authored input/ABI fixtures, no game code or data.
#define _GNU_SOURCE
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include "../../runtime/hle/cheats_rewards.h"
#include "../../runtime/settings.h"
#include "../../runtime/rt.h"

Settings g_settings;
static uint64_t input, stack;
static unsigned calls, checks;
static uint32_t expected[3];
static bool recursive;
static Cpu nested;
#define CHECK(x) do {checks++;if(!(x)){fprintf(stderr,"FAIL line%d %s\n",__LINE__,#x);abort();}}while(0)
void rt_fatal_trace(void) { _Exit(86); }
void guest_call(Cpu *c, uint64_t fn) {
    CHECK(fn == 0x70000ba860ull); CHECK(!(c->sp & 15));
    CHECK(c->x[1] == stack-0x20); CHECK(c->sp == stack-0x1000);
    CHECK(c->x[0] == 0x7000020000ull); CHECK(c->x[2] == 1);
    CHECK(c->x[30] == 0x7000001234ull);
    CHECK(LD16(c->x[1]) == LD16(input));
    for(unsigned i=0;i<3;i++)CHECK(LD32(c->x[1]+4+4*i)==expected[i]);
    for(unsigned i=0x10;i<0x14;i++)CHECK(LD8(c->x[1]+i)==LD8(input+i));
    // A distinct guest CPU can nest on this host stack without sharing leases.
    if(recursive){
        recursive=false; uint64_t original_input=input,original_stack=stack;
        uint32_t saved_expected[3];memcpy(saved_expected,expected,sizeof expected);
        input=nested.x[1];stack=nested.sp;
        expected[0]=30;expected[1]=70;expected[2]=110;
        CHECK(xcde_cheats_rewards_call(&nested));
        input=original_input;stack=original_stack;memcpy(expected,saved_expected,sizeof expected);
    }
    calls++;
    c->x[0]=0xabc; c->x[1]=0xdef; c->x[2]=0x123;
    c->pc=fn; c->nzcv=0x60000000; c->v[0]=0x456;
}
static void defaults(void){
    memset(&g_settings,0,sizeof g_settings);
    g_settings.cheat_exp_percent=g_settings.cheat_ap_percent=g_settings.cheat_sp_percent=g_settings.cheat_gold_percent=100;
}
static Cpu prepare(uint64_t base, uint16_t character,uint32_t exp,uint32_t ap,uint32_t sp){
    input=base+0x1008;stack=base+0x1000;
    memset((void*)(uintptr_t)(stack-0x1000),0xa5,0x2000);
    ST16(input,character);ST32(input+4,exp);ST32(input+8,ap);ST32(input+12,sp);
    Cpu c={0};c.sp=stack;c.pc=0x7000004321ull;c.x[0]=0x7000020000ull;c.x[1]=input;c.x[2]=1;c.x[30]=0x7000001234ull;
    c.tpidr=42;c.tpidrro=43;c.excl_addr=44;c.excl_val=45;c.fpcr=46;c.fpsr=47;return c;
}
int main(void){
    uint64_t base=0x7001000000ull;
    void *m=mmap((void*)(uintptr_t)base,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    CHECK(m==(void*)(uintptr_t)base);
    defaults();Cpu c=prepare(base,1,17,31,53),before=c;
    // OFF does not even inspect an invalid pointer and never invokes a callee.
    c.x[1]=0;Cpu invalid=c;CHECK(!xcde_cheats_rewards_call(&c));CHECK(!memcmp(&invalid,&c,sizeof c));CHECK(!calls);
    c=before;g_settings.cheat_exp=g_settings.cheat_ap=g_settings.cheat_sp=true;
    CHECK(!xcde_cheats_rewards_call(&c));CHECK(!memcmp(&before,&c,sizeof c));CHECK(!calls);
    g_settings.cheat_exp_percent=-1;g_settings.cheat_ap_percent=2001;
    CHECK(!xcde_cheats_rewards_call(&c));CHECK(!memcmp(&before,&c,sizeof c));
    // Every user slider position; floor once and leave the original record alone.
    for(int p=0;p<=2000;p++){
        defaults();g_settings.cheat_exp=g_settings.cheat_ap=g_settings.cheat_sp=true;
        g_settings.cheat_exp_percent=g_settings.cheat_ap_percent=g_settings.cheat_sp_percent=p;
        c=prepare(base,1,17,31,53);before=c;uint8_t record[20],scratch[32];
        memcpy(record,(void*)(uintptr_t)input,20);memcpy(scratch,(void*)(uintptr_t)(stack-32),32);
        expected[0]=17u*(unsigned)p/100;expected[1]=31u*(unsigned)p/100;expected[2]=53u*(unsigned)p/100;
        bool changed=expected[0]!=17||expected[1]!=31||expected[2]!=53;
        CHECK(xcde_cheats_rewards_call(&c)==changed);
        CHECK(!memcmp(record,(void*)(uintptr_t)input,20));CHECK(!memcmp(scratch,(void*)(uintptr_t)(stack-32),32));
        CHECK(c.sp==before.sp&&c.pc==before.pc&&c.x[1]==before.x[1]&&c.x[30]==before.x[30]);
        CHECK(c.tpidr==42&&c.tpidrro==43&&c.excl_addr==44&&c.excl_val==45&&c.fpcr==46&&c.fpsr==47);
        if(changed)CHECK(c.x[0]==0xabc&&c.nzcv==0x60000000&&c.v[0]==0x456);else CHECK(!memcmp(&c,&before,sizeof c));
    }
    // Independent EXP/AP/SP settings, native maximum safe per-award caps.
    defaults();g_settings.cheat_exp=g_settings.cheat_ap=g_settings.cheat_sp=true;
    g_settings.cheat_exp_percent=g_settings.cheat_ap_percent=g_settings.cheat_sp_percent=2000;
    c=prepare(base,14,100000000,99999999,999999);
    expected[0]=199999998;expected[1]=99999999;expected[2]=999999;CHECK(xcde_cheats_rewards_call(&c));
    c=prepare(base,15,0xffffffff,0x80000000,0);before=c;CHECK(!xcde_cheats_rewards_call(&c));CHECK(!memcmp(&c,&before,sizeof c));
    for(unsigned id=0;id<=16;id++){
        c=prepare(base,id,10,20,30);expected[0]=200;expected[1]=400;expected[2]=600;
        CHECK(xcde_cheats_rewards_call(&c)==((id>=1&&id<=8)||id==14||id==15));
    }
    defaults();g_settings.cheat_ap=true;g_settings.cheat_ap_percent=250;
    c=prepare(base,7,10,11,12);expected[0]=10;expected[1]=27;expected[2]=12;CHECK(xcde_cheats_rewards_call(&c));
    defaults();g_settings.cheat_exp=g_settings.cheat_ap=g_settings.cheat_sp=true;
    g_settings.cheat_exp_percent=g_settings.cheat_ap_percent=g_settings.cheat_sp_percent=200;
    nested=prepare(base+0x4000,14,15,35,55);
    c=prepare(base,8,10,20,30);expected[0]=20;expected[1]=40;expected[2]=60;recursive=true;CHECK(xcde_cheats_rewards_call(&c));CHECK(!recursive);
    // Gold positive awards only: setters/removals have no hooks.
    defaults();c=(Cpu){0};c.x[1]=123;before=c;xcde_cheats_gold(&c);CHECK(!memcmp(&c,&before,sizeof c));
    g_settings.cheat_gold=true;
    for(int p=0;p<=2000;p++){
        g_settings.cheat_gold_percent=p;c=(Cpu){0};c.x[1]=123;
        xcde_cheats_gold(&c);CHECK(c.x[1]==123u*(unsigned)p/100);
    }
    g_settings.cheat_gold_percent=2000;c.x[1]=100000000;xcde_cheats_gold(&c);CHECK(c.x[1]==999999999);
    for(uint32_t value=0x80000000;value;value=value==0x80000000?0xffffffff:0){c.x[1]=value;xcde_cheats_gold(&c);CHECK(c.x[1]==value);}
    g_settings.cheat_gold_percent=100;c.x[1]=0xffff00000000007bull;before=c;xcde_cheats_gold(&c);CHECK(!memcmp(&before,&c,sizeof c));
    // Changed options with an invalid native stack fail loudly in an isolated child.
    g_settings.cheat_exp=true;g_settings.cheat_exp_percent=200;
    pid_t pid=fork();CHECK(pid>=0);if(!pid){c=prepare(base,1,10,20,30);c.sp|=1;xcde_cheats_rewards_call(&c);_Exit(0);}int status;CHECK(waitpid(pid,&status,0)==pid);CHECK(WIFEXITED(status)&&WEXITSTATUS(status)==86);
    CHECK(!munmap(m,0x10000));printf("PASS rewards %u checks, %u native calls\n",checks,calls);return 0;
}
