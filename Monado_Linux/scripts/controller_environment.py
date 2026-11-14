"""[XCDE] LINUX-077: narrowly preserve SDL/Steam controller launch context.

No executable, driver-library, output-path or arbitrary SDL variable is admitted.
Steam's optional metadata remains read-only to the game. Its contents are never
parsed or logged; hidden host /tmp data has a bounded, private runtime mirror.
"""
import os
from pathlib import Path
import re
import stat
import threading
import time

STEAM_INFO = 'SteamVirtualGamepadInfo'
PRIVATE_DIRECTORY = 'steam-controller-metadata'
PRIVATE_INFO = PRIVATE_DIRECTORY + '/info'
METADATA_LIMIT = 1024 * 1024
_MIRROR_OWNER = b'Monado II controller metadata mirror v1\n'
BOOL_KEYS = frozenset((
    'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD',
    'SDL_JOYSTICK_HIDAPI', 'SDL_JOYSTICK_HIDAPI_STEAMDECK',
    'SDL_JOYSTICK_HIDAPI_XBOX', 'SDL_JOYSTICK_HIDAPI_PS4',
    'SDL_JOYSTICK_HIDAPI_PS5', 'SDL_JOYSTICK_HIDAPI_SWITCH',
    'SDL_JOYSTICK_DISABLE_UDEV', 'SDL_HIDAPI_UDEV',
    'SDL_JOYSTICK_LINUX_CLASSIC',
))
ID_KEYS = frozenset(('SteamAppId', 'SteamGameId', 'SteamOverlayGameId'))
LIST_KEYS = frozenset(('SDL_GAMECONTROLLER_IGNORE_DEVICES',
                       'SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'))
CONTEXT_KEYS = BOOL_KEYS | ID_KEYS | LIST_KEYS | frozenset((
    'SDL_GAMECONTROLLERCONFIG', STEAM_INFO))
_DEVICE_LIST = re.compile(r'(?:\s*0x[0-9a-fA-F]{1,4}/0x[0-9a-fA-F]{1,4}\s*(?:,|$))*\Z')


def metadata_file(value):
    """Return only a current-user, non-linked, non-shared writable target.

    Invalid optional integration data is omitted instead of stopping an ordinary
    game launch. Host filesystem permissions and all runtime guards still apply.
    """
    if not isinstance(value, str) or not value or len(os.fsencode(value)) >= 4096 or '\0' in value:
        return None
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        return None
    try:
        if path.resolve() != path:
            return None
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o022
                or before.st_size > METADATA_LIMIT):
            return None
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink) != (
                opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink):
            return None
    except (OSError, ValueError):
        return None
    return path


def preserve(environment):
    """Validate known input settings; never mutate the caller's environment."""
    result = {}
    for key in CONTEXT_KEYS:
        value = environment.get(key)
        if not isinstance(value, str) or '\0' in value:
            continue
        if key in BOOL_KEYS:
            if value in ('0', '1'):
                result[key] = value
        elif key in ID_KEYS:
            if re.fullmatch(r'[0-9]{1,20}', value) and int(value) < 1 << 64:
                result[key] = value
        elif key in LIST_KEYS:
            if len(value) <= 32768 and (not value or _DEVICE_LIST.fullmatch(value)):
                result[key] = value
        elif key == 'SDL_GAMECONTROLLERCONFIG':
            # SDL owns the mapping grammar; bound text, not a file/code path.
            if len(value.encode('utf-8')) <= 65536 and not any(ord(c) < 32 and c not in '\r\n\t' for c in value):
                result[key] = value
        elif key == STEAM_INFO:
            path = metadata_file(value)
            if path is not None:
                result[key] = str(path)
    return result


def namespace_metadata(environment, state):
    """[XCDE] LINUX-089: plan only a dedicated private snapshot directory.

    An original path outside hidden /tmp and writable state is already visible
    through the read-only root mount. Keep it live instead of pinning its inode.
    Never expose the original metadata's parent directory to the child.
    """
    source = metadata_file(environment.get(STEAM_INFO))
    if source is None:
        return None
    state = Path(state)
    if not source.is_relative_to('/tmp') and not source.is_relative_to(state):
        return None
    directory = state / PRIVATE_DIRECTORY
    # A cold invocation cannot claim a prior mirror as an original host source.
    # Verified inherited namespaces do not call this fresh-namespace planner.
    if source.is_relative_to(directory):
        return None
    return {'source': str(source), 'target': str(state / PRIVATE_INFO),
            'directory': str(directory), 'kind': 'private-mirror-v1'}


def private_environment(environment, state, planned_namespace):
    result = dict(environment)
    source = metadata_file(result.get(STEAM_INFO))
    if source is None:
        result.pop(STEAM_INFO, None)
    elif planned_namespace:
        metadata = namespace_metadata(result, state)
        if metadata:
            result[STEAM_INFO] = metadata['target']
        elif source.is_relative_to(Path(state)):
            result.pop(STEAM_INFO, None)
    return result


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _safe_regular(info):
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_nlink == 1 and not info.st_mode & 0o022
            and 0 <= info.st_size <= METADATA_LIMIT)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise OSError('incomplete controller metadata snapshot write')
        view = view[count:]


class MetadataMirror:
    """[XCDE] LINUX-089: fixed-source, fixed-directory host-side snapshot.

    The namespace binds only this dedicated directory read-only at both child
    aliases. Atomic publication changes its info inode, so SDL never reads a
    truncated update and can observe Steam's atomic source-file replacements.
    No child message selects a read or write path. The held directory descriptor
    belongs to the supervisor, is CLOEXEC and is never passed to the game.
    """
    interval = 0.5

    def __init__(self, source, directory_fd):
        self.source = Path(source)
        self.directory_fd = directory_fd
        self.last_source = None
        self.last_data = None
        self.last_poll = None
        self.last_mtime = 0
        self.failed = False
        self.reports = 0
        self.thread = None
        self.stop_event = None

    @classmethod
    def prepare(cls, metadata, state, state_fd):
        state = Path(state)
        expected = namespace_metadata({STEAM_INFO: metadata.get('source')}, state)
        if metadata != expected:
            raise ValueError('Steam metadata mirror plan changed or has an unsafe target')
        name = Path(PRIVATE_DIRECTORY).name
        try:
            os.mkdir(name, 0o700, dir_fd=state_fd)
        except FileExistsError:
            pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=state_fd)
        mirror = cls(metadata['source'], fd)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('controller metadata mirror directory must be private and owned')
            entries = set(os.listdir(fd))
            if not entries:
                marker = os.open('owner', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
                try:
                    _write_all(marker, _MIRROR_OWNER)
                    os.fsync(marker)
                finally:
                    os.close(marker)
            mirror._validate_directory(recover_staging=True)
            if not mirror.poll(force=True):
                raise ValueError('Steam metadata changed or became unsafe while preparing its snapshot')
            return mirror
        except BaseException:
            mirror.close()
            raise

    def _validate_directory(self, *, recover_staging=False):
        entries = set(os.listdir(self.directory_fd))
        allowed = {'owner', 'info', '.next'} if recover_staging else {'owner', 'info'}
        if not entries.issubset(allowed) or 'owner' not in entries:
            raise ValueError('controller metadata mirror contains unrecognized files')
        marker = os.open('owner', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                         os.O_NONBLOCK, dir_fd=self.directory_fd)
        try:
            info = os.fstat(marker)
            if (not _safe_regular(info) or stat.S_IMODE(info.st_mode) != 0o600 or
                    info.st_size != len(_MIRROR_OWNER) or
                    os.read(marker, len(_MIRROR_OWNER) + 1) != _MIRROR_OWNER):
                raise ValueError('controller metadata mirror ownership marker differs')
        finally:
            os.close(marker)
        if 'info' in entries:
            info = os.stat('info', dir_fd=self.directory_fd, follow_symlinks=False)
            if not _safe_regular(info) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError('controller metadata snapshot must be an ordinary private file')
        if '.next' in entries:
            # A prior process may have died before atomic publication. Only the
            # closed, marker-owned cache filename is recoverable; never follow
            # links or remove an unrecognized file from this directory.
            info = os.stat('.next', dir_fd=self.directory_fd, follow_symlinks=False)
            if not _safe_regular(info) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError('controller metadata staging file is unsafe')
            os.unlink('.next', dir_fd=self.directory_fd)

    def _read_source(self):
        if metadata_file(str(self.source)) is None:
            raise ValueError('optional controller metadata source is unsafe or unavailable')
        # Validate/open each parent without following symlinks as well as the
        # final file. A parent swapped after the path check cannot redirect the
        # supervisor into a different readable host file.
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in self.source.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                os.O_CLOEXEC, dir_fd=parent)
                os.close(parent)
                parent = child
            fd = os.open(self.source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                         os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            before = os.fstat(fd)
            if not _safe_regular(before):
                raise ValueError('optional controller metadata source changed')
            identity = _file_identity(before)
            if identity == self.last_source:
                return identity, None
            chunks, remaining = [], METADATA_LIMIT + 1
            while remaining:
                block = os.read(fd, min(65536, remaining))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            data = b''.join(chunks)
            if (len(data) > METADATA_LIMIT or len(data) != before.st_size or
                    identity != _file_identity(os.fstat(fd)) or
                    identity != _file_identity(self.source.lstat())):
                raise ValueError('optional controller metadata changed during read')
            return identity, data
        finally:
            os.close(fd)

    def _publish(self, data):
        self._validate_directory()
        fd = os.open('.next', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.directory_fd)
        try:
            _write_all(fd, data)
            # SDL compares integer seconds. Distinct rapid updates must remain
            # distinguishable even when the original filesystem has fine times.
            if 'info' in os.listdir(self.directory_fd):
                self.last_mtime = max(self.last_mtime,
                    int(os.stat('info', dir_fd=self.directory_fd, follow_symlinks=False).st_mtime))
            stamp = max(1, int(time.time()), self.last_mtime + 1)
            os.utime(fd, ns=(stamp * 1000000000, stamp * 1000000000))
            os.fsync(fd)
            os.replace('.next', 'info', src_dir_fd=self.directory_fd,
                       dst_dir_fd=self.directory_fd)
            os.fsync(self.directory_fd)
            self.last_mtime = stamp
        finally:
            os.close(fd)
            try:
                os.unlink('.next', dir_fd=self.directory_fd)
            except FileNotFoundError:
                pass

    def poll(self, *, force=False, log_fd=None):
        now = time.monotonic()
        if not force and self.last_poll is not None and now - self.last_poll < self.interval:
            return False
        self.last_poll = now
        try:
            identity, data = self._read_source()
            if data is not None and data != self.last_data:
                self._publish(data)
                self.last_data = data
            self.last_source = identity
            self.failed = False
            return True
        except (OSError, ValueError):
            if log_fd is not None and not self.failed and self.reports < 8:
                try:
                    os.write(log_fd, b'[input:metadata] refresh unavailable; retaining last valid snapshot\n')
                except OSError:
                    pass
                self.reports += 1
            self.failed = True
            return False

    def fileno(self):
        return self.directory_fd

    def start(self, log_fd=None):
        """One host-only refresh thread, joined after the whole session ends."""
        if self.thread is not None:
            raise RuntimeError('controller metadata mirror is already running')
        self.stop_event = threading.Event()
        def refresh():
            while not self.stop_event.wait(self.interval):
                self.poll(log_fd=log_fd)
        self.thread = threading.Thread(target=refresh, name='monado-controller-metadata')
        self.thread.start()

    def stop(self):
        if self.thread is not None:
            self.stop_event.set()
            self.thread.join()
            self.thread = None
            self.stop_event = None

    def close(self):
        self.stop()
        if self.directory_fd is not None:
            os.close(self.directory_fd)
            self.directory_fd = None
