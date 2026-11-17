"""LINUX-129: authored true enemy HP lifecycle and arithmetic fixtures."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'native Linux enemy health adapter')
class EnemyHealthNative(unittest.TestCase):
    def test_lifetime_fractions_floors_bounds_and_native_cpu_state(self):
        local = PORT / '.deps/bin/clang-cc'
        cc = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not cc:
            self.skipTest('Clang required for authored native enemy HP fixture')
        with tempfile.TemporaryDirectory(prefix='monado-enemy-health-') as name:
            binary = Path(name) / 'enemy-health'
            command = [cc, '-std=gnu11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-fno-fast-math', '-ffp-contract=off', '-fno-strict-aliasing',
                       str(PORT / 'tests/native/test_cheats_enemy_health.c'),
                       str(PORT / 'runtime/hle/cheats_enemy_health.c'),
                       str(PORT / 'runtime/hle/cheats_options.c'), '-pthread', '-lm', '-Wl,--no-gc-sections', '-o', str(binary)]
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith(('LD_', 'XCDE_', 'LARECOMP_', 'LASRECOMP_'))}
            environment.pop('GLIBC_TUNABLES', None)
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            built = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('PASS enemy health:', ran.stdout)


if __name__ == '__main__':
    unittest.main()
