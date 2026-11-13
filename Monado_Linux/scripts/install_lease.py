"""Installation-wide runtime/maintenance leases; never inspect save contents.

Runtime holders use an inherited read-only descriptor, so the native state guard
continues refusing writable regular descriptors outside the private profile.
Maintenance is nonblocking: live sessions defer cleanup instead of being killed.
"""
import contextlib
import errno
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

if sys.platform == 'linux':
    import fcntl
else:
    fcntl = None

_spec = importlib.util.spec_from_file_location(
    '_monado_lease_layout', Path(__file__).with_name('install_layout.py'))
_layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_layout)


def lease_path(port):
    port = _layout.canonical(port, directory=True)
    owner = _layout.installation_root(port)
    return owner / 'Monado_Linux/updates/.runtime.lock'


def _ordinary_file(fd, path):
    value, named = os.fstat(fd), path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
            or value.st_uid != os.getuid() or value.st_size != 0
            or value.st_mode & 0o022
            or (value.st_dev, value.st_ino) != (named.st_dev, named.st_ino)):
        raise ValueError('installation runtime lease must be an owned ordinary single-link file')
    return value


def _acquire(port, *, maintenance):
    if fcntl is None:
        raise OSError('installation leases require native Linux flock support')
    path = lease_path(port)
    # Walk known directories through nofollow dirfds so a concurrent parent
    # replacement cannot redirect lock creation into an unrelated tree.
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        parts = path.parent.parts[1:]
        for current, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            try:
                child = os.open(part, flags, dir_fd=directory)
            except FileNotFoundError:
                if current != len(parts) - 1:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=directory)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        flags = (os.O_RDWR if maintenance else os.O_RDONLY)
        flags |= os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open(path.name, flags, dir_fd=directory)
        except FileNotFoundError:
            # Already-created read-only leases can also be acquired inside the
            # DLSS read-only namespace; creation is a host-only first-use path.
            try:
                fd = os.open(path.name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            except FileExistsError:
                fd = os.open(path.name, flags, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        _ordinary_file(fd, path)
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if maintenance else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BlockingIOError(errno.EWOULDBLOCK,
                'Monado installation is in use; maintenance will retry after active sessions close'
                if maintenance else 'Monado installation maintenance is in progress; reopen the launcher shortly') from None
        _ordinary_file(fd, path)
        os.set_inheritable(fd, not maintenance)
        return fd
    except BaseException:
        os.close(fd)
        raise


def acquire_runtime(port):
    return _acquire(port, maintenance=False)


def acquire_maintenance(port):
    return _acquire(port, maintenance=True)


def release(fd):
    if fd is not None:
        os.close(fd)


def _below(path, roots):
    # /proc entries are absolute paths; never resolve candidate paths through links.
    path = Path(str(path).removesuffix(' (deleted)'))
    return path.is_absolute() and any(path == root or path.is_relative_to(root) for root in roots)


def _proc_path(value):
    # Kernel maps escape spaces/backslashes, including normal spaced install paths.
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def _process_identity(data):
    end = data.rfind(b')')
    tail = data[end + 2:].split()
    if len(data) > 16384 or end < 0 or len(tail) < 20 or not tail[19].isdigit():
        raise ValueError('invalid process identity; cleanup deferred')
    return tail[0], tail[19]


def _command_relevance(command, owner, roots):
    """Classify only accessible argv identity; never log private arguments.

    Desktop services can intentionally hide exe/cwd/maps from their own UID.
    Absolute unrelated commands are not evidence of a Monado session. Generic
    interpreters without an explicit unrelated script remain ambiguous.
    """
    parts = [os.fsdecode(part) for part in command.split(b'\0') if part]
    if not parts:
        return 'ambiguous'
    # Interpreter -c snippets and shell arguments can embed an owned path rather
    # than supplying it as a whole argv token. Err toward retaining these files.
    if any(re.search(re.escape(str(root)) + r'''(?=$|[/\s'"),;:\]])''', part)
           for part in parts for root in roots):
        return 'relevant'
    if any(str(owner) in part for part in parts):
        return 'ambiguous'
    names = [Path(part).name.lower() for part in parts]
    if any('monado' in name or 'xcde' in name or name in (
            'run_linux.py', 'launcher_linux.py', 'precompile_linux.py',
            'update_linux.py', 'build_linux_app.py') for name in names):
        return 'ambiguous'
    program = Path(parts[0])
    if not program.is_absolute():
        return 'ambiguous'
    interpreter = re.fullmatch(r'(?:python[0-9.]*(?:-?dbg)?|pypy[0-9.]*|sh|bash|dash|zsh|fish|env|bwrap|ld-linux[^/]*)', names[0])
    if not interpreter:
        return 'unrelated'
    if len(parts) > 1 and Path(parts[1]).is_absolute() and not parts[1].startswith('-'):
        return 'unrelated'
    return 'ambiguous'


def _systemd_credential_helper(entry, command, proc):
    """Recognize systemd's non-dumpable helper after it rewrites argv[0].

    A bare process name alone grants no exemption: require exact helper name and
    a stable same-UID kernel parent identifying the absolute systemd executable.
    """
    if [part for part in command.split(b'\0') if part] != [b'(sd-pam)']:
        return False
    try:
        if (entry / 'comm').read_text().strip() != '(sd-pam)':
            return False
        identity = (entry / 'stat').read_bytes()
        tail = identity[identity.rfind(b')') + 2:].split()
        if len(tail) < 20 or not tail[1].isdigit() or int(tail[1]) <= 1:
            return False
        parent = proc / tail[1].decode('ascii')
        if parent.stat().st_uid != os.getuid() or (parent / 'comm').read_text().strip() != 'systemd':
            return False
        before = _process_identity((parent / 'stat').read_bytes())
        argv = (parent / 'cmdline').read_bytes()
        if len(argv) > 1024 * 1024 or argv.split(b'\0', 1)[0] not in (
                b'/usr/lib/systemd/systemd', b'/lib/systemd/systemd',
                b'/usr/libexec/systemd/systemd'):
            return False
        return before == _process_identity((parent / 'stat').read_bytes())
    except (OSError, ValueError, UnicodeError):
        return False


def _legacy_processes(owner, roots, exclude_pids, proc):
    entries = list(proc.iterdir())
    if len(entries) > 65536:
        raise ValueError('process inventory exceeds safe maintenance bound')
    for entry in entries:
        if not entry.name.isdecimal() or int(entry.name) in exclude_pids:
            continue
        relevance = 'ambiguous'
        restricted = False
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            first = (entry / 'stat').read_bytes()
            state, start = _process_identity(first)
            if state == b'Z':
                continue
            # Read accessible argv BEFORE ptrace-gated exe/cwd/maps. A normal
            # non-dumpable desktop service must not pin every historical build.
            try:
                command = (entry / 'cmdline').read_bytes()
                if len(command) > 1024 * 1024:
                    raise ValueError('oversized process command line')
                relevance = _command_relevance(command, owner, roots)
                if relevance == 'ambiguous' and _systemd_credential_helper(entry, command, proc):
                    relevance = 'unrelated'
                if relevance == 'relevant':
                    return True
            except PermissionError:
                restricted = True
            for name in ('exe', 'cwd'):
                try:
                    if _below(os.readlink(entry / name), roots):
                        return True
                except PermissionError:
                    restricted = True
            # Accessible maps are always checked, even for unrelated commands:
            # a process could still retain an obsolete dependency library.
            try:
                with (entry / 'maps').open('r', errors='surrogateescape') as stream:
                    for count, line in enumerate(stream):
                        if count >= 131072 or len(line) > 32768:
                            raise ValueError('process mapping inventory exceeds safe bound')
                        columns = line.rstrip('\n').split(None, 5)
                        if len(columns) == 6 and _below(_proc_path(columns[5]), roots):
                            return True
            except PermissionError:
                restricted = True
            last = (entry / 'stat').read_bytes()
            if start != _process_identity(last)[1]:
                raise ValueError('process identity changed during maintenance inventory')
            if restricted and relevance != 'unrelated':
                raise ValueError('cannot exclude a potentially related legacy process; cleanup deferred')
        except (FileNotFoundError, ProcessLookupError):
            if entry.exists() and relevance != 'unrelated':
                raise ValueError('cannot inspect a live legacy process; cleanup deferred') from None
            continue
        except PermissionError as error:
            # No accessible stable identity: retain data rather than assuming
            # that an unreadable generic/interpreter process is unrelated.
            if relevance != 'unrelated':
                raise ValueError('cannot exclude live legacy process use; cleanup deferred') from error
    return False


def _profile_locks(owner, excluded):
    held = []
    count = 0
    pending = [(owner / 'Monado_Linux' / name, 0) for name in ('play', 'runs')]
    device = owner.stat().st_dev
    try:
        while pending:
            directory, depth = pending.pop()
            if not directory.exists():
                continue
            if depth > 16:
                raise ValueError('profile inventory exceeds safe maintenance depth')
            info = directory.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or info.st_dev != device:
                raise ValueError('profile inventory has a symlink or mounted directory; cleanup deferred')
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > 100000:
                        raise ValueError('profile inventory exceeds safe maintenance bound')
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append((Path(entry.path), depth + 1))
                    elif entry.name in ('.session.lock', '.precompile.lock'):
                        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                                or info.st_uid != os.getuid()):
                            raise ValueError('profile lease must be an owned ordinary file')
                        identity = (info.st_dev, info.st_ino)
                        if identity in excluded:
                            continue
                        fd = os.open(entry.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
                        held.append(fd)
                        after = os.fstat(fd)
                        if (after.st_dev, after.st_ino) != identity:
                            raise ValueError('profile lease changed during maintenance inventory')
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            raise BlockingIOError(errno.EWOULDBLOCK,
                                'a legacy launcher or precompiler is active; cleanup deferred') from None
        return held
    except BaseException:
        for fd in held:
            os.close(fd)
        raise


@contextlib.contextmanager
def legacy_guard(owner, roots, *, exclude_pids=(), exclude_lock_fds=(), proc_root=Path('/proc')):
    """Hold existing profile leases while checking/deleting legacy build roots.

    New clients additionally obey the installation-wide lease. Old standalone
    CLI clients did not have a common lease, so visible process identities are
    conservatively checked; unreadable/ambiguous inventories defer maintenance.
    """
    if fcntl is None:
        raise OSError('legacy maintenance guards require native Linux flock support')
    owner = _layout.canonical(owner, directory=True)
    roots = tuple(_layout.canonical(root, exists=False) for root in roots)
    if any(root == owner or not root.is_relative_to(owner) for root in roots):
        raise ValueError('legacy maintenance roots must be children of this installation')
    excluded = set()
    for fd in exclude_lock_fds:
        item = os.fstat(fd)
        if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1:
            raise ValueError('excluded profile lease must be an ordinary file')
        excluded.add((item.st_dev, item.st_ino))
    locks = _profile_locks(owner, excluded)
    try:
        if _legacy_processes(owner, roots, {*exclude_pids, os.getpid()}, proc_root):
            raise BlockingIOError(errno.EWOULDBLOCK, 'an older build is still running; cleanup deferred')
        yield
    finally:
        for fd in locks:
            os.close(fd)


def legacy_process_in_use(owner, roots, *, exclude_pids=(), exclude_lock_fds=(), proc_root=Path('/proc')):
    """Read-only admission probe; use legacy_guard across actual deletion."""
    try:
        with legacy_guard(owner, roots, exclude_pids=exclude_pids,
                          exclude_lock_fds=exclude_lock_fds, proc_root=proc_root):
            return False
    except BlockingIOError:
        return True
