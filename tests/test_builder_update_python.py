"""Persistent standalone Python survives new update workspaces; no real builds."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('builder_update_python', ROOT / 'tools/update_linux.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class PersistentBuildPython(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='monado-private-python-fixture-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.prefix = self.root / 'private python'
        self.python = self.prefix / 'bin/python3.14'
        self.python.parent.mkdir(parents=True)
        self.python.write_text('authored never-executed interpreter fixture')
        self.python.chmod(0o700)
        self.marker = self.prefix / 'monado-private-python.json'
        self.value = dict(schema=1, project='Monado II', python=[3, 14], runtime_kind='standalone-builder')
        self.game = self.root / 'game/xcde-linux'
        self.game.parent.mkdir()
        (self.game.parent / 'receipt.json').write_text(json.dumps({'dlss_enabled': False, 'framegen_enabled': False}))
        for name, value in (('base_prefix', str(self.prefix)), ('_base_executable', str(self.python)), ('version_info', (3, 14, 4))):
            patch = mock.patch.object(update.sys, name, value)
            patch.start(); self.addCleanup(patch.stop)

    def test_host_installation_keeps_legacy_build_entry(self):
        command = update.build_command(self.root / 'next workspace', self.game, True)
        self.assertEqual(command, [str(self.root / 'next workspace/Build_Monado_II.sh'), '--without-dlss'])

    def test_private_interpreter_is_used_without_a_candidate_venv(self):
        self.marker.write_text(json.dumps(self.value))
        workspace = self.root / 'next workspace'
        command = update.build_command(workspace, self.game, True)
        self.assertEqual(command[:4], [str(self.python), '-I', '-B', str(workspace / 'tools/build_linux_app.py')])
        self.assertIn('--without-dlss', command)
        self.assertFalse(workspace.exists())

    def test_bad_marker_or_interpreter_escape_fails_closed(self):
        for value in ({**self.value, 'python': [3, 13]}, {**self.value, 'project': 'other'}):
            self.marker.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'identity'):
                update.private_build_python()
        self.marker.write_text(json.dumps(self.value))
        outside = self.root / 'unrelated-python'
        outside.write_text('authored never-executed fixture'); outside.chmod(0o700)
        with mock.patch.object(update.sys, '_base_executable', str(outside)), self.assertRaisesRegex(ValueError, 'escaped'):
            update.private_build_python()

    def test_worker_rejects_forged_private_prefix(self):
        self.marker.write_text(json.dumps(self.value))
        workspace = self.root / 'candidate'
        valid = update.build_command(workspace, self.game, True)
        self.assertEqual(update.checked_worker_command(workspace, valid), valid)
        for command in ([], valid[1:], [*valid[:3], str(self.root / 'unrelated.py')], [valid[0], '-c', 'print(1)']):
            with self.subTest(command=command), self.assertRaises(ValueError):
                update.checked_worker_command(workspace, command)

    @unittest.skipUnless(os.name == 'posix', 'Linux worker lease fixture')
    def test_actual_worker_dispatch_accepts_private_prefix_and_keeps_lease_checks(self):
        self.marker.write_text(json.dumps(self.value))
        workspace = self.root / 'candidate'
        workspace.mkdir()
        (workspace / 'installation.json').write_text(json.dumps({'owner': str(self.root)}))
        lock = self.root / 'Monado_Linux/updates/install.lock'
        lock.parent.mkdir(parents=True)
        lock.touch()
        command = update.build_command(workspace, self.game, True)
        execute = mock.Mock(return_value=0)
        fixture = types.SimpleNamespace(execute=execute, reap_owned=lambda child: {})
        fd = os.open(lock, os.O_RDWR)
        try:
            with mock.patch.dict(update.sys.modules, {'build_linux_app': fixture}):
                self.assertEqual(update.build_worker(workspace, self.root / 'build.log', command, fd), 0)
            execute.assert_called_once_with(command, workspace, self.root / 'build.log')
        finally:
            os.close(fd)


if __name__ == '__main__':
    unittest.main()
