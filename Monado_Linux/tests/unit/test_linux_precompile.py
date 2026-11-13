"""[XCDE] LINUX-018: authored supervisor/protocol fixtures; no game or GPU."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import precompile_linux as PC


def work(session='a' * 32, identity='b' * 64, state='complete', **values):
    record = {key: 0 for key in PC.COUNTERS}
    record.update(session=session, identity=identity, state=state, phase='done', gpu_cache_uuid='0' * 32)
    record.update(values)
    return 'monado_precompile_work 1\n' + ''.join(key + ' ' + str(value) + '\n' for key, value in record.items())


class PrecompileProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = PC.directory(self.root / 'cache')
        self.addCleanup(os.close, self.fd)
        self.path = self.root / 'cache/precompile_work.txt'

    def test_complete_roundtrip_and_counter_types(self):
        self.path.write_text(work(files_total=3, files_done=3, programs=5, programs_done=5, attempted=6, built=6))
        result = PC.read_work(self.fd, 'a' * 32, 'b' * 64)
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['programs_done'], 5)
        self.assertIsInstance(result['programs_done'], int)

    def test_atomic_replace_between_open_and_fstat_keeps_old_readonly_snapshot(self):
        self.path.write_text(work(attempted=3, built=3))
        original = os.fstat
        observed = []
        def replace_before_stat(descriptor):
            replacement = self.path.with_name('replacement')
            replacement.write_text(work(attempted=7, built=7))
            os.replace(replacement, self.path)
            info = original(descriptor)
            observed.append(info.st_nlink)
            return info
        with mock.patch.object(PC.os, 'fstat', side_effect=replace_before_stat):
            result = PC.read_work(self.fd, 'a' * 32, 'b' * 64)
        self.assertEqual(observed, [0])
        self.assertEqual(result['built'], 3)
        self.assertEqual(PC.read_work(self.fd, 'a' * 32, 'b' * 64)['built'], 7)

    def test_writable_files_still_reject_unlinked_open_descriptor(self):
        self.path.write_text('preserve old bytes')
        original = os.fstat
        def unlink_before_stat(descriptor):
            self.path.unlink()
            return original(descriptor)
        with mock.patch.object(PC.os, 'fstat', side_effect=unlink_before_stat), self.assertRaisesRegex(ValueError, 'single-link'):
            PC.regular(self.fd, self.path.name, os.O_RDWR)

    def test_readonly_snapshot_rejects_foreign_owner(self):
        self.path.write_text(work())
        original = os.fstat
        def foreign_stat(descriptor):
            fields = list(original(descriptor)); fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        with mock.patch.object(PC.os, 'fstat', side_effect=foreign_stat), self.assertRaisesRegex(ValueError, 'owned regular'):
            PC.read_work(self.fd, 'a' * 32, 'b' * 64)

    def test_actual_concurrent_atomic_replacements_never_cancel_valid_work(self):
        self.path.write_text(work(attempted=0, built=0))
        started = threading.Event(); stop = threading.Event(); failures = []; writes = []
        def writer():
            started.wait()
            try:
                for number in range(1, 2001):
                    if stop.is_set(): break
                    temporary = self.path.with_name('replacement-' + str(number))
                    with temporary.open('x') as stream:
                        stream.write(work(attempted=number, built=number))
                    os.replace(temporary, self.path)
                    writes.append(number)
            except BaseException as error:
                failures.append(error)
        thread = threading.Thread(target=writer); thread.start(); started.set()
        reads = 0; deadline = time.monotonic() + 5
        try:
            while (thread.is_alive() or reads < 2000) and time.monotonic() < deadline:
                result = PC.read_work(self.fd, 'a' * 32, 'b' * 64)
                self.assertIsNotNone(result)
                self.assertEqual(result['attempted'], result['built'])
                self.assertGreaterEqual(result['built'], 0); self.assertLessEqual(result['built'], 2000)
                reads += 1
        finally:
            stop.set(); thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.assertEqual(len(writes), 2000)
        self.assertGreaterEqual(reads, 2000)

    def test_missing_and_stale_records_cannot_complete_new_session(self):
        self.assertIsNone(PC.read_work(self.fd, 'a' * 32, 'b' * 64))
        for session, identity in (('c' * 32, 'b' * 64), ('a' * 32, 'c' * 64)):
            self.path.write_text(work(session=session, identity=identity))
            self.assertIsNone(PC.read_work(self.fd, 'a' * 32, 'b' * 64))

    def test_malformed_records_fail_closed(self):
        records = [work() + 'state complete\n', work().replace('work 1', 'work 2'),
                   work(failed=-1), work(errors=1 << 64), work(files_done=1),
                   work(state='success'), work(phase='unknown'), work(gpu_cache_uuid='bad'),
                   work().replace('shaders 0\n', ''), work() + 'bad-field value\n',
                   'x' * (PC.MAX_RECORD + 1), work() + '\N{LATIN SMALL LETTER E WITH ACUTE}']
        for value in records:
            with self.subTest(value=value[:60]):
                self.path.write_text(value)
                with self.assertRaises(ValueError): PC.read_work(self.fd, 'a' * 32, 'b' * 64)

    def test_future_fields_are_ignored(self):
        self.path.write_text(work() + 'future_property value\n')
        self.assertEqual(PC.read_work(self.fd, 'a' * 32, 'b' * 64)['state'], 'complete')

    def test_linked_protocol_files_are_rejected_without_modification(self):
        original = self.root / 'original'; original.write_text('preserve')
        self.path.symlink_to(original)
        with self.assertRaises(ValueError): PC.read_work(self.fd, 'a' * 32, 'b' * 64)
        with self.assertRaises(ValueError): PC.atomic_record(self.fd, self.path.name, 'overwrite')
        self.path.unlink(); os.link(original, self.path)
        with self.assertRaises(ValueError): PC.read_work(self.fd, 'a' * 32, 'b' * 64)
        self.assertEqual(original.read_text(), 'preserve')

    def test_status_is_bounded_ascii_and_has_current_supervisor_identity(self):
        value = PC.status_record('a' * 32, 'b' * 64, 'c' * 64, 'failed', 'done', message='bad\npath\t\N{LATIN SMALL LETTER E WITH ACUTE}' * 200)
        self.assertLessEqual(len(value.encode('ascii')), PC.MAX_RECORD)
        self.assertIn('supervisor_pid ' + str(os.getpid()) + '\n', value)
        self.assertIn('session ' + 'a' * 32 + '\n', value)
        self.assertLessEqual(len(value.split('message ', 1)[1].rstrip('\n')), 512)

    def test_atomic_records_replace_without_partial_bytes_or_leftover_temporary(self):
        PC.atomic_record(self.fd, 'precompile_status.txt', 'old\n')
        PC.atomic_record(self.fd, 'precompile_status.txt', 'new\n')
        self.assertEqual((self.root / 'cache/precompile_status.txt').read_text(), 'new\n')
        self.assertEqual([p.name for p in (self.root / 'cache').iterdir()], ['precompile_status.txt'])

    def test_controls_are_explicit_bounded_and_cannot_replace_session_or_output(self):
        self.assertEqual(PC.controls(['XCDE_PRECOMPILE_THREADS=4', 'XCDE_PRECOMPILE_LIBS=1']),
                         {'XCDE_PRECOMPILE_THREADS': '4', 'XCDE_PRECOMPILE_LIBS': '1'})
        for values in (['XCDE_PRECOMPILE_THREADS=0'], ['XCDE_PRECOMPILE_THREADS=65'],
                       ['XCDE_PRECOMPILE_LIBS=2'], ['XCDE_PRECOMPILE_SESSION=0'],
                       ['XCDE_SHOTS=1:out'], ['XCDE_PRECOMPILE_LIST=/outside'],
                       ['XCDE_PRECOMPILE_THREADS=1', 'XCDE_PRECOMPILE_THREADS=2']):
            with self.subTest(values=values), self.assertRaises(ValueError): PC.controls(values)


class PrecompilePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'Monado_Linux'; self.root.mkdir()
        (self.base / 'game_files').mkdir()
        self.binary = self.root / 'build/candidate/xcde-linux'; self.binary.parent.mkdir(parents=True)
        header = bytearray(64); header[:6] = b'\x7fELF\x02\x01'; header[18:20] = (62).to_bytes(2, 'little')
        self.binary.write_bytes(header); self.binary.chmod(0o700)
        self.sysroot = self.root / '.deps/graphics/sysroots/fixture'
        (self.sysroot / 'usr/lib/x86_64-linux-gnu').mkdir(parents=True)
        (self.sysroot / '.monado-deps.json').write_text(json.dumps({'lock_sha256': 'fixture-lock'}))
        profile = self.root / 'games/xcde/profile.json'; profile.parent.mkdir(parents=True); profile.write_text('{"test":"authored"}')
        self.document = {'status': 'passed', 'generated': {'fixture': 'authored'}, 'precompile_protocol': 1,
                         'executable': {'path': str(self.binary), 'sha256': hashlib.sha256(header).hexdigest()},
                         'dependencies': {'sysroot': str(self.sysroot)},
                         'sources_before': {'graphics-deps-linux.lock.json': 'fixture-lock'}}
        self.receipt = self.binary.parent / 'receipt.json'; self.receipt.write_text(json.dumps(self.document))
        self.state = self.root / 'runs/fixture/state'
        for owner in (PC, PC.run_linux):
            patch = mock.patch.object(owner, 'ROOT', self.root); patch.start(); self.addCleanup(patch.stop)
        checker = mock.patch.object(PC.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'OK synthetic input\n', ''))
        self.checker = checker.start(); self.addCleanup(checker.stop)

    def test_identity_is_stable_and_no_preflight_writes(self):
        first = PC.prepare(self.binary, self.state)
        second = PC.prepare(self.binary, self.state)
        self.assertEqual(first['precompile_identity'], second['precompile_identity'])
        self.assertEqual(first['argv'][-2:], ['--precompile', str(self.base / 'game_files')])
        self.assertFalse(self.state.exists())
        self.assertNotIn('XCDE_PRECOMPILE_SESSION', first['environment'])

    def test_identity_changes_for_profile_and_controls(self):
        initial = PC.prepare(self.binary, self.state)['precompile_identity']
        changed = PC.prepare(self.binary, self.state, ['XCDE_PRECOMPILE_THREADS=2'])['precompile_identity']
        self.assertNotEqual(initial, changed)
        (self.root / 'games/xcde/profile.json').write_text('{"test":"different"}')
        self.assertNotEqual(initial, PC.prepare(self.binary, self.state)['precompile_identity'])

    def test_old_build_and_launcher_are_rejected_before_input_check(self):
        for change in ({'precompile_protocol': 0}, {'artifact_kind': 'linux-launcher'}, {'generated': {}}):
            with self.subTest(change=change):
                self.receipt.write_text(json.dumps({**self.document, **change}))
                with self.assertRaises(ValueError): PC.prepare(self.binary, self.state)
        self.checker.assert_not_called()

    def test_input_check_failure_prevents_any_state_or_worker(self):
        self.checker.return_value = subprocess.CompletedProcess([], 4, 'unsupported synthetic version', '')
        with self.assertRaisesRegex(ValueError, 'input check failed'): PC.prepare(self.binary, self.state)
        self.assertFalse(self.state.exists())

    def test_untrusted_inherited_controls_and_loader_injection_are_filtered(self):
        with mock.patch.dict(os.environ, {'XCDE_PRECOMPILE_SESSION': 'stale', 'LARECOMP_NO_USER_INPUT': '1',
                                          'LD_PRELOAD': '/bad', 'LD_LIBRARY_PATH': '/bad'}):
            environment = PC.prepare(self.binary, self.state)['environment']
        self.assertNotIn('XCDE_PRECOMPILE_SESSION', environment)
        self.assertNotIn('LARECOMP_NO_USER_INPUT', environment)
        self.assertNotIn('LD_PRELOAD', environment)
        self.assertEqual(environment['LD_LIBRARY_PATH'], str(self.sysroot / 'usr/lib/x86_64-linux-gnu'))

    def test_new_compiler_namespace_has_parent_death_without_mutating_game_plan(self):
        original = PC.run_linux.plan(self.binary, self.state, True)
        command = ['/usr/bin/bwrap', '--', *original['argv']]
        original.update(execution_argv=command, namespace={'kind': 'fixture'})
        with mock.patch.object(PC.run_linux, 'plan', return_value=original), \
                mock.patch.object(PC.run_linux, 'private_runtime_environment', side_effect=lambda env, *_args, **_kw: env):
            launch = PC.prepare(self.binary, self.state)
        self.assertEqual(launch['execution_argv'][1], '--die-with-parent')
        self.assertNotIn('--die-with-parent', command)
        self.assertEqual(launch['argv'][0], str(self.binary))
        self.assertTrue(launch['namespace']['compiler_parent_death'])

    def test_inherited_namespace_reuses_checked_private_desktop_environment(self):
        original = PC.run_linux.plan(self.binary, self.state, True)
        original['namespace'] = {'kind': 'inherited-private-dlss'}
        with mock.patch.object(PC.run_linux, 'plan', return_value=original), \
                mock.patch.object(PC.run_linux, 'private_runtime_environment', side_effect=lambda env, *_args, **_kw: env) as private:
            launch = PC.prepare(self.binary, self.state)
        self.assertFalse(private.call_args.kwargs['planned_namespace'])
        self.assertNotIn('execution_argv', launch)


WORKER = r'''
import os, pathlib, signal, sys, time
state=pathlib.Path(sys.argv[1]); mode=sys.argv[2]; cache=state/'cache'
session=os.environ['XCDE_PRECOMPILE_SESSION']; identity=os.environ['XCDE_PRECOMPILE_ID']
fields={key:0 for key in COUNTERS}
fields.update(session=session,identity=identity,state='running',phase='scan',gpu_cache_uuid='0'*32)
def write(**changes):
    fields.update(changes)
    temporary=cache/'fixture-work.tmp'
    temporary.write_text('monado_precompile_work 1\n'+''.join(key+' '+str(value)+'\n' for key,value in fields.items()))
    temporary.replace(cache/'precompile_work.txt')
(cache/'valid-cache.bin').write_bytes(b'preserved authored cache')
if mode=='stale':
    write(session='f'*32,state='complete',phase='done'); sys.exit(0)
if mode=='missing': sys.exit(0)
if mode=='partial': write(state='partial',phase='done',failed=1,attempted=1); sys.exit(2)
if mode=='fatal': write(state='failed',phase='done',errors=1); sys.exit(1)
if mode=='bad-complete': write(state='complete',phase='done',failed=1); sys.exit(0)
if mode=='unfinished': write(state='complete',phase='done',programs=1,programs_done=0); sys.exit(0)
if mode=='unsupported': write(state='complete',phase='done',attempted=3,built=3,unsupported=7); sys.exit(0)
if mode=='cooperate':
    write(); os.kill(os.getppid(),signal.SIGTERM)
    end=time.monotonic()+3
    while time.monotonic()<end:
        try: cancel=(cache/'precompile_cancel.txt').read_text()
        except FileNotFoundError: time.sleep(.005); continue
        if 'session '+session+'\n' in cancel:
            write(state='cancelled',phase='done'); sys.exit(130)
        time.sleep(.005)
    sys.exit(9)
if mode=='orphan':
    write()
    if os.fork()==0:
        os.setsid(); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30); os._exit(0)
    sys.exit(0)
if mode=='linger':
    write(); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30); sys.exit(9)
if mode=='adopt-exited':
    if os.fork()==0: os._exit(0)
    time.sleep(.05)
write(state='complete',phase='done',files_total=1,files_done=1,programs=1,programs_done=1,attempted=1,built=1)
sys.exit(0)
'''


@unittest.skipUnless(sys.platform == 'linux', 'native supervisor ownership')
class PrecompileSupervisionTests(unittest.TestCase):
    def run_fixture(self, mode, timeout=2, fault=False):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'
            script = textwrap.dedent(r'''
                import json, os, pathlib, signal, sys
                import precompile_linux as p
                before={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT)}
                state=pathlib.Path(STATE)
                worker='COUNTERS='+repr(p.COUNTERS)+'\n'+WORKER
                launch={'state':str(state),'cwd':'.','argv':[sys.executable,'-B','-c',worker,str(state),MODE],
                        'environment':{'PATH':'/usr/bin:/bin'},'binary_sha256':'b'*64,'precompile_identity':'c'*64}
                if FAULT:
                    original=p.atomic_record
                    def inject(fd,name,content):
                        if name=='precompile_status.txt' and 'state running\n' in content and 'phase scan\n' in content:
                            p.atomic_record=original
                            raise OSError('injected status write failure')
                        return original(fd,name,content)
                    p.atomic_record=inject
                try:
                    record=p.supervise(launch,session='a'*32,timeout=TIMEOUT,cancel_grace=.06,poll_seconds=.005)
                except OSError as error:
                    record={'error':str(error),'remaining_owned_pids':list(p.descendants())}
                record['status']=(state/'cache/precompile_status.txt').read_text()
                record['cache_unchanged']=(state/'cache/valid-cache.bin').read_bytes()==b'preserved authored cache'
                record['handlers_restored']=all(signal.getsignal(sig)==handler for sig,handler in before.items())
                record['children']=list(p.descendants())
                print(json.dumps(record))
            ''')
            prefix = 'import sys\nsys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ')\n'
            prefix += 'STATE=' + repr(str(state)) + '\nMODE=' + repr(mode) + '\nTIMEOUT=' + repr(timeout) + '\nWORKER=' + repr(WORKER) + '\nFAULT=' + repr(fault) + '\n'
            result = subprocess.run([sys.executable, '-B', '-c', prefix + script], cwd=ROOT,
                                    capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout.splitlines()[-1])
            record['cli_summaries'] = [line for line in result.stdout.splitlines() if line.startswith('[precompile-result]')]
            self.assertEqual(record['children'], [])
            self.assertEqual(record['remaining_owned_pids'], [])
            self.assertTrue(record['handlers_restored'])
            self.assertTrue(record['cache_unchanged'])
            return record

    def test_only_fresh_complete_native_result_and_exit_zero_is_success(self):
        record = self.run_fixture('complete')
        self.assertEqual(record['exit'], 0)
        self.assertEqual(record['state'], 'complete')
        self.assertFalse(record['forced'])

    def test_missing_or_stale_result_does_not_count_as_completion(self):
        for mode in ('missing', 'stale', 'unfinished'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_fixture(mode)['exit'], 1)

    def test_partial_and_fatal_results_remain_distinct(self):
        self.assertEqual(self.run_fixture('partial')['exit'], 2)
        self.assertEqual(self.run_fixture('fatal')['exit'], 1)
        self.assertEqual(self.run_fixture('bad-complete')['exit'], 2)

    def test_clean_scheduled_work_can_complete_with_explicit_unsupported_coverage(self):
        record = self.run_fixture('unsupported')
        self.assertEqual(record['exit'], 0)
        self.assertEqual(record['state'], 'complete')
        self.assertIn('unsupported 7\n', record['status'])
        self.assertIn('3 built, 7 not precompiled; remaining variants compile during play.', record['status'])

    def test_final_cli_reports_real_counters_and_retained_cache(self):
        record = self.run_fixture('partial')
        self.assertEqual(len(record['cli_summaries']), 1)
        summary = record['cli_summaries'][0]
        for expected in ('state=partial', 'worker_exit=2', 'built=0', 'failed=1', 'errors=0', 'forced=0', 'cache=retained'):
            self.assertIn(expected, summary)

    def test_cooperative_signal_cancel_retains_cache_and_reaps_worker(self):
        record = self.run_fixture('cooperate')
        self.assertEqual(record['exit'], 130)
        self.assertFalse(record['forced'])
        self.assertEqual(record['killed_owned_pids'], [])
        self.assertEqual(record['worker_exit'], 130)

    def test_timeout_force_is_limited_to_owned_worker(self):
        record = self.run_fixture('linger', timeout=.08)
        self.assertEqual(record['exit'], 130)
        self.assertTrue(record['forced'])
        self.assertTrue(record['timed_out'])
        self.assertEqual(record['worker_exit'], -signal.SIGKILL)
        self.assertTrue(record['killed_owned_pids'])

    def test_orphan_in_new_session_is_owned_until_reaped(self):
        record = self.run_fixture('orphan', timeout=.08)
        self.assertEqual(record['exit'], 130)
        self.assertTrue(record['forced'])
        self.assertTrue(record['killed_owned_pids'])

    def test_exited_adopted_helper_does_not_trigger_forced_cancel(self):
        record = self.run_fixture('adopt-exited')
        self.assertEqual(record['exit'], 0)
        self.assertEqual(record['killed_owned_pids'], [])

    def test_status_io_error_stops_only_owned_workers_and_records_forced_failure(self):
        record = self.run_fixture('linger', fault=True)
        self.assertEqual(record['error'], 'injected status write failure')
        self.assertIn('state failed\n', record['status'])
        self.assertIn('forced 1\n', record['status'])
        self.assertIn('owned workers stopped', record['status'])

    def test_supervisor_death_kills_only_its_authored_compiler_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'
            worker = "import os,pathlib,sys,time; pathlib.Path(sys.argv[1],'compiler.pid').write_text(str(os.getpid())); time.sleep(30)"
            supervisor = ('import ctypes,os,signal,sys\n'
                          'ctypes.CDLL(None).prctl(1,signal.SIGKILL,0,0,0)\n'
                          'import precompile_linux as p\n'
                          'p.supervise(' + repr({'state': str(state), 'cwd': '.',
                           'argv': [sys.executable, '-B', '-c', worker, str(state)],
                           'environment': {'PATH': '/usr/bin:/bin'},
                           'binary_sha256': 'b' * 64, 'precompile_identity': 'c' * 64}) + ')\n')
            controller = textwrap.dedent(r'''
                import ctypes,fcntl,json,os,pathlib,signal,subprocess,sys,time
                ctypes.CDLL(None).prctl(36,1,0,0,0)
                state=pathlib.Path(STATE)
                parent=subprocess.Popen([sys.executable,'-B','-c',PREFIX+SUPERVISOR],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                compiler=None; status=None
                try:
                    deadline=time.monotonic()+3
                    while not (state/'compiler.pid').exists() and time.monotonic()<deadline:
                        if parent.poll() is not None: raise RuntimeError(parent.stderr.read().decode())
                        time.sleep(.005)
                    compiler=int((state/'compiler.pid').read_text())
                    os.kill(parent.pid,signal.SIGKILL); parent.wait(timeout=2)
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline:
                        done,status=os.waitpid(compiler,os.WNOHANG)
                        if done: break
                        time.sleep(.005)
                    else: raise RuntimeError('compiler did not die with its supervisor')
                    with (state/'.precompile.lock').open('r+') as lease:
                        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    print(json.dumps({'supervisor_exit':parent.returncode,'compiler_signal':os.WTERMSIG(status),
                                      'children':pathlib.Path('/proc/self/task',str(os.getpid()),'children').read_text().strip()}))
                finally:
                    if parent.poll() is None: parent.kill(); parent.wait(timeout=2)
                    parent.stderr.close()
                    if compiler is not None and status is None:
                        try: os.kill(compiler,signal.SIGKILL)
                        except ProcessLookupError: pass
                        try: os.waitpid(compiler,0)
                        except ChildProcessError: pass
            ''')
            prefix = 'import sys\nsys.path.insert(0,' + repr(str(ROOT / 'scripts')) + ')\n'
            values = 'STATE=' + repr(str(state)) + '\nPREFIX=' + repr(prefix) + '\nSUPERVISOR=' + repr(supervisor) + '\n'
            result = subprocess.run([sys.executable, '-B', '-c', values + controller], cwd=ROOT,
                                    capture_output=True, text=True, timeout=9)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record['supervisor_exit'], -signal.SIGKILL)
            self.assertEqual(record['compiler_signal'], signal.SIGKILL)
            self.assertEqual(record['children'], '')


class PrecompileEntryTests(unittest.TestCase):
    def test_checked_cli_precompile_delegates_without_direct_exec(self):
        arguments = ['run_linux.py', '--executable', '/selected/game', '--state-root', '/selected/state',
                     '--precompile', '--dry-run', '--env', 'XCDE_PRECOMPILE_THREADS=2']
        with mock.patch.object(sys, 'argv', arguments), mock.patch.object(PC, 'main', return_value=37) as delegated, \
                mock.patch.object(PC.run_linux.os, 'execve') as execute:
            self.assertEqual(PC.run_linux.main(), 37)
        delegated.assert_called_once_with(['--executable', '/selected/game', '--state-root', '/selected/state',
                                          '--dry-run', '--env', 'XCDE_PRECOMPILE_THREADS=2'])
        execute.assert_not_called()

    def test_invalid_session_and_timing_fail_without_changing_handlers(self):
        before = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        for kwargs in ({'session': 'invalid'}, {'timeout': float('nan')}, {'cancel_grace': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): PC.supervise({}, **kwargs)
        self.assertTrue(all(signal.getsignal(number) == handler for number, handler in before.items()))

    def test_supervisor_lease_refuses_duplicate_without_overwriting_status(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'; state.mkdir()
            (state / 'cache').mkdir(); (state / 'cache/precompile_status.txt').write_text('existing active status')
            with (state / '.precompile.lock').open('w') as lease:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                launch = {'state': str(state), 'precompile_identity': 'c' * 64, 'binary_sha256': 'b' * 64}
                with self.assertRaisesRegex(ValueError, 'already using'):
                    PC.supervise(launch)
            self.assertEqual((state / 'cache/precompile_status.txt').read_text(), 'existing active status')

    def test_worker_exec_failure_restores_handlers_and_has_no_remaining_children(self):
        before = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'
            launch = {'state': str(state), 'precompile_identity': 'c' * 64, 'binary_sha256': 'b' * 64,
                      'environment': {}, 'argv': ['/no/such/authored/worker'], 'cwd': '.'}
            with self.assertRaises(FileNotFoundError): PC.supervise(launch)
            self.assertEqual(PC.descendants(), {})
        self.assertTrue(all(signal.getsignal(number) == handler for number, handler in before.items()))

    def test_preflight_cancel_publishes_fresh_result_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'
            launch = {'state': str(state), 'precompile_identity': 'c' * 64, 'binary_sha256': 'b' * 64}
            with mock.patch.object(PC.subprocess, 'Popen') as start:
                result = PC.supervise(launch, session='a' * 32, cancellation=[signal.SIGTERM])
            start.assert_not_called()
            self.assertEqual(result['exit'], 130)
            content = (state / 'cache/precompile_status.txt').read_text()
            self.assertIn('state cancelled\n', content)
            self.assertIn('session ' + 'a' * 32 + '\n', content)
            self.assertIsNone(result['worker_exit'])

    def test_preflight_cancel_skips_input_checker(self):
        with mock.patch.object(PC.subprocess, 'Popen') as checker:
            result = PC.check_input('/authored/input', [signal.SIGTERM])
        checker.assert_not_called()
        self.assertEqual(result.returncode, 130)

    def test_main_passes_early_signal_to_worker_admission_and_restores_handlers(self):
        before = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        def interrupted_prepare(*_args, **kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            self.assertEqual(kwargs['cancellation'], [signal.SIGTERM])
            return {'state': '/unused/test/state'}
        temporary = tempfile.TemporaryDirectory(prefix='monado-precompile-lease-fixture-')
        self.addCleanup(temporary.cleanup)
        port = Path(temporary.name).resolve() / 'Monado_Linux'
        port.mkdir()
        with mock.patch.object(PC, 'ROOT', port), \
                mock.patch.object(PC, 'prepare', side_effect=interrupted_prepare), \
                mock.patch.object(PC, 'supervise', return_value={'exit': 130}) as supervise:
            self.assertEqual(PC.main(['--executable', '/authored/game', '--state-root', '/authored/state']), 130)
        self.assertEqual(supervise.call_args.kwargs['cancellation'], [signal.SIGTERM])
        self.assertTrue(all(signal.getsignal(number) == handler for number, handler in before.items()))


if __name__ == '__main__':
    unittest.main()
