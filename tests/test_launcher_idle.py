"""LINUX-126: launcher pacing policy contracts; actual loop fixture is native SDL."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherIdlePolicy(unittest.TestCase):
    def test_bounded_painting_preserves_foreground_and_service_deadlines(self):
        compiler = os.environ.get('MONADO_TEST_CXX') or shutil.which('clang++') or shutil.which('c++')
        if not compiler:
            self.skipTest('C++17 compiler unavailable')
        with tempfile.TemporaryDirectory(prefix='monado-launcher-idle-') as temporary:
            binary = Path(temporary) / 'idle-policy'
            command = [compiler, '-std=c++17', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       str(ROOT / 'tests/native/test_launcher_idle_policy.cpp'), '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            result = subprocess.run(command, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('oversleep PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
