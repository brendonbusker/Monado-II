"""Current-only updater garbage collection; never select builds or touch profiles.

The trusted outer supervisor must hold exclusive installation/runtime maintenance
leases, reject legacy live users, and verify the selected runtime before calling.
Only recognized updater artifacts with reviewed ownership are deletion targets.
Original Python/dependency substrate and every profile remain outside cleanup.
A durable snapshot journal permits safe retry after partial deletion. Files added
or changed after authorization are preserved and reported as pending.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import uuid

ID = re.compile(r'(?:update|payload)-[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
MAX_JOURNAL = 128 * 1024 * 1024
MAX_NODES = 1_000_000
JOURNAL = 'retention-journal.json'
STATUS = 'retention-status.json'
ARTIFACTS = tuple(PurePosixPath('Monado_Linux') / x for x in
                  ('build', 'generated', '.deps', '.venv', 'runs/local-build'))
OUTER = frozenset(('transaction.json', 'payload.json', 'prepared.json', 'build.log',
                   'build.worker-console.log', 'workspace', 'download'))


def _ordinary(path, *, missing=False):
    path = Path(path).absolute()
    if '..' in path.parts or path.resolve() != path:
        raise ValueError('retention path contains links or traversal')
    for node in (*reversed(path.parents), path):
        try:
            info = node.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or (node != path and not stat.S_ISDIR(info.st_mode)):
            raise ValueError('retention path is not ordinary')
    return path


def _open_directory(path):
    """Open every component relative to an FD; never follow a raced parent link."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('directory traversal in retention path')
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _json(path, limit=MAX_JOURNAL):
    path = _ordinary(path)
    parent = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('unsafe or oversized retention metadata')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != info.st_size:
            raise ValueError('retention metadata changed while reading')
    finally:
        os.close(fd)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate retention metadata field')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('retention metadata must be an object')
    return value


def _sync(directory):
    fd = _open_directory(directory)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace(path, value):
    path = _ordinary(path, missing=True)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(raw) > MAX_JOURNAL:
        raise ValueError('retention journal exceeds its size limit')
    temporary = '.' + path.name + '-' + uuid.uuid4().hex + '.partial'
    directory = _open_directory(path.parent)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory)


def _snapshot(info):
    kind = 'd' if stat.S_ISDIR(info.st_mode) else 'f' if stat.S_ISREG(info.st_mode) else 'l' if stat.S_ISLNK(info.st_mode) else None
    if kind is None or (kind == 'f' and info.st_nlink != 1):
        raise ValueError('special or multiply-linked file in obsolete update')
    return [kind, info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode),
            info.st_nlink if kind != 'd' else 0, info.st_size if kind != 'd' else 0,
            info.st_mtime_ns if kind != 'd' else 0]


def _walk(root):
    """Metadata-only descriptor walk; symlinks are leaf entries, never followed."""
    root = _ordinary(root)
    top = root.lstat()
    if not stat.S_ISDIR(top.st_mode):
        raise ValueError('obsolete update must be an ordinary directory')
    device, owner = top.st_dev, top.st_uid
    nodes = {'.': _snapshot(top)}
    fd = _open_directory(root)
    if _snapshot(os.fstat(fd)) != nodes['.']:
        os.close(fd)
        raise ValueError('obsolete update root changed while opening')
    def visit(directory, prefix, depth):
        if depth > 128:
            raise ValueError('obsolete update nesting exceeds limit')
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = prefix / entry.name
                info = entry.stat(follow_symlinks=False)
                if info.st_dev != device or info.st_uid != owner:
                    raise ValueError('obsolete update crosses a mount or ownership boundary')
                nodes[relative.as_posix()] = _snapshot(info)
                if len(nodes) > MAX_NODES:
                    raise ValueError('obsolete update exceeds retention node limit')
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                    try:
                        opened = os.fstat(child)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise ValueError('obsolete update directory changed while scanning')
                        visit(child, relative, depth + 1)
                    finally:
                        os.close(child)
    try:
        visit(fd, PurePosixPath('.'), 0)
    finally:
        os.close(fd)
    return nodes


def _safe_relative(name):
    if not isinstance(name, str):
        raise ValueError('invalid retention journal relative path')
    path = PurePosixPath(name)
    if (path.is_absolute() or '..' in path.parts or
            path.as_posix() != name or not path.parts):
        raise ValueError('invalid retention journal relative path')
    return path


def _artifact(path):
    return any(path == base or path.is_relative_to(base) for base in ARTIFACTS)


def _workspace_allowed(nodes, manifest, prefix='workspace'):
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('obsolete workspace has no exact authored source manifest')
    known = {PurePosixPath(name) for name in files}
    known.add(PurePosixPath('publication-manifest.json'))
    extra = {PurePosixPath(x) for x in ('installation.json', 'Monado-II-x86_64.AppImage',
                                       'Monado-II-x86_64.AppImage.receipt.json')}
    directories = {PurePosixPath('.')}
    for path in known | extra | set(ARTIFACTS):
        directories.update(path.parents)
    for name, identity in nodes.items():
        path = PurePosixPath(name)
        if path == PurePosixPath(prefix):
            continue
        if not path.is_relative_to(prefix):
            continue
        relative = path.relative_to(prefix)
        if relative == PurePosixPath('game_files') and identity[0] == 'l':
            continue
        if _artifact(relative):
            continue
        if identity[0] == 'd' and relative in directories:
            continue
        if relative in known | extra and identity[0] == 'f':
            continue
        # Isolated launchers normally suppress bytecode; Python caches remain
        # derived source companions if an installed interpreter created them.
        if (relative.parent.name == '__pycache__' and relative.suffix == '.pyc' and
                relative.parent.parent in directories and identity[0] == 'f'):
            continue
        if identity[0] == 'd' and relative.name == '__pycache__' and relative.parent in directories:
            continue
        raise ValueError('unrecognized private or user file in obsolete workspace: ' + relative.as_posix())


@contextlib.contextmanager
def _regular_stream(path, maximum):
    path = _ordinary(path)
    parent = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError('unsafe or oversized staged extraction file')
        yield stream
        after = os.fstat(stream.fileno())
        if _snapshot(before) != _snapshot(after):
            raise ValueError('staged extraction file changed while checking')


def _stream_identity(stream):
    stream.seek(0)
    value = {'bytes': os.fstat(stream.fileno()).st_size,
             'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    stream.seek(0)
    return value


def _extraction_allowed(download, nodes, *, prefix='download/source'):
    """Authenticate exact staged source prefixes, without accepting them as code.

    New extractors durably declare all reviewed members before creating source/.
    The checked compressed archive and raw tar bind that declaration. Missing
    members and interrupted writes can be discarded; additions/changes cannot.
    """
    value = _json(download / 'extraction.json', 2 * 1024 * 1024)
    if (set(value) != {'schema', 'kind', 'version', 'archive', 'tar', 'files'} or
            type(value.get('schema')) is not int or value['schema'] != 1 or
            value.get('kind') != 'verified-source-extraction' or
            not isinstance(value.get('version'), str) or not VERSION.fullmatch(value['version'])):
        raise ValueError('invalid staged extraction ownership declaration')
    for name, limit in (('archive', 64 * 1024 * 1024), ('tar', 145 * 1024 * 1024)):
        identity = value[name]
        if (not isinstance(identity, dict) or set(identity) != {'bytes', 'sha256'} or
                type(identity.get('bytes')) is not int or not 0 < identity['bytes'] <= limit or
                not isinstance(identity.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', identity['sha256'])):
            raise ValueError('invalid staged archive identity')
    source_root = nodes.get(PurePosixPath(prefix).as_posix())
    if source_root is not None and source_root[0] != 'd':
        raise ValueError('partial source root is not an ordinary directory')
    files = value['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= 4097:
        raise ValueError('invalid declared source member count')
    directories = {PurePosixPath('.')}
    for name, identity in files.items():
        path = _safe_relative(name)
        if ('\\' in name or ':' in name or 'installation.json' in (part.casefold() for part in path.parts) or
                not isinstance(identity, dict) or set(identity) != {'bytes', 'sha256'} or
                type(identity.get('bytes')) is not int or not 0 <= identity['bytes'] <= 8 * 1024 * 1024 or
                not isinstance(identity.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', identity['sha256'])):
            raise ValueError('invalid declared source member identity')
        directories.update(path.parents)
    with _regular_stream(download / 'source.tar.gz', 64 * 1024 * 1024) as compressed:
        if _stream_identity(compressed) != value['archive']:
            raise ValueError('staged compressed archive differs from extraction declaration')
    root = 'monado-ii-' + value['version'] + '-linux-source/'
    with _regular_stream(download / 'archive.tar', 145 * 1024 * 1024) as raw:
        if _stream_identity(raw) != value['tar']:
            raise ValueError('staged raw archive differs from extraction declaration')
        with tarfile.open(fileobj=raw, mode='r:', ignore_zeros=True) as archive:
            members = {}
            for member in archive:
                if (not member.isfile() or member.sparse is not None or not member.name.startswith(root)
                        or len(members) >= 4097):
                    raise ValueError('staged raw archive has unexpected members')
                name = member.name[len(root):]
                if name not in files or name in members or member.size != files[name]['bytes']:
                    raise ValueError('staged raw archive differs from declared members')
                members[name] = member
            if set(members) != set(files):
                raise ValueError('staged raw archive has missing declared members')
            for name, identity in nodes.items():
                path = PurePosixPath(name)
                if not path.is_relative_to(prefix) or path == PurePosixPath(prefix):
                    continue
                relative = path.relative_to(prefix)
                if identity[0] == 'd' and relative in directories:
                    continue
                declared = files.get(relative.as_posix())
                if identity[0] != 'f' or declared is None or identity[6] > declared['bytes']:
                    raise ValueError('unrecognized file in partial source extraction: ' + relative.as_posix())
                with _regular_stream(download / 'source' / relative, 8 * 1024 * 1024) as actual:
                    with archive.extractfile(members[relative.as_posix()]) as expected:
                        remaining = identity[6]
                        while remaining:
                            data = actual.read(min(1024 * 1024, remaining))
                            if not data or data != expected.read(len(data)):
                                raise ValueError('partial source member changed: ' + relative.as_posix())
                            remaining -= len(data)
                        if actual.read(1):
                            raise ValueError('partial source member grew while checking')


def _owned(root, owner, verify_workspace):
    name = root.name
    if not ID.fullmatch(name):
        raise ValueError('not an updater-owned transaction name')
    if name.startswith('payload-'):
        value = _json(root / 'payload.json', 16384)
        if type(value.get('schema')) is not int or value != {'schema': 1, 'kind': 'game-payload', 'owner': str(owner),
                     'id': name, 'workspace': 'workspace'}:
            raise ValueError('invalid game payload ownership marker')
    else:
        value = _json(root / 'transaction.json', 16384)
        if (set(value) != {'schema', 'status', 'version', 'previous'} or
                type(value.get('schema')) is not int or value['schema'] != 1 or
                value.get('status') != 'staging' or not isinstance(value.get('version'), str) or
                not VERSION.fullmatch(value['version']) or value['previous'] is not None and not isinstance(value['previous'], dict)):
            raise ValueError('invalid updater transaction ownership marker')
    info, parent = root.stat(), root.parent.stat()
    if (info.st_dev, info.st_uid) != (parent.st_dev, parent.st_uid):
        raise ValueError('obsolete update crosses a mount or ownership boundary')
    nodes = _walk(root)
    for name in nodes:
        relative = PurePosixPath(name)
        if name != '.' and relative.parts[0] not in OUTER:
            raise ValueError('unrecognized file in updater transaction: ' + name)
        if len(relative.parts) == 1 and name != '.':
            expected = 'd' if name in ('workspace', 'download') else 'f'
            if nodes[name][0] != expected:
                raise ValueError('unexpected transaction companion type: ' + name)
    workspace = root / 'workspace'
    if workspace.exists():
        manifest = verify_workspace(workspace)
        _workspace_allowed(nodes, manifest)
    download = root / 'download'
    if download.exists():
        for child in download.iterdir():
            if child.name not in ('source.tar.gz', 'source.tar.gz.partial', 'archive.tar', 'source',
                                  'extraction.json', 'extraction.json.partial'):
                raise ValueError('unrecognized updater download file')
            if child.name == 'source':
                if (download / 'extraction.json').exists():
                    _extraction_allowed(download, nodes)
                else:
                    manifest = verify_workspace(child)
                    _workspace_allowed(nodes, manifest, prefix='download/source')
            elif not child.is_file() or child.is_symlink():
                raise ValueError('unsafe updater download archive')
        if (download / 'extraction.json').exists() and not (download / 'source').exists():
            _extraction_allowed(download, nodes)
    return nodes


def _victim(directory, relative, scope='transaction'):
    path = _safe_relative(relative)
    if scope == 'transaction' and len(path.parts) == 1 and ID.fullmatch(path.name):
        root = directory / relative
    elif scope == 'bootstrap' and relative in ('build', 'generated'):
        root = directory.parent / relative
    elif scope == 'download' and len(path.parts) == 2 and ID.fullmatch(path.parts[0]) and path.parts[1] == 'download':
        root = directory / relative
    else:
        raise ValueError('retention journal escaped owned cleanup roots')
    return _ordinary(root, missing=True)


def _bootstrap_owned(root, owner, verify_workspace):
    verify_workspace(owner)
    info, parent = root.stat(), root.parent.stat()
    if (info.st_dev, info.st_uid) != (parent.st_dev, parent.st_uid):
        raise ValueError('bootstrap artifact crosses a mount or ownership boundary')
    nodes = _walk(root)
    # Local build identities are emitted by the reviewed builder, not arbitrary
    # user directories. Refuse unexpected siblings rather than treating a whole
    # source checkout as disposable. Profiles/caches have separate roots.
    pattern = (r'local-\d{8}T\d{6}Z-[a-f0-9]{8}(?:-game|-launcher|-appimage)'
               if root.name == 'build' else r'local-\d{8}T\d{6}Z-[a-f0-9]{8}')
    for name, identity in nodes.items():
        if name == '.':
            continue
        relative = PurePosixPath(name)
        if not re.fullmatch(pattern, relative.parts[0]):
            raise ValueError('unrecognized bootstrap build identity: ' + relative.parts[0])
        if len(relative.parts) == 1 and identity[0] != 'd':
            raise ValueError('bootstrap artifact identity is not a directory')
        if any(part in ('play', 'save', 'saves', 'mods') for part in relative.parts):
            raise ValueError('private profile content in obsolete bootstrap output')
    return nodes


def _download_owned(root):
    info, parent = root.stat(), root.parent.stat()
    if (info.st_dev, info.st_uid) != (parent.st_dev, parent.st_uid):
        raise ValueError('download root crosses a mount or ownership boundary')
    nodes = _walk(root)
    for name, identity in nodes.items():
        if name == '.':
            continue
        if name not in ('source.tar.gz', 'source.tar.gz.partial', 'archive.tar',
                        'extraction.json', 'extraction.json.partial') or identity[0] != 'f':
            raise ValueError('unrecognized current download companion')
    if (root / 'extraction.json').exists():
        _extraction_allowed(root, nodes, prefix='source')
    return nodes


def _protected(root, current, retained_ports, live_roots):
    if root == current:
        return True
    for value in retained_ports:
        path = Path(value).absolute()
        # An original game port contains updates/ lexically, but does not own
        # their build outputs. Protect its actual build/generated siblings only.
        if path == root or path.is_relative_to(root) or (root.parent == path and root.name in ('build', 'generated')):
            return True
    for value in live_roots:
        path = Path(value).absolute()
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            return True
    return False


def _resume(directory, document):
    """Unlink only snapshotted nodes; additions/changes survive for inspection."""
    if set(document) != {'schema', 'owner', 'victim', 'scope', 'current_id', 'nodes'} or type(document['schema']) is not int or document['schema'] != 1:
        raise ValueError('unsupported retention deletion journal')
    root = _victim(directory, document['victim'], document['scope'])
    planned = document['nodes']
    if not isinstance(planned, dict) or not 1 <= len(planned) <= MAX_NODES or '.' not in planned:
        raise ValueError('invalid retention snapshot')
    for name, value in planned.items():
        if name != '.':
            _safe_relative(name)
        if (not isinstance(value, list) or len(value) != 8 or value[0] not in ('d', 'f', 'l') or
                any(type(item) is not int for item in value[1:])):
            raise ValueError('invalid retention node snapshot')
    if not root.exists():
        return
    actual = _walk(root)
    for name, identity in actual.items():
        if planned.get(name) != identity:
            raise ValueError('obsolete update acquired new or changed files; cleanup deferred: ' + name)
    parent = _open_directory(root.parent)
    try:
        for name in sorted(actual, key=lambda value: len(PurePosixPath(value).parts), reverse=True):
            components = () if name == '.' else PurePosixPath(name).parts
            fd = os.dup(parent)
            try:
                ancestors = (root.name, *components[:-1]) if components else ()
                for index, component in enumerate(ancestors):
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    os.close(fd); fd = child
                    ancestor = '.' if index == 0 else PurePosixPath(*components[:index]).as_posix()
                    if _snapshot(os.fstat(fd)) != planned[ancestor]:
                        raise ValueError('obsolete update ancestor changed during deletion: ' + ancestor)
                leaf = components[-1] if components else root.name
                try:
                    current = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if _snapshot(current) != planned[name]:
                    raise ValueError('obsolete update changed during deletion: ' + name)
                if planned[name][0] == 'd':
                    os.rmdir(leaf, dir_fd=fd)
                else:
                    os.unlink(leaf, dir_fd=fd)
            finally:
                os.close(fd)
        os.fsync(parent)
    finally:
        os.close(parent)


def cleanup(owner, current_record=None, *, verify_workspace, retained_ports=(), live_roots=(), include_bootstrap=False):
    """Prune inactive owned versions/payloads under caller-held maintenance leases.

    The caller must independently validate the active image/runtime, retire obsolete
    bridge/previous references and exclude legacy users before entering this API.
    With current_record=None the checked original installation remains current;
    only abandoned managed attempts are eligible, never original build output.
    No ownership blessing, executable loading, profile access or process control.
    """
    owner = _ordinary(owner)
    directory = _ordinary(owner / 'Monado_Linux/updates')
    selected = directory / 'active.json'
    retained_ports = tuple(retained_ports)
    live_roots = tuple(live_roots)
    def selection_unchanged():
        present = selected.exists() or selected.is_symlink()
        if current_record is None:
            if present:
                raise ValueError('active selection appeared during bootstrap retention')
        elif not present or _json(selected, 16384) != current_record:
            raise ValueError('current selection changed before retention')
    selection_unchanged()
    if current_record is None:
        # An ordinary fresh installation has no managed active selection yet.
        # Its original build is the working program, never an obsolete target.
        current_id, current = 'bootstrap', owner
        include_bootstrap = False
        retained_ports += (owner / 'Monado_Linux',)
        verify_workspace(owner)
    else:
        current_id = current_record.get('id')
        if not isinstance(current_id, str) or not ID.fullmatch(current_id):
            raise ValueError('invalid current retention selection')
        current = _ordinary(directory / current_id)
        if current_record.get('workspace') != (current / 'workspace').relative_to(owner).as_posix():
            raise ValueError('current selection escaped its transaction')
        verify_workspace(current / 'workspace')
    selection_unchanged()
    report = {'schema': 1, 'owner': str(owner), 'current_id': current_id,
              'status': 'complete', 'removed': [], 'pending': []}
    journal = directory / JOURNAL
    def pending(name, error):
        report['status'] = 'pending'
        report['pending'].append({'id': name, 'reason': str(error)[:512]})
    if journal.exists() or journal.is_symlink():
        try:
            document = _json(journal)
            if document.get('owner') != str(owner):
                raise ValueError('retention journal belongs to another installation')
            root = _victim(directory, document.get('victim'), document.get('scope'))
            if _protected(root, current, retained_ports, live_roots):
                raise ValueError('pending cleanup target is now current or in use')
            selection_unchanged()
            _resume(directory, document)
            report['removed'].append(document['victim'])
            journal.unlink(); _sync(directory)
        except (OSError, ValueError) as error:
            pending('journal', error)
            _replace(directory / STATUS, report)
            return report
    candidates = [(root, 'transaction', root.name) for root in sorted(directory.iterdir())
                  if ID.fullmatch(root.name)]
    if include_bootstrap:
        candidates += [(directory.parent / name, 'bootstrap', name) for name in ('generated', 'build')]
    if current_record is not None:
        candidates.append((current / 'download', 'download', current.name + '/download'))
    for port in retained_ports:
        port = Path(port)
        payload = port.parent.parent
        if payload.parent != directory or not payload.name.startswith('payload-'):
            continue
        try:
            marker = _json(payload / 'payload.json', 16384)
            if type(marker.get('schema')) is not int or marker != {
                    'schema': 1, 'kind': 'game-payload', 'owner': str(owner),
                    'id': payload.name, 'workspace': 'workspace'}:
                raise ValueError('retained payload has an invalid ownership marker')
            verify_workspace(payload / 'workspace')
            candidates.append((payload / 'download', 'download', payload.name + '/download'))
        except (OSError, ValueError) as error:
            pending(payload.name + '/download', error)
    for root, scope, relative in candidates:
        if not (root.exists() or root.is_symlink()):
            continue
        if _protected(root, current, retained_ports, live_roots):
            if not _protected(root, current, retained_ports, ()):
                pending(relative, 'obsolete update is still in use')
            continue
        try:
            selection_unchanged()
            root = _ordinary(root)
            if scope == 'transaction':
                nodes = _owned(root, owner, verify_workspace)
            elif scope == 'bootstrap':
                nodes = _bootstrap_owned(root, owner, verify_workspace)
            else:
                nodes = _download_owned(root)
            document = {'schema': 1, 'owner': str(owner), 'victim': relative, 'scope': scope,
                        'current_id': current_id, 'nodes': nodes}
            selection_unchanged()
            _replace(journal, document)
            selection_unchanged()
            _resume(directory, document)
            report['removed'].append(relative)
            journal.unlink(); _sync(directory)
        except (OSError, ValueError) as error:
            pending(relative, error)
            if journal.exists() or journal.is_symlink():
                break  # Retain one exact interrupted authorization for safe retry.
    report['removed'] = report['removed'][-32:]
    report['pending'] = report['pending'][-32:]
    _replace(directory / STATUS, report)
    return report
