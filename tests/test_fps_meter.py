"""LINUX-094: real-frame FPS sampling, independent of display refreshes."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FpsMeterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CC') or shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('C11 compiler required')
        cls.temp = tempfile.TemporaryDirectory(prefix='monado-fps-meter-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary = Path(cls.temp.name) / ('fps-meter.exe' if sys.platform == 'win32' else 'fps-meter')
        command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-ffp-contract=off',
                   '-Wall', '-Wextra', '-Werror',
                   str(ROOT / 'tests/native/test_fps_meter.c')]
        # Windows CRT supplies math without a separate Unix libm.
        if sys.platform != 'win32':
            command.append('-lm')
        command += ['-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], cwd=self.temp.name,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native FPS meter: PASS', result.stdout)

    def test_zero_clock_warmup_and_reset(self): self.scenario('warmup')
    def test_real_frame_rates_across_supported_targets(self): self.scenario('rates')
    def test_equal_backward_wrapped_and_suspended_clock(self): self.scenario('discontinuities')
    def test_stalls_are_measured_and_value_refresh_is_bounded(self): self.scenario('stalls')
    def test_repeat_and_generated_presentation_reads_do_not_add_frames(self): self.scenario('presentations')
    def test_clock_edges_never_publish_nonfinite_values(self): self.scenario('finite')

    def test_header_is_usable_by_the_cpp_overlay(self):
        compiler = os.environ.get('MONADO_TEST_CXX') or shutil.which('clang++') or shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler required')
        source = ('#include "ui/fps_meter.h"\n'
                  'int main(){FpsMeter meter{};fps_meter_reset(&meter);'
                  'fps_meter_frame(&meter,0);fps_meter_frame(&meter,500000000);'
                  'double value;return fps_meter_value(&meter,&value)&&value==2?0:1;}\n')
        binary = Path(self.temp.name) / ('fps-meter-cpp.exe' if sys.platform == 'win32' else 'fps-meter-cpp')
        command = [compiler, '-x', 'c++', '-std=c++17', '-O1', '-UNDEBUG',
                   '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'Monado_Linux/runtime'),
                   '-', '-o', str(binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
        result = subprocess.run(command, input=source, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
