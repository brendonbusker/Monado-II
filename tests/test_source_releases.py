"""Authored source-kit packaging tests; scanner policy is covered separately."""
from pathlib import Path
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
release = importlib.import_module('package_source_release')
ROOT = Path(__file__).resolve().parents[1]


class SourceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='monado-source-release-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / 'reviewed-source'
        self.source.mkdir()
        self.payloads = {
            'README.md': b'# Monado II\nAuthored fixture, no game data.\n',
            'LICENSE': b'Authored license fixture only\n',
            'publication-policy.json': b'{"schema": 1, "licensed_media": {}}\n',
            'Monado_Linux/runtime/example.c': b'int authored_linux(void) { return 1; }\n',
            'Monado_Linux/Play.sh': b'#!/bin/sh\nexit 0\n',
            'Monado_Windows/runtime/example.c': b'int authored_windows(void) { return 2; }\n',
            'Monado_Windows/Build.bat': b'@echo off\r\nrem authored fixture\r\n',
            'tools/check.py': b'print("authored fixture")\n',
            'update-version.json': b'{"schema":1,"protocol":1,"version":"0.1.16"}\n',
        }
        for name, data in self.payloads.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.manifest = dict(schema=1, project='Monado II', files={
            name: dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            for name, data in self.payloads.items()})
        self.save_manifest()
        self.guard = mock.patch.object(release, '_guard', autospec=True)
        self.guard_mock = self.guard.start()
        self.addCleanup(self.guard.stop)

    def save_manifest(self):
        (self.source / release.MANIFEST).write_bytes(release.encoded(self.manifest))

    def package(self, platform='linux', output='result', version='v0.1.0-test'):
        return release.package(self.source, platform, version, self.base / output)

    def archive_contents(self, receipt, output='result'):
        path = self.base / output / receipt['archive']
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                return {name.split('/', 1)[1]: archive.read(name) for name in archive.namelist()}
        with tarfile.open(path) as archive:
            return {item.name.split('/', 1)[1]: archive.extractfile(item).read() for item in archive.getmembers()}

    def assert_contents(self, receipt, platform):
        content = self.archive_contents(receipt)
        self.assertTrue(receipt['archive_readback_verified'])
        self.assertTrue(receipt['local_generation_required'])
        self.assertFalse(receipt['contains_compiled_binaries'])
        port = release.PORTS[platform]
        other = release.PORTS['windows' if platform == 'linux' else 'linux']
        self.assertTrue(any(name.startswith(port + '/') for name in content))
        self.assertFalse(any(name.startswith(other + '/') for name in content))
        manifest = json.loads(content[release.MANIFEST])
        self.assertEqual(manifest['platform'], platform)
        self.assertEqual(set(content), set(manifest['files']) | {release.MANIFEST})
        for name, metadata in manifest['files'].items():
            self.assertEqual(metadata['sha256'], hashlib.sha256(content[name]).hexdigest())
            self.assertEqual(metadata['bytes'], len(content[name]))
        self.assertIn(b'will not provide game files or tell you where', content['RELEASE_README.md'])
        status = json.loads(content['source-only-status.json'])
        self.assertEqual(status['kind'], 'source-only')
        self.assertFalse(status['contains_game_derived_code'])
        self.assertEqual(receipt['archived_files'], len(content))
        self.assertEqual(self.guard_mock.call_count, 4)

    def test_linux_tar_contains_only_linux_and_common_reviewed_sources(self):
        self.assert_contents(self.package(), 'linux')

    def test_windows_zip_contains_only_windows_and_common_reviewed_sources(self):
        self.assert_contents(self.package('windows'), 'windows')

    def test_platform_policy_drops_foreign_media_and_rebinds_its_exact_bytes(self):
        policy_name = 'publication-policy.json'
        foreign = 'Monado_Windows/tools/launcher/assets/gaur_plain.png'
        original = release.encoded(dict(schema=1, licensed_media={foreign: 'a' * 64}))
        (self.source / policy_name).write_bytes(original)
        self.manifest['files'][policy_name] = dict(bytes=len(original), sha256=hashlib.sha256(original).hexdigest())
        self.save_manifest()
        receipt = self.package()
        content = self.archive_contents(receipt)
        self.assertEqual(json.loads(content[policy_name])['licensed_media'], {})
        identity = json.loads(content[release.MANIFEST])['files'][policy_name]
        self.assertEqual(identity, dict(bytes=len(content[policy_name]), sha256=hashlib.sha256(content[policy_name]).hexdigest()))
        self.assertEqual((self.source / policy_name).read_bytes(), original)

    def test_linux_setup_and_old_updater_alias_are_identical_with_original_root(self):
        receipt = self.package(version='0.1.5')
        self.assertEqual(receipt['archive'], 'monado-ii-0.1.5-linux-setup.tar.gz')
        self.assertEqual(receipt['kind'], 'source-only')
        self.assertEqual(receipt['archive_aliases'], [dict(
            archive='monado-ii-0.1.5-linux-source.tar.gz',
            sha256=receipt['sha256'], bytes=receipt['bytes'])])
        output = self.base / 'result'
        setup = output / receipt['archive']
        compatibility = output / receipt['archive_aliases'][0]['archive']
        self.assertEqual(setup.read_bytes(), compatibility.read_bytes())
        for path in (setup, compatibility):
            with tarfile.open(path) as archive:
                self.assertTrue(all(item.name.startswith('monado-ii-0.1.5-linux-source/')
                                    for item in archive.getmembers()))
        checksums = (output / 'SHA256SUMS').read_text().splitlines()
        self.assertEqual(set(checksums), {
            receipt['sha256'] + '  monado-ii-0.1.5-linux-setup.tar.gz',
            receipt['sha256'] + '  monado-ii-0.1.5-linux-source.tar.gz'})
        for line in checksums:
            sha, name = line.split('  ')
            self.assertEqual(sha, release.digest(output / name))

    def test_windows_setup_has_no_unsupported_legacy_alias(self):
        receipt = self.package('windows', version='0.1.5')
        self.assertEqual(receipt['archive'], 'monado-ii-windows-original-implementation-setup.zip')
        self.assertEqual(receipt['archive_aliases'], [])
        output = self.base / 'result'
        self.assertEqual(sorted(p.name for p in output.iterdir()),
                         ['SHA256SUMS', receipt['archive'], 'release-receipt.json'])
        self.assertEqual((output / 'SHA256SUMS').read_text(),
                         receipt['sha256'] + '  ' + receipt['archive'] + '\n')

    def test_windows_implementation_identity_does_not_advance_with_linux_release(self):
        for version in ('0.1.16', '0.2.0'):
            with self.subTest(version=version):
                receipt = self.package('windows', output=version, version=version)
                content = self.archive_contents(receipt, output=version)
                self.assertEqual(receipt['archive'], release.WINDOWS_ARCHIVE)
                self.assertEqual(receipt['version'], 'original')
                self.assertEqual(receipt['source_release_version'], version)
                status = json.loads(content['source-only-status.json'])
                manifest = json.loads(content[release.MANIFEST])
                for metadata in (status, manifest, receipt):
                    self.assertEqual(metadata['windows_implementation'], 'original')
                    self.assertFalse(metadata['linux_feature_additions'])
                    self.assertEqual(metadata['source_release_version'], version)
                self.assertEqual(status['version'], 'original')
                self.assertEqual(manifest['release_version'], 'original')
                self.assertNotIn('update-version.json', content)
                self.assertNotIn(version.encode(), content['RELEASE_README.md'])
                self.assertIn(b'Original Windows implementation', content['RELEASE_README.md'])
                self.assertIn(b'no Linux feature additions', content['RELEASE_README.md'])
                with zipfile.ZipFile(self.base / version / receipt['archive']) as archive:
                    self.assertTrue(all(item.filename.startswith(
                        'monado-ii-windows-original-implementation/') for item in archive.infolist()))

    def test_linux_retains_linux_updater_version_and_metadata(self):
        receipt = self.package(version='0.1.16')
        content = self.archive_contents(receipt)
        self.assertEqual(receipt['version'], '0.1.16')
        self.assertEqual(json.loads(content['source-only-status.json'])['version'], '0.1.16')
        self.assertEqual(json.loads(content[release.MANIFEST])['release_version'], '0.1.16')
        self.assertEqual(content['update-version.json'], self.payloads['update-version.json'])
        self.assertNotIn('source_release_version', receipt)

    def test_current_workflow_packages_linux_without_mislabeling_native_windows(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/source-release.yml').read_text()
        self.assertNotIn('platform: windows', workflow)
        self.assertIn('archive_pattern: monado-ii-*-linux-*.tar.gz', workflow)
        self.assertIn('${{ matrix.archive_pattern }}', workflow)

    def test_native_windows_tree_cannot_be_exported_as_original_implementation(self):
        name = 'Monado_Windows/tools/build_windows_builder.py'
        data = b'# authored native builder fixture\n'
        (self.source / name).parent.mkdir(parents=True)
        (self.source / name).write_bytes(data)
        self.manifest['files'][name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.save_manifest()
        with self.assertRaisesRegex(release.ReleaseError, 'native Windows packager'):
            self.package('windows')
        self.assertFalse((self.base / 'result').exists())

    def test_corrupted_linux_alias_never_reaches_final_output(self):
        copy = release.shutil.copyfile

        def corrupt(source, target):
            copy(source, target)
            target.write_bytes(b'authored corrupt alias fixture')

        with mock.patch.object(release.shutil, 'copyfile', side_effect=corrupt):
            with self.assertRaisesRegex(release.ReleaseError, 'compatibility alias differs'):
                self.package(version='0.1.5')
        self.assertEqual(list((self.base / 'result').iterdir()), [])

    def test_linux_archive_is_deterministic(self):
        first = self.package(output='first')
        os.chmod(self.source / 'README.md', 0o755)
        second = self.package(output='second')
        self.assertEqual((self.base / 'first' / first['archive']).read_bytes(),
                         (self.base / 'second' / second['archive']).read_bytes())

    def test_windows_archive_is_deterministic(self):
        first = self.package('windows', output='first')
        second = self.package('windows', output='second')
        self.assertEqual((self.base / 'first' / first['archive']).read_bytes(),
                         (self.base / 'second' / second['archive']).read_bytes())

    def test_modes_and_timestamps_are_fixed(self):
        receipt = self.package()
        with tarfile.open(self.base / 'result' / receipt['archive']) as archive:
            for item in archive:
                self.assertEqual(item.mtime, 0)
                self.assertEqual(item.uid, 0)
                self.assertEqual(item.gid, 0)
                self.assertEqual(item.mode, 0o755 if item.name.endswith('.sh') else 0o644)

    def test_existing_output_is_not_overwritten(self):
        target = self.base / 'result'
        target.mkdir()
        (target / 'keep').write_text('preserve')
        with self.assertRaises(release.ReleaseError):
            self.package()
        self.assertEqual((target / 'keep').read_text(), 'preserve')

    def test_unsafe_version_tags_are_rejected(self):
        for value in ('', '../v1', '/absolute', 'v1/new', 'v1\n', 'v 1', 'v1;echo', 'v' * 65):
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                self.package(version=value)

    def test_extra_source_file_is_rejected(self):
        (self.source / 'unreviewed.txt').write_text('not in manifest')
        with self.assertRaises(release.ReleaseError):
            self.package()
        self.assertFalse((self.base / 'result').exists())

    def test_changed_reviewed_source_is_rejected(self):
        (self.source / 'README.md').write_text('modified')
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_missing_reviewed_source_is_rejected(self):
        (self.source / 'README.md').unlink()
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_unsafe_manifest_paths_are_rejected(self):
        for value in ('../secret', '/etc/passwd', 'a\\b', 'a//b', 'a/./b', 'a/../b', '.git/config',
                      'a:b', 'trailing. ', release.MANIFEST):
            self.manifest['files'] = {value: dict(sha256='0' * 64, bytes=0)}
            self.save_manifest()
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                self.package()

    def test_manifest_schema_and_identity_are_checked(self):
        for value in ('Wrong project', None):
            self.manifest['project'] = value
            self.save_manifest()
            with self.subTest(value=value), self.assertRaises(release.ReleaseError):
                self.package()

    def test_bool_byte_count_is_rejected(self):
        self.manifest['files']['README.md']['bytes'] = True
        self.save_manifest()
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_bool_schema_is_rejected(self):
        self.manifest['schema'] = True
        self.save_manifest()
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_duplicate_manifest_keys_are_rejected(self):
        raw = (self.source / release.MANIFEST).read_text()
        raw = raw.replace('"schema": 1', '"schema": 1, "schema": 1')
        (self.source / release.MANIFEST).write_text(raw)
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_source_symlink_is_rejected(self):
        path = self.source / 'README.md'
        path.unlink()
        try:
            path.symlink_to(self.source / 'LICENSE')
        except OSError:
            self.skipTest('host cannot create symlinks')
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_output_must_be_separate_from_source(self):
        with self.assertRaises(release.ReleaseError):
            release.package(self.source, 'linux', 'v1', self.source / 'release')
        self.assertFalse((self.source / 'release').exists())

    def test_git_metadata_is_never_archived(self):
        git = self.source / '.git'
        git.mkdir()
        (git / 'local-private-metadata').write_text('not a release file')
        content = self.archive_contents(self.package())
        self.assertFalse(any('.git/' in name for name in content))

    def test_missing_selected_platform_is_rejected(self):
        for name in list(self.manifest['files']):
            if name.startswith('Monado_Linux/'):
                del self.manifest['files'][name]
                (self.source / name).unlink()
        self.save_manifest()
        with self.assertRaises(release.ReleaseError):
            self.package()

    def test_guard_refusal_stops_before_output_creation(self):
        self.guard_mock.side_effect = release.ReleaseError('scanner refused candidate')
        with self.assertRaisesRegex(release.ReleaseError, 'scanner refused'):
            self.package()
        self.assertFalse((self.base / 'result').exists())

    def test_archive_corruption_is_rejected_before_final_filename(self):
        with mock.patch.object(release, '_write_archive', side_effect=lambda stage, target, *args: target.write_bytes(b'broken archive')):
            with self.assertRaises(release.ReleaseError):
                self.package()
        self.assertEqual(list((self.base / 'result').iterdir()), [])

    def test_source_mutation_during_packaging_is_rejected(self):
        write = release._write_archive

        def mutate(*args):
            write(*args)
            (self.source / 'README.md').write_text('changed after archive generation')

        with mock.patch.object(release, '_write_archive', side_effect=mutate):
            with self.assertRaises(release.ReleaseError):
                self.package()
        self.assertEqual(list((self.base / 'result').iterdir()), [])

    def test_real_publication_guard_accepts_both_source_kits(self):
        self.guard.stop()
        for platform in ('linux', 'windows'):
            with self.subTest(platform=platform):
                receipt = self.package(platform, output=platform)
                content = self.archive_contents(receipt, output=platform)
                self.assertTrue(receipt['archive_readback_verified'])
                self.assertEqual(json.loads(content[release.MANIFEST])['platform'], platform)

    def test_real_guard_rejects_authored_binary_magic_even_if_manifested(self):
        self.guard.stop()
        data = b'NSO0 AUTHORED REJECTION FIXTURE, NOT GAME DATA\n'
        name = 'Monado_Linux/runtime/example.c'
        (self.source / name).write_bytes(data)
        self.manifest['files'][name] = dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        self.save_manifest()
        with self.assertRaisesRegex(release.ReleaseError, 'publication guard rejected'):
            self.package()
        self.assertFalse((self.base / 'result').exists())


class SourceGuardImportIsolation(unittest.TestCase):
    """Real guard execution must stay paired with a dynamically loaded packager."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado guard import with spaces ')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / 'reviewed source'
        self.source.mkdir()
        files = {'README.md': b'# Authored source fixture\n',
            'LICENSE': b'Authored licence fixture\n',
            'publication-policy.json': b'{"schema":1,"licensed_media":{}}\n',
            'Monado_Linux/runtime/example.c': b'int authored_fixture(void) { return 1; }\n'}
        for name in ('tools/package_source_release.py', 'tools/publication_guard.py',
                'tools/build_launcher_appimage.py', 'tools/build_builder_appimage.py',
                'tools/builder_bootstrap.py', 'tools/portable_runtime.py',
                'Monado_Linux/scripts/install_layout.py'):
            files[name] = (ROOT / name).read_bytes()
        for name, data in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.save_manifest()
        spec = importlib.util.spec_from_file_location('_authored_local_source_packager',
            self.source / 'tools/package_source_release.py')
        self.packager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.packager)

    def save_manifest(self):
        files = {path.relative_to(self.source).as_posix():
            dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            for path in self.source.rglob('*') if path.is_file()
            and path.name != 'publication-manifest.json'}
        (self.source / 'publication-manifest.json').write_text(json.dumps(
            dict(schema=1, project='Monado II', files=files)))

    def test_dynamic_packager_uses_adjacent_real_guard_with_foreign_cached_refusal(self):
        foreign = types.ModuleType('publication_guard')
        foreign.verify_tree = mock.Mock(return_value=['foreign policy must not be used'])
        original_path = list(sys.path)
        with mock.patch.dict(sys.modules, {'publication_guard': foreign}):
            receipt = self.packager.package(self.source, 'linux', '0.1.28', self.base / 'package')
            self.assertIs(sys.modules['publication_guard'], foreign)
        foreign.verify_tree.assert_not_called()
        self.assertEqual(sys.path, original_path)
        self.assertTrue(receipt['archive_readback_verified'])

    def test_foreign_cached_acceptance_cannot_bypass_real_source_guard(self):
        target = self.source / 'Monado_Linux/runtime/example.c'
        target.write_bytes(b'NSO0 AUTHORED BINARY REJECTION FIXTURE\n')
        self.save_manifest()
        foreign = types.ModuleType('publication_guard')
        foreign.verify_tree = mock.Mock(return_value=[])
        with mock.patch.dict(sys.modules, {'publication_guard': foreign}):
            with self.assertRaisesRegex(self.packager.ReleaseError, 'publication guard rejected'):
                self.packager.package(self.source, 'linux', '0.1.28', self.base / 'package')
            self.assertIs(sys.modules['publication_guard'], foreign)
        foreign.verify_tree.assert_not_called()
        self.assertFalse((self.base / 'package').exists())

    def test_adjacent_guard_source_identity_is_still_checked(self):
        target = self.source / 'README.md'
        target.write_bytes(b'changed after reviewed manifest\n')
        with self.assertRaisesRegex(self.packager.ReleaseError, 'publication guard rejected'):
            self.packager.package(self.source, 'linux', '0.1.28', self.base / 'package')
        self.assertFalse((self.base / 'package').exists())

    def test_empty_oversized_and_nonregular_guard_helpers_are_not_executed(self):
        guard = self.source / 'tools/publication_guard.py'
        for data in (b'', b'# authored oversized helper\n' + b' ' * (8 * 1024 * 1024)):
            with self.subTest(bytes=len(data)):
                guard.write_bytes(data)
                with self.assertRaisesRegex(self.packager.ReleaseError, 'bounded single-link'):
                    self.packager._source_guard()
        guard.unlink(); guard.mkdir()
        with self.assertRaisesRegex(self.packager.ReleaseError, 'ordinary'):
            self.packager._source_guard()

    @unittest.skipUnless(hasattr(os, 'symlink'), 'filesystem symlinks unavailable')
    def test_linked_guard_helper_is_rejected_before_execution(self):
        guard = self.source / 'tools/publication_guard.py'
        original = self.base / 'guard.py'; guard.rename(original)
        try:
            guard.symlink_to(original)
        except OSError as error:
            self.skipTest('symlinks unavailable: ' + str(error))
        with self.assertRaisesRegex(self.packager.ReleaseError, 'link'):
            self.packager._source_guard()

    @unittest.skipUnless(hasattr(os, 'link'), 'filesystem hardlinks unavailable')
    def test_hardlinked_guard_helper_is_rejected_before_execution(self):
        guard = self.source / 'tools/publication_guard.py'
        try:
            os.link(guard, self.base / 'guard.py')
        except OSError as error:
            self.skipTest('hardlinks unavailable: ' + str(error))
        with self.assertRaisesRegex(self.packager.ReleaseError, 'single-link'):
            self.packager._source_guard()

    def test_guard_descriptor_ctime_change_still_rejects_unchanged_size_and_mtime(self):
        real_fstat = os.fstat
        calls = 0
        def descriptor(fd):
            nonlocal calls
            info = real_fstat(fd)
            calls += 1
            if calls == 2:
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
                fields['st_ctime_ns'] += 1
                return types.SimpleNamespace(**fields)
            return info
        with mock.patch.object(self.packager.os, 'fstat', side_effect=descriptor):
            with self.assertRaisesRegex(self.packager.ReleaseError, 'changed while reading'):
                self.packager._source_guard()
        self.assertEqual(calls, 2)

    def test_guard_accepts_stable_cross_api_windows_ctime_difference(self):
        real_fstat = os.fstat
        def descriptor(fd):
            info = real_fstat(fd)
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            fields['st_ctime_ns'] += 1000000000
            return types.SimpleNamespace(**fields)
        with mock.patch.object(self.packager.os, 'fstat', side_effect=descriptor):
            guard = self.packager._source_guard()
        self.assertEqual(guard.verify_tree(self.source), [])

    @unittest.skipUnless(sys.platform == 'linux', 'production Linux standalone packager imports fcntl')
    def test_isolated_python_actual_dynamic_builder_loader_keeps_deferred_guard_available(self):
        driver = self.base / 'isolated driver.py'
        driver.write_text('''import importlib.util, json, sys, types
from pathlib import Path
root, output, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
assert sys.flags.isolated and str(root / 'tools') not in sys.path
original_path = list(sys.path)
foreign = types.ModuleType('publication_guard')
def refuse(root):
    raise AssertionError('foreign cached publication guard executed')
foreign.verify_tree = refuse
if mode == 'foreign': sys.modules['publication_guard'] = foreign
spec = importlib.util.spec_from_file_location('_actual_appimage_loader', root / 'tools/build_launcher_appimage.py')
image = importlib.util.module_from_spec(spec); spec.loader.exec_module(image)
builder = image._load_authored_module(root, 'tools/build_builder_appimage.py', '_actual_deferred_builder')
assert sys.path == original_path
assert Path(builder.release.__file__).resolve() == root / 'tools/package_source_release.py'
receipt = builder.release.package(root, 'linux', '0.1.28', output)
assert receipt['archive_readback_verified'] and sys.path == original_path
assert (sys.modules.get('publication_guard') is foreign) if mode == 'foreign' else ('publication_guard' not in sys.modules)
print(json.dumps(dict(status='passed', mode=mode, archived_files=receipt['archived_files'])))
''')
        for mode in ('absent', 'foreign'):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, '-I', '-B', str(driver),
                    str(self.source), str(self.base / ('package-' + mode)), mode],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
