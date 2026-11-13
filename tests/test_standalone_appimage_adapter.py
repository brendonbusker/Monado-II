"""[XCDE] LINUX-081: source-updater bridge fixtures; no game/build execution."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_standalone_adapter_tested', ROOT / 'tools/build_launcher_appimage.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


def elf(runtime=False):
    data = bytearray(128)
    data[:6] = b'\x7fELF\x02\x01'; data[18:20] = (62).to_bytes(2, 'little')
    if runtime:
        data[8:11] = b'AI\x02'
    return bytes(data)


@unittest.skipUnless(sys.platform == 'linux', 'Linux standalone updater adapter')
class StandaloneAdapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monado-standalone-adapter-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'workspace with spaces'
        self.port = self.root / 'Monado_Linux'
        self.launcher = self.port / 'build/authored-gui/monado-launcher'
        self.game = self.port / 'build/authored-game/xcde-linux'
        for path, data in ((self.launcher, elf()), (self.game, b'PRIVATE authored game placeholder never bundled')):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); path.chmod(0o755)
        self.output = self.port / 'build/authored-image/Monado-II-x86_64.AppImage'
        self.files = {'README.md': b'Authored source fixture\n', 'update-version.json': b'{"version":"fixture"}\n',
                      'tools/build_builder_appimage.py': b'# Authored packager placeholder; never compiled\n',
                      'publication-policy.json': b'{"schema":1,"licensed_media":{}}\n'}
        for name, data in self.files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.manifest = dict(schema=1, project='Monado II', source_only=True,
            files={name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in self.files.items()})
        (self.root / 'publication-manifest.json').write_bytes(image.encoded(self.manifest))
        (self.port / '.deps/private-sdk').mkdir(parents=True)
        (self.port / '.deps/private-sdk/keep.txt').write_text('never bundle this unrelated local dependency')
        self.selection = dict(launcher_sha256=image.digest(elf()), game_sha256='a' * 64)
        self.calls = []
        self.events = []
        self.runtime = self.port / '.deps/appimage' / ('runtime-x86_64-' + image.RUNTIME_SHA)
        self.core = SimpleNamespace(installed_sources=lambda root: self.manifest,
                                    _original_metadata=lambda root, manifest: self.files['update-version.json'])
        self.fake_packager = SimpleNamespace(package=self.package_fixture)

    def module(self, root, relative, name):
        return self.core if relative == 'tools/update_linux.py' else self.fake_packager

    def package_fixture(self, root, dependency_port, output, image_path, **kwargs):
        self.events.append('package')
        self.assertEqual(self.runtime.read_bytes(), elf(runtime=True))
        self.calls.append(dict(source=root, dependency=dependency_port, output=output, image=image_path,
                               files={p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}, **kwargs))
        output.mkdir()
        image_path.write_bytes(elf(runtime=True)); image_path.chmod(0o755)
        receipt = dict(schema=1, project='Monado II', status='passed', artifact_kind='standalone-builder-appimage',
                       output=str(image_path), sha256=image.digest(image_path.read_bytes()), bytes=image_path.stat().st_size,
                       archive_readback_verified=True, requires_adjacent_workspace=False,
                       contains_game_files=False, contains_game_executable=False,
                       contains_generated_game_code=False, contains_vendor_sdk=False,
                       appdir_files={'authored': {'sha256': 'b' * 64, 'bytes': 1}})
        image_path.with_name(image_path.name + '.receipt.json').write_bytes(image.encoded(receipt))
        return receipt

    def runtime_fixture(self, port):
        self.events.append('runtime')
        self.assertEqual(port, self.port)
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.write_bytes(elf(runtime=True))
        return elf(runtime=True)

    def package(self):
        with mock.patch.object(image, 'verified_selection', return_value=self.selection), mock.patch.object(image, '_load_authored_module', side_effect=self.module), mock.patch.object(image, 'runtime_bytes', side_effect=self.runtime_fixture):
            return image.standalone_package(self.launcher, self.game, self.output, root=self.root)

    def test_first_package_acquires_pinned_runtime_before_standalone_packager(self):
        self.assertFalse(self.runtime.exists())
        self.package()
        self.assertEqual(self.events, ['runtime', 'package'])
        self.assertEqual(self.runtime.read_bytes(), elf(runtime=True))

    def test_runtime_acquisition_failure_preserves_native_files_without_packaging(self):
        protected = {p: p.read_bytes() for p in (self.game, self.launcher, self.root / 'publication-manifest.json')}
        with mock.patch.object(image, 'verified_selection', return_value=self.selection), mock.patch.object(image, '_load_authored_module', side_effect=self.module), mock.patch.object(image, 'runtime_bytes', side_effect=image.AppImageError('pinned runtime acquisition failed')) as runtime:
            with self.assertRaisesRegex(image.AppImageError, 'pinned runtime acquisition failed'):
                image.standalone_package(self.launcher, self.game, self.output, root=self.root)
        runtime.assert_called_once_with(self.port)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.name + '.receipt.json').exists())
        self.assertFalse((self.output.parent / 'standalone-package').exists())
        self.assertEqual({p: p.read_bytes() for p in protected}, protected)

    def test_exact_authored_export_omits_game_sdk_profile_and_build_bytes(self):
        receipt = self.package()
        call = self.calls[0]
        self.assertEqual(set(call['files']), set(self.files) | {'publication-manifest.json'})
        self.assertEqual(call['dependency'], self.port)
        self.assertFalse(call['source'].exists())
        self.assertNotIn(self.game.read_bytes(), call['files'].values())
        self.assertFalse(any('.deps' in p or '/build/' in p or 'game_files' in p for p in call['files']))
        self.assertEqual(receipt['artifact_kind'], 'local-launcher-appimage')
        self.assertEqual(receipt['standalone_artifact_kind'], 'standalone-builder-appimage')
        self.assertFalse(receipt['requires_adjacent_workspace'])
        self.assertEqual(receipt['launcher'], 'Monado_Linux/build/authored-gui/monado-launcher')
        self.assertEqual(receipt['game_port'], 'current')
        self.assertEqual(json.loads(Path(str(self.output) + '.receipt.json').read_bytes()), receipt)
        self.assertEqual(call['legacy_selection']['launcher_sha256'], self.selection['launcher_sha256'])

    def test_bound_game_uses_existing_installation_selection_contract(self):
        payload = self.base / 'owned payload/Monado_Linux'
        game = payload / 'build/authored-game/xcde-linux'
        game.parent.mkdir(parents=True); game.write_bytes(b'private authored payload')
        self.game = game
        with mock.patch.object(image.install_layout, 'build_port', return_value=payload):
            receipt = self.package()
        self.assertEqual(receipt['game_port'], 'bound')
        self.assertEqual(self.calls[0]['legacy_selection']['game'], 'Monado_Linux/build/authored-game/xcde-linux')

    def test_export_rejects_changed_source_before_packager(self):
        (self.root / 'README.md').write_bytes(b'modified authored fixture')
        with self.assertRaisesRegex(image.AppImageError, 'Source changed'):
            self.package()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_visible_installed_version_restores_only_verified_original_bytes(self):
        (self.root / 'update-version.json').write_bytes(b'{"version":"newer-visible-marker"}\n')
        self.package()
        self.assertEqual(self.calls[0]['files']['update-version.json'], self.files['update-version.json'])
        self.assertIn(b'newer-visible-marker', (self.root / 'update-version.json').read_bytes())

    def test_existing_outputs_are_never_overwritten(self):
        for relative in ('Monado-II-x86_64.AppImage', 'Monado-II-x86_64.AppImage.receipt.json', 'standalone-package'):
            with self.subTest(relative=relative):
                self.output.parent.mkdir(parents=True, exist_ok=True)
                path = self.output.parent / relative
                path.write_bytes(b'keep original')
                with self.assertRaisesRegex(image.AppImageError, 'refusing to replace'):
                    self.package()
                self.assertEqual(path.read_bytes(), b'keep original')
                path.unlink()

    def test_bad_standalone_receipt_never_adapts_to_legacy_success(self):
        operation = self.package_fixture
        def bad(*args, **kwargs):
            result = operation(*args, **kwargs)
            result['contains_game_files'] = True
            args[3].with_name(args[3].name + '.receipt.json').write_bytes(image.encoded(result))
            return result
        self.fake_packager.package = bad
        with self.assertRaisesRegex(image.AppImageError, 'receipt contract'):
            self.package()
        self.assertEqual(json.loads(Path(str(self.output) + '.receipt.json').read_bytes())['artifact_kind'], 'standalone-builder-appimage')

    def test_host_source_cli_flag_retains_existing_thin_package(self):
        result = dict(status='passed', output='authored', bytes=128, sha256='a' * 64, archive_readback_verified=True)
        args = ['--launcher-executable', str(self.launcher), '--game-executable', str(self.game), '--output', str(self.output), '--standalone']
        with mock.patch.object(image, 'standalone_build_environment', return_value=False), mock.patch.object(image, 'package', return_value=result) as thin, mock.patch.object(image, 'standalone_package') as full, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(image.main(args), 0)
        thin.assert_called_once_with(self.launcher, self.game, self.output, standalone_migration='retained-workspace-bootstrap'); full.assert_not_called()

    def test_malformed_private_marker_fails_instead_of_switching_modes(self):
        args = ['--launcher-executable', str(self.launcher), '--game-executable', str(self.game), '--output', str(self.output), '--standalone']
        with mock.patch.object(image, 'standalone_build_environment', side_effect=ValueError('Invalid standalone build interpreter identity')), mock.patch.object(image, 'package') as thin, mock.patch.object(image, 'standalone_package') as full, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                image.main(args)
        self.assertEqual(raised.exception.code, 1)
        thin.assert_not_called(); full.assert_not_called()

    def test_private_packaging_failure_never_falls_back_to_thin(self):
        args = ['--launcher-executable', str(self.launcher), '--game-executable', str(self.game), '--output', str(self.output), '--standalone']
        with mock.patch.object(image, 'standalone_build_environment', return_value=True), mock.patch.object(image, 'package') as thin, mock.patch.object(image, 'standalone_package', side_effect=ValueError('authored package failure')), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                image.main(args)
        thin.assert_not_called()

    def test_gate_uses_existing_checked_persistent_interpreter_identity(self):
        core = SimpleNamespace(private_build_python=mock.Mock(return_value=Path('/authored/private/bin/python3.14')))
        with mock.patch.object(image, '_load_authored_module', return_value=core):
            self.assertTrue(image.standalone_build_environment(self.root))
            core.private_build_python.return_value = None
            self.assertFalse(image.standalone_build_environment(self.root))
            core.private_build_python.side_effect = ValueError('malformed private runtime')
            with self.assertRaisesRegex(ValueError, 'malformed private runtime'):
                image.standalone_build_environment(self.root)

    def test_cli_default_retains_thin_package_and_flag_selects_standalone(self):
        result = dict(status='passed', output='authored', bytes=128, sha256='a' * 64, archive_readback_verified=True)
        args = ['--launcher-executable', str(self.launcher), '--game-executable', str(self.game), '--output', str(self.output)]
        for standalone in (False, True):
            with mock.patch.object(image, 'package', return_value=result) as thin, mock.patch.object(image, 'standalone_package', return_value=result) as new, mock.patch.object(image, 'standalone_build_environment', return_value=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(image.main(args + (['--standalone'] if standalone else [])), 0)
            self.assertEqual(new.call_count, int(standalone))
            self.assertEqual(thin.call_count, int(not standalone))


if __name__ == '__main__':
    unittest.main()
