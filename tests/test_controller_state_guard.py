"""LINUX-077: actual Landlock HIDAPI admission in a private device namespace."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


@unittest.skipUnless(sys.platform == 'linux', 'Linux controller device policy')
class ControllerStateGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        local = PORT / '.deps/bin/clang-cc'
        compiler = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            raise unittest.SkipTest('Clang required for native state guard')
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-controller-guard-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.binary = cls.folder / 'controller-guard'
        command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                   str(ROOT / 'tests/native/test_controller_state_guard.c'), '-o', str(cls.binary)]
        cls.environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        result = subprocess.run(command, env=cls.environment, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_only_strict_hidraw_names(self):
        result = subprocess.run([str(self.binary), 'names'], env=self.environment,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS names', result.stdout)

    def scenario(self, kind):
        bwrap = shutil.which('bwrap')
        if not bwrap:
            self.skipTest('bwrap required for isolated synthetic devices')
        with tempfile.TemporaryDirectory(prefix='case-', dir=self.folder) as temporary:
            case = Path(temporary); state = case / 'state'; state.mkdir()
            protected = case / 'game-input'; protected.write_bytes(b'authored read-only game input sentinel')
            node = '/dev/hidraw999' if kind != 'malformed' else '/dev/hidraw999x'
            command = [bwrap, '--unshare-user', '--unshare-pid', '--unshare-net', '--die-with-parent',
                       '--new-session', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
                       '--bind', str(case), str(case)]
            if kind == 'regular':
                command += ['--bind', str(protected), node]
            elif kind == 'symlink':
                command += ['--dev-bind', '/dev/full', '/dev/fixture-node', '--symlink', '/dev/fixture-node', node]
            else:
                command += ['--dev-bind', '/dev/full', node]
            action = 'allow' if kind == 'valid' else 'inherit' if kind == 'inherit' else 'deny'
            command += ['--', str(self.binary), action, str(state), str(protected), node]
            result = subprocess.run(command, env=self.environment, capture_output=True, text=True, timeout=20)
            if result.returncode and ('No permissions to create a new namespace' in result.stderr or
                                      'Creating new namespace failed' in result.stderr):
                if os.environ.get('MONADO_REQUIRE_CONTROLLER_GUARD_NAMESPACE') == '1':
                    self.fail(result.stdout + result.stderr)
                self.skipTest('host sandbox denies nested bwrap/user namespaces')
            if result.returncode == 77:
                self.skipTest('host lacks required Landlock ABI >=3')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS ' + action, result.stdout)
            self.assertEqual(protected.read_bytes(), b'authored read-only game input sentinel')
            self.assertEqual(list(state.iterdir()), [])

    def test_replaced_input_path_retains_read_only_fallback_without_new_write_rights(self):
        # Authored ordinary-file stand-in: exercise filesystem access only, no
        # evdev events, actual devices, host mounts, game inputs or profiles.
        bwrap = shutil.which('bwrap')
        if not bwrap:
            self.skipTest('bwrap required for isolated synthetic input directory')
        with tempfile.TemporaryDirectory(prefix='replacement-', dir=self.folder) as temporary:
            case = Path(temporary); state = case/'state'; state.mkdir()
            devices = case/'devices'; devices.mkdir()
            future = devices/'event999.pending'; future.write_bytes(b'authored future')
            command = [bwrap, '--unshare-user', '--unshare-pid', '--unshare-net',
                       '--die-with-parent', '--new-session', '--ro-bind', '/', '/',
                       '--dev', '/dev', '--proc', '/proc', '--bind', str(case), str(case),
                       '--bind', str(devices), '/dev/input', '--', str(self.binary),
                       'replacement', str(state), '/dev/input/event999']
            result = subprocess.run(command, env=self.environment, capture_output=True,
                                    text=True, timeout=20)
            if result.returncode and ('No permissions to create a new namespace' in result.stderr or
                                      'Creating new namespace failed' in result.stderr):
                if os.environ.get('MONADO_REQUIRE_CONTROLLER_GUARD_NAMESPACE') == '1':
                    self.fail(result.stdout+result.stderr)
                self.skipTest('host sandbox denies nested bwrap/user namespaces')
            if result.returncode == 77:
                self.skipTest('host lacks required Landlock ABI >=3')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('PASS replacement remains read-only', result.stdout)
            self.assertEqual((devices/'event999').read_bytes(), b'authored future')
            self.assertEqual(list(state.iterdir()), [])

    def test_existing_character_hidraw_is_admitted(self): self.scenario('valid')
    def test_prefix_lookalike_is_not_admitted(self): self.scenario('malformed')
    def test_hidraw_symlink_is_not_admitted(self): self.scenario('symlink')
    def test_hidraw_regular_file_is_not_admitted(self): self.scenario('regular')
    def test_inherited_writable_file_is_still_rejected(self): self.scenario('inherit')


if __name__ == '__main__':
    unittest.main()
