"""LINUX-077: actual input.c selection with authored headless SDL virtual pads."""
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


@unittest.skipUnless(sys.platform == 'linux', 'Linux SDL discovery')
class ControllerDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = Path(os.environ.get('MONADO_TEST_SDL_PORT', str(PORT)))
        marker = port / '.deps/graphics/active-sysroot.txt'
        if not marker.is_file():
            raise unittest.SkipTest('Pinned SDL3 dependencies unavailable')
        compiler = os.environ.get('MONADO_TEST_CC')
        if not compiler:
            local = port / '.deps/bin/clang-cc'
            compiler = str(local) if local.is_file() else shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('Clang required for native discovery fixture')
        spec = importlib.util.spec_from_file_location('controller_runtime', port / 'scripts/linux_runtime_check.py')
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        sysroot = Path(marker.read_text().strip())
        policy, _ = runtime.load_policy(port, sysroot)
        cls.environment = runtime.clean_environment(runtime.library_path(sysroot, policy))
        cls.environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        result = subprocess.run([str(port / '.deps/bin/pkg-config-graphics'), '--cflags', '--libs', 'sdl3'],
                                env=runtime.clean_environment(), capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-controller-discovery-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'controller-discovery'
        command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-ffp-contract=off',
                   '-fno-strict-aliasing', '-ffunction-sections', '-fdata-sections', '-pthread',
                   '-I', str(PORT / 'runtime'), str(ROOT / 'tests/native/test_controller_discovery.c'),
                   str(PORT / 'runtime/hle/bindings.c'), *shlex.split(result.stdout),
                   '-Wl,--gc-sections', '-lm', '-Xlinker', '-rpath', '-Xlinker', cls.environment['LD_LIBRARY_PATH'],
                   '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        result = subprocess.run(command, env=runtime.clean_environment(), capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        runtime.check_artifacts([cls.binary], sysroot, policy)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], cwd=self.temporary.name,
                                env=self.environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native SDL controller discovery: PASS ' + name, result.stdout)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [self.binary])

    def test_startup_controller_without_added_event(self): self.scenario('startup')
    def test_controller_arriving_after_empty_startup(self): self.scenario('delayed')
    def test_failed_first_device_does_not_hide_second(self): self.scenario('failed-first')
    def test_all_failed_then_usable_added_event(self): self.scenario('all-failed')
    def test_other_device_cannot_steal_selection_or_input(self): self.scenario('multiple')
    def test_selected_removal_recovers_existing_other_and_clears_hold(self): self.scenario('replacement')
    def test_reconnect_has_no_stale_held_buttons(self): self.scenario('reconnect')
    def test_inventory_budget_and_device_name_sanitization(self): self.scenario('diagnostics')


class LauncherControllerOwnership(unittest.TestCase):
    def test_backend_owns_gamepad_open_close(self):
        source = (PORT / 'tools/launcher/launcher.cpp').read_text()
        self.assertNotIn('SDL_OpenGamepad(', source)
        self.assertIn('rt_input_inventory(g_llog, "launcher", "startup")', source)
        self.assertIn('ImGuiConfigFlags_NavEnableGamepad', source)


if __name__ == '__main__':
    unittest.main()
