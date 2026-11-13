"""Standalone build mode: authored fixtures, no compiler or game execution."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gui_mode_fixtures', ROOT / 'tests/test_managed_linux_build.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
build = fixtures.build


class GuiBuildMode(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ManagedBuild('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.workspace

    def test_plan_keeps_native_launcher_checks_without_image_tools(self):
        paths, commands = build.layout(self.root, 2, identity='authored-gui', dlss=False, no_appimage=True)
        names = [name for name, _ in commands]
        self.assertIn('generate-game', names)
        self.assertIn('build-game', names)
        self.assertIn('build-launcher', names)
        self.assertIn('check-launcher', names)
        self.assertNotIn('package-appimage', names)
        self.assertNotIn('published', paths)
        self.assertNotIn('image', paths)
        self.assertEqual(paths['state'], self.fixture.state)

    def test_mutually_exclusive_modes_cannot_create_an_ambiguous_receipt(self):
        with self.assertRaisesRegex(build.BuildError, 'mutually exclusive'):
            build.layout(self.root, 2, game_only=True, no_appimage=True)

    def test_success_registers_only_checked_selection_and_preserves_profile(self):
        fixture = self.fixture
        before = fixtures.files(fixture.state), fixtures.files(fixture.input)
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(build.run_linux, 'validate_runtime', return_value={'status': 'passed'}):
            result = build.build(self.root, 2, runner=fixture.game_only_runner,
                locker=lambda port: contextlib.nullcontext(), identity='authored-gui', dlss=False, no_appimage=True)
        marker = json.loads((fixture.port / '.deps/metadata/gui-build.json').read_text())
        self.assertEqual(marker['artifact_kind'], 'local-gui-build')
        self.assertEqual(marker['game']['sha256'], fixtures.sha(Path(result['paths']['game'])))
        self.assertEqual(marker['launcher'], result['paths']['launcher'])
        self.assertEqual(marker['state'], str(fixture.state))
        self.assertEqual(marker['build_receipt_sha256'], fixtures.sha(Path(result['paths']['run']) / 'receipt.json'))
        self.assertEqual(before, (fixtures.files(fixture.state), fixtures.files(fixture.input)))
        self.assertFalse((self.root / build.IMAGE).exists())
        self.assertFalse(any('build_launcher_appimage.py' in str(command) for command in fixture.commands))

    def test_runtime_failure_never_publishes_a_gui_selection(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(build.run_linux, 'validate_runtime', side_effect=ValueError('authored rejection')):
            with self.assertRaisesRegex(ValueError, 'authored rejection'):
                build.build(self.root, 2, runner=self.fixture.game_only_runner,
                    locker=lambda port: contextlib.nullcontext(), identity='rejected-gui', dlss=False, no_appimage=True)
        self.assertFalse((self.fixture.port / '.deps/metadata/gui-build.json').exists())
        receipt = json.loads((self.fixture.port / 'runs/local-build/rejected-gui/receipt.json').read_text())
        self.assertEqual(receipt['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
