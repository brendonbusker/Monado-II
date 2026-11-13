"""LINUX-072: actual runtime configuration and overflow-safe percentage arithmetic."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'native Linux runtime settings')
class CheatsSettings(unittest.TestCase):
    def test_actual_parser_serializer_and_arithmetic(self):
        local = PORT / '.deps/bin/clang-cc'
        cc = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not cc:
            self.skipTest('Clang required for native settings fixture')
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('XCDE_', 'LARECOMP_', 'LASRECOMP_', 'LD_'))}
        env.pop('GLIBC_TUNABLES', None)
        with tempfile.TemporaryDirectory(prefix='monado-cheats-settings-') as directory:
            binary = Path(directory) / 'settings'
            args = [cc, '-std=c11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                    str(PORT / 'tests/native/test_cheats_settings.c'),
                    str(PORT / 'runtime/host/settings_ini.c'), '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                args[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            built = subprocess.run(args, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary), str(Path(directory) / 'xcde.ini')], cwd=directory,
                                 env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('100050 arithmetic cases PASS', ran.stdout)


if __name__ == '__main__':
    unittest.main()
