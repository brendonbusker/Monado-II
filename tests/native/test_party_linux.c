// [XCDE] LINUX-055 R2: authored Linux party objects/calls, no game data/code.
#define _GNU_SOURCE
#include <assert.h>
#include <fenv.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include "../../Monado_Linux/runtime/hle/party.c"
#define TEST_BYTES (2u*1024u*1024u)
#define FIELD (HEAP_BASE+0x1000)
#define PLAYER (HEAP_BASE+0x2000)
#define HUD (HEAP_BASE+0x3000)
#define LIST (HEAP_BASE+0x4000)
#define HOLDER (HEAP_BASE+0x5000)
#define GROUP (HEAP_BASE+0x6000)
#define GVT (HEAP_BASE+0x7000)
#define CHARA (HEAP_BASE+0x8000)
#define GAUGE (HEAP_BASE+0xb000)
#define STKTOP (HEAP_BASE+0x180000)
#define F_COUNT 0x7000000100ull
#define F_CLEAR 0x7000000200ull
#define F_ADD 0x7000000300ull
#define F_GET 0x7000000400ull
#define ENTRY (HEAP_BASE+0xc000)
Settings g_settings;
bool g_party_switch=true;
static uint64_t heap_bytes=TEST_BYTES;
static unsigned clear_calls,add_calls,focus_calls,leader_calls,lookup_calls;
static uint32_t handles[3];
static unsigned num_handles;
static uint16_t final_leader;
uint64_t kernel_heap_size(void) { return heap_bytes; }
void rt_fatal_trace(void) { abort(); }
void rt_unwind_point(void) {}
void plat_thread_background(void) {}
void plat_thread_name(const char *name) { (void)name; }
uint64_t plat_now_ns(void) { struct timespec t;assert(!clock_gettime(CLOCK_MONOTONIC,&t));return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec; }
static void put64(uint64_t a,uint64_t v) { memcpy((void*)a,&v,8); }
static void put32(uint64_t a,uint32_t v) { memcpy((void*)a,&v,4); }
static uint16_t id_at(unsigned n) { uint16_t v;memcpy(&v,(void*)(LIST+n*2),2);return v; }
void guest_call(Cpu *c,uint64_t fn) {
 uint64_t a=c->x[0],b=c->x[1],ret=0;
 switch(fn) {
 case PARTY_LIST_FN:assert(a==FIELD+0x20);ret=LIST;break;
 case 0x7000593120ull:assert(*(uint64_t*)a==FIELD+0x20);ret=HOLDER;break;
 case 0x70004c5490ull:assert(a==FIELD+0x20);ret=b+100;break;
 case F_COUNT:assert(a==GROUP);ret=num_handles;break;
 case F_CLEAR:assert(a==GROUP);++clear_calls;num_handles=0;break;
 case F_ADD:assert(a==GROUP&&num_handles<3);handles[num_handles++]=(uint32_t)b;++add_calls;break;
 case F_GET:assert(a==GROUP);put32(ENTRY,(uint32_t)(b<num_handles?handles[b]:0));ret=ENTRY;break;
 case FOCUS_FN:assert(a==FIELD+0x20);++focus_calls;break;
 case SET_LEADER_FN:assert(a==FIELD+0x20);++leader_calls;final_leader=(uint16_t)b;break;
 case 0x700049f8c0ull:assert(b==FIELD+0x20);put64(a,CHARA);++lookup_calls;break;
 default:fprintf(stderr,"unexpected authored guest boundary %llx\n",(unsigned long long)fn);abort();
 }
 // Deliberately clobber registers and host FP state: wrapper must preserve them.
 memset(c,0x92,sizeof *c);c->x[0]=ret;assert(!fesetround(FE_DOWNWARD));feraiseexcept(FE_INVALID);
}
static void objects(void) {
 atomic_store(&g_scan_stop,false);
 memset((void*)HEAP_BASE,0,TEST_BYTES);
 put64(FIELD,FIELD_VTABLE);put64(PLAYER,PLAYER_VTABLE);put64(HUD,HUD_VTABLE);
 float on=1;memcpy((void*)(PLAYER+0xc),&on,4);
 uint16_t ids[]={1,2,3,4,5,6,7};memcpy((void*)LIST,ids,sizeof ids);put64(LIST+0x18,7);
 put64(HOLDER+0x40,GROUP+8);put64(GROUP,GVT);
 put64(GVT+0x18,F_COUNT);put64(GVT+0x20,F_CLEAR);put64(GVT+0x28,F_ADD);put64(GVT+0x40,F_GET);
 put64(CHARA,CHARA_OBJ_VTABLE);put64(CHARA+0x1a38+0x1a0,FOLLOW_MOVE_INVOKER);
 clear_calls=add_calls=focus_calls=leader_calls=lookup_calls=num_handles=final_leader=0;
}
static void discovered(void) {
 Found f;heap_scan(&f);
 assert(f.n[K_FIELD]==1&&f.obj[K_FIELD][0]==FIELD);
 assert(f.n[K_PLAYER]==1&&f.obj[K_PLAYER][0]==PLAYER);
 assert(f.n[K_HUD]==1&&f.obj[K_HUD][0]==HUD);
 g_found=f;
 Found copy;found_get(&copy);assert(copy.n[K_FIELD]==1&&copy.obj[K_FIELD][0]==FIELD);
}
static void rotate(int step) {
 for(unsigned total=2;total<=7;total+=5) {
  objects();put64(LIST+0x18,total);discovered();
  Cpu c;memset(&c,0x56,sizeof c);c.sp=STKTOP;Cpu before=c;
  assert(!fesetround(FE_UPWARD));feclearexcept(FE_ALL_EXCEPT);feraiseexcept(FE_DIVBYZERO);
  switch_leader(&c,step);
  assert(!memcmp(&c,&before,sizeof c));assert(fegetround()==FE_UPWARD);assert(fetestexcept(FE_ALL_EXCEPT)==FE_DIVBYZERO);
  assert(clear_calls==1&&add_calls==(total==2?2:3)&&focus_calls==1&&leader_calls==1&&lookup_calls==1);
  assert(final_leader==(total==2?2:(step<0?3:2)));assert(id_at(0)==final_leader);
  assert(id_at(3)==4&&id_at(6)==7);assert(handles[0]==final_leader+100);
  assert(*(uint64_t*)(CHARA+0x1a38+0x1a0)==0);
 }
}
static void no_control(void) {
 for(unsigned mode=0;mode<4;mode++) {
  objects();discovered();
  if(mode==0)put32(PLAYER+0xc,0);
  if(mode==1)put32(PLAYER+0x10,1);
  if(mode==2){uint16_t lock=1;memcpy((void*)(PLAYER+0x136),&lock,2);}
  if(mode==3)put32(PLAYER+0xc,0x7f800001u);
  assert(!fesetround(FE_UPWARD));feclearexcept(FE_ALL_EXCEPT);feraiseexcept(FE_DIVBYZERO);
  Cpu c={0};c.sp=STKTOP;switch_leader(&c,1);
  assert(!clear_calls&&!leader_calls&&id_at(0)==1);
  assert(fegetround()==FE_UPWARD&&fetestexcept(FE_ALL_EXCEPT)==FE_DIVBYZERO);
 }
}
static void battle(void) {
 objects();put64(HUD+0x2c0,1);put64(GAUGE,GAUGE_VTABLE);put32(GAUGE-0x38,102);put32(GAUGE-0x10,0);discovered();
 Cpu c={0};c.sp=STKTOP;switch_leader(&c,1);
 assert(final_leader==3&&id_at(0)==3);assert(*(uint32_t*)(HUD+0x2d0)==103);assert(*(uint8_t*)(HUD+0x330)&2);
}
static void invalid(void) {
 objects();discovered();Cpu c={0};c.sp=STKTOP;
 assert(!mprotect((void*)LIST,4096,PROT_READ));switch_leader(&c,1);assert(id_at(0)==1&&!leader_calls);
 assert(!mprotect((void*)LIST,4096,PROT_READ|PROT_WRITE));
 put64(GROUP,HEAP_BASE+TEST_BYTES+0x1000);switch_leader(&c,1);assert(id_at(0)==1&&!leader_calls);
 heap_bytes=HEAP_MAX+1;Found f;heap_scan(&f);assert(!f.n[K_FIELD]&&!obj_ok(FIELD,K_FIELD));heap_bytes=TEST_BYTES;
}
static void guarded(void) {
 objects();uint64_t header=HEAP_BASE+0x11000-8;put64(header,PLAYER_VTABLE);
 assert(!mprotect((void*)(HEAP_BASE+0x11000),4096,PROT_NONE));assert(!obj_ok(header,K_PLAYER));assert(!player_in_control(header));
 Found f={0};f.n[K_GAUGE]=1;f.obj[K_GAUGE][0]=HEAP_BASE+0x10;assert(battle_hp(&f,1)==-1);
 // A protected page at the beginning of a coalesced run cannot hide later objects.
 assert(!mprotect((void*)HEAP_BASE,4096,PROT_NONE));heap_scan(&f);assert(f.n[K_FIELD]==1&&f.obj[K_FIELD][0]==FIELD);
 assert(!mprotect((void*)HEAP_BASE,4096,PROT_READ|PROT_WRITE));
 assert(!mprotect((void*)(HEAP_BASE+0x11000),4096,PROT_READ|PROT_WRITE));
}
static void worker(void) {
 objects();memset(&g_found,0,sizeof g_found);party_scanner_start();assert(g_scan_started);pthread_t first=g_scan_thread;
 party_scanner_start();assert(pthread_equal(first,g_scan_thread));
 uint64_t deadline=plat_now_ns()+2000000000ull;Found f;
 do{found_get(&f);if(f.n[K_FIELD])break;struct timespec t={0,1000000};nanosleep(&t,NULL);}while(plat_now_ns()<deadline);
 assert(f.n[K_FIELD]==1);uint64_t started=plat_now_ns();party_linux_reset();
 assert(plat_now_ns()-started<500000000ull&&!g_scan_started);found_get(&f);assert(!f.n[K_FIELD]);
 objects();party_scanner_start();assert(g_scan_started);party_linux_reset();assert(!g_scan_started);
}
static void macro_reset(void) {
 objects();put64(HUD+0x2c0,1);put64(HEAP_BASE+0xd000,PALETTE_VTABLE);put32(HEAP_BASE+0xd000+0x1c8,0);discovered();
 party_art_request(1);art_macro(1000);assert(g_macro_buttons==(1ull<<MACRO_RIGHT));
 g_cam_direct_frame=1000;g_tour_buttons=1;party_art_request(4);
 party_linux_reset();assert(g_art_req==-1&&!g_art_used&&!g_macro_buttons&&!g_tour_buttons&&!g_cam_direct_frame);
 objects();put64(HUD+0x2c0,1);put64(HEAP_BASE+0xd000,PALETTE_VTABLE);discovered();
 art_macro(0);assert(!g_macro_buttons);party_art_request(0);art_macro(1);assert(g_macro_buttons==(1ull<<MACRO_A));
 party_linux_reset();art_macro(0);assert(!g_macro_buttons&&!party_macro_buttons());
}
int main(int argc,char **argv) {
 assert(argc==2);
 void *p=mmap((void*)HEAP_BASE,TEST_BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
 assert(p==(void*)HEAP_BASE);objects();
 if(!strcmp(argv[1],"discovery")) discovered();
 else if(!strcmp(argv[1],"left")) rotate(-1);
 else if(!strcmp(argv[1],"right")) rotate(1);
 else if(!strcmp(argv[1],"no-control")) no_control();
 else if(!strcmp(argv[1],"battle")) battle();
 else if(!strcmp(argv[1],"invalid")) invalid();
 else if(!strcmp(argv[1],"guarded")) guarded();
 else if(!strcmp(argv[1],"worker")) worker();
 else if(!strcmp(argv[1],"macro-reset")) macro_reset();
 else abort();
 party_linux_reset();assert(!munmap(p,TEST_BYTES));puts("native Linux party: PASS");return 0;
}
