"""Authored failed-process fixtures; no game, installer or network execution."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_monado_diagnostic_builder', ROOT / 'Monado_Linux/scripts/build_linux.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeBuildDiagnostics(unittest.TestCase):
    def test_actual_failed_process_reports_loader_reason_and_preserves_full_logs(self):
        with tempfile.TemporaryDirectory(prefix='monado diagnostic space ') as directory:
            output = Path(directory)
            (output / 'logs').mkdir()
            builder = native.Builder.__new__(native.Builder)
            builder.output = output
            builder.lock = threading.Lock()
            builder.failed = threading.Event()
            builder.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
            builder.receipt = {'commands': []}
            reason = 'authored-lib-example.so.7: cannot open shared object file'
            with contextlib.redirect_stdout(io.StringIO()) as console:
                record, _ = builder.run('elf-loader-list', [sys.executable, '-I', '-B', '-c',
                    'import sys; sys.stderr.write(' + repr(reason + '\n') + '); raise SystemExit(127)'])
            self.assertEqual(record['exit'], 127)
            self.assertIn(reason, console.getvalue())
            self.assertIn(str(output / 'logs/elf-loader-list.stderr.log'), console.getvalue())
            self.assertEqual(Path(record['stderr']).read_text(), reason + '\n')
            self.assertTrue(builder.failed.is_set())
            saved = json.loads((output / 'receipt.json').read_text())
            self.assertEqual(saved['commands'][0]['exit'], 127)

    def test_large_diagnostic_is_bounded_and_complete_file_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'error.log'
            raw = b'x' * 50000 + b'\nGLIBC_AUTHORED_VERSION not found\n'
            path.write_bytes(raw)
            result = native.command_failure({'name': 'elf-loader-list', 'exit': 1, 'stderr': str(path)}, limit=1024)
            self.assertIn('GLIBC_AUTHORED_VERSION not found', result)
            self.assertIn('last 1024 bytes', result)
            self.assertLess(len(result), 1500)
            self.assertEqual(path.read_bytes(), raw)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink and special-file safety')
    def test_diagnostic_does_not_follow_links_or_block_on_fifo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / 'private'; private.write_text('AUTHORED SECRET MUST NOT BE PRINTED')
            link = root / 'link'; link.symlink_to(private)
            fifo = root / 'fifo'; os.mkfifo(fifo)
            for path in (link, fifo):
                result = native.command_failure({'name': 'authored', 'exit': 1, 'stderr': str(path)})
                self.assertNotIn('AUTHORED SECRET', result)

    def test_spawn_error_and_empty_stderr_stdout_fallback_are_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'stdout'; out.write_text('authored tool explains failure on stdout\n')
            err = root / 'stderr'; err.write_text('')
            result = native.command_failure({'name': 'tool', 'exit': 127,
                'spawn_error': 'authored missing executable', 'stderr': str(err), 'stdout': str(out)})
            self.assertIn('authored missing executable', result)
            self.assertIn('explains failure', result)


if __name__ == '__main__':
    unittest.main()
