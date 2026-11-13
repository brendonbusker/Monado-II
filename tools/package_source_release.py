#!/usr/bin/env python3
"""Build reviewed Monado II source-only release kits, never playable game binaries.

Input must be a clean publication tree, with publication-manifest.json binding
every ordinary file. The project publication guard runs on the source, trimmed
staging tree and archive readback. No game input is consumed or downloaded.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from typing import BinaryIO
import zipfile
import zlib

sys.dont_write_bytecode = True
MANIFEST = 'publication-manifest.json'
PROJECT = 'Monado II'
PORTS = {'linux': 'Monado_Linux', 'windows': 'Monado_Windows'}
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
# Windows retains the original implementation. Linux release versions identify
# source snapshots, not a Windows feature update. Change this policy only when
# an actual Windows implementation update is explicitly being released.
WINDOWS_IMPLEMENTATION = 'original'
WINDOWS_ROOT = 'monado-ii-windows-original-implementation'
WINDOWS_ARCHIVE = WINDOWS_ROOT + '-setup.zip'


class ReleaseError(ValueError):
    """A release candidate failed a policy, identity or archive check."""


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(document: dict) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + '\n').encode('utf-8')


def _guard(root: Path) -> None:
    from publication_guard import verify_tree
    violations = verify_tree(root)
    if violations:
        raise ReleaseError('publication guard rejected candidate: ' + '; '.join(violations))


def _relative(name: str) -> PurePosixPath:
    if (not isinstance(name, str) or not name or '\\' in name or '\x00' in name
            or ':' in name or name.startswith('/') or name.endswith('/')):
        raise ReleaseError('invalid manifest path')
    pieces = name.split('/')
    if any(piece in ('', '.', '..') or piece.rstrip(' .') != piece for piece in pieces):
        raise ReleaseError('unsafe manifest path: ' + name)
    if '.git' in pieces or name == MANIFEST:
        raise ReleaseError('manifest may not select Git metadata or itself')
    return PurePosixPath(name)


def _ordinary_root(path: Path, *, must_exist: bool) -> Path:
    path = path.absolute()
    if path.resolve() != path or '..' in path.parts:
        raise ReleaseError('directory must be canonical without symlinks')
    current = Path(path.anchor)
    for piece in path.parts[1:]:
        current /= piece
        try:
            info = current.lstat()
        except FileNotFoundError:
            if must_exist or current != path:
                raise ReleaseError('directory parent is missing') from None
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ReleaseError('directory component is not an ordinary directory')
    if must_exist and not path.is_dir():
        raise ReleaseError('source directory is missing')
    return path


def _inventory(root: Path) -> set[str]:
    def unreadable(error):
        raise ReleaseError('source tree cannot be completely enumerated') from error

    files = set()
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        for name in tuple(dirs):
            item = Path(directory) / name
            info = item.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise ReleaseError('source contains a linked or special directory')
            if directory == str(root) and name == '.git':
                dirs.remove(name)
        for name in names:
            item = Path(directory) / name
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ReleaseError('source contains a linked or special file')
            if directory == str(root) and name == '.git':
                continue  # ordinary linked-worktree metadata, never an archive member
            files.add(item.relative_to(root).as_posix())
    return files


def _document(root: Path) -> tuple[dict, bytes]:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseError('duplicate key in publication manifest')
            result[key] = value
        return result

    manifest = root / MANIFEST
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 8 * 1024 * 1024:
        raise ReleaseError('missing, linked or oversized publication manifest')
    raw = manifest.read_bytes()
    try:
        document = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeDecodeError) as error:
        raise ReleaseError('invalid publication manifest JSON') from error
    if (not isinstance(document, dict) or type(document.get('schema')) is not int or document.get('schema') != 1
            or document.get('project') != PROJECT or not isinstance(document.get('files'), dict)):
        raise ReleaseError('unexpected publication manifest schema/project/files')
    for name, metadata in document['files'].items():
        _relative(name)
        if (not isinstance(metadata, dict) or not isinstance(metadata.get('sha256'), str)
                or not SHA256.fullmatch(metadata['sha256'])
                or type(metadata.get('bytes')) is not int or metadata['bytes'] < 0):
            raise ReleaseError('invalid file identity in manifest: ' + name)
    actual = _inventory(root)
    if actual != set(document['files']) | {MANIFEST}:
        raise ReleaseError('source files differ from publication manifest (missing or extra files)')
    for name, metadata in document['files'].items():
        item = root.joinpath(*PurePosixPath(name).parts)
        if item.stat().st_size != metadata['bytes'] or digest(item) != metadata['sha256']:
            raise ReleaseError('source identity differs from publication manifest: ' + name)
    return document, raw


def _copy_checked(source: Path, destination: Path, identity: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = source.lstat()
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, 'rb') as incoming, destination.open('xb') as outgoing:
        actual = os.fstat(incoming.fileno())
        if (not stat.S_ISREG(actual.st_mode)
                or (before.st_dev, before.st_ino) != (actual.st_dev, actual.st_ino)):
            raise ReleaseError('source file changed before copying')
        shutil.copyfileobj(incoming, outgoing)
        after = os.fstat(incoming.fileno())
    if (actual.st_size, actual.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ReleaseError('source file changed while copying')
    if destination.stat().st_size != identity['bytes'] or digest(destination) != identity['sha256']:
        raise ReleaseError('copied source identity differs from reviewed file')


def _mode(name: str) -> int:
    return 0o755 if name.endswith('.sh') else 0o644


def _write_archive(stage: Path, target: Path, prefix: str, platform: str) -> None:
    names = sorted(_inventory(stage))
    if platform == 'linux':
        with target.open('xb') as output, gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
            with tarfile.open(mode='w', fileobj=compressed, format=tarfile.PAX_FORMAT) as archive:
                for name in names:
                    item = stage / name
                    info = tarfile.TarInfo(prefix + '/' + name)
                    info.size = item.stat().st_size
                    info.mode = _mode(name)
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    with item.open('rb') as source:
                        archive.addfile(info, source)
    else:
        with zipfile.ZipFile(target, mode='x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in names:
                info = zipfile.ZipInfo(prefix + '/' + name, date_time=ZIP_DATE)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | _mode(name)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (stage / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _read_member(stream: BinaryIO, target: Path, expected: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    hasher = hashlib.sha256()
    with target.open('xb') as output:
        while block := stream.read(min(1024 * 1024, expected['bytes'] - count + 1)):
            count += len(block)
            if count > expected['bytes']:
                raise ReleaseError('archive member is larger than its reviewed identity')
            hasher.update(block)
            output.write(block)
    if count != expected['bytes'] or hasher.hexdigest() != expected['sha256']:
        raise ReleaseError('archive member content differs from reviewed identity')


def _verify_archive(target: Path, stage: Path, readback: Path, prefix: str, platform: str) -> None:
    document, raw = _document(stage)
    identities = {**document['files'], MANIFEST: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    expected_names = {prefix + '/' + name: name for name in identities}
    readback.mkdir()
    try:
        if platform == 'linux':
            with tarfile.open(target, mode='r:gz') as archive:
                members = archive.getmembers()
                if len(members) != len(expected_names) or {item.name for item in members} != set(expected_names):
                    raise ReleaseError('tar member set differs from selected release files')
                for info in members:
                    name = expected_names[info.name]
                    if (not info.isfile() or info.size != identities[name]['bytes']
                            or info.mode != _mode(name) or info.uid or info.gid or info.mtime):
                        raise ReleaseError('tar member type, mode, timestamp or size differs')
                    stream = archive.extractfile(info)
                    if stream is None:
                        raise ReleaseError('tar member cannot be read')
                    with stream:
                        _read_member(stream, readback / name, identities[name])
        else:
            with zipfile.ZipFile(target) as archive:
                members = archive.infolist()
                if len(members) != len(expected_names) or {item.filename for item in members} != set(expected_names):
                    raise ReleaseError('zip member set differs from selected release files')
                for info in members:
                    name = expected_names[info.filename]
                    if (stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG
                            or info.file_size != identities[name]['bytes']
                            or stat.S_IMODE(info.external_attr >> 16) != _mode(name)
                            or info.date_time != ZIP_DATE or info.flag_bits & 1):
                        raise ReleaseError('zip member type, mode, timestamp or size differs')
                    with archive.open(info) as stream:
                        _read_member(stream, readback / name, identities[name])
    except (tarfile.TarError, zipfile.BadZipFile, gzip.BadGzipFile, zlib.error, EOFError) as error:
        raise ReleaseError('archive readback failed') from error
    _document(readback)
    _guard(readback)


def package(source: Path, platform: str, version: str, output: Path) -> dict:
    if platform not in PORTS or not VERSION.fullmatch(version):
        raise ReleaseError('unsupported platform or unsafe version tag')
    source = _ordinary_root(Path(source), must_exist=True)
    output = _ordinary_root(Path(output), must_exist=False)
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ReleaseError('output must be fresh and separate from source')
    _guard(source)
    document, raw = _document(source)
    selected_port = PORTS[platform]
    other_port = PORTS['windows' if platform == 'linux' else 'linux']
    selected = {name: metadata for name, metadata in document['files'].items()
                if not name.startswith(other_port + '/')}
    if platform == 'windows':
        # This is Linux updater state, not a Windows implementation version.
        selected.pop('update-version.json', None)
    if not any(name.startswith(selected_port + '/') for name in selected):
        raise ReleaseError('manifest has no source files for selected platform')
    if any(name in selected for name in ('RELEASE_README.md', 'source-only-status.json')):
        raise ReleaseError('source already contains generated release-only files')
    # The user-facing filename describes the setup flow. Existing Linux update
    # clients require the original internal root and source filename, so retain
    # that root and publish a byte-identical compatibility alias on every release.
    if platform == 'linux':
        prefix = f'monado-ii-{version}-linux-source'
        filename = f'monado-ii-{version}-linux-setup.tar.gz'
        alias = prefix + '.tar.gz'
        implementation_version = version
        provenance = {}
        heading = f'# Monado II — Linux source/setup kit ({version})\n\n'
    else:
        prefix = WINDOWS_ROOT
        filename = WINDOWS_ARCHIVE
        alias = None
        implementation_version = WINDOWS_IMPLEMENTATION
        provenance = dict(source_release_version=version,
                          windows_implementation=WINDOWS_IMPLEMENTATION,
                          linux_feature_additions=False)
        heading = (
            '# Monado II — Windows original implementation source/setup kit\n\n'
            '**Original Windows implementation — no Linux feature additions.**\n\n'
            'The Windows implementation is unchanged. The containing GitHub release\n'
            'and source-snapshot provenance do not identify a Windows feature update.\n'
            'Linux launcher, gameplay additions and updates are not backported here.\n\n'
        )
    output.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.package-', dir=output) as temporary:
        temporary = Path(temporary)
        stage = temporary / 'source'
        stage.mkdir()
        for name, metadata in sorted(selected.items()):
            _copy_checked(source / name, stage / name, metadata)
        release_readme = (
            heading +
            'This is a source-only release, not a prebuilt playable game. Generate and\n'
            'compile your game executable locally using the accompanying build documentation.\n'
            'Packaging checks do not establish Windows/Linux runtime or full-game validation.\n\n'
            'No game files, game-derived generated code, translated game shaders, caches,\n'
            'keys, saves, compiled game binaries or proprietary SDK binaries are included.\n'
            'You must supply files you legally dumped yourself from your own legally obtained\n'
            'Nintendo Switch and your own legally obtained copy of the supported game.\n'
            'The project will not provide game files or tell you where to obtain them.\n'
            'No dumping, extraction, decryption or key-acquisition instructions are supplied.\n\n'
            'Keep all local input and generated/runtime data outside tracked source. Preserve\n'
            'the accompanying original-project attribution and component license notices.\n'
        ).encode('utf-8')
        status = encoded(dict(schema=1, project=PROJECT, platform=platform, version=implementation_version,
            kind='source-only', local_generation_required=True, contains_game_files=False,
            contains_game_derived_code=False, contains_compiled_binaries=False,
            runtime_validation='not performed by packaging', windows_backports='deferred', **provenance))
        for name, content in {'RELEASE_README.md': release_readme, 'source-only-status.json': status}.items():
            (stage / name).write_bytes(content)
            selected[name] = dict(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
        trimmed = {key: value for key, value in document.items() if key != 'files'}
        trimmed.update(platform=platform, release_version=implementation_version,
                       release_kind='source-only', files=selected, **provenance)
        (stage / MANIFEST).write_bytes(encoded(trimmed))
        _document(stage)
        _guard(stage)
        archive = temporary / filename
        _write_archive(stage, archive, prefix, platform)
        _verify_archive(archive, stage, temporary / 'readback', prefix, platform)
        final_document, final_raw = _document(source)
        _guard(source)
        if final_raw != raw or final_document != document:
            raise ReleaseError('source publication manifest changed during packaging')
        identity = digest(archive)
        aliases = []
        if alias:
            legacy = temporary / alias
            shutil.copyfile(archive, legacy)
            if legacy.stat().st_size != archive.stat().st_size or digest(legacy) != identity:
                raise ReleaseError('Linux compatibility alias differs from verified setup archive')
            aliases.append(dict(archive=alias, sha256=identity, bytes=legacy.stat().st_size))
        receipt = dict(schema=1, project=PROJECT, platform=platform, version=implementation_version,
            kind='source-only', archive=filename, sha256=identity, bytes=archive.stat().st_size,
            archive_aliases=aliases,
            source_manifest_sha256=hashlib.sha256(raw).hexdigest(),
            release_manifest_sha256=digest(stage / MANIFEST),
            archived_files=len(selected) + 1, archive_readback_verified=True,
            publication_guards='source, platform stage, archive readback, unchanged source',
            contains_game_files=False, contains_game_derived_code=False,
            contains_compiled_binaries=False, local_generation_required=True, **provenance)
        archive.replace(output / filename)
        for compatibility in aliases:
            (temporary / compatibility['archive']).replace(output / compatibility['archive'])
        (output / 'release-receipt.json').write_bytes(encoded(receipt))
        checksums = [identity + '  ' + filename]
        checksums.extend(item['sha256'] + '  ' + item['archive'] for item in aliases)
        (output / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n', encoding='ascii')
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--platform', choices=tuple(PORTS), required=True)
    parser.add_argument('--version', required=True,
                        help='Linux release/source-snapshot version; Windows implementation stays original')
    parser.add_argument('--output', type=Path, required=True, help='fresh ordinary output directory outside source')
    args = parser.parse_args(argv)
    try:
        receipt = package(args.source, args.platform, args.version, args.output)
    except (OSError, ReleaseError) as error:
        print('Source release rejected: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
