"""Staged migration checks use candidate artifacts and import native siblings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

if sys.platform != 'linux':
    raise unittest.SkipTest('Linux standalone migration startup')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import builder_backend as backend
import builder_bootstrap as bootstrap


class MigrationStartup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado migration startup ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.port = self.root / 'candidate/Monado_Linux'
        (self.port / 'scripts').mkdir(parents=True)
        self.selected = dict(python=Path(sys.executable), port=self.port,
            launcher=self.port / 'build/authored-gui/monado-launcher',
            game=self.port / 'build/authored-game/xcde-linux',
            state=self.root / 'owner/Monado_Linux/play/launcher')

    def command(self, *, dry_run=False):
        with mock.patch.object(bootstrap, 'backend_module', return_value=backend), \
                mock.patch.object(backend.Broker, 'installation', return_value=self.selected) as select:
            command, selected = bootstrap.legacy_command(ROOT, self.port.parent, dry_run=dry_run)
        select.assert_called_once_with(self.port.parent, follow_active=not dry_run)
        self.assertEqual(selected, self.selected)
        self.assertNotIn('-I', command)
        self.assertIn('-B', command)
        return command

    def test_normal_launch_follows_current_but_dry_run_selects_exact_candidate(self):
        normal = self.command()
        checked = self.command(dry_run=True)
        self.assertNotIn('--dry-run', normal)
        self.assertEqual(checked, normal + ['--dry-run'])

    def test_actual_script_sibling_import_without_bytecode_or_profile_writes(self):
        scripts = self.port / 'scripts'
        (scripts / 'run_linux.py').write_text("VALUE = 'authored sibling fixture'\n")
        script = scripts / 'launcher_linux.py'
        script.write_text('import json,sys,run_linux\n'
            'print(json.dumps(dict(value=run_linux.VALUE, module=run_linux.__file__, '
            'bytecode=sys.dont_write_bytecode, argv=sys.argv[1:])))\n')
        environment = dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8')
        negative = subprocess.run([sys.executable, '-I', '-B', str(script)],
            capture_output=True, text=True, env=environment, timeout=10)
        self.assertNotEqual(negative.returncode, 0)
        self.assertIn('ModuleNotFoundError', negative.stderr)
        command = self.command(dry_run=True)
        positive = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(positive.returncode, 0, positive.stderr)
        value = json.loads(positive.stdout)
        self.assertEqual(value['value'], 'authored sibling fixture')
        self.assertEqual(Path(value['module']), scripts / 'run_linux.py')
        self.assertTrue(value['bytecode'])
        self.assertIn('--dry-run', value['argv'])
        self.assertFalse((scripts / '__pycache__').exists())
        self.assertFalse(self.selected['state'].exists())

    def test_exact_workspace_validation_never_consults_old_active_selection(self):
        owner = self.root / 'owner'
        candidate = owner / 'Monado_Linux/updates/candidate/workspace'
        port = candidate / 'Monado_Linux'
        port.mkdir(parents=True)
        active = owner / 'Monado_Linux/updates/active.json'
        active.write_text('{"schema":1}')
        state = owner / 'Monado_Linux/play/launcher'
        state.mkdir(parents=True)
        game = port / 'build/game/xcde-linux'
        gui = port / 'build/gui/monado-launcher'
        for path in (game, gui):
            path.parent.mkdir(parents=True)
            path.write_text('authored placeholder never executed')
        receipt = port / 'runs/local-build/authored/receipt.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(dict(status='passed', paths=dict(game=str(game), launcher=str(gui), state=str(state)))))
        metadata = port / '.deps/metadata/gui-build.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps(dict(schema=1, status='passed', artifact_kind='local-gui-build',
            build_id='authored', build_receipt_sha256=backend.digest(receipt))))
        layout = SimpleNamespace(installation_root=lambda p: owner, game_port=lambda p: port,
                                 profile_port=lambda p: owner / 'Monado_Linux')
        updater = SimpleNamespace(active_record=mock.Mock(side_effect=AssertionError('old selection must not be consulted')),
            installed_sources=mock.Mock(), layout_module=lambda p: layout)
        def load(path, name):
            return updater if str(path).endswith('update_linux.py') else layout
        selector = object.__new__(backend.Broker)
        with mock.patch.object(backend, 'module', side_effect=load), \
                mock.patch.object(backend, 'input_location', return_value=SimpleNamespace(inspect=lambda p, g: {'missing':False})), \
                mock.patch.object(backend.Broker, 'venv_python', return_value=Path(sys.executable)), \
                mock.patch.object(backend.Broker, 'version', return_value='authored'):
            selected = selector.installation(candidate, follow_active=False)
        updater.active_record.assert_not_called()
        updater.installed_sources.assert_called_once_with(candidate)
        self.assertEqual(selected['workspace'], candidate)
        self.assertEqual(selected['game'], game)
        self.assertEqual(selected['launcher'], gui)
        self.assertEqual(selected['state'], state)

    def migration_open(self, *, available, inherited_state=None):
        """Exercise bootstrap routing with authored status and no child execution."""
        app = self.root / 'AppDir'
        app.mkdir()
        data = self.root / 'builder data'
        manifest = dict(migration={'adjacent_workspace': True},
                        files={bootstrap.ARCHIVE: {}})
        args = SimpleNamespace(data_dir=data, dry_run=False, state_root=inherited_state,
            setup=False, self_check=False, headless_frames=None, screenshot=None)
        broker = SimpleNamespace(adopt=mock.Mock(), open=mock.Mock(return_value=available))
        backend_module = SimpleNamespace(Broker=mock.Mock(return_value=broker))
        def adopt(request):
            # Adoption persists the same owner and recovery status before the
            # frontend/worker handoff; the fallback must not discard them.
            session = backend_module.Broker.call_args.args[1]
            (data / 'installation.json').write_text(json.dumps(dict(schema=1, workspace=str(self.port.parent))))
            (session / 'status.json').write_text(json.dumps(dict(
                schema=1, phase='installed' if available else 'input_missing')))
        broker.adopt.side_effect = adopt
        worker = SimpleNamespace(poll=lambda: 0, returncode=0)
        frontend = SimpleNamespace(poll=lambda: 0, returncode=0)
        with mock.patch.object(bootstrap, 'validate_image', return_value=manifest), \
                mock.patch.object(bootstrap, 'copy_runtime', return_value=(self.root / 'private Python', 'authored')), \
                mock.patch.object(bootstrap, 'unpack_source', return_value=self.root / 'source'), \
                mock.patch.object(bootstrap, 'adjacent_workspace', return_value=self.port.parent), \
                mock.patch.object(bootstrap, 'backend_module', return_value=backend_module), \
                mock.patch.object(bootstrap, 'legacy_command', return_value=(['/authored/native-wrapper'], self.selected)) as legacy, \
                mock.patch.object(bootstrap.subprocess, 'Popen', side_effect=[worker, frontend]) as spawn, \
                mock.patch.object(bootstrap.subprocess, 'run', side_effect=AssertionError('redundant registered-open attempt')), \
                mock.patch.object(bootstrap, 'stop'):
            result = bootstrap.run(app, args)
        return result, broker, backend_module, spawn, legacy, data

    def test_missing_inherited_input_opens_recovery_frontend_and_keeps_owner(self):
        result, broker, _, spawn, legacy, data = self.migration_open(available=False)
        self.assertEqual(result, 0)
        broker.adopt.assert_called_once()
        broker.open.assert_called_once()
        legacy.assert_not_called()
        self.assertEqual(spawn.call_count, 2, 'missing input must show the recovery worker and frontend')
        self.assertIn('--serve', spawn.call_args_list[0].args[0])
        self.assertEqual(spawn.call_args_list[1].args[0][0], self.root / 'AppDir/usr/bin/monado-builder')
        self.assertEqual(json.loads((data / 'installation.json').read_text())['workspace'], str(self.port.parent))
        status = next((data / 'sessions').glob('*/status.json'))
        self.assertEqual(json.loads(status.read_text())['phase'], 'input_missing')

    def test_available_inherited_installation_still_opens_without_setup(self):
        result, broker, _, spawn, legacy, _ = self.migration_open(available=True)
        self.assertEqual(result, 0)
        broker.adopt.assert_called_once()
        broker.open.assert_called_once()
        spawn.assert_not_called()
        legacy.assert_not_called()

    def test_explicit_inherited_profile_still_uses_native_picker_route(self):
        inherited = self.root / 'owner/Monado_Linux/play/launcher'
        result, broker, backend_module, spawn, legacy, _ = self.migration_open(
            available=False, inherited_state=inherited)
        self.assertEqual(result, 0)
        backend_module.Broker.assert_not_called()
        broker.adopt.assert_not_called()
        broker.open.assert_not_called()
        legacy.assert_called_once_with(self.root / 'source', self.port.parent, inherited)
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(spawn.call_args.args[0], ['/authored/native-wrapper'])


if __name__ == '__main__':
    unittest.main()
