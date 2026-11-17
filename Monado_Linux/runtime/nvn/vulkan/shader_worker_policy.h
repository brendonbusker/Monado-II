// [XCDE] LINUX-126: bounded shader refinement on small shared-GPU machines.
// Normal jobs retain the existing pool and synchronous draw readiness behavior.
#ifndef MONADO_SHADER_WORKER_POLICY_H
#define MONADO_SHADER_WORKER_POLICY_H
#include <stdbool.h>

typedef struct ShaderWorkerPolicy {
    int normal_workers;
    bool dedicated_refinement;
    bool worker_override;
    bool invalid_worker_override;
    bool invalid_background_override;
} ShaderWorkerPolicy;

static inline ShaderWorkerPolicy shader_worker_policy(int cpus, bool integrated_gpu,
                                                       const char *workers, const char *background) {
    if (cpus < 1) cpus = 1;
    int n = cpus - 4;
    if (n < 4) n = 4;
    if (cpus <= 6) n = cpus - 2 < 2 ? 2 : cpus - 2;
    if (n > 16) n = 16;
    ShaderWorkerPolicy p = {.normal_workers = n, .dedicated_refinement = integrated_gpu && cpus <= 8};
    if (workers) {
        unsigned count = 0;
        const char *s = workers;
        while (*s >= '0' && *s <= '9' && count <= 16) count = count * 10 + (unsigned)(*s++ - '0');
        if (s != workers && !*s && count >= 1 && count <= 16) {
            p.normal_workers = (int)count;
            p.worker_override = true;
        } else p.invalid_worker_override = true;
    }
    if (background) {
        if (background[0] == '0' && !background[1]) p.dedicated_refinement = false;
        else if (!(background[0] == '1' && !background[1])) p.invalid_background_override = true;
    }
    return p;
}

// Call under the queue lock. A currently running driver compile cannot be
// preempted here; new refinements wait while required jobs are queued or busy.
static inline bool shader_refinement_may_start(bool queued, int normal_queued, int normal_busy) {
    return queued && normal_queued == 0 && normal_busy == 0;
}
#endif
