"""LINUX-072: actual authored reward wrapper/config-off/ABI component tests."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'native Linux reward wrapper contract')
class CheatsRewardsTests(unittest.TestCase):
    def test_native_reward_wrapper_and_gold(self):
        compiler = os.environ.get('MONADO_TEST_CC')
        local = PORT / '.deps/bin/clang-cc'
        compiler = compiler or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            self.skipTest('Clang is required for the native reward fixture')
        fixture = PORT / 'tests/native/test_cheats_rewards.c'
        source = PORT / 'runtime/hle/cheats_rewards.c'
        with tempfile.TemporaryDirectory(prefix='monado-cheat-rewards-') as directory:
            for flags in ([], ['-fsanitize=undefined', '-fno-sanitize-recover=all']):
                output = Path(directory) / ('rewards-ubsan' if flags else 'rewards')
                command = [compiler, '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror',
                           '-fno-fast-math', '-ffp-contract=off', *flags,
                           str(fixture), str(source), '-o', str(output)]
                built = subprocess.run(command, text=True, capture_output=True, timeout=90)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                ran = subprocess.run([str(output)], text=True, capture_output=True, timeout=30)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                self.assertIn('PASS rewards', ran.stdout)
