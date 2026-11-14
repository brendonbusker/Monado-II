"""LINUX-089: real ImGui SDL backend with authored dummy-video virtual pads."""
from pathlib import Path
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'Linux SDL backend recovery')
class ControllerImGuiRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = Path(os.environ.get('MONADO_TEST_SDL_PORT', str(PORT)))
        marker = port / '.deps/graphics/active-sysroot.txt'
        if not marker.is_file():
            raise unittest.SkipTest('Pinned SDL3 dependencies unavailable')
        compiler = os.environ.get('MONADO_TEST_CXX') or shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('Clang++ required for real ImGui backend fixture')
        spec = importlib.util.spec_from_file_location('controller_imgui_runtime', port / 'scripts/linux_runtime_check.py')
        runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
        sysroot = Path(marker.read_text().strip())
        policy, _ = runtime.load_policy(port, sysroot)
        cls.environment = runtime.clean_environment(runtime.library_path(sysroot, policy))
        cls.environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        result = subprocess.run([str(port / '.deps/bin/pkg-config-graphics'), '--cflags', '--libs', 'sdl3'],
                                env=runtime.clean_environment(), capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-controller-imgui-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'controller-imgui'
        imgui = PORT / 'third_party/imgui'
        command = [compiler, '-std=c++17', '-O1', '-UNDEBUG', '-ffp-contract=off',
                   '-fno-strict-aliasing', '-ffunction-sections', '-fdata-sections', '-pthread',
                   '-I', str(imgui), str(ROOT / 'tests/native/test_controller_imgui_recovery.cpp'),
                   *[str(imgui / name) for name in ('imgui.cpp', 'imgui_draw.cpp', 'imgui_tables.cpp', 'imgui_widgets.cpp')],
                   *shlex.split(result.stdout), '-Wl,--gc-sections', '-lm',
                   '-Xlinker', '-rpath', '-Xlinker', cls.environment['LD_LIBRARY_PATH'], '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        result = subprocess.run(command, env=runtime.clean_environment(), capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        runtime.check_artifacts([cls.binary], sysroot, policy)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], cwd=self.temporary.name,
                                env=self.environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native ImGui controller recovery: PASS ' + name, result.stdout)
        self.assertEqual({p.name for p in Path(self.temporary.name).iterdir()}, {self.binary.name})

    def test_missed_added_event_recovers_on_idle_tick(self): self.scenario('delayed')
    def test_failed_open_retries_when_focus_returns(self): self.scenario('focus-retry')
    def test_missed_remove_add_recovers_replacement(self): self.scenario('replacement')
    def test_healthy_first_controller_keeps_ownership(self): self.scenario('healthy')
    def test_auto_all_retains_healthy_and_recovers_missing(self): self.scenario('all')
    def test_manual_mode_preserves_caller_ownership(self): self.scenario('manual')
    def test_last_device_loss_releases_navigation(self): self.scenario('release')
    def test_failed_open_retries_are_bounded_by_monotonic_time(self): self.scenario('retry-backoff')
    def test_auto_all_discovers_missed_addition_without_reopening_healthy(self): self.scenario('all-addition')


if __name__ == '__main__':
    unittest.main()
