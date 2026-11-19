"""Bounded synthetic updater worker/lease checks; no game, GUI or downloads."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import fcntl
except ImportError:
    fcntl = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('update_worker_core', ROOT / 'tools/update_linux.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)

SCRIPT = '''#!/usr/bin/python3
import json, os, signal, subprocess, sys, time
from pathlib import Path
root = Path(__file__).parent
expected = Path(json.loads((root / "installation.json").read_text())["owner"]) / "Monado_Linux/updates/install.lock"
info = expected.stat()
leaked = False
for value in os.listdir("/proc/self/fd"):
    try:
        fd = os.fstat(int(value))
        leaked |= (fd.st_dev, fd.st_ino) == (info.st_dev, info.st_ino)
    except OSError:
        pass
(root / "script-started.json").write_text(json.dumps({"lease_inherited": leaked}))
if "--detach" in sys.argv:
    code = ("import os, signal, sys, time; from pathlib import Path; "
            "signal.signal(signal.SIGINT, signal.SIG_IGN); "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "Path(sys.argv[1]).write_text(str(os.getpid()) + ' ' + "
            "Path('/proc/self/stat').read_text().split(') ', 1)[1].split()[19]); "
            "time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", code, str(root / "detached.ready")],
                             start_new_session=True, close_fds=True)
while not (root / "release-worker").exists():
    time.sleep(0.02)
'''


def identity(pid):
    try:
        return Path('/proc', str(pid), 'stat').read_text().split(') ', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


@unittest.skipUnless(sys.platform == 'linux' and fcntl is not None and hasattr(os, 'pidfd_open'),
                     'Linux pidfd ownership checks')
class UpdateWorker(unittest.TestCase):
    def setUp(self):
        context = tempfile.TemporaryDirectory(prefix='monado-update-worker-')
        self.addCleanup(context.cleanup)
        self.owner = Path(context.name)
        self.port = self.owner / 'Monado_Linux'
        self.workspace = self.port / 'updates/update-fixture/workspace'
        (self.workspace / 'Monado_Linux').mkdir(parents=True)
        self.lock = self.port / 'updates/install.lock'
        self.fd = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (self.workspace / 'installation.json').write_text(json.dumps(dict(schema=1,
            owner=str(self.owner), workspace=str(self.workspace), game_port=str(self.port))))
        self.script = self.workspace / 'Build_Monado_II.sh'
        self.script.write_text(SCRIPT); self.script.chmod(0o755)
        self.log = self.workspace.parent / 'build.log'
        self.children = []
        self.addCleanup(self.cleanup_workers)

    def cleanup_workers(self):
        (self.workspace / 'release-worker').touch()
        detached = self.workspace / 'detached.ready'
        if detached.exists():
            pid, start = detached.read_text().split()
            if identity(int(pid)) == start:
                try:
                    descriptor = os.pidfd_open(int(pid), 0)
                    try: signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    finally: os.close(descriptor)
                except ProcessLookupError:
                    pass
        for child in self.children:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
            try:
                child.communicate(timeout=12)
            except subprocess.TimeoutExpired:
                child.kill(); child.communicate(timeout=3)
        if self.fd is not None:
            os.close(self.fd); self.fd = None

    def wait_for(self, path, child, timeout=5):
        end = time.monotonic() + timeout
        while not path.exists() and time.monotonic() < end and child.poll() is None:
            time.sleep(0.01)
        if not path.exists() and child.poll() is not None:
            self.fail('worker exited before synthetic readiness: ' + child.communicate(timeout=2)[0])
        self.assertTrue(path.exists(), 'synthetic worker readiness exceeded bound')

    def worker(self, *, fd=None, detached=False):
        descriptor = self.fd if fd is None else fd
        command = [sys.executable, '-I', '-B', str(ROOT / 'tools/update_linux.py'),
                   '--build-worker', str(self.workspace), '--worker-log', str(self.log),
                   '--update-lock-fd', str(descriptor), '--', str(self.script)]
        if detached:
            command.append('--detach')
        child = subprocess.Popen(command, cwd=self.workspace, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                 pass_fds=(descriptor,), close_fds=True, start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.children.append(child)
        return child

    def test_isolated_startup_imports_only_explicit_trusted_siblings(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/update_linux.py'), '--help'],
                                cwd=self.workspace, env={'PATH': '/usr/bin:/bin'}, capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--rollback', result.stdout)

    def test_real_worker_relays_typed_progress_without_exposing_log_paths(self):
        lines = ['[4/12] building-game-graphics-dependencies',
                 '[4/12] building-game-verifying-graphics-packages [packages 7]',
                 '[4/12] building-game-compiling-sdl [elapsed 15]',
                 'ffmpeg-build: starting; log: /authored/private-path',
                 '[4/12] building-game-compiling-sdl [elapsed untrusted]',
                 '[6/12] building-game-native-fsr3-dependency',
                 '[9/12] building-game-build-game',
                 '[compile 31/50] done', '[compile 99/50] done',
                 '[1/8] building-launcher-check-input']
        self.script.write_text('#!/usr/bin/python3\nprint(' + repr('\n'.join(lines)) + ', flush=True)\n')
        events = []
        update.run_build([str(self.script)], self.workspace, self.log, events.append, lambda: False, lock_fd=self.fd)
        self.assertEqual(self.log.read_text().splitlines(), lines)
        self.assertEqual([event['message'] for event in events], [
            'Building the game: Preparing graphics and audio libraries (4/12)',
            'Building the game: Checking graphics packages (4/12) · 7 packages checked',
            'Building the game: Compiling SDL (4/12) · 15s elapsed',
            'Building the game: Preparing native FSR3 upscaling (6/12)',
            'Building the game: Compiling native game files (9/12)',
            'Building the game: Compiling native game files (9/12) · 31/50 compile jobs finished',
            'Building the launcher: Checking game files (1/8)',
        ])
        self.assertEqual([event['fraction'] for event in events], [3/12, 3/12, 3/12, 5/12, 8/12, 8/12, 0])
        self.assertTrue(all(event['phase'] == 'building' for event in events))

    def test_wrong_inherited_lock_cannot_execute_build_script(self):
        wrong = os.open(self.owner / 'wrong.lock', os.O_RDWR | os.O_CREAT, 0o600)
        try:
            child = self.worker(fd=wrong)
            output = child.communicate(timeout=5)[0]
        finally:
            os.close(wrong)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn('lease mismatch', output)
        self.assertFalse((self.workspace / 'script-started.json').exists())

    def test_worker_retains_update_lease_without_leaking_it_to_build(self):
        child = self.worker()
        self.wait_for(self.workspace / 'script-started.json', child)
        self.assertFalse(json.loads((self.workspace / 'script-started.json').read_text())['lease_inherited'])
        os.close(self.fd); self.fd = None  # Simulates the outer supervisor closing/crashing.
        competitor = os.open(self.lock, os.O_RDWR | os.O_CLOEXEC)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            (self.workspace / 'release-worker').touch()
            output = child.communicate(timeout=8)[0]
            self.assertEqual(child.returncode, 0, output)
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(competitor)

    def test_cancel_reaps_detached_workers_and_preserves_unrelated_child(self):
        unrelated = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(unrelated)
        child = self.worker(detached=True)
        ready = self.workspace / 'detached.ready'
        self.wait_for(ready, child)
        pid, start = ready.read_text().split()
        child.send_signal(signal.SIGINT)
        output = child.communicate(timeout=18)[0]
        self.assertEqual(child.returncode, 130, output)
        self.assertNotEqual(identity(int(pid)), start, 'owned detached compiler survived cancellation')
        self.assertIsNone(unrelated.poll(), 'worker cleanup signalled an unrelated process')
        unrelated.terminate(); unrelated.wait(timeout=3)


class PublicationUpdateBoundary(unittest.TestCase):
    def test_runtime_update_roots_and_binding_markers_never_publish(self):
        for name in ('installation.json', 'Monado_Linux/installation.json',
                     'Monado_Linux/updates', 'Monado_Linux/updates/update-id/workspace/README.md'):
            with self.subTest(name=name):
                self.assertIsNotNone(update.path_problem(name))
        for name in ('tools/update_linux.py', 'tools/update_release.py',
                     'Monado_Linux/scripts/install_layout.py', 'update-version.json'):
            with self.subTest(name=name):
                self.assertIsNone(update.path_problem(name))


if __name__ == '__main__':
    unittest.main()
