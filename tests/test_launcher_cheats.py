"""LINUX-072: actual launcher cheat configuration and native ImGui widgets, without SDL/game input."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
SOURCE = PORT / 'tools/launcher/launcher.cpp'


def fixture_source():
    source = SOURCE.read_text()
    fields = source.split('    bool cheat_enabled[6]', 1)[1].split('    bool show_fps', 1)[0]
    fields = '    bool cheat_enabled[6]' + fields
    helpers = source.split('// [XCDE] LINUX-072: launcher cheat configuration,', 1)[1]
    helpers = helpers[helpers.index('static const char *const k_cheat_ini'):]
    helpers = helpers.split('// [XCDE] LINUX-072: end launcher cheat configuration.', 1)[0]
    widgets = 'static void cheat_slider(' + source.split('static void cheat_slider(', 1)[1].split('static void tab_audio()', 1)[0]
    theme = (PORT / 'tools/launcher/theme.h').read_text()
    checkbox = 'static bool checkbox(' + theme.split('static bool checkbox(', 1)[1].split('// A same-line row', 1)[0]
    prefix = r'''
#include <algorithm>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
#include "imgui.h"
#include "imgui_internal.h"
struct Cfg {
'''
    middle = r'''
};
static Cfg g;
static float g_scale = 1;
static const char *T(const char *s) { return s; }
struct Item { ImGuiID id; std::string label; ImRect box; ImGuiItemFlags flags; };
static std::vector<Item> items;
static bool crossed_width;
void ImGuiTestEngineHook_ItemAdd(ImGuiContext*, ImGuiID, const ImRect&, const ImGuiLastItemData*) {}
void ImGuiTestEngineHook_ItemInfo(ImGuiContext* ctx, ImGuiID id, const char *label, ImGuiItemStatusFlags) {
    items.push_back(Item{id, label, ctx->LastItemData.Rect, ctx->LastItemData.ItemFlags});
}
void ImGuiTestEngineHook_Log(ImGuiContext*, const char*, ...) {}
const char *ImGuiTestEngine_FindItemDebugLabel(ImGuiContext*, ImGuiID) { return ""; }
namespace launcher_theme {
static void section(const char *label) { ImGui::SeparatorText(label); }
'''
    suffix = r'''
static void frame(int width = 640) {
    items.clear();
    ImGuiIO &io = ImGui::GetIO(); io.DisplaySize = ImVec2((float)width, 1000); io.DeltaTime = 1.0f / 60;
    ImGui::NewFrame();
    ImGui::SetNextWindowPos(ImVec2(0, 0)); ImGui::SetNextWindowSize(io.DisplaySize);
    ImGui::Begin("cheats", nullptr, ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove);
    tab_cheats();
    crossed_width = ImGui::GetCurrentWindow()->DC.CursorMaxPos.x > ImGui::GetCurrentWindow()->WorkRect.Max.x + 1;
    ImGui::End(); ImGui::Render();
}
static Item named(const char *label) {
    for (const Item &item : items) if (item.label == label) return item;
    assert(false); return Item{};
}
static std::vector<Item> sliders() {
    std::vector<Item> result;
    for (const Item &item : items) if (item.label == "##multiplier") result.push_back(item);
    return result;
}
static void click(ImVec2 pos) {
    ImGuiIO &io = ImGui::GetIO();
    io.AddMousePosEvent(pos.x, pos.y); io.AddMouseButtonEvent(0, true); frame();
    io.AddMouseButtonEvent(0, false); frame();
}
static void config_tests() {
    for (int i = 0; i < 6; ++i) assert(!g.cheat_enabled[i] && g.cheat_percent[i] == 100);
    assert(!g.cheat_no_fall_damage);
    const char *invalid[] = {"", "-1", "+100", "1.5", "1x", "nan", "inf", "2001", "99999999999999999999999999999999999999", " 100", "100 ", "100%"};
    for (const char *value : invalid) assert(cheat_percent_value(value) == 100);
    for (const char *value : {"1", "true"}) assert(cheat_enabled_value(value));
    for (const char *value : {"0", "false", "2", "TRUE", "", "yes", "-1"}) assert(!cheat_enabled_value(value));
    for (int i = 0; i < 6; ++i) {
        const std::string key = std::string("cheat_") + k_cheat_ini[i];
        assert(is_cheat_key(key.c_str()) && is_cheat_key((key + "_percent").c_str()));
        assert(cheats_load(key.c_str(), "true") && g.cheat_enabled[i]);
        for (int value = 0; value <= 2000; ++value) {
            const std::string decimal = std::to_string(value);
            assert(cheats_load((key + "_percent").c_str(), decimal.c_str()));
            assert(g.cheat_percent[i] == value);
        }
    }
    assert(!cheats_load("party_switch", "1") && !is_cheat_key("cheat_exp_percent_extra"));
    assert(cheats_load("cheat_no_fall_damage", "1") && g.cheat_no_fall_damage);
    for (int i = 0; i < 6; ++i) { g.cheat_enabled[i] = i % 2; g.cheat_percent[i] = i * 400; }
    FILE *file = tmpfile(); assert(file); cheats_save(file); rewind(file);
    cheats_reset();
    char line[128], key[80], value[32]; int count = 0;
    while (fgets(line, sizeof line, file)) {
        assert(sscanf(line, "%79s = %31s", key, value) == 2);
        assert(cheats_load(key, value)); ++count;
    }
    assert(!ferror(file) && count == 13); fclose(file);
    for (int i = 0; i < 6; ++i) { assert(g.cheat_enabled[i] == (bool)(i % 2)); assert(g.cheat_percent[i] == i * 400); }
    assert(g.cheat_no_fall_damage);
    cheats_reset();
    for (int i = 0; i < 6; ++i) assert(!g.cheat_enabled[i] && g.cheat_percent[i] == 100);
    assert(!g.cheat_no_fall_damage);
}
static void ui_tests() {
    ImGui::CreateContext(); ImGuiIO &io = ImGui::GetIO(); io.IniFilename = nullptr;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    assert(io.Fonts->Build()); GImGui->TestEngineHookItems = true;
    frame(); frame();
    auto controls = sliders(); assert(controls.size() == 6);
    for (const Item &item : controls) assert(item.flags & ImGuiItemFlags_Disabled);
    click(named("Daño causado por el grupo").box.GetCenter());
    assert(g.cheat_enabled[0]); controls = sliders();
    assert(!(controls[0].flags & ImGuiItemFlags_Disabled));
    for (int i = 1; i < 6; ++i) assert(controls[i].flags & ImGuiItemFlags_Disabled);
    click(ImVec2(controls[0].box.Max.x - 1, controls[0].box.GetCenter().y)); assert(g.cheat_percent[0] == 2000);
    controls = sliders(); click(ImVec2(controls[0].box.Min.x + 1, controls[0].box.GetCenter().y)); assert(g.cheat_percent[0] == 0);
    for (int i = 1; i < 6; ++i) assert(g.cheat_percent[i] == 100);
    // Activate the native widget directly in this backend-free fixture, then deliver real key events.
    // A normal UI uses keyboard navigation to expose/activate its focus cursor first.
    ImGui::ActivateItemByID(sliders()[0].id); frame();
    io.AddKeyEvent(ImGuiMod_Ctrl, true); io.AddKeyEvent(ImGuiKey_RightArrow, true); frame();
    io.AddKeyEvent(ImGuiKey_RightArrow, false); io.AddKeyEvent(ImGuiMod_Ctrl, false); frame();
    assert(g.cheat_percent[0] == 1);
    ImGui::ActivateItemByID(sliders()[0].id); frame();
    click(named("Sin daño por caídas").box.GetCenter()); assert(g.cheat_no_fall_damage);
    frame(260); assert(!crossed_width); assert(sliders().size() == 6);
    ImGui::DestroyContext();
}
int main() { config_tests(); ui_tests(); puts("launcher cheats: defaults, strict config, all 12006 percentage values, roundtrip, native widgets, enable gates and narrow layout PASS"); }
'''
    return prefix + fields + middle + checkbox + '}\n' + helpers + widgets + suffix


@unittest.skipUnless(sys.platform == 'linux', 'Linux launcher feature')
class LauncherCheats(unittest.TestCase):
    def test_actual_configuration_and_headless_widgets(self):
        compiler = os.environ.get('MONADO_TEST_CXX')
        if not compiler:
            local = PORT / '.deps/bin/clang-cxx'
            compiler = str(local) if local.is_file() else shutil.which('clang++') or shutil.which('c++')
        if not compiler:
            cc = os.environ.get('MONADO_TEST_CC')
            if cc and Path(cc).with_name('clang-cxx').is_file():
                compiler = str(Path(cc).with_name('clang-cxx'))
        if not compiler:
            self.skipTest('C++ compiler unavailable; set MONADO_TEST_CXX')
        environment = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'XCDE_', 'LARECOMP_', 'LASRECOMP_'))}
        environment.pop('GLIBC_TUNABLES', None)
        environment.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
        with tempfile.TemporaryDirectory(prefix='monado-launcher-cheats-') as directory:
            root = Path(directory)
            fixture = root / 'launcher_cheats.cpp'; fixture.write_text(fixture_source())
            binary = root / 'launcher-cheats'
            imgui = PORT / 'third_party/imgui'
            command = [compiler, '-std=c++17', '-O1', '-UNDEBUG', '-DIMGUI_ENABLE_TEST_ENGINE', '-I', str(imgui), str(fixture)]
            command += [str(imgui / (name + '.cpp')) for name in ['imgui', 'imgui_draw', 'imgui_tables', 'imgui_widgets']]
            command += ['-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            compiled = subprocess.run(command, env=environment, cwd=root, capture_output=True, text=True, timeout=180)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary)], env=environment, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('narrow layout PASS', result.stdout)
            self.assertEqual({p.name for p in root.iterdir()}, {'launcher_cheats.cpp', 'launcher-cheats'})


if __name__ == '__main__':
    unittest.main()
