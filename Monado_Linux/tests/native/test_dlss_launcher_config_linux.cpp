// [XCDE] LINUX-017: actual launcher config/resource helpers, no SDL initialization/window/game.
#include <cassert>
#include <fstream>
#include <cerrno>
#include <unistd.h>
#include "imgui.h"
static unsigned refused_forks;
static pid_t config_forbid_fork() { refused_forks++; errno = EPERM; return -1; }
extern "C" pid_t config_imgui_forbid_fork() noexcept { return config_forbid_fork(); }
#define fork config_forbid_fork
namespace ImGui { static bool ConfigTestCombo(const char *, int *, const char *const[], int, int = -1); }
#define Combo ConfigTestCombo
#define main original_launcher_main
#include "../../tools/launcher/launcher.cpp"
#undef main
#undef Combo
#undef fork

static int requested_upscaler = -1, requested_quality = -1, seen_upscalers, seen_qualities;
namespace ImGui {
static bool ConfigTestCombo(const char *, int *selected, const char *const items[], int count, int) {
    if (count >= 2 && strstr(items[0], "Biline")) {
        seen_upscalers = count;
        if (requested_upscaler >= 0) { assert(requested_upscaler < count); *selected = requested_upscaler; return true; }
    }
    if (count == 5 && strstr(items[0], "DLAA")) {
        seen_qualities = count;
        if (requested_quality >= 0) { *selected = requested_quality; return true; }
    }
    return false;
}
}
static void frame() {
    ImGui::NewFrame(); ImGui::SetNextWindowSize(ImVec2(980,680)); ImGui::Begin("Configuration fixture");
    tab_graphics(); ImGui::End(); ImGui::Render();
}
static void put(const std::string &p, const std::string &v = "") { std::ofstream f(p); assert(f.good()); f << v; f.close(); assert(f.good()); }
static std::string read(const std::string &p) { std::ifstream f(p); assert(f.good()); return std::string(std::istreambuf_iterator<char>(f), {}); }
static void reset_cfg() { g = Cfg{}; g.icons = 1; g_mods.clear(); g_custom.clear(); g_extra.clear(); }
int main(int argc, char **argv) {
    assert(argc == 2 || (argc == 3 && !strcmp(argv[2], "selection")));
    const bool selection_only = argc == 3;
    g_root = argv[1];
    const std::string shim = g_root + "/libmonado-ngx.so", runtime = g_root + "/libnvidia-ngx-dlss.so.310.9.1";
    launcher_linux::game = g_root + "/synthetic-not-executed-game";
    assert(!linux_dlss_packaged());
    put(shim); assert(!linux_dlss_packaged());
    put(runtime); assert(linux_dlss_packaged());
    assert(!unlink(shim.c_str())); assert(!linux_dlss_packaged());
    put(shim);
    for (int mode : {-1,0,1,2,3,4}) {
        reset_cfg(); g.upscaler = mode; g.frame_gen = g.cut_fg = true;
        linux_graphics_normalize();
        assert(g.upscaler == (mode == 0 || mode == 1 || mode == 3 ? mode : 1));
        assert(!g.frame_gen && !g.cut_fg);
    }
    // Loading a DLSS setting without a valid quality must choose Native;
    // valid explicit qualities remain independent of INI key order.
    if (!selection_only) for (const char *ini : {"upscaler = dlss\n", "upscaler = dlss\nupscale_quality = invalid\n",
                           "upscale_quality = invalid\nupscaler = dlss\n"}) {
        reset_cfg(); g.uquality = 4;
        put(path("xcde.ini"), ini); load();
        assert(g.upscaler == 3 && g.uquality == 0);
        assert(read(path("xcde.ini")) == ini);
    }
    for (const char *upscaler : {"bilinear", "fsr", "fsr3"}) {
        reset_cfg();
        put(path("xcde.ini"), "upscaler = " + std::string(upscaler) + "\n"); load();
        assert(g.uquality == 1); // Other upscaler defaults are unchanged.
    }
    for (int q = 0; q < 5; q++) {
        reset_cfg();
        put(path("xcde.ini"), "upscale_quality = " + std::string(k_uq_ini[q]) + "\nupscaler = dlss\n"); load();
        assert(g.upscaler == 3 && g.uquality == q);
    }
    for (int q = 0; q < 5; q++) {
        reset_cfg();
        const std::string ini = "upscaler = dlss\nupscale_quality = " + std::string(k_uq_ini[q]) + "\nframe_gen = 1\ncutscenes = 30fg\nfps = 165\n";
        put(path("xcde.ini"),ini); load(); linux_graphics_normalize();
        assert(g.upscaler == 3 && g.uquality == q && !g.frame_gen && !g.cut_fg && g.cutscenes == 1);
        assert(read(path("xcde.ini")) == ini); // normalization is read-only until explicit save
        assert(save()); const std::string saved = read(path("xcde.ini"));
        assert(saved.find("upscaler = dlss\n") != std::string::npos && saved.find("upscale_quality = " + std::string(k_uq_ini[q]) + "\n") != std::string::npos);
        reset_cfg(); load(); linux_graphics_normalize(); assert(g.upscaler == 3 && g.uquality == q && !g.frame_gen && !g.cut_fg);
    }
    ImGui::CreateContext();
    ImGuiIO &io = ImGui::GetIO(); io.IniFilename = nullptr; io.DisplaySize = ImVec2(980,680); io.DeltaTime = 1.f / 60;
    unsigned char *pixels; int w,h; io.Fonts->GetTexDataAsRGBA32(&pixels,&w,&h); assert(pixels && w > 0 && h > 0);
    // Actual Graphics-tab handlers: entering DLSS defaults to native, while
    // staying on DLSS or choosing another quality does not overwrite it.
    for (int source : {0, 1}) {
        for (int prior = 0; prior < 5; ++prior) {
            reset_cfg(); g.upscaler = source; g.uquality = prior;
            requested_upscaler = 2; requested_quality = -1;
            frame(); assert(g.upscaler == 3 && g.uquality == 0);
        }
    }
    for (int q = 0; q < 5; ++q) {
        reset_cfg(); g.upscaler = 3; g.uquality = q;
        requested_upscaler = requested_quality = -1;
        frame(); assert(g.uquality == q);
        requested_upscaler = 2; frame(); assert(g.uquality == q); // selecting existing DLSS is not entering it
        requested_upscaler = 1; frame(); assert(g.upscaler == 1 && g.uquality == q);
    }
    for (int q = 0; q < 5; q++) {
        reset_cfg(); requested_upscaler = 2; requested_quality = q; seen_upscalers = seen_qualities = 0;
        frame();
        assert(seen_upscalers == 3 && seen_qualities == 5 && g.upscaler == 3 && g.uquality == q);
        assert(save()); put(path(("quality" + std::to_string(q) + ".ini").c_str()), read(path("xcde.ini")));
    }
    assert(!unlink(runtime.c_str()));
    reset_cfg(); requested_upscaler = requested_quality = -1; seen_upscalers = seen_qualities = 0;
    frame(); assert(seen_upscalers == 2 && seen_qualities == 0);
    ImGui::DestroyContext();
    // [XCDE] LINUX-020: native generation is gated separately from Super Resolution.
    put(runtime);
    const std::string fg_module = g_root + "/libmonado-fidelityfx.so", fg_license = g_root + "/FidelityFX-MIT.txt";
    assert(!linux_framegen_packaged());
    put(fg_module); assert(!linux_framegen_packaged());
    put(fg_license); assert(linux_framegen_packaged());
    for (int mode : {0,1,2,3}) {
        reset_cfg(); g.upscaler = mode; g.frame_gen = g.cut_fg = true;
        linux_graphics_normalize();
        assert(g.frame_gen == (mode == 3) && g.cut_fg == (mode == 3));
    }
    for (int q = 0; q < 5; q++) {
        reset_cfg(); g.upscaler = 3; g.uquality = q; g.frame_gen = g.cut_fg = true;
        assert(save()); reset_cfg(); load(); linux_graphics_normalize();
        assert(g.upscaler == 3 && g.uquality == q && g.frame_gen && g.cut_fg);
    }
    assert(!unlink(fg_license.c_str()));
    linux_graphics_normalize(); assert(!g.frame_gen && !g.cut_fg);
    assert(!unlink(runtime.c_str()));
    reset_cfg(); g.upscaler = 3; linux_graphics_normalize(); assert(g.upscaler == 1);
    launcher_linux::game = "no-slash"; assert(!linux_dlss_packaged());
    assert(refused_forks == 0);
    puts("native DLSS default and explicit quality preservation passed");
    puts("actual launcher paired-resource gate/reserved mode/five quality save-reload/no-package fallback passed; headless actual ImGui selection handlers passed; no window/game");
    return 0;
}
