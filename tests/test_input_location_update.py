"""Relocated-input updater checks using nonexecuted authored payload fixtures."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('location_update_fixtures', ROOT / 'tests/test_update_linux.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
u = fixtures.u


@unittest.skipUnless(sys.platform == 'linux', 'Linux installation/updater fixture')
class RelocatedUpdate(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Transactions('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_later_gui_update_rebuilds_relocated_payload_without_rewriting_receipt(self):
        f = self.fixture
        first = f.session()
        p = f.prepare(first)
        first.activate(p)
        workspace = f.owner / p['record']['workspace']
        port = Path(u.json_read(workspace / 'installation.json')['game_port'])
        game = Path(u.json_read(port / '.deps/metadata/game-payload.json')['game']['path'])
        receipt_path = game.parent / 'receipt.json'
        original_receipt = receipt_path.read_bytes()
        moved = f.base / 'relocated authored input'
        (f.owner / 'game_files').rename(moved)
        (f.owner / 'game_files').symlink_to(moved, target_is_directory=True)
        # Mimic core recovery of known direct payload + GUI links only.
        for link in (workspace / 'game_files', port.parent / 'game_files'):
            link.unlink()
            link.symlink_to(moved, target_is_directory=True)
        f.new['update-version.json'] = b'{"schema":1,"protocol":1,"version":"0.1.5"}'
        f.new['Monado_Linux/tools/launcher/launcher.cpp'] = b'// next authored GUI\n'
        fixtures.manifest(f.candidate, f.new)
        f.commands.clear()
        second = f.session(workspace=workspace, game=game,
            gui=workspace / 'Monado_Linux/build/new-gui/monado-launcher',
            discover=lambda _:dict(version='0.1.5', tag='v0.1.5'))
        result = f.prepare(second)
        self.assertTrue(result['rebuild'])
        self.assertEqual(len(f.commands), 2)
        self.assertIn('--game-only', f.commands[0])
        self.assertIn('--reuse-game', f.commands[1])
        self.assertEqual(receipt_path.read_bytes(), original_receipt)
        f.assertProtected()

    def test_missing_input_stops_before_download_or_build(self):
        f = self.fixture
        (f.owner / 'game_files').rename(f.base / 'temporarily absent authored input')
        session = f.session()
        with self.assertRaisesRegex(ValueError, 'Locate game files'):
            f.prepare(session)
        self.assertEqual(f.commands, [])
        self.assertFalse((f.port / 'updates').exists())

    def test_input_identity_metadata_is_strict_but_legacy_unchanged(self):
        current = Path('/authored/current input')
        self.assertFalse(u.input_path_changed({}, current))
        self.assertFalse(u.input_path_changed({'input':{'path':str(current)}}, current))
        self.assertTrue(u.input_path_changed({'input':{'path':'/authored/old input'}}, current))
        for field in ({}, {'path':'relative'}, {'path':42}, []):
            with self.subTest(field=field), self.assertRaises(ValueError):
                u.input_path_changed({'input':field}, current)


if __name__ == '__main__':
    unittest.main()
