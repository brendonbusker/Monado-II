"""Reconnect a moved, verified dump without changing a game receipt or profile.

The native receipt identifies the exact executable and ExeFS inventory. RomFS is
checked by the existing supported-version/layout checker, not a whole-file hash.
Only three explicitly bound workspaces can be repaired; this never scans other
installations, moves input files, or creates/writes save and settings files.
"""
import contextlib
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

if sys.platform == 'linux':
    import fcntl
else:
    fcntl = None


def _sibling(name):
    spec = importlib.util.spec_from_file_location('_input_location_' + name,
                                                 Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


layout = _sibling('install_layout')
lease = _sibling('install_lease')
MAX_JSON = 4 * 1024 * 1024
MAX_GAME_RECEIPT = 64 * 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')
ACTIVE = 'input-relocation.json'
COMPLETED = 'input-location.json'


class InputLocationError(ValueError):
    pass


class InputMissing(InputLocationError):
    pass


def _cancelled(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise InterruptedError('Locating game files was cancelled; no saves were changed')


def _point(failpoint, name):
    if failpoint is not None:
        failpoint(name)


def _absolute(value):
    if (not isinstance(value, str) or not value or not Path(value).is_absolute()
            or '..' in Path(value).parts or str(Path(value)) != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise InputLocationError('input locations must be absolute normalized paths')
    return Path(value)


def _dir(path):
    return layout.canonical(path, directory=True)


def _identity(info):
    return [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_uid, info.st_nlink]


def _read_json(path, *, optional=False, limit=MAX_JSON):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise InputLocationError('missing successful game build receipt: ' + str(path)) from None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or not 0 < info.st_size <= limit):
        raise InputLocationError('metadata must be an owned ordinary bounded file: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after, named = os.fstat(fd), path.lstat()
        signature = lambda item: (_identity(item), item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if not signature(info) == signature(before) == signature(after) == signature(named):
            raise InputLocationError('metadata changed while being read')
    finally:
        os.close(fd)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InputLocationError('duplicate metadata field')
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, ValueError) as error:
        raise InputLocationError('invalid relocation/build metadata: ' + str(error)) from error
    if not isinstance(value, dict):
        raise InputLocationError('metadata must be a JSON object')
    return value


def _digest(path, cancel=None, *, allow_hardlinks=False):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (not allow_hardlinks and info.st_nlink != 1):
        raise InputLocationError('expected an ordinary input file or single-link executable: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    result = hashlib.sha256()
    try:
        before = os.fstat(fd)
        if _identity(before) != _identity(info):
            raise InputLocationError('file changed before hashing: ' + str(path))
        while True:
            _cancelled(cancel)
            data = os.read(fd, 1024 * 1024)
            if not data:
                break
            result.update(data)
        signature = lambda item: (_identity(item), item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if not signature(info) == signature(os.fstat(fd)) == signature(path.lstat()):
            raise InputLocationError('file changed while hashing: ' + str(path))
    finally:
        os.close(fd)
    return result.hexdigest()


def _context(port, game, *, verify=False, cancel=None):
    port = _dir(port)
    binding = layout.binding(port)
    binary = layout.canonical(game)
    game_port = layout.build_port(port, binary)
    receipt_path = binary.parent / 'receipt.json'
    receipt = _read_json(receipt_path, limit=MAX_GAME_RECEIPT)
    accepted = receipt.get('executable', {})
    expected = receipt.get('input', {})
    if not isinstance(expected, dict):
        raise InputLocationError('selected game receipt has no valid input identity')
    inventory = expected.get('exefs')
    if (receipt.get('status') != 'passed' or receipt.get('artifact_kind') == 'linux-launcher'
            or not receipt.get('generated') or not isinstance(accepted, dict)
            or accepted.get('path') != str(binary) or not HEX.fullmatch(str(accepted.get('sha256', '')))
            or not isinstance(inventory, dict) or not inventory):
        raise InputLocationError('selected game needs a complete successful native game receipt')
    for name, digest in inventory.items():
        if (not isinstance(name, str) or not name or name in ('.', '..')
                or '/' in name or '\\' in name or any(ord(char) < 32 or ord(char) == 127 for char in name)
                or not isinstance(digest, str) or not HEX.fullmatch(digest)):
            raise InputLocationError('invalid receipted ExeFS inventory')
    previous = _absolute(expected.get('path'))
    if verify:
        if _digest(binary, cancel) != accepted['sha256']:
            raise InputLocationError('game executable differs from its successful receipt')
        with binary.open('rb') as stream:
            header = stream.read(64)
        if (len(header) != 64 or header[:6] != b'\x7fELF\x02\x01'
                or int.from_bytes(header[18:20], 'little') != 62
                or not os.access(binary, os.X_OK)):
            raise InputLocationError('selected game must be an executable Linux x86-64 ELF')
    owner = binding['owner']
    workspaces = tuple(dict.fromkeys((owner, port.parent, game_port.parent)))
    for workspace in workspaces:
        _dir(workspace)
    metadata = owner / 'Monado_Linux/.deps/metadata'
    # A completed transaction is provenance for subsequent moves, never a
    # runtime alias and never a replacement for the native immutable receipt.
    if (metadata.parent.exists() or metadata.parent.is_symlink()):
        _dir(metadata.parent)
    if metadata.exists() or metadata.is_symlink():
        _dir(metadata)
    completed = _read_json(metadata / COMPLETED, optional=True) if metadata.exists() else None
    receipt_sha = _digest(receipt_path, cancel)
    if completed is not None:
        _validate_completed(completed, owner)
        if (completed['game_receipt_sha256'] == receipt_sha and completed['exefs'] == inventory):
            previous = _absolute(completed['input'])
    return {'port': port, 'game': binary, 'owner': owner, 'game_port': game_port,
            'workspaces': workspaces, 'receipt_sha': receipt_sha, 'exefs': inventory,
            'previous': previous, 'receipt_input': _absolute(expected['path']),
            'metadata': metadata, 'completed': completed}


def _validate_completed(value, owner):
    if (set(value) != {'schema', 'owner', 'input', 'game_receipt_sha256', 'exefs'}
            or type(value['schema']) is not int or value['schema'] != 1
            or value['owner'] != str(owner) or not isinstance(value['exefs'], dict)
            or not HEX.fullmatch(str(value['game_receipt_sha256']))):
        raise InputLocationError('invalid completed input relocation record')
    _absolute(value['input'])


def _snapshot(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'kind': 'missing'}
    if stat.S_ISLNK(info.st_mode):
        return {'kind': 'link', 'identity': _identity(info), 'target': os.readlink(path)}
    if stat.S_ISDIR(info.st_mode):
        return {'kind': 'directory', 'identity': _identity(info)}
    return {'kind': 'other', 'identity': _identity(info)}


def _valid_input(path):
    try:
        root = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError) as error:
        raise InputLocationError('invalid game_files path: ' + str(path)) from error
    try:
        _dir(root)
        _dir(root / 'exefs')
        _dir(root / 'romfs')
    except (OSError, ValueError) as error:
        raise InputLocationError('existing game_files folder is incomplete or unsafe; it was preserved: ' + str(path)) from error
    return root


def inspect(port, game):
    """Read-only location check; do not hash the whole dump or create metadata."""
    context = _context(port, game)
    roots = [_valid_input(workspace / 'game_files') for workspace in context['workspaces']]
    missing = any(root is None for root in roots) or len(set(roots)) != 1
    pending_path = context['metadata'] / ACTIVE
    pending = pending_path.exists() or pending_path.is_symlink()
    result = {'missing': missing or pending, 'owner': str(context['owner']),
              'previous': str(context['previous']),
              'workspaces': [str(path) for path in context['workspaces']],
              'recovery_pending': pending}
    if not missing:
        result['input'] = str(roots[0])
    return result


@contextlib.contextmanager
def _directory(path, *, create=False):
    """Open a canonical directory using nofollow component-relative descriptors."""
    path = _absolute(str(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(path.parts[1:]):
            if create and index >= len(path.parts[1:]) - 2:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        if _identity(os.fstat(fd)) != _identity(path.lstat()):
            raise InputLocationError('installation directory changed during recovery')
        yield fd
    finally:
        os.close(fd)


def _lock(fd, path):
    value, named = os.fstat(fd), path.lstat()
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
            or value.st_uid != os.getuid() or value.st_mode & 0o022
            or _identity(value) != _identity(named)):
        raise InputLocationError('recovery lock must be an owned ordinary file')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise BlockingIOError('Monado launcher, game or update is using this installation; close it before locating files') from None


@contextlib.contextmanager
def _maintenance(port):
    if fcntl is None:
        raise InputLocationError('input recovery requires native Linux locking')
    owner = layout.installation_root(port)
    descriptors = []
    try:
        descriptors.append(lease.acquire_maintenance(port))
        path = owner / 'Monado_Linux/updates/install.lock'
        with _directory(path.parent) as directory:
            fd = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
                         | os.O_NONBLOCK | os.O_CREAT, 0o600, dir_fd=directory)
        descriptors.append(fd)
        _lock(fd, path)
        profile = owner / 'Monado_Linux/play/launcher/.session.lock'
        if profile.exists() or profile.is_symlink():
            with _directory(profile.parent) as directory:
                fd = os.open(profile.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                             | os.O_NONBLOCK, dir_fd=directory)
            descriptors.append(fd)
            _lock(fd, profile)
        yield
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def require_idle(port):
    """Nonblocking picker preflight; relocate rechecks and holds the same locks."""
    with _maintenance(_dir(port)):
        pass


def _rename(directory, source, target, flags):
    # NOREPLACE and EXCHANGE keep a raced-in unknown file from being overwritten.
    function = getattr(ctypes.CDLL(None, use_errno=True), 'renameat2', None)
    if function is None:
        raise InputLocationError('safe input recovery requires Linux renameat2 support')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(directory, os.fsencode(source), directory, os.fsencode(target), flags):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _write_json(directory, parent, name, value):
    path = parent / name
    existing = _snapshot(path)
    if existing['kind'] not in ('missing', 'other'):
        raise InputLocationError('recovery metadata path is not an ordinary file')
    if existing['kind'] == 'other':
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise InputLocationError('recovery metadata path is unsafe')
    temporary = '.' + name + '.' + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | os.O_CLOEXEC, 0o600, dir_fd=directory)
    try:
        data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        if _snapshot(path) != existing:
            raise InputLocationError('recovery metadata changed before publication')
        if existing['kind'] == 'missing':
            _rename(directory, temporary, name, 1)
        else:
            _rename(directory, temporary, name, 2)
            if _snapshot(parent / temporary) != existing:
                _rename(directory, temporary, name, 2)
                raise InputLocationError('recovery metadata raced during publication')
            os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _check_directory(entry, directory):
    path = Path(entry['workspace'])
    _dir(path)
    if not _identity(path.lstat()) == _identity(os.fstat(directory)) == entry['directory']:
        raise InputLocationError('input workspace identity changed; recovery was stopped')


def _exchange(entry, directory, expected, desired):
    """Publish an already staged link, preserving raced-in unknown objects."""
    workspace, name = Path(entry['workspace']), entry['stage']
    _check_directory(entry, directory)
    if _snapshot(workspace / 'game_files') != expected or _snapshot(workspace / name) != desired:
        raise InputLocationError('game_files changed before publication; unknown files were preserved')
    if expected['kind'] == 'missing':
        _rename(directory, name, 'game_files', 1)
    else:
        _rename(directory, name, 'game_files', 2)
        if _snapshot(workspace / name) != expected:
            # Undo only if neither side has changed since our exchange.
            if _snapshot(workspace / 'game_files') == desired:
                _rename(directory, name, 'game_files', 2)
            raise InputLocationError('game_files raced during publication; recovery requires attention')
    os.fsync(directory)


def _validate_journal(journal, context):
    if (set(journal) != {'schema', 'owner', 'receipt', 'target', 'state', 'entries', 'prior'}
            or journal['schema'] != 1 or journal['owner'] != str(context['owner'])
            or journal['receipt'] != context['receipt_sha'] or journal['state'] not in ('pending', 'committed')
            or not isinstance(journal['entries'], list)):
        raise InputLocationError('pending input relocation has a different installation or game identity')
    _absolute(journal['target'])
    if journal['prior'] is not None:
        _validate_completed(journal['prior'], context['owner'])
    expected = {str(path) for path in context['workspaces']}
    seen = set()
    for entry in journal['entries']:
        if (not isinstance(entry, dict) or set(entry) != {'workspace', 'directory', 'stage', 'old', 'new'}
                or entry['workspace'] not in expected or entry['workspace'] in seen
                or not re.fullmatch(r'\.input-relocation-[0-9a-f]{32}-[0-9]+', str(entry['stage']))
                or entry['old'].get('kind') not in ('missing', 'link')
                or entry['new'].get('kind') != 'link' or entry['new'].get('target') != journal['target']):
            raise InputLocationError('invalid pending input relocation paths')
        seen.add(entry['workspace'])


def _completed(context, target):
    return {'schema': 1, 'owner': str(context['owner']), 'input': str(target),
            'game_receipt_sha256': context['receipt_sha'], 'exefs': context['exefs']}


def _recover(journal, context, metadata_fd):
    """Finish a committed transaction, otherwise restore only recorded old/new links."""
    _validate_journal(journal, context)
    committed = journal['state'] == 'committed'
    # Inspect every entry first. A foreign replacement blocks all recovery writes.
    for entry in journal['entries']:
        with _directory(entry['workspace']) as directory:
            _check_directory(entry, directory)
            current = _snapshot(Path(entry['workspace']) / 'game_files')
            staged = _snapshot(Path(entry['workspace']) / entry['stage'])
            if (current not in (entry['old'], entry['new']) or
                    staged not in (entry['old'], entry['new'], {'kind': 'missing'})
                    or committed and current != entry['new']):
                raise InputLocationError('pending relocation conflicts with a changed game_files path; unknown files were preserved')
    for entry in reversed(journal['entries']):
        workspace = Path(entry['workspace'])
        with _directory(workspace) as directory:
            _check_directory(entry, directory)
            current, staged = _snapshot(workspace / 'game_files'), _snapshot(workspace / entry['stage'])
            if not committed and current == entry['new']:
                if entry['old']['kind'] == 'missing':
                    if _snapshot(workspace / 'game_files') != entry['new']:
                        raise InputLocationError('input link changed during rollback')
                    os.unlink('game_files', dir_fd=directory)
                else:
                    if staged != entry['old']:
                        raise InputLocationError('old input link is unavailable for rollback')
                    _exchange(entry, directory, entry['new'], staged)
            staged = _snapshot(workspace / entry['stage'])
            if staged != {'kind': 'missing'}:
                if staged not in (entry['old'], entry['new']):
                    raise InputLocationError('unknown staged path was preserved')
                os.unlink(entry['stage'], dir_fd=directory)
            os.fsync(directory)
    if committed:
        _write_json(metadata_fd, context['metadata'], COMPLETED, _completed(context, journal['target']))
    # Pending rollback did not change the completed record, so preserve it.
    os.unlink(ACTIVE, dir_fd=metadata_fd)
    os.fsync(metadata_fd)


def _production_checker(target, cancel):
    checker = Path(__file__).resolve().parents[1] / 'tools/extract/check_dump.py'
    process = subprocess.Popen([sys.executable, '-I', '-B', str(checker), str(target)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               close_fds=True)
    deadline = time.monotonic() + 180
    try:
        while True:
            _cancelled(cancel)
            if time.monotonic() > deadline:
                raise InputLocationError('game-input validation exceeded its time limit')
            try:
                output, _ = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise InputLocationError('The selected folder is not the supported DE 2.0.0 dump: ' +
                                     output.decode('utf-8', errors='replace')[-4000:])
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _validate_target(context, replacement, checker, cancel):
    try:
        target = _absolute(str(Path(replacement).expanduser())).resolve(strict=True)
        _dir(target)
        _dir(target / 'exefs')
        _dir(target / 'romfs')
    except (OSError, ValueError, RuntimeError) as error:
        raise InputLocationError('Choose the game-files folder containing ordinary exefs and romfs directories') from error
    for root in dict.fromkeys((context['port'], context['game_port'], context['owner'] / 'Monado_Linux')):
        if target == root or target.is_relative_to(root) or root.is_relative_to(target):
            raise InputLocationError('game input must be separate from Linux builds, dependencies and private state')
    root_identity = [_identity(path.lstat()) for path in (target, target / 'exefs', target / 'romfs')]
    _cancelled(cancel)
    if checker is None:
        _production_checker(target, cancel)
    elif checker(target) is False:
        raise InputLocationError('selected folder failed the supported DE 2.0.0 input checker')
    _cancelled(cancel)
    anchor = _target_anchor(target)
    inventory = {entry.name: _digest(entry, cancel, allow_hardlinks=True)
                 for entry in sorted((target / 'exefs').iterdir())}
    if inventory != context['exefs']:
        raise InputLocationError('selected ExeFS files do not exactly match the existing game build; choose its original game input')
    if _target_anchor(target) != anchor or anchor['roots'] != root_identity:
        raise InputLocationError('game-input directories changed during validation')
    context['target_anchor'] = anchor
    return target


def _target_anchor(target):
    paths = (target, target / 'exefs', target / 'romfs')
    for path in paths:
        _dir(path)
    entries = {}
    for entry in sorted((target / 'exefs').iterdir()):
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise InputLocationError('ExeFS entries must remain ordinary files')
        entries[entry.name] = [_identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return {'roots': [_identity(path.lstat()) for path in paths], 'exefs': entries}


def _verify_target(context, target):
    if _target_anchor(target) != context['target_anchor']:
        raise InputLocationError('selected game input changed before relocation completed')


def relocate(port, game, replacement, *, checker=None, cancel=None, failpoint=None):
    """Validate and transactionally reconnect input; never rebuild or edit saves."""
    _cancelled(cancel)
    context = _context(port, game, verify=True, cancel=cancel)
    with _maintenance(context['port']):
        # Re-read under the installation lease; receipts/bindings must not drift.
        context = _context(port, game, verify=True, cancel=cancel)
        with _directory(context['metadata'], create=True) as metadata_fd:
            pending = _read_json(context['metadata'] / ACTIVE, optional=True)
            if pending is not None:
                _recover(pending, context, metadata_fd)
                context = _context(port, game, verify=True, cancel=cancel)
            target = _validate_target(context, replacement, checker, cancel)
            allowed = {context['receipt_input'], context['previous'], context['owner'] / 'game_files'}
            entries = []
            transaction = uuid.uuid4().hex
            for number, workspace in enumerate(context['workspaces']):
                path = workspace / 'game_files'
                old = _snapshot(path)
                if old['kind'] == 'directory' and path == target:
                    continue  # Preserve the original ordinary input directory.
                if old['kind'] not in ('missing', 'link'):
                    raise InputLocationError('game_files is an ordinary file/directory; it will not be replaced: ' + str(path))
                if old['kind'] == 'link':
                    if old['identity'][3] != os.getuid() or old['identity'][4] != 1:
                        raise InputLocationError('game_files must be an owned single-link symlink')
                    link = Path(old['target'])
                    destination = Path(os.path.normpath(str(link if link.is_absolute() else workspace / link)))
                    if destination not in allowed:
                        raise InputLocationError('game_files points to an unknown location; its link was preserved: ' + str(path))
                entries.append({'workspace': str(workspace), 'directory': _identity(workspace.lstat()),
                                'stage': '.input-relocation-' + transaction + '-' + str(number),
                                'old': old, 'new': None})
            # Recheck inputs and binary after the checker before publishing links.
            if _context(port, game, verify=True, cancel=cancel)['receipt_sha'] != context['receipt_sha']:
                raise InputLocationError('game build changed during input validation')
            _verify_target(context, target)
            _cancelled(cancel)
            staged = []
            journal = None
            try:
                for entry in entries:
                    with _directory(entry['workspace']) as directory:
                        _check_directory(entry, directory)
                        os.symlink(str(target), entry['stage'], dir_fd=directory)
                        entry['new'] = _snapshot(Path(entry['workspace']) / entry['stage'])
                        os.fsync(directory)
                        staged.append(entry)
                journal = {'schema': 1, 'owner': str(context['owner']), 'receipt': context['receipt_sha'],
                           'target': str(target), 'state': 'pending', 'entries': entries,
                           'prior': context['completed']}
                _write_json(metadata_fd, context['metadata'], ACTIVE, journal)
                _point(failpoint, 'journal-ready')
                for number, entry in enumerate(entries):
                    _cancelled(cancel)
                    _point(failpoint, 'before-link-' + str(number))
                    with _directory(entry['workspace']) as directory:
                        _exchange(entry, directory, entry['old'], entry['new'])
                        # Retain the original link at its journaled staging name
                        # until commit, so interrupted rollback preserves identity.
                    _point(failpoint, 'after-link-' + str(number))
                _cancelled(cancel)
                _point(failpoint, 'before-commit')
                _verify_target(context, target)
                journal['state'] = 'committed'
                _write_json(metadata_fd, context['metadata'], ACTIVE, journal)
                _point(failpoint, 'committed')
                _recover(journal, context, metadata_fd)
            except Exception as error:
                if journal is not None:
                    try:
                        pending = _read_json(context['metadata'] / ACTIVE, optional=True)
                        if pending is not None:
                            _recover(pending, context, metadata_fd)
                    except Exception as recovery:
                        raise InputLocationError(str(error) + '; recovery is pending: ' + str(recovery)) from error
                else:
                    for entry in staged:
                        if _snapshot(Path(entry['workspace']) / entry['stage']) == entry['new']:
                            with _directory(entry['workspace']) as directory:
                                os.unlink(entry['stage'], dir_fd=directory)
                raise
    return {'input': str(target), 'owner': str(context['owner']), 'rebuilt': False}
