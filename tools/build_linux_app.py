#!/usr/bin/env python3
"""Build Monado II locally and produce the workspace's launcher AppImage.

One explicit invocation verifies the player's existing extracted input, downloads
locked build dependencies, generates/compiles locally and packages only the
launcher. Internal updater payload builds can omit the launcher and AppImage.
No game or graphical window is opened. Every run uses fresh outputs; previous
builds, saves and a known-good launcher AppImage are preserved.
"""
import argparse
import codecs
import contextlib
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'Monado-II-x86_64.AppImage'
# Native receipts include every compiler command and immutable absolute path.
# LINUX-054 measured a valid 408-command receipt at 2,503,473 bytes in a nested
# managed install; keep this bounded without rejecting supported long paths.
MAX_BUILD_RECEIPT = 8 * 1024 * 1024
REQUIRED_TOOLS = ('bash', 'pkg-config', 'dpkg-deb', 'readelf', 'mksquashfs', 'unsquashfs')
BUILD_PATH = '/usr/bin:/bin'
DLSS_REQUIRED_TOOLS = ('nm',)
BWRAP = Path('/usr/bin/bwrap')
_run_spec = importlib.util.spec_from_file_location('monado_builder_run_linux', ROOT / 'Monado_Linux/scripts/run_linux.py')
run_linux = importlib.util.module_from_spec(_run_spec)
_run_spec.loader.exec_module(run_linux)
install_layout = run_linux.install_layout
runtime_check = run_linux.runtime_check


class BuildError(RuntimeError):
    pass


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ordinary(path, *, directory=False, missing=False):
    path = Path(path).absolute()
    if path.resolve() != path or '..' in path.parts:
        raise BuildError('output/source path must be canonical without symlinks: ' + str(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise BuildError('missing path: ' + str(current)) from None
        if stat.S_ISLNK(info.st_mode):
            raise BuildError('managed path must not be a symlink: ' + str(current))
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise BuildError('path parent is not a directory: ' + str(current))
        if current == path and ((directory and not stat.S_ISDIR(info.st_mode)) or
                (not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))):
            raise BuildError('expected ordinary ' + ('directory: ' if directory else 'single-link file: ') + str(path))
    return path


def json_file(path):
    ordinary(path)
    if path.stat().st_size > MAX_BUILD_RECEIPT:
        raise BuildError('oversized build receipt: ' + str(path))
    try:
        return json.loads(path.read_text())
    except (UnicodeError, ValueError) as error:
        raise BuildError('invalid build receipt: ' + str(path)) from error


def image_pair(path):
    """Only replace a known, intact local image/receipt pair, never unknown files."""
    receipt = Path(str(path) + '.receipt.json')
    ordinary(path, missing=True)
    ordinary(receipt, missing=True)
    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise BuildError('incomplete existing AppImage/receipt pair; preserve it and inspect: ' + str(path))
    with path.open('rb') as stream:
        header = stream.read(12)
    if header[:4] != b'\x7fELF' or header[8:11] != b'AI\x02':
        raise BuildError('expected a verified type-2 AppImage: ' + str(path))
    document = json_file(receipt)
    if document.get('status') != 'passed' or document.get('sha256') != digest(path):
        raise BuildError('existing AppImage does not match its successful receipt; refusing to replace it')
    return document


def validate_features(*, dlss, framegen):
    if type(dlss) is not bool or (framegen is not None and type(framegen) is not bool):
        raise BuildError('build feature selections must be booleans (or an unspecified frame-generation selection)')
    # Normal builds include the experimental provider; the user's runtime
    # checkbox remains off by default. None preserves the explicit DLSS optout.
    if framegen is None:
        framegen = dlss
    if framegen and not dlss:
        raise BuildError('--framegen requires DLSS/DLAA support; it cannot be combined with --without-dlss')
    return framegen


def existing_framegen_sdk(port):
    """Verify this workspace's SDK without fetching, compiling or loading it."""
    active = ordinary(port / '.deps/fsr/active-build.txt', missing=True)
    if not active.exists():
        return None
    recipe = ordinary(port / 'scripts/setup_linux_fsr.py')
    spec = importlib.util.spec_from_file_location('monado_builder_fsr_setup', recipe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.verify_existing()
    except (OSError, ValueError, RuntimeError) as error:
        raise BuildError('Existing native frame-generation SDK failed verification; preserve it and inspect before retrying: ' + str(error)) from error


def validate_reused_game(port, binary, state, *, dlss, framegen=None):
    """Retain an original successful build; never relocate or rewrite its receipt."""
    framegen = validate_features(dlss=dlss, framegen=framegen)
    binary = ordinary(binary)
    install_layout.build_port(port, binary)
    receipt = json_file(binary.parent / 'receipt.json')
    if (receipt.get('status') != 'passed' or receipt.get('artifact_kind') == 'linux-launcher' or
            not isinstance(receipt.get('generated'), dict) or not receipt['generated'] or receipt.get('errors')):
        raise BuildError('--reuse-game requires a successful complete generated-game receipt')
    if type(receipt.get('dlss_enabled')) is not bool or receipt['dlss_enabled'] != dlss:
        raise BuildError('reused game DLSS flag differs from the requested build; preserve the existing feature selection')
    if type(receipt.get('framegen_enabled')) is not bool or receipt['framegen_enabled'] != framegen:
        raise BuildError('reused game frame-generation flag differs from the requested build; preserve the existing feature selection')
    before = receipt.get('sources_before')
    if not isinstance(before, dict) or not before or before != receipt.get('sources_after'):
        raise BuildError('reused game has no stable native source snapshot')
    # The release classifier separately checks generator/profile/launch protocol
    # changes. This builder also refuses changed or newly added native inputs.
    required = {'scripts/build_linux.py', 'scripts/linux_runtime_check.py',
                'scripts/linux_runtime_graph.py', 'graphics-deps-linux.lock.json', 'requirements-linux.lock',
                'tools/gen_smaa_inc.py', 'dlss-linux.lock.json', 'scripts/setup_linux_dlss.py',
                'fsr-linux.lock.json', 'scripts/setup_linux_fsr.py'}
    native = {p.relative_to(port).as_posix() for name in ('runtime', 'third_party')
              for p in (port / name).rglob('*') if p.is_file() and
              p.suffix in ('.c', '.cpp', '.h', '.hpp', '.inc', '.hlsl')}
    icon = port / 'local_assets/monado-icon.png'
    if icon.exists() or icon.is_symlink():
        required.add('local_assets/monado-icon.png')
    if set(before) != required | native:
        raise BuildError('reused game native source closure differs; a full local game build is required')
    for name, expected in before.items():
        source = ordinary(port / name)
        if not source.is_relative_to(port) or digest(source) != expected:
            raise BuildError('reused game native source differs: ' + name + '; a full local game build is required')
    launch = run_linux.plan(binary, state, port=port)
    selected = Path(launch['input'])
    expected_input = receipt.get('input', {})
    exefs = {p.name: digest(p) for p in sorted((selected / 'exefs').iterdir()) if p.is_file()}
    if expected_input.get('path') != str(selected) or expected_input.get('exefs') != exefs:
        raise BuildError('reused game input differs from its build receipt')
    return {'path': str(binary), 'sha256': launch['binary_sha256'],
            'receipt_sha256': digest(binary.parent / 'receipt.json'), 'build_port': launch['build_port']}


def validate_linux_library_root(root):
    """Reject source roots that cannot fit Linux's library search-path grammar."""
    if ':' in str(root) or any(ord(char) < 32 for char in str(root)):
        raise BuildError('Linux library search paths cannot contain colons or control characters; use another source folder')


def layout(root, jobs, *, require_input=True, identity=None, dlss=True, reuse_game=None, framegen=None, game_only=False):
    framegen = validate_features(dlss=dlss, framegen=framegen)
    if game_only and reuse_game is not None:
        raise BuildError('--game-only cannot reuse a game; it creates a fresh game payload')
    root = ordinary(root, directory=True)
    validate_linux_library_root(root)
    port = ordinary(root / 'Monado_Linux', directory=True)
    install_layout.binding(port)
    for name in ('build', 'generated', 'runs', '.deps'):
        ordinary(port / name, directory=True, missing=True)
    for name in ('runs/local-build', '.deps/metadata'):
        ordinary(port / name, directory=True, missing=True)
    if not game_only:
        image_pair(root / IMAGE)
    selected = root / 'game_files'
    try:
        source = selected.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        source = selected
    valid = source.is_dir() and (source / 'exefs').is_dir() and (source / 'romfs').is_dir()
    if require_input and not valid:
        raise BuildError('Put your own already-extracted DE 2.0.0 files in game_files/exefs and game_files/romfs '\
                         'next to Build_Monado_II.sh. An existing game_files directory may be linked instead. '\
                         'No files will be moved or downloaded.')
    if source == port or source.is_relative_to(port) or port.is_relative_to(source):
        raise BuildError('game input must be disjoint from Linux build and runtime directories')
    if require_input:
        install_layout.shared_input(port)
    identity = identity or ('local-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    if not identity or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in identity):
        raise BuildError('unsafe build identity')
    paths = dict(root=root, port=port, input=source, run=port / 'runs/local-build' / identity,
                 generated=port / 'generated' / identity, game=port / 'build' / (identity + '-game') / 'xcde-linux',
                 launcher=port / 'build' / (identity + '-launcher') / 'monado-launcher',
                 image=port / 'build' / (identity + '-appimage') / IMAGE, published=root / IMAGE,
                 state=install_layout.profile_port(port) / 'play/launcher')
    if game_only:
        for name in ('launcher', 'image', 'published'):
            paths.pop(name)
        paths['payload_receipt'] = port / '.deps/metadata/game-payload.json'
        ordinary(paths['payload_receipt'], missing=True)
        if paths['payload_receipt'].exists():
            raise BuildError('game payload receipt already exists; use a fresh immutable payload workspace')
    if reuse_game is not None:
        paths['game'] = ordinary(reuse_game)
        validate_reused_game(port, paths['game'], paths['state'], dlss=dlss, framegen=framegen)
    for name in ('run', 'generated', 'game', *(() if game_only else ('launcher', 'image'))):
        if reuse_game is not None and name in ('game', 'generated'):
            continue
        path = paths[name]
        if name in ('game', 'launcher', 'image'):
            path = path.parent
        ordinary(path, directory=True, missing=True)
        if path.exists():
            raise BuildError('build outputs must be fresh: ' + str(path))
    python = port / '.venv/bin/python'
    commands = [
        ('check-input', [sys.executable, '-I', '-B', port / 'tools/extract/check_dump.py', source]),
        ('install-tools', [sys.executable, '-I', '-B', root / 'tools/setup_linux_tools.py', '--port', port, '--install']),
        ('check-tools', [sys.executable, '-I', '-B', root / 'tools/setup_linux_tools.py', '--port', port, '--check']),
        ('graphics-dependencies', [python, '-B', port / 'scripts/setup_linux_graphics.py']),
    ]
    if dlss:
        commands.append(('native-dlss-dependency', [python, '-B', port / 'scripts/setup_linux_dlss.py']))
    if framegen and reuse_game is None:
        sdk = existing_framegen_sdk(port)
        recipe = port / 'scripts/setup_linux_fsr.py'
        if sdk is None:
            paths['framegen_sdk'] = ordinary(port / '.deps/fsr/build' / identity, directory=True, missing=True)
            if paths['framegen_sdk'].exists():
                raise BuildError('frame-generation SDK build output must be fresh: ' + str(paths['framegen_sdk']))
            commands += [('framegen-source', [python, '-B', recipe, '--fetch']),
                         ('native-framegen-dependency', [python, '-B', recipe, '--build', '--output', paths['framegen_sdk'], '--jobs', jobs])]
        else:
            paths['framegen_sdk'] = ordinary(Path(sdk['library_path']).parent, directory=True)
            commands.append(('native-framegen-dependency', [python, '-B', recipe]))
    commands.append(('check-runtime-dependencies', [python, '-B', port / 'scripts/linux_runtime_check.py',
                     '--probe', '--port', port, '--output', paths['run'] / 'runtime-probe']))
    if reuse_game is None:
        commands += [
            ('generate-game', [python, '-B', port / 'tools/gen_all.py', '--exefs', source / 'exefs', '--out', paths['generated'], '--simd', 'c']),
            ('build-game', [python, '-B', port / 'scripts/build_linux.py', '--generated', paths['generated'], '--output', paths['game'].parent, '--jobs', jobs,
                            *(['--dlss'] if dlss else []), *(['--framegen'] if framegen else [])]),
        ]
    if not game_only:
        commands += [
            ('build-launcher', [python, '-B', port / 'scripts/build_launcher_linux.py', '--output', paths['launcher'].parent, '--jobs', jobs]),
            ('check-launcher', [python, '-B', port / 'scripts/launcher_linux.py', '--launcher-executable', paths['launcher'], '--game-executable', paths['game'], '--state-root', paths['state'], '--dry-run']),
            ('package-appimage', [sys.executable, '-I', '-B', root / 'tools/build_launcher_appimage.py', '--launcher-executable', paths['launcher'], '--game-executable', paths['game'], '--output', paths['image']]),
        ]
    return paths, [(name, list(map(str, command))) for name, command in commands]


def _preflight(*, dlss=True, game_only=False):
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or sys.version_info[:2] != (3, 14):
        raise BuildError('Build_Monado_II.sh requires Linux x86-64 and Python 3.14')
    required = tuple(name for name in REQUIRED_TOOLS if not game_only or name not in ('mksquashfs', 'unsquashfs'))
    required += DLSS_REQUIRED_TOOLS if dlss else ()
    missing = [name for name in required if shutil.which(name, path=BUILD_PATH) is None]
    if missing:
        raise BuildError('Missing host build tools: ' + ', '.join(missing) + '. Install these with your distribution; '\
                         'mksquashfs/unsquashfs are supplied by squashfs-tools. Background build stages never install packages.')
    if dlss and (not BWRAP.is_file() or not os.access(BWRAP, os.X_OK)):
        raise BuildError('DLSS/DLAA builds require /usr/bin/bwrap from bubblewrap for the existing private '
                         'runtime namespace. Install bubblewrap, or explicitly use --without-dlss. '
                         'No system packages are installed by this script.')
    if dlss:
        try:
            runtime_check.discover_gnu_cxx()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            raise BuildError('DLSS/DLAA requires a compatible native GNU C++ runtime: ' + str(error) +
                             '. Install your distribution runtime, or explicitly use --without-dlss.') from error


def prerequisite_diagnostic(*, dlss=True, game_only=False):
    """[XCDE] LINUX-066: managed builds may inspect prerequisites, never install."""
    try:
        path = ROOT / 'tools/linux_prerequisites.py'
        specification = importlib.util.spec_from_file_location('_monado_prerequisite_report', path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        report = module.inspect_environment(ROOT, without_dlss=not dlss, game_only=game_only)
        return module.format_report(report)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, ImportError, AttributeError, TypeError):
        # The original failure stays authoritative if the optional explanation
        # cannot be produced. No missing diagnostic may weaken a build check.
        return ''


def preflight(*, dlss=True, game_only=False):
    try:
        _preflight(dlss=dlss, game_only=game_only)
    except BuildError as error:
        detail = prerequisite_diagnostic(dlss=dlss, game_only=game_only)
        raise BuildError(str(error) + ('\n' + detail if detail else '')) from error


def prepare_input_layout(root):
    """Populate only a newly created empty input directory, never an existing link."""
    root = ordinary(root, directory=True)
    selected = root / 'game_files'
    try:
        selected.lstat()
        return
    except FileNotFoundError:
        pass
    # The Linux entry preflight has already run. Directory descriptors prevent a
    # concurrent replacement with a link from redirecting these empty mkdirs.
    selected.mkdir(mode=0o700)
    descriptor = os.open(selected, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.mkdir('exefs', mode=0o700, dir_fd=descriptor)
        os.mkdir('romfs', mode=0o700, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    raise BuildError('Created empty game_files/exefs and game_files/romfs next to Build_Monado_II.sh. '\
                     'Put your own already-extracted DE 2.0.0 files there, then run the same build command again. '\
                     'No dependencies or game files were downloaded.')


def write_json(path, document):
    temporary = path.with_name(path.name + '.partial')
    ordinary(temporary, missing=True)
    with temporary.open('w') as stream:
        stream.write(json.dumps(document, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextlib.contextmanager
def build_lock(port):
    import fcntl  # Linux-only execution; source fixtures are also run on Windows.
    metadata = ordinary(port / '.deps/metadata', directory=True, missing=True)
    metadata.mkdir(parents=True, exist_ok=True)
    path = ordinary(metadata / 'appimage-build.lock', missing=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BuildError('build lock is not an ordinary single-link file')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BuildError('Another Monado II build is already running in this folder') from None
        yield
    finally:
        os.close(descriptor)


def child_id(pid):
    """Kernel process identity/ancestry, as used by the precompile supervisor."""
    try:
        data = Path('/proc', str(pid), 'stat').read_text()
        fields = data[data.rfind(')') + 2:].split()
        return (pid, int(fields[19])), int(fields[1]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants():
    pending, found = [os.getpid()], {}
    for parent in pending:
        try:
            threads = list(Path('/proc', str(parent), 'task').iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        if len(threads) > 256:
            raise BuildError('build worker thread limit exceeded')
        for thread in threads:
            try:
                children = (thread / 'children').read_text().split()
            except (FileNotFoundError, ProcessLookupError):
                continue
            for word in children:
                pid = int(word)
                if pid in found:
                    continue
                item = child_id(pid)
                if item is None or item[1] != parent:
                    continue
                found[pid] = item
                pending.append(pid)
                if len(found) > 256:
                    raise BuildError('build worker process limit exceeded')
    return found


def signal_owned(owned, number):
    """Pidfds and a fresh kernel starttime check avoid PID-reuse/name guesses."""
    for pid, (identity, _parent, state) in owned.items():
        if state == 'Z':
            continue
        try:
            descriptor = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            continue
        try:
            current = child_id(pid)
            if current is not None and current[0] == identity and current[2] != 'Z':
                signal.pidfd_send_signal(descriptor, number)
        except ProcessLookupError:
            pass
        finally:
            os.close(descriptor)


def reap_owned(child):
    if child is not None:
        child.poll()  # Preserve Popen's direct-child exit status.
    for pid, item in descendants().items():
        if (child is None or pid != child.pid) and item[2] == 'Z' and item[1] == os.getpid():
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
    return descendants()


@contextlib.contextmanager
def owned_children():
    if sys.platform != 'linux' or not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise BuildError('Linux pidfd process ownership is required for local build supervision')
    if descendants():
        raise BuildError('build supervisor must not own unrelated existing children')
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'cannot enable build child subreaper')
    try:
        yield
    finally:
        # Never silently abandon adopted workers or call a stage successful while
        # they remain. A kernel-uninterruptible worker is a reported hard failure.
        remaining = descendants()
        if remaining:
            raise BuildError('owned build workers remain after cleanup: ' + repr(sorted(remaining)))
        if libc.prctl(36, previous.value, 0, 0, 0):
            raise OSError(ctypes.get_errno(), 'cannot restore build child subreaper')


def stop_owned(child, *, grace=5, timeout=30):
    started = time.monotonic()
    signal_owned(reap_owned(child), signal.SIGINT)
    while True:
        owned = reap_owned(child)
        if not owned:
            if child is not None:
                child.wait()
            return
        elapsed = time.monotonic() - started
        if elapsed >= grace:
            signal_owned(owned, signal.SIGKILL)
        if elapsed >= timeout:
            raise BuildError('owned build workers did not exit within the 30-second cleanup bound: ' + repr(sorted(owned)))
        time.sleep(0.02)


def execute(command, cwd, log, *, cancel_grace=5, cleanup_timeout=30):
    if not 0 < cancel_grace <= cleanup_timeout <= 30:
        raise BuildError('build cleanup requires 0 < grace <= timeout <= 30 seconds')
    environment = {'PATH': BUILD_PATH, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'PYTHONDONTWRITEBYTECODE': '1'}
    with owned_children(), log.open('x') as output, selectors.DefaultSelector() as selector:
        pending = []
        def request(number, _frame):
            if not pending:
                pending.append(number)
        handlers = {number: signal.signal(number, request) for number in
                    (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        child = None
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            child = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True, close_fds=True)
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                owned = reap_owned(child)
                if pending:
                    raise KeyboardInterrupt
                if child.returncode is not None and not owned and not selector.get_map():
                    return child.wait()
                if child.returncode is not None and any(item[2] != 'Z' for item in owned.values()):
                    raise BuildError('build stage exited while owned workers were still running')
                for key, _mask in selector.select(timeout=0.05):
                    data = os.read(key.fileobj.fileno(), 65536)
                    text = decoder.decode(data, final=not data)
                    if text:
                        output.write(text)
                        output.flush()
                        print(text, end='', flush=True)
                    if not data:
                        selector.unregister(key.fileobj)
        finally:
            try:
                if child is not None and descendants():
                    stop_owned(child, grace=cancel_grace, timeout=cleanup_timeout)
                elif child is not None:
                    child.wait()
            finally:
                if child is not None:
                    child.stdout.close()
                for number, handler in handlers.items():
                    signal.signal(number, handler)


def copy_new(source, destination):
    ordinary(source)
    ordinary(destination, missing=True)
    with source.open('rb') as incoming, destination.open('xb') as output:
        shutil.copyfileobj(incoming, output)
        output.flush()
        os.fsync(output.fileno())
    destination.chmod(source.stat().st_mode & 0o777)
    if digest(source) != digest(destination):
        raise BuildError('copy identity changed: ' + str(source))


def publish(paths):
    """Preserve prior pair; caller rolls back if the final headless check fails."""
    source, target = paths['image'], paths['published']
    if image_pair(source) is None:
        raise BuildError('packager did not produce a verified AppImage/receipt pair')
    previous = image_pair(target)
    names = [IMAGE, IMAGE + '.receipt.json']
    backup = source.parent / 'previous'
    backup.mkdir()
    if previous is not None:
        for name in names:
            copy_new(target.parent / name, backup / name)
        image_pair(backup / IMAGE)
    staged = []
    for name in names:
        temporary = target.parent / ('.' + name + '-' + paths['run'].name + '.partial')
        copy_new(source.parent / name, temporary)
        staged.append(temporary)
    try:
        for temporary, name in zip(staged, names):
            temporary.replace(target.parent / name)
        image_pair(target)
    except BaseException:
        restore(paths, backup, previous is not None)
        raise
    return backup, previous is not None


def restore(paths, backup, had_previous):
    target = paths['published']
    for name in (IMAGE, IMAGE + '.receipt.json'):
        current = target.parent / name
        if current.exists():
            ordinary(current)
            current.rename(paths['image'].parent / ('failed-' + name))
        if had_previous:
            copy_new(backup / name, current)
    if had_previous:
        image_pair(target)


def build(root=ROOT, jobs=4, *, runner=execute, locker=build_lock, identity=None, dlss=True, reuse_game=None, framegen=None, game_only=False):
    framegen = validate_features(dlss=dlss, framegen=framegen)
    if game_only and reuse_game is not None:
        raise BuildError('--game-only cannot reuse a game; it creates a fresh game payload')
    preflight(dlss=dlss, game_only=game_only)
    prepare_input_layout(root)
    paths, commands = layout(root, jobs, identity=identity, dlss=dlss, reuse_game=reuse_game, framegen=framegen, game_only=game_only)
    with locker(paths['port']):
        # Recheck after obtaining the lease; another completed build may now be
        # present, but its known pair will be preserved rather than overwritten.
        if not game_only:
            image_pair(paths['published'])
        paths['run'].mkdir(parents=True)
        receipt_path = paths['run'] / 'receipt.json'
        receipt = dict(schema=1, status='running', scope='local game payload; no game/UI execution' if game_only else 'local game build and launcher-only AppImage; no game/UI execution',
                       started_utc=datetime.now(timezone.utc).isoformat(), jobs=jobs,
                       dlss_enabled=dlss, framegen_enabled=framegen,
                       reused_game=validate_reused_game(paths['port'], paths['game'], paths['state'], dlss=dlss, framegen=framegen) if reuse_game is not None else None,
                       paths={name: str(path) for name, path in paths.items()}, commands=[])
        write_json(receipt_path, receipt)
        print('Downloads: locked Python/compiler and Ubuntu development packages.' + ('' if game_only else ' Also the pinned AppImage runtime.')
              + (' The default DLSS/DLAA build also downloads the pinned official NVIDIA SDK into this workspace.' if dlss else
                 ' DLSS/DLAA support is explicitly omitted (--without-dlss).')
              + (' Experimental frame-generation support is included; a missing SDK is fetched and built locally, while a verified local SDK is reused. The runtime checkbox stays off by default.' if framegen else '') + '\n'
              'Game files are never downloaded. Existing input and saves are preserved.\n'
              'Fresh build logs: ' + str(paths['run']), flush=True)
        backup = None
        total = len(commands) + (0 if game_only else 1)
        try:
            for number, (name, command) in enumerate(commands, 1):
                log = paths['run'] / (f'{number:02d}-' + name + '.log')
                entry = dict(name=name, argv=command, cwd=str(paths['port']), log=str(log), status='running')
                receipt['commands'].append(entry)
                write_json(receipt_path, receipt)
                print(f'[{number}/{total}] {name}', flush=True)
                started = time.monotonic()
                code = runner(command, paths['port'], log)
                entry.update(exit=code, seconds=time.monotonic() - started, status='passed' if code == 0 else 'failed')
                write_json(receipt_path, receipt)
                if code:
                    raise BuildError(f'{name} failed (exit {code}). Log: {log}')
            if reuse_game is not None and validate_reused_game(paths['port'], paths['game'], paths['state'], dlss=dlss, framegen=framegen) != receipt['reused_game']:
                raise BuildError('reused game receipt or identity changed during launcher build; previous image is preserved')
            if game_only:
                selected = validate_reused_game(paths['port'], paths['game'], paths['state'], dlss=dlss, framegen=framegen)
                run_linux.validate_runtime(run_linux.plan(paths['game'], paths['state'], port=paths['port']))
                receipt.update(status='passed', game=selected)
            else:
                backup = publish(paths)
                log = paths['run'] / f'{len(commands) + 1:02d}-check-appimage.log'
                command = [str(paths['published']), '--appimage-extract-and-run', '--dry-run']
                entry = dict(name='check-appimage', argv=command, cwd=str(paths['root']), log=str(log), status='running')
                receipt['commands'].append(entry)
                write_json(receipt_path, receipt)
                print(f'[{len(commands) + 1}/{total}] check-appimage (no window or game)', flush=True)
                code = runner(command, paths['root'], log)
                entry.update(exit=code, status='passed' if code == 0 else 'failed')
                if code:
                    raise BuildError(f'AppImage startup check failed (exit {code}). Log: {log}')
                receipt.update(status='passed', appimage_sha256=digest(paths['published']))
        except BaseException as error:
            if backup is not None:
                restore(paths, *backup)
            status = 'cancelled' if isinstance(error, KeyboardInterrupt) else 'failed'
            if receipt['commands'] and receipt['commands'][-1]['status'] == 'running':
                receipt['commands'][-1]['status'] = status
            receipt.update(status=status, error=str(error))
            raise
        finally:
            receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
            write_json(receipt_path, receipt)
        if game_only:
            try:
                ordinary(paths['payload_receipt'], missing=True)
                if paths['payload_receipt'].exists():
                    raise BuildError('game payload receipt appeared during build; refusing to replace it')
                write_json(paths['payload_receipt'], dict(schema=1, artifact_kind='local-game-payload', status='passed',
                           build_id=paths['run'].name, game=receipt['game'], build_receipt_sha256=digest(receipt_path)))
            except BaseException as error:
                receipt.update(status='cancelled' if isinstance(error, KeyboardInterrupt) else 'failed', error=str(error))
                write_json(receipt_path, receipt)
                raise
            print('\nReady game payload: ' + str(paths['game']) + '\nNo launcher was published and no game was launched.', flush=True)
        else:
            print('\nReady: ' + str(paths['published']) + '\nRun ./Play_Monado_II.sh to configure settings and press Play. '
                  'Keep it beside Monado_Linux and game_files. No game was launched.', flush=True)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, choices=range(1, 7), default=4, help='parallel compiler jobs (1–6)')
    parser.add_argument('--plan', action='store_true', help='print the local build steps without downloads or writes')
    parser.add_argument('--without-dlss', action='store_true',
                        help='explicitly omit the native NVIDIA DLSS/DLAA provider and SDK download')
    parser.add_argument('--framegen', action='store_true', default=None,
                        help='compatibility option: normal DLSS builds already include experimental frame-generation support; runtime settings remain off by default')
    parser.add_argument('--reuse-game', type=Path,
                        help='retain an unchanged successful game build from this installation; rebuild only the launcher')
    parser.add_argument('--game-only', action='store_true',
                        help='build and verify a fresh native game payload without a launcher or AppImage')
    parser.add_argument('--build-id', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        framegen = validate_features(dlss=not args.without_dlss, framegen=args.framegen)
        if args.plan:
            paths, commands = layout(ROOT, args.jobs, require_input=False, identity=args.build_id, dlss=not args.without_dlss, reuse_game=args.reuse_game, framegen=framegen, game_only=args.game_only)
            print(json.dumps(dict(mode='plan', paths={name: str(path) for name, path in paths.items()},
                                  commands=[dict(name=name, argv=command) for name, command in commands],
                                  dlss_enabled=not args.without_dlss,
                                  framegen_enabled=framegen,
                                  reuses_game=args.reuse_game is not None,
                                  game_only=args.game_only,
                                  runtime_dependencies=runtime_check.dependency_plan(ROOT / 'Monado_Linux'),
                                  launches_game=False, launches_gui=False, network='none in plan; explicit build fetches locked dependencies'), indent=2))
        else:
            build(jobs=args.jobs, identity=args.build_id, dlss=not args.without_dlss, reuse_game=args.reuse_game, framegen=framegen, game_only=args.game_only)
    except KeyboardInterrupt:
        print('Build cancelled; completed local work and previous AppImage preserved. See the build receipt/logs.', file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Monado II build stopped: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
