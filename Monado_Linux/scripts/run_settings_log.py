# [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
#!/usr/bin/env python3
"""[XCDE] LINUX-099: small private, bounded requested-settings run records.

This is a diagnostic supplement, never a source of game settings or launch
validation. Only known non-private settings are retained; keys/bindings, mod
paths and arbitrary environment values are excluded. The native log reports
actual parsed/fallback values and effective targets under the same run ID.
"""
import datetime
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
if sys.platform == 'linux':
    import fcntl
else:
    fcntl = None

DIRECTORY = 'game-runs'
MARKER = 'owner.json'
LOCK = '.lock'
OWNER = b'{"owner":"monado-game-settings-log","schema":1}\n'
MAX_RUNS = 16
MAX_INI = 262144
MAX_RECORD = 32768
MAX_LINES = 128
RUN_NAME = re.compile(r'run-([0-9a-f]{32})\.json\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
ENUMS = {
    'aspect_ratio': {'native', 'original', '16:10', '21:9', '32:9'},
    'resolution': {'match', 'dynamic', '75%', '50%', '25%', *(str(n) for n in range(1, 9))},
    'upscaler': {'bilinear', 'fsr', 'fsr3', 'dlss'},
    'upscale_quality': {'native', 'quality', 'balanced', 'performance', 'ultra'},
    'antialias': {'smaa', 'off'},
    'fps_overlay_mode': {'off', 'number', 'compact', 'detailed'},
    'cutscenes': {'same', '30', '30fg'},
    'fps': {'unlimited'},
    'menu_navigation_speed': {'normal', 'fast'},
    'language': {'auto', 'ja', 'en-US', 'fr', 'de', 'it', 'es', 'zh-CN', 'ko', 'nl', 'pt', 'ru'},
    'launcher_lang': {'en', 'es'},
    'button_icons': {'auto', 'nintendo', 'xbox', 'playstation', 'keyboard'},
}
NUMBERS = {'fps', 'volume', 'stick_deadzone'}
BOOLS = {'fullscreen', 'frame_gen', 'frame_gen_smooth_motion', 'frame_gen_match_display',
         'depth_of_field', 'game_blur', 'vsync', 'party_switch', 'show_fps',
         'show_fps_overlay', 'quickstep_slot', 'movie_audio', 'cheat_no_fall_damage',
         'mod_icons_xbox', 'mod_icons_playstation', 'mod_icons_keyboard'}
for _name in ('damage_dealt', 'damage_received', 'exp', 'ap', 'sp', 'gold', 'movement_speed', 'enemy_health'):
    BOOLS.add('cheat_' + _name)
    NUMBERS.add('cheat_' + _name + '_percent')
KNOWN = set(ENUMS) | NUMBERS | BOOLS | {'window'}
NUMERIC = re.compile(r'[+-]?[0-9]{1,9}(?:\.[0-9]{1,9})?\Z')
REPORT_KEYS = {'method', 'external_driver_enabled', 'component_available', 'output_fps',
               'counter_status', 'counter_available', 'counter_kind', 'cuda_task_metadata',
               'observer_requested', 'cuda_task_metadata_protocol'}
REPORT_BOOLEANS = {'external_driver_enabled', 'component_available', 'counter_available',
                   'cuda_task_metadata', 'observer_requested'}
TIMING_KEYS = {'XCDE_FPS_PERIOD_SCALE', 'XCDE_FPS_INTERVAL', 'XCDE_FPS_AFTER_S', 'XCDE_FPS_AFTER_FRAMES'}


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_regular(parent, name, limit):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
            before.st_nlink != 1 or not 0 <= before.st_size <= limit):
        raise ValueError('untrusted diagnostic file')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
        opened = os.fstat(fd)
        chunks = []
        total = 0
        while total <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    final = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (_identity(before) != _identity(opened) or _identity(opened) != _identity(after) or
            _identity(before) != _identity(final) or total != before.st_size or total > limit):
        raise ValueError('diagnostic file changed')
    return b''.join(chunks), before


def _open_directory(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        os.close(fd)
        raise ValueError('untrusted diagnostic directory')
    return fd


def _state_directory(state, *, create=True):
    state = Path(state)
    if not state.is_absolute() or state.resolve() != state or state == Path('/'):
        raise ValueError('noncanonical diagnostic state')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in state.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise ValueError('untrusted diagnostic state')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _valid_value(key, value):
    if key in ENUMS and value in ENUMS[key]:
        return True
    if key in BOOLS:
        return value in ('true', 'false') or bool(re.fullmatch(r'[+-]?[0-9]{1,9}', value))
    if key in NUMBERS:
        return bool(NUMERIC.fullmatch(value))
    if key == 'window':
        return bool(re.fullmatch(r'[0-9]{1,5}x[0-9]{1,5}', value))
    return False


def requested_settings(state_fd):
    try:
        raw, _ = _read_regular(state_fd, 'xcde.ini', MAX_INI)
    except FileNotFoundError:
        return {'status': 'missing', 'known_settings_ini': '', 'redacted_invalid_values': 0}
    except (OSError, ValueError):
        return {'status': 'unavailable-or-untrusted', 'known_settings_ini': '', 'redacted_invalid_values': 0}
    row = {'status': 'captured-known-settings', 'source_sha256': hashlib.sha256(raw).hexdigest(),
           'known_settings_ini': '', 'redacted_invalid_values': 0,
           'note': 'Requested known settings only; native run log records parsed/effective values. Private and unknown keys excluded.'}
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        row['status'] = 'invalid-encoding'
        return row
    lines = []
    for line in text.splitlines():
        line = line.lstrip('\ufeff').strip()
        if not line or line[0] in '#;[' or '=' not in line:
            continue
        key, value = (part.strip() for part in line.split('=', 1))
        if key not in KNOWN:
            continue
        if not _valid_value(key, value):
            row['redacted_invalid_values'] += 1
            continue
        lines.append(key + ' = ' + value + '\n')
        if len(lines) > MAX_LINES or sum(map(len, lines)) > 16384:
            row['status'] = 'too-many-known-settings'
            return row
    row['known_settings_ini'] = ''.join(lines)
    return row


def _safe_report(report):
    result = {}
    if not isinstance(report, dict):
        return result
    for key in REPORT_KEYS:
        value = report.get(key)
        if value is None:
            result[key] = value
        elif key in REPORT_BOOLEANS:
            if isinstance(value, bool):
                result[key] = value
        elif key == 'cuda_task_metadata_protocol':
            if type(value) is int and value == 1:
                result[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and abs(value) <= 1000000:
            result[key] = value
        elif isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.+-]{1,96}', value):
            result[key] = value
    return result


def _existing_records(fd):
    records = []
    for name in os.listdir(fd):
        if name in (MARKER, LOCK):
            continue
        match = RUN_NAME.fullmatch(name)
        if not match:
            raise ValueError('foreign or interrupted diagnostic entry preserved')
        raw, info = _read_regular(fd, name, MAX_RECORD)
        document = json.loads(raw)
        if (not isinstance(document, dict) or document.get('schema') != 1 or
                document.get('owner') != 'monado-game-settings-log' or
                document.get('run_id') != match[1] or not isinstance(document.get('started_utc'), str)):
            raise ValueError('unrecognized diagnostic record preserved')
        stored_digest = document.pop('record_sha256', None)
        if not isinstance(stored_digest, str) or stored_digest != hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest():
            raise ValueError('modified diagnostic record preserved')
        records.append((info.st_mtime_ns, name, info))
    return sorted(records)


def _publish(fd, name, data):
    temporary = '.' + name + '.tmp'
    opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
    info = os.fstat(opened)
    published = False
    try:
        with os.fdopen(opened, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication without replacing an existing name. The final file
        # is visible only after all bytes have been flushed successfully.
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        published = True
    finally:
        try:
            current = os.stat(temporary, dir_fd=fd, follow_symlinks=False)
            if current.st_dev == info.st_dev and current.st_ino == info.st_ino:
                os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
    if published:
        os.fsync(fd)


def record_game_run(launch, environment, *, manifest=None):
    """Return a new ID even when optional recording fails; never stop gameplay.

    The caller admits this generated ID after ordinary launch validation and
    before exec. Dry runs and precompile must not call this function.
    """
    run_id = secrets.token_hex(16)
    result = {'run_id': run_id, 'status': 'unavailable'}
    state_fd = logs_fd = runs_fd = lock_fd = None
    try:
        state_fd = _state_directory(launch['state'])
        requested = requested_settings(state_fd)
        logs_fd = _open_directory(state_fd, 'logs', create=True)
        runs_fd = _open_directory(logs_fd, DIRECTORY, create=True)
        try:
            marker, _ = _read_regular(runs_fd, MARKER, len(OWNER))
            if marker != OWNER:
                raise ValueError('foreign diagnostic marker preserved')
        except FileNotFoundError:
            if os.listdir(runs_fd):
                raise ValueError('foreign diagnostic directory preserved')
            _publish(runs_fd, MARKER, OWNER)
        lock_fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                          0o600, dir_fd=runs_fd)
        lock_info = os.fstat(lock_fd)
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or
                lock_info.st_nlink != 1 or lock_info.st_size != 0 or fcntl is None):
            raise ValueError('untrusted diagnostic lock')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = _existing_records(runs_fd)
        if len(old) > MAX_RUNS:
            raise ValueError('unexpected diagnostic inventory preserved')
        controls = sorted(key for key in environment if re.fullmatch(r'(?:XCDE|LARECOMP)_[A-Z0-9_]{1,80}', key))[:64]
        timing = {key: environment[key] for key in TIMING_KEYS
                  if isinstance(environment.get(key), str) and NUMERIC.fullmatch(environment[key])}
        binary = launch.get('binary_sha256')
        document = {'schema': 1, 'owner': 'monado-game-settings-log', 'run_id': run_id,
                    'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'binary_sha256': binary if isinstance(binary, str) and HASH.fullmatch(binary) else None,
                    'frame_generation_request': _safe_report(launch.get('frame_generation')),
                    'requested_settings': requested, 'runtime_control_names': controls,
                    'timing_overrides': timing}
        if manifest is not None:
            path = Path(manifest)
            source_fd = None
            try:
                source_fd = _state_directory(path.parent, create=False)
                source_raw, _ = _read_regular(source_fd, path.name, 1048576)
                document['source_manifest_sha256'] = hashlib.sha256(source_raw).hexdigest()
            except (OSError, ValueError):
                # An absent/untrusted source identity does not invalidate the
                # receipted binary, whose validation is owned by the caller.
                pass
            finally:
                if source_fd is not None:
                    os.close(source_fd)
        document['record_sha256'] = hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        data = (json.dumps(document, indent=2, sort_keys=True) + '\n').encode('utf-8')
        if len(data) > MAX_RECORD:
            raise ValueError('diagnostic record exceeds bound')
        _publish(runs_fd, 'run-' + run_id + '.json', data)
        # Only previously validated records in our marker-owned directory are
        # candidates. Recheck their exact identity before unlinking by dirfd.
        for _, name, info in old[:max(0, len(old) + 1 - MAX_RUNS)]:
            current = os.stat(name, dir_fd=runs_fd, follow_symlinks=False)
            if _identity(info) != _identity(current):
                raise ValueError('changed diagnostic record preserved')
            os.unlink(name, dir_fd=runs_fd)
        os.fsync(runs_fd)
        result['status'] = 'recorded'
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError) as error:
        # Diagnostics are optional. Preserve unknown/foreign entries and native
        # launch behavior; never relax validation or mutate the player's INI.
        result['reason'] = ('busy' if isinstance(error, OSError) and error.errno in (errno.EAGAIN, errno.EWOULDBLOCK)
                            else 'storage-full' if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT)
                            else 'io-unavailable' if isinstance(error, OSError)
                            else 'untrusted-or-modified-log-state')
    finally:
        for fd in (lock_fd, runs_fd, logs_fd, state_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
    return result
