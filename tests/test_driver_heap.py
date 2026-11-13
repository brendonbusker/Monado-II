"""LINUX-070: compile/run the checked driver-heap helper with authored native fixtures."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


def dependency_port():
    # Match the existing native camera fixture's project-local compiler override.
    override = os.environ.get('MONADO_TEST_SDL_PORT')
    for port in ([Path(override)] if override else [PORT]):
        marker = port / '.deps/graphics/active-sysroot.txt'
        if marker.is_file():
            sysroot = Path(marker.read_text().strip())
            if (sysroot / 'usr/include/vulkan/vulkan.h').is_file():
                return port.resolve(), sysroot.resolve()
    return None, None


@unittest.skipUnless(sys.platform == 'linux', 'native Linux guest heap mappings')
class DriverHeap(unittest.TestCase):
    def test_checked_mapping_and_failure_paths(self):
        port, sysroot = dependency_port()
        if port is None:
            self.skipTest('Pinned Vulkan development headers unavailable; set MONADO_TEST_SDL_PORT')
        compiler = os.environ.get('MONADO_TEST_CC')
        if not compiler:
            local = port / '.deps/bin/clang-cc'
            compiler = str(local) if local.is_file() else shutil.which('clang')
        if not compiler:
            self.skipTest('Clang is required for the native driver heap fixture')
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('XCDE_', 'LARECOMP_', 'LASRECOMP_', 'LD_'))}
        environment.pop('GLIBC_TUNABLES', None)
        environment.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
        with tempfile.TemporaryDirectory(prefix='monado-native-driver-heap-') as directory:
            binary = Path(directory) / 'driver-heap'
            command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-ffp-contract=off',
                       '-fno-strict-aliasing', '-Wall', '-Wextra', '-Werror',
                       '-I', str(sysroot / 'usr/include'),
                       str(PORT / 'tests/native/test_driver_heap.c'),
                       str(PORT / 'runtime/nvn/vulkan/driver_heap.c'), '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            compiled = subprocess.run(command, env=environment, capture_output=True,
                                      text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary)], cwd=directory, env=environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('driver heap: 40 authored cases PASS', result.stdout)
            self.assertEqual({path.name for path in Path(directory).iterdir()}, {binary.name},
                             'Native fixture must never create game/runtime state')


if __name__ == '__main__':
    unittest.main()
