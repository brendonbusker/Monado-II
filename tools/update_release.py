#!/usr/bin/env python3
"""Trusted, bounded source-release checks for Monado II's local Linux updater.

This module never executes downloaded code, obtains game input, modifies an
installation, or activates a build. The outer updater owns those separate steps.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zlib

from publication_guard import MAX_FILE, path_problem, read_regular, verify_tree

REPOSITORY = 'brendonbusker/Monado-II'
LATEST_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
HOSTS = frozenset(('api.github.com', 'github.com', 'release-assets.githubusercontent.com',
                   'objects.githubusercontent.com'))
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXTRACTED = 128 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_TAR = MAX_EXTRACTED + MAX_MEMBERS * 4096 + 1024 * 1024
MAX_METADATA = 2 * 1024 * 1024
CHUNK = 1024 * 1024
MANIFEST = 'publication-manifest.json'
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


class UpdateError(ValueError):
    """The release is unavailable, malformed or unsafe to stage."""


class UpdateCancelled(UpdateError):
    """The owner requested cancellation between bounded operations."""


def _version(value):
    if not isinstance(value, str) or len(value) > 64 or not VERSION.fullmatch(value):
        raise UpdateError('unsupported stable version')
    return tuple(map(int, value.split('.')))


def _url(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise UpdateError('invalid official release URL')
    try:
        parsed = urllib.parse.urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname in HOSTS and not parsed.username
                 and not parsed.password and parsed.port in (None, 443) and not parsed.fragment)
    except ValueError as error:
        raise UpdateError('invalid official release URL') from error
    if not valid:
        raise UpdateError('release URL is not an allowed official HTTPS endpoint')
    return value


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        _url(newurl)  # Check before urllib contacts the redirect destination.
        return super().redirect_request(request, response, code, message, headers, newurl)


def _open(url, opener):
    _url(url)
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Monado-II-source-updater/1',
        'Accept': 'application/vnd.github+json' if url == LATEST_URL else 'application/octet-stream',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    if opener is None:
        opener = urllib.request.build_opener(_Redirect()).open
    elif not callable(opener):
        opener = opener.open
    response = opener(request, timeout=30)
    try:
        _url(response.geturl())
        if response.getcode() != 200:
            raise UpdateError('official release request did not return HTTP 200')
        return response
    except BaseException:
        response.close()
        raise


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise UpdateError('duplicate release metadata key')
            result[key] = value
        return result

    def nonfinite(value):
        raise UpdateError('nonfinite release metadata value')

    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise UpdateError('invalid release JSON') from error
    if not isinstance(result, dict):
        raise UpdateError('release metadata must be an object')
    return result


def _archive_name(version, *, legacy=False):
    _version(version)
    kind = 'source' if legacy else 'setup'
    return 'monado-ii-' + version + '-linux-' + kind + '.tar.gz'


def _offer(offer):
    if not isinstance(offer, dict):
        raise UpdateError('invalid release offer')
    version = offer.get('version')
    names = (_archive_name(version), _archive_name(version, legacy=True))
    base = 'https://github.com/' + REPOSITORY + '/releases/download/v' + version + '/'
    matches = [name for name in names if offer.get('archive_url') == base + name]
    if (offer.get('tag') != 'v' + version or len(matches) != 1
            or not isinstance(offer.get('archive_sha256'), str)
            or not SHA256.fullmatch(offer['archive_sha256'])
            or type(offer.get('archive_bytes')) is not int
            or not 0 < offer['archive_bytes'] <= MAX_ARCHIVE):
        raise UpdateError('invalid pinned source-release offer')
    _url(offer['archive_url'])
    return version, matches[0]


def discover(current_version, *, opener=None):
    """Return the newer stable official setup kit, or None when up to date.

    GitHub's API digest binds the archive to the HTTPS release metadata. Missing
    asset digests fail closed; this is not an independent publisher signature.
    """
    current = _version(current_version)
    try:
        with _open(LATEST_URL, opener) as response:
            raw = response.read(MAX_METADATA + 1)
        if len(raw) > MAX_METADATA:
            raise UpdateError('oversized release metadata')
        document = _json(raw)
        tag = document.get('tag_name')
        if (document.get('draft') is not False or document.get('prerelease') is not False
                or not isinstance(tag, str) or not tag.startswith('v')):
            raise UpdateError('latest release is not a supported stable release')
        version = tag[1:]
        latest = _version(version)
        if latest <= current:
            return None
        assets = document.get('assets')
        if not isinstance(assets, list) or len(assets) > 32 or any(not isinstance(a, dict) for a in assets):
            raise UpdateError('invalid release asset list')
        canonical = [a for a in assets if a.get('name') == _archive_name(version)]
        legacy = [a for a in assets if a.get('name') == _archive_name(version, legacy=True)]
        if len(canonical) > 1 or len(legacy) > 1 or not (canonical or legacy):
            raise UpdateError('release needs an unambiguous Linux setup-kit asset')
        # A malformed canonical asset must fail closed instead of silently using
        # the compatibility alias. Older releases have only the legacy name.
        asset = (canonical or legacy)[0]
        digest = asset.get('digest')
        if (asset.get('state') != 'uploaded' or not isinstance(digest, str)
                or not digest.startswith('sha256:')):
            raise UpdateError('release asset has no verified SHA-256 digest')
        offer = dict(version=version, tag=tag, archive_url=asset.get('browser_download_url'),
                     archive_sha256=digest[7:], archive_bytes=asset.get('size'))
        _, selected_name = _offer(offer)
        if selected_name != asset['name']:
            raise UpdateError('release asset name and official URL differ')
        return offer
    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
        raise UpdateError('could not check the official release: ' + str(error)) from error


def _cancel(cancel):
    if cancel is not None and cancel():
        raise UpdateCancelled('source update cancelled; active installation is unchanged')


def _progress(callback, phase, count, total):
    if callback is not None:
        callback(dict(phase=phase, bytes=count, total=total))


def _fresh_destination(destination):
    destination = Path(destination).absolute()
    if destination.resolve() != destination or destination.exists() or destination.is_symlink():
        raise UpdateError('update staging must be a fresh canonical directory')
    if not destination.parent.is_dir():
        raise UpdateError('update staging parent must already exist')
    destination.mkdir(mode=0o700)
    return destination


def _relative(name):
    if (not isinstance(name, str) or path_problem(name) or name == 'installation.json'
            or any(part.casefold() == 'installation.json' for part in name.split('/'))):
        raise UpdateError('unsafe or reserved source archive path: ' + str(name))
    return PurePosixPath(name)


def verified_source(root):
    """Verify an untouched clean public source tree using installed guard code."""
    root = Path(root).absolute()
    problems = verify_tree(root)
    if problems:
        raise UpdateError('source publication guard rejected candidate: ' + '; '.join(problems))
    document = _json(read_regular(root / MANIFEST))
    if document.get('source_only') is not True or document.get('platform') not in (None, 'linux'):
        raise UpdateError('candidate must be a Linux-compatible source-only tree')
    for name in document['files']:
        _relative(name)
    return document


def _extraction_declaration(destination, offer, raw_tar, identities):
    """Durably declare owned source members before any partial extraction exists.

    This receipt only authorizes later deletion of exact archive bytes/prefixes;
    it never authorizes execution or treats incomplete source as a valid release.
    """
    archive = destination / 'source.tar.gz'
    def identity(path):
        with path.open('rb') as stream:
            return {'bytes': path.stat().st_size,
                    'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    compressed = identity(archive)
    if compressed != {'bytes': offer['archive_bytes'], 'sha256': offer['archive_sha256']}:
        raise UpdateError('source archive changed before extraction declaration')
    value = {'schema': 1, 'kind': 'verified-source-extraction', 'version': offer['version'],
             'archive': compressed, 'tar': identity(raw_tar), 'files': identities}
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(raw) > MAX_METADATA:
        raise UpdateError('extraction ownership declaration exceeds its bound')
    temporary = destination / 'extraction.json.partial'
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(destination / 'extraction.json')
    if os.name != 'nt':
        directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _unpack(archive_path, destination, offer, progress, cancel):
    version, _ = _offer(offer)
    # Retain this archive root for installed 0.1.3/0.1.4 clients, including users
    # who skip a transition release. The setup filename does not change content.
    prefix = 'monado-ii-' + version + '-linux-source/'
    raw_tar = destination / 'archive.tar'
    total = 0
    with gzip.open(archive_path, 'rb') as incoming, raw_tar.open('xb') as outgoing:
        while True:
            _cancel(cancel)
            block = incoming.read(min(CHUNK, MAX_TAR - total + 1))
            if not block:
                break
            total += len(block)
            if total > MAX_TAR:
                raise UpdateError('decompressed source archive exceeds its limit')
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    source = destination / 'source'
    with tarfile.open(raw_tar, 'r:', ignore_zeros=True) as archive:
        members, folded, directories, components = {}, set(), set(), {}
        expanded = 0
        for member in archive:
            _cancel(cancel)
            if (len(members) >= MAX_MEMBERS or not member.isfile() or member.sparse is not None
                    or not member.name.startswith(prefix)):
                raise UpdateError('unexpected archive root, member type or member count')
            name = member.name[len(prefix):]
            _relative(name)
            if (name in members or name.casefold() in folded or member.size < 0
                    or member.size > MAX_FILE or member.mode != (0o755 if name.endswith('.sh') else 0o644)):
                raise UpdateError('duplicate, colliding, oversized or noncanonical archive member')
            parents = [str(p) for p in PurePosixPath(name).parents if str(p) != '.']
            if name in directories or any(parent in members for parent in parents):
                raise UpdateError('archive file/directory paths collide')
            for component in [name, *parents]:
                prior = components.setdefault(component.casefold(), component)
                if prior != component:
                    raise UpdateError('archive path components collide by case')
            directories.update(parents)
            expanded += member.size
            if expanded > MAX_EXTRACTED:
                raise UpdateError('expanded source files exceed their limit')
            members[name] = member
            folded.add(name.casefold())
        if MANIFEST not in members:
            raise UpdateError('source archive has no publication manifest')
        with archive.extractfile(members[MANIFEST]) as stream:
            raw = stream.read(MAX_FILE + 1)
        document = _json(raw)
        if (document.get('schema') != 1 or type(document.get('schema')) is not int
                or document.get('project') != 'Monado II' or document.get('platform') != 'linux'
                or document.get('release_version') != version or document.get('release_kind') != 'source-only'
                or document.get('source_only') is not True or not isinstance(document.get('files'), dict)):
            raise UpdateError('archive manifest is not the selected Linux source release')
        identities = dict(document['files'])
        if MANIFEST in identities or set(members) != set(identities) | {MANIFEST}:
            raise UpdateError('archive files differ from the source manifest')
        identities[MANIFEST] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        for name, identity in identities.items():
            _relative(name)
            if (not isinstance(identity, dict) or type(identity.get('bytes')) is not int
                    or identity['bytes'] != members[name].size or not isinstance(identity.get('sha256'), str)
                    or not SHA256.fullmatch(identity['sha256'])):
                raise UpdateError('invalid archive manifest identity')
        _extraction_declaration(destination, offer, raw_tar, identities)
        source.mkdir(mode=0o700)
        count = 0
        for name, identity in identities.items():
            _cancel(cancel)
            target = source.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            hasher, length = hashlib.sha256(), 0
            with archive.extractfile(members[name]) as incoming, target.open('xb') as outgoing:
                while True:
                    _cancel(cancel)
                    block = incoming.read(min(CHUNK, identity['bytes'] - length + 1))
                    if not block:
                        break
                    length += len(block)
                    if length > identity['bytes']:
                        raise UpdateError('archive member exceeds its manifest size')
                    hasher.update(block)
                    outgoing.write(block)
            if length != identity['bytes'] or hasher.hexdigest() != identity['sha256']:
                raise UpdateError('archive member differs from its manifest identity')
            target.chmod(0o755 if name.endswith('.sh') else 0o644)
            count += length
            _progress(progress, 'extract', count, expanded)
    verified_source(source)
    status = _json(read_regular(source / 'source-only-status.json'))
    if (type(status.get('schema')) is not int or status.get('schema') != 1 or status.get('project') != 'Monado II'
            or status.get('platform') != 'linux' or status.get('version') != version
            or status.get('kind') != 'source-only' or status.get('local_generation_required') is not True
            or any(status.get(key) is not False for key in
                   ('contains_game_files', 'contains_game_derived_code', 'contains_compiled_binaries'))):
        raise UpdateError('candidate source-kit status differs from the selected release')
    metadata = _json(read_regular(source / 'update-version.json'))
    if (type(metadata.get('schema')) is not int or metadata['schema'] != 1
            or type(metadata.get('protocol')) is not int or metadata['protocol'] != 1
            or metadata.get('version') != version):
        raise UpdateError('candidate update protocol/version is unsupported')
    _cancel(cancel)
    return source


def fetch_and_extract(offer, destination, *, opener=None, progress=None, cancel=None):
    """Download and validate only source bytes under a fresh staging directory."""
    _offer(offer)
    _cancel(cancel)
    destination = _fresh_destination(destination)
    partial = destination / 'source.tar.gz.partial'
    count, hasher = 0, hashlib.sha256()
    try:
        with _open(offer['archive_url'], opener) as incoming, partial.open('xb') as outgoing:
            while True:
                _cancel(cancel)
                block = incoming.read(min(CHUNK, offer['archive_bytes'] - count + 1))
                if not block:
                    break
                count += len(block)
                if count > offer['archive_bytes']:
                    raise UpdateError('download exceeds the pinned release size')
                hasher.update(block)
                outgoing.write(block)
                _progress(progress, 'download', count, offer['archive_bytes'])
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if count != offer['archive_bytes'] or hasher.hexdigest() != offer['archive_sha256']:
            raise UpdateError('download differs from the official release identity')
        archive = destination / 'source.tar.gz'
        partial.rename(archive)
        return _unpack(archive, destination, offer, progress, cancel)
    except UpdateError:
        raise
    except (OSError, ValueError, tarfile.TarError, EOFError, zlib.error,
            urllib.error.URLError, http.client.HTTPException) as error:
        raise UpdateError('source release could not be staged: ' + str(error)) from error


LAUNCHER_FILES = frozenset((
    'README.md', 'CHANGELOG.md', 'CREDITS.md', 'CONTRIBUTING.md', 'LICENSE', 'NOTICE.md', 'TODO.md',
    'RELEASE_README.md', 'source-only-status.json', 'publication-policy.json', 'update-version.json',
    'Play_Monado_II.sh', 'tools/update_release.py', 'tools/update_linux.py', 'tools/update_retention.py',
    'Monado_Linux/scripts/install_lease.py', 'tests/test_install_lease.py', 'tests/test_update_retention.py',
    'tools/build_launcher_appimage.py', 'tests/test_update_release.py', 'tests/test_update_linux.py',
    'Monado_Linux/scripts/build_launcher_linux.py', 'Monado_Linux/scripts/launcher_linux.py',
))


def _files(document):
    if not isinstance(document, dict) or not isinstance(document.get('files'), dict):
        raise UpdateError('classification requires a source manifest')
    result = {}
    for name, identity in document['files'].items():
        _relative(name)
        if (not isinstance(identity, dict) or not isinstance(identity.get('sha256'), str)
                or not SHA256.fullmatch(identity['sha256']) or type(identity.get('bytes')) is not int
                or not 0 <= identity['bytes'] <= MAX_FILE):
            raise UpdateError('classification manifest has an invalid source identity')
        if not name.startswith('Monado_Windows/'):
            result[name] = identity['sha256'], identity['bytes']
    return result


def classify(installed_manifest, candidate_manifest):
    """Return launcher only when every changed path is explicitly presentation-only."""
    installed, candidate = _files(installed_manifest), _files(candidate_manifest)
    for name in installed.keys() | candidate.keys():
        if installed.get(name) == candidate.get(name):
            continue
        if (name in LAUNCHER_FILES or name.startswith('Monado_Linux/tools/launcher/')
                or name.startswith('tools/appimage/')
                or (name.startswith('docs/') and name.endswith('.md'))):
            continue
        return 'game'
    return 'launcher'
