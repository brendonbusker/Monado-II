// [XCDE] LINUX-094: authored monotonic timing fixtures, no game execution.
#include "../../Monado_Linux/runtime/ui/fps_meter.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static const uint64_t second = UINT64_C(1000000000);
static void near(double value, double expected) { assert(fabs(value - expected) < 0.0001); }

static void warmup(void) {
    FpsMeter meter;
    double value = -1;
    fps_meter_reset(&meter);
    assert(!fps_meter_value(&meter, &value) && value == 0);
    fps_meter_frame(&meter, 0);  // zero is a valid clock origin
    fps_meter_frame(&meter, 499000000);
    assert(!fps_meter_value(&meter, &value));
    fps_meter_frame(&meter, 500000000);
    assert(fps_meter_value(&meter, &value));
    near(value, 4);  // two real frame intervals over half a second
    fps_meter_reset(&meter);
    assert(!fps_meter_value(&meter, &value) && value == 0);
    assert(!fps_meter_value(&meter, NULL));
}

static void rates(void) {
    const unsigned targets[] = {1, 30, 60, 120, 144, 165, 240};
    for (size_t k = 0; k < sizeof targets / sizeof *targets; ++k) {
        const unsigned target = targets[k];
        FpsMeter meter;
        fps_meter_reset(&meter);
        for (unsigned i = 0; i <= target * 3; ++i)
            fps_meter_frame(&meter, (uint64_t)i * second / target);
        double value;
        assert(fps_meter_value(&meter, &value));
        near(value, target);
    }
}

static void discontinuities(void) {
    FpsMeter meter;
    double value;
    fps_meter_reset(&meter);
    for (unsigned i = 0; i <= 60; ++i) fps_meter_frame(&meter, (uint64_t)i * second / 60);
    assert(fps_meter_value(&meter, &value)); near(value, 60);
    for (unsigned i = 0; i < 1000; ++i) fps_meter_frame(&meter, second);
    assert(fps_meter_value(&meter, &value)); near(value, 60);
    fps_meter_frame(&meter, second / 2);  // clock moved backwards
    assert(!fps_meter_value(&meter, &value) && value == 0);
    fps_meter_frame(&meter, second * 4);  // minimized or suspended for >2s
    assert(!fps_meter_value(&meter, &value));
    for (unsigned i = 1; i <= 30; ++i) fps_meter_frame(&meter, second * 4 + (uint64_t)i * second / 60);
    assert(fps_meter_value(&meter, &value)); near(value, 60);
    fps_meter_reset(&meter);
    fps_meter_frame(&meter, UINT64_MAX - second);
    fps_meter_frame(&meter, UINT64_MAX - second / 2);
    assert(fps_meter_value(&meter, &value)); near(value, 2);
    fps_meter_frame(&meter, 10);  // monotonic counter wrapped
    assert(!fps_meter_value(&meter, &value));
}

static void stalls(void) {
    FpsMeter meter;
    double value;
    fps_meter_reset(&meter);
    fps_meter_frame(&meter, 0);
    for (unsigned i = 1; i <= 10; ++i) fps_meter_frame(&meter, (uint64_t)i * 20000000);
    fps_meter_frame(&meter, 500000000);  // one slow real frame
    assert(fps_meter_value(&meter, &value)); near(value, 22);
    fps_meter_frame(&meter, 510000000);
    assert(fps_meter_value(&meter, &value)); near(value, 22);  // stable between refreshes
    for (unsigned i = 2; i <= 50; ++i) fps_meter_frame(&meter, 500000000 + (uint64_t)i * 10000000);
    assert(fps_meter_value(&meter, &value)); near(value, 100);
}

static void presentations(void) {
    FpsMeter meter;
    double value;
    fps_meter_reset(&meter);
    for (unsigned i = 0; i <= 90; ++i) {
        // Caller samples once per real rendered frame. V-Sync repeats / frame
        // generation only display the value, and cannot change that frame count.
        fps_meter_frame(&meter, (uint64_t)i * second / 30);
        double previous = 0;
        const bool ready = fps_meter_value(&meter, &previous);
        for (unsigned display = 0; display < 8; ++display) {
            assert(fps_meter_value(&meter, &value) == ready);
            assert(value == previous);
        }
    }
    assert(fps_meter_value(&meter, &value)); near(value, 30);
}

static void finite_values(void) {
    FpsMeter meter;
    fps_meter_reset(&meter);
    fps_meter_frame(&meter, 100);
    // Very short intervals and a near-limit clock remain finite. These are
    // authored clock edge cases, not a performance claim.
    for (unsigned i = 1; i <= 1000; ++i) fps_meter_frame(&meter, 100 + i);
    fps_meter_frame(&meter, 500000100);
    double value;
    assert(fps_meter_value(&meter, &value) && isfinite(value) && value > 0);
    fps_meter_frame(&meter, UINT64_MAX);
    assert(!fps_meter_value(&meter, &value) && value == 0);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "warmup")) warmup();
    else if (!strcmp(argv[1], "rates")) rates();
    else if (!strcmp(argv[1], "discontinuities")) discontinuities();
    else if (!strcmp(argv[1], "stalls")) stalls();
    else if (!strcmp(argv[1], "presentations")) presentations();
    else if (!strcmp(argv[1], "finite")) finite_values();
    else assert(!"unknown FPS meter scenario");
    puts("native FPS meter: PASS");
    return 0;
}
