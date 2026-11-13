"""[XCDE] LINUX-088: real source-kit to builder-template migration, no compilation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile

if sys.platform != 'linux':
    raise unittest.SkipTest('standalone AppImage migration is Linux-only')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_builder_appimage as builder
import package_source_release as release

spec = importlib.util.spec_from_file_location('monado_template_migration_image', ROOT / 'tools/build_launcher_appimage.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


def identity(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class StandaloneTemplateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monado-template-migration-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / 'reviewed source'
        self.source.mkdir()
        self.files = {
            'README.md': b'# Authored migration fixture\n',
            'LICENSE': b'Authored license fixture\n',
            'publication-policy.json': image.encoded(dict(schema=1, licensed_media={})),
            'update-version.json': image.encoded(dict(schema=1, protocol=1, version='0.1.17')),
            'Monado_Linux/runtime/fixture.c': b'int authored_fixture(void) { return 1; }\n',
            'Monado_Windows/runtime/fixture.c': b'int authored_original(void) { return 2; }\n',
        }
        # Exercise the actual installed-source verifier, including its imports.
        for name in ('update_linux.py', 'update_release.py', 'installation_version.py', 'publication_guard.py'):
            self.files['tools/' + name] = (ROOT / 'tools' / name).read_bytes()
        for name, data in self.files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.manifest = dict(schema=1, project='Monado II', source_only=True,
            files={name: identity(data) for name, data in self.files.items()})
        self.write_manifest(self.source, self.manifest)

    def write_manifest(self, root, document):
        (root / release.MANIFEST).write_bytes(image.encoded(document))

    def kit(self, platform='linux'):
        output = self.base / ('original-' + platform)
        receipt = release.package(self.source, platform, '0.1.17', output)
        archive = output / receipt['archive']
        workspace = self.base / ('installed ' + platform + ' kit')
        workspace.mkdir()
        if platform == 'linux':
            with tarfile.open(archive, 'r:gz') as stream:
                members = {item.name.split('/', 1)[1]: stream.extractfile(item).read()
                           for item in stream.getmembers()}
        else:
            with zipfile.ZipFile(archive) as stream:
                members = {name.split('/', 1)[1]: stream.read(name) for name in stream.namelist()}
        for name, data in members.items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return workspace

    def rewrite(self, workspace, name, data=None):
        document = json.loads((workspace / release.MANIFEST).read_bytes())
        path = workspace / name
        if data is None:
            path.unlink()
            del document['files'][name]
        else:
            path.write_bytes(data)
            document['files'][name] = identity(data)
        self.write_manifest(workspace, document)

    def export(self, workspace):
        files = image.reviewed_source_files(workspace)
        target = self.base / 'clean temporary export'
        target.mkdir()
        for name, (data, mode) in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        return target, files

    def test_real_source_kit_repackages_as_builder_template(self):
        workspace = self.kit()
        sentinels = {
            workspace / 'Monado_Linux/play/launcher/save/owned.txt': b'keep authored save fixture',
            workspace / 'Monado_Linux/.deps/private.txt': b'keep authored dependency fixture',
            workspace / 'game_files/romfs/owned.txt': b'keep authored input fixture',
        }
        for path, data in sentinels.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        document = json.loads((workspace / release.MANIFEST).read_bytes())
        protected = {workspace / name: (workspace / name).read_bytes()
                     for name in [*document['files'], release.MANIFEST]}
        protected.update(sentinels)
        exported, files = self.export(workspace)
        output = self.base / 'builder package'
        output.mkdir()
        # No downstream mock: this is the real template/release/guard pipeline.
        archive, receipt = builder.authored_template(exported, output)
        self.assertTrue(receipt['archive_readback_verified'])
        self.assertTrue(archive.is_file())
        self.assertNotIn('RELEASE_README.md', files)
        self.assertNotIn('source-only-status.json', files)
        normalized = json.loads(files[release.MANIFEST][0])
        for name in ('platform', 'release_kind', 'release_version'):
            self.assertNotIn(name, normalized)
        self.assertFalse(any(name.startswith('Monado_Windows/') for name in files))
        with tarfile.open(archive, 'r:gz') as stream:
            names = {item.name.split('/', 1)[1] for item in stream.getmembers()}
            self.assertEqual(names, set(files) | {'RELEASE_README.md', 'source-only-status.json'})
        self.assertEqual({path: path.read_bytes() for path in protected}, protected)

    def test_clean_publication_export_is_unchanged_and_repackages(self):
        original = (self.source / release.MANIFEST).read_bytes()
        exported, files = self.export(self.source)
        self.assertEqual(files[release.MANIFEST][0], original)
        self.assertEqual({name: data for name, (data, mode) in files.items() if name != release.MANIFEST}, self.files)
        output = self.base / 'clean builder package'
        output.mkdir()
        archive, receipt = builder.authored_template(exported, output)
        self.assertTrue(archive.is_file())
        self.assertTrue(receipt['archive_readback_verified'])
        self.assertEqual((self.source / release.MANIFEST).read_bytes(), original)

    def test_changed_metadata_or_authored_source_rejected_before_export(self):
        workspace = self.kit()
        for name in ('README.md', 'RELEASE_README.md', 'source-only-status.json'):
            with self.subTest(name=name):
                path = workspace / name
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'Local source changes'):
                    image.reviewed_source_files(workspace)
                path.write_bytes(original)

    def test_partial_or_missing_distribution_markers_rejected(self):
        workspace = self.kit()
        for name in ('RELEASE_README.md', 'source-only-status.json'):
            with self.subTest(name=name):
                raw = (workspace / release.MANIFEST).read_bytes()
                data = (workspace / name).read_bytes()
                self.rewrite(workspace, name)
                with self.assertRaisesRegex(ValueError, 'source-kit'):
                    image.reviewed_source_files(workspace)
                (workspace / name).write_bytes(data)
                (workspace / release.MANIFEST).write_bytes(raw)
        self.rewrite(workspace, 'RELEASE_README.md')
        self.rewrite(workspace, 'source-only-status.json')
        with self.assertRaisesRegex(ValueError, 'source-kit'):
            image.reviewed_source_files(workspace)

    def test_manifest_bound_malformed_metadata_rejected(self):
        workspace = self.kit()
        original_manifest = (workspace / release.MANIFEST).read_bytes()
        original_status = (workspace / 'source-only-status.json').read_bytes()
        original_readme = (workspace / 'RELEASE_README.md').read_bytes()
        status = json.loads(original_status)
        cases = [
            ('source-only-status.json', image.encoded(dict(status, platform='windows'))),
            ('source-only-status.json', image.encoded(dict(status, version='0.1.16'))),
            ('source-only-status.json', image.encoded(dict(status, contains_game_files=True))),
            ('source-only-status.json', image.encoded(dict(status, contains_compiled_binaries=0))),
            ('source-only-status.json', image.encoded(dict(status, unreviewed='extra field'))),
            ('RELEASE_README.md', original_readme.replace(b'0.1.17', b'0.1.16')),
            ('RELEASE_README.md', original_readme + b'Unreviewed generated metadata\n'),
            ('update-version.json', image.encoded(dict(schema=1, protocol=1, version='0.1.16'))),
        ]
        for name, data in cases:
            with self.subTest(name=name, data=data[:80]):
                original = (workspace / name).read_bytes()
                self.rewrite(workspace, name, data)
                with self.assertRaisesRegex(ValueError, 'source-kit'):
                    image.reviewed_source_files(workspace)
                (workspace / name).write_bytes(original)
                (workspace / release.MANIFEST).write_bytes(original_manifest)
        self.assertEqual((workspace / 'source-only-status.json').read_bytes(), original_status)

    def test_wrong_or_partial_manifest_provenance_rejected(self):
        workspace = self.kit()
        document = json.loads((workspace / release.MANIFEST).read_bytes())
        for name, value in (('platform', 'windows'), ('release_version', '0.1.16'),
                            ('release_kind', 'binary'), ('windows_implementation', 'original'),
                            ('source_release_version', '0.1.17'), ('linux_feature_additions', False),
                            ('release_kind', None)):
            with self.subTest(name=name, value=value):
                changed = dict(document)
                if value is None:
                    changed.pop(name)
                else:
                    changed[name] = value
                self.write_manifest(workspace, changed)
                with self.assertRaisesRegex(ValueError, 'source-kit'):
                    image.reviewed_source_files(workspace)
        self.write_manifest(workspace, document)

    def test_actual_windows_kit_is_not_a_linux_builder_template(self):
        workspace = self.kit('windows')
        with self.assertRaisesRegex(ValueError, 'source-kit'):
            image.reviewed_source_files(workspace)

    def test_release_packager_still_rejects_unnormalized_distribution(self):
        workspace = self.kit()
        with self.assertRaisesRegex(release.ReleaseError, 'generated release-only files'):
            release.package(workspace, 'linux', '0.1.17', self.base / 'must not package')


if __name__ == '__main__':
    unittest.main()
