"""Actual optional FSR4 setup/preparation boundary and identity checks."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / 'Monado_Linux/scripts'
sys.path.insert(0, str(SCRIPTS))
import setup_linux_fsr4 as component
import setup_linux_fsr4_tools as tools
# The preparation provider uses Unix accounts, Proton, private POSIX modes and
# Linux mount/process ownership. Native Windows needs its own provider/fixtures.
if sys.platform == 'linux':
    import prepare_linux_fsr4 as prepare


class Fsr4SourceIdentity(unittest.TestCase):
    def test_source_lock_matches_actual_imported_files(self):
        lock = component.verify_source()
        self.assertEqual(lock['abi'], 2)
        self.assertGreater(len(lock['files']), 20)
        self.assertEqual(len(lock['dependencies']), 5)
        self.assertEqual(lock['sdk']['sha256'], 'aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace')


@unittest.skipUnless(sys.platform == 'linux', 'Linux FSR4 dependency and Proton preparation provider')
class Fsr4Preparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monado-fsr4-')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def archive(self, entries):
        path = self.root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz') as tf:
            for name, data, kind in entries:
                info = tarfile.TarInfo(name); info.type = kind
                if kind == tarfile.REGTYPE:
                    info.size = len(data); tf.addfile(info, io.BytesIO(data))
                else:
                    info.linkname = data.decode(); tf.addfile(info)
        return path

    def test_model_identity_survives_unrelated_native_docs_updates(self):
        lock=component.verify_source();changed=json.loads(json.dumps(lock))
        changed['files']['third_party/fsr4_native/README.md']['sha256']='updated documentation'
        changed['files']['third_party/fsr4_native/fsr411.cpp']['sha256']='updated native module'
        self.assertEqual(prepare.model_identity(lock),prepare.model_identity(changed))
        changed['files']['third_party/fsr4cap/extract.py']['sha256']='changed translation recipe'
        self.assertNotEqual(prepare.model_identity(lock),prepare.model_identity(changed))

    def test_no_display_fails_before_any_download_or_output(self):
        with mock.patch.object(prepare,'cache_sdk') as download:
            with self.assertRaisesRegex(ValueError,'X11/XWayland'):
                prepare.prepare(self.root/'new-output',self.root/'proton',display=None)
            download.assert_not_called()
        self.assertFalse((self.root/'new-output').exists())

    def test_cleanup_keeps_nested_mount_sentinel_and_removes_other_owned_data(self):
        work=self.root/'preparation/test';work.mkdir(parents=True)
        (work/'.monado-fsr4-owner.json').write_text(json.dumps({'output':'owned-output'}))
        (work/'logs').mkdir();(work/'logs/keep.log').write_text('keep')
        mounted=work/'cache/doc';mounted.mkdir(parents=True);(mounted/'keep.txt').write_text('outside mount sentinel')
        (work/'compat/pfx').mkdir(parents=True);(work/'compat/pfx/temp.txt').write_text('temporary')
        (work/'cache/shaders').mkdir();(work/'cache/shaders/temp.bin').write_bytes(b'temporary')
        with mock.patch.object(prepare,'BASE',self.root),mock.patch.object(prepare,'mounted_paths_below',return_value={mounted}):
            warnings=prepare.cleanup_work(work,'owned-output')
        self.assertTrue(warnings);self.assertEqual((mounted/'keep.txt').read_text(),'outside mount sentinel')
        self.assertFalse((work/'compat').exists());self.assertFalse((work/'cache/shaders').exists())
        self.assertEqual((work/'logs/keep.log').read_text(),'keep')

    def test_ordinary_boundary_rejects_symlinks_parent_escape_and_existing_output(self):
        target = self.root / 'owned'; target.mkdir()
        (self.root / 'alias').symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError): component.ordinary(self.root / 'alias/new', self.root)
        with self.assertRaises(ValueError): component.ordinary(self.root.parent / 'outside', self.root)
        with self.assertRaises(ValueError): component.ordinary(target, self.root, fresh=True)
        self.assertEqual(component.ordinary(target / 'new', self.root, fresh=True), target / 'new')

    def test_source_unpack_allows_only_bounded_regular_files(self):
        archive = self.archive([('repo/src/main.c', b'int a;\n', tarfile.REGTYPE)])
        with mock.patch.object(tools, 'BASE', self.root): tools.unpack(archive, self.root / 'out')
        self.assertEqual((self.root / 'out/src/main.c').read_bytes(), b'int a;\n')
        self.assertEqual((self.root / 'out/src/main.c').stat().st_mode & 0o777, 0o644)

    def test_source_unpack_rejects_traversal_duplicate_and_links(self):
        cases = [[('repo/../escape', b'x', tarfile.REGTYPE)],
                 [('repo/f', b'a', tarfile.REGTYPE), ('repo/f', b'b', tarfile.REGTYPE)],
                 [('repo/link', b'/etc', tarfile.SYMTYPE)],
                 [('repo/link', b'repo/a', tarfile.LNKTYPE)]]
        for i, entries in enumerate(cases):
            with self.subTest(i=i):
                archive = self.archive(entries)
                with mock.patch.object(tools, 'BASE', self.root), self.assertRaises(ValueError):
                    tools.unpack(archive, self.root / ('bad' + str(i)))
        self.assertFalse((self.root / 'escape').exists())

    def test_locked_class_bindings_patch_applies_exact_hunks_without_host_tools(self):
        source = b'intro\nold\ncontext\ntwo\nthree\nfour\nfive\ntail\n'
        delta = (b'diff --git a/dxil_spirv.cpp b/dxil_spirv.cpp\nindex fixture\n'
                 b'--- a/dxil_spirv.cpp\n+++ b/dxil_spirv.cpp\n'
                 b'@@ -2,2 +2,3 @@ first\n-old\n+new\n+added\n context\n'
                 b'@@ -4,1 +5,1 @@ second\n-two\n+2\n'
                 b'@@ -5,1 +6,1 @@ third\n-three\n+3\n'
                 b'@@ -6,1 +7,1 @@ fourth\n-four\n+4\n'
                 b'@@ -7,1 +8,1 @@ fifth\n-five\n+5\n')
        expected = b'intro\nnew\nadded\ncontext\n2\n3\n4\n5\ntail\n'
        with mock.patch.multiple(tools, DXIL_SOURCE_SHA256=hashlib.sha256(source).hexdigest(),
                                 DXIL_PATCHED_SHA256=hashlib.sha256(expected).hexdigest()):
            self.assertEqual(tools.class_bindings_source(source, delta), expected)
            with self.assertRaisesRegex(ValueError, 'source changed'):
                tools.class_bindings_source(source + b'unexpected file modification\n', delta)
            with self.assertRaisesRegex(ValueError, 'patch layout'):
                tools.class_bindings_source(source, delta.replace(b'+++ b/dxil_spirv.cpp', b'+++ b/other.cpp'))
            with self.assertRaisesRegex(ValueError, 'patch context changed'):
                tools.class_bindings_source(source, delta.replace(b'-old\n', b'-unexpected\n'))
            with self.assertRaisesRegex(ValueError, 'produced unexpected source'):
                tools.class_bindings_source(source, delta.replace(b'+added\n', b'+unexpected\n'))

    def test_offline_download_never_contacts_network(self):
        item = {'path': 'test', 'commit': '123', 'archive_sha256': '00'}
        with mock.patch.object(tools, 'BASE', self.root), mock.patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'offline'): tools.fetch(item, offline=True)
            network.assert_not_called()

    def test_bad_download_is_never_committed_to_cache(self):
        item = {'path': 'test', 'commit': '123', 'url': 'https://example.invalid/test',
                'archive_bytes': 3, 'archive_sha256': '00'}
        response = mock.MagicMock(); response.__enter__.return_value.read.return_value = b'bad'
        with mock.patch.object(tools, 'BASE', self.root), mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'): tools.fetch(item)
        self.assertEqual(list((self.root / 'downloads').iterdir()), [])

    def test_existing_bad_cache_is_not_silently_replaced(self):
        cache = self.root / 'downloads'; cache.mkdir()
        path = cache / 'test-123.tar.gz'; path.write_bytes(b'changed')
        with mock.patch.object(tools, 'BASE', self.root), mock.patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                tools.fetch({'path': 'test', 'commit': '123', 'archive_sha256': '00'})
            network.assert_not_called()
        self.assertEqual(path.read_bytes(), b'changed')

    def fake_proton(self, text=None):
        install = self.root / 'installed-proton'; install.mkdir()
        (install / 'files/share/default_pfx').mkdir(parents=True)
        path = install / 'proton'
        path.write_text(text or '''# read-only fixture
if __name__ == "__main__":
    g_proton.cleanup_legacy_dist()
    g_proton.do_steampipe_fixups()
    if g_proton.missing_default_prefix():
        g_proton.make_default_prefix()
''')
        return path

    def test_private_runner_disables_installed_maintenance_without_modifying_install(self):
        original = self.fake_proton(); before = original.read_bytes()
        work = self.root / 'work'; work.mkdir()
        path, receipt = prepare.private_proton(original, work)
        self.assertEqual(original.read_bytes(), before)
        self.assertNotIn('g_proton.cleanup_legacy_dist()', path.read_text())
        self.assertNotIn('g_proton.do_steampipe_fixups()', path.read_text())
        self.assertNotIn('g_proton.make_default_prefix()', path.read_text())
        self.assertIn('raise RuntimeError', path.read_text())
        self.assertEqual(receipt['installed_sha256'], component.digest(original))
        folders=list((work/'compat').rglob('Documents'))
        self.assertEqual(len(folders),1)
        self.assertTrue(folders[0].is_dir() and folders[0].is_relative_to(work))
        self.assertEqual(set(original.parent.iterdir()), {original.parent / 'files', original})

    def test_unknown_proton_script_refuses_execution(self):
        original = self.fake_proton('# incompatible script')
        work = self.root / 'work'; work.mkdir()
        with self.assertRaisesRegex(ValueError, 'unrecognized Proton'):
            prepare.private_proton(original, work)

    def test_private_environment_keeps_home_and_omits_display_and_human_steam(self):
        work = self.root / 'work'; work.mkdir()
        home = self.root / 'account-home';home.mkdir()
        with mock.patch.dict(os.environ, {'HOME':str(home)}, clear=True),mock.patch.object(prepare.pwd,'getpwuid') as lookup:
            env = prepare.environment(work, self.root / 'installed/proton')
            self.assertEqual(env['HOME'], str(home));lookup.assert_not_called()
        self.assertNotIn('DISPLAY', env); self.assertNotIn('WAYLAND_DISPLAY', env)
        for key in ('STEAM_COMPAT_DATA_PATH', 'STEAM_COMPAT_CLIENT_INSTALL_PATH', 'PROTON_LOG_DIR',
                    'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'MESA_SHADER_CACHE_DIR', 'TMPDIR'):
            self.assertTrue(Path(env[key]).is_relative_to(work), key)

    def test_private_environment_without_home_uses_actual_account_lookup(self):
        work=self.root/'work';work.mkdir();home=self.root/'account-home';home.mkdir()
        account=mock.Mock(pw_dir=str(home))
        with mock.patch.dict(os.environ,{},clear=True),mock.patch.object(prepare.pwd,'getpwuid',return_value=account) as lookup:
            env=prepare.environment(work,self.root/'installed/proton')
            self.assertEqual(env['HOME'],str(home));self.assertNotIn('HOME',os.environ)
            lookup.assert_called_once_with(os.getuid())
        self.assertNotEqual(env['HOME'],str(work));self.assertFalse((home/'.steam').exists())

    def test_invalid_home_uses_actual_account_and_missing_account_is_actionable(self):
        home=self.root/'account-home';home.mkdir()
        with mock.patch.dict(os.environ,{'HOME':'relative-home'},clear=True),mock.patch.object(prepare.pwd,'getpwuid',return_value=mock.Mock(pw_dir=str(home))):
            self.assertEqual(prepare.user_home(),str(home))
        work=self.root/'work';work.mkdir()
        with mock.patch.dict(os.environ,{},clear=True),mock.patch.object(prepare.pwd,'getpwuid',side_effect=KeyError('no Unix account')):
            with self.assertRaisesRegex(ValueError,'desktop session with HOME set'):
                prepare.environment(work,self.root/'installed/proton')
        self.assertEqual(list(work.iterdir()),[])

    def test_missing_model_marker_is_an_error(self):
        with mock.patch.object(prepare, 'BASE', self.root), mock.patch.object(component, 'verify_source'):
            with self.assertRaises(FileNotFoundError): prepare.verify_assets()

    def test_changed_model_receipt_is_rejected_before_file_access(self):
        assets = self.root / 'assets/test'; assets.mkdir(parents=True)
        receipt = assets / 'receipt.json'; receipt.write_text('{}')
        (self.root / 'active-assets.json').write_text(json.dumps({'schema': 1,
            'receipt_path': str(receipt), 'receipt_sha256': 'changed'}))
        with mock.patch.object(prepare, 'BASE', self.root), mock.patch.object(component, 'verify_source'):
            with self.assertRaisesRegex(ValueError, 'receipt changed'): prepare.verify_assets()


if __name__ == '__main__': unittest.main()
