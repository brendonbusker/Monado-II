"""Authored input-recovery flow fixtures; no game, visible GUI or human state."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'Monado_Linux/scripts'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


launcher = None
if sys.platform == 'linux':
    plan = load('input_recovery_run_linux', SCRIPTS / 'run_linux.py')
    with mock.patch.dict(sys.modules, {'run_linux': plan}):
        launcher = load('input_recovery_launcher', SCRIPTS / 'launcher_linux.py')


@unittest.skipUnless(sys.platform == 'linux', 'Linux input recovery wrapper')
class LegacyRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado input recovery flow ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.port = self.base / 'owner/Monado_Linux'
        self.port.mkdir(parents=True)
        self.game = self.port / 'build/game/xcde-linux'
        self.gui = self.port / 'build/gui/monado-launcher'
        self.state = self.port / 'play/launcher'
        self.args = SimpleNamespace(game_executable=self.game, launcher_executable=self.gui,
            packaged_launcher=None, state_root=self.state, dry_run=False, shot=None,
            shot_tab=None, shot_frame=None, ui_script=None, test_exit_after_child=False,
            test_child_env=[])
        self.helper = SimpleNamespace(inspect=mock.Mock(return_value={'missing': True, 'previous': '/authored/old input'}),
                                      relocate=mock.Mock(), require_idle=mock.Mock())

    def test_available_input_preserves_normal_launch_without_locator_validation(self):
        self.helper.inspect.return_value = {'missing': False}
        with mock.patch.object(launcher, 'input_location_module', return_value=self.helper), mock.patch.object(launcher, 'input_independent_runtime') as validate, mock.patch.object(launcher, 'locate_game_files') as picker:
            self.assertTrue(launcher.recover_input(self.args))
        validate.assert_not_called(); picker.assert_not_called()
        self.helper.relocate.assert_not_called()

    def test_scripted_or_dry_run_routes_never_load_recovery_or_open_picker(self):
        controls = {'dry_run': True, 'shot': self.base / 'shot.png', 'shot_tab': 0,
                    'shot_frame': 1, 'ui_script': self.base / 'script.json',
                    'test_exit_after_child': True, 'test_child_env': ['XCDE_USAGE=unused']}
        for field, value in controls.items():
            args = SimpleNamespace(**vars(self.args)); setattr(args, field, value)
            with self.subTest(field=field), mock.patch.object(launcher, 'input_location_module', side_effect=AssertionError('interactive recovery forbidden')):
                self.assertTrue(launcher.recover_input(args))

    def test_recover_checks_both_artifacts_and_idle_before_picker_then_relinks(self):
        order = []
        self.helper.require_idle.side_effect = lambda port: order.append('idle')
        def validate(path, **kwargs):
            order.append('gui' if kwargs.get('launcher') else 'game')
            return self.gui, 'authored-hash', '/receipted/library/path'
        def picker(*args):
            order.append('picker')
            self.assertEqual(args, (self.gui, '/receipted/library/path', '/authored/old input'))
            return str(self.base / 'relocated input')
        with mock.patch.object(launcher, 'ROOT', self.port), mock.patch.object(launcher, 'input_location_module', return_value=self.helper), mock.patch.object(launcher, 'input_independent_runtime', side_effect=validate), mock.patch.object(launcher, 'locate_game_files', side_effect=picker), mock.patch.object(launcher, 'acquire_lock', side_effect=AssertionError('profile writes forbidden')):
            self.assertTrue(launcher.recover_input(self.args))
        self.assertEqual(order, ['gui', 'game', 'idle', 'picker'])
        self.helper.relocate.assert_called_once_with(self.port, self.game, str(self.base / 'relocated input'), checker=launcher.check_input)
        self.assertFalse(self.state.exists())

    def test_busy_installation_refuses_without_a_picker_or_child_kill(self):
        self.helper.require_idle.side_effect = BlockingIOError('installation in use')
        with mock.patch.object(launcher, 'input_location_module', return_value=self.helper), mock.patch.object(launcher, 'input_independent_runtime', return_value=(self.gui, 'hash', '/libs')), mock.patch.object(launcher, 'locate_game_files') as picker:
            with self.assertRaisesRegex(BlockingIOError, 'in use'):
                launcher.recover_input(self.args)
        picker.assert_not_called(); self.helper.relocate.assert_not_called()

    def test_invalid_native_or_packaged_identity_refuses_before_picker(self):
        with mock.patch.object(launcher, 'input_location_module', return_value=self.helper), mock.patch.object(launcher, 'input_independent_runtime', side_effect=ValueError('receipt mismatch')), mock.patch.object(launcher, 'locate_game_files') as picker:
            with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                launcher.recover_input(self.args)
        picker.assert_not_called()
        self.args.packaged_launcher = self.base / 'packaged-gui'
        with mock.patch.object(launcher, 'input_location_module', return_value=self.helper), mock.patch.object(launcher, 'input_independent_runtime', return_value=(self.gui, 'hash', '/libs')), mock.patch.object(launcher, 'verified_packaged_launcher', side_effect=ValueError('copy changed')), mock.patch.object(launcher, 'locate_game_files') as picker:
            with self.assertRaisesRegex(ValueError, 'copy changed'):
                launcher.recover_input(self.args)
        picker.assert_not_called()

    def test_cancel_exits_cleanly_before_prepare_or_profile_creation(self):
        with mock.patch.object(launcher, 'recover_input', return_value=False), mock.patch.object(launcher, 'prepare') as prepare, mock.patch.object(launcher, 'acquire_lock') as lock:
            self.assertEqual(launcher.main(['--no-updates']), 0)
        prepare.assert_not_called(); lock.assert_not_called()
        self.assertFalse(self.state.exists())

    def picker_output(self, data, *, error=b'', code=0):
        # An authored Python IPC child replaces the UI; no native GUI executes.
        real_popen = subprocess.Popen
        program = 'import os;os.write(1,' + repr(data) + ');os.write(2,' + repr(error) + ');raise SystemExit(' + str(code) + ')'
        def spawn(argv, **kwargs):
            self.assertEqual(argv, [str(self.gui), '--locate-game-files', '--missing-input', '/authored/old input'])
            self.assertEqual(kwargs['env']['LD_LIBRARY_PATH'], '/receipted/libs')
            self.assertNotIn('LD_PRELOAD', kwargs['env'])
            self.assertNotIn('--state-root', argv)
            return real_popen([sys.executable, '-I', '-B', '-c', program], **kwargs)
        with mock.patch.object(launcher, 'ROOT', self.port), mock.patch.object(launcher.subprocess, 'Popen', side_effect=spawn), mock.patch.dict(os.environ, {'LD_PRELOAD': '/injected/not-used'}):
            return launcher.locate_game_files(self.gui, '/receipted/libs', '/authored/old input')

    def test_picker_accepts_utf8_nul_and_cancel_without_profile_writes(self):
        self.assertEqual(self.picker_output('/authored/game files é'.encode() + b'\0'), '/authored/game files é')
        self.assertIsNone(self.picker_output(b''))
        self.assertFalse(self.state.exists())

    def test_picker_rejects_unbounded_invalid_or_failed_ipc(self):
        for data in (b'/missing nul', b'/one\0/two\0', b'relative\0', b'/bad\nname\0', b'/bad\xff\0', b'x' * 4097):
            with self.subTest(data=data[:30]), self.assertRaises(ValueError):
                self.picker_output(data)
        with self.assertRaisesRegex(ValueError, 'failed'):
            self.picker_output(b'', error=b'authored dialog error', code=1)
        with self.assertRaisesRegex(ValueError, 'excessive'):
            self.picker_output(b'', error=b'x' * 16385)


@unittest.skipUnless(sys.platform == 'linux', 'Linux read-only native validation')
class IndependentNativeValidation(unittest.TestCase):
    setUp = LegacyRecovery.setUp

    def test_real_authored_elf_receipt_and_runtime_are_checked_without_game_input(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('A host C compiler is needed for this authored load-only fixture')
        check = launcher.run_linux.runtime_check
        libdir = self.port / '.deps/graphics/sysroots/authored/usr/lib/x86_64-linux-gnu'
        libdir.mkdir(parents=True)
        sysroot = libdir.parents[2]
        library = libdir / 'libinput_recovery_fixture.so.1'
        source = self.base / 'authored.c'
        source.write_text('int authored(void){return 0;}\n')
        subprocess.run([cc, '-shared', '-fPIC', str(source), '-Wl,-soname,' + library.name, '-o', str(library)], check=True, capture_output=True)
        self.gui.parent.mkdir(parents=True)
        source.write_text('extern int authored(void);int main(void){return authored();}\n')
        subprocess.run([cc, str(source), str(library), '-o', str(self.gui)], check=True, capture_output=True)
        policy = {'schema': 1, 'root_sonames': [library.name], 'library_dirs': ['usr/lib/x86_64-linux-gnu'],
                  'owned_sonames': {library.name: {'path': str(library.relative_to(sysroot)), 'package': 'authored'}},
                  'host_sonames': {'libc.so.6': {'reason': 'Authored platform fixture', 'category': 'platform'},
                                   'ld-linux-x86-64.so.2': {'reason': 'Authored loader fixture', 'category': 'platform'}}}
        lock = self.port / 'graphics-deps-linux.lock.json'
        lock.write_text(json.dumps({'schema': 1, 'runtime': policy}))
        lock_sha = check.digest(lock)
        marker = {'lock_sha256': lock_sha, 'runtime_policy': policy, 'runtime_policy_sha256': check.policy_digest(policy),
                  'owned_runtime_files': {library.name: {'path': str(library.relative_to(sysroot)), 'bytes': library.stat().st_size, 'sha256': check.digest(library)}}}
        (sysroot / '.monado-deps.json').write_text(json.dumps(marker))
        receipt = {'status': 'passed', 'artifact_kind': 'linux-launcher',
                   'executable': {'path': str(self.gui), 'sha256': check.digest(self.gui)},
                   'sources_before': {'graphics-deps-linux.lock.json': lock_sha},
                   'dependencies': {'sysroot': str(sysroot)},
                   'runtime_validation': check.check_artifacts([self.gui], sysroot, policy)}
        receipt_path = self.gui.parent / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        spawn = subprocess.Popen
        def load_only(argv, *args, **kwargs):
            self.assertNotEqual(Path(argv[0]), self.gui, 'authored application must never execute')
            return spawn(argv, *args, **kwargs)
        with mock.patch.object(launcher, 'ROOT', self.port), mock.patch.object(launcher.subprocess, 'Popen', side_effect=load_only):
            checked = launcher.input_independent_runtime(self.gui, launcher=True)
            self.assertEqual(checked, (self.gui, receipt['executable']['sha256'], str(libdir)))
            self.assertFalse((self.port.parent / 'game_files').exists())
            self.assertFalse(self.state.exists())
            self.gui.write_bytes(self.gui.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'successful build receipt'):
                launcher.input_independent_runtime(self.gui, launcher=True)


@unittest.skipUnless(sys.platform == 'linux', 'Linux local broker IPC recovery')
class BrokerRecoveryIPC(unittest.TestCase):
    def test_real_broker_reconnects_synthetic_input_without_rebuild_or_native_execution(self):
        core_fixture = load('input_recovery_authored_fixture', ROOT / 'tests/test_input_location.py')
        backend = load('input_recovery_backend_fixture', ROOT / 'tools/builder_backend.py')
        with tempfile.TemporaryDirectory(prefix='monado recovery broker IPC ') as temporary:
            base = Path(temporary).resolve()
            f = core_fixture.Fixture(base)
            session = base / 'session'; session.mkdir(mode=0o700)
            state = base / 'builder registry'; state.mkdir(mode=0o700)
            source = base / 'authored source'; source.mkdir()
            (source / 'update-version.json').write_text('{"version":"authored-recovery-test"}')
            registry = state / backend.REGISTRY
            registry.write_text(json.dumps({'schema': 1, 'workspace': str(f.owner)}))
            selected = {'owner': str(f.owner), 'workspace': str(f.port.parent), 'port': str(f.port),
                        'game': str(f.game), 'launcher': str(f.port / 'build/unused-gui/monado-launcher'),
                        'state': str(f.profile), 'python': sys.executable, 'version': 'authored-recovery-test'}
            selection = base / 'selection.json'; selection.write_text(json.dumps(selected))
            checker = base / 'authored-checker.py'
            checker.write_text('import sys,pathlib\np=pathlib.Path(sys.argv[1])\n'
                               'assert (p/"romfs/layout.txt").read_text()=="synthetic version 2.0.0"\n'
                               'print("Authored input checker passed")\n')
            verifier = base / 'authored-readonly-launch-check.py'
            verifier.write_text('import json,pathlib\np=pathlib.Path(' + repr(str(f.owner / 'game_files')) + ')\n'
                                'assert p.resolve(strict=True)==pathlib.Path(' + repr(str(f.new)) + ')\n'
                                'assert (p/"exefs/main").is_file()\nprint("Authored read-only existing-wrapper check passed")\n')
            harness = base / 'authored-service.py'
            harness.write_text('import importlib.util,json,pathlib,sys\n'
                'spec=importlib.util.spec_from_file_location("authored_broker",' + repr(str(ROOT / 'tools/builder_backend.py')) + ')\n'
                'b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)\n'
                'def installation(self,workspace):\n'
                ' value=json.loads(pathlib.Path(' + repr(str(selection)) + ').read_text())\n'
                ' for k in ("owner","workspace","port","game","launcher","state","python"):value[k]=pathlib.Path(value[k])\n'
                ' value["input_location"]=b.input_location().inspect(value["port"],value["game"])\n'
                ' return value\n'
                'original=b.Broker.run_command\n'
                'def run(self,argv,cwd,**kw):\n'
                ' if any(str(v).endswith("check_dump.py") for v in argv):argv=[sys.executable,"-I","-B",' + repr(str(checker)) + ',argv[-1]]\n'
                ' elif "--dry-run" in argv:argv=[sys.executable,"-I","-B",' + repr(str(verifier)) + ']\n'
                ' else:raise AssertionError("Build or native execution forbidden in recovery fixture")\n'
                ' return original(self,argv,cwd,**kw)\n'
                'b.Broker.installation=installation;b.Broker.run_command=run\n'
                'raise SystemExit(b.main())\n')
            protected = [f.game, f.receipt, f.profile / 'save.dat', f.profile / 'xcde.ini', registry]
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected}
            input_before = {str(path.relative_to(f.new)): path.read_bytes() for path in f.new.rglob('*') if path.is_file()}
            child = subprocess.Popen([sys.executable, '-I', '-B', str(harness), '--serve', '--source', str(source), '--session', str(session), '--state', str(state)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            def await_phase(phase, identity=None):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    path = session / 'status.json'
                    if path.exists():
                        value = json.loads(path.read_text())
                        if value['phase'] == phase and (identity is None or value['request_id'] == identity):
                            return value
                    if child.poll() is not None:
                        self.fail('authored recovery broker exited: ' + child.communicate()[0].decode())
                    time.sleep(.02)
                self.fail('broker did not reach ' + phase + ': ' + (session / 'status.json').read_text())
            try:
                missing = await_phase('input_missing')
                self.assertEqual(missing['output'], str(f.owner))
                self.assertEqual(missing['input_previous'], str(f.input))
                self.assertFalse(missing['can_open'])
                # A valid-layout folder with different ExeFS must not repair links.
                wrong = base / 'wrong executable identity'
                shutil.copytree(f.new, wrong)
                (wrong / 'exefs/main').write_text('different authored executable')
                backend.atomic(session / 'request.json', {'id': 'reject-wrong', 'action': 'relocate', 'input': str(wrong)})
                rejected = await_phase('failed', 'reject-wrong')
                self.assertFalse(rejected['can_open'])
                self.assertTrue(all(os.readlink(link) == str(f.input) for link in f.links))
                backend.atomic(session / 'request.json', {'id': 'locate-correct', 'action': 'relocate', 'input': str(f.new)})
                ready = await_phase('installed', 'locate-correct')
                self.assertTrue(ready['can_open'])
                self.assertEqual(ready['input_previous'], '')
                self.assertTrue(all(link.resolve(strict=True) == f.new for link in f.links))
                self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected})
                self.assertEqual(input_before, {str(path.relative_to(f.new)): path.read_bytes() for path in f.new.rglob('*') if path.is_file()})
                self.assertFalse(any(path.name == 'monado-launcher' for path in f.owner.rglob('*')))
                self.assertTrue(list(session.glob('worker-*.log')), 'checker and dry-run must use owned worker sessions')
            finally:
                if child.poll() is None:
                    child.terminate()
                output = child.communicate(timeout=8)[0]
            self.assertEqual(child.returncode, 0, output.decode())


if __name__ == '__main__':
    unittest.main()
