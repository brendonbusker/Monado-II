"""Authored source-kit packaging tests; scanner policy is covered separately."""
from pathlib import Path
import hashlib
import importlib
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
release = importlib.import_module('package_source_release')


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

    def test_workflow_selects_canonical_windows_asset_and_both_linux_names(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/source-release.yml').read_text()
        self.assertIn('archive_pattern: monado-ii-windows-original-implementation-setup.zip', workflow)
        self.assertIn('artifact_name: monado-ii-windows-original-implementation-setup', workflow)
        self.assertIn('archive_pattern: monado-ii-*-linux-*.tar.gz', workflow)
        self.assertIn('${{ matrix.archive_pattern }}', workflow)

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


if __name__ == '__main__':
    unittest.main()
