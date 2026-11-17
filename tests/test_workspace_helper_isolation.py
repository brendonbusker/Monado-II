"""LINUX-121: real registered-owner migration with source-bound helper policies.

All installs, input/native files, and launch scripts are authored fixtures.
Only the settings-process boundary is replaced by a harmless recorded spawner.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(sys.platform == 'linux', 'Linux registered-installation migration')
class WorkspaceHelperIsolation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado helper policies ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.a = self.installation('older owner', 'A')
        self.b = self.installation('new dev', 'B')
        self.backend = load(ROOT / 'tools/builder_backend.py', '_tested_helper_backend')
        self.bootstrap = load(ROOT / 'tools/builder_bootstrap.py', '_tested_helper_bootstrap')

    def installation(self, name, owner):
        workspace = self.base / name
        workspace.mkdir()
        files = {'README.md': b'# Authored source fixture\n',
                 'update-version.json': b'{"schema":1,"protocol":1,"version":"0.1.27"}',
                 'Monado_Linux/scripts/install_layout.py': (ROOT / 'Monado_Linux/scripts/install_layout.py').read_bytes(),
                 'Monado_Linux/scripts/launcher_linux.py': b'import sys\nprint("AUTHORED SETTINGS CHECK", "--dry-run" in sys.argv)\n'}
        for stem in ('update_linux', 'update_release', 'installation_version', 'publication_guard'):
            data = (ROOT / 'tools' / (stem + '.py')).read_bytes()
            if stem in ('installation_version', 'publication_guard'):
                data += ('\nSOURCE_OWNER_TAG = ' + repr(owner) + '\n').encode()
            if stem == 'publication_guard' and owner == 'A':
                data += b'\n_original_path_problem = path_problem\ndef path_problem(name):\n    return "foreign fixture policy" if name == "B_ONLY.md" else _original_path_problem(name)\n'
            files['tools/' + stem + '.py'] = data
        if owner == 'B':
            files['B_ONLY.md'] = b'# New reviewed authored feature\n'
        files['publication-policy.json'] = b'{"schema":1,"licensed_media":{}}'
        for name, data in files.items():
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (workspace / 'publication-manifest.json').write_text(json.dumps(dict(schema=1, project='Monado II', source_only=True,
            files={name:dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) for name,data in files.items()})))
        port = workspace / 'Monado_Linux'
        state = port / 'play/launcher'
        (state / 'save').mkdir(parents=True)
        (state / 'save/slot').write_bytes(b'AUTHORED SAVE SENTINEL')
        (state / 'xcde.ini').write_bytes(b'cheat_exp = 0\n')
        (workspace / 'game_files/exefs').mkdir(parents=True)
        (workspace / 'game_files/romfs').mkdir()
        (workspace / 'game_files/romfs/input').write_bytes(b'AUTHORED INPUT SENTINEL')
        identity = 'fixture-20261116T000000Z-01234567'
        game = port / ('build/' + identity + '-game/xcde-linux')
        launcher = port / ('build/' + identity + '-launcher/monado-launcher')
        for path in (game, launcher):
            path.parent.mkdir(parents=True)
            path.write_bytes(b'AUTHORED NONEXECUTED NATIVE PLACEHOLDER')
        receipt = port / ('runs/local-build/' + identity + '/receipt.json')
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(dict(schema=1,status='passed',paths=dict(game=str(game),launcher=str(launcher),state=str(state)))))
        metadata = port / '.deps/metadata/gui-build.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps(dict(schema=1,status='passed',artifact_kind='local-gui-build',build_id=identity,build_receipt_sha256=digest(receipt))))
        return workspace

    def foreign_modules(self):
        guard = load(self.a / 'tools/publication_guard.py', '_foreign_helper_guard')
        version = load(self.a / 'tools/installation_version.py', '_foreign_helper_version')
        # Import the release helper with the exact older generic guard present.
        with mock.patch.dict(sys.modules, {'publication_guard': guard}):
            release = load(self.a / 'tools/update_release.py', '_foreign_helper_release')
        return dict(publication_guard=guard, update_release=release, installation_version=version)

    def native_boundary(self):
        # Installed input/ELF execution is independent coverage. The real source,
        # selection, metadata receipt, registry, and migration code remains active.
        return mock.patch.object(self.backend, 'input_location', return_value=types.SimpleNamespace(
            inspect=lambda port,game:dict(missing=False, input=str(port.parent/'game_files'), previous='')))

    def test_each_updater_uses_own_guard_release_and_version_with_foreign_cache(self):
        foreign = self.foreign_modules()
        with mock.patch.dict(sys.modules, foreign):
            new = load(self.b / 'tools/update_linux.py', '_new_workspace_updater')
            new.installed_sources(self.b)
            self.assertIsNone(new.path_problem('B_ONLY.md'))
            self.assertIsNone(new.update_release.path_problem('B_ONLY.md'))
            self.assertEqual(new.installed_version.SOURCE_OWNER_TAG, 'B')
            self.assertIs(sys.modules['publication_guard'], foreign['publication_guard'])
            self.assertIs(sys.modules['update_release'], foreign['update_release'])
            self.assertIs(sys.modules['installation_version'], foreign['installation_version'])
            for name in ('update_release', 'installed_version'):
                self.assertTrue(Path(getattr(new, name).__file__).is_relative_to(self.b))

    def test_normal_bootstrap_registered_A_then_adjacent_B_runs_real_broker_migration(self):
        state = self.base / 'builder-state'; state.mkdir()
        (state / self.backend.REGISTRY).write_text(json.dumps(dict(schema=1,workspace=str(self.a))))
        appdir = self.base / 'authored-appdir'; (appdir/'usr/lib').mkdir(parents=True)
        spawned = []
        checks = []
        def spawn(argv, **kwargs):
            if '--command-worker' in argv:
                self.assertIn('--dry-run', argv)
                self.assertIn(str(self.b/'Monado_Linux/scripts/launcher_linux.py'), argv)
                checks.append(argv)
                return subprocess.Popen(argv, **kwargs)
            self.assertEqual(Path(argv[2]), self.b/'Monado_Linux/scripts/launcher_linux.py')
            self.assertNotIn('--dry-run', argv)
            os.write(kwargs['stdout'], b'AUTHORED SETTINGS HANDOFF\n')
            spawned.append((argv,kwargs['cwd']))
            return types.SimpleNamespace(wait=lambda:0)
        real = self.backend.Broker
        class RecordedBroker(real):
            def __init__(inner, *args, **kwargs):
                super().__init__(*args, popen=spawn, **kwargs)
        args = types.SimpleNamespace(data_dir=state, state_root=None, dry_run=False, self_check=False,
            setup=False, headless_frames=None, source_build=False)
        before = {str(p):p.read_bytes() for w in (self.a,self.b) for d in ('Monado_Linux/play/launcher','game_files')
                  for p in (w/d).rglob('*') if p.is_file()}
        manifest = dict(migration={'adjacent_workspace':True}, files={self.bootstrap.ARCHIVE:{}})
        foreign = self.foreign_modules()
        with mock.patch.dict(sys.modules,foreign), self.native_boundary(), \
             mock.patch.object(real,'venv_python',return_value=Path(sys.executable)), \
             mock.patch.object(self.backend,'Broker',RecordedBroker), \
             mock.patch.object(self.bootstrap,'validate_image',return_value=manifest), \
             mock.patch.object(self.bootstrap,'copy_runtime',return_value=(Path(sys.prefix),'fixture-runtime')), \
             mock.patch.object(self.bootstrap,'unpack_source',return_value=self.b), \
             mock.patch.object(self.bootstrap,'copy_native_runtime',return_value=None), \
             mock.patch.object(self.bootstrap,'adjacent_workspace',return_value=self.b), \
             mock.patch.object(self.bootstrap,'backend_module',return_value=self.backend):
            self.assertEqual(self.bootstrap.run(appdir,args),0)
        self.assertEqual(len(spawned),1)
        self.assertEqual(len(checks),1)
        self.assertEqual(json.loads((state/self.backend.REGISTRY).read_text())['workspace'],str(self.b))
        self.assertIn(b'AUTHORED SETTINGS HANDOFF',(state/'settings-launcher.log').read_bytes())
        after = {name:Path(name).read_bytes() for name in before}
        self.assertEqual(after,before)

    def test_source_tamper_and_linked_helper_still_fail_closed(self):
        with mock.patch.dict(sys.modules,self.foreign_modules()):
            new = load(self.b/'tools/update_linux.py','_new_guard_negative')
            (self.b/'B_ONLY.md').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Local source changes'):
                new.installed_sources(self.b)
            target = self.b/'tools/publication_guard.py';target.unlink();target.symlink_to(self.a/'tools/publication_guard.py')
            with self.assertRaisesRegex(ValueError,'helper'):
                load(self.b/'tools/update_linux.py','_linked_guard_negative')

    def test_failed_runtime_dry_run_blocks_registration_and_settings_spawn(self):
        script = self.b / 'Monado_Linux/scripts/launcher_linux.py'
        script.write_bytes(b'print("AUTHORED RUNTIME REFUSAL")\nraise SystemExit(23)\n')
        manifest_path = self.b / 'publication-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['Monado_Linux/scripts/launcher_linux.py'] = dict(
            bytes=script.stat().st_size, sha256=digest(script))
        manifest_path.write_text(json.dumps(manifest))
        state = self.base / 'refusal-state'; state.mkdir()
        registry = state / self.backend.REGISTRY
        registry.write_text(json.dumps(dict(schema=1, workspace=str(self.a))))
        original = registry.read_bytes()
        session = self.base / 'refusal-session'; session.mkdir(mode=0o700)
        def spawn(argv, **kwargs):
            self.assertIn('--command-worker', argv, 'failed admission must not open settings')
            self.assertIn('--dry-run', argv)
            return subprocess.Popen(argv, **kwargs)
        with mock.patch.dict(sys.modules, self.foreign_modules()), self.native_boundary(), \
             mock.patch.object(self.backend.Broker, 'venv_python', return_value=Path(sys.executable)):
            broker = self.backend.Broker(self.b, session, state, popen=spawn)
            with self.assertRaisesRegex(self.backend.BuilderError, 'AUTHORED RUNTIME REFUSAL'):
                broker.adopt_and_open(dict(output=str(self.b)))
        self.assertEqual(registry.read_bytes(), original)
        self.assertFalse((state / 'settings-launcher.log').exists())

    def test_hardlinked_and_oversized_helpers_are_not_executed(self):
        target = self.b / 'tools/publication_guard.py'
        os.link(target, self.base / 'guard-hardlink.py')
        with self.assertRaisesRegex(ValueError, 'helper'):
            load(self.b / 'tools/update_release.py', '_hardlinked_guard_negative')
        (self.base / 'guard-hardlink.py').unlink()
        with target.open('wb') as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, 'helper'):
            load(self.b / 'tools/update_release.py', '_oversized_guard_negative')

    def test_concurrent_source_loads_do_not_share_generic_module_aliases(self):
        errors = []
        def worker(workspace, tag):
            try:
                for i in range(12):
                    u = load(workspace/'tools/update_linux.py', '_concurrent_'+tag+str(i))
                    self.assertEqual(u.installed_version.SOURCE_OWNER_TAG,tag)
                    self.assertEqual(u.path_problem('B_ONLY.md') is None,tag=='B')
            except BaseException as e:errors.append(e)
        foreign = self.foreign_modules()
        with mock.patch.dict(sys.modules,foreign):
            threads=[threading.Thread(target=worker,args=(self.a,'A')),threading.Thread(target=worker,args=(self.b,'B'))]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertFalse(errors,errors)
            self.assertIs(sys.modules['publication_guard'],foreign['publication_guard'])

if __name__ == '__main__':unittest.main()
