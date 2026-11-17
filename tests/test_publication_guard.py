"""Authored scanner fixtures only; no game input, credentials or runtime data."""
from pathlib import Path
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import stat
import struct
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
guard = importlib.import_module('publication_guard')
ROOT = Path(__file__).resolve().parents[1]


def authored_rgb_png():
    """A real one-pixel PNG created from authored bytes, never game data."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data)))
    header = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
            chunk(b'IDAT', zlib.compress(b'\x00\x11\x22\x33')) + chunk(b'IEND', b''))


class PublicationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='monado-publication-guard-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'source'
        self.root.mkdir()
        self.files = {
            'README.md': b'# Monado II\nAuthored fixture only.\n',
            'Monado_Linux/runtime/example.c': b'int example(void) { return 1; }\n',
        }
        self.policy = dict(schema=1, licensed_media={})
        self.manifest = dict(schema=1, project='Monado II', files={})
        self.refresh()

    def refresh(self):
        self.files[guard.POLICY] = (json.dumps(self.policy, indent=2) + '\n').encode()
        for name, content in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.manifest['files'] = {name: dict(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
                                  for name, content in self.files.items()}
        self.save_manifest()

    def save_manifest(self):
        (self.root / guard.MANIFEST).write_text(json.dumps(self.manifest, indent=2) + '\n')

    def reject_content(self, content, name='Monado_Linux/runtime/example.c'):
        self.files[name] = content
        self.refresh()
        result = guard.verify_tree(self.root)
        self.assertTrue(result)
        return result

    @unittest.skipUnless(os.name == 'posix' and shutil.which('git'), 'POSIX symlink and Git required')
    def test_shared_input_link_and_directory_are_ignored_before_staging(self):
        # [XCDE] LINUX-029: a trailing-slash ignore misses the shared input link.
        checkout = self.base / 'ignore-checkout'
        checkout.mkdir()
        (checkout / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
        (checkout / 'README.md').write_text('Authored ignore fixture only.\n')
        outside = self.base / 'authored-input'
        outside.mkdir()
        (outside / 'fixture.txt').write_text('Authored synthetic bytes.\n')
        environment = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        def git(*args):
            return subprocess.run(['git', '-C', str(checkout), *args], env=environment,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(git('init', '-q').returncode, 0)
        shared = checkout / 'game_files'
        shared.symlink_to(outside, target_is_directory=True)
        self.assertEqual(git('check-ignore', '--no-index', 'game_files').returncode, 0)
        self.assertEqual(git('add', '--all').returncode, 0)
        self.assertNotIn('game_files', git('ls-files').stdout)
        shared.unlink()
        shared.mkdir()
        (shared / 'fixture.txt').write_text('Authored ordinary-directory fixture.\n')
        self.assertEqual(git('add', '--all').returncode, 0)
        self.assertNotIn('game_files', git('ls-files').stdout)
        self.assertEqual(git('check-ignore', '--no-index', 'README.md').returncode, 1)

    def test_clean_authored_source_passes(self):
        self.assertEqual(guard.verify_tree(self.root), [])

    def test_platform_trimmed_manifest_and_unused_licensed_font_policy_pass(self):
        self.policy['licensed_media']['Monado_Windows/fonts/reviewed.ttf'] = '0' * 64
        self.manifest['platform'] = 'linux'
        self.refresh()
        self.assertEqual(guard.verify_tree(self.root), [])

    def test_manifest_schema_and_project_are_strict(self):
        for field, value in (('schema', True), ('schema', 2), ('project', 'Wrong project'), ('files', [])):
            with self.subTest(field=field, value=value):
                original = self.manifest[field]
                self.manifest[field] = value
                self.save_manifest()
                self.assertTrue(guard.verify_tree(self.root))
                self.manifest[field] = original

    def test_platform_must_be_known(self):
        self.manifest['platform'] = 'unknown'
        self.save_manifest()
        self.assertTrue(guard.verify_tree(self.root))

    def test_manifest_and_policy_require_json_objects(self):
        for name in (guard.MANIFEST, guard.POLICY):
            for value in ('[]', 'null', '1', 'true'):
                with self.subTest(name=name, value=value):
                    self.refresh()
                    (self.root / name).write_text(value)
                    self.assertTrue(guard.verify_tree(self.root))

    def test_duplicate_json_keys_and_nonfinite_constants_are_rejected(self):
        for name in (guard.MANIFEST, guard.POLICY):
            for raw in ('{"schema":1,"schema":1}', '{"schema":1,"value":NaN}',
                        '{"schema":1,"value":Infinity}'):
                with self.subTest(name=name, raw=raw):
                    self.refresh()
                    (self.root / name).write_text(raw)
                    self.assertTrue(guard.verify_tree(self.root))

    def test_manifest_file_metadata_is_strict(self):
        for metadata in ({}, {'sha256': '0' * 64, 'bytes': True},
                         {'sha256': 'not a hash', 'bytes': 0},
                         {'sha256': '0' * 64, 'bytes': -1},
                         {'sha256': '0' * 64, 'bytes': guard.MAX_FILE + 1}):
            with self.subTest(metadata=metadata):
                self.manifest['files']['README.md'] = metadata
                self.save_manifest()
                self.assertTrue(guard.verify_tree(self.root))

    def test_extra_changed_and_missing_files_are_rejected(self):
        (self.root / 'unreviewed.txt').write_text('outside manifest')
        self.assertTrue(guard.verify_tree(self.root))
        (self.root / 'unreviewed.txt').unlink()
        (self.root / 'README.md').write_text('modified')
        self.assertTrue(guard.verify_tree(self.root))
        (self.root / 'README.md').unlink()
        self.assertTrue(guard.verify_tree(self.root))

    def test_manifest_cannot_hash_itself(self):
        self.manifest['files'][guard.MANIFEST] = dict(sha256='0' * 64, bytes=0)
        self.save_manifest()
        self.assertTrue(guard.verify_tree(self.root))

    def test_policy_must_itself_be_manifested(self):
        del self.manifest['files'][guard.POLICY]
        self.save_manifest()
        self.assertTrue(guard.verify_tree(self.root))

    def test_unsafe_paths_are_rejected_without_outside_reads(self):
        names = ('../outside', '/absolute', 'a\\b', 'a//b', 'a/./b', 'a/../b',
                 '.git/config', 'game_files/note.txt', 'Monado_Linux/build/note.txt',
                 'ROMFS/note.txt', 'source/save_1/note.txt', 'sdk/include/a.h',
                 'a:drive', 'a/CON', 'a/foo.', 'trailing ', 'a\x01b')
        for name in names:
            with self.subTest(name=name):
                self.manifest['files'][name] = dict(sha256='0' * 64, bytes=0)
                self.save_manifest()
                with mock.patch.object(guard, 'read_regular', wraps=guard.read_regular) as reader:
                    self.assertTrue(guard.verify_tree(self.root))
                self.assertTrue(all(Path(call.args[0]).is_relative_to(self.root) for call in reader.call_args_list))
                del self.manifest['files'][name]

    def test_case_colliding_paths_are_rejected(self):
        self.manifest['files']['readme.MD'] = self.manifest['files']['README.md']
        self.save_manifest()
        self.assertTrue(guard.verify_tree(self.root))

    def test_forbidden_empty_directory_is_rejected(self):
        (self.root / 'game_files').mkdir()
        self.assertTrue(guard.verify_tree(self.root))

    def test_legacy_distribution_script_and_images_are_rejected(self):
        for name in ('Monado_Linux/scripts/make_dist.sh', 'artwork.png', 'artwork.svg', 'icon.ico'):
            with self.subTest(name=name):
                self.assertIsNotNone(guard.path_problem(name))

    def test_local_appimage_payloads_cannot_enter_reviewed_source(self):
        for name in ('Monado-II.AppImage', 'other.APPIMAGE', 'payload.squashfs',
                     'Launcher.AppDir/usr/bin/gui', 'nested/thing.appdir/README.md'):
            with self.subTest(name=name):
                self.assertIsNotNone(guard.path_problem(name))
        empty = self.root / 'Launcher.AppDir'
        empty.mkdir()
        self.assertTrue(guard.verify_tree(self.root))

    def test_program_container_and_shader_magic_are_rejected_when_renamed(self):
        examples = (b'NSO' + b'0 AUTHORED MAGIC FIXTURE', b'\x7fELF' + b'fixture',
                    b'M' + b'Z fixture', b'XC' + b'VC fixture', bytes((3, 2, 35, 7)) + b'fixture')
        for data in examples:
            with self.subTest(data=data[:4]):
                self.assertIsNotNone(guard.content_problem('ordinary.txt', data))

    def test_unknown_binary_non_utf8_and_control_bytes_are_rejected(self):
        for data in (b'fixture\xff\xfe', b'fixture\x00tail', b'fixture\x01tail', b'fixture\x7ftail'):
            with self.subTest(data=data):
                self.assertIsNotNone(guard.content_problem('ordinary.txt', data))
        self.assertIsNone(guard.content_problem('ordinary.txt', 'UTF-8 text: café\tline\r\n'.encode()))

    def test_key_and_credential_signatures_are_rejected(self):
        examples = (b'master_' + b'key_00 = ' + b'0' * 32,
                    b'gh' + b'p_' + b'a' * 36,
                    b'github_' + b'pat_' + b'a' * 60,
                    b'-----BE' + b'GIN PRIVATE KEY-----',
                    b'AK' + b'IA' + b'A' * 16,
                    b'sk-' + b'proj-' + b'a' * 40)
        for data in examples:
            with self.subTest(prefix=data[:8]):
                self.assertIsNotNone(guard.content_problem('ordinary.txt', data))

    def test_generated_function_signature_is_rejected(self):
        data = b'void ' + b'f_' + b'7000123456' + b'(Cpu *c) { }\n'
        self.assertIsNotNone(guard.content_problem('ordinary.c', data))

    def test_authored_extern_and_prototype_declarations_are_allowed(self):
        signature = b'void ' + b'f_' + b'7000123456' + b'(Cpu *c)'
        self.assertIsNone(guard.content_problem('patches.py', b'extern ' + signature + b';\n'))
        self.assertIsNone(guard.content_problem('ordinary.txt', signature + b';\n'))
        self.assertIsNotNone(guard.content_problem('renamed.txt', signature + b'\n{\n}\n'))

    def test_excluded_font_decoder_constant_is_rejected(self):
        data = b'const int ' + b'KEY' + b' = 0x' + b'12345678;\n'
        self.assertIsNotNone(guard.content_problem('Monado_Linux/runtime/hle/pl.c', data))

    def test_personal_home_paths_including_escaped_windows_are_rejected(self):
        examples = (b'/ho' + b'me/' + b'fixture-owner/.config/private',
                    b'/Us' + b'ers/' + b'fixture-owner/file',
                    b'C:' + b'\\Users\\' + b'fixture-owner\\private',
                    b'C:' + b'\\\\Users\\\\' + b'fixture-owner\\\\private')
        for data in examples:
            with self.subTest(data=data[:4]):
                self.assertIsNotNone(guard.content_problem('ordinary.txt', data))

    def test_manifest_metadata_is_scanned_for_personal_data(self):
        self.manifest['unreviewed_note'] = ('/ho' + 'me/' + 'fixture-owner/private')
        self.save_manifest()
        self.assertTrue(guard.verify_tree(self.root))

    def test_licensed_font_requires_exact_policy_identity(self):
        name = 'Monado_Linux/fonts/reviewed.ttf'
        data = bytes((0, 1, 0, 0)) + b'AUTHORED HEADER FIXTURE, NO REAL FONT DATA'
        self.files[name] = data
        self.policy['licensed_media'][name] = hashlib.sha256(data).hexdigest()
        self.refresh()
        self.assertEqual(guard.verify_tree(self.root), [])
        self.policy['licensed_media'][name] = '0' * 64
        self.refresh()
        self.assertTrue(guard.verify_tree(self.root))

    def test_licensed_font_policy_cannot_allow_other_media_or_bad_hashes(self):
        for name, identity in (('font.ttf', None), ('font.ttf', 'not a hash'),
                               ('art.png', '0' * 64), ('../font.ttf', '0' * 64)):
            with self.subTest(name=name, identity=identity):
                self.policy['licensed_media'] = {name: identity}
                self.refresh()
                self.assertTrue(guard.verify_tree(self.root))

    def artwork_fixture(self):
        data = authored_rgb_png()
        self.files[guard.ARTWORK_PATH] = data
        identity = hashlib.sha256(data).hexdigest()
        self.policy['licensed_media'][guard.ARTWORK_PATH] = identity
        self.refresh()
        return data, identity

    @contextlib.contextmanager
    def authored_artwork_policy(self, data=None, identity=None):
        # Only this isolated synthetic fixture changes the immutable production
        # pin. Tests using the actual shipped illustration do not patch the pin.
        data = data if data is not None else authored_rgb_png()
        identity = identity or hashlib.sha256(data).hexdigest()
        with mock.patch.object(guard, 'ARTWORK_SHA256', identity), \
                mock.patch.object(guard, 'ARTWORK_BYTES', len(data)), \
                mock.patch.object(guard, 'ARTWORK_WIDTH', 1), \
                mock.patch.object(guard, 'ARTWORK_HEIGHT', 1):
            yield

    def test_actual_reviewed_artwork_has_immutable_identity_and_header(self):
        source = ROOT / guard.ARTWORK_PATH
        if not (ROOT / 'Monado_Linux').is_dir():
            self.skipTest('Linux illustration is absent from the Windows-only source kit')
        self.assertTrue(source.is_file(), 'the reviewed Linux illustration must be shipped')
        data = source.read_bytes()
        self.assertEqual(len(data), 2621747)
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '4a863642bba750089667e10727cf72353875a7baf80a0903911e47d897d8fd0a')
        self.assertIsNone(guard.path_problem(guard.ARTWORK_PATH))
        self.assertIsNone(guard.content_problem(guard.ARTWORK_PATH, data,
                         {guard.ARTWORK_PATH: guard.ARTWORK_SHA256}))
        self.assertIsNotNone(guard.content_problem(guard.ARTWORK_PATH, data))

    def test_reviewed_artwork_requires_fixed_policy_and_matching_file(self):
        data, identity = self.artwork_fixture()
        with self.authored_artwork_policy(data):
            self.assertEqual(guard.verify_tree(self.root), [])
            self.policy['licensed_media'].clear()
            self.refresh()
            self.assertTrue(guard.verify_tree(self.root))
            self.policy['licensed_media'][guard.ARTWORK_PATH] = '0' * 64
            self.refresh()
            self.assertTrue(guard.verify_tree(self.root))
            self.policy['licensed_media'][guard.ARTWORK_PATH] = identity
            self.refresh()
            self.assertEqual(guard.verify_tree(self.root), [])

    def test_artwork_rehashing_manifest_and_policy_cannot_admit_mutated_content(self):
        data, identity = self.artwork_fixture()
        changed = data[:-1] + bytes((data[-1] ^ 1,))
        with self.authored_artwork_policy(data):
            self.files[guard.ARTWORK_PATH] = changed
            self.refresh()  # A new manifest hash cannot override the fixed pin.
            self.assertTrue(guard.verify_tree(self.root))
            self.policy['licensed_media'][guard.ARTWORK_PATH] = hashlib.sha256(changed).hexdigest()
            self.refresh()  # Nor can a newly supplied policy hash override it.
            self.assertTrue(guard.verify_tree(self.root))
            self.assertIsNotNone(guard.content_problem(guard.ARTWORK_PATH, changed,
                                 {guard.ARTWORK_PATH: identity}))

    def test_artwork_header_dimensions_format_and_size_are_independently_checked(self):
        good = authored_rgb_png()
        malformed = [good[:16] + struct.pack('>I', 2) + good[20:],
                     good[:20] + struct.pack('>I', 2) + good[24:],
                     good[:25] + b'\x06' + good[26:],
                     b'NOTPNG!!' + good[8:]]
        for data in malformed:
            identity = hashlib.sha256(data).hexdigest()
            with self.subTest(header=data[:29]), self.authored_artwork_policy(data):
                self.assertIsNotNone(guard.content_problem(guard.ARTWORK_PATH, data,
                                     {guard.ARTWORK_PATH: identity}))
        with self.authored_artwork_policy(good):
            self.assertIsNotNone(guard.content_problem(guard.ARTWORK_PATH, good + b'x',
                                 {guard.ARTWORK_PATH: hashlib.sha256(good).hexdigest()}))

    def test_artwork_exception_does_not_allow_renamed_or_unreviewed_images(self):
        names = ('gaur_plain.png', 'Monado_Windows/tools/launcher/assets/other.png',
                 'Monado_Linux/tools/launcher/assets/gaur_plain.PNG',
                 'Monado_Linux/tools/launcher/assets/other.png',
                 'Monado_Linux/tools/launcher/assets/../assets/gaur_plain.png',
                 'game_files/gaur_plain.png', 'icon.png', 'art.svg')
        data = authored_rgb_png()
        identity = hashlib.sha256(data).hexdigest()
        with self.authored_artwork_policy(data):
            for name in names:
                with self.subTest(name=name):
                    self.assertIsNotNone(guard.path_problem(name))
                    self.policy['licensed_media'] = {name: identity}
                    self.refresh()
                    self.assertTrue(guard.verify_tree(self.root))

    def test_windows_reviewed_assets_are_identical_and_pinned(self):
        if not (ROOT / 'Monado_Windows').is_dir():
            self.skipTest('Windows launcher assets are absent from the Linux-only source kit')
        policy = json.loads((ROOT / guard.POLICY).read_text(encoding='utf-8'))['licensed_media']
        for suffix in ('gaur_plain.png', 'fonts/DejaVuSans.ttf',
                       'fonts/DejaVuSerif-Bold.ttf', 'fonts/DejaVuSerif-BoldItalic.ttf'):
            windows = 'Monado_Windows/tools/launcher/assets/' + suffix
            linux = windows.replace('Monado_Windows/', 'Monado_Linux/', 1)
            with self.subTest(asset=suffix):
                data = (ROOT / windows).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), policy[windows])
                self.assertEqual(policy[windows], policy[linux])
                if (ROOT / linux).is_file():
                    self.assertEqual(data, (ROOT / linux).read_bytes())
                self.assertIsNone(guard.path_problem(windows))
                self.assertIsNone(guard.content_problem(windows, data, policy))
                self.assertIsNotNone(guard.content_problem(windows, data[:-1] + b'x', policy))

    def test_windows_artwork_requires_fixed_pin_even_if_policy_is_rehashed(self):
        name = 'Monado_Windows/tools/launcher/assets/gaur_plain.png'
        data = authored_rgb_png()
        with self.authored_artwork_policy(data):
            self.files[name] = data
            self.policy['licensed_media'][name] = hashlib.sha256(data).hexdigest()
            self.refresh()
            self.assertEqual(guard.verify_tree(self.root), [])
            self.files[name] = data[:-1] + bytes((data[-1] ^ 1,))
            self.policy['licensed_media'][name] = hashlib.sha256(self.files[name]).hexdigest()
            self.refresh()
            self.assertTrue(guard.verify_tree(self.root))

    def test_artwork_survives_guarded_archive_and_mutated_copy_is_refused(self):
        # Exercise the actual source/stage/readback policy path with authored
        # fixture pixels, not just the content helper in isolation.
        data, identity = self.artwork_fixture()
        # The packager now selects its own adjacent policy, independently of
        # generic cached modules. Give this synthetic-pixel fixture an adjacent
        # real scanner with only its artwork pin changed, rather than patching
        # a process-global policy that production must correctly ignore.
        helpers = self.base / 'fixture-tools'
        helpers.mkdir()
        shutil.copyfile(ROOT / 'tools/package_source_release.py', helpers / 'package_source_release.py')
        policy_source = (ROOT / 'tools/publication_guard.py').read_text()
        policy_source = policy_source.replace(
            f"ARTWORK_SHA256 = '{guard.ARTWORK_SHA256}'", f"ARTWORK_SHA256 = '{identity}'").replace(
            f'ARTWORK_BYTES = {guard.ARTWORK_BYTES}', f'ARTWORK_BYTES = {len(data)}').replace(
            f'ARTWORK_WIDTH, ARTWORK_HEIGHT = {guard.ARTWORK_WIDTH}, {guard.ARTWORK_HEIGHT}',
            'ARTWORK_WIDTH, ARTWORK_HEIGHT = 1, 1')
        (helpers / 'publication_guard.py').write_text(policy_source)
        spec = importlib.util.spec_from_file_location('_authored_art_release', helpers / 'package_source_release.py')
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with mock.patch.object(release, '_source_guard', wraps=release._source_guard) as checks:
            result = release.package(self.root, 'linux', 'authored-art-test', self.base / 'release')
            self.assertEqual(checks.call_count, 4)  # source, staging, readback, final source
            archive = self.base / 'release' / result['archive']
            with tarfile.open(archive) as packed:
                name = next(name for name in packed.getnames() if name.endswith('/' + guard.ARTWORK_PATH))
                self.assertEqual(packed.extractfile(name).read(), data)
            self.files[guard.ARTWORK_PATH] = data[:-1] + bytes((data[-1] ^ 1,))
            self.refresh()
            rejected = self.base / 'rejected-release'
            with self.assertRaises(release.ReleaseError):
                release.package(self.root, 'linux', 'rejected-art-test', rejected)
            self.assertFalse(rejected.exists())
            self.assertEqual(checks.call_count, 5)
        self.assertIs(sys.modules['publication_guard'], guard)

    def test_policy_schema_bool_is_rejected(self):
        self.policy['schema'] = True
        self.refresh()
        self.assertTrue(guard.verify_tree(self.root))

    def test_symlink_files_and_directories_are_rejected_without_following(self):
        external = self.base / 'external'
        external.mkdir()
        (external / 'private').write_text('authored outside fixture')
        try:
            (self.root / 'linked-dir').symlink_to(external, target_is_directory=True)
            (self.root / 'linked-file').symlink_to(external / 'private')
        except OSError:
            self.skipTest('host cannot create symlinks')
        with mock.patch.object(guard, 'read_regular', wraps=guard.read_regular) as reader:
            self.assertTrue(guard.verify_tree(self.root))
        self.assertTrue(all(Path(call.args[0]).is_relative_to(self.root) for call in reader.call_args_list))

    def test_root_git_symlink_is_rejected_without_reading_its_target(self):
        external = self.base / 'external'
        external.mkdir()
        try:
            (self.root / '.git').symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest('host cannot create symlinks')
        self.assertTrue(guard.verify_tree(self.root))

    def test_ordinary_git_directory_and_worktree_pointer_are_excluded(self):
        git = self.root / '.git'
        git.mkdir()
        (git / 'metadata').write_bytes(b'authored metadata\xff')
        self.assertEqual(guard.verify_tree(self.root), [])
        (git / 'metadata').unlink()
        git.rmdir()
        git.write_text('gitdir: authored fixture pointer, never followed')
        self.assertEqual(guard.verify_tree(self.root), [])

    def test_root_directory_symlink_is_rejected(self):
        alias = self.base / 'alias'
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('host cannot create symlinks')
        self.assertTrue(guard.verify_tree(alias))

    def test_walk_errors_fail_closed(self):
        def inaccessible(*args, **kwargs):
            kwargs['onerror'](PermissionError('authored failure'))
            return iter(())
        with mock.patch.object(guard.os, 'walk', side_effect=inaccessible):
            result = guard.verify_tree(self.root)
        self.assertTrue(any('enumerate' in value for value in result))

    def test_regular_reader_rejects_oversize(self):
        target = self.root / 'README.md'
        with mock.patch.object(guard, 'MAX_FILE', 4):
            with self.assertRaises(ValueError):
                guard.read_regular(target)

    def reader_metadata(self, **changes):
        actual = (self.root / 'README.md').lstat()
        fields = {name: getattr(actual, name) for name in
                  ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        fields['st_birthtime_ns'] = 1234000000
        return SimpleNamespace(**{**fields, **changes})

    def test_regular_reader_allows_stable_windows_stat_fstat_api_differences(self):
        target = self.root / 'README.md'
        expected = target.read_bytes()
        pathname = self.reader_metadata(st_mode=stat.S_IFREG | 0o755, st_ctime_ns=1234000000)
        descriptor = self.reader_metadata(st_mode=stat.S_IFREG | 0o644, st_ctime_ns=1235000000)
        with mock.patch.object(Path, 'lstat', side_effect=(pathname, pathname)), \
                mock.patch.object(guard.os, 'fstat', side_effect=(descriptor, descriptor)):
            self.assertEqual(guard.read_regular(target), expected)

    def test_regular_reader_rejects_cross_api_object_and_time_mismatch(self):
        target = self.root / 'README.md'
        pathname = self.reader_metadata()
        for field, value in (('st_dev', pathname.st_dev + 1),
                             ('st_ino', pathname.st_ino + 1),
                             ('st_mode', stat.S_IFLNK | 0o644),
                             ('st_size', pathname.st_size + 1),
                             ('st_mtime_ns', pathname.st_mtime_ns + 1),
                             ('st_birthtime_ns', pathname.st_birthtime_ns + 1)):
            with self.subTest(field=field), \
                    mock.patch.object(Path, 'lstat', return_value=pathname), \
                    mock.patch.object(guard.os, 'fstat', return_value=self.reader_metadata(**{field: value})):
                with self.assertRaises(ValueError):
                    guard.read_regular(target)

    def test_regular_reader_rejects_same_api_metadata_mutation(self):
        target = self.root / 'README.md'
        pathname = self.reader_metadata(st_mode=stat.S_IFREG | 0o755, st_ctime_ns=1234000000)
        descriptor = self.reader_metadata(st_mode=stat.S_IFREG | 0o644, st_ctime_ns=1235000000)
        for api in ('path', 'descriptor'):
            original = pathname if api == 'path' else descriptor
            for field in ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns',
                          'st_ctime_ns', 'st_birthtime_ns'):
                changed = SimpleNamespace(**{**vars(original), field: getattr(original, field) + 1})
                path_values = (pathname, changed) if api == 'path' else (pathname, pathname)
                fd_values = (descriptor, changed) if api == 'descriptor' else (descriptor, descriptor)
                with self.subTest(api=api, field=field), \
                        mock.patch.object(Path, 'lstat', side_effect=path_values), \
                        mock.patch.object(guard.os, 'fstat', side_effect=fd_values):
                    with self.assertRaises(ValueError):
                        guard.read_regular(target)

    def test_regular_reader_requests_binary_mode_and_preserves_control_bytes(self):
        target = self.root / 'README.md'
        expected = b'authored\r\nbyte fixture\x1a\x00\xff\r\n'
        target.write_bytes(expected)
        original_open = guard.os.open
        native_binary = getattr(guard.os, 'O_BINARY', 0)
        marker = 1 << 29
        seen = []

        def opened(path, flags):
            seen.append(flags)
            return original_open(path, (flags & ~marker) | native_binary)

        with mock.patch.object(guard.os, 'O_BINARY', marker, create=True), \
                mock.patch.object(guard.os, 'open', side_effect=opened):
            self.assertEqual(guard.read_regular(target), expected)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0] & marker)

    def test_regular_reader_detects_fstat_change(self):
        target = self.root / 'README.md'
        actual = target.stat()
        fields = {name: getattr(actual, name) for name in
                  ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        changed = SimpleNamespace(**{**fields, 'st_mtime_ns': actual.st_mtime_ns + 1})
        with mock.patch.object(guard.os, 'fstat', side_effect=(actual, changed)):
            with self.assertRaises(ValueError):
                guard.read_regular(target)

    def test_regular_reader_detects_path_replacement_after_open(self):
        target = self.root / 'README.md'
        original_open = guard.os.open

        def replaced(path, flags):
            # Rename before opening: Windows CRT descriptors can deny rename.
            previous = self.root / 'previous-readme'
            target.rename(previous)
            descriptor = original_open(previous, flags)
            target.write_text('authored replacement')
            return descriptor

        with mock.patch.object(guard.os, 'open', side_effect=replaced):
            with self.assertRaises(ValueError):
                guard.read_regular(target)

    def test_manifest_change_during_verification_is_rejected(self):
        original = guard.read_regular
        count = 0

        def mutate(path):
            nonlocal count
            data = original(path)
            count += 1
            if count == 3:
                self.manifest['note'] = 'changed while checking source'
                self.save_manifest()
            return data

        with mock.patch.object(guard, 'read_regular', side_effect=mutate):
            result = guard.verify_tree(self.root)
        self.assertTrue(any('changed during' in value for value in result))


if __name__ == '__main__':
    unittest.main()
