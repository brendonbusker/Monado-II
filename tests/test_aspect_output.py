"""LINUX-089: real settings, output sizing and native UI canvas integration."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'Linux native aspect/config integration')
class AspectOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CC') or shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('Clang required for production runtime headers')
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-aspect-output-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'aspect-output'
        cls.environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
        sources = [ROOT / 'tests/native/test_aspect_output.c',
                   *[PORT / name for name in ('runtime/host/settings_ini.c', 'runtime/host/stubs_gfx.c',
                                              'runtime/host/xcde_aspect.c', 'runtime/nvn/output_scale.c')]]
        command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-ffp-contract=off', '-fno-strict-aliasing',
                   '-ffunction-sections', '-fdata-sections', '-I', str(PORT / 'runtime'),
                   *map(str, sources), '-Wl,--gc-sections', '-lm', '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        result = subprocess.run(command, env=cls.environment, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        with tempfile.TemporaryDirectory(prefix='config-', dir=self.temporary.name) as state:
            result = subprocess.run([str(self.binary), name], cwd=state, env=self.environment,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('native aspect output/config integration: PASS', result.stdout)
            self.assertLessEqual({p.name for p in Path(state).iterdir()}, {'aspect.ini'})

    def test_missing_invalid_and_reload_preferences_keep_original(self): self.scenario('defaults')
    def test_native_original_roundtrip_and_other_settings_preserved(self): self.scenario('roundtrip')
    def test_original_viewport_and_dlaa_rounding_match_exact_goldens(self): self.scenario('original')
    def test_native_16_10_21_9_32_9_extents_across_bases(self): self.scenario('native')
    def test_explicit_ratios_fit_other_monitors_and_remain_selected_on_resize(self): self.scenario('explicit')
    def test_explicit_ratios_keep_dlaa_sr_spatial_canvas_and_cap_contracts(self): self.scenario('explicit-quality')
    def test_dlaa_native_sr_quality_and_spatial_resolution_contracts(self): self.scenario('quality')
    def test_unsupported_shapes_fallback_and_texture_caps(self): self.scenario('bounds')
    def test_uniform_centered_canvas_and_rejected_invalid_inputs(self): self.scenario('canvas')


if __name__ == '__main__':
    unittest.main()
