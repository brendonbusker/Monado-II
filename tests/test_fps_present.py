"""LINUX-094: actual presentation control flow with authored Vulkan/FG mocks."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'Linux presentation fixture')
class FpsPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CC') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('native C compiler required')
        active = PORT / '.deps/graphics/active-sysroot.txt'
        include = Path(active.read_text().strip()) / 'usr/include' if active.exists() else Path('/usr/include')
        if not (include / 'vulkan/vulkan.h').is_file():
            raise unittest.SkipTest('Vulkan headers required for actual WSI types')
        spec = importlib.util.spec_from_file_location('fps_wsi_fixture', PORT / 'scripts/framegen_presentation_tests_linux.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        cls.temp = tempfile.TemporaryDirectory(prefix='monado-fps-present-')
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = (PORT / 'runtime/nvn/vulkan/device.c').read_text()
        start = source.index('void vk_frame_end(const char *shot_path) {')
        end = source.index('\nvoid vk_save_png(', start)
        body = directory / 'frame-end.inc'
        body.write_text(source[start:end])
        authored = directory / 'fixture.c'
        authored.write_text(fixture.HARNESS.replace('PACING_HEADER', str(PORT / 'runtime/nvn/vulkan/framegen_pacing_linux.h'))
                            .replace('FRAME_END_SOURCE', str(body)))
        cls.binaries = {}
        for generated in (False, True):
            binary = directory / ('generated' if generated else 'ordinary')
            command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-ffp-contract=off', '-fno-strict-aliasing',
                       '-I' + str(include), *(['-DXCDE_LINUX_FRAMEGEN'] if generated else []),
                       str(authored), '-lm', '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binaries[generated] = binary

    def scenario(self, generated, mode, enabled):
        command = [str(self.binaries[generated]), str(mode), *(['--overlay'] if enabled else [])]
        result = subprocess.run(command, cwd=self.temp.name, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('passed', result.stdout)
        if enabled:
            self.assertIn('OVERLAY draws=', result.stdout)

    def test_disabled_ordinary_capture_and_hash_keep_existing_output(self):
        for mode in (0, 6, 7):
            with self.subTest(mode=mode): self.scenario(False, mode, False)

    def test_enabled_ordinary_capture_and_hash_include_counter(self):
        for mode in (0, 6, 7):
            with self.subTest(mode=mode): self.scenario(False, mode, True)

    def test_disabled_framegen_retains_all_pacing_and_recovery_scenarios(self):
        for mode in range(22):
            with self.subTest(mode=mode): self.scenario(True, mode, False)

    def test_counter_follows_generation_with_clean_retained_input_and_both_outputs(self):
        for mode in range(22):
            with self.subTest(mode=mode): self.scenario(True, mode, True)


if __name__ == '__main__':
    unittest.main()
