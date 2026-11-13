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
import uuid

ROOT = Path(__file__).resolve().parents[1]
# Isolated AppImage/worker Python deliberately omits the script directory.
_import_path = list(sys.path)
sys.path.insert(0, str(ROOT / 'tools'))
try:
    import update_release
    import installation_version as installed_version
    from publication_guard import content_problem, path_problem, read_regular
finally:
    sys.path[:] = _import_path
IMAGE = 'Monado-II-x86_64.AppImage'
IDENTITY = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
ACTIVE_KEYS = {'schema', 'version', 'id', 'workspace', 'image_sha256',
               'receipt_sha256', 'source_manifest_sha256'}
MAX_GAME_RECEIPT = 8 * 1024 * 1024  # native compile commands scale with managed path length


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
        if len(data) != identity.get('bytes') or hashlib.sha256(data).hexdigest() != identity.get('sha256'):
            raise ValueError('Local source changes detected; keep this installation and merge them manually: ' + name)
        problem = content_problem(name, data, policy.get('licensed_media', {}))
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
        selected = _current_selection(owner)
        if selected is None:
            if workspace != owner:
                raise ValueError('only the original installation can clean unactivated attempts')
            installed_sources(owner)
            _retire_unactivated_history(owner)
        else:
            _retire_rollback(owner, workspace)
        lease = _support_module('install_lease')
        fd = lease.acquire_maintenance(owner / 'Monado_Linux')
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


def sync_installation_version(workspace, state, profile_lock_fd):
    """Normal-start repair under the already held profile lease and install lease.

    No active managed version means an ordinary fresh/development launch has no
    version-marker migration to perform. Dry runs never call this function.
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
    selected = _current_selection(owner)
    if selected is None:
        directory = owner / 'Monado_Linux/updates'
        if workspace != owner or not directory.exists() or not any(
                path.name.startswith(('update-', 'payload-')) for path in directory.iterdir()):
            return False
    elif active_record(owner, selected) != workspace:
        return False
    session = object.__new__(Session)
    session.owner, session.lock_fd = owner, None
    try:
        session._lock()
        if _current_selection(owner) != selected:
            raise ValueError('active selection changed during version synchronization')
        if selected is None:
            cleanup_current(owner, workspace, state, profile_lock_fd=profile_lock_fd)
            return False
        original, current = _prepare_version_state(owner, workspace)
        target = _selected_metadata(owner, original, selected)
        changed = current != target
        if changed:
            _replace_metadata(owner / 'update-version.json', target)
        cleanup_current(owner, workspace, state, profile_lock_fd=profile_lock_fd)
        return changed
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
    if type(framegen) is not bool or (framegen and not receipt['dlss_enabled']):
        raise ValueError('old game has an invalid frame-generation feature receipt')
    return receipt



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


def build_command(workspace, game, rebuild):
    command = [str(workspace / 'Build_Monado_II.sh')]
    receipt = game_features(game)
    framegen = receipt.get('framegen_enabled', False)
    if not receipt['dlss_enabled']:
        command.append('--without-dlss')
    if not rebuild:
        if receipt['dlss_enabled'] and not framegen:
            raise ValueError('The selected game lacks standard frame-generation support; a full rebuild is required.')
        if framegen:
            command.append('--framegen')
        command += ['--reuse-game', str(game)]
    elif receipt.get('foley_trace'):
        raise ValueError('This custom diagnostic game build requires a manual rebuild; the current version is preserved.')
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


def build_worker(workspace, log, command, lock_fd):
    """Trusted cleanup process, never the GUI's broad session reaper."""
    workspace, log = ordinary(workspace), ordinary(log, missing=True)
    if not log.is_relative_to(workspace.parent) or command[0] != str(workspace / 'Build_Monado_II.sh'):
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
        # Native FG support is part of the normal DLSS build. A launcher-only
        # update cannot reuse an older game that lacks that capability.
        rebuild = rebuild or (features['dlss_enabled'] and not features.get('framegen_enabled', False))
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
