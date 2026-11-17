#!/usr/bin/env python3
"""Monado II Linux updates: one retained version and durable activation.

This module runs only in the outer launcher supervisor. It never opens, copies,
restores or migrates saves/configuration/caches. Installed builds and authored
source stay in place; only the checked visible version marker is updated, with
its exact original bytes bound to the unchanged source manifest. Network and
compilation never run in the sandboxed GUI/game.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import types
import uuid

ROOT = Path(__file__).resolve().parents[1]


def _workspace_helper(stem):
    """Load this workspace's helper without sharing process-wide import aliases.

    One builder process can inspect an older registered install and then a newer
    adjacent install. Their publication policies and release helpers must remain
    paired with their own sources, regardless of import order or concurrent use.
    """
    path = ROOT / 'tools' / (stem + '.py')
    if path.resolve() != path:
        raise ValueError('update helper path contains a link')
    before = path.lstat()
    limit = 8 * 1024 * 1024
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise ValueError('update helper must be an ordinary bounded single-link file')
    def snapshot(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                getattr(info, 'st_birthtime_ns', None))
    def same_object(left, right):
        # Windows lstat/fstat can disagree on executable bits and ctime. Keep
        # full snapshots within each API and compare common identity across it.
        def identity(info):
            return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode),
                    info.st_nlink, info.st_size, info.st_mtime_ns)
        births = (getattr(left, 'st_birthtime_ns', None), getattr(right, 'st_birthtime_ns', None))
        return identity(left) == identity(right) and (None in births or births[0] == births[1])
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                 getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not same_object(opened, before):
            raise ValueError('update helper identity changed before reading')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    final = path.lstat()
    if (snapshot(after) != snapshot(opened) or snapshot(final) != snapshot(before)
            or not same_object(final, after)
            or len(data) != before.st_size or len(data) > limit or path.resolve() != path):
        raise ValueError('update helper changed while reading')
    name = '_monado_workspace_' + hashlib.sha256(os.fsencode(path)).hexdigest() + '_' + stem
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ''
    # Compile the checked bytes directly: no stale pyc lookup or shared-module
    # registration, and no sys.path mutation while another workspace is loading.
    exec(compile(data, str(path), 'exec'), module.__dict__)
    return module


update_release = _workspace_helper('update_release')
installed_version = _workspace_helper('installation_version')
_publication_guard = _workspace_helper('publication_guard')
content_problem = _publication_guard.content_problem
path_problem = _publication_guard.path_problem
read_regular = _publication_guard.read_regular
IMAGE = 'Monado-II-x86_64.AppImage'
IDENTITY = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
ACTIVE_KEYS = {'schema', 'version', 'id', 'workspace', 'image_sha256',
               'receipt_sha256', 'source_manifest_sha256'}
MAX_GAME_RECEIPT = 8 * 1024 * 1024  # native compile commands scale with managed path length

# [XCDE] LINUX-111: reuse only a content-policy verdict, never a trusted file
# identity. Every installed_sources call still reads and hashes every source,
# including ordinary-path and before/open/after race checks. The exact bytes,
# filename and policy determine this pure verdict. No on-disk cache is used.
_SOURCE_POLICY_VERDICTS = contextvars.ContextVar('monado_source_policy_verdicts', default=None)


@contextlib.contextmanager
def source_verification_context():
    """Bound pure policy-work reuse to one synchronous installation operation."""
    token = _SOURCE_POLICY_VERDICTS.set({})
    try:
        yield
    finally:
        _SOURCE_POLICY_VERDICTS.reset(token)


def ordinary(path, *, missing=False):
    path = Path(path).absolute()
    if '..' in path.parts or path.resolve() != path:
        raise ValueError('update path must be canonical without links or traversal')
    for parent in [*reversed(path.parents), path]:
        try:
            info = parent.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('update path contains a link')
        if parent != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError('update path parent is not an ordinary directory')
        if parent == path and not (stat.S_ISDIR(info.st_mode) or
                (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
            raise ValueError('update path is not an ordinary directory or single-link file')
    return path


def digest(path):
    return hashlib.sha256(read_regular(ordinary(path))).hexdigest()


def json_read(path, limit=2 * 1024 * 1024):
    raw = read_regular(ordinary(path))
    if len(raw) > limit:
        raise ValueError('update metadata exceeds size limit')
    def unique(pairs):
        value = {}
        for name, data in pairs:
            if name in value:
                raise ValueError('duplicate update metadata field')
            value[name] = data
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('update metadata must be an object')
    return value


def write_new(path, value):
    ordinary(path, missing=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


def durable_replace(path, value):
    ordinary(path, missing=True)
    temporary = path.parent / ('.' + path.name + '-' + uuid.uuid4().hex + '.partial')
    write_new(temporary, value)
    try:
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def layout_module(workspace):
    path = ordinary(Path(workspace) / 'Monado_Linux/scripts/install_layout.py')
    spec = importlib.util.spec_from_file_location('_monado_update_install_layout', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installed_sources(workspace, *, _allow_stale_marker=False):
    # An owner marker can recursively verify the active source more than once.
    # Even a standalone read-only caller gets one bounded pure-verdict context.
    if _SOURCE_POLICY_VERDICTS.get() is None:
        with source_verification_context():
            return _installed_sources(workspace, _allow_stale_marker=_allow_stale_marker)
    return _installed_sources(workspace, _allow_stale_marker=_allow_stale_marker)


def _installed_sources(workspace, *, _allow_stale_marker=False):
    """Verify release-owned source bytes while leaving all runtime directories alone.

    Unlike the clean archive guard this intentionally does not enumerate runtime
    files. No game input, generated output, dependency cache or save is read.
    Only an original installation's version marker may differ: its original
    bytes must match the unchanged manifest, and its visible value must follow
    a fully verified active selection (or a known recovery state during sync).
    """
    workspace = ordinary(workspace)
    manifest = json_read(workspace / 'publication-manifest.json')
    policy = json_read(workspace / 'publication-policy.json')
    verdicts = _SOURCE_POLICY_VERDICTS.get()
    policy_identity = hashlib.sha256(json.dumps(policy, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode()).digest()
    files = manifest.get('files')
    if (manifest.get('schema') != 1 or manifest.get('source_only') is not True or
            manifest.get('project') != 'Monado II' or not isinstance(files, dict) or
            not 1 <= len(files) <= 4096 or 'publication-policy.json' not in files):
        raise ValueError('installation has no supported exact source manifest')
    original = None
    backup = workspace / 'Monado_Linux/updates' / installed_version.BACKUP
    if backup.exists() or backup.is_symlink():
        if layout_module(ROOT).installation_root(workspace / 'Monado_Linux') != workspace:
            raise ValueError('only the original installation may have a bootstrap version backup')
        original = _original_metadata(workspace, manifest)
        _checked_owner_marker(workspace, original, allow_stale=_allow_stale_marker)
    for name, identity in files.items():
        if (path_problem(name) or name == 'publication-manifest.json' or not isinstance(identity, dict)):
            raise ValueError('unsafe installed source manifest')
        data = original if name == 'update-version.json' and original is not None else read_regular(ordinary(workspace / name))
        source_identity = hashlib.sha256(data).hexdigest()
        if len(data) != identity.get('bytes') or source_identity != identity.get('sha256'):
            raise ValueError('Local source changes detected; keep this installation and merge them manually: ' + name)
        key = (name, source_identity, policy_identity)
        if verdicts is not None and key in verdicts:
            problem = verdicts[key]
        else:
            problem = content_problem(name, data, policy.get('licensed_media', {}))
            if problem is None and verdicts is not None:
                # Bound an unusually large cleanup operation without changing
                # validation: an evicted verdict is simply calculated again.
                if len(verdicts) >= 16384:
                    verdicts.clear()
                verdicts[key] = None
        if problem:
            raise ValueError('installed source policy rejected ' + name + ': ' + problem)
    return manifest


def version(workspace):
    return installed_version.metadata(read_regular(ordinary(Path(workspace) / 'update-version.json')))['version']


def pair(image):
    # Image may contain a GUI bigger than the source guard's 8 MiB input limit.
    image = ordinary(image)
    if not image.is_file() or image.stat().st_size > 64 * 1024 * 1024 or not os.access(image, os.X_OK):
        raise ValueError('missing ordinary local launcher image')
    receipt = json_read(Path(str(image) + '.receipt.json'))
    with image.open('rb') as stream:
        header = stream.read(12)
        stream.seek(0)
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if (header[:4] != b'\x7fELF' or header[8:11] != b'AI\x02' or
            receipt.get('status') != 'passed' or receipt.get('artifact_kind') != 'local-launcher-appimage' or
            receipt.get('sha256') != actual or receipt.get('bytes') != image.stat().st_size or
            receipt.get('archive_readback_verified') is not True or
            any(receipt.get(key) is not False for key in ('contains_game_executable',
                'contains_game_files', 'contains_generated_game_code', 'contains_vendor_sdk'))):
        raise ValueError('updated image/receipt pair failed validation')
    return receipt


def active_record(owner, record, *, verify_sources=True):
    owner = ordinary(owner)
    if (set(record) != ACTIVE_KEYS or record.get('schema') != 1 or
            not isinstance(record.get('id'), str) or not IDENTITY.fullmatch(record['id']) or
            not isinstance(record.get('workspace'), str) or
            not all(isinstance(record.get(key), str) and HASH.fullmatch(record[key]) for key in
                    ('image_sha256', 'receipt_sha256', 'source_manifest_sha256'))):
        raise ValueError('invalid active update selection')
    expected = owner / 'Monado_Linux/updates' / record['id'] / 'workspace'
    if record['workspace'] != expected.relative_to(owner).as_posix():
        raise ValueError('active update escaped its immutable version directory')
    workspace = ordinary(expected)
    binding = json_read(workspace / 'installation.json', 8192)
    if binding.get('owner') != str(owner) or binding.get('workspace') != str(workspace):
        raise ValueError('active installation binding mismatch')
    module = layout_module(ROOT)
    if module.installation_root(workspace / 'Monado_Linux') != owner:
        raise ValueError('active update has a different owner')
    if version(workspace) != record['version']:
        raise ValueError('active version metadata mismatch')
    if digest(workspace / 'publication-manifest.json') != record['source_manifest_sha256']:
        raise ValueError('active source manifest changed')
    if verify_sources:
        installed_sources(workspace)
    receipt = pair(workspace / IMAGE)
    if receipt['sha256'] != record['image_sha256'] or digest(workspace / (IMAGE + '.receipt.json')) != record['receipt_sha256']:
        raise ValueError('active image identity mismatch')
    return workspace


def _original_metadata(owner, manifest):
    identity = manifest['files'].get('update-version.json')
    path = owner / 'Monado_Linux/updates' / installed_version.BACKUP
    if path.exists() or path.is_symlink():
        return installed_version.original_from_backup(json_read(path, 16384), owner,
            digest(owner / 'publication-manifest.json'), identity)
    return installed_version.checked_original(read_regular(ordinary(owner / 'update-version.json')), identity)


def _previous_selection(owner):
    path = owner / 'Monado_Linux/updates/previous.json'
    if not path.exists() and not path.is_symlink():
        return None
    value = json_read(path, 8192)
    if (set(value) != {'schema', 'selection'} or type(value.get('schema')) is not int
            or value['schema'] not in (1, 2, 3)
            or (value['schema'] == 3 and value['selection'] is not None)):
        raise ValueError('invalid previous version record')
    if value['selection'] is not None:
        active_record(owner, value['selection'])
    return value


def _selected_metadata(owner, original, selection):
    if selection is None:
        return original
    selected = active_record(owner, selection)
    data = read_regular(ordinary(selected / 'update-version.json'))
    installed_version.metadata(data)
    return data


def _current_selection(owner):
    path = owner / 'Monado_Linux/updates/active.json'
    if path.exists() or path.is_symlink():
        value = json_read(path, 8192)
        active_record(owner, value)
        return value
    return None


def _checked_owner_marker(owner, original, *, allow_stale=False):
    expected = _selected_metadata(owner, original, _current_selection(owner))
    actual = read_regular(ordinary(owner / 'update-version.json'))
    installed_version.metadata(actual)
    permitted = [expected]
    if allow_stale:
        permitted.append(original)
        previous = _previous_selection(owner)
        if previous is not None:
            permitted.append(_selected_metadata(owner, original, previous['selection']))
    if actual not in permitted:
        raise ValueError('installed-version marker does not match a verified current/previous version')
    return actual, expected


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes_new(path, data, mode=0o600):
    ordinary(path, missing=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    _fsync_directory(path.parent)


def _replace_metadata(path, data):
    installed_version.metadata(data)
    temporary = path.parent / ('.installed-version-' + uuid.uuid4().hex + '.partial')
    try:
        _write_bytes_new(temporary, data)
        os.replace(temporary, ordinary(path))
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _bridge_workspace(owner, bridge):
    if (set(bridge) != installed_version.BRIDGE_KEYS or type(bridge.get('schema')) is not int
            or bridge['schema'] != 1 or bridge.get('owner') != str(owner)
            or not isinstance(bridge.get('workspace'), str)
            or not all(isinstance(bridge.get(key), str) and HASH.fullmatch(bridge[key]) for key in
                       ('manifest_sha256', 'updater_sha256', 'version_helper_sha256', 'wrapper_sha256'))):
        raise ValueError('invalid installation version bridge')
    relative = Path(bridge['workspace'])
    if bridge['workspace'] == '.':
        workspace = owner
    elif (len(relative.parts) == 4 and relative.parts[:2] == ('Monado_Linux', 'updates')
            and relative.parts[3] == 'workspace' and relative.parts[2].startswith('update-')
            and IDENTITY.fullmatch(relative.parts[2])
            and bridge['workspace'] == relative.as_posix()):
        workspace = ordinary(owner / relative)
        if layout_module(ROOT).installation_root(workspace / 'Monado_Linux') != owner:
            raise ValueError('installation version bridge owner mismatch')
    else:
        raise ValueError('installation version bridge escaped its owner')
    manifest = installed_sources(workspace, _allow_stale_marker=workspace == owner)
    if digest(workspace / 'publication-manifest.json') != bridge['manifest_sha256']:
        raise ValueError('installation version bridge source manifest changed')
    for name, key in (('tools/update_linux.py', 'updater_sha256'),
                      ('tools/installation_version.py', 'version_helper_sha256'),
                      (installed_version.WRAPPER, 'wrapper_sha256')):
        if manifest['files'].get(name, {}).get('sha256') != bridge[key]:
            raise ValueError('installation version bridge differs from verified source')
    if digest(owner / installed_version.WRAPPER) != bridge['wrapper_sha256']:
        raise ValueError('unknown or modified installation rollback wrapper')
    return workspace


def _prepare_version_state(owner, capable_workspace):
    """Under the install lease: establish recovery before changing the marker."""
    manifest = installed_sources(owner, _allow_stale_marker=True)
    original = _original_metadata(owner, manifest)
    current, _ = _checked_owner_marker(owner, original, allow_stale=True)
    capable = installed_sources(capable_workspace, _allow_stale_marker=capable_workspace == owner)
    directory = owner / 'Monado_Linux/updates'
    wrapper = owner / installed_version.WRAPPER
    bridge_path = directory / installed_version.BRIDGE
    bridge = None
    if bridge_path.exists() or bridge_path.is_symlink():
        bridge = json_read(bridge_path, 8192)
        _bridge_workspace(owner, bridge)
    else:
        data = read_regular(ordinary(capable_workspace / installed_version.WRAPPER))
        if (capable['files'].get(installed_version.WRAPPER, {}).get('sha256') != hashlib.sha256(data).hexdigest()
                or any(name not in capable['files'] for name in ('tools/update_linux.py', 'tools/installation_version.py'))):
            raise ValueError('selected source has no verified version-recovery entrypoint')
        if wrapper.exists() or wrapper.is_symlink():
            if read_regular(ordinary(wrapper)) != data or not os.access(wrapper, os.X_OK):
                raise ValueError('unknown or modified installation rollback wrapper')
        bridge = dict(schema=1, owner=str(owner), workspace=capable_workspace.relative_to(owner).as_posix(),
            manifest_sha256=digest(capable_workspace / 'publication-manifest.json'),
            updater_sha256=capable['files']['tools/update_linux.py']['sha256'],
            version_helper_sha256=capable['files']['tools/installation_version.py']['sha256'],
            wrapper_sha256=capable['files'][installed_version.WRAPPER]['sha256'])
    previous = _previous_selection(owner)
    backup = directory / installed_version.BACKUP
    if not backup.exists():
        write_new(backup, installed_version.make_backup(owner, digest(owner / 'publication-manifest.json'),
            manifest['files']['update-version.json'], original))
        _fsync_directory(directory)
    if not wrapper.exists():
        _write_bytes_new(wrapper, read_regular(ordinary(capable_workspace / installed_version.WRAPPER)), 0o755)
    if not bridge_path.exists():
        write_new(bridge_path, bridge)
        _fsync_directory(directory)
    # Old rollback clients must refuse before modifying selection: they cannot
    # restore a mutable owner marker. The pinned wrapper remains usable instead.
    if previous is None or previous['schema'] not in (2, 3):
        durable_replace(directory / 'previous.json', {'schema': 2,
            'selection': None if previous is None else previous['selection']})
    return original, current


def _retire_rollback(owner, workspace):
    """LINUX-054: bind compatibility entrypoints to current, never old history.

    Keep the unchanged original wrapper/source manifest usable by old bootstrap
    dispatchers. Its --rollback command now reports that downgrades are manual.
    The bridge is small metadata referencing current, not a retained old build.
    Caller has committed and repaired active.json and the visible version first.
    """
    manifest = installed_sources(workspace)
    selected = _current_selection(owner)
    if selected is None or active_record(owner, selected) != workspace:
        raise ValueError('only the checked active version can retire update history')
    wrapper = installed_version.WRAPPER
    expected = manifest['files'].get(wrapper, {}).get('sha256')
    if not expected or digest(owner / wrapper) != expected:
        raise ValueError('unknown installation rollback compatibility wrapper')
    directory = owner / 'Monado_Linux/updates'
    bridge = dict(schema=1, owner=str(owner), workspace=workspace.relative_to(owner).as_posix(),
        manifest_sha256=digest(workspace / 'publication-manifest.json'),
        updater_sha256=manifest['files']['tools/update_linux.py']['sha256'],
        version_helper_sha256=manifest['files']['tools/installation_version.py']['sha256'],
        wrapper_sha256=expected)
    durable_replace(directory / installed_version.BRIDGE, bridge)
    # Old raw --rollback helpers only understand schemas 1/2. Schema 3 makes
    # them refuse BEFORE restoring a bootstrap whose game has been pruned.
    durable_replace(directory / 'previous.json', {'schema': 3, 'selection': None})


def _support_module(name):
    """Load only the reviewed support code shipped with this updater."""
    path = ordinary(ROOT / 'Monado_Linux/scripts' / (name + '.py'))
    spec = importlib.util.spec_from_file_location('_monado_update_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _retire_unactivated_history(owner):
    """A failed activation may have established a bridge before restoring owner.

    Validate then retire that transient pin before deleting its never-activated
    candidate. The next update can establish its own checked current binding.
    Original bootstrap source and the compatibility wrapper stay unchanged.
    """
    if _current_selection(owner) is not None:
        raise ValueError('active selection appeared before bootstrap cleanup')
    directory = owner / 'Monado_Linux/updates'
    bridge = directory / installed_version.BRIDGE
    if bridge.exists() or bridge.is_symlink():
        _bridge_workspace(owner, json_read(bridge, 8192))
        bridge.unlink()
        _fsync_directory(directory)
    previous = _previous_selection(owner)
    if previous is not None:
        durable_replace(directory / 'previous.json', {'schema': 3, 'selection': None})


def cleanup_current(owner, workspace, state, *, profile_lock_fd=None):
    """Best-effort owned GC; activation success never depends on deleting history.

    Caller holds install.lock. The separate runtime lease excludes other profiles
    and inherited GUI/game/precompile workers before touching their code paths.
    """
    fd = None
    try:
        # Refuse promptly while a new/other launcher is using this installation.
        # Recovery/bridge audits and obsolete tree walks are unnecessary until
        # exclusive maintenance admission succeeds.
        lease = _support_module('install_lease')
        fd = lease.acquire_maintenance(owner / 'Monado_Linux')
        selected = _current_selection(owner)
        if selected is None:
            if workspace != owner:
                raise ValueError('only the original installation can clean unactivated attempts')
            installed_sources(owner)
            _retire_unactivated_history(owner)
        else:
            _retire_rollback(owner, workspace)
        if _current_selection(owner) != selected or (selected is not None and active_record(owner, selected) != workspace):
            raise ValueError('active version changed before cleanup')
        module = layout_module(ROOT)
        game_port = module.game_port(workspace / 'Monado_Linux')
        roots = [owner / 'Monado_Linux/build', owner / 'Monado_Linux/generated']
        roots += [p for p in (owner / 'Monado_Linux/updates').iterdir()
                  if p.name.startswith(('update-', 'payload-')) and p != workspace.parent
                  and not game_port.is_relative_to(p)]
        excluded = () if profile_lock_fd is None else (profile_lock_fd,)
        _import_path = list(sys.path)
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import update_retention
        finally:
            sys.path[:] = _import_path
        with lease.legacy_guard(owner, roots, exclude_lock_fds=excluded):
            return update_retention.cleanup(owner, selected, verify_workspace=installed_sources,
                retained_ports=(game_port,), include_bootstrap=selected is not None)
    except (OSError, ValueError) as error:
        report = {'status': 'pending', 'removed': [], 'pending': [str(error)[:1024]]}
        try:
            durable_replace(owner / 'Monado_Linux/updates/retention-status.json', report)
        except (OSError, ValueError):
            pass  # ENOSPC/permissions must not undo or mask a committed activation.
        try:
            print('[updates] Cleanup pending; the current build is usable. ' + str(error), file=sys.stderr)
        except OSError:
            pass
        return report
    finally:
        if fd is not None:
            os.close(fd)


def sync_installation_version(workspace, state, profile_lock_fd, *, cleanup=True):
    """Normal-start repair under the already held profile lease and install lease.

    No active managed version means an ordinary fresh/development launch has no
    version-marker migration to perform. Dry runs never call this function.
    The launcher defers optional retention until its complete session has ended;
    mandatory marker/source validation remains part of startup admission.
    """
    import fcntl
    workspace, state = ordinary(workspace), ordinary(state)
    owner = layout_module(ROOT).installation_root(workspace / 'Monado_Linux')
    if not any(state != parent and state.is_relative_to(parent) for parent in
               (owner / 'Monado_Linux/play', owner / 'Monado_Linux/runs')):
        raise ValueError('version synchronization requires the original private profile')
    lease = ordinary(state / '.session.lock')
    expected, held = lease.stat(), os.fstat(profile_lock_fd)
    if (not stat.S_ISREG(held.st_mode) or held.st_nlink != 1
            or (expected.st_dev, expected.st_ino) != (held.st_dev, held.st_ino)):
        raise ValueError('version synchronization profile lease mismatch')
    fcntl.flock(profile_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Nothing read before install.lock is trusted for admission. Read only the
    # small selection record here; the full active image/source validation below
    # occurs under the lease. Previously it ran twice here and then a third time
    # under the lease, even though the first two results could not be reused.
    selected_path = owner / 'Monado_Linux/updates/active.json'
    selected = json_read(selected_path, 8192) if selected_path.exists() or selected_path.is_symlink() else None
    if selected is None:
        directory = owner / 'Monado_Linux/updates'
        if workspace != owner or not directory.exists() or not any(
                path.name.startswith(('update-', 'payload-')) for path in directory.iterdir()):
            return False
    session = object.__new__(Session)
    session.owner, session.lock_fd = owner, None
    try:
        session._lock()
        # No result from before install.lock is trusted across admission. This
        # context ends before the lock is released, even after a failed sync.
        with source_verification_context():
            if _current_selection(owner) != selected:
                raise ValueError('active selection changed during version synchronization')
            if selected is not None and owner / selected['workspace'] != workspace:
                return False  # The fully validated selection names another build.
            if selected is None:
                if cleanup:
                    cleanup_current(owner, workspace, state, profile_lock_fd=profile_lock_fd)
                return False
            original, current = _prepare_version_state(owner, workspace)
            target = _selected_metadata(owner, original, selected)
            changed = current != target
            if changed:
                _replace_metadata(owner / 'update-version.json', target)
            if cleanup:
                cleanup_current(owner, workspace, state, profile_lock_fd=profile_lock_fd)
            return changed
    finally:
        session.close()


def finish_installation_maintenance(workspace):
    """Best-effort retention after all native-session descriptors are closed.

    Re-resolve the original owner and current selection under a fresh install
    lease. No selection/source verdict survives the session lifetime. A changed
    selection or a concurrent runtime leaves obsolete files alone; activation
    still performs its existing immediate cleanup independently.
    """
    workspace = ordinary(workspace)
    owner = layout_module(ROOT).installation_root(workspace / 'Monado_Linux')
    directory = owner / 'Monado_Linux/updates'
    if not directory.exists():
        return False
    ordinary(directory)
    session = object.__new__(Session)
    session.owner, session.lock_fd = owner, None
    try:
        session._lock()
        with source_verification_context():
            selected = _current_selection(owner)
            if selected is None:
                if workspace != owner or not any(path.name.startswith(('update-', 'payload-'))
                        for path in directory.iterdir()):
                    return False
                installed_sources(owner)
            elif active_record(owner, selected) != workspace:
                return False
            return cleanup_current(owner, workspace, None)
    finally:
        session.close()


def dispatch_active(workspace, argv):
    """The original workspace image is a stable bootstrap; versions stay put.

    Explicitly opening a managed version remains possible for checks/rollback.
    No network, GUI, game, save write or source execution from a download here.
    """
    workspace = ordinary(workspace)
    module = layout_module(workspace)
    owner = module.installation_root(workspace / 'Monado_Linux')
    if owner != workspace:
        return None
    selected = ordinary(owner / 'Monado_Linux/updates/active.json', missing=True)
    if not selected.exists():
        return None
    active = active_record(owner, json_read(selected, 8192))
    return [str(active / IMAGE), '--appimage-extract-and-run', *argv]


def game_features(game):
    """Validate the selected game's recorded capabilities before planning reuse."""
    receipt = json_read(Path(game).parent / 'receipt.json', MAX_GAME_RECEIPT)
    if not isinstance(receipt.get('dlss_enabled'), bool):
        raise ValueError('old game has no explicit feature receipt')
    framegen = receipt.get('framegen_enabled', False)
    fsr3 = receipt.get('fsr3_enabled', False)
    if type(receipt.get('fsr4_enabled', False)) is not bool or type(fsr3) is not bool or type(framegen) is not bool or (framegen and not (receipt['dlss_enabled'] or fsr3)):
        raise ValueError('old game has an invalid frame-generation feature receipt')
    return receipt


def input_path_changed(receipt, current):
    """Relocation keeps a playable binary, but a later reuse needs a fresh payload.

    Immutable native build receipts are never rewritten to bless a new path.
    Legacy receipts without this field retain their existing validation path;
    the native builder's strict input identity checks remain authoritative.
    """
    recorded = receipt.get('input')
    if recorded is None:
        return False
    if (not isinstance(recorded, dict) or not isinstance(recorded.get('path'), str)
            or not Path(recorded['path']).is_absolute()):
        raise ValueError('The selected game has invalid recorded input metadata')
    return recorded['path'] != str(current)


def inherited_game_features(workspace):
    """Read the current checked game for an implicit legacy managed build.

    This is a read-only capability bridge while the parent updater owns its
    installation lock. Never acquire a nested lease or execute an old reader.
    Recheck all selection/binary/receipt bindings before returning its truthful
    compiled features; original bootstrap source age is not the active version.
    """
    workspace = ordinary(workspace)
    layout = layout_module(ROOT)
    owner = layout.installation_root(workspace / 'Monado_Linux')
    if owner == workspace:
        raise ValueError('feature inheritance requires an updater-managed workspace')
    binding_path = workspace / 'installation.json'
    def stamp(path):
        info = ordinary(path).stat()
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    binding_stamp = stamp(binding_path)
    binding_identity = digest(binding_path)
    active_path = owner / 'Monado_Linux/updates/active.json'
    active_identity = digest(active_path) if active_path.exists() or active_path.is_symlink() else None
    active_stamp = stamp(active_path) if active_identity is not None else None
    selected_record = _current_selection(owner)
    selected = owner if selected_record is None else active_record(owner, selected_record)
    installed_sources(selected)
    watched = {}
    def remember(path, *, large=False):
        path = ordinary(path)
        before = stamp(path)
        identity = _file_digest(path) if large else digest(path)
        if stamp(path) != before:
            raise ValueError('selection changed while reading feature inheritance metadata')
        watched[path] = (before, identity, large)
    metadata_path = selected / 'Monado_Linux/.deps/metadata/gui-build.json'
    port = layout.game_port(selected / 'Monado_Linux')
    expected_receipt = None
    if metadata_path.exists() or metadata_path.is_symlink():
        # Graphical first installs deliberately have no workspace AppImage.
        # Follow the same checked local-gui-build selection as Broker.open.
        remember(metadata_path)
        metadata = json_read(metadata_path, 16384)
        identity = metadata.get('build_id')
        if (metadata.get('schema') != 1 or metadata.get('status') != 'passed'
                or metadata.get('artifact_kind') != 'local-gui-build'
                or not isinstance(identity, str) or not IDENTITY.fullmatch(identity)):
            raise ValueError('invalid GUI build metadata for feature inheritance')
        build_path = selected / 'Monado_Linux/runs/local-build' / identity / 'receipt.json'
        remember(build_path)
        built = json_read(build_path, MAX_GAME_RECEIPT)
        game_info = metadata.get('game')
        if (built.get('schema') != 1 or built.get('status') != 'passed'
                or digest(build_path) != metadata.get('build_receipt_sha256')
                or not isinstance(game_info, dict) or set(game_info) !=
                   {'path', 'sha256', 'receipt_sha256', 'build_port'}
                or not all(isinstance(value, str) for value in game_info.values())
                or not isinstance(built.get('paths'), dict)
                or not isinstance(built['paths'].get('launcher'), str)
                or built.get('game') != game_info):
            raise ValueError('GUI build receipt differs during feature inheritance')
        game = ordinary(game_info['path'])
        launcher = ordinary(built.get('paths', {}).get('launcher', ''))
        if (game_info.get('build_port') != str(port)
                or not any(game.is_relative_to(port / name) for name in ('build', 'runs', 'accepted'))
                or built.get('paths', {}).get('game') != str(game)
                or metadata.get('launcher') != str(launcher)
                or not launcher.is_relative_to(selected / 'Monado_Linux')
                or metadata.get('state') != str(owner / 'Monado_Linux/play/launcher')
                or built.get('paths', {}).get('state') != metadata['state']):
            raise ValueError('GUI build selection escaped its checked installation')
        expected, expected_receipt = game_info.get('sha256'), game_info.get('receipt_sha256')
        if not isinstance(expected_receipt, str) or not HASH.fullmatch(expected_receipt):
            raise ValueError('GUI game receipt has no exact feature inheritance identity')
    else:
        image_path = selected / IMAGE
        remember(image_path, large=True)
        remember(Path(str(image_path) + '.receipt.json'))
        image = pair(image_path)
        name = image.get('game')
        if not isinstance(name, str):
            raise ValueError('current AppImage has no game selection for feature inheritance')
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 4
                or relative.parts[0] != 'Monado_Linux'
                or relative.parts[1] not in ('build', 'runs', 'accepted')):
            raise ValueError('current game has no valid AppImage selection for feature inheritance')
        game = ordinary(port.parent / relative)
        expected = image.get('game_sha256')
    game_receipt = game.parent / 'receipt.json'
    game_stamp, game_receipt_stamp = stamp(game), stamp(game_receipt)
    game_receipt_identity = digest(game_receipt)
    features = game_features(game)
    if (not isinstance(expected, str) or not HASH.fullmatch(expected)
            or features.get('status') != 'passed'
            or features.get('executable', {}).get('path') != str(game)
            or features.get('executable', {}).get('sha256') != expected
            or _file_digest(game) != expected
            or (expected_receipt is not None and game_receipt_identity != expected_receipt)):
        raise ValueError('current native game identity differs during feature inheritance')
    # A full rebuild can be repairing old providers or a relocated input path.
    # Capability inheritance needs truthful compiled metadata, not a runnable
    # old dependency/input graph. The newly built payload is checked normally.
    after_active = digest(active_path) if active_path.exists() or active_path.is_symlink() else None
    if (after_active != active_identity or _current_selection(owner) != selected_record
            or (stamp(active_path) if after_active is not None else None) != active_stamp
            or stamp(binding_path) != binding_stamp
            or stamp(game) != game_stamp or stamp(game_receipt) != game_receipt_stamp
            or layout.game_port(selected / 'Monado_Linux') != port
            or digest(binding_path) != binding_identity
            or any(stamp(path) != before or (_file_digest(path) if large else digest(path)) != identity
                   for path, (before, identity, large) in watched.items())
            or digest(game_receipt) != game_receipt_identity or _file_digest(game) != expected):
        raise ValueError('current installation changed during feature inheritance; retry from its launcher')
    return features



def verify_runtime_selection(workspace, state):
    """Recheck real game/GUI loading before selecting an update; no state writes."""
    workspace = ordinary(Path(workspace))
    port = workspace / 'Monado_Linux'
    layout = layout_module(workspace)
    image = pair(workspace / IMAGE)
    roots = []
    for key in ('launcher', 'game'):
        name = image.get(key)
        if not isinstance(name, str):
            raise ValueError('Update image has no receipted native ' + key + ' selection')
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 4
                or relative.parts[0] != 'Monado_Linux'
                or relative.parts[1] not in ('build', 'runs', 'accepted')):
            raise ValueError('Invalid update native selection path')
        selected_root = layout.game_port(port).parent if key == 'game' else workspace
        roots.append(ordinary(selected_root / relative))
    # Run the current authored validator, not code copied from an unselected
    # candidate. It understands preserved legacy receipts without blessing them
    # as a new closed dependency graph.
    path = ROOT / 'Monado_Linux/scripts/run_linux.py'
    spec = importlib.util.spec_from_file_location('_monado_update_runtime_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = []
    for executable in roots:
        launch = module.plan(executable, state, port=port)
        checks.append(module.validate_runtime(launch))
    return {'schema': 1, 'status': 'passed', 'checks': checks,
            'scope': 'Current native dependency checks before update activation; no game/UI or profile writes'}


def private_build_python():
    """Reuse the standalone launcher's persistent interpreter, never its mount.

    Ordinary installations keep the existing shell/doctor entry. The bundled
    interpreter has a manifest-bound marker at its stable base prefix; a new
    update workspace does not yet have a virtualenv and must not require a
    separately installed system Python just to create it.
    """
    marker = Path(sys.base_prefix) / 'monado-private-python.json'
    if not marker.exists() and not marker.is_symlink():
        return None
    prefix = ordinary(Path(sys.base_prefix))
    value = json_read(ordinary(marker), 16384)
    if (sys.version_info[:2] != (3, 14) or value.get('schema') != 1 or
            value.get('project') != 'Monado II' or value.get('python') != [3, 14] or
            value.get('runtime_kind') != 'standalone-builder'):
        raise ValueError('Invalid standalone build interpreter identity')
    executable = ordinary(Path(getattr(sys, '_base_executable', sys.executable)))
    if not executable.is_relative_to(prefix) or not os.access(executable, os.X_OK):
        raise ValueError('Standalone build interpreter escaped its persistent prefix')
    return executable


def build_command(workspace, game, rebuild):
    private_python = private_build_python()
    command = ([str(private_python), '-I', '-B', str(workspace / 'tools/build_linux_app.py')]
               if private_python is not None else [str(workspace / 'Build_Monado_II.sh')])
    receipt = game_features(game)
    framegen = receipt.get('framegen_enabled', False)
    if not receipt['dlss_enabled']:
        command.append('--without-dlss')
    if rebuild:
        # This modern updater understands the FSR3-only provider receipt. Old
        # updaters omit this flag and keep their original no-DLSS contract.
        # Full current builds include FSR3 by default; runtime use remains off.
        command.append('--framegen')
    if not rebuild:
        if not receipt.get('fsr4_enabled', False):
            command.append('--without-fsr4')
        if not receipt.get('fsr3_enabled', False):
            command.append('--without-fsr3')
        if receipt['dlss_enabled'] and not framegen:
            raise ValueError('The selected game lacks standard frame-generation support; a full rebuild is required.')
        if framegen:
            command.append('--framegen')
        command += ['--reuse-game', str(game)]
    elif receipt.get('foley_trace'):
        raise ValueError('This custom diagnostic game build requires a manual rebuild; the current version is preserved.')
    elif receipt.get('split_game') and receipt.get('game_library'):
        # A renderer/runtime update may retain exact local game code. The native
        # builder independently verifies its module, ABI, input and content
        # receipts again before copying it into the new atomic payload pair.
        path = workspace / 'Monado_Linux/scripts/gamecode_identity.py'
        if path.is_file() and not path.is_symlink():
            import importlib.util
            spec = importlib.util.spec_from_file_location('_monado_update_gamecode_abi', path)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            expected = module.identity(workspace / 'Monado_Linux', receipt.get('dependencies', {}).get('compiler_wrappers', {}))
            if expected == receipt.get('gamecode_abi'):
                command += ['--reuse-game-code', str(game)]
    return command


def _copy_reviewed_source(source, destination):
    """Copy only verified authored files, never a build/profile/input tree."""
    manifest = installed_sources(source)
    destination.mkdir(mode=0o700)
    for name in sorted([*manifest['files'], 'publication-manifest.json']):
        original = ordinary(source / name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_bytes_new(target, read_regular(original), 0o700 if os.access(original, os.X_OK) else 0o600)
    installed_sources(destination)


def _file_digest(path):
    with ordinary(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def payload_result(workspace, build_id):
    """Check the fixed output identity from the native game-only builder."""
    if not isinstance(build_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', build_id):
        raise ValueError('invalid native game payload build identity')
    port = workspace / 'Monado_Linux'
    marker = json_read(port / '.deps/metadata/game-payload.json', 16384)
    game = marker.get('game')
    if (set(marker) != {'schema', 'artifact_kind', 'status', 'build_id', 'game', 'build_receipt_sha256'}
            or type(marker.get('schema')) is not int or not isinstance(game, dict)
            or set(game) != {'path', 'sha256', 'receipt_sha256', 'build_port'}):
        raise ValueError('native game payload has an invalid build receipt')
    expected = port / 'build' / (build_id + '-game') / 'xcde-linux'
    build_receipt = port / 'runs/local-build' / build_id / 'receipt.json'
    if (marker.get('schema') != 1 or marker.get('artifact_kind') != 'local-game-payload'
            or marker.get('status') != 'passed' or marker.get('build_id') != build_id
            or game.get('path') != str(expected) or game.get('build_port') != str(port)
            or game.get('sha256') != _file_digest(expected)
            or game.get('receipt_sha256') != digest(expected.parent / 'receipt.json')
            or marker.get('build_receipt_sha256') != digest(build_receipt)
            or json_read(build_receipt).get('status') != 'passed'):
        raise ValueError('native game payload does not match its checked build receipt')
    return expected


def run_build(command, workspace, log, emit, cancelled, *, lock_fd=None):
    """A separate trusted subreaper owns only build workers, including setsid jobs."""
    invocation = [sys.executable, '-I', '-B', str(ROOT / 'tools/update_linux.py'),
                  '--build-worker', str(workspace), '--worker-log', str(log),
                  '--update-lock-fd', str(lock_fd), '--', *command]
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    output_path = log.with_suffix('.worker-console.log')
    with output_path.open('xb') as output:
        child = subprocess.Popen(invocation, cwd=workspace, env=environment,
                                 stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                 close_fds=True, pass_fds=(lock_fd,), start_new_session=True)
        interrupted = None
        started = time.monotonic()
        offset = 0
        pending = b''
        while child.poll() is None:
            if (cancelled() or time.monotonic() - started > 3600) and interrupted is None:
                child.send_signal(signal.SIGINT)
                interrupted = time.monotonic()
            # Never forcibly kill the trusted cleanup owner. It retains its
            # subreaper and the update lease until detached children are gone.
            if log.exists():
                with log.open('rb') as incoming:
                    incoming.seek(offset)
                    data = incoming.read(65536)
                    offset += len(data)
                pending += data
                lines = pending.split(b'\n')
                pending = lines.pop()[-4096:]
                for line in lines:
                    stage = re.match(rb'\[(\d+)/(\d+)\] ([a-z-]+)', line)
                    if stage:
                        done, total = int(stage[1]), int(stage[2])
                        if 0 < done <= total <= 100:
                            emit({'phase': 'building', 'fraction': (done - 1) / total,
                                  'message': stage[3].decode().replace('-', ' ').capitalize() +
                                             f' ({done}/{total})'})
            time.sleep(0.1)
        code = child.wait()
    if interrupted is not None:
        raise update_release.UpdateCancelled('Update build cancelled; previous version remains selected.')
    if code:
        raise ValueError('Update build failed; previous version remains selected. Log: ' + str(log))


def checked_worker_command(workspace, command):
    """Allow only the legacy entry or the exact persistent-Python entry."""
    if (not isinstance(command, list) or not command or
            any(not isinstance(arg, str) or '\x00' in arg for arg in command)):
        raise ValueError('invalid build worker command')
    if command[0] == str(workspace / 'Build_Monado_II.sh'):
        return command
    private_python = private_build_python()
    prefix = ([str(private_python), '-I', '-B', str(workspace / 'tools/build_linux_app.py')]
              if private_python is not None else None)
    if prefix is None or command[:4] != prefix:
        raise ValueError('build worker must use its fixed candidate build command')
    return command


def build_worker(workspace, log, command, lock_fd):
    """Trusted cleanup process, never the GUI's broad session reaper."""
    workspace, log = ordinary(workspace), ordinary(log, missing=True)
    checked_worker_command(workspace, command)
    if not log.is_relative_to(workspace.parent):
        raise ValueError('build worker must use its fixed candidate build command and log')
    import fcntl
    binding = json_read(workspace / 'installation.json', 8192)
    expected = ordinary(Path(binding['owner']) / 'Monado_Linux/updates/install.lock')
    info, held = expected.stat(), os.fstat(lock_fd)
    if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1 or (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
        raise ValueError('build worker update lease mismatch')
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.set_inheritable(lock_fd, False)
    previous = list(sys.path)
    sys.path.insert(0, str(ROOT / 'tools'))
    try:
        import build_linux_app
    finally:
        sys.path[:] = previous
    try:
        return build_linux_app.execute(command, workspace, log)
    finally:
        # execute already performs bounded pidfd cleanup. If an uninterruptible
        # worker remains, retain ownership until it exits rather than orphan it
        # or permit a second updater to claim that cleanup completed.
        while True:
            remaining = build_linux_app.reap_owned(None)
            if not remaining:
                break
            build_linux_app.signal_owned(remaining, signal.SIGKILL)
            time.sleep(0.1)


class Session:
    """One offer/install transaction owned by the existing launcher session lease."""
    def __init__(self, workspace, state, launcher, game, *, discover=None, fetch=None, runner=None):
        self.workspace = ordinary(workspace)
        self.state = ordinary(state, missing=True)
        self.launcher, self.game = ordinary(launcher), ordinary(game)
        self.layout = layout_module(self.workspace)
        self.owner = self.layout.installation_root(self.workspace / 'Monado_Linux')
        self.current_version = version(self.workspace)
        stable = self.owner / 'Monado_Linux'
        if not any(self.state != parent and self.state.is_relative_to(parent) for parent in (stable / 'play', stable / 'runs')):
            raise ValueError('updater session has no stable original profile')
        self.discover = discover or update_release.discover
        self.fetch = fetch or update_release.fetch_and_extract
        self.runner = runner or run_build
        self.offer = None
        self.lock_fd = None
        self.prepared = None
        self.profile_lock_fd = None  # borrowed from the outer launcher; never closed here
        self._busy = threading.Lock()

    def check(self):
        result = self.discover(self.current_version)
        if result is None:
            return None
        self.offer = dict(result, id=uuid.uuid4().hex)
        return {'id': self.offer['id'], 'version': self.offer['version'], 'rebuild': True,
                'message': 'This update may rebuild the game locally. Saves and settings stay in place.'}

    def _lock(self):
        import fcntl
        directory = ordinary(self.owner / 'Monado_Linux/updates', missing=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        path = ordinary(directory / 'install.lock', missing=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        if os.fstat(fd).st_nlink != 1 or not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError('unsafe workspace update lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise ValueError('Another Monado II update is already running.') from None
        self.lock_fd = fd
        return directory

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def install(self, offer_id, progress, cancel):
        if not self._busy.acquire(blocking=False):
            raise ValueError('update already in progress')
        try:
            return self._install(offer_id, progress, cancel)
        except BaseException:
            self.close()
            raise
        finally:
            self._busy.release()

    def _build_payload(self, workspace, directory, progress, cancelled):
        """Build at a permanent independent path so GUI versions never own reuse."""
        identity = 'payload-' + uuid.uuid4().hex
        transaction = directory / identity
        transaction.mkdir(mode=0o700)
        write_new(transaction / 'payload.json', {'schema': 1, 'kind': 'game-payload',
            'owner': str(self.owner), 'id': identity, 'workspace': 'workspace'})
        payload = transaction / 'workspace'
        archive = workspace.parent / 'download/source.tar.gz'
        if self.fetch is update_release.fetch_and_extract or archive.exists():
            # Reuse the exact checked release archive, not an interruptible copy
            # of hundreds of source files into an otherwise incomplete workspace.
            # _unpack declares partial extraction before writing source, so GC can
            # authenticate and clean a killed/cancelled payload preparation too.
            archive = ordinary(archive)
            download = transaction / 'download'
            download.mkdir(mode=0o700)
            partial = download / 'source.tar.gz.partial'
            size, hasher = 0, hashlib.sha256()
            with archive.open('rb') as incoming, partial.open('xb') as outgoing:
                while True:
                    update_release._cancel(cancelled)
                    data = incoming.read(update_release.CHUNK)
                    if not data:
                        break
                    size += len(data)
                    if size > self.offer['archive_bytes']:
                        raise ValueError('payload source archive exceeds its reviewed size')
                    hasher.update(data)
                    outgoing.write(data)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if size != self.offer['archive_bytes'] or hasher.hexdigest() != self.offer['archive_sha256']:
                raise ValueError('payload source archive differs from the reviewed release')
            complete = download / 'source.tar.gz'
            partial.rename(complete)
            _fsync_directory(download)
            source = update_release._unpack(complete, download, self.offer, progress, cancelled)
            source.rename(payload)
            _fsync_directory(transaction)
        else:
            # Explicit injected offline fixture providers have no transport
            # archive; their already-verified source still gets a fresh copy.
            _copy_reviewed_source(workspace, payload)
        port = payload / 'Monado_Linux'
        write_new(payload / 'installation.json', {'schema': 1, 'owner': str(self.owner),
            'workspace': str(payload), 'game_port': str(port)})
        (payload / 'game_files').symlink_to((self.owner / 'game_files').resolve(strict=True), target_is_directory=True)
        build_id = 'game-' + identity.removeprefix('payload-')
        command = build_command(payload, self.game, True) + ['--game-only', '--build-id', build_id]
        self._run(command, payload, transaction / 'build.log', progress, cancelled)
        if cancelled():
            raise update_release.UpdateCancelled('Update cancelled; current version remains selected.')
        installed_sources(payload)
        return payload_result(payload, build_id)

    def _run(self, command, workspace, log, progress, cancelled):
        if self.runner is run_build:
            self.runner(command, workspace, log, progress, cancelled, lock_fd=self.lock_fd)
        else:
            self.runner(command, workspace, log, progress, cancelled)

    def _install(self, offer_id, progress, cancel):
        if self.offer is None or offer_id != self.offer['id'] or self.prepared is not None:
            raise ValueError('stale or repeated update offer')
        cancelled = cancel.is_set
        if cancelled():
            raise update_release.UpdateCancelled('Update cancelled.')
        baseline = installed_sources(self.workspace)
        try:
            current_input = self.layout.shared_input(self.workspace / 'Monado_Linux')
        except FileNotFoundError as error:
            raise ValueError('Game files could not be found. Close the launcher and reopen Monado II '
                             'to choose Locate game files, then retry this update. Saves stay in place.') from error
        directory = self._lock()
        active = directory / 'active.json'
        prior = json_read(active, 8192) if active.exists() else None
        if prior is not None:
            active_record(self.owner, prior)
            current_active = self.owner / prior['workspace']
            if self.workspace != current_active:
                raise ValueError('This launcher is no longer the active version. Reopen the main launcher before updating.')
        identifier = 'update-' + uuid.uuid4().hex
        transaction = directory / identifier
        transaction.mkdir(mode=0o700)
        write_new(transaction / 'transaction.json', {'schema': 1, 'status': 'staging',
                  'version': self.offer['version'], 'previous': prior})
        source = self.fetch(self.offer, transaction / 'download', progress=progress, cancel=cancelled)
        candidate_manifest = update_release.verified_source(source)
        if version(source) != self.offer['version']:
            raise ValueError('downloaded version metadata differs from release')
        rebuild = update_release.classify(baseline, candidate_manifest) == 'game'
        features = game_features(self.game)
        rebuild = rebuild or input_path_changed(features, current_input)
        # Native FG support is part of the normal DLSS build. A launcher-only
        # update cannot reuse an older game that lacks that capability.
        adds_fsr3 = 'Monado_Linux/scripts/setup_linux_fsr3.py' in candidate_manifest.get('files', {})
        adds_fsr4 = 'Monado_Linux/scripts/setup_linux_fsr4.py' in candidate_manifest.get('files', {})
        rebuild = rebuild or (adds_fsr4 and not features.get('fsr4_enabled', False)) or (adds_fsr3 and not features.get('fsr3_enabled', False)) or (features['dlss_enabled'] and not features.get('framegen_enabled', False))
        old_port = self.layout.build_port(self.workspace / 'Monado_Linux', self.game)
        # A one-time rebuild detaches legacy original/version-owned game output.
        # New launcher-only updates directly reference one permanent payload.
        payload_owner = old_port.parent.parent
        reusable_payload = payload_owner.parent == directory and payload_owner.name.startswith('payload-')
        if reusable_payload:
            ownership = json_read(payload_owner / 'payload.json', 16384)
            if type(ownership.get('schema')) is not int or ownership != {'schema': 1, 'kind': 'game-payload', 'owner': str(self.owner),
                             'id': payload_owner.name, 'workspace': 'workspace'}:
                raise ValueError('native game payload has an invalid ownership marker')
            binding = json_read(old_port.parent / 'installation.json', 8192)
            if type(binding.get('schema')) is not int or binding != {'schema': 1, 'owner': str(self.owner),
                           'workspace': str(old_port.parent), 'game_port': str(old_port)}:
                raise ValueError('native game payload must have a direct self binding')
            installed_sources(old_port.parent)
            result = json_read(old_port / '.deps/metadata/game-payload.json', 16384)
            if payload_result(old_port.parent, result.get('build_id')) != self.game:
                raise ValueError('selected game differs from the owned native payload')
        rebuild = rebuild or not reusable_payload
        workspace = transaction / 'workspace'
        source.rename(workspace)  # Before any build: absolute paths never change afterward.
        port = workspace / 'Monado_Linux'
        game = self._build_payload(workspace, directory, progress, cancelled) if rebuild else self.game
        game_port = game.parents[2]
        write_new(workspace / 'installation.json', {'schema': 1, 'owner': str(self.owner),
                  'workspace': str(workspace), 'game_port': str(game_port)})
        shared_input = (self.owner / 'game_files').resolve(strict=True)
        (workspace / 'game_files').symlink_to(shared_input, target_is_directory=True)
        command = build_command(workspace, game, False)
        progress({'phase': 'building', 'message': 'Rebuilding the game and launcher locally. Saves stay in place.' if rebuild else
                  'Updating the launcher; keeping the verified game build and saves.'})
        self._run(command, workspace, transaction / 'build.log', progress, cancelled)
        if cancelled():
            raise update_release.UpdateCancelled('Update cancelled; previous version remains selected.')
        installed_sources(self.workspace)
        installed_sources(workspace)
        image_receipt = pair(workspace / IMAGE)
        runtime_validation = verify_runtime_selection(workspace, self.state)
        # The builder's final AppImage --dry-run checks the exact input, selected
        # native receipts/resources and stable state without opening a game/UI.
        record = {'schema': 1, 'version': self.offer['version'], 'id': identifier,
                  'workspace': workspace.relative_to(self.owner).as_posix(),
                  'image_sha256': image_receipt['sha256'],
                  'receipt_sha256': digest(workspace / (IMAGE + '.receipt.json')),
                  'source_manifest_sha256': digest(workspace / 'publication-manifest.json')}
        active_record(self.owner, record)
        self.prepared = {'record': record, 'previous': prior, 'transaction': str(transaction), 'rebuild': rebuild,
                         'runtime_validation': runtime_validation}
        write_new(transaction / 'prepared.json', self.prepared)
        progress({'phase': 'ready', 'message': 'Update built and checked. Restarting the launcher; saves stay in place.'})
        return self.prepared

    def activate(self, prepared):
        """Call only after GUI/activity descendants exit, while profile lease is held."""
        if self.lock_fd is None or prepared is not self.prepared:
            raise ValueError('no owned prepared update to activate')
        record = prepared['record']
        workspace = active_record(self.owner, record)
        directory = self.owner / 'Monado_Linux/updates'
        selected = directory / 'active.json'
        actual = json_read(selected, 8192) if selected.exists() else None
        if actual != prepared['previous']:
            raise ValueError('active selection changed; preserve the prepared update and retry safely')
        verify_runtime_selection(workspace, self.state)
        original, marker_before = _prepare_version_state(self.owner, workspace)
        # Previous record is durable before the one-file commit. Until replace,
        # crashes leave the old selection. Images, code and saves stay in place;
        # the derived visible version marker follows the committed selection.
        durable_replace(directory / 'previous.json', {'schema': 2, 'selection': actual})
        try:
            durable_replace(selected, record)
            _replace_metadata(self.owner / 'update-version.json', _selected_metadata(self.owner, original, record))
        except BaseException:
            # Restore the derived marker before selecting an older bootstrap,
            # which may not contain startup repair code.
            _replace_metadata(self.owner / 'update-version.json', marker_before)
            if actual is None:
                selected.unlink(missing_ok=True)
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try: os.fsync(fd)
                finally: os.close(fd)
            else:
                durable_replace(selected, actual)
            raise
        # Retire prior selection only after successful durable activation. Any
        # pending cleanup is retried by the new launcher's startup migration.
        cleanup_current(self.owner, workspace, self.state, profile_lock_fd=self.profile_lock_fd)
        self.close()
        return [str(workspace / IMAGE), '--appimage-extract-and-run', '--state-root', str(self.state)]


def rollback(owner):
    """Compatibility API: post-update downgrades are manual, never change saves."""
    raise ValueError('Local rollback is no longer available. Download an older release from GitHub '
                     'and build it manually; keep your existing saves and settings.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback', action='store_true',
                        help='deprecated: older releases must be downloaded and built manually')
    parser.add_argument('--owner', type=Path,
                        help='original installation selected by the verified rollback entrypoint')
    parser.add_argument('--build-worker', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-log', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--update-lock-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    if options.build_worker:
        command = options.command[1:] if options.command[:1] == ['--'] else options.command
        if not options.worker_log or not command or options.rollback or options.update_lock_fd is None or options.owner is not None:
            parser.error('invalid private build worker invocation')
        try:
            sys.exit(build_worker(options.build_worker, options.worker_log, command, options.update_lock_fd))
        except KeyboardInterrupt:
            sys.exit(130)
    elif options.rollback and not options.command:
        owner = layout_module(ROOT).installation_root(ROOT / 'Monado_Linux')
        if options.owner is not None and ordinary(options.owner) != owner:
            parser.error('rollback owner differs from the updater installation')
        try:
            rollback(owner)
        except ValueError as error:
            parser.exit(1, str(error) + '\n')
    else:
        parser.error('choose --rollback')
