// [XCDE] LINUX-126: pure policy, no game data or Vulkan device required.
#include <assert.h>
#include <stdio.h>
#include "shader_worker_policy.h"

int main(void) {
    const int cpus[] = {1, 2, 4, 6, 8, 12, 16, 24, 64};
    const int expected[] = {2, 2, 2, 4, 4, 8, 12, 16, 16};
    for (unsigned i = 0; i < sizeof cpus / sizeof *cpus; i++) {
        ShaderWorkerPolicy desktop = shader_worker_policy(cpus[i], false, NULL, NULL);
        ShaderWorkerPolicy shared = shader_worker_policy(cpus[i], true, NULL, NULL);
        assert(desktop.normal_workers == expected[i] && !desktop.dedicated_refinement);
        assert(shared.normal_workers == expected[i] && shared.dedicated_refinement == (cpus[i] <= 8));
    }
    assert(shader_worker_policy(8, true, "2", NULL).normal_workers == 2);
    assert(shader_worker_policy(8, true, "4", NULL).normal_workers == 4);
    assert(shader_worker_policy(64, false, "16", NULL).normal_workers == 16);
    const char *bad[] = {"", "0", "17", "-1", "2x", " 2", "999999999999999999999999999999999"};
    for (unsigned i = 0; i < sizeof bad / sizeof *bad; i++) {
        ShaderWorkerPolicy p = shader_worker_policy(8, true, bad[i], NULL);
        assert(p.normal_workers == 4 && p.invalid_worker_override && !p.worker_override);
    }
    assert(!shader_worker_policy(8, true, NULL, "0").dedicated_refinement);
    assert(shader_worker_policy(8, true, NULL, "1").dedicated_refinement);
    assert(!shader_worker_policy(8, false, NULL, "1").dedicated_refinement);
    assert(!shader_worker_policy(24, true, NULL, "1").dedicated_refinement);
    assert(shader_worker_policy(8, true, NULL, "bad").invalid_background_override);
    assert(shader_refinement_may_start(true, 0, 0));
    assert(!shader_refinement_may_start(false, 0, 0));
    assert(!shader_refinement_may_start(true, 1, 0));
    assert(!shader_refinement_may_start(true, 0, 1));
    puts("shader worker policy: PASS");
    return 0;
}
