#!/usr/bin/env python3
"""[XCDE] LINUX-004/006: launch a receipted Linux build with explicit private state.

This CLI and the native settings launcher use the same runtime/precompile entry
point and the selected shared extracted input. It never
copies saves, game input or the Windows pipeline seed. --dry-run validates and
prints the launch plan without executing the ELF or creating state.
"""
import argparse
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

ROOT = Path(__file__).resolve().parent.parent
_layout_spec = importlib.util.spec_from_file_location('monado_install_layout', ROOT / 'scripts/install_layout.py')
install_layout = importlib.util.module_from_spec(_layout_spec)
_layout_spec.loader.exec_module(install_layout)
_runtime_spec = importlib.util.spec_from_file_location('monado_runtime_check', Path(__file__).with_name('linux_runtime_check.py'))
runtime_check = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime_check)
_lease_spec = importlib.util.spec_from_file_location('monado_install_lease', Path(__file__).with_name('install_lease.py'))
install_lease = importlib.util.module_from_spec(_lease_spec)
_lease_spec.loader.exec_module(install_lease)
_controller_spec = importlib.util.spec_from_file_location('monado_controller_environment', Path(__file__).with_name('controller_environment.py'))
controller_environment = importlib.util.module_from_spec(_controller_spec)
_controller_spec.loader.exec_module(controller_environment)
_run_log_spec = importlib.util.spec_from_file_location('monado_run_settings_log', Path(__file__).with_name('run_settings_log.py'))
run_settings_log = importlib.util.module_from_spec(_run_log_spec)
_run_log_spec.loader.exec_module(run_settings_log)
_observer_spec = importlib.util.spec_from_file_location('monado_present_observer_manifest', Path(__file__).with_name('present_observer_manifest.py'))
present_observer_manifest = importlib.util.module_from_spec(_observer_spec)
_observer_spec.loader.exec_module(present_observer_manifest)
BWRAP = Path('/usr/bin/bwrap')
NGX_UPDATER = Path('/usr/bin/nvidia-ngx-updater')
X11_SOCKETS = Path('/tmp/.X11-unix')


# [XCDE] LINUX-097: NVIDIA driver FG is a separate, explicit launch choice.
# Never inherit arbitrary driver switches or output paths into a checked game.
def smooth_motion_component(manifests=None, library_dirs=None):
    """Probe the installed host layer and ELF only; no driver code is loaded.

    Presence is not selected-GPU qualification. The driver's layer owns its RTX
    capability decision and reports unsupported hardware through the game log.
    Arguments allow authored fixtures without reading a host user's settings.
    """
    if manifests is None:
        manifests = (Path('/usr/share/vulkan/implicit_layer.d/nvidia_layers.json'),
                     Path('/etc/vulkan/implicit_layer.d/nvidia_layers.json'))
    if library_dirs is None:
        library_dirs = tuple(Path(p) for p in ('/usr/lib/x86_64-linux-gnu', '/lib/x86_64-linux-gnu',
                                               '/usr/lib64', '/lib64', '/usr/lib', '/lib',
                                               '/run/opengl-driver/lib'))
    for manifest in manifests:
        try:
            manifest = Path(manifest)
            if not manifest.is_file() or not 0 < manifest.stat().st_size <= 131072:
                continue
            doc = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(doc, dict):
                continue
            layers = doc.get('layers', [doc.get('layer')])
            if not isinstance(layers, list) or len(layers) > 32:
                continue
            for layer in layers:
                if not isinstance(layer, dict) or layer.get('name') != 'VK_LAYER_NV_present':
                    continue
                if layer.get('enable_environment') != {'NVPRESENT_ENABLE_SMOOTH_MOTION': '1'}:
                    continue
                name = layer.get('library_path')
                if not isinstance(name, str) or not name or len(name) > 4095 or '\x00' in name:
                    continue
                path = Path(name)
                if '..' in path.parts or (not path.is_absolute() and len(path.parts) != 1):
                    continue
                candidates = (path,) if path.is_absolute() else tuple(Path(d) / path for d in library_dirs)
                for candidate in candidates:
                    if not candidate.is_file() or not 64 <= candidate.stat().st_size <= 134217728:
                        continue
                    with candidate.open('rb') as stream:
                        header = stream.read(20)
                    if header[:6] == b'\x7fELF\x02\x01' and int.from_bytes(header[18:20], 'little') == 62:
                        return True
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return False


def frame_generation_profile(state):
    """Read only this checked profile's ordinary INI; mixed FG fails to FSR.

    No arbitrary XCDE_INI/environment path is read on the host side. Legacy FSR
    uses atoi semantics; new external switches require exact 1/true opt-in.
    """
    path = Path(state) / 'xcde.ini'
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 262144:
            return {}
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(262145)
            after = os.fstat(stream.fileno())
        snapshot = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        if snapshot(before) != snapshot(opened) or snapshot(opened) != snapshot(after) or len(data) > 262144:
            return {}
        values = {}
        for raw in data.decode('utf-8').splitlines():
            if len(raw.encode('utf-8')) > 510:
                return {}
            line = raw.lstrip('\ufeff').strip()
            if not line or line[0] in '#;[' or '=' not in line:
                continue
            key, value = (part.strip() for part in line.split('=', 1))
            if key in ('frame_gen', 'frame_gen_smooth_motion', 'cutscenes', 'show_fps_overlay', 'fps_overlay_mode'):
                values[key] = value
        return values
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def smooth_motion_requested(state):
    values = frame_generation_profile(state)
    try:
        legacy = re.match(r'^[+-]?[0-9]+', values.get('frame_gen', ''))
        fsr = bool(legacy and int(legacy[0]) != 0) or values.get('cutscenes') == '30fg'
        return not fsr and values.get('frame_gen_smooth_motion') in ('1', 'true')
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def frame_generation_environment(environment, state, *, component_available=None):
    """Admit one fixed external-driver boolean from profile intent, never a path."""
    result = {key: value for key, value in environment.items()
              if not key.startswith('NVPRESENT_') and key not in (
                  'DISABLE_LAYER_NV_PRESENT_1', 'MONADO_CUDA_TASK_METADATA', 'MONADO_PRESENT_OBSERVER',
                  )}
    selected = smooth_motion_requested(state)
    available = bool(component_available if component_available is not None else smooth_motion_component()) if selected else False
    if selected and available:
        result['NVPRESENT_ENABLE_SMOOTH_MOTION'] = '1'
        result['NVPRESENT_LOG_LEVEL'] = '4'  # bounded driver activation/fallback rows, no output path
        result['MONADO_CUDA_TASK_METADATA'] = '1'
    report = {'method': 'nvidia-smooth-motion' if selected else 'application',
              'external_driver_enabled': selected and available,
              'component_available': available if selected else None,
              'output_fps': 'external-driver-unavailable-to-application' if selected and available else 'application-presentations',
              'cuda_task_metadata': selected and available,
              # LINUX-101: diagnostics measure selected driver output even when
              # the user hides the on-screen counter. Off/FSR never request it.
              'observer_requested': selected and available}
    if report['observer_requested']:
        report['output_fps'] = 'downstream-measurement-requested-not-yet-active'
    return result, report


def checked_path(path, parents, *, exists):
    path = path.absolute()
    if path.resolve() != path or path.is_symlink() or not any(path != p and path.is_relative_to(p) for p in parents):
        raise ValueError('path must be an ordinary child of an allowed Linux directory: ' + str(path))
    if exists and not path.is_file():
        raise ValueError('executable is missing: ' + str(path))
    return path


def verify_runtime_resources(binary, receipt):
    """[XCDE] LINUX-017: verify optional local vendor/icon companions too."""
    for name, expected in receipt.get('runtime_resources', {}).items():
        if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
            raise ValueError('invalid receipted runtime resource name')
        path = binary.parent / name
        if (path.is_symlink() or path.resolve() != path or not path.is_file() or
                expected.get('path') != str(path) or expected.get('bytes') != path.stat().st_size):
            raise ValueError('runtime resource is missing or relocated: ' + name)
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected.get('sha256'):
            raise ValueError('runtime resource differs from its build receipt: ' + name)


def private_tmp_alias(state):
    """Reuse only an existing state/tmp alias with the updater still masked."""
    try:
        source, temporary = state.stat(), Path('/tmp').stat()
        alias = source.st_dev == temporary.st_dev and source.st_ino == temporary.st_ino
    except OSError:
        return False
    if not alias:
        return False
    try:
        updater = NGX_UPDATER.lstat()
    except FileNotFoundError:
        return True
    null = Path('/dev/null').stat()
    if not stat.S_ISCHR(updater.st_mode) or not stat.S_ISCHR(null.st_mode) or updater.st_rdev != null.st_rdev:
        raise ValueError('existing private /tmp alias has an unmasked NVIDIA updater; refusing reuse')
    return True


def private_runtime_environment(environment, state, *, planned_namespace=False):
    """Keep NGX lock files private without redirecting desktop IPC endpoints.

    Return a child environment; never mutate getenv-visible state in a threaded
    application. A planned namespace is allowed only before the checked bwrap
    command mounts state at /tmp. Reused namespaces must already attest it.
    """
    state = Path(state)
    if not planned_namespace and not private_tmp_alias(state):
        raise ValueError('private runtime environment requires the verified state /tmp namespace')
    environment = controller_environment.private_environment(environment, state, planned_namespace)
    original = environment.get('XDG_RUNTIME_DIR')
    if not original:
        # Existing headless/X11 launches already use NGX's private /tmp fallback.
        # Preserve their desktop defaults rather than invent a session directory.
        return dict(environment)
    if not Path(original).is_absolute():
        raise ValueError('DLSS requires an absolute original XDG_RUNTIME_DIR for desktop IPC')
    result = dict(environment)
    private = '/tmp/runtime'
    if original == private:
        display = result.get('WAYLAND_DISPLAY')
        if display and not Path(display).is_absolute():
            raise ValueError('private runtime environment cannot rebase a relative Wayland endpoint')
        return result  # already prepared by the outer launcher; keep IPC paths
    runtime = Path(original)
    if not runtime.is_dir():
        raise ValueError('original XDG_RUNTIME_DIR must be an existing directory')
    display = result.get('WAYLAND_DISPLAY')
    if display and not Path(display).is_absolute():
        result['WAYLAND_DISPLAY'] = str(runtime / display)
    elif 'WAYLAND_DISPLAY' not in result and (runtime / 'wayland-0').is_socket():
        result['WAYLAND_DISPLAY'] = str(runtime / 'wayland-0')
    # Official native-client lookup overrides retain their original precedence.
    result.setdefault('PIPEWIRE_RUNTIME_DIR', str(runtime))
    had_pulse_runtime = 'PULSE_RUNTIME_PATH' in result
    result.setdefault('PULSE_RUNTIME_PATH', str(runtime / 'pulse'))
    pulse_socket = runtime / 'pulse/native'
    if not had_pulse_runtime and 'PULSE_SERVER' not in result and pulse_socket.is_socket():
        result['PULSE_SERVER'] = 'unix:' + str(pulse_socket)
    bus = runtime / 'bus'
    if 'DBUS_SESSION_BUS_ADDRESS' not in result and bus.is_socket():
        result['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + str(bus)
    result['XDG_RUNTIME_DIR'] = private
    return result


def dlss_namespace(argv, state, *, pid_namespace=True, cuda_task_metadata=False):
    """[XCDE] LINUX-017: mount-private NGX locks and network, no host writes.

    Keep the actual game argv separate: callers use argv[0] for build identity.
    This is the component-tested bwrap arrangement, without parent-death killing.
    """
    if not BWRAP.is_file() or not os.access(BWRAP, os.X_OK):
        raise ValueError('DLSS requires the installed /usr/bin/bwrap namespace helper')
    if X11_SOCKETS.is_symlink() or (X11_SOCKETS.exists() and not X11_SOCKETS.is_dir()):
        raise ValueError('X11 socket bind source must be an ordinary directory')
    if NGX_UPDATER.exists() and not NGX_UPDATER.is_file():
        raise ValueError('NVIDIA updater mask destination must be an installed file')
    command = [str(BWRAP), '--unshare-user']
    if cuda_task_metadata and pid_namespace:
        raise ValueError('Smooth Motion own-task metadata requires the host-supervised game PID scope')
    if pid_namespace:
        command += ['--unshare-pid']
    command += ['--unshare-net', '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev']
    # Outer GUI namespaces must not own PID1: a GUI crash must leave its game
    # alive for the existing Python subreaper/lock holder to adopt and wait for.
    command += ['--proc', '/proc'] if pid_namespace or cuda_task_metadata else ['--ro-bind', '/proc', '/proc']
    command += ['--bind', str(state), str(state)]
    # [XCDE] LINUX-089: the host supervisor exports only validated metadata into
    # a dedicated private directory. Bind that directory RO at BOTH aliases;
    # binding the original file would freeze its inode across Steam replacement.
    metadata = controller_environment.namespace_metadata(os.environ, state)
    command += ['--bind', str(state), '/tmp']
    if metadata:
        command += ['--ro-bind', metadata['directory'], metadata['directory'],
                    '--ro-bind', metadata['directory'],
                    '/tmp/' + controller_environment.PRIVATE_DIRECTORY]
    x11 = X11_SOCKETS.is_dir()
    if x11:
        command += ['--ro-bind', str(X11_SOCKETS), '/tmp/.X11-unix']
    mask_updater = NGX_UPDATER.is_file()
    if mask_updater:
        command += ['--ro-bind', '/dev/null', str(NGX_UPDATER)]
    command += ['--', *argv]
    with BWRAP.open('rb') as stream:
        identity = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = {'kind': 'bwrap-private-dlss', 'helper': str(BWRAP),
                     'helper_sha256': identity, 'x11_socket_bind': x11,
                     'updater_masked': mask_updater, 'pid_namespace': pid_namespace,
                     'cuda_task_metadata': cuda_task_metadata}
    if metadata:
        result['controller_metadata'] = metadata
    return command, result


def prepare_namespace_state(launch, *, controller_refresh=False):
    """Create only validated private directories; dry-run never calls this."""
    state = Path(launch['state'])
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    mirror = None
    try:
        for part in state.parts[1:]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        try:
            os.mkdir('runtime', 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open('runtime', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            info = os.fstat(child)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('private runtime directory must be owned by this user with mode 0700')
        finally:
            os.close(child)
        metadata = launch['namespace'].get('controller_metadata')
        if metadata:
            mirror = controller_environment.MetadataMirror.prepare(metadata, state, fd)
        if launch['namespace'].get('x11_socket_bind', False):
            try:
                os.mkdir('.X11-unix', 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open('.X11-unix', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(child)
    except BaseException:
        if mirror is not None:
            mirror.close()
        raise
    finally:
        os.close(fd)
    if mirror is not None and not controller_refresh:
        # Precompile/developer namespace callers need only the initial snapshot,
        # not an input-session watcher or an unowned directory descriptor.
        mirror.close()
        return None
    return mirror


def wait_metadata_child(execution, environment, runtime_fd, mirror):
    """[XCDE] LINUX-089: only hidden-metadata CLI launches need a supervisor.

    Ordinary and inherited launches still exec directly. Keep the readonly
    installation lease until this one owned child exits; signals do not kill it
    or interrupt a save. No watcher process, game-controlled IPC or new paths.
    """
    interrupted = []
    def keep_game(number, frame):
        interrupted.append(number)
        try:
            os.write(2, b'Monado session remains active; close its window to finish safely.\n')
        except OSError:
            pass
    handlers = {number: signal.signal(number, keep_game)
                for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        mirror.start(log_fd=2)
        child = subprocess.Popen(execution, env=environment, close_fds=True,
                                 pass_fds=(runtime_fd,), start_new_session=True)
        code = child.wait()
        return 128 - code if code < 0 else code if code else 128 + interrupted[0] if interrupted else 0
    finally:
        mirror.stop()
        for number, handler in handlers.items():
            signal.signal(number, handler)


def plan(executable, state, precompile=False, *, port=None):
    root = Path(port) if port is not None else ROOT
    owning_port = install_layout.build_port(root, executable)
    binary = checked_path(executable, [owning_port / name for name in ('build', 'runs', 'accepted')], exists=True)
    state = checked_path(state, install_layout.state_roots(root), exists=False)
    if binary.is_relative_to(state) or state.is_relative_to(binary.parent):
        raise ValueError('runtime state must be separate from the selected build output')
    receipt = json.loads((binary.parent / 'receipt.json').read_text())
    with binary.open('rb') as stream:
        header = stream.read(64)
        stream.seek(0)
        identity = hashlib.file_digest(stream, 'sha256').hexdigest()
    if len(header) != 64 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 62:
        raise ValueError('expected a native Linux x86-64 ELF')
    accepted = receipt.get('executable', {})
    if receipt.get('status') != 'passed' or accepted.get('path') != str(binary) or accepted.get('sha256') != identity:
        raise ValueError('executable does not match a successful build receipt')
    if not os.access(binary, os.X_OK):
        raise ValueError('selected ELF is not executable')
    verify_runtime_resources(binary, receipt)
    if type(receipt.get('split_game', False)) is not bool:
        raise ValueError('invalid split-game build receipt flag')
    if receipt.get('split_game', False):
        library = receipt.get('game_library', {})
        expected = receipt.get('gamecode_abi', {}).get('id')
        id_file = binary.parent / 'lasgame.so.id'
        if (type(receipt.get('split_game')) is not bool or not isinstance(expected, str)
                or not re.fullmatch(r'[0-9a-f]{64}', expected)
                or library.get('path') != str(binary.parent / 'lasgame.so')
                or library.get('sha256') != receipt.get('runtime_resources', {}).get('lasgame.so', {}).get('sha256')
                or library.get('abi_id') != expected or library.get('id_path') != str(id_file)
                or id_file.is_symlink() or not id_file.is_file()
                or hashlib.sha256(id_file.read_bytes()).hexdigest() != library.get('id_sha256')
                or id_file.read_text() != expected + '\n'):
            raise ValueError('split runtime/game library ABI pair differs from its receipt')
    # ELF RUNPATH does not select dependencies of dependencies. Select the exact
    # receipted development sysroot for those too (not an inherited search path).
    sysroot = Path(receipt.get('dependencies', {}).get('sysroot', ''))
    expected_lock = receipt.get('sources_before', {}).get('graphics-deps-linux.lock.json')
    if not sysroot.is_absolute() or sysroot.resolve() != sysroot or not sysroot.is_relative_to(owning_port / '.deps/graphics/sysroots'):
        raise ValueError('build receipt has no valid local graphics sysroot')
    marker = json.loads((sysroot / '.monado-deps.json').read_text())
    library_path = sysroot / 'usr/lib/x86_64-linux-gnu'
    if not expected_lock or marker.get('lock_sha256') != expected_lock or not library_path.is_dir():
        raise ValueError('graphics sysroot identity differs from the build receipt')
    runtime_check.require_receipt_validation(receipt, marker)
    policy, _ = runtime_check.load_policy(owning_port, sysroot, expected_lock=expected_lock,
        expected_policy=receipt.get('runtime_validation', {}).get('runtime_policy_sha256'))
    selected_library_path = runtime_check.library_path(sysroot, policy)
    source = install_layout.shared_input(root)
    if source == state or state.is_relative_to(source) or source.is_relative_to(state):
        raise ValueError('shared input and runtime state must be disjoint')
    argv = [str(binary), '--state-root', str(state)]
    if precompile:
        argv.append('--precompile')
    argv.append(str(source))
    launch = {'argv': argv, 'cwd': str(root), 'input': str(source), 'state': str(state),
              'binary_sha256': identity, 'library_path': selected_library_path, 'build_port': str(owning_port)}
    dlss = receipt.get('dlss_enabled', False)
    if not isinstance(dlss, bool):
        raise ValueError('invalid DLSS build receipt flag')
    framegen = receipt.get('framegen_enabled', False)
    if not isinstance(framegen, bool):
        raise ValueError('invalid frame-generation build receipt flag')
    fsr3 = receipt.get('fsr3_enabled', False)
    if type(fsr3) is not bool:
        raise ValueError('invalid FSR3 build receipt flag')
    if fsr3 and not {'libmonado-fsr3.so', 'AMD-FidelityFX-LICENSE.txt'}.issubset(receipt.get('runtime_resources', {})):
        raise ValueError('FSR3 build receipt is missing its verified provider/resources')
    if framegen and (not (dlss or fsr3) or not {'libmonado-fidelityfx.so', 'FidelityFX-MIT.txt'}.issubset(receipt.get('runtime_resources', {}))):
        raise ValueError('frame-generation build receipt is missing its supported provider/resources')
    fsr4 = receipt.get('fsr4_enabled', False)
    if type(fsr4) is not bool:
        raise ValueError('invalid FSR4 build receipt flag')
    if fsr4 and not {'libmonado-fsr4.so', 'FSR4-GPL-2.0-or-later.txt', 'FSR4-AMD-SDK-LICENSE.md', 'FSR4-component-source.tar.gz'}.issubset(receipt.get('runtime_resources', {})):
        raise ValueError('FSR4 build receipt is missing its verified component/license/source resources')
    if fsr4:
        spec = importlib.util.spec_from_file_location('_monado_fsr4_asset_selection', ROOT / 'scripts/fsr4_assets_linux.py')
        assets_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(assets_module)
        assets, reason = assets_module.available(ROOT, receipt)
        launch['fsr4_assets'] = assets
        launch['fsr4_unavailable_reason'] = reason
        if assets:
            argv[3:3] = ['--fsr4-assets', assets['asset_root']]
    actual_game = bool(receipt.get('generated') or receipt.get('game_library')) and not precompile
    smooth = actual_game and dlss and smooth_motion_requested(state) and smooth_motion_component()
    launch['smooth_motion_planned'] = smooth
    protocol = receipt.get('cuda_task_metadata_protocol')
    launch['cuda_task_metadata_protocol'] = protocol if type(protocol) is int and protocol == 1 else None
    launch['observer_library'] = present_observer_manifest.checked_resource(binary, receipt) if actual_game else None
    if dlss:
        required = {'libmonado-ngx.so', 'libnvidia-ngx-dlss.so.310.9.1', 'NVIDIA-DLSS-LICENSE.txt'}
        if not required.issubset(receipt.get('runtime_resources', {})):
            raise ValueError('DLSS build receipt is missing its runtime companions')
        if private_tmp_alias(state):
            launch['namespace'] = {'kind': 'inherited-private-dlss', 'private_tmp_alias': True}
        else:
            launch['execution_argv'], launch['namespace'] = dlss_namespace(argv, state,
                pid_namespace=not smooth, cuda_task_metadata=smooth)
    return launch


def validate_runtime(launch):
    return runtime_check.check_receipted(Path(launch['argv'][0]), Path(launch['build_port']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True, help='dedicated child of Monado_Linux/runs or play')
    parser.add_argument('--precompile', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--env', action='append', default=[], metavar='NAME=VALUE',
                        help='explicit XCDE_ or LARECOMP_ runtime control; output paths must stay in state')
    args = parser.parse_args()
    # [XCDE] LINUX-018: precompile owns a cooperative, session-keyed supervisor;
    # ordinary Play keeps the existing direct checked exec behavior unchanged.
    if args.precompile:
        import precompile_linux
        delegated = ['--executable', str(args.executable), '--state-root', str(args.state_root)]
        if args.dry_run:
            delegated.append('--dry-run')
        for entry in args.env:
            delegated += ['--env', entry]
        return precompile_linux.main(delegated)
    try:
        launch = plan(args.executable, args.state_root, args.precompile)
        # Avoid inheriting controls from another project/session. Desktop and
        # device environment remains available; runtime sets its own cache roots.
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(('XCDE_', 'LARECOMP_', 'LASRECOMP_', 'MONADO_'))
                       and not k.startswith('LD_') and k not in ('GLIBC_TUNABLES', 'SDL_DYNAMIC_API', 'SDL_DYNAPI')
                       and k not in controller_environment.CONTEXT_KEYS}
        environment.update(controller_environment.preserve(os.environ))
        controls = {}
        for entry in args.env:
            key, separator, value = entry.partition('=')
            if not separator or not key.startswith(('XCDE_', 'LARECOMP_')) or not key.replace('_', '').isalnum():
                raise ValueError('--env requires an XCDE_ or LARECOMP_ name and value')
            if key == 'LARECOMP_DATA_ROOT':
                raise ValueError('use --state-root instead of overriding LARECOMP_DATA_ROOT')
            controls[key] = value
        environment.update(controls)
        environment['LD_LIBRARY_PATH'] = launch['library_path']
        # [XCDE] LINUX-016: same desktop icon/group for launcher and game.
        environment['SDL_APP_ID'] = 'monado-linux-port'
        # [XCDE] LINUX-097: only the actual game gets a controlled driver flag;
        # GUI/precompile use ordinary clean environments. Profile paths are not
        # supplied by inherited variables, and no driver log filename is admitted.
        environment, launch['frame_generation'] = frame_generation_environment(environment, Path(launch['state']))
        requested = launch['frame_generation']['external_driver_enabled']
        if 'smooth_motion_planned' in launch and requested != launch['smooth_motion_planned']:
            raise ValueError('frame-generation settings or driver component changed while preparing Play; try Play again')
        if requested and 'smooth_motion_planned' in launch:
            if launch.get('cuda_task_metadata_protocol') != 1:
                raise ValueError('Smooth Motion requires a current full game build with scoped CUDA metadata support; rebuild this version first')
            if launch.get('namespace', {}).get('kind') == 'inherited-private-dlss':
                raise ValueError('Smooth Motion needs the current launcher host Play supervisor; reopen the updated AppImage or Play script')
            launch['frame_generation']['cuda_task_metadata_protocol'] = 1
        observer = launch['frame_generation']['observer_requested']
        launch['frame_generation']['counter_available'] = bool(observer and launch.get('observer_library'))
        launch['frame_generation']['counter_kind'] = 'accepted-downstream-requests-not-scanout'
        launch['frame_generation']['counter_status'] = ('planned-not-yet-active' if observer and launch.get('observer_library')
            else 'resource-unavailable' if observer else 'not-requested')
        if 'namespace' in launch:
            environment = private_runtime_environment(environment, Path(launch['state']),
                                                       planned_namespace='execution_argv' in launch)
        check = subprocess.run([str(ROOT / '.venv/bin/python'), '-B', str(ROOT / 'tools/extract/check_dump.py'),
                                launch['input']], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if check.returncode:
            raise ValueError('selected game input check failed: ' + check.stdout + check.stderr)
        launch['input_check'] = check.stdout.strip()
        launch['controls'] = controls
        if args.dry_run:
            print(json.dumps(launch, indent=2))
            return 0
        launch['runtime_validation'] = validate_runtime(launch)
        if launch['frame_generation']['method'] == 'nvidia-smooth-motion':
            if launch['frame_generation']['external_driver_enabled']:
                print('[fg] NVIDIA Smooth Motion requested; driver log determines activation, generated-frame identity unavailable', file=sys.stderr)
            else:
                print('[fg] NVIDIA Smooth Motion component unavailable; ordinary presentation retained', file=sys.stderr)
        os.umask(0o077)
        mirror = None
        if 'namespace' in launch:
            mirror = prepare_namespace_state(launch, controller_refresh=True)
        if observer and launch.get('observer_library'):
            try:
                directory = present_observer_manifest.prepare(Path(launch['state']), launch['observer_library'])
                environment.pop('VK_ADD_LAYER_PATH', None)
                environment.pop('VK_INSTANCE_LAYERS', None)
                environment['VK_LAYER_PATH'] = directory
                environment['MONADO_PRESENT_OBSERVER'] = '1'
                launch['frame_generation']['counter_status'] = 'ready-for-driver-attachment'
            except (OSError, ValueError, TypeError):
                launch['frame_generation']['counter_available'] = False
                launch['frame_generation']['counter_status'] = 'private-manifest-unavailable'
                print('[fg] optional output counter unavailable: private manifest validation failed', file=sys.stderr)
        # [XCDE] LINUX-099: private requested-settings snapshot, joined to the
        # native effective-settings/renderer rows. Optional logging failure
        # never changes settings, capabilities or validated launch behavior.
        run_record = run_settings_log.record_game_run(launch, environment, manifest=ROOT.parent / 'publication-manifest.json')
        environment['MONADO_RUN_ID'] = run_record['run_id']
        print('[run] id=' + run_record['run_id'] + ' event=launch settings_record=' + run_record['status'] +
              (' reason=' + run_record['reason'] if 'reason' in run_record else ''), file=sys.stderr)
        os.chdir(ROOT)
        # A read-only inherited installation lease pins this game even if its
        # launcher/supervisor dies. No writable regular descriptor is admitted.
        runtime_fd = install_lease.acquire_runtime(ROOT)
        # No inherited writable regular descriptors may bypass the runtime guard.
        # Stdio remains for terminals/pipes; the guard validates file redirections.
        for entry in os.listdir('/proc/self/fd'):
            fd = int(entry)
            if fd > 2 and fd != runtime_fd and (mirror is None or fd != mirror.fileno()):
                try:
                    os.close(fd)
                except OSError:
                    pass
        execution = launch.get('execution_argv', launch['argv'])
        if mirror is not None:
            try:
                return wait_metadata_child(execution, environment, runtime_fd, mirror)
            finally:
                mirror.close()
                install_lease.release(runtime_fd)
        os.execve(execution[0], execution, environment)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    sys.exit(main())
