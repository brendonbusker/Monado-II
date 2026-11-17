"""LINUX-126: scheduling/queue fixtures; diagnostic overrides are direct-executable only.

XCDE_SHADER_WORKERS / XCDE_SHADER_BACKGROUND are intentionally not inherited
through the launcher environment. Ordinary builds require no environment flags.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'Linux owned-worker scheduling')
class ShaderWorkerPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CC')
        if not compiler:
            private = PORT / '.deps/bin/clang-cc'
            compiler = str(private) if private.is_file() else shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('native Clang compiler required')
        cls.directory = tempfile.TemporaryDirectory(prefix='monado-shader-workers-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.output = Path(cls.directory.name)
        source = (PORT / 'runtime/nvn/vulkan/exec.c').read_text()
        section = source.split('#include "shader_worker_policy.h"', 1)[1]
        section = '#include "shader_worker_policy.h"' + section.split('// ================================================================== state', 1)[0]
        (cls.output / 'shader_worker_section_fixture.h').write_text(section)
        source = (PORT / 'runtime/platform/linux.c').read_text()
        section = 'void plat_thread_shader_background(void)' + source.split('void plat_thread_shader_background(void)', 1)[1]
        section = section.split('void plat_thread_audio(void)', 1)[0]
        (cls.output / 'shader_priority_section_fixture.h').write_text(section)
        cls.binaries = {}
        for name, fixture, flags in (
                ('policy', 'test_shader_worker_policy.c', []), ('queue', 'test_shader_worker_queue.c', []),
                ('priority', 'test_shader_worker_priority.c', []),
                ('real-priority', 'test_shader_worker_priority.c', ['-DREAL_PRIORITY=1'])):
            binary = cls.output / name
            command = [compiler, '-O1', '-UNDEBUG', '-pthread', '-ffp-contract=off', *flags,
                       '-I', str(PORT / 'runtime/nvn/vulkan'), '-I', str(cls.output),
                       str(ROOT / 'tests/native' / fixture), '-o', str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binaries[name] = binary
        # Preserve two historical failure modes as executable negative
        # controls, using the same queue fixture and readiness oracles.
        normal = (cls.output / 'shader_worker_section_fixture.h').read_text()
        mutations = {
            'no-completion-wake': ('if (!atomic_load(&g_jobs_busy)) pthread_cond_broadcast(&jobs_cond);',
                                   '/* missing completion notification */'),
            'no-create-fallback': ('pthread_mutex_lock(&jobs_lock);\n                jobs_separate_refinement = false;',
                                   'pthread_mutex_lock(&jobs_lock);\n                /* missing fallback */'),
        }
        for name, (before, after) in mutations.items():
            if normal.count(before) != 1:
                raise AssertionError('negative control no longer matches one production site: ' + name)
            altered = cls.output / name
            altered.mkdir()
            (altered / 'shader_worker_section_fixture.h').write_text(normal.replace(before, after, 1))
            binary = altered / 'queue'
            command = [compiler, '-O1', '-UNDEBUG', '-pthread', '-ffp-contract=off',
                       '-I', str(altered), '-I', str(PORT / 'runtime/nvn/vulkan'),
                       str(ROOT / 'tests/native/test_shader_worker_queue.c'), '-o', str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binaries[name] = binary

    def scenario(self, binary, name):
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
        result = subprocess.run([str(self.binaries[binary]), name], cwd=self.output, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)

    def test_counts_small_integrated_only_and_bounded_overrides(self):
        self.scenario('policy', 'all')

    def test_actual_queues_preserve_required_job_readiness_and_failures(self):
        for name in ('default', 'desktop', 'override2', 'override4', 'background-off',
                     'busy-gates-low', 'urgent-during-low', 'readiness-steal',
                     'fail-refine', 'fail-all', 'sync', 'inline'):
            with self.subTest(scenario=name):
                self.scenario('queue', name)

    def test_priority_is_once_per_owned_thread_and_denials_are_nonfatal(self):
        for name in ('normal', 'already-lower', 'get-denied', 'set-denied', 'tid-denied'):
            with self.subTest(scenario=name):
                self.scenario('priority', name)
        self.scenario('real-priority', 'real-tid-isolation')

    def test_missing_completion_wake_and_creation_fallback_fail_same_oracles(self):
        for binary, scenario in (('no-completion-wake', 'busy-gates-low'), ('no-create-fallback', 'fail-refine')):
            with self.subTest(binary=binary):
                result = subprocess.run([str(self.binaries[binary]), scenario], cwd=self.output,
                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'},
                    capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
