"""LINUX-075: native startup policy and real build/startup wiring, no game input."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'Linux RADV compatibility')
class RadvDccNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local = PORT / '.deps/bin/clang-cc'
        compiler = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            raise unittest.SkipTest('Clang required for the native fixture')
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-radv-dcc-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'radv-dcc'
        command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                   str(PORT / 'tests/native/test_radv_dcc_compat.c'), '-o', str(cls.binary)]
        cls.environment = dict(os.environ)
        for key in tuple(cls.environment):
            if key.startswith(('XCDE_', 'LARECOMP_', 'LASRECOMP_')) or key == 'RADV_DEBUG':
                cls.environment.pop(key)
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        result = subprocess.run(command, env=cls.environment, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], env=self.environment,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ' + name, result.stdout)
        self.assertEqual(result.stderr, '')

    def test_append_preserve_and_idempotence(self): self.scenario('append')
    def test_existing_exact_token_is_unchanged(self): self.scenario('existing')
    def test_optout_and_invalid_policy(self): self.scenario('policy')
    def test_allocation_and_environment_failure(self): self.scenario('failures')


class RadvDccWiring(unittest.TestCase):
    def test_before_platform_and_workers_in_actual_graphics_entry(self):
        source = (PORT / 'runtime/host/main_boot.c').read_text()
        call = source.index('if (rt_radv_dcc_prepare(')
        self.assertEqual(source.count('if (rt_radv_dcc_prepare('), 1)
        guarded_start = source.index('if (!rt_paths_init_linux(')
        self.assertLess(guarded_start, call)
        self.assertLess(call, source.index('plat_init(', guarded_start))
        self.assertLess(call, source.index('if (precompile)', guarded_start))
        self.assertIn('#ifdef XCDE_GFX', source[call-600:call])
        self.assertIn('FATAL: RADV DCC compatibility', source[call:call+250])

    def test_actual_nvn_build_compiles_helper(self):
        source = (PORT / 'scripts/build_linux.py').read_text()
        self.assertEqual(source.split().count('vulkan/radv_dcc_compat'), 1)


if __name__ == '__main__':
    unittest.main()
