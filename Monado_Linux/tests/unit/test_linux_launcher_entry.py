"""[XCDE] LINUX-009: synthetic launcher identity, paths, controls and ownership."""
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    spec = importlib.util.spec_from_file_location('launcher_linux', ROOT / 'scripts/launcher_linux.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
finally:
    sys.path.pop(0)


@unittest.skipUnless(sys.platform == 'linux', 'Linux launcher entry')
class LauncherEntryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='monado-launcher-entry-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'Monado_Linux'
        self.root.mkdir()
        self.input = self.base / 'game_files'
        (self.input / 'exefs').mkdir(parents=True)
        (self.input / 'romfs').mkdir()
        self.state = self.root / 'play/session'
        self.desktop_runtime = self.base / 'desktop-runtime'
        self.desktop_runtime.mkdir(mode=0o700)
        environment = mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.desktop_runtime)})
        environment.start(); self.addCleanup(environment.stop)
        for module in (launcher, launcher.run_linux):
            patch = mock.patch.object(module, 'ROOT', self.root)
            patch.start(); self.addCleanup(patch.stop)
        self.sysroot = self.root / '.deps/graphics/sysroots/test'
        (self.sysroot / 'usr/lib/x86_64-linux-gnu').mkdir(parents=True)
        (self.sysroot / '.monado-deps.json').write_text(json.dumps({'lock_sha256': 'lock'}))
        self.gui = self.binary('gui', gui=True)
        self.game = self.binary('game', gui=False)

    def binary(self, name, *, gui):
        path = self.root / 'build' / name / name
        path.parent.mkdir(parents=True)
        header = bytearray(64); header[:6] = b'\x7fELF\x02\x01'; header[18:20] = (62).to_bytes(2, 'little')
        path.write_bytes(header); path.chmod(0o700)
        receipt = {'status': 'passed', 'executable': {'path': str(path), 'sha256': hashlib.sha256(header).hexdigest()},
                   'dependencies': {'sysroot': str(self.sysroot)},
                   'sources_before': {'graphics-deps-linux.lock.json': 'lock'}}
        if gui:
            receipt['artifact_kind'] = 'linux-launcher'
        else:
            receipt['generated'] = {'generated/synthetic/main_0.c': 'synthetic'}
        (path.parent / 'receipt.json').write_text(json.dumps(receipt))
        return path

    def argv(self, *extra):
        return ['--launcher-executable', str(self.gui), '--game-executable', str(self.game),
                '--state-root', str(self.state), *map(str, extra)]

    def prepare(self, *extra):
        return launcher.prepare(launcher.arguments(self.argv(*extra))[1])

    def test_normal_plan_has_no_test_overrides_and_creates_no_state(self):
        plan = self.prepare()
        self.assertNotIn('--test-child-env', plan['argv'])
        self.assertEqual(plan['test_controls'], {})
        self.assertFalse(self.state.exists())
        self.assertIn(str(self.game), plan['argv'])
        self.assertNotIn('execution_argv', plan)
        self.assertNotIn('runtime_environment', plan)

    def enable_dlss(self):
        path = self.game.parent / 'receipt.json'
        receipt = json.loads(path.read_text())
        receipt['dlss_enabled'] = True
        receipt['runtime_resources'] = {}
        for name in ('libmonado-ngx.so', 'libnvidia-ngx-dlss.so.310.9.1', 'NVIDIA-DLSS-LICENSE.txt'):
            resource = self.game.parent / name
            resource.write_bytes(('synthetic ' + name).encode())
            receipt['runtime_resources'][name] = {'path': str(resource), 'bytes': resource.stat().st_size,
                'sha256': hashlib.sha256(resource.read_bytes()).hexdigest()}
        path.write_text(json.dumps(receipt))

    def test_dlss_wraps_gui_before_guard_and_keeps_selection_argv(self):
        self.enable_dlss()
        calls = []
        def namespace(argv, state, *, pid_namespace=True):
            calls.append((argv, state, pid_namespace))
            return ['/synthetic/bwrap', '--', *argv], {'x11_socket_bind': False}
        with mock.patch.object(launcher.run_linux, 'private_tmp_alias', return_value=False), \
             mock.patch.object(launcher.run_linux, 'dlss_namespace', side_effect=namespace):
            plan = self.prepare()
        self.assertEqual(plan['argv'][0], str(self.gui))
        self.assertEqual(plan['argv'][plan['argv'].index('--game-executable') + 1], str(self.game))
        self.assertEqual(plan['execution_argv'], ['/synthetic/bwrap', '--', *plan['argv']])
        self.assertEqual(calls[-1], (plan['argv'], self.state, False))
        self.assertFalse(self.state.exists())

    def test_dlss_inside_existing_alias_does_not_wrap_again(self):
        self.enable_dlss()
        with mock.patch.object(launcher.run_linux, 'private_tmp_alias', return_value=True), \
             mock.patch.object(launcher.run_linux, 'dlss_namespace', side_effect=AssertionError('nested namespace')):
            plan = self.prepare()
        self.assertNotIn('execution_argv', plan)
        self.assertFalse(self.state.exists())

    def test_dry_run_checks_input_but_never_opens_state_or_spawns_gui(self):
        with mock.patch.object(launcher, 'check_input', return_value='synthetic checker passed') as checker, \
             mock.patch.object(launcher, 'wait_session') as wait, \
             mock.patch.object(launcher, 'acquire_lock') as lock, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.main(self.argv('--dry-run')), 0)
        checker.assert_called_once_with(str(self.input)); wait.assert_not_called(); lock.assert_not_called()
        self.assertFalse(self.state.exists()); self.assertEqual(json.loads(output.getvalue())['state'], str(self.state))

    def test_normal_start_logs_verified_game_selection_before_gui(self):
        # Give the two synthetic ELFs different hashes so logging the GUI hash
        # by mistake cannot satisfy the game-identity assertion.
        self.game.write_bytes(self.game.read_bytes() + b'game-selection')
        receipt_path = self.game.parent / 'receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['executable']['sha256'] = hashlib.sha256(self.game.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        def inspect_selection(argv, environment, lock_fd, log_fd, *, updates, runtime_fd):
            self.assertIsNone(updates)
            self.assertEqual(fcntl.fcntl(runtime_fd, fcntl.F_GETFL) & os.O_ACCMODE, os.O_RDONLY)
            with self.assertRaises(BlockingIOError):
                launcher.install_lease.acquire_maintenance(self.root)
            lines = (self.state / 'logs/launcher-console.log').read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith('[launcher-selection] '))
            selection = json.loads(lines[0].removeprefix('[launcher-selection] '))
            self.assertEqual(selection, {'game_executable': str(self.game),
                                        'game_sha256': hashlib.sha256(self.game.read_bytes()).hexdigest()})
            self.assertEqual(argv[argv.index('--game-executable') + 1], str(self.game))
            return 0
        with mock.patch.object(launcher, 'check_input', return_value='synthetic checker passed'), \
             mock.patch.object(launcher.run_linux, 'validate_runtime', return_value={'status': 'passed'}) as runtime, \
             mock.patch.object(launcher, 'wait_session', side_effect=inspect_selection) as wait:
            self.assertEqual(launcher.main(self.argv()), 0)
        wait.assert_called_once()
        self.assertEqual(runtime.call_count, 4)  # Revalidate after startup maintenance/admission.

    def test_runtime_failure_prevents_state_lock_logs_and_gui(self):
        with mock.patch.object(launcher, 'check_input', return_value='synthetic checker passed'), \
             mock.patch.object(launcher.run_linux, 'validate_runtime', side_effect=ValueError('authored missing runtime ABI')), \
             mock.patch.object(launcher, 'acquire_lock') as lock, \
             mock.patch.object(launcher, 'wait_session') as wait, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            launcher.main(self.argv())
        self.assertEqual(stopped.exception.code, 1)
        lock.assert_not_called(); wait.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_wrong_artifact_and_incomplete_game_are_rejected(self):
        for target, changes in ((self.gui, {'artifact_kind': 'wrong'}), (self.game, {'generated': {}})):
            path = target.parent / 'receipt.json'; original = path.read_text(); receipt = json.loads(original)
            receipt.update(changes); path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError): self.prepare()
            path.write_text(original)
        with self.assertRaises(ValueError):
            launcher.prepare(launcher.arguments(self.argv('--game-executable', self.gui))[1])

    def test_altered_elf_cannot_launch(self):
        self.gui.write_bytes(self.gui.read_bytes() + b'altered')
        with self.assertRaisesRegex(ValueError, 'receipt'): self.prepare()
        self.assertFalse(self.state.exists())

    def test_failed_receipt_cannot_launch(self):
        path = self.gui.parent / 'receipt.json'; receipt = json.loads(path.read_text())
        receipt['status'] = 'failed'; path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'receipt'): self.prepare()
        self.assertFalse(self.state.exists())

    def test_overlapping_or_outside_state_rejected_without_writes(self):
        for state in (self.input, self.input / 'state', self.base, self.root / 'build/game/state'):
            with self.subTest(state=state), self.assertRaises(ValueError):
                launcher.prepare(launcher.arguments(self.argv('--state-root', state))[1])

    def test_state_symlink_hardlink_and_fifo_rejected(self):
        self.state.mkdir(parents=True)
        outsider = self.base / 'original'; outsider.write_text('preserve')
        link = self.state / 'entry'
        link.symlink_to(outsider)
        with self.assertRaises(ValueError): self.prepare()
        link.unlink(); os.link(outsider, link)
        with self.assertRaises(ValueError): self.prepare()
        link.unlink(); os.mkfifo(link)
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(outsider.read_text(), 'preserve')

    def test_internal_symlinks_and_symlink_parents_also_rejected(self):
        self.state.mkdir(parents=True)
        (self.state / 'original').write_text('safe')
        (self.state / 'link').symlink_to(self.state / 'original')
        with self.assertRaises(ValueError): self.prepare()
        (self.state / 'link').unlink()
        alias = self.root / 'runs'; alias.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(ValueError):
            launcher.prepare(launcher.arguments(self.argv('--state-root', alias / 'nested'))[1])

    def test_lock_conflict_and_release(self):
        first = launcher.acquire_lock(self.state)
        try:
            with self.assertRaisesRegex(ValueError, 'already using'):
                launcher.acquire_lock(self.state)
        finally:
            os.close(first)
        second = launcher.acquire_lock(self.state); os.close(second)
        self.assertEqual((self.state / '.session.lock').stat().st_mode & 0o777, 0o600)

    def test_lock_and_log_open_reject_aliases(self):
        self.state.mkdir(parents=True)
        original = self.base / 'preserve'; original.write_text('preserve')
        lock = self.state / '.session.lock'; os.link(original, lock)
        with self.assertRaises(ValueError): launcher.acquire_lock(self.state)
        lock.unlink(); lock.symlink_to(original)
        with self.assertRaises(ValueError): launcher.acquire_lock(self.state)
        directory = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(OSError): launcher.regular_open(directory, '.session.lock', os.O_WRONLY | os.O_APPEND)
        finally:
            os.close(directory)
        self.assertEqual(original.read_text(), 'preserve')

    def test_test_controls_require_script_and_safe_whitelist(self):
        with self.assertRaisesRegex(ValueError, 'require --ui-script'):
            self.prepare('--test-child-env', 'XCDE_EXIT_AFTER_SHOTS=1')
        self.state.mkdir(parents=True); script = self.state / 'events.txt'; script.write_text('3 quit\n')
        for control in ('XCDE_STRICT=0', 'XCDE_INI=/tmp/other', 'XCDE_USAGE=/tmp/escape',
                        'XCDE_SHOTS=30:../escape.png', 'LARECOMP_AUDIO_GAIN=nan', 'XCDE_DUP_CHECK=0',
                        'XCDE_TRACE_PRESENT=20:10', 'XCDE_STALL=-1'):
            with self.subTest(control=control), self.assertRaises(ValueError):
                self.prepare('--ui-script', script, '--test-child-env', control)
        plan = self.prepare('--ui-script', script, '--test-exit-after-child', '--test-child-env',
                            'XCDE_SHOTS=30:build/capture.png', '--test-child-env', 'LARECOMP_AUDIO_GAIN=0')
        self.assertIn('--test-exit-after-child', plan['argv'])

    def test_shot_and_script_must_be_inside_state(self):
        with self.assertRaises(ValueError): self.prepare('--shot', '/tmp/escape.bmp')
        with self.assertRaises(ValueError): self.prepare('--shot-frame', '7')
        with self.assertRaises(ValueError): self.prepare('--ui-script', self.state / 'missing')
        plan = self.prepare('--shot', 'build/window.bmp', '--shot-frame', '7', '--shot-tab', '2')
        self.assertIn(str(self.state / 'build/window.bmp'), plan['argv'])
        self.assertFalse(self.state.exists())

    def test_environment_removes_runtime_and_loader_injection(self):
        with mock.patch.dict(os.environ, {'XCDE_STRICT': '0', 'LARECOMP_WINDOW': '10x10', 'LD_PRELOAD': '/tmp/evil',
                                         'LD_LIBRARY_PATH': '/tmp/other', 'MONADO_STATE_ROOT': '/tmp/state',
                                         'HTTPS_PROXY': 'unwanted', 'DISPLAY': ':synthetic'}):
            env = launcher.clean_environment('/verified/library')
            self.assertEqual(env['SDL_APP_ID'], 'monado-linux-port')
        self.assertEqual(env['LD_LIBRARY_PATH'], '/verified/library')
        self.assertEqual(env['DISPLAY'], ':synthetic')
        for key in ('XCDE_STRICT', 'LARECOMP_WINDOW', 'LD_PRELOAD', 'MONADO_STATE_ROOT', 'HTTPS_PROXY'):
            self.assertNotIn(key, env)

    def session_test(self, *, terminate_wrapper=False):
        # Dedicated helper isolates subreaper/signal state from unittest itself.
        self.state.mkdir(parents=True)
        ready, done = self.state / 'ready', self.state / 'done'
        gui = self.state / 'synthetic_gui.py'
        gui.write_text('import os,time\nfrom pathlib import Path\n'
                       'pid=os.fork()\n'
                       'if pid==0:\n os.setsid()\n time.sleep(.45)\n Path(' + repr(str(done)) + ').write_text("done")\n os._exit(0)\n'
                       'Path(' + repr(str(ready)) + ').write_text(str(pid))\n'
                       'time.sleep(.12)\nos._exit(0)\n')
        helper = self.state / 'wrapper.py'
        helper.write_text('import os,sys\nfrom pathlib import Path\n'
                          'sys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ')\nimport launcher_linux as m\n'
                          'm.ROOT=Path(' + repr(str(self.root)) + ')\n'
                          'fd=m.acquire_lock(Path(' + repr(str(self.state)) + '))\n'
                          'runtime=m.install_lease.acquire_runtime(m.ROOT)\n'
                          'log=os.open(' + repr(str(self.state / 'console.log')) + ',os.O_WRONLY|os.O_CREAT,0o600)\n'
                          'code=m.wait_session([sys.executable,' + repr(str(gui)) + '],dict(os.environ),fd,log,runtime_fd=runtime)\n'
                          'os.close(log);os.close(fd);os.close(runtime);sys.exit(code)\n')
        process = subprocess.Popen([sys.executable, '-B', str(helper)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                if process.poll() is not None: break
                time.sleep(.01)
            self.assertTrue(ready.exists())
            if terminate_wrapper:
                process.send_signal(signal.SIGTERM)
            # GUI exits after .12s, adopted child remains to .45s. Wrapper holds
            # lock until that child's natural completion, without killing it.
            time.sleep(.20)
            self.assertIsNone(process.poll())
            with self.assertRaisesRegex(ValueError, 'already using'): launcher.acquire_lock(self.state)
            with self.assertRaises(BlockingIOError): launcher.install_lease.acquire_maintenance(self.root)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143 if terminate_wrapper else 0, (stdout, stderr))
            self.assertTrue(done.exists())
            with self.assertRaises(ProcessLookupError): os.kill(int(ready.read_text()), 0)
            fd = launcher.acquire_lock(self.state); os.close(fd)
            fd = launcher.install_lease.acquire_maintenance(self.root); os.close(fd)
        finally:
            if process.poll() is None:
                process.kill(); process.communicate(timeout=5)

    def test_subreaper_holds_lock_until_adopted_game_exits(self):
        self.session_test()

    def test_term_does_not_kill_game_or_release_lock_early(self):
        self.session_test(terminate_wrapper=True)

    def test_gui_inherits_lock_if_wrapper_is_killed(self):
        self.state.mkdir(parents=True)
        gui = self.state / 'gui.py'
        ready, done = self.state / 'ready', self.state / 'done'
        gui.write_text('import os,time\nfrom pathlib import Path\n'
                       'Path(' + repr(str(ready)) + ').write_text(str(os.getpid()))\n'
                       'time.sleep(.5)\nPath(' + repr(str(done)) + ').write_text("done")\n')
        wrapper = self.state / 'wrapper.py'
        wrapper.write_text('import os,sys\nfrom pathlib import Path\n'
                           'sys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ')\nimport launcher_linux as m\n'
                           'm.ROOT=Path(' + repr(str(self.root)) + ')\n'
                           'fd=m.acquire_lock(Path(' + repr(str(self.state)) + '))\n'
                           'runtime=m.install_lease.acquire_runtime(m.ROOT)\n'
                           'log=os.open(' + repr(str(self.state / 'console.log')) + ',os.O_WRONLY|os.O_CREAT,0o600)\n'
                           'm.wait_session([sys.executable,' + repr(str(gui)) + '],dict(os.environ),fd,log,runtime_fd=runtime)\n')
        # Outer synthetic controller reaps the orphaned GUI, keeping the real
        # unittest process free of subreaper state and live descendants.
        controller = ('import ctypes,os,signal,subprocess,sys,time\nfrom pathlib import Path\n'
                      'sys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ')\nimport launcher_linux as m\n'
                      'assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0\n'
                      'p=subprocess.Popen([sys.executable,' + repr(str(wrapper)) + '])\n'
                      'ready=Path(' + repr(str(ready)) + ')\n'
                      'deadline=time.monotonic()+3\n'
                      'while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)\n'
                      'assert ready.exists()\np.kill(); assert p.wait(timeout=3)==-signal.SIGKILL\n'
                      'try:\n fd=m.acquire_lock(Path(' + repr(str(self.state)) + '))\n'
                      'except ValueError: pass\nelse:\n os.close(fd); raise AssertionError("inherited lock released")\n'
                      'try:\n fd=m.install_lease.acquire_maintenance(Path(' + repr(str(self.root)) + '))\n'
                      'except BlockingIOError: pass\nelse:\n os.close(fd); raise AssertionError("inherited runtime lease released")\n'
                      'pid,status=os.waitpid(int(ready.read_text()),0)\nassert os.waitstatus_to_exitcode(status)==0\n'
                      'assert Path(' + repr(str(done)) + ').exists()\n'
                      'fd=m.acquire_lock(Path(' + repr(str(self.state)) + '));os.close(fd)\n')
        result = subprocess.run([sys.executable, '-B', '-c', controller], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
