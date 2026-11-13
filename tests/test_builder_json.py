"""Native setup IPC contracts; no SDL, game data, network or game build."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuilderJsonContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get('MONADO_TEST_CXX')
        compiler = configured or shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            raise unittest.SkipTest('clang++, g++ or MONADO_TEST_CXX is required for the native JSON fixture')
        if configured and not (shutil.which(configured) or Path(configured).is_file()):
            raise RuntimeError('MONADO_TEST_CXX does not name an available C++ compiler')
        cls.directory = tempfile.TemporaryDirectory(prefix='monado-builder-json-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / ('builder-json.exe' if os.name == 'nt' else 'builder-json')
        command = [compiler, '-std=c++17', '-O1', '-UNDEBUG',
                   '-I' + str(ROOT / 'Monado_Linux/tools/builder'),
                   str(ROOT / 'tests/native/test_builder_json.cpp'), '-o', str(cls.binary)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Native JSON fixture did not compile:\n' + result.stdout[-4000:] + result.stderr[-4000:])

    def contract(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])

    def test_typed_status_getters_and_missing_fields(self):
        self.contract('getters')

    def test_quoted_unicode_and_control_character_paths_round_trip(self):
        self.contract('paths')

    def test_unicode_escapes_surrogate_pairs_and_invalid_sequences(self):
        self.contract('unicode')

    def test_duplicate_nested_nonfinite_and_malformed_documents_rejected(self):
        self.contract('invalid')

    def test_partial_status_writes_never_parse_as_complete_messages(self):
        self.contract('truncated')

    def test_message_and_field_count_bounds(self):
        self.contract('bounds')


if __name__ == '__main__':
    unittest.main()
