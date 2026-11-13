// [XCDE] LINUX-056: actual headless NGX reconstruction of authored jittered
// geometry. No game input, translated shaders, window or human state.
// Reuse the existing licensed fixture's Vulkan/namespace/network scaffolding.
#define main monado_dlss_contract_fixture_main
#include "../../Monado_Linux/tests/native/test_dlss_linux.cpp"
#undef main

static float phase(unsigned index, unsigned base) {
    float scale = 1.0f, value = 0.0f;
    for (; index; index /= base) { scale /= base; value += scale * (index % base); }
    return value;
}
static std::array<float, 2> jitter(unsigned frame, unsigned phases) {
    unsigned index = frame % phases + 1;
    return {phase(index, 2) - 0.5f, phase(index, 3) - 0.5f};
}
static void raster(Scene &scene, const std::array<float, 2> &j) {
    auto *motion = reinterpret_cast<uint16_t *>(scene.staging.host + scene.motion_offset);
    auto *depth = reinterpret_cast<float *>(scene.staging.host + scene.depth_offset);
    const float rw = scene.color.desc.width, rh = scene.color.desc.height;
    for (uint32_t y = 0; y < scene.color.desc.height; ++y)
        for (uint32_t x = 0; x < scene.color.desc.width; ++x) {
            // Match positive VkViewport x/y offsets: a static feature moves
            // right/down by +j render pixels. Sample its unshifted location.
            float u = (x + 0.5f - j[0]) / rw;
            float v = (y + 0.5f - j[1]) / rh;
            bool rectangle = u >= 0.31f && u < 0.68f && v >= 0.23f && v < 0.77f;
            size_t p = static_cast<size_t>(y) * scene.color.desc.width + x;
            // Entire signal is original analytic test geometry. Smooth texture
            // supplies interior detail; hard edges exercise subpixel coverage.
            float detail = 6.0f * std::sin(43.0f * u) * std::cos(29.0f * v);
            scene.staging.host[4 * p] = static_cast<unsigned char>(rectangle ? 190.0f + detail : 24.0f);
            scene.staging.host[4 * p + 1] = static_cast<unsigned char>(rectangle ? 155.0f + detail : 30.0f);
            scene.staging.host[4 * p + 2] = static_cast<unsigned char>(rectangle ? 75.0f + detail : 45.0f);
            scene.staging.host[4 * p + 3] = 255;
            depth[p] = rectangle ? 0.3f : 0.8f;
            // Static geometry and camera: true motion is exactly zero. Raster
            // jitter is deliberately not included in the motion-vector signal.
            motion[2 * p] = motion[2 * p + 1] = 0;
        }
    scene.staging.sync(false);
}
struct Stability { double rms{}, centroid_x{}, centroid_y{}; };
static Stability stability(const char *name, int quality, bool wrong_jitter) {
    constexpr uint32_t ow = 384, oh = 216;
    constexpr unsigned warmup = 64, measured = 32, total = warmup + measured;
    auto dimensions = optimal(ow, oh, quality);
    Scene scene(dimensions[0], dimensions[1], ow, oh);
    size_t count = static_cast<size_t>(ow) * oh;
    std::vector<double> sum(count), square(count);
    double min_x = 1e30, max_x = -1e30, min_y = 1e30, max_y = -1e30;
    unsigned phases = quality ? 18 : 8;
    for (unsigned frame = 0; frame < total; ++frame) {
        auto j = jitter(frame, phases);
        raster(scene, j);
        begin(); scene.upload();
        DlssFrame input{};
        input.color = scene.color.desc; input.motion = scene.motion.desc;
        input.depth = scene.depth.desc; input.output = scene.output.desc;
        input.jitter[0] = (wrong_jitter ? -1.0f : 1.0f) * j[0];
        input.jitter[1] = (wrong_jitter ? -1.0f : 1.0f) * j[1];
        input.reset = frame == 0; input.quality = quality;
        input.recording_seq = recording_seq; input.completed_seq = completed_seq;
        CHECK(ngx_linux_evaluate(command, &input));
        scene.copy_output(); finish(); scene.staging.sync(true);
        const unsigned char *bytes = scene.staging.host + scene.read_offset;
        if (frame >= warmup) {
            double mass = 0, cx = 0, cy = 0;
            for (uint32_t y = 0; y < oh; ++y) for (uint32_t x = 0; x < ow; ++x) {
                size_t p = static_cast<size_t>(y) * ow + x;
                double value = bytes[4 * p] / 255.0;
                sum[p] += value; square[p] += value * value;
                double weight = std::max(0.0, value - 0.15);
                mass += weight; cx += weight * (x + 0.5); cy += weight * (y + 0.5);
            }
            CHECK(mass > count * 0.05 && mass < count * 0.5);
            cx /= mass; cy /= mass;
            min_x = std::min(min_x, cx); max_x = std::max(max_x, cx);
            min_y = std::min(min_y, cy); max_y = std::max(max_y, cy);
        }
    }
    double variance = 0;
    // Exclude only the outer 8px: do not let a large flat border hide edge noise.
    size_t roi = 0;
    for (uint32_t y = 8; y + 8 < oh; ++y) for (uint32_t x = 8; x + 8 < ow; ++x) {
        size_t p = static_cast<size_t>(y) * ow + x;
        double mean = sum[p] / measured;
        variance += std::max(0.0, square[p] / measured - mean * mean); ++roi;
    }
    Stability metric{std::sqrt(variance / roi), max_x - min_x, max_y - min_y};
    printf("STABILITY {\"case\":\"%s\",\"quality\":%d,\"render_width\":%u,\"render_height\":%u,\"output_width\":%u,\"output_height\":%u,\"raster_shift\":\"positive-render-pixels-right-down\",\"eval_jitter\":\"%s\",\"warmup\":%u,\"measured\":%u,\"pixel_rms\":%.9f,\"centroid_x_range_px\":%.9f,\"centroid_y_range_px\":%.9f}\n",
           name, quality, dimensions[0], dimensions[1], ow, oh, wrong_jitter ? "negated" : "same-as-raster", warmup, measured,
           metric.rms, metric.centroid_x, metric.centroid_y);
    VK_OK(vkDeviceWaitIdle(device)); ngx_linux_reset();
    return metric;
}
int main(int argc, char **argv) {
    setvbuf(stdout, nullptr, _IOLBF, 0);
    const char *state = nullptr, *feature = nullptr;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--state-root") && i + 1 < argc) state = argv[++i];
        else if (!strcmp(argv[i], "--feature-dir") && i + 1 < argc) feature = argv[++i];
        else CHECK(!"unknown argument");
    }
    CHECK(state && feature); private_state(state);
    std::string data = std::string(state) + "/ngx"; CHECK(mkdir(data.c_str(), 0700) == 0);
    CHECK(ngx_linux_init(feature, data.c_str())); network_policy(); create_device();
    auto native = stability("native-consistent", 0, false);
    auto native_wrong = stability("native-negated", 0, true);
    auto quality = stability("quality-consistent", 1, false);
    auto quality_wrong = stability("quality-negated", 1, true);
    printf("SENSITIVITY {\"native_wrong_to_consistent_rms\":%.6f,\"quality_wrong_to_consistent_rms\":%.6f,\"interpretation\":\"descriptive metrics; actual game stability is not qualified\"}\n",
           native_wrong.rms / std::max(1e-12, native.rms), quality_wrong.rms / std::max(1e-12, quality.rms));
    VK_OK(vkDeviceWaitIdle(device)); ngx_linux_reset(); ngx_linux_shutdown();
    vkDestroyFence(device, fence, nullptr); vkDestroyCommandPool(device, pool, nullptr);
    vkDestroyDevice(device, nullptr); vkDestroyInstance(instance, nullptr);
    printf("PASS actual jittered synthetic scene, native/67%% and negated-jitter controls; no game/UI\n");
    return 0;
}
