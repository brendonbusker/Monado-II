"""Runtime companion boundaries using authored tiny source archives; no network."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('builder_runtime_sources_tested', ROOT / 'tools/package_builder_runtime_sources.py')
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


def source_archive(root, files, *, extra=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as tar:
        for name, data in files.items():
            member = tarfile.TarInfo(root + '/' + name)
            member.size, member.mode = len(data), 0o644
            tar.addfile(member, io.BytesIO(data))
        if extra is not None:
            tar.addfile(extra, io.BytesIO(b'') if extra.isfile() else None)
    return output.getvalue()


class RuntimeSources(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='monado-runtime-sources-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / 'source'
        self.cache = self.base / 'cache'
        self.cache.mkdir()
        self.materials = self.root / pack.MATERIALS
        self.materials.mkdir(parents=True)
        self.lock = json.loads((ROOT / pack.MATERIALS / pack.LOCK).read_text())
        for source, target in ((ROOT / 'LICENSE', self.root / 'LICENSE'),
                (ROOT / 'tools/appimage/libfuse-LGPL-2.1.txt', self.root / 'tools/appimage/libfuse-LGPL-2.1.txt'),
                (ROOT / pack.MATERIALS / 'RUNTIME_SOURCES.md', self.materials / 'RUNTIME_SOURCES.md'),
                (ROOT / pack.MATERIALS / 'Dockerfile.runtime-relink', self.materials / 'Dockerfile.runtime-relink')):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for entry in self.lock['sources']:
            data = source_archive(entry['root'], {name: b'authored upstream-source fixture\n' for name in entry['required']})
            self.put(entry, data)
        self.write_lock()
        self.output = self.base / 'output' / 'monado-ii-0.1.17-linux-builder-runtime-sources.tar.gz'

    def write_lock(self):
        (self.materials / pack.LOCK).write_bytes(pack.encoded(self.lock))

    def put(self, entry, data):
        entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (self.cache / entry['name']).write_bytes(data)

    def package(self, **kwargs):
        return pack.package(self.root, self.cache, self.output, '0.1.17', **kwargs)

    def test_exact_archives_notices_relink_recipe_and_readback(self):
        receipt = self.package()
        self.assertEqual(receipt['status'], 'passed')
        self.assertTrue(receipt['archive_readback_verified'])
        self.assertFalse(receipt['contains_compiled_executables'])
        self.assertFalse(receipt['contains_game_files'])
        self.assertEqual(receipt['sha256'], pack.sha(self.output.read_bytes()))
        with tarfile.open(self.output) as tar:
            names = [m.name.split('/', 1)[1] for m in tar.getmembers()]
            self.assertEqual(len(names), 10)
            self.assertIn('LGPL-2.1.txt', names)
            self.assertIn('Dockerfile.runtime-relink', names)
            self.assertIn('MANIFEST.json', names)
            self.assertIn('SHA256SUMS', names)
            for entry in self.lock['sources']:
                packaged_name, expected, _ = pack.prepared_source((self.cache / entry['name']).read_bytes(), entry)
                member = next(m for m in tar.getmembers() if m.name.endswith('/archives/' + packaged_name))
                self.assertEqual(tar.extractfile(member).read(), expected)

    def test_windows_path_and_descriptor_stat_variations_are_tolerated(self):
        path = self.cache / self.lock['sources'][0]['name']
        original = os.fstat
        def windows_fstat(fd):
            value = original(fd)
            fields = {name: getattr(value, name) for name in
                      ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            fields['st_mode'] ^= 0o111
            fields['st_ctime_ns'] += 1
            return SimpleNamespace(**fields)
        with mock.patch.object(pack.os, 'fstat', side_effect=windows_fstat):
            self.assertEqual(pack.regular(path), path.read_bytes())

    def test_libfuse_filter_retains_preferred_sources_and_records_every_omission(self):
        entry = next(e for e in self.lock['sources'] if e['name'] == 'fuse-3.15.0.tar.xz')
        files = {name: b'authored fixture source\n' for name in entry['required']}
        files.update({'include/api.h':b'authored interface', 'doc/fuse.1':b'authored manual',
                      'doc/html/index.html':b'generated docs', 'doc/html/paper.pdf':b'paper copy',
                      'doc/fast17-vangoor.pdf':b'unrelated paper'})
        data = source_archive(entry['root'], files)
        name, filtered, info = pack.prepared_source(data, entry)
        self.assertEqual(name, 'fuse-3.15.0-source.tar.gz')
        omitted = {'doc/html/index.html', 'doc/html/paper.pdf', 'doc/fast17-vangoor.pdf'}
        self.assertEqual(set(info['excluded_nonbuild_documents']), omitted)
        with tarfile.open(fileobj=io.BytesIO(filtered)) as archive:
            actual = {m.name.split('/',1)[1]:archive.extractfile(m).read() for m in archive.getmembers()}
        self.assertEqual(actual, {n:d for n,d in files.items() if n not in omitted})
        self.assertEqual(set(info['retained_files']), set(actual))
        self.assertTrue(info['retained_source_bytes_unchanged'])
        for n,d in files.items():
            record = (info['excluded_nonbuild_documents'] if n in omitted else info['retained_files'])[n]
            self.assertEqual(record['sha256'], pack.sha(d))

    def test_changed_cache_refuses_without_output(self):
        path = self.cache / self.lock['sources'][0]['name']
        data = path.read_bytes(); path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaisesRegex(ValueError, 'size/hash'):
            self.package()
        self.assertFalse(self.output.exists())

    def test_no_implicit_download_and_exact_official_fetch(self):
        entry = self.lock['sources'][0]
        path = self.cache / entry['name']
        data = path.read_bytes(); path.unlink()
        with self.assertRaisesRegex(ValueError, 'use --fetch'):
            self.package()
        class Response(io.BytesIO):
            def geturl(self): return entry['url']
        opener = SimpleNamespace(open=lambda request, timeout: Response(data))
        self.package(fetch=True, opener=opener)
        self.assertEqual(path.read_bytes(), data)

    def test_fetch_wrong_identity_never_caches(self):
        entry = self.lock['sources'][0]
        path = self.cache / entry['name']; path.unlink()
        class Response(io.BytesIO):
            def geturl(self): return entry['url']
        with self.assertRaisesRegex(ValueError, 'size/hash'):
            self.package(fetch=True, opener=SimpleNamespace(open=lambda request, timeout: Response(b'wrong')))
        self.assertFalse(path.exists()); self.assertFalse(self.output.exists())

    def test_links_traversal_compiled_files_and_missing_materials_refused(self):
        entry = self.lock['sources'][0]
        base = {name: b'authored fixture\n' for name in entry['required']}
        for problem in ('link', 'traversal', 'compiled', 'missing', 'duplicate'):
            with self.subTest(problem=problem):
                files = dict(base); extra = None
                if problem == 'link':
                    extra = tarfile.TarInfo(entry['root'] + '/linked'); extra.type = tarfile.SYMTYPE; extra.linkname = '/outside'
                elif problem == 'traversal':
                    files['../escaped'] = b'authored'
                elif problem == 'compiled':
                    files['native-fixture'] = b'\x7fELF' + bytes(60)
                elif problem == 'missing':
                    del files[entry['required'][0]]
                else:
                    extra = tarfile.TarInfo(entry['root'] + '/' + entry['required'][0])
                data = source_archive(entry['root'], files, extra=extra)
                with self.assertRaises(ValueError):
                    pack.inspect_archive(data, entry)

    def test_output_partial_and_existing_archive_are_preserved(self):
        self.output.parent.mkdir()
        for path in (self.output, self.output.with_name('.' + self.output.name + '.partial')):
            path.write_bytes(b'authored keep')
            with self.assertRaises(ValueError): self.package()
            self.assertEqual(path.read_bytes(), b'authored keep')
            path.unlink()

    def test_reproducible_companion_and_hash_manifest(self):
        self.package(); first = self.output.read_bytes()
        with tarfile.open(self.output) as tar:
            prefix = tar.getmembers()[0].name.split('/')[0]
            sums = tar.extractfile(prefix + '/SHA256SUMS').read().decode().splitlines()
            for line in sums:
                expected, name = line.split('  ', 1)
                self.assertEqual(expected, pack.sha(tar.extractfile(prefix + '/' + name).read()))
        self.output.unlink(); Path(str(self.output) + '.receipt.json').unlink()
        self.package(); self.assertEqual(first, self.output.read_bytes())

    def test_only_reviewed_origins_and_source_lock_identity(self):
        for url in ('http://github.com/source', 'https://example.com/source', 'https://user@github.com/source'):
            with self.subTest(url=url), self.assertRaises(ValueError): pack.safe_url(url)
        self.lock['runtime']['revision'] = 'wrong'; self.write_lock()
        with self.assertRaisesRegex(ValueError, 'identity'): self.package()

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_linked_cache_file_is_not_followed(self):
        entry = self.lock['sources'][0]; path = self.cache / entry['name']
        elsewhere = self.base / 'elsewhere'; path.rename(elsewhere)
        try: path.symlink_to(elsewhere)
        except OSError: self.skipTest('symlink creation unavailable')
        with self.assertRaises(ValueError): self.package()


if __name__ == '__main__':
    unittest.main()
