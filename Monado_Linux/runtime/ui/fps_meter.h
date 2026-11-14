// [XCDE] LINUX-094: rendered-game FPS, independent of presentation repeats.
// The render thread calls frame once per real frame; drawing the overlay only
// reads value. No wall-clock, platform, ImGui or game state is needed here.
#ifndef MONADO_FPS_METER_H
#define MONADO_FPS_METER_H
#include <stdbool.h>
#include <stdint.h>

typedef struct FpsMeter {
    uint64_t start_ns, last_ns, intervals;
    double rate;
    bool started, ready;
} FpsMeter;

static inline void fps_meter_reset(FpsMeter *meter) {
    meter->start_ns = meter->last_ns = meter->intervals = 0;
    meter->rate = 0;
    meter->started = meter->ready = false;
}

static inline void fps_meter_frame(FpsMeter *meter, uint64_t now_ns) {
    // A resume starts a new window rather than displaying a stale pre-suspend
    // result. Ordinary hitches below two seconds remain part of measured FPS.
    if (!meter->started || now_ns < meter->last_ns ||
        now_ns - meter->last_ns > UINT64_C(2000000000)) {
        fps_meter_reset(meter);
        meter->started = true;
        meter->start_ns = meter->last_ns = now_ns;
        return;
    }
    if (now_ns == meter->last_ns) return;
    meter->last_ns = now_ns;
    meter->intervals++;
    uint64_t elapsed = now_ns - meter->start_ns;
    if (elapsed >= UINT64_C(500000000)) {
        meter->rate = (double)meter->intervals * 1e9 / (double)elapsed;
        meter->ready = true;
        meter->start_ns = now_ns;
        meter->intervals = 0;
    }
}

static inline bool fps_meter_value(const FpsMeter *meter, double *fps) {
    if (!fps) return false;
    *fps = meter->ready ? meter->rate : 0;
    return meter->ready;
}
#endif
