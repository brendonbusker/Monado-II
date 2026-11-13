"""Authored fixture tests for the standalone builder's binary/package boundary."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import subprocess
import unittest
from unittest import mock

if sys.platform != 'linux':
    raise unittest.SkipTest('standalone AppImage bootstrap is Linux-only')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import builder_bootstrap as bootstrap
import build_builder_appimage as packager
import builder_backend as backend


def identity(data, mode=0o644):
    return dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), mode=mode)


def write(root, name, data, mode=0o644):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


class BuilderPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monado-builder-package-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_allowlist_detects_extra_file_directory_link_and_changed_mode(self):
        stage = self.root / 'stage'
        stage.mkdir()
        file = write(stage, 'usr/python/bin/python3.14', b'authored fixture', 0o755)
        identities = {'usr/python/bin/python3.14': identity(b'authored fixture', 0o755)}
        bootstrap.verify(stage, identities)
        file.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'manifest'):
            bootstrap.verify(stage, identities)
        file.chmod(0o755)
        extra = write(stage, 'unexpected.txt', b'not allowed')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            bootstrap.verify(stage, identities)
        extra.unlink()
        (stage / 'unexpected').mkdir()
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            bootstrap.verify(stage, identities)
        (stage / 'unexpected').rmdir()
        linked = stage / 'linked'
        linked.symlink_to(file)
        with self.assertRaises(ValueError):
            bootstrap.verify(stage, identities)

    def test_runtime_cache_is_stable_and_detects_tampering(self):
        app = self.root / 'AppDir'
        app.mkdir()
        data = b'private interpreter fixture'
        write(app, 'usr/python/bin/python3.14', data, 0o755)
        state = self.root / 'app data with spaces'
        state.mkdir()
        identities = {'usr/python/bin/python3.14': identity(data, 0o755)}
        runtime, first = bootstrap.copy_runtime(app, state, identities)
        again, second = bootstrap.copy_runtime(app, state, identities)
        self.assertEqual((runtime, first), (again, second))
        self.assertNotEqual(runtime.parent, app)
        (runtime / 'bin/python3.14').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'manifest'):
            bootstrap.copy_runtime(app, state, identities)

    def test_unsafe_data_paths_are_rejected(self):
        original = self.root / 'ordinary'
        original.mkdir()
        linked = self.root / 'link'
        linked.symlink_to(original, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical'):
            bootstrap.ordinary_dir(linked)
        for path in ('../outside', '/absolute', 'a/../b', 'a\\b', 'a//b', 'a:b'):
            with self.assertRaises(ValueError):
                bootstrap.relative(path)

    def source_archive(self):
        members = {'tools/publication_guard.py': b'def verify_tree(root):\n    return []\n',
                   'tools/builder_backend.py': b'# authored worker fixture\n'}
        manifest = bootstrap.encoded(dict(schema=1, project='Monado II', files={
            name: {k: v for k, v in identity(data).items() if k != 'mode'}
            for name, data in members.items()}))
        members['publication-manifest.json'] = manifest
        app = self.root / 'AppDir'
        (app / bootstrap.ARCHIVE).parent.mkdir(parents=True)
        archive_path = app / bootstrap.ARCHIVE
        with tarfile.open(archive_path, 'w:gz') as archive:
            for name, data in members.items():
                member = tarfile.TarInfo('source/' + name)
                member.size = len(data)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(data))
        return app, identity(archive_path.read_bytes()), manifest

    def test_cached_source_manifest_must_match_trusted_archive(self):
        app, archive_identity, expected = self.source_archive()
        state = self.root / 'state'
        state.mkdir()
        source = bootstrap.unpack_source(app, state, archive_identity)
        self.assertEqual((source / 'publication-manifest.json').read_bytes(), expected)
        self.assertEqual(bootstrap.unpack_source(app, state, archive_identity), source)
        # Changing both a cached source file and its cached manifest must never
        # bless executable Python that is absent from the bundled archive.
        guard = source / 'tools/publication_guard.py'
        guard.write_bytes(b'raise RuntimeError("untrusted cached code ran")\n')
        manifest = json.loads(expected)
        metadata = identity(guard.read_bytes())
        manifest['files']['tools/publication_guard.py'] = {k: v for k, v in metadata.items() if k != 'mode'}
        (source / 'publication-manifest.json').write_bytes(bootstrap.encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'differs from bundled archive'):
            bootstrap.unpack_source(app, state, archive_identity)

    def test_archive_cannot_install_links_or_parent_traversal(self):
        app = self.root / 'AppDir'
        archive_path = app / bootstrap.ARCHIVE
        archive_path.parent.mkdir(parents=True)
        with tarfile.open(archive_path, 'w:gz') as archive:
            data = b'{}'
            good = tarfile.TarInfo('source/publication-manifest.json')
            good.size, good.mode = len(data), 0o644
            archive.addfile(good, io.BytesIO(data))
            bad = tarfile.TarInfo('source/tools/../escape')
            bad.size, bad.mode = 1, 0o644
            archive.addfile(bad, io.BytesIO(b'x'))
        state = self.root / 'state'
        state.mkdir()
        with self.assertRaises(ValueError):
            bootstrap.unpack_source(app, state, identity(archive_path.read_bytes()))
        self.assertFalse((state / 'escape').exists())

    def test_packager_checks_unreviewed_source_before_compiling(self):
        output = self.root / 'output'
        with mock.patch.object(packager.release, '_document', side_effect=ValueError('unreviewed source')), \
                mock.patch.object(packager, 'compile_frontend') as compile_frontend:
            with self.assertRaisesRegex(ValueError, 'unreviewed source'):
                packager.package(ROOT, ROOT / 'Monado_Linux', output, self.root / 'test.AppImage')
            compile_frontend.assert_not_called()
        self.assertFalse(output.exists())

    def test_legacy_dry_run_checks_native_without_creating_registry(self):
        app = self.root / 'AppDir'
        app.mkdir()
        state = self.root / 'must remain absent'
        args = SimpleNamespace(data_dir=state, dry_run=True, state_root=self.root / 'owner/runs/profile')
        manifest = dict(migration={'adjacent_workspace': True}, files={bootstrap.ARCHIVE: {}})
        with mock.patch.object(bootstrap, 'validate_image', return_value=manifest), \
                mock.patch.object(bootstrap, 'unpack_source', return_value=self.root), \
                mock.patch.object(bootstrap, 'adjacent_workspace', return_value=self.root / 'workspace'), \
                mock.patch.object(bootstrap, 'legacy_command', return_value=(['fixture', '--dry-run'], {'owner': 'fixture'})) as command, \
                mock.patch.object(bootstrap.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.assertEqual(bootstrap.run(app, args), 0)
        command.assert_called_once_with(self.root, self.root / 'workspace', args.state_root, dry_run=True)
        self.assertFalse(state.exists())

    def test_moved_migration_image_can_use_registry_or_first_run(self):
        moved = self.root / 'moved image'
        moved.mkdir()
        executable = write(moved, 'Monado-II.AppImage', b'authored image fixture', 0o755)
        with mock.patch.dict(os.environ, {'APPIMAGE': str(executable)}):
            self.assertIsNone(bootstrap.adjacent_workspace(required=False))
            with self.assertRaisesRegex(ValueError, 'requires the adjacent'):
                bootstrap.adjacent_workspace()
            (moved / 'Monado_Linux').mkdir()
            self.assertEqual(bootstrap.adjacent_workspace(required=False), moved)
            (moved / 'Monado_Linux').rmdir()
            elsewhere = self.root / 'unrelated port'
            elsewhere.mkdir()
            (moved / 'Monado_Linux').symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'canonical'):
                bootstrap.adjacent_workspace(required=False)

    def test_legacy_command_preserves_explicit_profile_and_bound_selection(self):
        selected = dict(python=self.root / 'owner/Monado_Linux/.venv/bin/python',
            port=self.root / 'owner/Monado_Linux/updates/update-next/workspace/Monado_Linux',
            launcher=self.root / 'launcher', game=self.root / 'separate-game-payload',
            state=self.root / 'owner/Monado_Linux/play/launcher')
        class Broker:
            def installation(self, workspace, *, follow_active=True):
                self.follow_active = follow_active
                return selected
            launcher_command = backend.Broker.launcher_command
        inherited = self.root / 'owner/Monado_Linux/runs/isolated-profile'
        with mock.patch.object(bootstrap, 'backend_module', return_value=SimpleNamespace(Broker=Broker)):
            command, actual = bootstrap.legacy_command(self.root, self.root, inherited, dry_run=True)
        self.assertEqual(actual, selected)
        self.assertEqual(command[command.index('--state-root') + 1], str(inherited))
        self.assertEqual(command[command.index('--game-executable') + 1], str(selected['game']))
        self.assertEqual(command[-1], '--dry-run')

    def test_private_python_clone_needs_no_host_python_libraries_or_notices(self):
        base = self.root / 'persistent python'
        stdlib = base / 'lib/python3.14'
        wrapper = write(self.root, 'new-entry-wrapper', b'new authored entry', 0o755)
        executable = write(base, 'bin/python3.14', b'old authored entry', 0o755)
        write(base, 'bin/python3.14.real', b'private real interpreter', 0o755)
        write(base, 'monado-private-python.json', bootstrap.encoded(dict(schema=1, project='Monado II', python=[3, 14])))
        write(stdlib, 'os.py', b'# private standard library fixture\n')
        write(stdlib, 'LICENSE.txt', b'private Python complete notice')
        for extension in packager.EXTENSIONS:
            write(stdlib, 'lib-dynload/' + extension + '.cpython-314-x86_64-linux-gnu.so', b'private extension ' + extension.encode(), 0o755)
        for soname in packager.PYTHON_LIBS:
            write(base, 'lib/' + soname, b'private support library ' + soname.encode(), 0o755)
        for package in set(packager.PYTHON_LIBS.values()) | {'python3.14'}:
            name = 'Python-copyright.txt' if package == 'python3.14' else package + '-copyright.txt'
            write(base, 'share/doc/monado-ii/' + name, b'complete private component notice ' + name.encode())
        write(base, 'share/doc/monado-ii/Apache-2.0.txt', b'complete private Apache licence')
        probe = dict(version=[3, 14, 4], prefix=str(base), stdlib=str(stdlib))
        actual_regular = packager.image.regular
        def private_only(path, *args, **kwargs):
            path = Path(path)
            self.assertTrue(path.is_relative_to(self.root), 'host resource read during private clone: ' + str(path))
            return actual_regular(path, *args, **kwargs)
        files, commands = {}, []
        with mock.patch.object(packager, 'run', return_value=json.dumps(probe)), \
                mock.patch.object(packager, 'needed', return_value={'libc.so.6'}), \
                mock.patch.object(packager.image, 'regular', side_effect=private_only):
            packager.private_python(files, wrapper, commands, python=executable)
        self.assertEqual(files['usr/python/bin/python3.14.real'][0], b'private real interpreter')
        self.assertEqual(files['usr/python/bin/python3.14'][0], b'new authored entry')
        self.assertIn('usr/python/share/doc/monado-ii/Python-copyright.txt', files)
        self.assertIn('usr/share/doc/monado-ii/Apache-2.0.txt', files)

    def test_private_python_manifest_excludes_gpl_only_extensions(self):
        self.assertNotIn('readline', packager.EXTENSIONS)
        self.assertNotIn('_gdbm', packager.EXTENSIONS)
        self.assertNotIn('_dbm', packager.EXTENSIONS)
        self.assertNotIn('libpython3.14.so', packager.PYTHON_LIBS)
        self.assertNotIn('libvulkan.so.1', packager.PYTHON_LIBS)


if __name__ == '__main__':
    unittest.main()
