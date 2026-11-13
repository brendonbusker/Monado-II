#!/usr/bin/env python3
"""Package the exact official AppImage runtime sources/relinking materials.

This separate third-party source asset is not a game/source-tree packager.
Only three locked official archives and fixed authored guides/licenses enter it.
No game dump, SDK, compiled runtime or arbitrary directory is ever selected.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = 'tools/builder_appimage'
LOCK = 'runtime-sources.lock.json'
MAX_ARCHIVE = 20 * 1024 * 1024
MAX_EXPANDED = 160 * 1024 * 1024
REVISION = 'fedfad51acc2860b2916a1eef32ba4a500ff31ef'
RUNTIME_SHA = '617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46'
URLS = {
    'appimage-type2-runtime-fedfad51.tar.gz': 'https://codeload.github.com/AppImage/type2-runtime/tar.gz/' + REVISION,
    'fuse-3.15.0.tar.xz': 'https://github.com/libfuse/libfuse/releases/download/fuse-3.15.0/fuse-3.15.0.tar.xz',
    'squashfuse-0.5.2.tar.gz': 'https://github.com/vasi/squashfuse/archive/0.5.2.tar.gz',
}
HOSTS = {'github.com', 'codeload.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(path):
    path = Path(path).absolute()
    if path.resolve() != path or '..' in path.parts:
        raise ValueError('source materials paths must be canonical and have no symlinks')
    return path


def regular(path, limit=MAX_ARCHIVE):
    path = canonical(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise ValueError('expected an ordinary single-link bounded source file')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
        finished = os.fstat(stream.fileno())
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    # Windows lstat/fstat can report different executable bits and ctime
    # semantics. Keep full comparisons within each API, as the source guard
    # does, then compare shared identity across pathname/descriptor APIs.
    common = lambda s: (s.st_dev, s.st_ino, stat.S_IFMT(s.st_mode), s.st_size, s.st_mtime_ns)
    if (identity(before) != identity(after) or identity(opened) != identity(finished) or
            common(before) != common(opened) or not stat.S_ISREG(opened.st_mode) or
            opened.st_nlink != 1 or len(data) != before.st_size):
        raise ValueError('source file changed while reading')
    return data


def relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or
            name != str(PurePosixPath(name)) or PurePosixPath(name).is_absolute() or
            any(p in ('.', '..', '') for p in name.split('/'))):
        raise ValueError('unsafe source archive member path')
    return name


def load_lock(root):
    def unique(pairs):
        value = {}
        for name, entry in pairs:
            if name in value:
                raise ValueError('duplicate source lock field')
            value[name] = entry
        return value
    raw = regular(root / MATERIALS / LOCK, 65536)
    lock = json.loads(raw, object_pairs_hook=unique)
    if (lock.get('schema') != 1 or lock.get('project') != 'Monado II' or
            lock.get('runtime', {}).get('revision') != REVISION or
            lock['runtime'].get('binary_sha256') != RUNTIME_SHA or
            not isinstance(lock.get('sources'), list) or len(lock['sources']) != len(URLS)):
        raise ValueError('unexpected runtime source identity')
    seen = set()
    for entry in lock['sources']:
        name = relative(entry.get('name'))
        if (name in seen or name not in URLS or entry.get('url') != URLS[name] or
                type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= MAX_ARCHIVE or
                not re.fullmatch(r'[0-9a-f]{64}', str(entry.get('sha256', ''))) or
                not isinstance(entry.get('required'), list) or not entry['required']):
            raise ValueError('invalid locked upstream source')
        relative(entry.get('root'))
        for needed in entry['required']:
            relative(needed)
        seen.add(name)
    return lock, raw


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or
            parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('runtime source download left official HTTPS origins')


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def archive_bytes(cache, entry, *, fetch=False, opener=None):
    path = canonical(cache / entry['name'])
    if not path.exists() and not path.is_symlink():
        if not fetch:
            raise ValueError('missing locked source archive; use --fetch to download official sources: ' + entry['name'])
        safe_url(entry['url'])
        request = urllib.request.Request(entry['url'], headers={'User-Agent': 'Monado-II-runtime-source-materials'})
        client = opener or urllib.request.build_opener(Redirect())
        with client.open(request, timeout=60) as response:
            safe_url(response.geturl())
            data = response.read(entry['bytes'] + 1)
        if len(data) != entry['bytes'] or sha(data) != entry['sha256']:
            raise ValueError('official runtime source size/hash differs from the reviewed lock')
        cache.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    data = regular(path, entry['bytes'])
    if len(data) != entry['bytes'] or sha(data) != entry['sha256']:
        raise ValueError('cached runtime source size/hash differs; preserve it for inspection')
    return data


def inspect_archive(data, entry):
    seen, required, expanded, files = set(), set(entry['required']), 0, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as source:
        members = source.getmembers()
        if not 0 < len(members) <= 10000:
            raise ValueError('unexpected upstream source member count')
        for member in members:
            name = member.name.rstrip('/')
            relative(name)
            parts = PurePosixPath(name).parts
            if parts[0] != entry['root'] or name in seen or not (member.isfile() or member.isdir()):
                raise ValueError('unsafe, linked or duplicate source archive member')
            seen.add(name)
            if member.isdir():
                continue
            if not 0 <= member.size <= MAX_ARCHIVE:
                raise ValueError('oversized source archive member')
            expanded += member.size
            files += 1
            if expanded > MAX_EXPANDED:
                raise ValueError('upstream source exceeds expansion bound')
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError('source member could not be inspected')
            with stream:
                magic = stream.read(8)
            if (magic.startswith((b'\x7fELF', b'MZ', b'!<arch>\n', b'!<thin>\n')) or
                    magic[:4] in (b'\x03\x02\x23\x07', b'\x07\x23\x02\x03', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe')):
                raise ValueError('compiled executable/object/shader inside source archive')
            required.discard('/'.join(parts[1:]))
    if required:
        raise ValueError('upstream archive lacks required source/build materials: ' + ', '.join(sorted(required)))
    return dict(members=len(members), files=files, expanded_bytes=expanded,
                required_sources_present=True, compiled_native_files=False)


def prepared_source(data, entry):
    """Omit only unrelated/nonpreferred documentation from libfuse's release.

    All remaining preferred source, interfaces, build scripts and manual pages
    retain their exact upstream bytes and executable bits. The upstream archive
    itself stays intact in the cache and its reviewed hash remains in the lock.
    """
    if entry['name'] != 'fuse-3.15.0.tar.xz':
        return entry['name'], data, None
    kept, omitted, contents = {}, {}, {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name[len(entry['root']) + 1:]
            with archive.extractfile(member) as incoming:
                content = incoming.read(MAX_ARCHIVE + 1)
            identity = dict(bytes=len(content), sha256=sha(content), mode=member.mode & 0o777)
            if name.startswith('doc/html/') or name == 'doc/fast17-vangoor.pdf':
                omitted[name] = identity
            else:
                kept[name] = identity
                contents[name] = content
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as result:
            for name, content in sorted(contents.items()):
                member = tarfile.TarInfo(entry['root'] + '/' + name)
                member.mode, member.size = kept[name]['mode'], len(content)
                result.addfile(member, io.BytesIO(content))
    report = dict(upstream_archive=entry['name'], upstream_bytes=entry['bytes'],
        upstream_sha256=entry['sha256'], retained_files=kept,
        excluded_nonbuild_documents=omitted, retained_source_bytes_unchanged=True,
        excluded_prefixes=['doc/html/'], excluded_paths=['doc/fast17-vangoor.pdf'])
    return 'fuse-3.15.0-source.tar.gz', output.getvalue(), report


def readback(path, prefix, files):
    found = set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive.getmembers():
            if (not member.isfile() or member.mode != 0o644 or not member.name.startswith(prefix + '/') or
                    member.name in found or member.uid or member.gid or member.mtime):
                raise ValueError('runtime source companion readback has unsafe metadata')
            relative(member.name)
            name = member.name[len(prefix) + 1:]
            if name not in files:
                raise ValueError('unexpected runtime source companion file')
            with archive.extractfile(member) as incoming:
                if incoming.read(MAX_ARCHIVE + 1) != files[name]:
                    raise ValueError('runtime source companion readback identity mismatch')
            found.add(member.name)
    if found != {prefix + '/' + name for name in files}:
        raise ValueError('runtime source companion readback missing files')


def package(root, cache, output, version, *, fetch=False, opener=None):
    root, cache, output = map(canonical, (root, cache, output))
    if not re.fullmatch(r'0\.\d+\.\d+', version):
        raise ValueError('use a concrete Monado II release version')
    filename = 'monado-ii-' + version + '-linux-builder-runtime-sources.tar.gz'
    if output.name != filename or output.is_relative_to(root):
        raise ValueError('runtime source companion must use its release filename outside reviewed source')
    receipt_path = output.with_name(output.name + '.receipt.json')
    if output.exists() or output.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError('refusing to replace runtime source output or receipt')
    lock, raw_lock = load_lock(root)
    files, inspections = {}, {}
    for entry in lock['sources']:
        data = archive_bytes(cache, entry, fetch=fetch, opener=opener)
        inspection = inspect_archive(data, entry)
        name, packaged, derivation = prepared_source(data, entry)
        if derivation is not None:
            inspection['source_derivation'] = derivation
            inspect_archive(packaged, entry)
        inspections[entry['name']] = inspection
        files['archives/' + name] = packaged
    for source, target in (
        (root / MATERIALS / 'RUNTIME_SOURCES.md', 'README.md'),
        (root / MATERIALS / 'Dockerfile.runtime-relink', 'Dockerfile.runtime-relink'),
        (root / 'tools/appimage/libfuse-LGPL-2.1.txt', 'LGPL-2.1.txt'),
        (root / 'LICENSE', 'LICENSE-Monado-II.txt')):
        files[target] = regular(source)
    files[LOCK] = raw_lock
    identities = {name: dict(bytes=len(data), sha256=sha(data)) for name, data in sorted(files.items())}
    manifest = dict(schema=1, project='Monado II', version=version,
        kind='appimage-runtime-source-and-relinking-materials', files=identities,
        source_inspections=inspections, contains_game_files=False, contains_compiled_executables=False,
        contains_vendor_sdk=False, unrelated_libfuse_documentation_omitted=True,
        binary_runtime_sha256=RUNTIME_SHA)
    files['MANIFEST.json'] = encoded(manifest)
    files['SHA256SUMS'] = ''.join(sha(data) + '  ' + name + '\n' for name, data in sorted(files.items())).encode()
    prefix = filename.removesuffix('.tar.gz')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name('.' + output.name + '.partial')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('refusing to replace an existing partial source archive')
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
        created = True
        with os.fdopen(descriptor, 'wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(prefix + '/' + name)
                    info.size, info.mode, info.mtime, info.uid, info.gid = len(data), 0o644, 0, 0, 0
                    archive.addfile(info, io.BytesIO(data))
        readback(temporary, prefix, files)
        archive_data = regular(temporary)
        os.link(temporary, output)
        temporary.unlink()
        receipt = dict(status='passed', artifact_kind=manifest['kind'], version=version,
            archive=output.name, bytes=len(archive_data), sha256=sha(archive_data),
            archive_readback_verified=True, files=identities, source_inspections=inspections,
            contains_game_files=False, contains_compiled_executables=False, contains_vendor_sdk=False)
        with receipt_path.open('xb') as stream:
            stream.write(encoded(receipt))
        return receipt
    finally:
        if created and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--fetch', action='store_true', help='download only missing exact locked official source archives')
    args = parser.parse_args(argv)
    try:
        receipt = package(args.source, args.cache, args.output, args.version, fetch=args.fetch)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, 'Runtime source companion failed: ' + str(error) + '\n')
    print(json.dumps({name: receipt[name] for name in ('status', 'archive', 'bytes', 'sha256', 'archive_readback_verified')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
