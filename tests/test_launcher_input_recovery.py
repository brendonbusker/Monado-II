"""Native input-picker stdout, cancellation, UTF-8 and pre-SDL argument guards."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeInputRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CXX') or shutil.which('c++')
        include = os.environ.get('MONADO_TEST_SDL_INCLUDE')
        if not compiler or not include:
            raise unittest.SkipTest('MONADO_TEST_CXX and MONADO_TEST_SDL_INCLUDE are required')
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-input-picker-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'input-picker'
        result = subprocess.run([compiler, '-std=c++17', '-O1', '-UNDEBUG', '-pthread',
                                 '-Wall', '-Wextra', '-Werror', '-I', include,
                                 str(ROOT / 'tests/native/test_launcher_input_recovery.cpp'),
                                 '-o', str(cls.binary)], capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Native locator fixture failed to compile:\n' + result.stdout + result.stderr)

    def run_picker(self, *args, mode='select', forbid_init=False):
        environment = os.environ.copy()
        environment['MONADO_LOCATOR_FIXTURE'] = mode
        if forbid_init:
            environment['MONADO_LOCATOR_FORBID_INIT'] = '1'
        return subprocess.run([str(self.binary), '--locate-game-files', *args],
                              env=environment, capture_output=True, timeout=10)

    def test_exact_utf8_nul_protocol_and_missing_path_with_spaces(self):
        for args in [(), ('--missing-input', '/tmp/Old Game Files')]:
            with self.subTest(args=args):
                result = self.run_picker(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '/tmp/Recovered Game Files/日本語\0'.encode())
                self.assertEqual(result.stderr, b'')

    def test_cancel_is_empty_success(self):
        result = self.run_picker(mode='cancel')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))

    def test_error_invalid_selection_and_multiple_selection_never_emit_path(self):
        for mode in ['error', 'relative', 'multiple']:
            with self.subTest(mode=mode):
                result = self.run_picker(mode=mode)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b'')
                self.assertTrue(result.stderr)

    def test_invalid_arguments_rejected_before_sdl_initialization(self):
        for args in [('--unknown',), ('--missing-input',), ('--missing-input', 'relative'),
                     ('--missing-input', '/tmp/line\nfeed'), ('--unknown', '/tmp/a'),
                     ('--missing-input', '/tmp/a', '--extra', 'value')]:
            with self.subTest(args=args):
                result = self.run_picker(*args, forbid_init=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, b'')

    def test_utf8_controls_and_protocol_length_boundary(self):
        result = subprocess.run([str(self.binary), '--test-validation'], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
