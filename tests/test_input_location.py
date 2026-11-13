"""Moved-input recovery using only authored data/ELF headers; no game execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_input_location_test', ROOT / 'Monado_Linux/scripts/input_location.py')
location = importlib.util.module_from_spec(spec)
spec.loader.exec_module(location)
if sys.platform == 'linux':
    import fcntl


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    """Synthetic managed GUI and direct game payload for adjacent flow tests."""
    def __init__(self, base):
        self.owner = Path(base).resolve() / 'Installation with spaces'
        self.original = self.owner / 'Monado_Linux'
        self.port = self.original / 'updates/gui-2/workspace/Monado_Linux'
        self.payload = self.original / 'updates/game-1/workspace/Monado_Linux'
        for path in (self.original, self.port, self.payload):
            path.mkdir(parents=True, exist_ok=True)
        for path in (self.port, self.payload):
            (path.parent / 'installation.json').write_text(json.dumps({
                'schema': 1, 'owner': str(self.owner), 'workspace': str(path.parent),
                'game_port': str(self.payload)}))
        self.input = Path(base).resolve() / 'My original game files'
        (self.input / 'exefs').mkdir(parents=True)
        (self.input / 'romfs').mkdir()
        (self.input / 'exefs/main').write_bytes(b'authored test executable input, not a game')
        (self.input / 'exefs/sdk').write_bytes(b'authored synthetic SDK input')
        (self.input / 'romfs/layout.txt').write_text('synthetic version 2.0.0')
        self.links = [path / 'game_files' for path in (self.owner, self.port.parent, self.payload.parent)]
        for link in self.links:
            link.symlink_to(self.input)
        self.game = self.payload / 'build/authored/xcde-linux'
        self.game.parent.mkdir(parents=True)
        header = bytearray(64)
        header[:6] = b'\x7fELF\x02\x01'
        header[18:20] = (62).to_bytes(2, 'little')
        self.game.write_bytes(header)
        self.game.chmod(0o700)
        self.receipt = self.game.parent / 'receipt.json'
        self.value = {'status': 'passed', 'generated': {'authored-fixture': True},
                      'executable': {'path': str(self.game), 'sha256': digest(self.game)},
                      'input': {'path': str(self.input),
                                'exefs': {item.name: digest(item) for item in (self.input / 'exefs').iterdir()}}}
        self.write_receipt()
        self.profile = self.original / 'play/launcher'
        self.profile.mkdir(parents=True)
        (self.profile / '.session.lock').touch(mode=0o600)
        (self.profile / 'xcde.ini').write_text('[authored fixture]\nsetting = preserved\n')
        (self.profile / 'save.dat').write_bytes(b'authored fake save untouched')
        self.new = Path(base).resolve() / 'Relocated game files'
        self.input.rename(self.new)
        self.metadata = self.original / '.deps/metadata'

    def write_receipt(self):
        self.receipt.write_text(json.dumps(self.value))

    def checker(self, path):
        if (path / 'romfs/layout.txt').read_text() != 'synthetic version 2.0.0':
            raise ValueError('unsupported fixture version')
        return True

    def relocate(self, **kwargs):
        return location.relocate(self.port, self.game, self.new, checker=self.checker, **kwargs)


@unittest.skipUnless(sys.platform == 'linux', 'native Linux locks and renameat2')
class InputLocation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='monado-input-location-')
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(self.temporary.name)

    def assert_unmoved(self):
        for link in self.fixture.links:
            self.assertEqual(os.readlink(link), str(self.fixture.input))

    def test_inspect_is_read_only_and_reports_missing(self):
        f = self.fixture
        result = location.inspect(f.port, f.game)
        self.assertTrue(result['missing'])
        self.assertEqual(result['owner'], str(f.owner))
        self.assertEqual(result['previous'], str(f.input))
        self.assertFalse(f.metadata.exists())
        self.assert_unmoved()

    def test_reconnects_owner_gui_payload_preserving_native_and_profile_bytes(self):
        f = self.fixture
        protected = [f.game, f.receipt, f.profile / 'save.dat', f.profile / 'xcde.ini']
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected}
        result = f.relocate()
        self.assertEqual(result, {'input': str(f.new), 'owner': str(f.owner), 'rebuilt': False})
        for link in f.links:
            self.assertEqual(link.resolve(strict=True), f.new)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in protected})
        self.assertEqual(json.loads(f.receipt.read_text())['input']['path'], str(f.input))
        status = location.inspect(f.port, f.game)
        self.assertFalse(status['missing'])
        self.assertEqual(status['previous'], str(f.new))
        self.assertFalse((f.metadata / location.ACTIVE).exists())
        self.assertFalse(list(f.owner.rglob('.input-relocation-*')))

    def test_second_move_has_owned_completed_provenance(self):
        f = self.fixture
        f.relocate()
        third = f.new.with_name('Third input location')
        f.new.rename(third)
        result = location.relocate(f.port, f.game, third, checker=f.checker)
        self.assertEqual(result['input'], str(third))
        for link in f.links:
            self.assertEqual(link.resolve(strict=True), third)
        self.assertEqual(json.loads(f.receipt.read_text())['input']['path'], str(f.input))

    def test_ordinary_owner_input_selected_as_target_is_preserved(self):
        f = self.fixture
        f.links[0].unlink()
        f.new.rename(f.links[0])
        info = f.links[0].stat()
        result = location.relocate(f.port, f.game, f.links[0], checker=f.checker)
        self.assertEqual(result['input'], str(f.links[0]))
        self.assertFalse(f.links[0].is_symlink())
        self.assertEqual(info.st_ino, f.links[0].stat().st_ino)
        self.assertTrue(all(link.resolve() == f.links[0] for link in f.links[1:]))

    def test_missing_known_entries_can_be_added(self):
        f = self.fixture
        f.links[1].unlink()
        f.relocate()
        self.assertEqual(f.links[1].resolve(strict=True), f.new)

    def test_read_only_hardlinked_exefs_is_supported(self):
        f = self.fixture
        source = f.new / 'exefs/main'
        os.link(source, f.new / 'same-authored-main-outside-exefs')
        self.assertEqual(source.stat().st_nlink, 2)
        f.relocate()
        self.assertEqual(source.stat().st_nlink, 2)

    def test_large_native_receipt_retains_existing_64_mib_limit(self):
        f = self.fixture
        f.value['authored-large-receipt-fixture'] = 'x' * (4 * 1024 * 1024)
        f.write_receipt()
        self.assertTrue(location.inspect(f.port, f.game)['missing'])
        f.relocate()

    def test_relative_and_control_character_replacements_are_rejected(self):
        f = self.fixture
        for path in ('relative/path', '/tmp/control\x7fpath'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                location.relocate(f.port, f.game, path, checker=f.checker)
        self.assert_unmoved()

    def test_input_change_after_publication_rolls_back(self):
        f = self.fixture
        def change(name):
            if name == 'after-link-0':
                (f.new / 'exefs/main').write_bytes(b'authored racing input edit')
        with self.assertRaisesRegex(ValueError, 'game input changed'):
            f.relocate(failpoint=change)
        self.assert_unmoved()

    def test_input_root_replacement_during_checker_is_rejected(self):
        f = self.fixture
        def checker(path):
            moved = path.with_name('root moved during fixture check')
            path.rename(moved)
            (path / 'exefs').mkdir(parents=True)
            (path / 'romfs').mkdir()
            for source in (moved / 'exefs').iterdir():
                (path / 'exefs' / source.name).write_bytes(source.read_bytes())
            return True
        with self.assertRaisesRegex(ValueError, 'directories changed'):
            location.relocate(f.port, f.game, f.new, checker=checker)
        self.assert_unmoved()


    def test_checker_wrong_version_and_false_are_rejected(self):
        f = self.fixture
        (f.new / 'romfs/layout.txt').write_text('wrong version')
        with self.assertRaisesRegex(ValueError, 'unsupported fixture'):
            f.relocate()
        with self.assertRaisesRegex(ValueError, 'input checker'):
            location.relocate(f.port, f.game, f.new, checker=lambda path: False)
        self.assert_unmoved()

    def test_exact_exefs_inventory_rejects_changed_extra_missing_and_links(self):
        f = self.fixture
        for kind in ('changed', 'extra', 'missing', 'link'):
            with self.subTest(kind=kind):
                main = f.new / 'exefs/main'
                original = main.read_bytes()
                extra = f.new / 'exefs/extra'
                if kind == 'changed':
                    main.write_bytes(b'wrong')
                elif kind == 'extra':
                    extra.write_bytes(b'extra authored fixture')
                elif kind == 'missing':
                    main.unlink()
                else:
                    main.unlink()
                    main.symlink_to(f.new / 'exefs/sdk')
                with self.assertRaises(ValueError):
                    f.relocate()
                self.assert_unmoved()
                if extra.exists():
                    extra.unlink()
                if main.exists() or main.is_symlink():
                    main.unlink()
                main.write_bytes(original)

    def test_bad_native_receipt_hash_header_kind_and_executable_are_rejected(self):
        f = self.fixture
        original = f.game.read_bytes()
        f.game.write_bytes(b'bad ELF')
        with self.assertRaisesRegex(ValueError, 'differs'):
            f.relocate()
        f.value['executable']['sha256'] = digest(f.game)
        f.write_receipt()
        with self.assertRaisesRegex(ValueError, 'ELF'):
            f.relocate()
        f.game.write_bytes(original)
        f.value['executable']['sha256'] = digest(f.game)
        f.value['artifact_kind'] = 'linux-launcher'
        f.write_receipt()
        with self.assertRaisesRegex(ValueError, 'game receipt'):
            f.relocate()
        del f.value['artifact_kind']
        f.write_receipt()
        f.game.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'executable Linux'):
            f.relocate()
        self.assert_unmoved()

    def test_existing_ordinary_input_paths_and_unknown_links_are_preserved(self):
        f = self.fixture
        f.links[1].unlink()
        f.links[1].mkdir()
        sentinel = f.links[1] / 'unrelated.txt'
        sentinel.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'ordinary file/directory'):
            f.relocate()
        self.assertEqual(sentinel.read_text(), 'preserve')
        sentinel.unlink()
        f.links[1].rmdir()
        f.links[1].symlink_to('/somewhere/not-authorized')
        with self.assertRaisesRegex(ValueError, 'unknown location'):
            f.relocate()
        self.assertEqual(os.readlink(f.links[1]), '/somewhere/not-authorized')

    def test_incomplete_existing_root_is_an_error_not_missing_repair(self):
        f = self.fixture
        f.links[0].unlink()
        f.links[0].mkdir()
        with self.assertRaisesRegex(ValueError, 'incomplete or unsafe'):
            location.inspect(f.port, f.game)
        self.assertTrue(f.links[0].is_dir())

    def test_runtime_update_and_profile_locks_refuse_busy_without_input_writes(self):
        f = self.fixture
        runtime = location.lease.acquire_runtime(f.port)
        try:
            with self.assertRaises(BlockingIOError):
                f.relocate()
        finally:
            os.close(runtime)
        for path in (f.original / 'updates/install.lock', f.profile / '.session.lock'):
            with self.subTest(path=str(path)):
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(BlockingIOError):
                        f.relocate()
                finally:
                    os.close(descriptor)
        self.assert_unmoved()

    def test_cancel_before_and_during_transaction_restores_all_links(self):
        f = self.fixture
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            f.relocate(cancel=cancelled)
        cancelled.clear()
        def stop(name):
            if name == 'after-link-0':
                cancelled.set()
        with self.assertRaises(InterruptedError):
            f.relocate(cancel=cancelled, failpoint=stop)
        self.assert_unmoved()
        self.assertFalse((f.metadata / location.ACTIVE).exists())

    def test_failpoints_roll_back_each_partial_publication(self):
        f = self.fixture
        for failure in ('journal-ready', 'after-link-0', 'after-link-1', 'before-commit'):
            with self.subTest(failure=failure):
                def fail(name):
                    if name == failure:
                        raise RuntimeError('authored interruption')
                with self.assertRaisesRegex(RuntimeError, 'authored interruption'):
                    f.relocate(failpoint=fail)
                self.assert_unmoved()
                self.assertFalse((f.metadata / location.ACTIVE).exists())

    def test_hard_interruption_can_recover_then_relocate(self):
        f = self.fixture
        class PowerLoss(BaseException):
            pass
        def fail(name):
            if name == 'after-link-0':
                raise PowerLoss()
        with self.assertRaises(PowerLoss):
            f.relocate(failpoint=fail)
        self.assertTrue((f.metadata / location.ACTIVE).exists())
        self.assertTrue(location.inspect(f.port, f.game)['recovery_pending'])
        f.relocate()
        self.assertTrue(all(link.resolve(strict=True) == f.new for link in f.links))
        self.assertFalse((f.metadata / location.ACTIVE).exists())

    def test_missing_original_backup_is_a_conflict_not_a_guessed_repair(self):
        f = self.fixture
        class PowerLoss(BaseException):
            pass
        def fail(name):
            if name == 'after-link-0':
                raise PowerLoss()
        with self.assertRaises(PowerLoss):
            f.relocate(failpoint=fail)
        journal = json.loads((f.metadata / location.ACTIVE).read_text())
        entry = journal['entries'][0]
        (Path(entry['workspace']) / entry['stage']).unlink()
        with self.assertRaisesRegex(ValueError, 'old input link is unavailable'):
            f.relocate()
        self.assertTrue((f.metadata / location.ACTIVE).exists())
        self.assertEqual(f.links[0].resolve(strict=True), f.new)


    def test_hard_interruption_after_commit_finishes_without_reverting(self):
        f = self.fixture
        class PowerLoss(BaseException):
            pass
        def fail(name):
            if name == 'committed':
                raise PowerLoss()
        with self.assertRaises(PowerLoss):
            f.relocate(failpoint=fail)
        f.relocate()
        self.assertTrue(all(link.resolve(strict=True) == f.new for link in f.links))

    def test_concurrent_unknown_link_is_preserved_and_journal_retained(self):
        f = self.fixture
        def race(name):
            if name == 'before-link-1':
                f.links[1].unlink()
                f.links[1].symlink_to('/foreign/path')
        with self.assertRaisesRegex(ValueError, 'recovery is pending'):
            f.relocate(failpoint=race)
        self.assertEqual(os.readlink(f.links[1]), '/foreign/path')
        self.assertTrue((f.metadata / location.ACTIVE).exists())
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            f.relocate()
        self.assertEqual(os.readlink(f.links[1]), '/foreign/path')

    def test_target_cannot_overlap_state_build_or_dependencies(self):
        f = self.fixture
        for path in (f.original / 'play/input', f.port / '.deps/input', f.payload / 'build/input'):
            with self.subTest(path=str(path)):
                (path / 'exefs').mkdir(parents=True)
                (path / 'romfs').mkdir()
                with self.assertRaisesRegex(ValueError, 'separate from'):
                    location.relocate(f.port, f.game, path, checker=f.checker)
        self.assert_unmoved()

    def test_parent_symlink_and_unsafe_metadata_are_refused(self):
        f = self.fixture
        f.metadata.parent.mkdir()
        f.metadata.symlink_to(f.profile, target_is_directory=True)
        with self.assertRaises(ValueError):
            f.relocate()
        self.assert_unmoved()
        self.assertFalse((f.profile / location.ACTIVE).exists())


if __name__ == '__main__':
    unittest.main()
