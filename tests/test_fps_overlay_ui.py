"""LINUX-094: actual FPS overlay lifecycle and ImGui geometry, no Vulkan/window/game."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PORT=ROOT/'Monado_Linux'

class FpsOverlayUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=os.environ.get('MONADO_TEST_CXX') or shutil.which('clang++')
        if not compiler:raise unittest.SkipTest('Clang C++ required for production runtime headers')
        include=os.environ.get('MONADO_TEST_SDL_INCLUDE')
        if not include:
            active=PORT/'.deps/graphics/active-sysroot.txt'
            if active.is_file():include=str(Path(active.read_text().strip())/'usr/include')
        if not include or not (Path(include)/'SDL3/SDL.h').is_file():raise unittest.SkipTest('SDL3/Vulkan headers required')
        cls.temp=tempfile.TemporaryDirectory(prefix='monado-fps-ui-');cls.addClassCleanup(cls.temp.cleanup)
        cls.binary=Path(cls.temp.name)/'fps-ui';imgui=PORT/'third_party/imgui'
        command=[compiler,'-std=c++17','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing',
            '-ffunction-sections','-fdata-sections','-I'+str(imgui),'-I'+str(imgui/'backends'),'-I'+include,
            str(ROOT/'tests/native/test_fps_overlay_ui.cpp'),str(PORT/'runtime/ui/menu_vk.cpp'),
            *[str(imgui/(name+'.cpp')) for name in ['imgui','imgui_draw','imgui_tables','imgui_widgets']],
            '-Wl,--gc-sections','-pthread','-lm','-o',str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN')=='1':command[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all']
        result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        if result.returncode:raise AssertionError(result.stdout+result.stderr)

    def scenario(self,name):
        result=subprocess.run([str(self.binary),name],cwd=self.temp.name,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('native FPS overlay UI: PASS',result.stdout)
    def test_all_ratios_sizes_and_warmup_have_bounded_legible_geometry(self):self.scenario('layout')
    def test_default_off_does_not_initialize_or_draw_and_invalid_extent_is_empty(self):self.scenario('disabled')
    def test_actual_ui_context_isolated_input_transparent_and_toggle_reset_safe(self):self.scenario('runtime')
    def test_optional_backend_failure_preserves_context_and_stops_retries(self):self.scenario('init-failure')
    def test_optional_font_failure_cleans_backend_and_preserves_game_context(self):self.scenario('font-failure')

if __name__=='__main__':unittest.main()
