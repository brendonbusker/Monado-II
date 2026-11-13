"""LINUX-072: run actual combat hook against authored synthetic native frames."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'

@unittest.skipUnless(sys.platform == 'linux', 'Linux combat hook contract')
class CheatsCombatTests(unittest.TestCase):
    def test_native_events_and_disabled_identity(self):
        local = PORT / '.deps/bin/clang-cc'
        compiler = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            self.skipTest('Clang required for authored native combat fixture')
        source = (PORT / 'runtime/hle/cheats_combat.c').read_text()
        source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include')) + '\n'
        with tempfile.TemporaryDirectory(prefix='monado-cheats-combat-') as directory:
            temporary = Path(directory)
            (temporary / 'combat_production.h').write_text(source)
            binary = temporary / 'combat'
            command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-ffp-contract=off',
                       '-fno-strict-aliasing', '-Wall', '-Wextra', '-Werror',
                       '-I', str(temporary), '-I', str(PORT / 'runtime/hle'),
                       str(PORT / 'tests/native/test_cheats_combat.c'), '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS 8254 combat cases', result.stdout)
