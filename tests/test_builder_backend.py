"""[XCDE] LINUX-081: authored GUI broker fixtures; no game or real build."""
import hashlib
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
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_builder_backend_tested', ROOT / 'tools/builder_backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def encode(value):
    return json.dumps(value, sort_keys=True).encode()


def manifest(root, files):
    files = dict(files, **{'publication-policy.json': encode({'schema': 1, 'licensed_media': {}})})
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (root / 'publication-manifest.json').write_bytes(encode({'schema': 1, 'project': 'Monado II', 'source_only': True,
        'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()}}))


@unittest.skipUnless(sys.platform == 'linux', 'Linux native setup broker fixtures')
class BrokerFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='monado-builder-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / 'reviewed source'
        self.source.mkdir()
        self.session = self.base / 'session'
        self.session.mkdir(mode=0o700)
        self.state = self.base / 'state'
        self.state.mkdir(mode=0o700)
        self.input = self.base / 'own extracted input'
        (self.input / 'exefs').mkdir(parents=True)
        (self.input / 'romfs').mkdir()
        (self.input / 'exefs/authored.txt').write_text('authored validation fixture; no game data')
        self.output = self.base / 'final build with spaces'
        manifest(self.source, {
            'README.md': b'Authored fixture only.\n',
            'update-version.json': encode({'version': 'test-fixture'}),
            'Monado_Linux/tools/extract/check_dump.py': b'import sys\nprint("OK authored input fixture")\n',
            'tools/build_linux_app.py': b'# Authored command placeholder; never invokes a compiler.\n',
        })
        self.broker = backend.Broker(self.source, self.session, self.state)
        self.addCleanup(self.broker.close)
        prerequisites = mock.patch.object(self.broker, 'check_prerequisites', return_value='Authored host prerequisite fixture passed')
        prerequisites.start(); self.addCleanup(prerequisites.stop)

    def request(self, action='inspect', **extra):
        return dict(id='fixture-' + str(time.monotonic_ns()), action=action, input=str(self.input), output=str(self.output), dlss=False, precompile=False, jobs=2, **extra)

    def inventory(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_fresh_registry_and_inspection_do_not_write_input_or_output(self):
        before = self.inventory(self.input)
        result = self.broker.inspect(self.request())
        self.assertEqual(result, (self.input, self.output))
        self.assertEqual(self.broker.status['phase'], 'ready')
        self.assertFalse(self.output.exists())
        self.assertFalse((self.state / backend.REGISTRY).exists())
        self.assertEqual(self.inventory(self.input), before)

    def test_missing_game_paths_fail_without_staging(self):
        request = self.request(); request['input'] = ''
        with self.assertRaisesRegex(backend.BuilderError, 'Choose your extracted'):
            self.broker.inspect(request)
        self.assertFalse(self.output.exists())

    def test_input_checker_failure_never_creates_output(self):
        with mock.patch.object(self.broker, 'run_command', side_effect=backend.BuilderError('Unsupported input')):
            with self.assertRaisesRegex(backend.BuilderError, 'Unsupported input'):
                self.broker.inspect(self.request())
        self.assertFalse(self.output.exists())

    def test_new_or_empty_destination_allowed_unknown_nonempty_protected(self):
        self.output.mkdir()
        self.broker.inspect(self.request())
        (self.output / 'keep.txt').write_text('unrelated owned file')
        with self.assertRaises((backend.BuilderError, FileNotFoundError)):
            backend.destination(str(self.output), self.source, self.state, self.input)
        self.assertEqual((self.output / 'keep.txt').read_text(), 'unrelated owned file')

    def test_managed_and_input_overlap_rejected(self):
        for output in (self.input, self.input / 'inside', self.base, self.source / 'inside', self.state / 'inside'):
            request = self.request(); request['output'] = str(output)
            with self.subTest(output=output), self.assertRaises(backend.BuilderError):
                backend.destination(str(output), self.source, self.state, self.input)

    def test_output_symlink_or_colon_rejected(self):
        link = self.base / 'linked'; link.symlink_to(self.base, target_is_directory=True)
        for output in (link / 'target', self.base / 'colon:path'):
            request = self.request(); request['output'] = str(output)
            with self.subTest(output=output), self.assertRaises(backend.BuilderError):
                backend.destination(str(output), self.source, self.state, self.input)

    def test_input_selected_link_resolves_without_moving_files(self):
        link = self.base / 'input link'; link.symlink_to(self.input, target_is_directory=True)
        request = self.request(); request['input'] = str(link)
        source, _ = self.broker.inspect(request)
        self.assertEqual(source, self.input)
        self.assertTrue(link.is_symlink())

    def test_staging_selects_only_manifest_entries_and_keeps_input_link(self):
        (self.source / 'unreviewed.txt').write_text('must not copy')
        backend.stage_source(self.source, self.output, self.input)
        self.assertFalse((self.output / 'unreviewed.txt').exists())
        self.assertTrue((self.output / 'game_files').is_symlink())
        self.assertEqual((self.output / 'game_files').resolve(), self.input)
        self.assertEqual(backend.destination(str(self.output), self.source, self.state, self.input), self.output)

    def test_manifest_tamper_forbidden_game_path_or_changed_source_rejected(self):
        path = self.source / 'README.md'
        path.write_text('changed authored file')
        with self.assertRaisesRegex(backend.BuilderError, 'source changed'):
            backend.stage_source(self.source, self.output, self.input)
        self.assertFalse(self.output.exists())
        path.write_bytes(b'Authored fixture only.\n')
        value = backend.document(self.source / 'publication-manifest.json')
        value['files']['game_files/romfs/unsafe.txt'] = {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()}
        (self.source / 'publication-manifest.json').write_bytes(encode(value))
        with self.assertRaisesRegex(backend.BuilderError, 'Unsafe source manifest'):
            backend.stage_source(self.source, self.output, self.input)

    def test_retry_preserves_completed_state_and_refuses_changed_source(self):
        backend.stage_source(self.source, self.output, self.input)
        saved = self.output / 'Monado_Linux/play/launcher/save_1/progress.txt'
        saved.parent.mkdir(parents=True); saved.write_text('authored save fixture')
        backend.destination(str(self.output), self.source, self.state, self.input)
        backend.stage_source(self.source, self.output, self.input)
        self.assertEqual(saved.read_text(), 'authored save fixture')
        (self.output / 'README.md').write_text('user changed authored source')
        with self.assertRaisesRegex(backend.BuilderError, 'source was modified'):
            backend.destination(str(self.output), self.source, self.state, self.input)
        self.assertEqual(saved.read_text(), 'authored save fixture')

    def test_failed_build_uses_no_appimage_without_registering_or_touching_input(self):
        before = self.inventory(self.input)
        commands = []
        def run(argv, cwd, **kwargs):
            commands.append(list(map(str, argv)))
            if '--no-appimage' in argv:
                raise backend.BuilderError('authored compiler failure')
            return 'OK'
        with mock.patch.object(self.broker, 'run_command', side_effect=run):
            with self.assertRaisesRegex(backend.BuilderError, 'authored compiler failure'):
                self.broker.build(self.request(action='build'))
        self.assertTrue(any('--no-appimage' in c and '--without-dlss' in c and '--jobs' in c for c in commands))
        self.assertTrue((self.output / backend.MARKER).exists())
        self.assertFalse((self.state / backend.REGISTRY).exists())
        self.assertEqual(before, self.inventory(self.input))

    def test_prerequisite_failure_is_actionable_and_precedes_workspace_creation(self):
        with mock.patch.object(self.broker, 'run_command', return_value='OK'), mock.patch.object(self.broker, 'check_prerequisites', side_effect=backend.BuilderError('Install the reported host package: dpkg')):
            with self.assertRaisesRegex(backend.BuilderError, 'host package: dpkg'):
                self.broker.build(self.request(action='build'))
        self.assertFalse(self.output.exists())
        self.assertFalse((self.state / backend.REGISTRY).exists())

    def test_inspect_input_is_independent_of_unselected_destination(self):
        self.output.mkdir(); (self.output / 'unrelated.txt').write_text('keep')
        self.broker.inspect(self.request())
        self.assertEqual(self.broker.status['phase'], 'ready')
        with self.assertRaises((backend.BuilderError, FileNotFoundError)):
            backend.destination(str(self.output), self.source, self.state, self.input)
        self.assertEqual((self.output / 'unrelated.txt').read_text(), 'keep')

    def test_build_input_check_never_publishes_terminal_ready_mid_request(self):
        phases = []
        original = self.broker.update
        def update(**fields):
            if 'phase' in fields:
                phases.append(fields['phase'])
            return original(**fields)
        selected = dict(owner=self.output, version='test-fixture')
        with mock.patch.object(self.broker, 'run_command', return_value='OK'), mock.patch.object(self.broker, 'installation', return_value=selected), mock.patch.object(self.broker, 'update', side_effect=update):
            self.broker.build(self.request(action='build'))
        self.assertNotIn('ready', phases)
        self.assertEqual(phases[0], 'checking')
        self.assertIn('building', phases)
        self.assertEqual(phases[-1], 'complete')

    def test_successful_build_registers_only_after_verified_selection(self):
        selected = dict(owner=self.output, version='test-fixture')
        with mock.patch.object(self.broker, 'run_command', return_value='OK'), mock.patch.object(self.broker, 'installation', return_value=selected) as validate:
            self.broker.build(self.request(action='build'))
        validate.assert_called_once_with(self.output)
        self.assertEqual(backend.document(self.state / backend.REGISTRY)['workspace'], str(self.output))
        self.assertEqual(self.broker.status['phase'], 'complete')
        self.assertTrue(self.broker.status['can_open'])

    def test_requests_deduplicate_and_busy_cancel_owns_exact_worker(self):
        request = self.request()
        with mock.patch.object(self.broker, 'inspect') as inspect:
            self.broker.dispatch(request)
            self.broker.thread.join(2)
            self.broker.dispatch(request)
            inspect.assert_called_once()
        self.broker.dispatch(dict(id='cancel', action='cancel'))
        self.assertTrue(self.broker.cancelled.is_set())
        self.assertEqual(self.broker.status['request_id'], 'cancel')
        self.assertEqual(self.broker.status['phase'], 'cancelled')

    def test_actual_authored_child_cancellation_does_not_affect_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(lambda: (unrelated.terminate(), unrelated.wait()) if unrelated.poll() is None else None)
        errors = []
        import threading
        def command():
            try:
                self.broker.run_command([sys.executable, '-c', 'import time; print("authored worker",flush=True); time.sleep(30)'], self.source)
            except InterruptedError as error:
                errors.append(str(error))
        worker = threading.Thread(target=command); worker.start()
        deadline = time.monotonic() + 3
        while self.broker.child is None and time.monotonic() < deadline:
            time.sleep(.01)
        child = self.broker.child
        self.assertIsNotNone(child)
        self.broker.cancelled.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(errors)
        self.assertIsNotNone(child.poll())
        self.assertIsNone(unrelated.poll())

    def test_detached_grandchild_is_reaped_after_direct_child_exits(self):
        pidfile = self.session / 'detached-pid.txt'
        program = ('import os,time,pathlib\n'
                   'pid=os.fork()\n'
                   'if pid==0:\n'
                   ' os.setsid();pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid()))\n'
                   ' while True:time.sleep(1)\n'
                   'time.sleep(.2);os._exit(0)\n')
        with self.assertRaisesRegex(backend.BuilderError, 'Stage failed'):
            self.broker.run_command([sys.executable, '-c', program], self.source)
        pid = int(pidfile.read_text())
        self.assertFalse(Path('/proc', str(pid)).exists(), 'detached authored worker must be reaped')

    def test_cancel_reaps_detached_session_without_touching_unrelated_child(self):
        import threading
        pidfile = self.session / 'cancel-detached-pid.txt'
        program = ('import os,time,pathlib\n'
                   'pid=os.fork()\n'
                   'if pid==0:\n'
                   ' os.setsid();pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid()))\n'
                   ' while True:time.sleep(1)\n'
                   'time.sleep(30)\n')
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        self.addCleanup(lambda: (unrelated.terminate(), unrelated.wait()) if unrelated.poll() is None else None)
        errors = []
        def execute():
            try:
                self.broker.run_command([sys.executable, '-c', program], self.source)
            except InterruptedError as error:
                errors.append(str(error))
        thread = threading.Thread(target=execute)
        thread.start()
        deadline = time.monotonic() + 5
        pid_text = ''
        while time.monotonic() < deadline:
            if pidfile.exists():
                pid_text = pidfile.read_text()
                if pid_text.isdecimal():
                    break
            time.sleep(.01)
        self.assertTrue(pid_text.isdecimal(), 'owned detached child did not publish its PID')
        pid = int(pid_text)
        self.broker.cancelled.set()
        thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        self.assertFalse(Path('/proc', str(pid)).exists(), 'owned detached child must be reaped')
        self.assertIsNone(unrelated.poll())

    def test_command_worker_preserves_reviewed_desktop_context(self):
        with mock.patch.dict(os.environ, {'DISPLAY': ':authored', 'SteamAppId': '480', 'LD_PRELOAD': '/not-admitted'}, clear=True):
            value = self.broker.run_command([sys.executable, '-c', 'import os,json;print(json.dumps({key:os.environ.get(key) for key in ("DISPLAY","SteamAppId","LD_PRELOAD")}))'], self.source)
        value = json.loads(value)
        self.assertEqual(value['DISPLAY'], ':authored')
        self.assertEqual(value['SteamAppId'], '480')
        self.assertIsNone(value['LD_PRELOAD'])

    def test_worker_progress_uses_human_stage_labels_and_real_compile_counts(self):
        self.broker.run_command([sys.executable, '-c', 'print("[1/2] graphics-dependencies")'], self.source, progress=True)
        self.assertEqual(self.broker.status['message'], 'Preparing graphics and audio libraries')
        previous = self.broker.status['progress']
        self.broker.run_command([sys.executable, '-c', 'print("[2/2] build-game");print("[compile 3/4] authored fixture.c")'], self.source, progress=True)
        self.assertEqual(self.broker.status['message'], 'Compiling: 3 of 4 files')
        self.assertGreater(self.broker.status['progress'], previous)
        self.assertLess(self.broker.status['progress'], 1)

    def test_venv_links_keep_private_prefix_while_parent_links_rejected(self):
        port = self.base / 'port'
        (port / '.venv/bin').mkdir(parents=True)
        (port / '.venv/pyvenv.cfg').write_text('home = /usr/bin\n')
        (port / '.venv/bin/python').symlink_to(Path(sys.executable).resolve())
        self.assertEqual(backend.Broker.venv_python(port), port / '.venv/bin/python')

    def test_controller_context_survives_but_loader_injection_does_not(self):
        mapping = '03000000000000000000000000000000,Authored Fixture,a:b0,'
        with mock.patch.dict(os.environ, {'SDL_GAMECONTROLLERCONFIG': mapping, 'SteamAppId': '480',
                                         'LD_PRELOAD': '/invalid/fixture.so', 'SDL_DYNAMIC_API': '/invalid/sdl.so', 'XCDE_TEST': '1'}, clear=True):
            value = backend.environment()
        self.assertEqual(value['SDL_GAMECONTROLLERCONFIG'], mapping)
        self.assertEqual(value['SteamAppId'], '480')
        self.assertNotIn('LD_PRELOAD', value)
        self.assertNotIn('SDL_DYNAMIC_API', value)
        self.assertNotIn('XCDE_TEST', value)

    def test_registered_owner_follows_verified_active_update_and_preserves_profile(self):
        owner = self.base / 'installed owner'
        active = owner / 'Monado_Linux/updates/authored-update/workspace'
        port = active / 'Monado_Linux'
        port.mkdir(parents=True)
        (owner / 'Monado_Linux/updates/active.json').write_text('{"schema":1}')
        (active / 'installation.json').write_text(json.dumps({'schema': 1, 'owner': str(owner), 'workspace': str(active), 'game_port': str(port)}))
        state = owner / 'Monado_Linux/play/launcher'
        saved = state / 'save_1/progress.txt'
        saved.parent.mkdir(parents=True); saved.write_text('authored save kept in original profile')
        game = port / 'build/authored-game/xcde-linux'; game.parent.mkdir(parents=True); game.write_text('authored never executed fixture')
        gui = port / 'build/authored-launcher/monado-launcher'; gui.parent.mkdir(parents=True); gui.write_text('authored never executed fixture')
        run = port / 'runs/local-build/authored-build/receipt.json'; run.parent.mkdir(parents=True)
        run.write_text(json.dumps({'status': 'passed', 'paths': {'game': str(game), 'launcher': str(gui), 'state': str(state)}}))
        metadata = port / '.deps/metadata/gui-build.json'; metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'schema': 1, 'status': 'passed', 'artifact_kind': 'local-gui-build', 'build_id': 'authored-build', 'build_receipt_sha256': backend.digest(run)}))
        (port / '.venv/bin').mkdir(parents=True)
        (port / '.venv/pyvenv.cfg').write_text('home = /usr/bin\n')
        (port / '.venv/bin/python').symlink_to(Path(sys.executable).resolve())
        layout = backend.module(ROOT / 'Monado_Linux/scripts/install_layout.py', '_monado_fixture_real_layout')
        updater = SimpleNamespace(active_record=mock.Mock(return_value=active), json_read=backend.document,
                                  layout_module=lambda path: layout, installed_sources=mock.Mock())
        def load(path, name):
            return updater if str(path).endswith('update_linux.py') else layout
        recovery = SimpleNamespace(inspect=mock.Mock(return_value={'missing': False, 'previous': str(self.input), 'owner': str(owner)}))
        with mock.patch.object(backend, 'module', side_effect=load), mock.patch.object(backend, 'input_location', return_value=recovery):
            selected = self.broker.installation(owner)
        updater.active_record.assert_called_once_with(owner, {'schema': 1})
        updater.installed_sources.assert_called_once_with(active)
        self.assertEqual(selected['owner'], owner)
        self.assertEqual(selected['workspace'], active)
        self.assertEqual(selected['game'], game)
        self.assertEqual(selected['state'], state)
        recovery.inspect.assert_called_once_with(port, game)
        self.assertEqual(saved.read_text(), 'authored save kept in original profile')

    def test_inflight_cancel_echoes_cancel_request_id(self):
        def inspect(request):
            self.broker.update(phase='checking')
            self.broker.cancelled.wait(2)
            raise InterruptedError('authored cancellation')
        with mock.patch.object(self.broker, 'inspect', side_effect=inspect):
            self.broker.dispatch(self.request())
            self.broker.dispatch(dict(id='cancel-inflight', action='cancel'))
            self.broker.thread.join(3)
        self.assertEqual(self.broker.status['phase'], 'cancelled')
        self.assertEqual(self.broker.status['request_id'], 'cancel-inflight')

    def test_open_registered_first_run_returns_two_without_starting_a_gui(self):
        with mock.patch.object(backend.Broker, 'open') as opened:
            code = backend.main(['--open-registered', '--source', str(self.source), '--session', str(self.session), '--state', str(self.state)])
        self.assertEqual(code, 2)
        opened.assert_not_called()

    def test_invalid_registered_install_returns_attention_without_starting_a_gui(self):
        (self.state / backend.REGISTRY).write_text('{"schema":99}')
        with mock.patch.object(backend.Broker, 'open') as opened:
            code = backend.main(['--open-registered', '--source', str(self.source), '--session', str(self.session), '--state', str(self.state)])
        self.assertEqual(code, 3)
        opened.assert_not_called()
        self.assertEqual(backend.document(self.session / 'status.json')['phase'], 'failed')

    def test_open_registered_starts_settings_only_after_valid_registry(self):
        (self.state / backend.REGISTRY).write_text(json.dumps({'schema': 1, 'workspace': str(self.source)}))
        selected = dict(owner=self.source, version='test-fixture', input_location={'missing': False})
        with mock.patch.object(backend.Broker, 'installation', return_value=selected), mock.patch.object(backend.Broker, 'open') as opened:
            code = backend.main(['--open-registered', '--source', str(self.source), '--session', str(self.session), '--state', str(self.state)])
        self.assertEqual(code, 0)
        opened.assert_called_once_with({})

    def missing_selection(self):
        return dict(owner=self.source, workspace=self.source, port=self.source / 'Monado_Linux',
                    game=self.source / 'Monado_Linux/build/fixture/xcde-linux',
                    version='test-fixture', input_location={'missing': True, 'previous': '/authored/missing input'})

    def test_missing_input_retains_owner_and_open_registered_returns_three(self):
        (self.state / backend.REGISTRY).write_text(json.dumps({'schema': 1, 'workspace': str(self.source)}))
        before = (self.state / backend.REGISTRY).read_bytes()
        with mock.patch.object(backend.Broker, 'installation', return_value=self.missing_selection()), mock.patch.object(backend.Broker, 'open') as opened:
            code = backend.main(['--open-registered', '--source', str(self.source), '--session', str(self.session), '--state', str(self.state)])
        self.assertEqual(code, 3)
        opened.assert_not_called()
        status = backend.document(self.session / 'status.json')
        self.assertEqual(status['phase'], 'input_missing')
        self.assertEqual(status['output'], str(self.source))
        self.assertEqual(status['input'], '')
        self.assertEqual(status['input_previous'], '/authored/missing input')
        self.assertFalse(status['can_open'])
        self.assertEqual((self.state / backend.REGISTRY).read_bytes(), before)

    def test_input_moved_after_registration_is_detected_before_any_launch(self):
        self.broker.registered = self.source
        with mock.patch.object(self.broker, 'installation', return_value=self.missing_selection()), mock.patch.object(self.broker, 'verify_launch') as verify, mock.patch.object(self.broker, 'popen') as spawn:
            self.assertFalse(self.broker.open({}))
        verify.assert_not_called(); spawn.assert_not_called()
        self.assertEqual(self.broker.status['phase'], 'input_missing')

    def test_relocation_uses_current_helper_owned_checker_then_readonly_launch_check(self):
        selected = self.missing_selection()
        self.broker.registered = self.source
        order = []
        def relocate(port, game, replacement, *, checker, cancel):
            self.assertIs(cancel, self.broker.cancelled)
            self.assertEqual((port, game, replacement), (selected['port'], selected['game'], self.input))
            checker(replacement)
            order.append('relocated')
        helper = SimpleNamespace(relocate=mock.Mock(side_effect=relocate))
        with mock.patch.object(self.broker, 'installation', return_value=selected), mock.patch.object(backend, 'input_location', return_value=helper), mock.patch.object(self.broker, 'run_command', return_value='OK') as checked, mock.patch.object(self.broker, 'verify_launch', side_effect=lambda value: order.append('verified')):
            self.broker.relocate({'input': str(self.input)})
        self.assertEqual(order, ['relocated', 'verified'])
        self.assertEqual(checked.call_args.args[0][-2:], [ROOT / 'Monado_Linux/tools/extract/check_dump.py', self.input])
        self.assertEqual(self.broker.status['phase'], 'installed')
        self.assertTrue(self.broker.status['can_open'])
        self.assertEqual(self.broker.status['input_previous'], '')
        self.assertFalse(self.output.exists())

    def test_relocation_failure_keeps_recovery_unopenable_and_does_not_build(self):
        selected = self.missing_selection()
        self.broker.registered = self.source
        self.broker.missing_input(selected)
        with mock.patch.object(self.broker, 'installation', return_value=selected), mock.patch.object(backend, 'input_location', return_value=SimpleNamespace(relocate=mock.Mock(side_effect=ValueError('Different game input')))), mock.patch.object(self.broker, 'verify_launch') as verify, mock.patch.object(self.broker, 'build') as build:
            self.broker.dispatch(self.request(action='relocate'))
            self.broker.thread.join(2)
        self.assertEqual(self.broker.status['phase'], 'failed')
        self.assertFalse(self.broker.status['can_open'])
        self.assertEqual(self.broker.status['input_previous'], '/authored/missing input')
        verify.assert_not_called(); build.assert_not_called()

    def test_actual_service_inspects_authored_fixture_then_stops_without_building(self):
        session = self.base / 'second session'; session.mkdir(mode=0o700)
        state = self.base / 'second state'; state.mkdir(mode=0o700)
        command = [sys.executable, '-B', str(ROOT / 'tools/builder_backend.py'), '--serve',
                   '--source', str(self.source), '--session', str(session), '--state', str(state)]
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        def stop():
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
        self.addCleanup(stop)
        def await_status(phase):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                path = session / 'status.json'
                if path.exists():
                    value = backend.document(path)
                    if value['phase'] == phase:
                        return value
                if child.poll() is not None:
                    self.fail('authored broker service exited early: ' + child.communicate()[0].decode())
                time.sleep(.02)
            self.fail('authored broker service did not reach ' + phase)
        await_status('welcome')
        request = self.request()
        backend.atomic(session / 'request.json', request)
        status = await_status('ready')
        self.assertEqual(status['request_id'], request['id'])
        self.assertIn('OK authored input fixture', status['detail'])
        self.assertFalse(self.output.exists())
        self.assertFalse((state / backend.REGISTRY).exists())
        child.terminate(); child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0)

    def test_flat_status_json_and_duplicate_metadata_rejected(self):
        status = backend.document(self.session / 'status.json')
        self.assertEqual(status['schema'], 1)
        self.assertFalse(any(isinstance(value, (dict, list)) for value in status.values()))
        target = self.session / 'duplicate.json'
        target.write_text('{"id":"one","id":"two"}')
        with self.assertRaisesRegex(backend.BuilderError, 'Duplicate JSON'):
            backend.document(target)


if __name__ == '__main__':
    unittest.main()
