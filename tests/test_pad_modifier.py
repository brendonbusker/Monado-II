"""Native held-controller chord/camera routing; no SDL or game content."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


class PadModifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local = PORT / '.deps/bin/clang-cc'
        compiler = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            raise unittest.SkipTest('Clang is required for the authored controller routing fixture')
        context = tempfile.TemporaryDirectory(prefix='monado-pad-modifier-')
        cls.addClassCleanup(context.cleanup)
        cls.directory = Path(context.name).resolve()
        cls.binary = cls.directory / ('pad-modifier.exe' if os.name == 'nt' else 'pad-modifier')
        command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                   '-I', str(PORT / 'runtime'), str(ROOT / 'tests/native/test_pad_modifier.c'),
                   '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], cwd=self.directory,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pad modifier: PASS ' + name, result.stdout)
        self.assertEqual({path.name for path in self.directory.iterdir()}, {self.binary.name})

    def test_single_tap_has_native_press_and_release_without_synthetic_pulse(self):
        self.run_case('tap')

    def test_neutral_camera_hold_reaches_native_hud_immediately_and_through_release(self):
        self.run_case('camera')

    def test_selected_shoulder_edges_switch_once_and_stay_masked_until_up(self):
        self.run_case('chords')

    def test_capture_disconnect_remap_toggle_and_explicit_reset_cancel_gestures(self):
        self.run_case('cancel')

    def test_disabled_and_host_test_passthrough_and_reconnect_baseline(self):
        self.run_case('passthrough')

    def test_all_mapped_guest_bits_and_holds_are_independent_of_poll_rate(self):
        self.run_case('mapping')


if __name__ == '__main__':
    unittest.main()
