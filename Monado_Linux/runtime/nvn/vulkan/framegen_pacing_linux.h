// [XCDE] LINUX-020: one monotonic half-frame wait, after the generated image is GPU ready/presented.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
#include <errno.h>
#include <time.h>

static uint64_t fg_pacing_now(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
    return (uint64_t)now.tv_sec * 1000000000ull + (uint64_t)now.tv_nsec;
}
// The SDK still receives the measured delta. In uncapped FIFO, that delta
// includes any wait for the previous pair. Feeding it back as the next pair
// period can apply a growing delay. Use the display's two-output period instead.
static float fg_pacing_interval_ms(float measured_ms, float target_fps, bool fifo, float display_hz) {
    if (target_fps == 0.f && fifo && isfinite(display_hz) && display_hz >= 30.f && display_hz <= 1000.f)
        target_fps = display_hz * .5f;
    if (!isfinite(measured_ms) || measured_ms < 1.f || measured_ms > 100.f || (!isfinite(target_fps) || target_fps <= 0)) return measured_ms;
    float target_ms = 1000.f / (float)target_fps;
    // [XCDE] LINUX-097: a known cap defines a stable output clock. The
    // measured SDK delta is a separate input, not a jittery pacing target.
    return target_ms;
}
static bool fg_pacing_deadline(uint64_t presented, float frame_ms, uint64_t *deadline) {
    if (!presented || !deadline || !isfinite(frame_ms) || frame_ms < 1.f || frame_ms > 100.f) return false;
    uint64_t half = (uint64_t)((double)frame_ms * 500000.);
    if (UINT64_MAX - presented < half) return false;
    *deadline = presented + half;
    return true;
}
static bool fg_pacing_wait(uint64_t deadline) {
    if (!deadline) return false;
    struct timespec time = {(time_t)(deadline / 1000000000ull), (long)(deadline % 1000000000ull)};
    int result;
    do { result = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &time, NULL); } while (result == EINTR);
    return result == 0;
}
// The render worker's deliberate idle accounting needs observed time, never
// the requested half-period: preparation may have consumed that budget already.
static bool fg_pacing_wait_elapsed(uint64_t deadline, uint64_t *elapsed_ns) {
    if (!elapsed_ns) return fg_pacing_wait(deadline);
    *elapsed_ns = 0;
    if (!deadline) return false;
    uint64_t before = fg_pacing_now();
    bool result = fg_pacing_wait(deadline);
    uint64_t after = fg_pacing_now();
    if (before && after >= before) *elapsed_ns = after - before;
    return result;
}

// [XCDE] LINUX-097: one persistent two-output timeline. GPU-ready work may
// arrive early, late or in bursts. Preserve phase when possible, never repay
// missed deadlines with back-to-back output submissions.
typedef struct FgPacingClock {
    uint64_t next_pair_ns, last_output_ns, half_ns;
    bool active;
} FgPacingClock;
typedef struct FgPacingPlan {
    uint64_t generated_ns, real_ns;
    bool rebased, missed;
} FgPacingPlan;
static void fg_pacing_clock_reset(FgPacingClock *clock) {
    clock->next_pair_ns = clock->last_output_ns = clock->half_ns = 0;
    clock->active = false;
}
static uint64_t fg_pacing_output_deadline(const FgPacingClock *clock, uint64_t requested) {
    if (!clock->active || !clock->last_output_ns) return requested;
    if (UINT64_MAX - clock->last_output_ns < clock->half_ns) return 0;
    uint64_t earliest = clock->last_output_ns + clock->half_ns;
    return requested < earliest ? earliest : requested;
}
static bool fg_pacing_schedule(FgPacingClock *clock, uint64_t ready_ns, float frame_ms, FgPacingPlan *plan) {
    uint64_t half_end = 0;
    if (!clock || !plan || !fg_pacing_deadline(1, frame_ms, &half_end) || !ready_ns) return false;
    uint64_t half = half_end - 1;
    uint64_t difference = half > clock->half_ns ? half - clock->half_ns : clock->half_ns - half;
    bool changed = clock->active && difference > (clock->half_ns / 128 + 1);
    bool discontinuity = clock->active && clock->last_output_ns &&
        (ready_ns < clock->last_output_ns || ready_ns - clock->last_output_ns > UINT64_C(200000000));
    bool rebase = changed || discontinuity;
    uint64_t first = clock->active && !rebase ? clock->next_pair_ns : ready_ns;
    bool missed = clock->active && !rebase && first < ready_ns;
    if (first < ready_ns) { rebase |= ready_ns - first > half; first = ready_ns; }
    // Every accepted output gets at least one half-period, including after
    // scheduler oversleep and a slow second image. Never catch up in a burst.
    if (clock->active && !discontinuity && clock->last_output_ns) {
        if (UINT64_MAX - clock->last_output_ns < half) return false;
        uint64_t earliest = clock->last_output_ns + half;
        if (first < earliest) first = earliest;
    }
    if (UINT64_MAX - first < half || UINT64_MAX - (first + half) < half) return false;
    plan->generated_ns = first; plan->real_ns = first + half; plan->rebased = rebase; plan->missed = missed;
    clock->next_pair_ns = first + 2 * half; clock->half_ns = half; clock->active = true;
    return true;
}
static void fg_pacing_observe(FgPacingClock *clock, uint64_t submitted_ns) {
    if (!clock->active) return;
    if (!submitted_ns || submitted_ns < clock->last_output_ns) { fg_pacing_clock_reset(clock); return; }
    clock->last_output_ns = submitted_ns;
}
