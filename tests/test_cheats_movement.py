"""LINUX-120: checked party locomotion hook and authored native event cases."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
sys.path.insert(0, str(PORT / 'tools/lifter'))
from lifter import Lifter  # noqa: E402
from patchfmt import PatchMismatch  # noqa: E402
SPEC = importlib.util.spec_from_file_location('movement_cheat_patches', PORT / 'games/xcde/patches.py')
patches = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patches)
SITE, WORD = 0x7000446524, 0xbd002e60


class MovementPatch(unittest.TestCase):
    def fixture(self):
        words = dict(patches.MOVEMENT_CHEAT_CONTEXT)
        words[SITE] = WORD
        lifter = Lifter(0x7000000000, 'c')
        gen = SimpleNamespace(name='main', nso=SimpleNamespace(build_id=patches.MOVEMENT_CHEAT_BUILD_ID),
                              word=words.__getitem__, lift=lambda a: lifter.lift(words[a], a))
        return gen, words

    def test_checked_scalar_store_remains_after_optional_helper(self):
        gen, _ = self.fixture()
        original = gen.lift(SITE).code
        emitted = patches.PATCHES[SITE].apply(gen, SITE)
        self.assertTrue(emitted.endswith(original))
        self.assertEqual(emitted.count(original), 1)
        self.assertLess(emitted.index('xcde_cheats_movement_speed(c)'), emitted.index(original))
        self.assertEqual(patches.PATCHES[SITE].req, 'LINUX-120')

    def test_module_build_and_each_native_contract_reject_changes(self):
        for name, build in [('sdk', patches.MOVEMENT_CHEAT_BUILD_ID), ('main', '0' * 32)]:
            gen, _ = self.fixture(); gen.name = name; gen.nso.build_id = build
            with self.assertRaisesRegex(ValueError, 'checked DE 2.0.0 main'):
                patches.PATCHES[SITE].apply(gen, SITE)
        for address in [SITE, *patches.MOVEMENT_CHEAT_CONTEXT]:
            with self.subTest(address=hex(address)):
                gen, words = self.fixture(); words[address] ^= 1
                with self.assertRaises((ValueError, PatchMismatch)):
                    patches.PATCHES[SITE].apply(gen, SITE)


@unittest.skipUnless(sys.platform == 'linux', 'native Linux movement hook contract')
class MovementNative(unittest.TestCase):
    def test_scalars_native_bonuses_identity_and_fp_environment(self):
        local = PORT / '.deps/bin/clang-cc'
        compiler = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            self.skipTest('Clang required for authored native movement fixture')
        with tempfile.TemporaryDirectory(prefix='monado-cheats-movement-') as directory:
            binary = Path(directory) / 'movement'
            command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-fno-fast-math', '-ffp-contract=off', '-fno-strict-aliasing',
                       str(PORT / 'tests/native/test_cheats_movement.c'),
                       str(PORT / 'runtime/hle/cheats_movement.c'),
                       str(PORT / 'runtime/hle/cheats_options.c'), '-pthread', '-lm', '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            built = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('PASS movement:', ran.stdout)
