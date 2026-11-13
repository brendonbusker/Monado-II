#!/usr/bin/env python3
"""[XCDE] LINUX-018: supervise an explicitly requested native shader precompile.

The checked game ELF runs only its --precompile entry. Progress and cancellation
are session keyed; completion requires a fresh, flushed native result and a
successful process exit. This module never launches gameplay or retries/skips a
failed shader. --dry-run validates without creating state or starting a worker.
"""
import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time

import run_linux

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 1
MAX_RECORD = 8192
COUNTERS = ('files_total', 'files_done', 'shaders', 'programs', 'programs_done',
            'seed_total', 'seed_done', 'variants_total', 'variants_done',
            'attempted', 'built', 'failed', 'skipped', 'unsupported', 'errors',
            'gpu_vendor', 'gpu_device', 'gpu_driver')
PHASES = frozenset(('scan', 'build', 'seed', 'pipelines', 'done'))
WORK_STATES = frozenset(('running', 'complete', 'partial', 'cancelled', 'failed'))
CONTROLS = frozenset(('XCDE_PRECOMPILE_THREADS', 'XCDE_PRECOMPILE_LIBS',
                      'XCDE_PRECOMPILE_PIPELINES', 'XCDE_TEST_PRECOMPILE_CRASH'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def controls(entries):
    result = {}
    for entry in entries:
        key, separator, value = entry.partition('=')
        if not separator or key not in CONTROLS or key in result or not value.isdecimal():
            raise ValueError('unsupported or duplicate explicit precompile control: ' + key)
        number = int(value)
        valid = (1 <= number <= 64 if key == 'XCDE_PRECOMPILE_THREADS' else
                 1 <= number <= 1000000 if key == 'XCDE_TEST_PRECOMPILE_CRASH' else
                 number in (0, 1))
        if not valid:
            raise ValueError('invalid precompile control value: ' + key)
        result[key] = str(number)
    return result


def parent_death_guard():
    """Prepare the compiler/checker-only lifetime guard before a single-thread fork."""
    libc = ctypes.CDLL(None, use_errno=True)
    parent_pid = os.getpid()
    def lifetime():
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) or os.getppid() != parent_pid:
            os._exit(126)  # PR_SET_PDEATHSIG, including its setup race
    return lifetime


def check_input(source, cancellation=None):
    command = [str(ROOT / '.venv/bin/python'), '-B',
               str(ROOT / 'tools/extract/check_dump.py'), source]
    options = {'cwd': ROOT, 'env': {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}}
    if cancellation is None:
        return subprocess.run(command, capture_output=True, text=True, timeout=120, **options)
    if cancellation:
        return subprocess.CompletedProcess(command, 130, 'Input validation cancelled.', '')
    # Cancellation during preflight owns this exact checker too. It cannot leave
    # a checker orphan or wait for its full 120-second bound after the UI stops.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True,
                          preexec_fn=parent_death_guard(), **options) as checker:
        deadline = time.monotonic() + 120
        while True:
            try:
                stdout, stderr = checker.communicate(timeout=0.1)
                return subprocess.CompletedProcess(command, checker.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if cancellation or time.monotonic() >= deadline:
                    checker.terminate()
                    try:
                        stdout, stderr = checker.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        checker.kill()
                        stdout, stderr = checker.communicate()
                    if cancellation:
                        return subprocess.CompletedProcess(command, 130, stdout, stderr)
                    raise subprocess.TimeoutExpired(command, 120, stdout, stderr)


def prepare(executable, state, entries=(), *, cancellation=None):
    requested_controls = controls(entries)
    launch = run_linux.plan(executable, state, precompile=True)
    if 'execution_argv' in launch:
        # This is a compiler-only namespace. Ordinary Play/outer GUI lifetimes
        # retain their existing behavior when a launcher closes or dies.
        launch['execution_argv'] = list(launch['execution_argv'])
        launch['execution_argv'].insert(1, '--die-with-parent')
        launch['namespace'] = {**launch['namespace'], 'compiler_parent_death': True}
    receipt = json.loads((Path(launch['argv'][0]).parent / 'receipt.json').read_text())
    if receipt.get('artifact_kind') == 'linux-launcher' or not receipt.get('generated'):
        raise ValueError('precompile requires a complete receipted game build')
    if type(receipt.get('precompile_protocol')) is not int or receipt['precompile_protocol'] != PROTOCOL:
        raise ValueError('selected build does not support the Linux precompile protocol')
    check = check_input(launch['input'], cancellation)
    if check.returncode and not (check.returncode == 130 and cancellation):
        raise ValueError('selected game input check failed: ' + check.stdout + check.stderr)
    profile = ROOT / 'games/xcde/profile.json'
    marker = Path(receipt['dependencies']['sysroot']) / '.monado-deps.json'
    identity = {'protocol': PROTOCOL, 'binary_sha256': launch['binary_sha256'],
                'input_profile_sha256': digest(profile),
                'graphics_lock_sha256': receipt['sources_before']['graphics-deps-linux.lock.json'],
                'sysroot_marker_sha256': digest(marker),
                'runtime_resources': {name: item['sha256'] for name, item in
                                      receipt.get('runtime_resources', {}).items()},
                'controls': requested_controls}
    launch['precompile_identity'] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    launch['precompile_identity_inputs'] = identity
    launch['input_check'] = check.stdout.strip()
    launch['controls'] = identity['controls']
    # Match the checked normal CLI's desktop environment policy, without leaked
    # runtime controls or loader injection. Do not mutate process-global getenv.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('XCDE_', 'LARECOMP_', 'LASRECOMP_', 'MONADO_'))
                   and not key.startswith('LD_') and key != 'GLIBC_TUNABLES'}
    environment.update(launch['controls'])
    environment.update(LD_LIBRARY_PATH=launch['library_path'], SDL_APP_ID='monado-linux-port',
                       XCDE_STRICT='1', XCDE_NO_ERROR_DIALOG='1',
                       XCDE_INI=str(Path(launch['state']) / 'xcde.ini'))
    if 'namespace' in launch:
        environment = run_linux.private_runtime_environment(
            environment, Path(launch['state']), planned_namespace='execution_argv' in launch)
    launch['environment'] = environment
    return launch


def directory(path):
    """Create/open canonical directories using nofollow dirfds, never replace."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in Path(path).parts[1:]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def ordinary(fd, name, *, absent=True):
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        if absent:
            return
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('precompile state file must be ordinary and single-link: ' + name)


def regular(fd, name, flags):
    ordinary(fd, name)
    result = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=fd)
    info = os.fstat(result)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(result)
        raise ValueError('precompile state file must be ordinary and single-link: ' + name)
    return result


def readonly_snapshot(fd, name):
    """Pin one owned atomic-replacement snapshot without weakening writers.

    The native writer can rename a new file over this name after open(). The
    old descriptor then has zero links, but still holds its complete immutable
    bytes. Multiple links, foreign ownership and non-regular files remain errors.
    """
    try:
        result = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError('precompile snapshot must be an owned regular file without symlinks: ' + name) from error
        raise
    try:
        info = os.fstat(result)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink not in (0, 1)):
            raise ValueError('precompile snapshot must be an owned regular file without multiple links: ' + name)
    except BaseException:
        os.close(result)
        raise
    return result


def atomic_record(fd, name, content):
    data = content.encode('ascii')
    if len(data) > MAX_RECORD:
        raise ValueError('precompile record exceeds the protocol bound')
    ordinary(fd, name)
    temporary = '.' + name + '.' + secrets.token_hex(8)
    out = regular(fd, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(out, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def read_work(fd, session, identity):
    try:
        source = readonly_snapshot(fd, 'precompile_work.txt')
    except FileNotFoundError:
        return None
    with os.fdopen(source, 'rb') as stream:
        data = stream.read(MAX_RECORD + 1)
    if len(data) > MAX_RECORD:
        raise ValueError('native precompile record exceeds the protocol bound')
    try:
        lines = data.decode('ascii').splitlines()
    except UnicodeDecodeError as error:
        raise ValueError('native precompile record is not ASCII') from error
    if not lines or lines[0] != 'monado_precompile_work 1':
        raise ValueError('unsupported native precompile work protocol')
    record = {}
    for line in lines[1:]:
        key, separator, value = line.partition(' ')
        if not separator or key in record or not re.fullmatch(r'[a-z_]+', key):
            raise ValueError('malformed native precompile work record')
        record[key] = value
    # An old run is not a result, and cannot cancel or complete the new session.
    if record.get('session') != session or record.get('identity') != identity:
        return None
    if record.get('phase') not in PHASES or record.get('state') not in WORK_STATES:
        raise ValueError('invalid native precompile phase/state')
    for key in COUNTERS:
        value = record.get(key)
        if value is None or not value.isdecimal() or len(value) > 20 or int(value) > (1 << 64) - 1:
            raise ValueError('invalid native precompile counter: ' + key)
        record[key] = int(value)
    if not re.fullmatch(r'[0-9a-f]{32}', record.get('gpu_cache_uuid', '')):
        raise ValueError('invalid native precompile GPU cache UUID')
    for done, total in (('files_done', 'files_total'), ('programs_done', 'programs'),
                        ('seed_done', 'seed_total'), ('variants_done', 'variants_total')):
        if record[done] > record[total]:
            raise ValueError('native precompile progress exceeds its total')
    return record


def status_record(session, build, identity, state, phase, work=None, *, forced=False, message=''):
    if not re.fullmatch(r'[0-9a-f]{32}', session) or any(
            not re.fullmatch(r'[0-9a-f]{64}', value) for value in (build, identity)):
        raise ValueError('invalid precompile status identity')
    clean = ''.join(char if 32 <= ord(char) <= 126 else ' ' for char in str(message))[:512]
    rows = ['monado_precompile_status 1', 'session ' + session, 'build ' + build,
            'identity ' + identity, 'supervisor_pid ' + str(os.getpid()),
            'state ' + state, 'phase ' + phase, 'forced ' + str(int(forced))]
    rows += [key + ' ' + str((work or {}).get(key, 0)) for key in COUNTERS]
    rows.append('gpu_cache_uuid ' + (work or {}).get('gpu_cache_uuid', '0' * 32))
    rows.append('message ' + clean)
    return '\n'.join(rows) + '\n'


def child_id(pid):
    """Kernel identity plus parent/state, never a guessed executable/name match."""
    try:
        data = Path('/proc', str(pid), 'stat').read_text()
        fields = data[data.rfind(')') + 2:].split()
        return (pid, int(fields[19])), int(fields[1]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants():
    """Bounded fresh ancestry walk; subreaping retains escaped worker orphans."""
    pending = [os.getpid()]
    found = {}
    for parent in pending:
        tasks = Path('/proc', str(parent), 'task')
        try:
            threads = list(tasks.iterdir())
        except FileNotFoundError:
            continue
        if len(threads) > 256:
            raise RuntimeError('precompile worker thread limit exceeded')
        for thread in threads:
            try:
                children = (thread / 'children').read_text().split()
            except FileNotFoundError:
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
                    raise RuntimeError('precompile worker process limit exceeded')
    return found


def force_owned(owned):
    killed = []
    for pid, (identity, _parent, state) in owned.items():
        if state == 'Z':
            continue
        try:
            descriptor = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            continue
        try:
            current = child_id(pid)
            if current is None or current[0] != identity or current[2] == 'Z':
                continue
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            killed.append(pid)
        except ProcessLookupError:
            pass
        finally:
            os.close(descriptor)
    return killed


def supervise(launch, *, session=None, timeout=21600, cancel_grace=15, poll_seconds=0.1, cancellation=None, runtime_fd=None):
    """Own only this requested compiler and its descendants until reaped.

    Signals request cooperative cancellation. Parent death terminates only this
    requested compiler. No imported boot runner, process-name search, automatic
    retry or gameplay path is used.
    """
    session = session or secrets.token_hex(16)
    if not re.fullmatch(r'[0-9a-f]{32}', session):
        raise ValueError('precompile session must be 32 lowercase hexadecimal digits')
    if any(not math.isfinite(value) or value <= 0 for value in (timeout, cancel_grace, poll_seconds)):
        raise ValueError('precompile timing bounds must be finite and positive')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('precompile supervision requires Linux pidfd signals')
    if descendants():
        raise RuntimeError('precompile supervisor must not own unrelated children')
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'cannot enable precompile child subreaper')
    pending = cancellation if cancellation is not None else []
    def request(number, _frame):
        if not pending:
            pending.append(number)
    handlers = {number: signal.signal(number, request) for number in
                (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    state = Path(launch['state'])
    identity = launch['precompile_identity']
    build = launch['binary_sha256']
    descriptors = []
    child = None
    cache = None
    cancelled = None
    forced = False
    timed_out = False
    work = None
    failure = None
    exception_message = None
    result = 1
    killed = []
    started = time.monotonic()
    try:
        state_fd = directory(state); descriptors.append(state_fd)
        lease = regular(state_fd, '.precompile.lock', os.O_RDWR | os.O_CREAT); descriptors.append(lease)
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('a shader precompile is already using this state directory') from None
        cache = directory(state / 'cache'); descriptors.append(cache)
        logs = directory(state / 'logs'); descriptors.append(logs)
        log_fd = regular(logs, 'precompile-worker.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        descriptors.append(log_fd)
        supervisor_log = regular(logs, 'launcher-precompile.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        descriptors.append(supervisor_log)
        # Refuse hostile existing protocol paths before spawning any worker.
        for name in ('precompile_status.txt', 'precompile_work.txt', 'precompile_cancel.txt'):
            ordinary(cache, name)
        if 'namespace' in launch:
            run_linux.prepare_namespace_state(launch)
        last_status = None
        last_transition = None
        def publish(current, phase, message):
            nonlocal last_status, last_transition
            content = status_record(session, build, identity, current, phase, work,
                                    forced=forced, message=message)
            if content != last_status:
                atomic_record(cache, 'precompile_status.txt', content)
                last_status = content
            if (current, phase) != last_transition:
                line = ('[precompile] session=' + session + ' identity=' + identity +
                        ' state=' + current + ' phase=' + phase + '\n').encode('ascii')
                while line:
                    line = line[os.write(supervisor_log, line):]
                last_transition = (current, phase)
        publish('starting', 'validating', 'Starting the checked native shader compiler.')
        if pending:
            publish('cancelled', 'done', 'Precompile cancelled during validation; no compiler worker was started.')
            os.fsync(supervisor_log)
            return {'state': 'cancelled', 'exit': 130, 'session': session, 'identity': identity,
                    'forced': False, 'timed_out': False, 'killed_owned_pids': [],
                    'remaining_owned_pids': [], 'worker_exit': None,
                    'seconds': time.monotonic() - started}
        environment = dict(launch['environment'])
        environment.update(XCDE_PRECOMPILE_ID=identity, XCDE_PRECOMPILE_SESSION=session)
        execution = launch.get('execution_argv', launch['argv'])
        child = subprocess.Popen(execution, cwd=launch['cwd'], env=environment,
                                 stdin=subprocess.DEVNULL, stdout=log_fd, stderr=log_fd,
                                 start_new_session=True, close_fds=True,
                                 pass_fds=(() if runtime_fd is None else (runtime_fd,)),
                                 preexec_fn=parent_death_guard())
        while True:
            exit_code = child.poll()
            # Reap adopted helpers, preserving Popen's owned direct-child status.
            owned = descendants()
            for pid, item in list(owned.items()):
                if pid != child.pid and item[2] == 'Z' and item[1] == os.getpid():
                    try:
                        os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
            owned = descendants()
            try:
                latest = read_work(cache, session, identity)
                if latest is not None:
                    work = latest
            except (ValueError, OSError) as error:
                failure = str(error)
                if not pending:
                    pending.append(signal.SIGTERM)
            now = time.monotonic()
            if not pending and now - started >= timeout:
                timed_out = True
                pending.append(signal.SIGTERM)
            if pending and cancelled is None:
                cancelled = now
                atomic_record(cache, 'precompile_cancel.txt',
                              'monado_precompile_cancel 1\nsession ' + session + '\n')
            if cancelled is not None and owned and now - cancelled >= cancel_grace:
                hits = force_owned(owned)
                if hits:
                    forced = True
                    killed.extend(hits)
            if exit_code is not None and not owned:
                break
            if cancelled is not None:
                publish('cancelling', (work or {}).get('phase', 'validating'),
                        'Stopping owned compiler workers.' if forced else
                        'Cancel requested; waiting for the current compiler job to finish.')
            else:
                publish('running', (work or {}).get('phase', 'validating'), 'Preparing shader caches.')
            time.sleep(poll_seconds)
        child.wait()
        if failure:
            final, result, message = 'failed', 1, failure
        elif cancelled is not None:
            final, result = 'cancelled', 130
            message = ('Precompile timed out; ' if timed_out else 'Precompile cancelled; ')
            message += ('owned compiler workers required forced termination. Valid caches are retained.' if forced
                        else 'valid caches are retained and can be reused on the next run.')
        elif child.returncode == 0 and work and work['state'] == 'complete' and work['phase'] == 'done':
            incomplete = any(work[done] != work[total] for done, total in
                             (('files_done', 'files_total'), ('programs_done', 'programs'),
                              ('seed_done', 'seed_total'), ('variants_done', 'variants_total')))
            if incomplete:
                final, result, message = 'failed', 1, 'Native precompile completion has unfinished work counters.'
            elif work['failed'] or work['skipped'] or work['errors']:
                final, result, message = 'partial', 2, 'Precompile ended with failed or skipped work; inspect the worker log.'
            else:
                final, result = 'complete', 0
                message = (str(work['built']) + ' built, ' + str(work['unsupported']) +
                           ' not precompiled; remaining variants compile during play.')
        elif work and work['state'] == 'partial' and work['phase'] == 'done' and child.returncode in (0, 2):
            final, result, message = 'partial', 2, 'Precompile completed partially; inspect failed, skipped and unsupported counts.'
        elif work and work['state'] == 'cancelled' and work['phase'] == 'done' and child.returncode == 130:
            final, result, message = 'cancelled', 130, 'Precompile cancelled; valid caches are retained.'
        else:
            final, result, message = 'failed', 1, 'Native precompile did not produce a fresh complete result (exit ' + str(child.returncode) + '). See logs/precompile-worker.log.'
        publish(final, 'done', message)
        counts = work or {}
        summary = ('[precompile-result] state=' + final + ' worker_exit=' + str(child.returncode) +
                   ' programs=' + str(counts.get('programs_done', 0)) + '/' + str(counts.get('programs', 0)) +
                   ' built=' + str(counts.get('built', 0)) + ' failed=' + str(counts.get('failed', 0)) +
                   ' unsupported=' + str(counts.get('unsupported', 0)) + ' errors=' + str(counts.get('errors', 0)) +
                   ' forced=' + str(int(forced)) + ' cache=retained')
        pending_log = (summary + '\n').encode('ascii')
        while pending_log:
            pending_log = pending_log[os.write(supervisor_log, pending_log):]
        os.fsync(supervisor_log)
        print(summary, flush=True)
        print(message, flush=True)
        return {'state': final, 'exit': result, 'session': session, 'identity': identity,
                'forced': forced, 'timed_out': timed_out, 'killed_owned_pids': sorted(set(killed)),
                'remaining_owned_pids': sorted(descendants()), 'worker_exit': child.returncode,
                'seconds': time.monotonic() - started}
    except BaseException as error:
        exception_message = str(error)
        if cache is not None and child is not None:
            try:
                atomic_record(cache, 'precompile_status.txt', status_record(
                    session, build, identity, 'failed', (work or {}).get('phase', 'validating'),
                    work, forced=forced, message='Supervisor failed; cancelling owned workers. ' + str(error)))
            except (OSError, ValueError):
                pass
        raise
    finally:
        # An exceptional supervisor path still owns only its requested workers.
        # First request cancellation and allow native cache writers to settle.
        try:
            if child is not None and descendants():
                if cache is not None:
                    try:
                        atomic_record(cache, 'precompile_cancel.txt',
                                      'monado_precompile_cancel 1\nsession ' + session + '\n')
                    except (OSError, ValueError):
                        pass
                deadline = time.monotonic() + cancel_grace
                while descendants() and time.monotonic() < deadline:
                    child.poll()
                    for pid, item in descendants().items():
                        if pid != child.pid and item[2] == 'Z' and item[1] == os.getpid():
                            try:
                                os.waitpid(pid, os.WNOHANG)
                            except ChildProcessError:
                                pass
                    time.sleep(poll_seconds)
                while descendants():
                    hits = force_owned(descendants())
                    if hits:
                        forced = True
                        killed.extend(hits)
                    child.poll()
                    for pid, item in descendants().items():
                        if pid != child.pid and item[2] == 'Z' and item[1] == os.getpid():
                            try:
                                os.waitpid(pid, os.WNOHANG)
                            except ChildProcessError:
                                pass
                    time.sleep(poll_seconds)
                child.wait()
            if exception_message is not None and cache is not None and child is not None:
                try:
                    atomic_record(cache, 'precompile_status.txt', status_record(
                        session, build, identity, 'failed', (work or {}).get('phase', 'validating'),
                        work, forced=forced, message='Supervisor failed; owned workers stopped. ' + exception_message))
                except (OSError, ValueError):
                    pass
        finally:
            try:
                for fd in reversed(descriptors):
                    os.close(fd)
            finally:
                for number, handler in handlers.items():
                    signal.signal(number, handler)
                if libc.prctl(36, previous.value, 0, 0, 0):
                    raise OSError(ctypes.get_errno(), 'cannot restore precompile child subreaper')


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--session', help='fresh launcher-generated 32-digit lowercase hexadecimal nonce')
    parser.add_argument('--env', action='append', default=[], metavar='NAME=VALUE',
                        help='explicit bounded precompile controls only')
    parser.add_argument('--timeout', type=float, default=21600,
                        help='wall limit in seconds, 1..86400; cancellation grace is 15 seconds')
    return parser, parser.parse_args(argv)


def main(argv=None):
    parser, args = arguments(argv)
    cancellation = []
    runtime_fd = None
    def request(number, _frame):
        if not cancellation:
            cancellation.append(number)
    handlers = {number: signal.signal(number, request) for number in
                (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 86400:
            raise ValueError('--timeout must be finite and in 1..86400 seconds')
        if args.session is not None and not re.fullmatch(r'[0-9a-f]{32}', args.session):
            raise ValueError('--session must be 32 lowercase hexadecimal digits')
        if not args.dry_run:
            runtime_fd = run_linux.install_lease.acquire_runtime(ROOT)
        launch = prepare(args.executable, args.state_root, args.env, cancellation=cancellation)
        if args.dry_run:
            if cancellation:
                return 130
            visible = {key: value for key, value in launch.items() if key != 'environment'}
            print(json.dumps(visible, indent=2))
            return 0
        if not cancellation:
            launch['runtime_validation'] = run_linux.validate_runtime(launch)
        os.umask(0o077)
        return supervise(launch, session=args.session, timeout=args.timeout, cancellation=cancellation, runtime_fd=runtime_fd)['exit']
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')
    finally:
        run_linux.install_lease.release(runtime_fd)
        for number, handler in handlers.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    sys.exit(main())
