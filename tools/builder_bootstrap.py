#!/usr/bin/env python3
"""Standalone builder entry point; materialize stable tools, never build a game.

The AppImage mount is temporary. Python used to create a game's virtual
 environment is copied to a verified persistent content-addressed directory
before the backend is started, so closing/moving the AppImage cannot invalidate
that environment. This module never selects game input or initiates a build.
"""
from __future__ import annotations
import argparse
import importlib.util
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

MANIFEST = 'usr/share/monado-ii/builder-manifest.json'
ARCHIVE = 'usr/share/monado-ii/source-template.tar.gz'
MAX_BYTES = 256 * 1024 * 1024


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or
            name.startswith('/') or name != str(PurePosixPath(name)) or
            any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Invalid builder bundle path')
    return name


def regular(path, limit=64 * 1024 * 1024):
    path = Path(path)
    before = path.lstat()
    if (path.resolve() != path or not stat.S_ISREG(before.st_mode) or
            before.st_nlink != 1 or before.st_size > limit):
        raise ValueError('Expected a bounded ordinary builder file: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    after = path.lstat()
    snapshot = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink,
                           s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if snapshot(before) != snapshot(after) or len(data) != before.st_size:
        raise ValueError('Builder file changed while reading')
    return data


def document(path, limit=4 * 1024 * 1024):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate builder metadata key')
            result[key] = value
        return result
    return json.loads(regular(path, limit), object_pairs_hook=unique)


def verify(root, identities, *, extras=()):
    if not isinstance(identities, dict) or not 0 < len(identities) <= 4096:
        raise ValueError('Invalid builder file inventory')
    total = 0
    for name, identity in identities.items():
        relative(name)
        if (not isinstance(identity, dict) or type(identity.get('bytes')) is not int or
                identity['bytes'] < 0 or identity.get('mode') not in (0o644, 0o755)):
            raise ValueError('Invalid builder file identity')
        data = regular(root / name)
        total += len(data)
        if (identity['bytes'] != len(data) or identity.get('sha256') != digest(data)
                or stat.S_IMODE((root / name).stat().st_mode) != identity['mode']):
            raise ValueError('Builder file differs from its manifest: ' + name)
    if total > MAX_BYTES:
        raise ValueError('Builder file inventory is oversized')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if not p.is_dir()}
    dirs = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir()}
    expected = set(identities) | set(extras)
    expected_dirs = {str(parent) for name in expected for parent in PurePosixPath(name).parents
                     if str(parent) != '.'}
    if actual != expected or dirs != expected_dirs:
        raise ValueError('Builder runtime contains unexpected files or directories')


def validate_image(root):
    doc = document(root / MANIFEST)
    if (doc.get('schema') != 1 or doc.get('project') != 'Monado II' or
            doc.get('kind') != 'standalone-builder' or doc.get('contains_game_files') is not False):
        raise ValueError('Invalid standalone builder manifest')
    verify(root, doc.get('files'), extras=(MANIFEST,))
    return doc


def ordinary_dir(path, *, create=False):
    path = Path(path).expanduser().absolute()
    if path.resolve() != path or '..' in path.parts:
        raise ValueError('Builder data directory must be canonical without links')
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise ValueError('Builder data directory is not an ordinary directory')
    return path


def copy_runtime(appdir, state, identities):
    prefix = 'usr/python/'
    selected = {name[len(prefix):]: value for name, value in identities.items() if name.startswith(prefix)}
    identity = digest(encoded(selected))
    parent = ordinary_dir(state / 'runtimes', create=True)
    target = parent / identity
    if target.exists() or target.is_symlink():
        verify(target, selected)
        return target, identity
    with tempfile.TemporaryDirectory(prefix='.python-', dir=parent) as temp:
        stage = Path(temp) / 'runtime'
        stage.mkdir()
        for name, metadata in selected.items():
            output = stage / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(regular(appdir / (prefix + name)))
            output.chmod(metadata['mode'])
        verify(stage, selected)
        stage.rename(target)
    return target, identity


def unpack_source(appdir, state, identity):
    data = regular(appdir / ARCHIVE)
    if identity['bytes'] != len(data) or identity['sha256'] != digest(data):
        raise ValueError('Source template archive changed')
    parent = ordinary_dir(state / 'sources', create=True)
    target = parent / digest(data)
    with tarfile.open(appdir / ARCHIVE, 'r:gz') as checked_archive:
        selected = [member for member in checked_archive.getmembers()
                    if PurePosixPath(member.name).name == 'publication-manifest.json'
                    and len(PurePosixPath(member.name).parts) == 2]
        if len(selected) != 1 or not selected[0].isfile() or selected[0].size > 8 * 1024 * 1024:
            raise ValueError('Source template has no unique bounded manifest')
        with checked_archive.extractfile(selected[0]) as manifest_stream:
            expected_manifest = manifest_stream.read(8 * 1024 * 1024 + 1)
    if target.exists() or target.is_symlink():
        verify_source(target, expected_manifest)
        return target
    with tempfile.TemporaryDirectory(prefix='.source-', dir=parent) as temp:
        stage = Path(temp) / 'source'
        stage.mkdir()
        with tarfile.open(appdir / ARCHIVE, 'r:gz') as archive:
            members = archive.getmembers()
            if not members or len(members) > 4096:
                raise ValueError('Invalid source template member count')
            seen, total, prefix = set(), 0, None
            for member in members:
                relative(member.name)
                parts = PurePosixPath(member.name).parts
                if len(parts) < 2 or not member.isfile() or member.mode not in (0o644, 0o755):
                    raise ValueError('Source template contains a nonordinary member')
                if prefix is None:
                    prefix = parts[0]
                if parts[0] != prefix:
                    raise ValueError('Source template has multiple roots')
                name = '/'.join(parts[1:])
                if name in seen or member.size > 8 * 1024 * 1024:
                    raise ValueError('Source template member duplicated or oversized')
                seen.add(name)
                total += member.size
                if total > 128 * 1024 * 1024:
                    raise ValueError('Source template expanded size is too large')
                output = stage / name
                output.parent.mkdir(parents=True, exist_ok=True)
                incoming = archive.extractfile(member)
                if incoming is None:
                    raise ValueError('Source template member is unreadable')
                with incoming:
                    content = incoming.read(member.size + 1)
                if len(content) != member.size:
                    raise ValueError('Source template member size changed')
                output.write_bytes(content)
                output.chmod(member.mode)
        verify_source(stage, expected_manifest)
        stage.rename(target)
    return target


def verify_source(source, expected_manifest):
    # Use only the embedded source guard, after its file identities are checked.
    if regular(source / 'publication-manifest.json', 8 * 1024 * 1024) != expected_manifest:
        raise ValueError('Cached source manifest differs from bundled archive')
    manifest = document(source / 'publication-manifest.json', 8 * 1024 * 1024)
    if manifest.get('schema') != 1 or manifest.get('project') != 'Monado II':
        raise ValueError('Invalid authored source manifest')
    identities = {name: {**value, 'mode': 0o755 if name.endswith('.sh') else 0o644}
                  for name, value in manifest.get('files', {}).items()}
    verify(source, identities, extras=('publication-manifest.json',))
    import importlib.util
    spec = importlib.util.spec_from_file_location('monado_builder_source_guard', source / 'tools/publication_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    problems = guard.verify_tree(source)
    if problems:
        raise ValueError('Authored source template rejected: ' + '; '.join(problems))


def stop(process, timeout=12):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)



def backend_module(source):
    spec = importlib.util.spec_from_file_location('monado_builder_trusted_backend', source / 'tools/builder_backend.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def adjacent_workspace(*, required=True):
    image = Path(os.environ.get('APPIMAGE', '')).absolute()
    regular(image)
    workspace = ordinary_dir(image.parent)
    port = workspace / 'Monado_Linux'
    if not port.exists() and not port.is_symlink():
        if required:
            raise ValueError('Inherited launcher profile/check requires the adjacent Monado_Linux workspace')
        return None
    # A present but malformed/linked adjacent port must fail closed. A moved
    # standalone image with no adjacent port can use its registered owner or
    # start first-run setup; no workspace is guessed from unrelated folders.
    ordinary_dir(port)
    return workspace


def legacy_command(source, workspace, state_root=None, *, dry_run=False):
    """Resolve managed payload/profile with the same checked backend as setup.

    No broker/session/registry object is constructed for --dry-run or an
    explicit inherited --state-root. The unchanged native launch wrapper owns
    the complete receipt/input/dependency/profile validation.
    """
    backend = backend_module(source)
    selector = object.__new__(backend.Broker)
    # Before activation an adjacent candidate must validate its own artifacts,
    # not the owner's still-selected old version. Normal opens follow active.
    selected = selector.installation(workspace, follow_active=not dry_run)
    state = state_root.absolute() if state_root is not None else selected['state']
    # The checked native wrapper imports sibling run_linux.py. Its ordinary
    # script directory must remain importable; use the broker's sanitized -B
    # invocation rather than Python -I, which removes that directory.
    command = selector.launcher_command(dict(selected, state=state))
    if dry_run:
        command.append('--dry-run')
    return command, selected


def dry_run(appdir, manifest, args):
    # Existing update clients require a no-window/no-profile-write check. A
    # temporary authored-source extraction is sufficient; no persistent builder
    # registry, private Python cache or real user installation is modified.
    selected = None
    if manifest.get('migration') == {'adjacent_workspace': True}:
        with tempfile.TemporaryDirectory(prefix='monado-builder-check-') as temp:
            source = unpack_source(appdir, Path(temp), manifest['files'][ARCHIVE])
            command, selected = legacy_command(source, adjacent_workspace(), args.state_root, dry_run=True)
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise ValueError('Updated native launcher check failed: ' + result.stderr[-3000:] + result.stdout[-3000:])
    print(json.dumps(dict(status='passed', kind='standalone-builder',
        migration_checked=selected is not None, game_build_performed=False,
        installation_registered=False, profile_writes=False), sort_keys=True))
    return 0


def run(appdir, args):
    manifest = validate_image(appdir)
    if args.state_root is not None and manifest.get('migration') != {'adjacent_workspace': True}:
        raise ValueError('--state-root is supported only by an inherited installation image')
    if args.dry_run:
        return dry_run(appdir, manifest, args)
    state = ordinary_dir(args.data_dir or Path(os.environ.get('XDG_DATA_HOME',
        str(Path.home() / '.local/share'))) / 'monado-ii-builder', create=True)
    lockpath = state / '.materialize.lock'
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(lockpath, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        python, identity = copy_runtime(appdir, state, manifest['files'])
        source = unpack_source(appdir, state, manifest['files'][ARCHIVE])
    finally:
        os.close(fd)
    if args.self_check:
        # A real relocated interpreter/venv probe is packaging validation, never a
        # game build or generator invocation. It does not register an installation.
        probe_code = 'import ssl,ctypes,venv,json,sys,sysconfig;print(json.dumps(dict(prefix=sys.prefix,base=sys.base_prefix,executable=sys.executable,base_executable=sys._base_executable,soabi=sysconfig.get_config_var("SOABI"),ssl=ssl.OPENSSL_VERSION,cert_file=ssl.get_default_verify_paths().cafile)))'
        clean = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        result = subprocess.run([python / 'bin/python3.14', '-I', '-B', '-c', probe_code],
            capture_output=True, text=True, timeout=30, env=clean)
        if result.returncode:
            raise ValueError('Private Python check failed: ' + result.stderr[-2000:])
        with tempfile.TemporaryDirectory(prefix='.venv-probe-', dir=state) as temporary:
            venv = Path(temporary) / 'venv'
            create = subprocess.run([python / 'bin/python3.14', '-I', '-B', '-m', 'venv', '--without-pip', venv],
                capture_output=True, text=True, timeout=30, env=clean)
            if create.returncode:
                raise ValueError('Private Python venv creation failed: ' + create.stderr[-2000:])
            checked = subprocess.run([venv / 'bin/python', '-I', '-B', '-c', probe_code],
                capture_output=True, text=True, timeout=30, env=clean)
            if checked.returncode:
                raise ValueError('Private Python venv probe failed: ' + checked.stderr[-2000:])
            venv_probe = json.loads(checked.stdout)
            if (Path(venv_probe['prefix']) != venv or Path(venv_probe['base']) != python or
                    Path(venv_probe['base_executable']).resolve() != python / 'bin/python3.14'):
                raise ValueError('Private Python venv does not retain its stable runtime wrapper')
        print(json.dumps(dict(status='passed', kind='standalone-builder',
            runtime=str(python), runtime_identity=identity, source=str(source),
            source_manifest_sha256=digest(regular(source / 'publication-manifest.json')),
            probe=json.loads(result.stdout), venv_probe=venv_probe, contains_game_files=False,
            game_build_performed=False, installation_registered=False), sort_keys=True))
        return 0
    sessions = ordinary_dir(state / 'sessions', create=True)
    session = Path(tempfile.mkdtemp(prefix=time.strftime('%Y%m%dT%H%M%S-'), dir=sessions))
    environment = os.environ.copy()
    environment.pop('PYTHONHOME', None)
    environment.pop('PYTHONPATH', None)
    environment.pop('LD_PRELOAD', None)
    environment['LD_LIBRARY_PATH'] = str(python / 'lib') + ':' + str(appdir / 'usr/lib')
    backendlog = (session / 'backend-console.txt').open('xb')
    migration_workspace = None
    if manifest.get('migration') == {'adjacent_workspace': True} and not args.setup and args.headless_frames is None:
        migration_workspace = adjacent_workspace(required=args.state_root is not None)
    if migration_workspace is not None:
        workspace = migration_workspace
        if args.state_root is not None:
            command, _ = legacy_command(source, workspace, args.state_root)
            subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                stdout=backendlog, stderr=subprocess.STDOUT, start_new_session=True)
            backendlog.close()
            return 0
        trusted_backend = backend_module(source)
        broker = trusted_backend.Broker(source, session, state)
        broker.adopt({'id': 'migration-adopt', 'output': str(workspace)})
        if broker.open({'id': 'migration-open'}) is not False:
            backendlog.close()
            return 0
        # A valid inherited installation can have missing game input. Adopt
        # retains its owner and recovery status; show the same Locate wizard
        # used by registered standalone installs instead of exiting silently.
    if not args.setup and args.headless_frames is None and migration_workspace is None:
        attempt = subprocess.run([python / 'bin/python3.14', '-I', '-B', source / 'tools/builder_backend.py',
            '--open-registered', '--session', session, '--source', source, '--state', state],
            env=environment, stdout=backendlog, stderr=subprocess.STDOUT, timeout=90)
        if attempt.returncode == 0:
            backendlog.close()
            return 0
    backend = subprocess.Popen([python / 'bin/python3.14', '-I', '-B', source / 'tools/builder_backend.py',
        '--serve', '--session', session, '--source', source, '--state', state],
        env=environment, stdout=backendlog, stderr=subprocess.STDOUT)
    gui = None
    try:
        command = [appdir / 'usr/bin/monado-builder', '--session', session]
        if args.headless_frames is not None:
            command += ['--headless-frames', str(args.headless_frames)]
        if args.screenshot:
            command += ['--screenshot', str(args.screenshot.absolute())]
        gui = subprocess.Popen(command, env=environment)
        def interrupted(_sig, _frame):
            if gui.poll() is None:
                gui.terminate()
        with contextlib.suppress(ValueError):
            signal.signal(signal.SIGTERM, interrupted)
            signal.signal(signal.SIGINT, interrupted)
        reported_worker_exit = False
        while gui.poll() is None:
            if backend.poll() is not None and not reported_worker_exit:
                reported_worker_exit = True
                request_id = ''
                with contextlib.suppress(OSError, ValueError):
                    request_id = document(session / 'request.json').get('id', '')
                failed = dict(schema=1, request_id=request_id, phase='failed',
                    message='Setup worker stopped. Close and reopen Monado II to retry.',
                    detail='The complete worker log is retained in this setup session.',
                    log=str(session / 'backend-console.txt'), progress=0,
                    can_open=False, worker_stopped=True)
                temporary = session / '.supervisor-status.json'
                temporary.write_bytes(encoded(failed))
                temporary.replace(session / 'status.json')
            time.sleep(.05)
        return gui.returncode
    finally:
        if gui is not None and gui.poll() is None:
            stop(gui)
        stop(backend, timeout=45)
        backendlog.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, help='explicit isolated builder registry/tools directory')
    parser.add_argument('--dry-run', action='store_true', help='verify the image and inherited native selection without GUI or profile/registry writes')
    parser.add_argument('--state-root', type=Path, help='preserve an inherited explicit original-owner profile')
    parser.add_argument('--setup', action='store_true', help='show setup even when a valid build is registered')
    parser.add_argument('--self-check', action='store_true', help='verify bundled tools/source without GUI or game build')
    parser.add_argument('--headless-frames', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--screenshot', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.state_root is not None and args.headless_frames is not None:
        parser.error('--state-root cannot be combined with hidden setup previews')
    if args.state_root is not None and args.setup:
        parser.error('--state-root is an inherited launcher profile; it cannot select setup storage')
    if args.headless_frames is not None and not 1 <= args.headless_frames <= 1000:
        parser.error('headless frame bound must be 1..1000')
    try:
        return run(Path(__file__).resolve().parents[3], args)
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        parser.exit(1, 'Monado II setup could not start: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
