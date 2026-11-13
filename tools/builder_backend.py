#!/usr/bin/env python3
"""[XCDE] LINUX-081: local-only GUI build broker; no automatic gameplay.

The native frontend exchanges bounded JSON with this ordinary-user service.
Only an explicit Build request copies reviewed authored source into the selected
final workspace and invokes the existing builder. Input remains read-only.
"""
from __future__ import annotations

import argparse
import ctypes
try:
    import fcntl
except ImportError:  # Source-only Windows CI imports; the broker is Linux-only.
    fcntl = None
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
MAX_JSON = 1024 * 1024
MARKER = '.monado-builder-workspace.json'
REGISTRY = 'installation.json'
PHASE = re.compile(r'^\[(\d+)/(\d+)\]\s+(.+)$')
COMPILE = re.compile(r'^\[compile (\d+)/(\d+)\]\s*(.*)$')
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,96}\Z')
STAGE_LABELS = {
    'check-input': 'Checking game files',
    'install-tools': 'Preparing compiler tools',
    'check-tools': 'Checking compiler tools',
    'graphics-dependencies': 'Preparing graphics and audio libraries',
    'native-dlss-dependency': 'Preparing NVIDIA DLSS support',
    'framegen-source': 'Preparing optional frame-generation source',
    'native-framegen-dependency': 'Building optional frame-generation support',
    'check-runtime-dependencies': 'Checking native runtime dependencies',
    'generate-game': 'Translating your game files',
    'build-game': 'Compiling the game',
    'build-launcher': 'Building the settings launcher',
    'check-launcher': 'Checking the settings launcher',
    'package-appimage': 'Finishing the launcher',
    'check-appimage': 'Checking the finished launcher',
}


class BuilderError(ValueError):
    pass


def canonical(value, *, directory=False, missing=False):
    path = Path(value).absolute()
    if path.resolve() != path or '..' in path.parts or ':' in str(path) or any(ord(c) < 32 for c in str(path)):
        raise BuilderError('Choose an ordinary folder without links, colons or control characters: ' + str(path))
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise BuilderError('Missing path: ' + str(item)) from None
        if stat.S_ISLNK(info.st_mode):
            raise BuilderError('Managed paths cannot contain symbolic links: ' + str(item))
        if (item != path or directory) and not stat.S_ISDIR(info.st_mode):
            raise BuilderError('Expected an ordinary directory: ' + str(item))
        if item == path and not directory and not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
            raise BuilderError('Expected an ordinary file or directory: ' + str(item))
    return path


def read_bytes(path, limit=MAX_JSON):
    path = canonical(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise BuilderError('Expected a bounded ordinary single-link file: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
        finished = os.fstat(stream.fileno())
    after = path.lstat()
    snapshot = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_nlink, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    if snapshot(before) != snapshot(opened) or snapshot(opened) != snapshot(finished) or snapshot(before) != snapshot(after) or len(data) != before.st_size:
        raise BuilderError('File changed while reading: ' + str(path))
    return data


def document(path, limit=MAX_JSON):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BuilderError('Duplicate JSON field: ' + key)
            result[key] = value
        return result
    result = json.loads(read_bytes(path, limit), object_pairs_hook=unique,
                        parse_constant=lambda value: (_ for _ in ()).throw(BuilderError('Nonfinite JSON number')))
    if not isinstance(result, dict):
        raise BuilderError('Expected a JSON object: ' + str(path))
    return result


def digest(path):
    canonical(path)
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic(path, value):
    path = canonical(path, missing=True)
    if path.exists():
        read_bytes(path)
    temporary = path.parent / ('.' + path.name + '-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write((json.dumps(value, ensure_ascii=True, sort_keys=True) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def module(path, name):
    read_bytes(path, 8 * 1024 * 1024)
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def input_location():
    # Existing installations can predate recovery. Load the reviewed helper
    # shipped in this builder, never replace their authored source to add it.
    return module(ROOT / 'Monado_Linux/scripts/input_location.py', '_monado_builder_input_location')


def environment():
    # Preserve the desktop/controller session, but not injected Python/loader or
    # game diagnostic controls. Existing game launch wrappers recheck their own.
    keys = ('HOME', 'USER', 'LOGNAME', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
            'XDG_RUNTIME_DIR', 'XDG_SESSION_TYPE', 'DBUS_SESSION_BUS_ADDRESS',
            'PULSE_SERVER', 'PULSE_COOKIE', 'PULSE_RUNTIME_PATH', 'PIPEWIRE_REMOTE',
            'PIPEWIRE_RUNTIME_DIR', 'TZ')
    result = {key: os.environ[key] for key in keys if key in os.environ}
    controllers = module(ROOT / 'Monado_Linux/scripts/controller_environment.py', '_monado_builder_controllers')
    result.update(controllers.preserve(os.environ))
    result.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
    return result


def selected_input(value):
    if not isinstance(value, str) or not value.strip():
        raise BuilderError('Choose your extracted game folder first')
    # A user-selected link is resolved once; no input is copied or modified.
    path = Path(value).expanduser().resolve(strict=True)
    canonical(path, directory=True)
    for name in ('exefs', 'romfs'):
        canonical(path / name, directory=True)
    return path


def disjoint(left, right):
    return left != right and not left.is_relative_to(right) and not right.is_relative_to(left)


def snapshot(source):
    """Bind only the reviewed source allowlist, never a recursive development copy."""
    source = canonical(source, directory=True)
    guard = module(ROOT / 'tools/publication_guard.py', '_monado_gui_publication_guard')
    manifest = document(source / 'publication-manifest.json')
    policy = document(source / 'publication-policy.json')
    files = manifest.get('files')
    if manifest.get('schema') != 1 or manifest.get('project') != 'Monado II' or not isinstance(files, dict) or not 1 <= len(files) <= 4096:
        raise BuilderError('Missing reviewed authored source manifest')
    if 'publication-policy.json' not in files:
        raise BuilderError('Source policy is not bound by the manifest')
    result = {}
    for name, identity in files.items():
        if guard.path_problem(name) or name == 'publication-manifest.json' or not isinstance(identity, dict):
            raise BuilderError('Unsafe source manifest entry: ' + str(name))
        data = read_bytes(source / name, 8 * 1024 * 1024)
        if identity.get('sha256') != hashlib.sha256(data).hexdigest() or type(identity.get('bytes')) is not int or identity['bytes'] != len(data):
            raise BuilderError('Reviewed authored source changed: ' + name)
        problem = guard.content_problem(name, data, policy.get('licensed_media', {}))
        if problem:
            raise BuilderError(problem + ': ' + name)
        result[name] = data
    result['publication-manifest.json'] = read_bytes(source / 'publication-manifest.json')
    return result


def destination(value, source, state, input_path):
    if not isinstance(value, str) or not value.strip():
        raise BuilderError('Choose a final build destination first')
    output = canonical(Path(value).expanduser(), directory=True, missing=True)
    for protected, label in ((source, 'launcher source'), (state, 'launcher state'), (input_path, 'game input')):
        if not disjoint(output, protected):
            raise BuilderError('Build destination must be separate from ' + label)
    if output.exists() and any(output.iterdir()):
        marker = document(output / MARKER)
        expected = {'schema': 1, 'source_manifest_sha256': digest(source / 'publication-manifest.json'), 'input': str(input_path), 'workspace': str(output)}
        if marker != expected:
            raise BuilderError('This nonempty folder is not this builder’s matching workspace; choose a new or empty folder')
        # Only retry our exact source snapshot; never overwrite local edits.
        for name, data in snapshot(source).items():
            if read_bytes(output / name, 8 * 1024 * 1024) != data:
                raise BuilderError('Workspace source was modified; preserve it and choose a new folder: ' + name)
        link = output / 'game_files'
        if not link.is_symlink() or link.resolve(strict=True) != input_path:
            raise BuilderError('Workspace game-input link changed; preserve it and choose a new folder')
    return output


def stage_source(source, output, input_path):
    files = snapshot(source)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    canonical(output, directory=True)
    marker = output / MARKER
    if marker.exists():
        return  # destination() already checked the exact resumable source.
    # Unknown partial copies are deliberately never overwritten on retry.
    for name, data in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o755 if name.endswith('.sh') else 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    (output / 'game_files').symlink_to(input_path, target_is_directory=True)
    atomic(marker, {'schema': 1, 'source_manifest_sha256': hashlib.sha256(files['publication-manifest.json']).hexdigest(),
                    'input': str(input_path), 'workspace': str(output)})


class Broker:
    def __init__(self, source, session, state, *, popen=subprocess.Popen):
        self.source = canonical(source, directory=True)
        self.session = canonical(session, directory=True)
        self.state = canonical(state, directory=True)
        self.popen = popen
        self.cancelled = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.child = None
        self.seen = set()
        self.status = dict(schema=1, request_id='', phase='welcome', message='Build your copy of Monado II',
                           detail='Choose your own extracted DE 2.0.0 game folder. Nothing is uploaded.',
                           progress=0.0, input='', output=str(Path.home() / 'Games/Monado-II'),
                           version=self.version(self.source), log='', can_open=False, input_previous='')
        self.registered = None
        registry = self.state / REGISTRY
        if registry.exists() or registry.is_symlink():
            try:
                value = document(registry, 16384)
                if set(value) != {'schema', 'workspace'} or value.get('schema') != 1:
                    raise BuilderError('Invalid registered installation')
                candidate = canonical(value['workspace'], directory=True)
                selected = self.installation(candidate)
                self.registered = selected['owner']
                if not self.missing_input(selected):
                    self.status.update(phase='installed', message='Monado II is ready', output=str(self.registered),
                                       version=selected['version'], detail='Open your existing settings launcher.', can_open=True)
            except (OSError, ValueError, RuntimeError) as error:
                self.status.update(phase='failed', message='Registered installation needs attention', detail=str(error), can_open=False)
        self.update()

    @staticmethod
    def version(source):
        try:
            return str(document(source / 'update-version.json', 16384)['version'])
        except (OSError, ValueError, KeyError):
            return 'development'

    def update(self, **fields):
        with self.lock:
            self.status.update(fields)
            atomic(self.session / 'status.json', self.status)

    def run_command(self, argv, cwd, *, logfile=None, timeout=None, progress=False):
        """Own one exact process session; child builder owns its compiler workers."""
        if self.cancelled.is_set():
            raise InterruptedError('Cancelled before starting the next stage')
        started = time.monotonic()
        stream = open(logfile, 'ab', buffering=0) if logfile else None
        output = bytearray()
        workerlog = self.session / ('worker-' + uuid.uuid4().hex + '.log')
        command = [sys.executable, '-I', '-B', ROOT / 'tools/builder_backend.py', '--command-worker',
                   '--worker-cwd', canonical(cwd, directory=True), '--worker-log', workerlog,
                   '--worker-parent', str(os.getpid())]
        lease = getattr(self, 'lease_fd', None)
        if lease is not None:
            command += ['--worker-lease', str(lease)]
        command += ['--', *argv]
        child = self.popen(list(map(str, command)), cwd=str(cwd), env=environment(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
                           pass_fds=(lease,) if lease is not None else ())
        with self.lock:
            self.child = child
        pending = b''
        interrupted = None
        stage = (0, 1)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while selector.get_map() or child.poll() is None:
                    if self.cancelled.is_set() or (timeout is not None and time.monotonic() - started > timeout):
                        if interrupted is None:
                            interrupted = time.monotonic()
                            if child.poll() is None:
                                child.send_signal(signal.SIGINT)
                        # This isolated worker owns pidfds/subreaping for every
                        # descendant, including detached sessions. Never kill the
                        # reaper merely because kernel cleanup is slow.
                        if child.poll() is None and time.monotonic() - interrupted > 35:
                            self.update(message='Waiting for owned build workers to stop', detail='Cancellation is still in progress. The installation lease is retained until every owned worker exits.')
                    for key, _ in selector.select(0.05):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        if stream:
                            stream.write(data)
                        output.extend(data)
                        if len(output) > 65536:
                            del output[:-65536]
                        pending += data
                        lines = pending.split(b'\n'); pending = lines.pop()[-8192:]
                        if progress:
                            for raw in lines:
                                line = raw.decode('utf-8', errors='replace').strip()
                                matched = PHASE.match(line)
                                if matched:
                                    done, total = int(matched[1]), int(matched[2])
                                    stage = (done - 1, max(total, 1))
                                    self.update(message=STAGE_LABELS.get(matched[3], matched[3].replace('-', ' ').capitalize()), progress=min(.94, .05 + .87 * stage[0] / stage[1]))
                                compiled = COMPILE.match(line)
                                if compiled:
                                    count, total = int(compiled[1]), int(compiled[2])
                                    self.update(message='Compiling: ' + str(count) + ' of ' + str(total) + ' files',
                                                progress=min(.94, .05 + .87 * (stage[0] + count / max(total, 1)) / stage[1]))
                            self.update(detail=output.decode('utf-8', errors='replace')[-12000:])
                code = child.wait()
            text = output.decode('utf-8', errors='replace')
            if interrupted is not None:
                if self.cancelled.is_set():
                    raise InterruptedError('Build cancelled; logs and completed local work were preserved')
                raise BuilderError('Stage timed out. See the retained log for details.')
            if code:
                raise BuilderError('Stage failed (exit ' + str(code) + ').\n' + text[-12000:])
            return text
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                while child.poll() is None:
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        continue
            child.stdout.close()
            with self.lock:
                self.child = None
            if stream:
                stream.close()

    def inspect(self, request, *, completion_phase='ready'):
        source = selected_input(request.get('input', ''))
        # This is the first wizard page: validate input independently of the
        # destination the user will choose on the following settings page.
        output = Path(request.get('output') or self.status['output']).expanduser().absolute()
        self.update(phase='checking', input=str(source), output=str(output), message='Checking game files', detail='Reading the selected input; it is not copied or changed.')
        text = self.run_command([sys.executable, '-I', '-B', self.source / 'Monado_Linux/tools/extract/check_dump.py', source], self.source, timeout=180)
        self.update(phase=completion_phase, message='Game files verified', detail=text.strip(), progress=0)
        return source, output

    def check_prerequisites(self, dlss, output):
        doctor = module(ROOT / 'tools/linux_prerequisites.py', '_monado_gui_prerequisites')
        report = doctor.inspect_environment(self.source, without_dlss=not dlss, game_only=True)
        if not report.get('compatible'):
            raise BuilderError(doctor.format_report(report))
        parent = output
        while not parent.exists():
            parent = parent.parent
        free = shutil.disk_usage(canonical(parent, directory=True)).free / (1024 ** 3)
        return f'{free:.1f} GiB free on the destination disk. Build tools, generated files and caches also use this disk; keep space available until the build finishes.'

    def build(self, request):
        # Keep the native request pending through input validation, preflight
        # and compilation; 'ready' is terminal only for the separate Inspect.
        source, _ = self.inspect(request, completion_phase='checking')
        output = destination(request.get('output', ''), self.source, self.state, source)
        jobs = request.get('jobs', 4)
        dlss = request.get('dlss', True)
        precompile = request.get('precompile', False)
        if type(jobs) is not int or not 1 <= jobs <= 6 or type(dlss) is not bool or type(precompile) is not bool:
            raise BuilderError('Invalid build settings')
        prerequisites = self.check_prerequisites(dlss, output)
        self.update(phase='building', message='Preparing local workspace', detail='Copying reviewed authored source only; game files stay in their original folder.\n' + prerequisites, progress=.02)
        stage_source(self.source, output, source)
        identity = 'gui-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
        logs = output / 'Monado_Linux/runs/gui-builder'
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        canonical(logs, directory=True)
        logfile = logs / (identity + '.log')
        self.update(log=str(logfile))
        command = [sys.executable, '-I', '-B', output / 'tools/build_linux_app.py', '--no-appimage', '--jobs', str(jobs), '--build-id', identity]
        if not dlss:
            command.append('--without-dlss')
        self.run_command(command, output, logfile=logfile, progress=True)
        selected = self.installation(output)
        # Only a verified complete game+GUI pair enters the persistent registry.
        self.registered = selected['owner']
        atomic(self.state / REGISTRY, dict(schema=1, workspace=str(self.registered)))
        if precompile:
            self.update(message='Preparing shaders', progress=.95, detail='Optional native shader preparation. Gameplay is not started.')
            try:
                self.run_command([selected['python'], '-B', selected['port'] / 'scripts/precompile_linux.py',
                                  '--executable', selected['game'], '--state-root', selected['state'], '--session', uuid.uuid4().hex],
                                 selected['port'], logfile=logfile)
            except (BuilderError, InterruptedError) as error:
                self.update(phase='complete', message='Game built; shader preparation did not finish', detail=str(error) + '\nYou can retry shader preparation in the settings launcher.', progress=1, can_open=True)
                return
        self.update(phase='complete', message='Monado II is ready', detail='Open the settings launcher to configure the game and press Play when you are ready.', progress=1, can_open=True, input_previous='', version=selected['version'])

    @staticmethod
    def venv_python(port):
        # venv intentionally creates its python names as links to the checked
        # permanent base interpreter. Preserve that name to retain venv prefix.
        parent = canonical(port / '.venv/bin', directory=True)
        read_bytes(port / '.venv/pyvenv.cfg', 16384)
        python = parent / 'python'
        target = canonical(python.resolve(strict=True))
        if not target.is_file() or not os.access(python, os.X_OK):
            raise BuilderError('Installed private Python is unavailable')
        return python

    def installation(self, workspace, *, follow_active=True):
        """Follow the current owner on open; check the exact workspace when staging."""
        workspace = canonical(workspace, directory=True)
        layout = module(workspace / 'Monado_Linux/scripts/install_layout.py', '_monado_builder_install_layout')
        owner = canonical(layout.installation_root(workspace / 'Monado_Linux'), directory=True)
        active = owner / 'Monado_Linux/updates/active.json'
        if follow_active and (active.exists() or active.is_symlink()):
            updater = module(owner / 'tools/update_linux.py', '_monado_builder_installed_updater')
            workspace = updater.active_record(owner, updater.json_read(active, 8192))
            layout = updater.layout_module(workspace)
        updater = module(workspace / 'tools/update_linux.py', '_monado_builder_checked_workspace')
        updater.installed_sources(workspace)
        port = workspace / 'Monado_Linux'
        metadata = port / '.deps/metadata/gui-build.json'
        if metadata.exists() or metadata.is_symlink():
            value = document(metadata)
            if value.get('schema') != 1 or value.get('status') != 'passed' or value.get('artifact_kind') != 'local-gui-build' or not IDENTIFIER.fullmatch(str(value.get('build_id', ''))):
                raise BuilderError('Incomplete GUI build metadata')
            receipt_path = port / 'runs/local-build' / value['build_id'] / 'receipt.json'
            receipt = document(receipt_path, 8 * 1024 * 1024)
            if receipt.get('status') != 'passed' or digest(receipt_path) != value.get('build_receipt_sha256'):
                raise BuilderError('GUI build receipt changed or did not complete')
            paths = receipt['paths']
            game = canonical(paths['game']); launcher = canonical(paths['launcher'])
            state = canonical(paths['state'], directory=True, missing=True)
            if not game.is_relative_to(layout.game_port(port)) or not launcher.is_relative_to(port):
                raise BuilderError('GUI build selection escaped its installation')
            if state != layout.profile_port(port) / 'play/launcher':
                raise BuilderError('GUI build profile does not match its original owner')
        else:
            updater = module(workspace / 'tools/update_linux.py', '_monado_builder_adopt_updater')
            updater.installed_sources(workspace)
            value = updater.pair(workspace / updater.IMAGE)
            selected = {}
            for key in ('game', 'launcher'):
                relative = PurePosixPath(value.get(key, ''))
                if relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 4 or relative.parts[0] != 'Monado_Linux' or relative.parts[1] not in ('build', 'runs', 'accepted'):
                    raise BuilderError('Invalid installed native selection')
                selected[key] = canonical((layout.game_port(port).parent if key == 'game' else workspace) / str(relative))
            game, launcher = selected['game'], selected['launcher']
            state = layout.profile_port(port) / 'play/launcher'
        # Native wrappers perform the full unchanged source/input/ELF/dependency
        # validation again before opening any window or obtaining profile locks.
        return dict(owner=owner, workspace=workspace, port=port, game=game, launcher=launcher, state=state,
                    python=self.venv_python(port), version=self.version(workspace),
                    input_location=input_location().inspect(port, game))

    def missing_input(self, selected):
        location = selected['input_location']
        if not location['missing']:
            return False
        self.update(phase='input_missing', message='Locate your game files', input='',
                    input_previous=location['previous'], output=str(selected['owner']),
                    version=selected['version'], can_open=False, progress=0,
                    detail='Your game files have moved or are unavailable. Choose the same extracted DE 2.0.0 folder. Your installed build, settings and saves stay in place.')
        return True

    def adopt(self, request):
        selected = self.installation(request.get('output', ''))
        missing = selected['input_location']['missing']
        if not missing:
            self.verify_launch(selected)
        self.registered = selected['owner']
        atomic(self.state / REGISTRY, dict(schema=1, workspace=str(self.registered)))
        if self.missing_input(selected):
            return
        self.update(phase='installed', message='Existing installation linked', output=str(self.registered), version=selected['version'], detail='Your existing game input, settings, caches and saves stay in place.', can_open=True, input_previous='')

    def relocate(self, request):
        if self.registered is None:
            raise BuilderError('No completed installation is selected')
        selected = self.installation(self.registered)
        replacement = selected_input(request.get('input', ''))
        self.update(phase='checking', message='Checking the relocated game files', input=str(replacement), can_open=False,
                    detail='Validating the original game version and exact executable identity. No rebuild or save changes are needed.')
        def checker(path):
            self.run_command([sys.executable, '-I', '-B', ROOT / 'Monado_Linux/tools/extract/check_dump.py', path],
                             self.source, timeout=180)
        input_location().relocate(selected['port'], selected['game'], replacement, checker=checker, cancel=self.cancelled)
        # Keep all ordinary launch checks intact. This is a read-only dry run;
        # the installed launcher, game receipts and authored source are reused.
        self.verify_launch(selected)
        self.update(phase='installed', message='Game files located', input=str(replacement), input_previous='',
                    output=str(selected['owner']), version=selected['version'], can_open=True,
                    detail='Your existing game is ready. Settings and saves remain in their original folder.', progress=1)

    def launcher_command(self, selected):
        return [str(selected['python']), '-B', str(selected['port'] / 'scripts/launcher_linux.py'),
                '--game-executable', str(selected['game']), '--launcher-executable', str(selected['launcher']), '--state-root', str(selected['state'])]

    def verify_launch(self, selected):
        return self.run_command([*self.launcher_command(selected), '--dry-run'], selected['port'], timeout=180)

    def open(self, request):
        if self.registered is None:
            raise BuilderError('No completed installation is selected')
        selected = self.installation(self.registered)
        if self.missing_input(selected):
            return False
        self.update(message='Checking the installed launcher', detail='Verifying the existing game and settings launcher without moving any files.')
        self.verify_launch(selected)
        # Existing launcher supervisor owns its session and profile lease. It may
        # legitimately outlive this setup window; never kill a running game when
        # the setup UI closes. No Play button or scripted gameplay is invoked.
        logfile = self.state / 'settings-launcher.log'
        canonical(logfile, missing=True)
        fd = os.open(logfile, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise BuilderError('Settings launch log is not an ordinary single-link file')
            child = self.popen(self.launcher_command(selected), cwd=str(selected['port']), env=environment(), stdin=subprocess.DEVNULL,
                               stdout=fd, stderr=fd, start_new_session=True, close_fds=True)
        finally:
            os.close(fd)
        # Reap this wrapper when it exits while setup remains open, but do not
        # impose compiler cancellation semantics on a user-controlled session.
        threading.Thread(target=child.wait, daemon=True).start()
        self.update(phase='installed', message='Settings launcher opened', version=selected['version'], detail='Configure the game there. Closing this setup window will not close a running game.', can_open=True, input_previous='')
        return True

    def dispatch(self, request):
        identity = request.get('id')
        if not isinstance(identity, str) or not IDENTIFIER.fullmatch(identity):
            raise BuilderError('Invalid request identifier')
        if identity in self.seen:
            return
        self.seen.add(identity)
        action = request.get('action')
        if action == 'cancel':
            self.cancelled.set()
            self.update(request_id=identity)
            if not self.thread or not self.thread.is_alive():
                self.update(phase='cancelled', message='No build is running', detail='No game or build process was started.')
            return
        if self.thread and self.thread.is_alive():
            raise BuilderError('Wait for the current operation to finish or cancel it')
        actions = {'inspect': self.inspect, 'build': self.build, 'adopt': self.adopt, 'open': self.open, 'relocate': self.relocate}
        if action not in actions:
            raise BuilderError('Unsupported setup action')
        self.cancelled.clear()
        self.update(request_id=identity)
        def work():
            try:
                actions[action](request)
            except InterruptedError as error:
                self.update(phase='cancelled', message='Operation cancelled', detail=str(error))
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                self.update(phase='failed', message='Setup needs attention', detail=str(error))
        self.thread = threading.Thread(target=work, daemon=False)
        self.thread.start()

    def close(self):
        self.cancelled.set()
        if self.thread:
            while self.thread.is_alive():
                self.thread.join(timeout=1)



def command_worker(cwd, log, argv, lease=None, parent_pid=None):
    """Single-threaded process owner; never owns an unrelated settings session."""
    cwd = canonical(cwd, directory=True)
    log = canonical(log, missing=True)
    parent = canonical(log.parent, directory=True)
    if parent.stat().st_uid != os.getuid() or parent.stat().st_mode & 0o022:
        raise BuilderError('Worker logs require a private ordinary session directory')
    if log.exists() or log.is_symlink():
        raise BuilderError('Worker log must be fresh')
    if argv and argv[0] == '--':
        argv = argv[1:]
    if not argv or not Path(argv[0]).is_absolute() or any(not isinstance(v, str) or '\0' in v for v in argv):
        raise BuilderError('Worker command must have an explicit absolute executable')
    if lease is not None:
        info = os.fstat(lease)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise BuilderError('Invalid inherited installation lease')
    if parent_pid is not None:
        # This is a fresh single-threaded worker, so no unsafe Python preexec_fn
        # runs in the threaded broker. Parent death requests normal owned cleanup.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0):
            raise OSError(ctypes.get_errno(), 'Cannot install worker parent-death guard')
        if os.getppid() != parent_pid:
            return 130
    os.umask(0o077)
    owner = module(ROOT / 'tools/build_linux_app.py', '_monado_gui_command_owner')
    code = 1
    try:
        # The shared compiler supervisor intentionally starts with a minimal
        # environment. Restore only the already-reviewed desktop/controller
        # context for checkers and optional shader preparation, without loader
        # or Python injection. No shell interprets these argv assignments.
        command = ['/usr/bin/env', '--', *[key + '=' + value for key, value in sorted(environment().items())], *argv]
        code = owner.execute(command, cwd, log)
    except KeyboardInterrupt:
        code = 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Owned setup command stopped: ' + str(error), file=sys.stderr, flush=True)
    finally:
        # execute normally leaves no children. If its bounded cleanup reports a
        # kernel-uninterruptible child, retain this reaper and inherited lease
        # until it can be killed/reaped, rather than abandoning it to init.
        handlers = {number: signal.signal(number, signal.SIG_IGN) for number in
                    (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            started = time.monotonic()
            while True:
                remaining = owner.reap_owned(None)
                if not remaining:
                    break
                owner.signal_owned(remaining, signal.SIGINT if time.monotonic() - started < 5 else signal.SIGKILL)
                time.sleep(.05)
        finally:
            for number, handler in handlers.items():
                signal.signal(number, handler)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--serve', action='store_true')
    mode.add_argument('--command-worker', action='store_true', help=argparse.SUPPRESS)
    mode.add_argument('--open-registered', action='store_true', help='open a registered checked settings launcher, or return 2 for first-run setup')
    parser.add_argument('--session', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--worker-cwd', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-log', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-lease', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--worker-parent', type=int, help=argparse.SUPPRESS)
    parser.add_argument('command', nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or fcntl is None:
        parser.error('The native GUI build broker currently supports Linux only')
    if args.command_worker:
        if args.worker_cwd is None or args.worker_log is None or not args.command:
            parser.error('Command worker requires cwd, fresh log and command')
        return command_worker(args.worker_cwd, args.worker_log, args.command, args.worker_lease, args.worker_parent)
    if args.session is None or args.source is None or args.state is None or args.command:
        parser.error('Setup requires --session, --source and --state, without a worker command')
    broker = None
    stop = threading.Event()
    def request_stop(*_):
        stop.set()
        if broker is not None:
            broker.cancelled.set()
    handlers = {number: signal.signal(number, request_stop) for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    lease_fd = None
    try:
        for path in (args.session, args.state):
            canonical(path, directory=True)
            if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022:
                raise BuilderError('Setup session/state must be owned by this user and not group/world writable')
        lockfile = args.state / '.broker.lock'
        canonical(lockfile, missing=True)
        lease_fd = os.open(lockfile, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        if not stat.S_ISREG(os.fstat(lease_fd).st_mode) or os.fstat(lease_fd).st_nlink != 1:
            raise BuilderError('Setup lock must be an ordinary single-link file')
        try:
            fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BuilderError('Another Monado II setup window is using this registry; close it first') from None
        broker = Broker(args.source, args.session, args.state)
        broker.lease_fd = lease_fd
        if args.open_registered:
            if broker.registered is None:
                return 3 if (args.state / REGISTRY).exists() or (args.state / REGISTRY).is_symlink() else 2
            if not broker.status['can_open']:
                return 3
            try:
                return 3 if broker.open({}) is False else 0
            except (OSError, ValueError, RuntimeError, InterruptedError, subprocess.SubprocessError) as error:
                broker.update(phase='failed', message='Registered installation needs attention', detail=str(error), can_open=False)
                return 3
        while not stop.wait(.1):
            request_path = args.session / 'request.json'
            if request_path.exists() or request_path.is_symlink():
                try:
                    broker.dispatch(document(request_path, 16384))
                except (OSError, ValueError, RuntimeError) as error:
                    broker.update(phase='failed', message='Invalid setup request', detail=str(error))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print('Monado II setup stopped: ' + str(error), file=sys.stderr)
        return 1
    finally:
        if broker:
            broker.close()
        if lease_fd is not None:
            os.close(lease_fd)
        for number, handler in handlers.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    raise SystemExit(main())
