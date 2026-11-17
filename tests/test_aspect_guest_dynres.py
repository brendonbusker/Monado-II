"""LINUX-103: native aspects own scene size without falsifying GPU timings."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux virtual-RomFS fixture')
class AspectGuestResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CC') or shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('C11 compiler required')
        cls.directory = tempfile.TemporaryDirectory(prefix='monado-aspect-guest-resolution-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / 'fixture'
        args = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-ffp-contract=off', '-fno-strict-aliasing',
                '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                str(ROOT / 'tests/native/test_aspect_guest_dynres.c'),
                str(ROOT / 'Monado_Linux/runtime/host/xcde_aspect.c'), '-lm', '-pthread', '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            args[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        with tempfile.TemporaryDirectory(dir=self.directory.name) as work:
            env = os.environ.copy()
            for key in ('XCDE_LIBNX', 'XCDE_MODS_DIR', 'XCDE_NO_MODS'):
                env.pop(key, None)
            result = subprocess.run([str(self.binary), name], cwd=work, env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('native aspect guest-resolution policy: PASS', result.stdout)

    def test_all_native_aspects_keep_scene_size_at_every_fps_and_host_resolution(self):
        self.scenario('modes')

    def test_original_and_unknown_modes_preserve_authored_native_behavior(self):
        self.scenario('original')

    def test_mod_omitted_dynamic_key_is_explicitly_disabled_for_native_aspects(self):
        self.scenario('missing')

    def test_lowercase_virtual_overlay_and_exact_guest_path(self):
        self.scenario('mod')

    def test_mixed_case_virtual_overlay_keeps_native_aspect_policy(self):
        self.scenario('mod-mixed')

    def test_mixed_case_virtual_overlay_and_original_input_remain_immutable(self):
        self.scenario('mod-original')

    def test_native_aspect_correctness_owns_dynamic_key_and_preserves_other_overrides(self):
        self.scenario('override')

    def test_comments_malformed_duplicate_and_unterminated_mod_lines_do_not_bypass_policy(self):
        self.scenario('malformed')


if __name__ == '__main__':
    unittest.main()
