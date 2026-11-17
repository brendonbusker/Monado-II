// [XCDE] LINUX-126: timing contracts, no SDL, game or wall-clock dependencies.
#include "../../Monado_Linux/tools/launcher/linux_loop.h"
#include <cassert>
#include <cstdio>
using launcher_linux::LoopPacing;
static unsigned paints(bool visible,bool focus,bool game) {
    LoopPacing policy;unsigned frames=0;
    // Frequent input does not bypass the software-renderer frame ceiling.
    for(uint64_t now=1000000;now<1001000000;now+=100000)
        frames+=policy.paint(now,visible,focus,game);
    return frames;
}
int main() {
    assert(paints(true,true,false)==60);
    assert(paints(true,true,true)==60); // foreground remains responsive
    assert(paints(true,false,false)==4);
    assert(paints(true,false,true)==1);
    assert(!paints(false,false,true));
    LoopPacing policy;
    assert(!policy.paint(1000000,false,false,true));assert(policy.wait_ms(1000000)==50);
    assert(policy.paint(2000000,true,false,true));assert(policy.wait_ms(2000000)==50);
    assert(!policy.paint(3000000,true,false,true));
    // Restore/focus/child exit redraw now rather than waiting for the old period.
    assert(policy.paint(4000000,true,true,true));assert(policy.wait_ms(4000000)==17);
    assert(policy.paint(5000000,true,true,false));
    assert(!policy.paint(5000001,true,true,false));assert(policy.wait_ms(5000001)==17);
    assert(policy.wait_ms(22000000)==1);
    // A large scheduling pause never causes catch-up rendering bursts.
    assert(policy.paint(9999999999ull,true,true,false));
    assert(!policy.paint(9999999999ull,true,true,false));
    assert(!policy.paint(10000000000ull,false,false,false));
    assert(policy.paint(10000000001ull,true,false,false));
    puts("launcher idle policy: foreground cap, background/game budgets, hidden polling, restore/focus/exit and oversleep PASS");
}
