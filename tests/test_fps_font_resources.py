"""Licensed FPS font embedding: actual bundled bytes and guarded local outputs."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'Monado_Linux/tools/launcher/assets/fonts'
SPEC = importlib.util.spec_from_file_location('fps_font_generator_under_test',
    ROOT / 'Monado_Linux/tools/gen_fps_fonts.py')
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def identity(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def stat_fields(info, **changes):
    fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
    fields.update(changes)
    return SimpleNamespace(**fields)


def native_recipe():
    previous = list(sys.path)
    sys.path.insert(0, str(ROOT / 'Monado_Linux/scripts'))
    try:
        spec = importlib.util.spec_from_file_location('fps_font_native_build_under_test',
            ROOT / 'Monado_Linux/scripts/build_linux.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous


class FpsFontResources(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-fps-fonts-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.assets = self.base / 'fonts'
        self.assets.mkdir()
        for name in ('DejaVuSans.ttf', 'DejaVuSerif-Bold.ttf', 'LICENSE-DejaVu.txt'):
            shutil.copyfile(ASSETS / name, self.assets / name)
        self.output = self.base / 'fps_fonts.h'

    def reject_without_output(self):
        with self.assertRaises((OSError, ValueError)):
            generator.generate(self.assets, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.is_symlink())

    def test_actual_font_bytes_deterministic_header_and_licence_identity(self):
        first = generator.generate(self.assets, self.output)
        raw = self.output.read_bytes()
        second_path = self.base / 'fps_fonts_second.h'
        second = generator.generate(self.assets, second_path)
        self.assertEqual(raw, second_path.read_bytes())
        self.assertEqual(first, second)
        self.assertEqual(first['header'], identity(raw))
        arrays = {}
        for name, contents in re.findall(
                r'inline constexpr unsigned char (\w+)\[\] = \{([^}]*)\};', raw.decode('ascii')):
            self.assertNotIn(name, arrays)
            arrays[name] = bytes(int(value, 16) for value in re.findall(r'0x([0-9a-f]{2})', contents))
        expected = {'DejaVuSans.ttf': 'fps_font_sans', 'DejaVuSerif-Bold.ttf': 'fps_font_serif'}
        self.assertEqual(set(arrays), set(expected.values()))
        self.assertEqual(set(first['fonts']), set(expected))
        for name, symbol in expected.items():
            original = (ASSETS / name).read_bytes()
            self.assertEqual(arrays[symbol], original)
            self.assertEqual(first['fonts'][name], dict(identity(original), symbol=symbol))
        licence = (ASSETS / 'LICENSE-DejaVu.txt').read_bytes()
        self.assertEqual(first['licence'], dict(identity(licence), source='LICENSE-DejaVu.txt'))
        self.assertIn(b'DejaVu-font-license.txt', raw)
        self.assertNotIn(b'monado_art_png', raw)
        self.assertNotIn(b'gaur_plain', raw)

    def test_reads_only_two_named_fonts_and_notice_not_art_or_host_fonts(self):
        (self.assets / 'gaur_plain.png').write_bytes(b'authored invalid artwork, must never be read')
        (self.assets / 'unrelated.ttf').write_bytes(b'authored invalid unselected font')
        requested = []
        real = generator.read_source
        def read(path, **kwargs):
            path = Path(path)
            self.assertEqual(path.parent, self.assets)
            requested.append((path.name, kwargs.get('font', False)))
            return real(path, **kwargs)
        with mock.patch.object(generator, 'read_source', side_effect=read):
            generator.generate(self.assets, self.output)
        self.assertEqual(requested, [('DejaVuSans.ttf', True),
            ('DejaVuSerif-Bold.ttf', True), ('LICENSE-DejaVu.txt', False)])

    def test_stable_windows_path_and_descriptor_ctimes_can_differ(self):
        # CPython3.14 Windows uses creation time for pathname ctime and change
        # time for fstat ctime (python/cpython#157671). Both channels are stable.
        real_fstat = os.fstat
        def descriptor(fd):
            info = real_fstat(fd)
            return stat_fields(info, st_ctime_ns=info.st_ctime_ns + 1000000000)
        with mock.patch.object(generator.os, 'fstat', side_effect=descriptor):
            actual = generator.generate(self.assets, self.output)
        reference_output = self.base / 'reference_fonts.h'
        reference = generator.generate(self.assets, reference_output)
        self.assertEqual(actual, reference)
        self.assertEqual(self.output.read_bytes(), reference_output.read_bytes())

    def test_ctime_change_on_either_channel_is_rejected_with_identical_size_and_mtime(self):
        target = self.assets / 'DejaVuSans.ttf'
        real_lstat, real_fstat = Path.lstat, os.fstat
        for channel in ('pathname', 'descriptor'):
            with self.subTest(channel=channel):
                calls = 0
                def pathname(path, *args, **kwargs):
                    nonlocal calls
                    info = real_lstat(path, *args, **kwargs)
                    if path == target:
                        calls += 1
                        if calls == 2:
                            info = stat_fields(info, st_ctime_ns=info.st_ctime_ns + 1)
                    return info
                def descriptor(fd):
                    nonlocal calls
                    info = real_fstat(fd)
                    calls += 1
                    if calls == 2:
                        info = stat_fields(info, st_ctime_ns=info.st_ctime_ns + 1)
                    return info
                patch = (mock.patch.object(generator.Path, 'lstat', pathname)
                         if channel == 'pathname' else
                         mock.patch.object(generator.os, 'fstat', side_effect=descriptor))
                with patch, self.assertRaisesRegex(ValueError, 'changed while reading'):
                    generator.read_source(target, font=True)
                self.assertEqual(calls, 2)
                self.assertFalse(self.output.exists())

    def test_open_descriptor_must_match_path_identity_links_size_mode_and_mtime(self):
        target = self.assets / 'DejaVuSans.ttf'
        original = target.lstat()
        changes = {'st_dev': original.st_dev + 1, 'st_ino': original.st_ino + 1,
            'st_mode': original.st_mode ^ stat.S_IXUSR, 'st_nlink': 2,
            'st_size': original.st_size + 1, 'st_mtime_ns': original.st_mtime_ns + 1}
        real_fstat = os.fstat
        for name, value in changes.items():
            with self.subTest(field=name):
                def descriptor(fd):
                    return stat_fields(real_fstat(fd), **{name: value})
                with mock.patch.object(generator.os, 'fstat', side_effect=descriptor):
                    self.reject_without_output()

    def test_missing_or_bad_font_never_creates_header(self):
        target = self.assets / 'DejaVuSerif-Bold.ttf'
        target.unlink()
        self.reject_without_output()
        for data in (b'', b'OTTO', b'not a font at all', b'ttcf' + b'\0' * 32):
            with self.subTest(data=data):
                target.write_bytes(data)
                self.reject_without_output()

    def test_missing_or_bad_notice_never_creates_header(self):
        target = self.assets / 'LICENSE-DejaVu.txt'
        target.unlink()
        self.reject_without_output()
        for data in (b'', b'notice missing complete expected redistribution terms', b'\xff\xfe\xff'):
            with self.subTest(data=data):
                target.write_bytes(data)
                self.reject_without_output()

    @unittest.skipUnless(hasattr(os, 'symlink'), 'filesystem symlinks unavailable')
    def test_linked_font_notice_or_assets_directory_are_rejected(self):
        for name in ('DejaVuSans.ttf', 'LICENSE-DejaVu.txt'):
            with self.subTest(name=name):
                target = self.assets / name
                saved = self.base / ('original-' + name)
                target.rename(saved)
                try:
                    target.symlink_to(saved)
                except OSError as error:
                    saved.rename(target)
                    self.skipTest('symlinks unavailable: ' + str(error))
                self.reject_without_output()
                target.unlink(); saved.rename(target)
        alias = self.base / 'font-alias'
        alias.symlink_to(self.assets, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical'):
            generator.generate(alias, self.output)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, 'link'), 'filesystem hardlinks unavailable')
    def test_hardlinked_font_and_notice_are_rejected(self):
        for name in ('DejaVuSans.ttf', 'LICENSE-DejaVu.txt'):
            with self.subTest(name=name):
                target = self.assets / name
                linked = self.base / ('linked-' + name)
                try:
                    os.link(target, linked)
                except OSError as error:
                    self.skipTest('hardlinks unavailable: ' + str(error))
                self.reject_without_output()
                linked.unlink()

    def test_oversized_font_or_notice_never_creates_header(self):
        for name in ('DejaVuSans.ttf', 'LICENSE-DejaVu.txt'):
            with self.subTest(name=name):
                target = self.assets / name
                original = target.read_bytes()
                with target.open('wb') as stream:
                    stream.truncate(generator.MAX_ASSET + 1)
                self.reject_without_output()
                target.write_bytes(original)

    def test_existing_header_and_non_directory_parent_are_preserved(self):
        self.output.write_bytes(b'authored existing header sentinel')
        with self.assertRaisesRegex(ValueError, 'fresh'):
            generator.generate(self.assets, self.output)
        self.assertEqual(self.output.read_bytes(), b'authored existing header sentinel')
        for path in (self.base / 'absent' / 'fps.h', self.output / 'fps.h'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'fresh'):
                generator.generate(self.assets, path)
        self.assertFalse((self.base / 'absent').exists())

    @unittest.skipUnless(hasattr(os, 'link'), 'filesystem hardlinks unavailable')
    def test_hardlinked_output_preserves_both_existing_names(self):
        sentinel = self.base / 'sentinel'; sentinel.write_bytes(b'authored preserved target')
        try:
            os.link(sentinel, self.output)
        except OSError as error:
            self.skipTest('hardlinks unavailable: ' + str(error))
        with self.assertRaisesRegex(ValueError, 'fresh'):
            generator.generate(self.assets, self.output)
        self.assertEqual(sentinel.read_bytes(), b'authored preserved target')
        self.assertEqual(self.output.read_bytes(), b'authored preserved target')

    @unittest.skipUnless(hasattr(os, 'symlink'), 'filesystem symlinks unavailable')
    def test_linked_output_or_output_parent_cannot_redirect_or_overwrite(self):
        sentinel = self.base / 'sentinel'; sentinel.write_bytes(b'authored preserved target')
        try:
            self.output.symlink_to(sentinel)
        except OSError as error:
            self.skipTest('symlinks unavailable: ' + str(error))
        with self.assertRaisesRegex(ValueError, 'fresh'):
            generator.generate(self.assets, self.output)
        self.assertEqual(sentinel.read_bytes(), b'authored preserved target')
        self.output.unlink()
        actual = self.base / 'real-output'; actual.mkdir()
        alias = self.base / 'linked-output'; alias.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'fresh'):
            generator.generate(self.assets, alias / 'fps_fonts.h')
        self.assertEqual(list(actual.iterdir()), [])


class NativeFontFinalization(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-fps-font-finish-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.header = self.base / 'inc/fps_fonts.h'
        self.header.parent.mkdir()
        self.original = b'authored generated font header fixture\n'
        self.header.write_bytes(self.original)
        self.native = native_recipe()
        self.builder = object.__new__(self.native.Builder)
        self.builder.output = self.base
        self.builder.failed = threading.Event()
        self.metadata = dict(schema=1, header=identity(self.original))
        self.builder.receipt = dict(sources_before={}, generated={}, errors=[],
            dependencies={}, fps_font_resources=self.metadata)

    def finish(self, expected):
        with mock.patch.object(self.native, 'source_snapshot', return_value={}):
            result = self.builder.finish()
        self.assertEqual(result, expected)
        self.assertEqual(self.builder.receipt['status'], 'passed' if expected else 'failed')
        recorded = json.loads((self.base / 'receipt.json').read_text())
        self.assertEqual(recorded['fps_font_resources'], self.metadata)
        self.assertEqual(recorded['sources_before'], recorded['sources_after'])
        if expected:
            self.assertEqual(recorded['errors'], [])
        else:
            self.assertIn('generated FPS font header changed during build', recorded['errors'])

    def test_unchanged_generated_header_is_accepted_and_metadata_retained(self):
        self.finish(True)

    def test_same_size_changed_header_rejects_success(self):
        self.header.write_bytes(b'X' + self.original[1:])
        self.assertEqual(self.header.stat().st_size, len(self.original))
        self.finish(False)

    def test_missing_generated_header_rejects_success(self):
        self.header.unlink()
        self.finish(False)

    @unittest.skipUnless(hasattr(os, 'symlink'), 'filesystem symlinks unavailable')
    def test_linked_generated_header_rejects_identical_bytes(self):
        target = self.base / 'same-header'; self.header.rename(target)
        try:
            self.header.symlink_to(target)
        except OSError as error:
            self.skipTest('symlinks unavailable: ' + str(error))
        self.finish(False)
        self.assertEqual(target.read_bytes(), self.original)

    @unittest.skipUnless(hasattr(os, 'link'), 'filesystem hardlinks unavailable')
    def test_hardlinked_generated_header_rejects_identical_bytes(self):
        target = self.base / 'same-header'
        try:
            os.link(self.header, target)
        except OSError as error:
            self.skipTest('hardlinks unavailable: ' + str(error))
        self.finish(False)
        self.assertEqual(target.read_bytes(), self.original)

    def test_verified_prebuilt_runtime_needs_no_local_generated_header(self):
        self.header.unlink()
        self.builder.receipt['prebuilt_runtime'] = dict(manifest_sha256='1' * 64,
            path='authored verified import fixture')
        self.finish(True)


if __name__ == '__main__':
    unittest.main()
