"""Real authored installation/lease fixtures for deferred session retention.

The only executed child is a tiny Python sentinel, never a game, SDL or human
installation. Native runtime/input checks are explicit authored boundaries here;
their independent artifact checks remain in the production startup path.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

if sys.platform != 'linux':
    raise unittest.SkipTest('Linux installation leases and descriptor lifecycle')

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixtures = load('_monado_retention_lifecycle_fixtures', ROOT / 'tests/test_update_linux.py')
u = fixtures.u
with mock.patch.object(sys, 'path', [str(ROOT / 'Monado_Linux/scripts'), *sys.path]):
    launcher = load('_monado_retention_lifecycle_launcher', ROOT / 'Monado_Linux/scripts/launcher_linux.py')


class RetentionLifecycle(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Transactions('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.workspace, self.game_port, self.game = self.fixture.active_payload()
        self.owner, self.state = self.fixture.owner, self.fixture.state
        self.directory = self.owner / 'Monado_Linux/updates'
        self.obsolete = self.directory / 'update-authored-obsolete'
        self.obsolete.mkdir()
        (self.obsolete / 'transaction.json').write_text(json.dumps({
            'schema': 1, 'status': 'staging', 'version': '0.1.1', 'previous': None}))
        (self.obsolete / 'build.log').write_text('AUTHORED OLD BUILD LOG\n')

    def test_startup_sync_still_repairs_marker_without_walking_obsolete_trees(self):
        # A valid previous marker can need repair even when optional GC waits.
        marker = self.owner / 'update-version.json'
        marker.write_bytes(self.fixture.files['update-version.json'])
        fd = self.fixture.lease()
        try:
            with mock.patch.object(u, 'cleanup_current', side_effect=AssertionError('GC before UI')):
                self.assertTrue(u.sync_installation_version(self.workspace, self.state, fd, cleanup=False))
        finally:
            os.close(fd)
        self.assertEqual(u.version(self.owner), '0.1.4')
        self.assertTrue(self.obsolete.exists())
        self.fixture.assertProtected()

    def test_source_tampering_and_links_still_refuse_deferred_startup(self):
        path = self.workspace / 'README.md'
        before = path.read_bytes()
        for replacement in ('changed', 'link'):
            with self.subTest(replacement=replacement):
                if replacement == 'changed':
                    path.write_bytes(b'X' * len(before))
                else:
                    path.unlink()
                    path.symlink_to(self.owner / 'README.md')
                fd = self.fixture.lease()
                try:
                    with self.assertRaises(ValueError):
                        u.sync_installation_version(self.workspace, self.state, fd, cleanup=False)
                finally:
                    os.close(fd)
                if path.is_symlink():
                    path.unlink()
                path.write_bytes(before)
                self.assertTrue(self.obsolete.exists())
                self.fixture.assertProtected()

    def test_completion_rechecks_selection_and_sources_before_deletion(self):
        selected = self.directory / 'active.json'
        record = selected.read_bytes()
        selected.write_text('{}')
        with self.assertRaises(ValueError):
            u.finish_installation_maintenance(self.workspace)
        self.assertTrue(self.obsolete.exists())
        selected.write_bytes(record)
        path = self.workspace / 'README.md'
        before = path.read_bytes()
        path.write_bytes(b'changed after GUI handoff\n')
        with self.assertRaises(ValueError):
            u.finish_installation_maintenance(self.workspace)
        self.assertTrue(self.obsolete.exists())
        path.write_bytes(before)
        report = u.finish_installation_maintenance(self.workspace)
        self.assertEqual(report['status'], 'complete')
        self.assertFalse(self.obsolete.exists())
        self.fixture.assertProtected()

    def test_concurrent_runtime_defers_before_bridge_audits_and_tree_walks(self):
        lease = u._support_module('install_lease')
        fd = lease.acquire_runtime(self.owner / 'Monado_Linux')
        try:
            with mock.patch.object(u, '_retire_rollback', side_effect=AssertionError('must defer first')):
                report = u.finish_installation_maintenance(self.workspace)
            self.assertEqual(report['status'], 'pending')
            self.assertTrue(self.obsolete.exists())
        finally:
            os.close(fd)
        self.assertEqual(u.finish_installation_maintenance(self.workspace)['status'], 'complete')
        self.assertFalse(self.obsolete.exists())
        self.fixture.assertProtected()

    def test_real_supervisor_hands_off_and_closes_session_descriptors_before_gc(self):
        # Execute the production supervisor with real authored filesystem leases
        # and a harmless child which observes whether startup already ran GC.
        child = self.state / 'authored-child.py'
        observed = self.state / 'authored-observed.json'
        child.write_text('import json,sys,time\nfrom pathlib import Path\n'
            'old=Path(sys.argv[1]);out=Path(sys.argv[2])\n'
            'out.write_text(json.dumps(dict(obsolete_exists=old.is_dir(), at=time.monotonic())))\n')
        before = {p: p.read_bytes() for p in (self.state / 'save').iterdir()}
        argv = [sys.executable, '-I', '-B', str(child), str(self.obsolete), str(observed),
                '--game-executable', str(self.game)]
        plan = dict(state=str(self.state), input='AUTHORED INPUT BOUNDARY', argv=argv,
                    game_sha256='0' * 64, library_path='/usr/lib', runtime_environment={
                        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        # Use the complete installed helper from its actual candidate source.
        # Game/GUI linking and input-version validation are separate fixtures.
        stderr = io.StringIO()
        with mock.patch.object(launcher, 'ROOT', self.workspace / 'Monado_Linux'), \
                mock.patch.object(launcher, 'recover_input', return_value=True), \
                mock.patch.object(launcher, 'prepare', return_value=plan), \
                mock.patch.object(launcher, 'check_input', return_value={'authored': True}), \
                mock.patch.object(launcher.run_linux, 'plan', return_value=plan), \
                mock.patch.object(launcher.run_linux, 'validate_runtime', return_value=None) as validate, \
                contextlib.redirect_stderr(stderr):
            result = launcher.main(['--no-updates', '--state-root', str(self.state),
                '--game-executable', str(self.game), '--launcher-executable', str(child)])
        self.assertEqual(result, 0)
        self.assertEqual(validate.call_count, 4, 'both artifacts remain checked before and after admission')
        self.assertTrue(json.loads(observed.read_text())['obsolete_exists'], 'GC delayed the child handoff')
        self.assertFalse(self.obsolete.exists(), 'natural session completion must still retry cleanup')
        self.assertLess(stderr.getvalue().index('native-gui-handoff'), stderr.getvalue().index('session-finished-retention'))
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        # Both locks are available after the production supervisor completed.
        profile = self.fixture.lease()
        os.close(profile)
        lease = u._support_module('install_lease')
        runtime = lease.acquire_maintenance(self.owner / 'Monado_Linux')
        os.close(runtime)


if __name__ == '__main__':
    unittest.main()
