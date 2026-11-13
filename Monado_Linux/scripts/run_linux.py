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
BWRAP = Path('/usr/bin/bwrap')
NGX_UPDATER = Path('/usr/bin/nvidia-ngx-updater')
X11_SOCKETS = Path('/tmp/.X11-unix')


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


def dlss_namespace(argv, state, *, pid_namespace=True):
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
    if pid_namespace:
        command += ['--unshare-pid']
    command += ['--unshare-net', '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev']
    # Outer GUI namespaces must not own PID1: a GUI crash must leave its game
    # alive for the existing Python subreaper/lock holder to adopt and wait for.
    command += ['--proc', '/proc'] if pid_namespace else ['--ro-bind', '/proc', '/proc']
    command += ['--bind', str(state), str(state)]
    # [XCDE] LINUX-077: Steam's optional controller metadata can live in host
    # /tmp. Admit one validated read-only file before replacing /tmp; point SDL
    # at its canonical state alias, not an assumed propagated /tmp submount.
    metadata = controller_environment.namespace_metadata(os.environ, state)
    if metadata:
        command += ['--ro-bind', metadata['source'], metadata['target']]
    command += ['--bind', str(state), '/tmp']
    if metadata:
        # bwrap's directory bind does not propagate the earlier child file
        # mount. Expose the same read-only inode at the private /tmp alias too.
        command += ['--ro-bind', metadata['source'], '/tmp/' + controller_environment.PRIVATE_INFO]
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
                     'updater_masked': mask_updater, 'pid_namespace': pid_namespace}
    if metadata:
        result['controller_metadata'] = metadata
    return command, result


def prepare_namespace_state(launch):
    """Create only validated private directories; dry-run never calls this."""
    state = Path(launch['state'])
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
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
            expected_target = state / controller_environment.PRIVATE_INFO
            if (metadata.get('target') != str(expected_target)
                    or controller_environment.metadata_file(metadata.get('source')) is None):
                raise ValueError('Steam controller metadata changed or has an unsafe bind target')
            target_fd = os.open('runtime', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            try:
                item = os.open('steam-virtual-gamepad-info', os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                               0o600, dir_fd=target_fd)
                try:
                    info = os.fstat(item)
                    existing_source = metadata['source'] == str(expected_target)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_uid != os.getuid()
                            or (not existing_source and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 0))):
                        raise ValueError('Steam controller metadata bind placeholder must be a private empty ordinary file')
                finally:
                    os.close(item)
            finally:
                os.close(target_fd)
        if launch['namespace'].get('x11_socket_bind', False):
            try:
                os.mkdir('.X11-unix', 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open('.X11-unix', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(child)
    finally:
        os.close(fd)


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
    if framegen and (not dlss or not {'libmonado-fidelityfx.so', 'FidelityFX-MIT.txt'}.issubset(receipt.get('runtime_resources', {}))):
        raise ValueError('frame-generation build receipt is missing its supported provider/resources')
    if dlss:
        required = {'libmonado-ngx.so', 'libnvidia-ngx-dlss.so.310.9.1', 'NVIDIA-DLSS-LICENSE.txt'}
        if not required.issubset(receipt.get('runtime_resources', {})):
            raise ValueError('DLSS build receipt is missing its runtime companions')
        if private_tmp_alias(state):
            launch['namespace'] = {'kind': 'inherited-private-dlss', 'private_tmp_alias': True}
        else:
            launch['execution_argv'], launch['namespace'] = dlss_namespace(argv, state)
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
        os.umask(0o077)
        if 'namespace' in launch:
            prepare_namespace_state(launch)
        os.chdir(ROOT)
        # A read-only inherited installation lease pins this game even if its
        # launcher/supervisor dies. No writable regular descriptor is admitted.
        runtime_fd = install_lease.acquire_runtime(ROOT)
        # No inherited writable regular descriptors may bypass the runtime guard.
        # Stdio remains for terminals/pipes; the guard validates file redirections.
        for entry in os.listdir('/proc/self/fd'):
            fd = int(entry)
            if fd > 2 and fd != runtime_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        execution = launch.get('execution_argv', launch['argv'])
        os.execve(execution[0], execution, environment)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    sys.exit(main())
