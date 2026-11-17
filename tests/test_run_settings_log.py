"""LINUX-099: private per-run requested/effective settings diagnostics."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
SPEC = importlib.util.spec_from_file_location('authored_run_settings_log', PORT / 'scripts/run_settings_log.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
native = None
if sys.platform == 'linux':
    NATIVE_SPEC = importlib.util.spec_from_file_location('authored_run_log_native', PORT / 'scripts/run_linux.py')
    native = importlib.util.module_from_spec(NATIVE_SPEC)
    NATIVE_SPEC.loader.exec_module(native)

@unittest.skipUnless(sys.platform == 'linux', 'Linux private diagnostic records')
class RunSettingsLog(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-run-log-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.ini = self.state / 'xcde.ini'
        self.manifest = self.root / 'publication-manifest.json'
        self.manifest.write_text('{"authored":true}\n')
        self.launch = {'state': str(self.state), 'binary_sha256': 'a' * 64,
                       'frame_generation': {'method': 'nvidia-smooth-motion', 'external_driver_enabled': True,
                                            'output_fps': 'external-driver-unavailable-to-application',
                                            'private_path': '/not-recorded', 'counter_status': '/not-recorded'}}
    def record(self):
        result = helper.record_game_run(self.launch, {'XCDE_FPS_INTERVAL': '1', 'XCDE_INI': '/private/path',
            'XCDE_SECRET': 'TOP_SECRET_ENVIRONMENT', 'MONADO_RUN_ID': '/untrusted', 'PATH': '/private/bin'}, manifest=self.manifest)
        self.assertRegex(result['run_id'], r'^[0-9a-f]{32}$')
        return result
    def path(self, result):
        return self.state / 'logs/game-runs' / ('run-' + result['run_id'] + '.json')
    def test_known_requested_snapshot_binary_identity_and_private_exclusion(self):
        text = 'fps = 120\nfps_overlay_mode = detailed\nupscaler = dlss\nupscale_quality = native\nframe_gen_smooth_motion = 1\nframe_gen_match_display = 1\nquickstep_slot = 1\ncheat_exp = 1\ncheat_exp_percent = 225\ncheat_enemy_health = 1\ncheat_enemy_health_percent = 175\nbind_key_a = TOP_SECRET_BINDING\nmod_TOP_SECRET_PATH = 1\nframe_gen = SECRET_INVALID\nwindow = bad\n'
        self.ini.write_text(text); before = self.ini.read_bytes()
        result = self.record(); self.assertEqual(result['status'], 'recorded')
        raw = self.path(result).read_bytes(); row = json.loads(raw)
        self.assertEqual(self.ini.read_bytes(), before)
        self.assertEqual(row['binary_sha256'], 'a' * 64)
        self.assertEqual(row['source_manifest_sha256'], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(row['requested_settings']['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertIn('cheat_exp_percent = 225', row['requested_settings']['known_settings_ini'])
        self.assertIn('cheat_enemy_health = 1', row['requested_settings']['known_settings_ini'])
        self.assertIn('cheat_enemy_health_percent = 175', row['requested_settings']['known_settings_ini'])
        self.assertIn('fps_overlay_mode = detailed', row['requested_settings']['known_settings_ini'])
        self.assertEqual(row['requested_settings']['redacted_invalid_values'], 2)
        for secret in (b'TOP_SECRET', b'SECRET_INVALID', b'/private', b'/not-recorded', b'bind_key', b'mod_TOP'):
            self.assertNotIn(secret, raw)
        self.assertEqual(row['timing_overrides'], {'XCDE_FPS_INTERVAL': '1'})
        self.assertNotIn('private_path', row['frame_generation_request'])
        self.assertNotIn('counter_status', row['frame_generation_request'])
    def test_each_run_keeps_its_old_snapshot_when_ini_changes(self):
        self.ini.write_text('fps = 120\nframe_gen = 1\n'); one = self.record(); raw = self.path(one).read_bytes()
        self.ini.write_text('fps = unlimited\nframe_gen_smooth_motion = 1\n'); two = self.record()
        self.assertNotEqual(one['run_id'], two['run_id']); self.assertEqual(self.path(one).read_bytes(), raw)
        self.assertIn('fps = unlimited', json.loads(self.path(two).read_bytes())['requested_settings']['known_settings_ini'])
    def test_driver_metadata_fields_are_strict_and_do_not_claim_generation(self):
        self.launch['frame_generation'].update(cuda_task_metadata=True, observer_requested=True,
            cuda_task_metadata_protocol=1, counter_kind='downstream-submitted', counter_status='requested')
        result = self.record(); row = json.loads(self.path(result).read_bytes())['frame_generation_request']
        self.assertIs(row['cuda_task_metadata'], True); self.assertIs(row['observer_requested'], True)
        self.assertEqual(row['cuda_task_metadata_protocol'], 1); self.assertEqual(row['counter_kind'], 'downstream-submitted')
        self.launch['frame_generation'].update(cuda_task_metadata='true', observer_requested=1,
            cuda_task_metadata_protocol=2, counter_kind='/private/observer', counter_status='/private/status')
        result = self.record(); row = json.loads(self.path(result).read_bytes())['frame_generation_request']
        for key in ('cuda_task_metadata', 'observer_requested', 'cuda_task_metadata_protocol', 'counter_kind', 'counter_status'):
            self.assertNotIn(key, row)
    def test_retention_is_bounded_to_sixteen_owned_small_records(self):
        self.ini.write_text('fps = 120\n')
        rows = [self.record() for _ in range(20)]
        self.assertTrue(all(row['status'] == 'recorded' for row in rows))
        files = list((self.state / 'logs/game-runs').glob('run-*.json'))
        self.assertEqual(len(files), 16); self.assertFalse(self.path(rows[0]).exists()); self.assertTrue(self.path(rows[-1]).exists())
        self.assertLess(sum(p.stat().st_size for p in files), 16 * helper.MAX_RECORD)
    def test_foreign_entries_markers_and_symlinks_are_preserved(self):
        self.ini.write_text('fps = 120\n'); self.assertEqual(self.record()['status'], 'recorded')
        directory = self.state / 'logs/game-runs'; sentinel = directory / 'foreign.txt'; sentinel.write_text('preserve')
        self.assertEqual(self.record()['status'], 'unavailable'); self.assertEqual(sentinel.read_text(), 'preserve'); sentinel.unlink()
        outside = self.root / 'outside'; outside.write_text('preserve')
        link = directory / ('run-' + 'b' * 32 + '.json'); link.symlink_to(outside)
        self.assertEqual(self.record()['status'], 'unavailable'); self.assertTrue(link.is_symlink()); self.assertEqual(outside.read_text(), 'preserve')
    def test_edited_owned_record_is_preserved_instead_of_pruned(self):
        result = self.record(); path = self.path(result); row = json.loads(path.read_bytes())
        row['requested_settings']['known_settings_ini'] = 'fps = 144\n'
        path.write_text(json.dumps(row)); before = path.read_bytes()
        self.assertEqual(self.record()['status'], 'unavailable'); self.assertEqual(path.read_bytes(), before)
    def test_linked_fifo_oversized_and_invalid_ini_never_leak_or_hang(self):
        outside = self.root / 'private.ini'; outside.write_text('fps = 123\nSECRET_DATA\n'); self.ini.symlink_to(outside)
        result = self.record(); self.assertEqual(json.loads(self.path(result).read_bytes())['requested_settings']['status'], 'unavailable-or-untrusted'); self.ini.unlink()
        os.mkfifo(self.ini); result = self.record(); self.assertEqual(json.loads(self.path(result).read_bytes())['requested_settings']['status'], 'unavailable-or-untrusted'); self.ini.unlink()
        self.ini.write_bytes(b'x' * (helper.MAX_INI + 1)); result = self.record(); self.assertEqual(json.loads(self.path(result).read_bytes())['requested_settings']['status'], 'unavailable-or-untrusted')
        self.ini.write_bytes(b'\xff\xfe'); result = self.record(); self.assertEqual(json.loads(self.path(result).read_bytes())['requested_settings']['status'], 'invalid-encoding')
    def test_optional_write_failure_is_nonfatal_and_publishes_no_partial_record(self):
        self.ini.write_text('fps = 120\n'); self.assertEqual(self.record()['status'], 'recorded')
        directory = self.state / 'logs/game-runs'; before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        with mock.patch.object(helper.os, 'link', side_effect=OSError('authored no space')):
            self.assertEqual(self.record()['status'], 'unavailable')
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}, before)
        self.assertEqual(self.ini.read_text(), 'fps = 120\n')
    def test_busy_lock_and_untrusted_parent_do_not_block_or_follow(self):
        import fcntl
        self.assertEqual(self.record()['status'], 'recorded')
        lock = self.state / 'logs/game-runs/.lock'
        with lock.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.record()['status'], 'unavailable')
        outside = self.root / 'outside-state'; outside.mkdir(); alias = self.root / 'alias'; alias.symlink_to(outside, target_is_directory=True)
        result = helper.record_game_run({'state': str(alias)}, {})
        self.assertEqual(result['status'], 'unavailable'); self.assertEqual(list(outside.iterdir()), [])
    def test_missing_and_excessive_known_settings_have_explicit_status(self):
        result = self.record(); self.assertEqual(json.loads(self.path(result).read_bytes())['requested_settings']['status'], 'missing')
        self.ini.write_text('fps = 120\n' * (helper.MAX_LINES + 1))
        result = self.record(); row = json.loads(self.path(result).read_bytes())['requested_settings']
        self.assertEqual(row['status'], 'too-many-known-settings'); self.assertEqual(row['known_settings_ini'], '')
    def test_actual_launch_continues_on_diagnostic_write_failure_and_dry_run_does_not_record(self):
        class ExecObserved(BaseException): pass
        self.ini.write_text('fps = 120\n'); before = self.ini.read_bytes()
        launch = {'argv': ['/authored/no-game-exec'], 'input': str(self.root / 'input'),
                  'state': str(self.state), 'library_path': '/authored/libs', 'binary_sha256': 'a' * 64}
        captured = {}
        def execute(path, args, environment): captured.update(environment); raise ExecObserved()
        real_listdir = os.listdir
        def descriptors(path): return ['0', '1', '2'] if path == '/proc/self/fd' else real_listdir(path)
        with mock.patch.dict(os.environ, {'PATH': '/usr/bin:/bin', 'MONADO_RUN_ID': '/untrusted'}, clear=True), \
             mock.patch.object(sys, 'argv', ['run_linux.py', '--executable', '/authored/no-game-exec', '--state-root', str(self.state)]), \
             mock.patch.object(native, 'plan', return_value=dict(launch)), \
             mock.patch.object(native, 'validate_runtime', return_value={}), \
             mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'authored pass', '')), \
             mock.patch.object(native.install_lease, 'acquire_runtime', return_value=99), \
             mock.patch.object(native.os, 'listdir', side_effect=descriptors), \
             mock.patch.object(native.os, 'chdir'), mock.patch.object(native.os, 'umask'), \
             mock.patch.object(native.os, 'execve', side_effect=execute), \
             mock.patch.object(native.run_settings_log, '_publish', side_effect=OSError('authored no space')):
            with self.assertRaises(ExecObserved): native.main()
        self.assertRegex(captured['MONADO_RUN_ID'], r'^[0-9a-f]{32}$'); self.assertEqual(self.ini.read_bytes(), before)
        with mock.patch.object(sys, 'argv', ['run_linux.py', '--executable', '/authored/no-game-exec', '--state-root', str(self.state), '--dry-run']), \
             mock.patch.object(native, 'plan', return_value=dict(launch)), \
             mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'authored pass', '')), \
             mock.patch.object(native.run_settings_log, 'record_game_run') as recording:
            self.assertEqual(native.main(), 0); recording.assert_not_called()

@unittest.skipUnless(sys.platform == 'linux', 'native Linux effective diagnostics')
class NativeRunDiagnostics(unittest.TestCase):
    def test_actual_parser_and_bounded_runtime_events(self):
        compiler = os.environ.get('MONADO_TEST_CC') or shutil.which('clang')
        if not compiler: self.skipTest('native Clang required')
        with tempfile.TemporaryDirectory(prefix='monado-native-run-log-') as temporary:
            out = Path(temporary); binary = out / 'fixture'
            command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-DXCDE_LINUX_DLSS', '-DXCDE_LINUX_FRAMEGEN',
                       '-ffp-contract=off', '-fno-strict-aliasing', str(ROOT / 'tests/native/test_run_diagnostics.c'),
                       str(PORT / 'runtime/host/settings_ini.c'), str(PORT / 'runtime/hle/cheats_options.c'), '-pthread', '-lm', '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1': command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            environment = {k:v for k,v in os.environ.items() if not k.startswith(('XCDE_', 'LARECOMP_', 'MONADO_', 'NVPRESENT_'))}
            compiled = subprocess.run(command, cwd=out, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            outputs = {}
            for scenario in ('parsed', 'missing', 'ignored', 'external', 'bounded', 'sanitize'):
                result = subprocess.run([str(binary), str(out / 'xcde.ini'), scenario], cwd=out, env=environment, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr); self.assertIn('PASS', result.stdout); outputs[scenario] = result.stderr
            self.assertIn('id=0123456789abcdef0123456789abcdef', outputs['parsed'])
            self.assertIn('event=settings-loaded method=fsr-requested', outputs['parsed'])
            self.assertIn('fps_overlay_mode=3', outputs['parsed']); self.assertIn('configured_fps=120', outputs['parsed']); self.assertIn('policy_target_fps=90', outputs['parsed'])
            self.assertIn('nominal_fps=120 measured_fps=no', outputs['parsed']); self.assertIn('nominal_fps=90 measured_fps=no', outputs['parsed'])
            self.assertIn('qualified_fg_cap=0 fg_ready=0', outputs['parsed']); self.assertIn('qualified_fg_cap=90 fg_ready=1', outputs['parsed'])
            self.assertIn('cheat_enabled=0,0,1,0,0,0,0,0,1', outputs['parsed'])
            self.assertIn('cheat_percent=100,100,225,100,100,100,100,175', outputs['parsed'])
            self.assertIn('configured_fps=30', outputs['missing']); self.assertIn('hidden=1', outputs['ignored'])
            self.assertIn('method=nvidia-external-requested', outputs['external']); self.assertIn('app_present=mailbox', outputs['external'])
            self.assertEqual(outputs['bounded'].count('event=effective-target '), 32)
            self.assertEqual(outputs['bounded'].count('event=frame-policy '), 32)
            self.assertEqual(outputs['bounded'].count('event=applied-limiter '), 32)
            self.assertEqual(outputs['bounded'].count('event=pacing-limit '), 1); self.assertEqual(outputs['bounded'].count('event=renderer-limit '), 1)
            self.assertIn('id=direct', outputs['sanitize']); self.assertNotIn('SECRET_ID', outputs['sanitize'])
            self.assertNotIn('\nforged=', outputs['sanitize']); self.assertIn('GPU?forged=1??', outputs['sanitize'])

if __name__ == '__main__': unittest.main()
