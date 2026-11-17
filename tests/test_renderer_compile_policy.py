"""LINUX-126: the real object recipe keeps targeted O2, v2 and strict behavior."""
from pathlib import Path
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
SPEC = importlib.util.spec_from_file_location('monado_renderer_compile_policy', PORT / 'scripts/build_linux.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


@unittest.skipUnless(sys.platform == 'linux', 'Linux native build recipe')
class RendererCompilePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('MONADO_TEST_CC')
        if not compiler:
            private = PORT / '.deps/bin/clang-cc'
            compiler = str(private) if private.is_file() else shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('native Clang compiler required')
        cls.compiler = str(Path(shutil.which(compiler) or compiler).absolute())
        result = subprocess.run([cls.compiler, '--version'], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.zig = 'ziglang' in result.stdout

    def test_exact_allowlist_does_not_optimize_guest_or_neighbor_units(self):
        self.assertEqual(build.RENDERER_O2_SOURCES, {
            'runtime/nvn/vulkan/exec.c', 'runtime/nvn/vulkan/textures.c'})
        for name in ('generated/main/main_0.c', 'runtime/simd.h', 'runtime/kernel.c',
                     'runtime/nvn/vulkan/temporal.c', 'runtime/nvn/vulkan/exec.cpp',
                     'runtime/ui/menu_vk.cpp'):
            with self.subTest(source=name):
                self.assertEqual(build.source_policy_flags(name), [])

    def test_actual_compiler_and_receipted_object_argv(self):
        with tempfile.TemporaryDirectory(prefix='monado-renderer-policy-') as temporary:
            directory = Path(temporary)
            adapter = directory / 'adapter.py'
            # Only stock Clang's spelling differs from the production Zig CPU
            # name. Preserve production argv in Builder's actual receipt.
            cpu = '-march=x86_64_v2' if self.zig else '-march=x86-64-v2'
            adapter.write_text('import os,sys\nargs=[' + repr(cpu) +
                ' if arg=="-march=x86_64_v2" else arg for arg in sys.argv[1:]]\n' +
                'os.execv(' + repr(self.compiler) + ',[' + repr(self.compiler) + ',*args])\n')
            driver = directory / 'clang-cc'
            driver.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(adapter)) + ' "$@"\n')
            driver.chmod(0o755)
            for name in ('obj', 'tmp', 'logs'):
                (directory / name).mkdir()
            builder = build.Builder.__new__(build.Builder)
            builder.output = directory
            builder.args = types.SimpleNamespace(keep_going=False)
            builder.lock, builder.failed = threading.Lock(), threading.Event()
            builder.env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                           'TMPDIR': str(directory / 'tmp')}
            builder.cc = builder.cxx = str(driver)
            builder.receipt = {'commands': [], 'objects': {}, 'errors': [], 'dependencies': {}}
            builder.flags = ['-O1', '-UNDEBUG', '-march=x86_64_v2', '-ffp-contract=off', '-fno-strict-aliasing']
            fixture = '''#include <assert.h>
#ifdef NDEBUG
#error assertions disabled
#endif
#ifdef __FAST_MATH__
#error fast math enabled
#endif
#if defined(__FMA__) || defined(__AVX__) || defined(__AVX2__)
#error CPU baseline widened
#endif
#if !defined(__SSE4_2__) || __FINITE_MATH_ONLY__ != 0
#error wrong baseline or finite-only arithmetic
#endif
int renderer_policy_fixture(int a) { assert(a != 123); return a + 1; }
'''
            for relative in ('runtime/nvn/vulkan/exec.c', 'runtime/nvn/vulkan/textures.c',
                             'runtime/nvn/vulkan/temporal.c', 'generated/main/main_0.c'):
                source = directory / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(fixture)
                with mock.patch.object(build, 'ROOT', directory):
                    result = builder.compile(source)
                if result is None:
                    logs = '\n'.join(p.read_text() for p in (directory / 'logs').glob('*.stderr.log'))
                    self.fail(logs)
                command = builder.receipt['commands'][-1]['argv']
                opts = [arg for arg in command if arg in ('-O1', '-O2')]
                expected = '-O2' if relative in build.RENDERER_O2_SOURCES else '-O1'
                self.assertEqual(opts[-1], expected)
                self.assertIn('-march=x86_64_v2', command)
                if expected == '-O2':
                    self.assertLess(command.index('-O2'), len(command) - 1 - command[::-1].index('-UNDEBUG'))
                # Ask the actual driver to show its final cc1 options. This
                # catches optimization/FP option ordering, beyond list matching.
                probe = subprocess.run([*command, '-###'], capture_output=True, text=True, timeout=60)
                self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
                # Zig 0.14.1 maps both requested O1 and O2 to cc1 O2. The
                # explicit source policy documents intent; it is not evidence
                # of additional optimization or an FPS gain on that compiler.
                cc1_expected = '-O2' if self.zig else expected
                self.assertIn('"' + cc1_expected + '"', probe.stderr)
                self.assertIn('"-ffp-contract=off"', probe.stderr)
                symbols = subprocess.check_output(['nm', '-u', str(result)], text=True)
                self.assertIn('__assert_fail', symbols)
            # Assert the optimized macro probe sees the same final policy; Zig
            # otherwise defines NDEBUG automatically for optimized C.
            flags = [*builder.flags, *build.source_policy_flags('runtime/nvn/vulkan/exec.c')]
            macros = subprocess.run([str(driver), *flags, '-dM', '-E', '-x', 'c', '/dev/null'],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(macros.returncode, 0, macros.stderr)
            build.check_correctness_macros(macros.stdout)


if __name__ == '__main__':
    unittest.main()
