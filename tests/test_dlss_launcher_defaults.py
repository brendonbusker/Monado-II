"""Actual launcher configuration and headless ImGui DLSS selection; no window/game."""
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


def dependency_port():
    override = os.environ.get('MONADO_TEST_SDL_PORT')
    port = Path(override) if override else PORT
    if ((port / '.deps/graphics/active-sysroot.txt').is_file()
            and (port / '.deps/bin/pkg-config-graphics').is_file()):
        return port.resolve()
    return None


@unittest.skipUnless(sys.platform == 'linux', 'native Linux launcher configuration')
class DlssLauncherDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        port = dependency_port()
        if port is None:
            raise unittest.SkipTest('Pinned SDL3 development dependencies unavailable; set MONADO_TEST_SDL_PORT')
        cc = os.environ.get('MONADO_TEST_CC')
        sibling = Path(cc).with_name('clang-cxx') if cc else port / '.deps/bin/clang-cxx'
        compiler = os.environ.get('MONADO_TEST_CXX') or (str(sibling) if sibling.is_file() else shutil.which('clang++'))
        if not compiler:
            raise unittest.SkipTest('Clang C++ is required for the actual launcher fixture')
        spec = importlib.util.spec_from_file_location('launcher_defaults_runtime_check', port / 'scripts/linux_runtime_check.py')
        runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
        sysroot = Path((port / '.deps/graphics/active-sysroot.txt').read_text().strip())
        policy, _ = runtime.load_policy(port, sysroot)
        cls.environment = runtime.clean_environment(runtime.library_path(sysroot, policy))
        cls.environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        pkg = subprocess.run([str(port / '.deps/bin/pkg-config-graphics'), '--cflags', '--libs', 'sdl3'],
                             env=runtime.clean_environment(), capture_output=True, text=True, timeout=30)
        if pkg.returncode:
            raise AssertionError(pkg.stdout + pkg.stderr)
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-launcher-defaults-')
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        common = [compiler, '-std=c++17', '-O1', '-UNDEBUG', '-ffp-contract=off', '-fno-strict-aliasing',
                  '-ffunction-sections', '-fdata-sections', '-pthread', '-I', str(PORT / 'third_party/imgui'),
                  '-I', str(PORT / 'third_party/imgui/backends')]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            common[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        objects = []
        for source in ('imgui', 'imgui_draw', 'imgui_tables', 'imgui_widgets'):
            target = directory / (source + '.o')
            command = [*common, '-Dfork=config_imgui_forbid_fork', '-c',
                       str(PORT / 'third_party/imgui' / (source + '.cpp')), '-o', str(target)]
            compiled = subprocess.run(command, env=runtime.clean_environment(), capture_output=True,
                                      text=True, timeout=120)
            if compiled.returncode:
                raise AssertionError(compiled.stdout + compiled.stderr)
            objects.append(str(target))
        cls.binary = directory / 'launcher-defaults'
        command = [*common, str(PORT / 'tests/native/test_dlss_launcher_config_linux.cpp'), *objects,
                   *shlex.split(pkg.stdout), '-Wl,--gc-sections', '-lm', '-Xlinker', '-rpath',
                   '-Xlinker', cls.environment['LD_LIBRARY_PATH'], '-o', str(cls.binary)]
        compiled = subprocess.run(command, env=runtime.clean_environment(), capture_output=True,
                                  text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        runtime.check_artifacts([cls.binary], sysroot, policy)
        cls.directory = directory

    def scenario(self, selection_only):
        with tempfile.TemporaryDirectory(prefix='state-', dir=self.directory) as state:
            command = [str(self.binary), state] + (['selection'] if selection_only else [])
            result = subprocess.run(command, cwd=state, env=self.environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('native DLSS default and explicit quality preservation passed', result.stdout)

    def test_missing_quality_and_explicit_quality_serialization(self):
        self.scenario(False)

    def test_actual_graphics_selection_defaults_native_and_preserves_explicit_quality(self):
        self.scenario(True)


if __name__ == '__main__':
    unittest.main()
