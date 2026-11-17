// [XCDE] LINUX-126: execute the actual authored exec.c worker/readiness section.
// Python extracts that section unchanged; the fixture supplies no Vulkan/game.
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define LOG(...) ((void)0)
#define VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU 1
static struct { struct { int deviceType; } props; } g_vk;
static int fixture_cpus = 8, fail_all, fail_refine, hold_normal;
static _Atomic int created, lowered, refined, quick_done, refine_waits;
static pthread_t refinement_id;
static bool refinement_identified;
static pthread_mutex_t fixture_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t fixture_cond = PTHREAD_COND_INITIALIZER;
static int pw_npending, pl_npending, lv_npending;
static const char *g_rq_where;
static bool tl_rq_worker;
static uint64_t stat_build_waits, stat_build_wait_ns, hc_wait_ns, hc_wait_n;
static bool diag_deterministic(void) { return false; }
static void prewarm_pump(void) { abort(); }
static void vk_rq_at(const char *where) { g_rq_where = where; }
static uint64_t SDL_GetTicksNS(void) {
    struct timespec t;
    assert(!clock_gettime(CLOCK_MONOTONIC, &t));
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}
int plat_cpu_count(void) { return fixture_cpus; }
void plat_thread_background(void) {} // existing generic Linux behavior unchanged
void plat_thread_name(const char *name) {
    if (!strcmp(name, "shader refine")) {
        pthread_mutex_lock(&fixture_lock);
        refinement_id = pthread_self();
        refinement_identified = true;
        pthread_cond_broadcast(&fixture_cond);
        pthread_mutex_unlock(&fixture_lock);
    }
}
void plat_thread_shader_background(void) { atomic_fetch_add(&lowered, 1); }
static int fixture_create(pthread_t *, const pthread_attr_t *, void *(*)(void *), void *);
static int fixture_wait(pthread_cond_t *, pthread_mutex_t *);
#define pthread_create fixture_create
#define pthread_cond_wait fixture_wait
#include "shader_worker_section_fixture.h"
#undef pthread_create
#undef pthread_cond_wait

typedef struct { void *(*fn)(void *); void *arg; } Start;
static void *start_thread(void *arg) {
    Start s = *(Start *)arg;
    free(arg);
    if (s.fn == worker && hold_normal) {
        pthread_mutex_lock(&fixture_lock);
        while (hold_normal) pthread_cond_wait(&fixture_cond, &fixture_lock);
        pthread_mutex_unlock(&fixture_lock);
    }
    return s.fn(s.arg);
}
static int fixture_create(pthread_t *t, const pthread_attr_t *a, void *(*fn)(void *), void *arg) {
    if (fail_all || (fail_refine && fn == refinement_worker)) return EAGAIN;
    Start *s = malloc(sizeof *s);
    assert(s);
    *s = (Start){fn, arg};
    int rc = pthread_create(t, a, start_thread, s);
    if (rc) free(s); else atomic_fetch_add(&created, 1);
    return rc;
}
static int fixture_wait(pthread_cond_t *cond, pthread_mutex_t *lock) {
    if (cond == &jobs_cond) {
        pthread_mutex_lock(&fixture_lock);
        bool refine = refinement_identified && pthread_equal(pthread_self(), refinement_id);
        if (refine) atomic_fetch_add(&refine_waits, 1);
        pthread_cond_broadcast(&fixture_cond);
        pthread_mutex_unlock(&fixture_lock);
    }
    return pthread_cond_wait(cond, lock);
}

static struct timespec deadline(void) {
    struct timespec t;
    assert(!clock_gettime(CLOCK_REALTIME, &t));
    t.tv_sec += 5;
    return t;
}
static void wait_atomic(_Atomic int *value, int count) {
    struct timespec end = deadline();
    pthread_mutex_lock(&fixture_lock);
    while (atomic_load(value) < count) assert(!pthread_cond_timedwait(&fixture_cond, &fixture_lock, &end));
    pthread_mutex_unlock(&fixture_lock);
}
static void notify_increment(_Atomic int *value) {
    pthread_mutex_lock(&fixture_lock);
    atomic_fetch_add(value, 1);
    pthread_cond_broadcast(&fixture_cond);
    pthread_mutex_unlock(&fixture_lock);
}
typedef struct Gate {
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int entered;
    bool released;
} Gate;
static Gate normal_gate = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER};
static Gate low_gate = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER};
static void block(Gate *g) {
    pthread_mutex_lock(&g->lock);
    g->entered++;
    pthread_cond_broadcast(&g->cond);
    while (!g->released) pthread_cond_wait(&g->cond, &g->lock);
    pthread_mutex_unlock(&g->lock);
}
static void wait_entered(Gate *g) {
    struct timespec end = deadline();
    pthread_mutex_lock(&g->lock);
    while (!g->entered) assert(!pthread_cond_timedwait(&g->cond, &g->lock, &end));
    pthread_mutex_unlock(&g->lock);
}
static void release(Gate *g) {
    pthread_mutex_lock(&g->lock);
    g->released = true;
    pthread_cond_broadcast(&g->cond);
    pthread_mutex_unlock(&g->lock);
}
static void blocked_normal(void *arg) { block(arg); }
static void quick(void *arg) { (void)arg; notify_increment(&quick_done); }
static void low(void *arg) { (void)arg; notify_increment(&refined); }
static void blocked_low(void *arg) { block(arg); notify_increment(&refined); }
static void ready(void *arg) { atomic_store((_Atomic int *)arg, 1); }
static void same_thread(void *arg) { assert(pthread_equal(pthread_self(), *(pthread_t *)arg)); }

int main(int argc, char **argv) {
    assert(argc == 2);
    const char *scenario = argv[1];
    g_vk.props.deviceType = VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    if (!strcmp(scenario, "sync") || !strcmp(scenario, "inline")) {
        if (!strcmp(scenario, "sync")) assert(!setenv("LARECOMP_SYNC_SHADERS", "1", 1));
        else tl_inline_jobs = true;
        pthread_t me = pthread_self();
        run_job(same_thread, &me);
        run_job_low(same_thread, &me);
        assert(!atomic_load(&created) && !atomic_load(&lowered));
    } else if (!strcmp(scenario, "fail-all")) {
        fail_all = 1;
        pthread_t me = pthread_self();
        run_job(same_thread, &me);
        run_job_low(same_thread, &me);
        assert(jobs_inline_fallback && !atomic_load(&created));
    } else if (!strcmp(scenario, "readiness-steal")) {
        hold_normal = 1;
        _Atomic int state = 0;
        run_job(ready, &state);
        run_job_low(low, NULL);
        assert(wait_ready(&state, &state));
        wait_atomic(&refined, 1);
        assert(!atomic_load(&g_jobs_busy) && !atomic_load(&g_jobs_queued));
        assert(stat_build_waits == 1);
    } else if (!strcmp(scenario, "busy-gates-low")) {
        run_job(blocked_normal, &normal_gate);
        wait_entered(&normal_gate);
        wait_atomic(&refine_waits, 1);
        int before = atomic_load(&refine_waits);
        run_job_low(low, NULL);
        // The actual refinement thread must wake, inspect required work, and
        // return to its wait, rather than merely not being scheduled yet.
        wait_atomic(&refine_waits, before + 1);
        assert(!atomic_load(&refined));
        release(&normal_gate);
        wait_atomic(&refined, 1);
        assert(atomic_load(&lowered) == 1);
    } else if (!strcmp(scenario, "urgent-during-low")) {
        run_job(quick, NULL);
        wait_atomic(&quick_done, 1);
        run_job_low(blocked_low, &low_gate);
        wait_entered(&low_gate);
        run_job_low(low, NULL);
        run_job(quick, NULL);
        wait_atomic(&quick_done, 2); // required job is not behind the busy refinement
        assert(!atomic_load(&refined));
        release(&low_gate);
        wait_atomic(&refined, 2);
        assert(atomic_load(&lowered) == 1);
    } else {
        int expected = 5;
        if (!strcmp(scenario, "desktop")) { fixture_cpus = 24; g_vk.props.deviceType = 2; expected = 16; }
        else if (!strcmp(scenario, "fail-refine")) { fail_refine = 1; expected = 4; }
        else if (!strcmp(scenario, "override2")) { assert(!setenv("XCDE_SHADER_WORKERS", "2", 1)); expected = 3; }
        else if (!strcmp(scenario, "override4")) { assert(!setenv("XCDE_SHADER_WORKERS", "4", 1)); }
        else if (!strcmp(scenario, "background-off")) { assert(!setenv("XCDE_SHADER_BACKGROUND", "0", 1)); expected = 4; }
        else assert(!strcmp(scenario, "default"));
        run_job(quick, NULL);
        wait_atomic(&quick_done, 1);
        run_job_low(low, NULL);
        wait_atomic(&refined, 1);
        assert(atomic_load(&created) == expected);
        if (!strcmp(scenario, "desktop") || !strcmp(scenario, "fail-refine") || !strcmp(scenario, "background-off")) {
            assert(!jobs_separate_refinement && !atomic_load(&lowered));
        } else assert(jobs_separate_refinement && atomic_load(&lowered) == 1);
    }
    printf("shader worker queue: PASS %s\n", scenario);
    return 0;
}
