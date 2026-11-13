"""Disposable authored ownership/GC fixtures; no real game, save or installation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_test_retention', ROOT / 'tools/update_retention.py')
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def source(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    files = {'README.md': b'# Authored source fixture\n',
             'Monado_Linux/scripts/fixture.py': b'# Authored helper\n'}
    for name, value in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    manifest = {'files': {name: {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value)}
                          for name, value in files.items()}}
    write(workspace / 'publication-manifest.json', manifest)
    return manifest


def verified(workspace):
    value = gc._json(workspace / 'publication-manifest.json')
    for name, identity in value['files'].items():
        data = (workspace / name).read_bytes()
        if len(data) != identity['bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
            raise ValueError('Local source changes')
    return value


@unittest.skipUnless(sys.platform == 'linux', 'descriptor-relative Linux cleanup')
class Retention(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-current-retention-')
        self.addCleanup(temporary.cleanup)
        self.owner = Path(temporary.name).resolve() / 'owner'
        self.updates = self.owner / 'Monado_Linux/updates'
        self.updates.mkdir(parents=True)
        source(self.owner)
        self.current = self.version('update-current', '0.1.12')
        self.record = {'id': self.current.name, 'workspace': str((self.current/'workspace').relative_to(self.owner))}
        write(self.updates / 'active.json', self.record)
        self.sentinels = []
        for name in ('game_files/romfs/synthetic', 'Monado_Linux/play/launcher/save/slot.sav',
                     'Monado_Linux/play/launcher/.quickstep/slot.json',
                     'Monado_Linux/play/launcher/xcde.ini', 'Monado_Linux/play/launcher/shader-cache/cache',
                     'Monado_Linux/.venv/bin/python', 'Monado_Linux/.deps/tools/python',
                     'Monado_Linux/.deps/graphics/library'):
            path = self.owner / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'AUTHORED PROTECTED SENTINEL')
            self.sentinels.append(path)
        self.before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sentinels}

    def version(self, name, version='0.1.11', *, payload=False):
        path = self.updates / name
        path.mkdir()
        if payload:
            write(path / 'payload.json', {'schema': 1, 'kind': 'game-payload', 'owner': str(self.owner),
                                        'id': name, 'workspace': 'workspace'})
        else:
            write(path / 'transaction.json', {'schema': 1, 'status': 'staging', 'version': version, 'previous': None})
        source(path / 'workspace')
        (path / 'workspace/game_files').symlink_to(self.owner / 'game_files', target_is_directory=True)
        write(path / 'workspace/installation.json', {'schema': 1})
        build = path / 'workspace/Monado_Linux/build/local-fixture-game'
        build.mkdir(parents=True)
        (build / 'xcde-linux').write_bytes(b'NONEXECUTED AUTHORED BINARY PLACEHOLDER')
        log = path / 'workspace/Monado_Linux/runs/local-build/fixture/build.log'
        log.parent.mkdir(parents=True); log.write_text('Authored completed log\n')
        return path

    def clean(self, **kw):
        return gc.cleanup(self.owner, self.record, verify_workspace=verified, **kw)

    def assert_protected(self):
        self.assertEqual(self.before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sentinels})
        self.assertTrue(self.current.is_dir())
        verified(self.current / 'workspace')

    def test_gui_first_install_without_an_adjacent_image_reclaims_obsolete_outputs(self):
        identity = 'gui-20261113T120000Z-0123abcd'
        for relative in ('generated/' + identity, 'build/' + identity + '-game', 'build/' + identity + '-launcher'):
            path = self.owner / 'Monado_Linux' / relative
            path.mkdir(parents=True)
            (path / 'authored-synthetic-output.txt').write_text('authored obsolete build fixture')
        self.assertFalse((self.owner / 'Monado-II-x86_64.AppImage').exists())
        report = self.clean(include_bootstrap=True)
        self.assertEqual(report['status'], 'complete', report)
        self.assertFalse((self.owner / 'Monado_Linux/build').exists())
        self.assertFalse((self.owner / 'Monado_Linux/generated').exists())
        self.assert_protected()

    def test_unknown_gui_output_identity_stays_protected(self):
        path = self.owner / 'Monado_Linux/build/gui-my-unrelated-folder'
        path.mkdir(parents=True)
        sentinel = path / 'keep.txt'
        sentinel.write_text('preserve unknown folder')
        report = self.clean(include_bootstrap=True)
        self.assertEqual(report['status'], 'pending')
        self.assertEqual(sentinel.read_text(), 'preserve unknown folder')
        self.assert_protected()

    def test_legacy_accumulation_keeps_only_current_and_protected_data(self):
        old = [self.version('update-legacy-' + str(i), '0.1.'+str(i)) for i in range(5,12)]
        archive = self.current/'download'
        archive.mkdir(); (archive/'archive.tar').write_bytes(b'NONEXECUTED ARCHIVE')
        report = self.clean()
        self.assertEqual(report['status'], 'complete')
        self.assertFalse(any(path.exists() for path in old))
        self.assertFalse(archive.exists())
        self.assertEqual([p.name for p in self.updates.iterdir() if p.name.startswith('update-')], [self.current.name])
        self.assert_protected()

    def test_twenty_updates_keep_one_version_and_direct_payload(self):
        previous = self.current
        payload = self.version('payload-zero', payload=True)
        for i in range(20):
            selected = self.version('update-step-' + str(i), '0.2.' + str(i))
            if i % 3 == 0:
                payload = self.version('payload-step-' + str(i), payload=True)
            self.current = selected
            self.record = {'id': selected.name, 'workspace': str((selected/'workspace').relative_to(self.owner))}
            write(self.updates/'active.json', self.record)
            report = self.clean(retained_ports=[payload/'workspace/Monado_Linux'])
            self.assertEqual(report['status'], 'complete')
            self.assertFalse(previous.exists())
            self.assertEqual(len([p for p in self.updates.iterdir() if p.name.startswith('update-')]), 1)
            self.assertEqual(len([p for p in self.updates.iterdir() if p.name.startswith('payload-')]), 1)
            self.assert_protected()
            previous = selected

    def test_unknown_private_file_blocks_whole_victim(self):
        old = self.version('update-private')
        secret = old/'workspace/Monado_Linux/play/launcher/save/private'
        secret.parent.mkdir(parents=True); secret.write_bytes(b'KEEP USER CONTENT')
        report = self.clean()
        self.assertEqual(report['status'], 'pending')
        self.assertTrue(old.exists()); self.assertEqual(secret.read_bytes(), b'KEEP USER CONTENT')
        self.assert_protected()

    def test_modified_authored_source_blocks_whole_victim(self):
        old = self.version('update-modified')
        (old/'workspace/README.md').write_text('User edits\n')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue((old/'workspace/Monado_Linux/build/local-fixture-game/xcde-linux').exists())

    def test_unknown_transaction_companion_is_preserved(self):
        old = self.version('update-unowned')
        (old/'my-backup').write_bytes(b'KEEP')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue((old/'my-backup').exists())

    def test_directory_disguised_as_build_log_is_preserved(self):
        old = self.version('update-fake-log')
        (old/'build.log').mkdir(); (old/'build.log/secret').write_bytes(b'KEEP')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue((old/'build.log/secret').exists())

    def test_missing_ownership_marker_and_unmanaged_name_are_preserved(self):
        unowned = self.updates/'update-user'; unowned.mkdir()
        unrelated = self.updates/'my-backups'; unrelated.mkdir()
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(unowned.exists()); self.assertTrue(unrelated.exists())

    def test_symlink_root_refused_but_leaf_symlink_never_follows_target(self):
        old = self.version('update-link-leaf')
        deps = old/'workspace/Monado_Linux/.deps'; deps.mkdir()
        (deps/'external').symlink_to(self.sentinels[0])
        self.assertEqual(self.clean()['status'], 'complete')
        self.assertFalse(old.exists()); self.assert_protected()
        root_link = self.updates/'update-root-link'; root_link.symlink_to(self.owner/'game_files')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(root_link.is_symlink()); self.assert_protected()

    def test_hardlink_refused(self):
        old = self.version('update-hardlink')
        link = old/'workspace/Monado_Linux/build/linked'
        os.link(self.sentinels[0], link)
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(link.exists()); self.assert_protected()

    def test_held_legacy_workspace_is_pending(self):
        old = self.version('update-live')
        self.assertEqual(self.clean(live_roots=[old/'workspace'])['status'], 'pending')
        self.assertTrue(old.exists())
        self.assertEqual(self.clean()['status'], 'complete')

    def test_original_game_binding_does_not_pin_updates_subtree(self):
        old = self.version('update-independent')
        self.assertEqual(self.clean(retained_ports=[self.owner/'Monado_Linux'])['status'], 'complete')
        self.assertFalse(old.exists()); self.assert_protected()

    def test_interrupted_partial_deletion_resumes_without_source_files(self):
        old = self.version('update-interrupted')
        real = os.unlink
        calls = []
        def interrupt(path, *a, **kw):
            if path == 'fixture.py':
                calls.append(str(path)); real(path, *a, **kw)
                raise OSError('authored interruption after source unlink')
            return real(path, *a, **kw)
        with mock.patch.object(gc.os, 'unlink', side_effect=interrupt):
            self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(calls); self.assertTrue((self.updates/gc.JOURNAL).exists())
        self.assertFalse((old/'workspace/Monado_Linux/scripts/fixture.py').exists())
        self.assertEqual(self.clean()['status'], 'complete')
        self.assertFalse(old.exists()); self.assertFalse((self.updates/gc.JOURNAL).exists()); self.assert_protected()

    def test_file_added_after_journal_is_preserved(self):
        old = self.version('update-added')
        with mock.patch.object(gc, '_resume', side_effect=OSError('authored interruption before deletion')):
            self.assertEqual(self.clean()['status'], 'pending')
        added = old/'new-user-file'; added.write_bytes(b'KEEP AFTER INTERRUPTION')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(added.exists()); self.assertTrue((old/'workspace/README.md').exists())

    def test_changed_file_after_journal_is_preserved(self):
        old = self.version('update-changed')
        with mock.patch.object(gc, '_resume', side_effect=OSError('authored interruption')):
            self.assertEqual(self.clean()['status'], 'pending')
        data = old/'workspace/README.md'; data.write_text('Changed after authorization')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertEqual(data.read_text(), 'Changed after authorization')

    def test_pending_target_selected_current_is_preserved(self):
        old = self.version('update-now-active')
        with mock.patch.object(gc, '_resume', side_effect=OSError('authored interruption')):
            self.assertEqual(self.clean()['status'], 'pending')
        self.current = old
        self.record = {'id': old.name, 'workspace': str((old/'workspace').relative_to(self.owner))}
        write(self.updates/'active.json', self.record)
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(old.exists()); self.assert_protected()

    def test_selection_mismatch_refuses_before_deletion(self):
        old = self.version('update-selection-race')
        write(self.updates/'active.json', dict(self.record, id='update-other'))
        with self.assertRaisesRegex(ValueError, 'selection changed'):
            self.clean()
        self.assertTrue(old.exists()); self.assert_protected()

    def test_forged_payload_owner_is_preserved(self):
        old = self.version('payload-forged', payload=True)
        value=gc._json(old/'payload.json'); value['owner']='/unrelated'
        write(old/'payload.json',value)
        self.assertEqual(self.clean()['status'], 'pending'); self.assertTrue(old.exists())

    def test_boolean_payload_schema_is_refused(self):
        old = self.version('payload-boolean-schema', payload=True)
        marker = old / 'payload.json'
        value = gc._json(marker); value['schema'] = True
        write(marker, value)
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(old.exists()); self.assert_protected()

    def test_bootstrap_outputs_removed_but_python_and_dependencies_preserved(self):
        for kind, name in [('build','local-20261108T212336Z-5e218c17-game'),
                           ('generated','local-20261108T212336Z-5e218c17')]:
            path=self.owner/'Monado_Linux'/kind/name;path.mkdir(parents=True)
            (path/'authored-placeholder').write_bytes(b'DERIVED PLACEHOLDER')
        self.assertEqual(self.clean(include_bootstrap=True)['status'],'complete')
        self.assertFalse((self.owner/'Monado_Linux/build').exists())
        self.assertFalse((self.owner/'Monado_Linux/generated').exists())
        self.assert_protected()

    def test_bootstrap_original_game_and_unknown_files_are_preserved(self):
        output=self.owner/'Monado_Linux/build/local-20261108T212336Z-5e218c17-game'
        output.mkdir(parents=True);(output/'placeholder').write_bytes(b'KEEP')
        self.assertEqual(self.clean(include_bootstrap=True,retained_ports=[self.owner/'Monado_Linux'])['status'],'complete')
        self.assertTrue(output.exists())
        (output.parent/'my-saves').mkdir()
        self.assertEqual(self.clean(include_bootstrap=True)['status'],'pending')
        self.assertTrue(output.exists()); self.assert_protected()

    def test_unknown_current_download_file_is_preserved(self):
        download=self.current/'download';download.mkdir();(download/'my-file').write_bytes(b'KEEP')
        self.assertEqual(self.clean()['status'],'pending')
        self.assertTrue((download/'my-file').exists()); self.assert_protected()

    def partial_extraction(self, *, middle=False):
        # Reuse the existing source-release writer/HTTPS fixtures, not a mocked
        # ownership declaration. Incomplete source must remain non-executable.
        import test_update_release as release
        old = self.updates / ('update-partial-middle' if middle else 'update-partial-start')
        old.mkdir()
        write(old / 'transaction.json', {'schema': 1, 'status': 'staging', 'version': '0.1.4', 'previous': None})
        files = release.source_files()
        files['README.md'] = b'# Authored interrupted member\n' * 100000
        data = release.archive_bytes(files)
        destination = old / 'download'
        target = destination / 'source/README.md'
        def cancelled():
            if middle:
                return target.exists() and 0 < target.stat().st_size < len(files['README.md'])
            return (destination / 'source').is_dir()
        with mock.patch.object(release.update, 'CHUNK', 4096), self.assertRaises(release.update.UpdateCancelled):
            release.update.fetch_and_extract(release.offer(data), destination,
                                            opener=release.response(data), cancel=cancelled)
        return old, target, files

    def test_declared_cancelled_extraction_is_cleaned_before_first_file(self):
        old, _, _ = self.partial_extraction()
        self.assertEqual(self.clean()['status'], 'complete')
        self.assertFalse(old.exists()); self.assert_protected()

    def test_declared_mid_member_extraction_is_cleaned_as_exact_prefix(self):
        old, target, files = self.partial_extraction(middle=True)
        actual = target.read_bytes()
        self.assertGreater(len(actual), 0)
        self.assertLess(len(actual), len(files['README.md']))
        self.assertEqual(actual, files['README.md'][:len(actual)])
        self.assertEqual(self.clean()['status'], 'complete')
        self.assertFalse(old.exists()); self.assert_protected()

    def test_changed_partial_member_is_preserved(self):
        old, target, _ = self.partial_extraction(middle=True)
        changed = b'User changes' + target.read_bytes()
        target.write_bytes(changed)
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertEqual(target.read_bytes(), changed); self.assertTrue(old.exists())

    def test_unknown_file_in_declared_partial_source_is_preserved(self):
        old, _, _ = self.partial_extraction()
        unknown = old / 'download/source/my-save.sav'; unknown.write_bytes(b'KEEP USER DATA')
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertEqual(unknown.read_bytes(), b'KEEP USER DATA')

    def test_changed_declared_archive_is_preserved(self):
        old, _, _ = self.partial_extraction()
        archive = old / 'download/source.tar.gz'
        changed = archive.read_bytes() + b'User change'
        archive.write_bytes(changed)
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertEqual(archive.read_bytes(), changed)

    def test_legacy_incomplete_extraction_without_declaration_remains_pending(self):
        old, _, _ = self.partial_extraction()
        (old / 'download/extraction.json').unlink()
        self.assertEqual(self.clean()['status'], 'pending')
        self.assertTrue(old.exists()); self.assert_protected()

    def test_completed_current_download_with_declaration_is_removed(self):
        import test_update_release as release
        data = release.archive_bytes()
        extracted = release.update.fetch_and_extract(release.offer(data), self.current / 'download',
                                                     opener=release.response(data))
        preserved = self.owner / 'preserved-authored-source'
        extracted.rename(preserved)
        self.assertEqual(self.clean()['status'], 'complete')
        self.assertFalse((self.current / 'download').exists())
        self.assertTrue((preserved / 'README.md').exists()); self.assert_protected()

    def test_fresh_installation_cleans_failed_attempts_without_touching_original_build(self):
        (self.updates / 'active.json').unlink()
        old = self.version('update-fresh-failed')
        original = self.owner / 'Monado_Linux/build/local-20261108T212336Z-5e218c17-game/xcde-linux'
        original.parent.mkdir(parents=True); original.write_bytes(b'KEEP WORKING ORIGINAL')
        marker = self.owner / 'update-version.json'; marker.write_bytes(b'ORIGINAL VERSION SENTINEL')
        readme = (self.owner / 'README.md').read_bytes()
        report = gc.cleanup(self.owner, None, verify_workspace=verified, include_bootstrap=True)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['current_id'], 'bootstrap')
        self.assertFalse(old.exists()); self.assertFalse(self.current.exists())
        self.assertEqual(original.read_bytes(), b'KEEP WORKING ORIGINAL')
        self.assertEqual(marker.read_bytes(), b'ORIGINAL VERSION SENTINEL')
        self.assertEqual((self.owner / 'README.md').read_bytes(), readme)
        self.assertEqual(self.before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sentinels})
        self.assertFalse((self.updates / 'active.json').exists())

    def test_bootstrap_mode_refuses_existing_active_selection(self):
        old = self.version('update-bootstrap-refuse')
        with self.assertRaisesRegex(ValueError, 'active selection appeared'):
            gc.cleanup(self.owner, None, verify_workspace=verified)
        self.assertTrue(old.exists()); self.assert_protected()

    def test_bootstrap_mode_refuses_selection_appearing_during_source_check(self):
        (self.updates / 'active.json').unlink()
        old = self.version('update-bootstrap-race')
        def checked(workspace):
            result = verified(workspace)
            if workspace == self.owner:
                write(self.updates / 'active.json', self.record)
            return result
        with self.assertRaisesRegex(ValueError, 'active selection appeared'):
            gc.cleanup(self.owner, None, verify_workspace=checked)
        self.assertTrue(old.exists()); self.assert_protected()
        self.assertFalse((self.updates / gc.JOURNAL).exists())

    def test_changed_selection_during_victim_verification_stops_before_unlink(self):
        old = self.version('update-victim-selection-race')
        replacement = {'id': old.name, 'workspace': str((old / 'workspace').relative_to(self.owner))}
        def checked(workspace):
            result = verified(workspace)
            if workspace == old / 'workspace':
                write(self.updates / 'active.json', replacement)
            return result
        report = gc.cleanup(self.owner, self.record, verify_workspace=checked)
        self.assertEqual(report['status'], 'pending')
        self.assertTrue(old.exists()); self.assert_protected()
        self.assertFalse((self.updates / gc.JOURNAL).exists())

    def test_retained_payload_download_is_cleaned_without_deleting_payload(self):
        import test_update_release as release
        payload = self.version('payload-download', payload=True)
        data = release.archive_bytes()
        extracted = release.update.fetch_and_extract(release.offer(data), payload / 'download',
                                                     opener=release.response(data))
        preserved = self.owner / 'preserved-payload-authored-source'
        extracted.rename(preserved)
        report = self.clean(retained_ports=[payload / 'workspace/Monado_Linux'])
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(payload.exists()); verified(payload / 'workspace')
        self.assertFalse((payload / 'download').exists())
        self.assertTrue((preserved / 'README.md').exists()); self.assert_protected()

    def test_journal_traversal_and_duplicate_json_refused(self):
        for value in ['../game_files', '/tmp', None, 'update-x/../game_files']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                gc._victim(self.updates,value)
        (self.updates/gc.JOURNAL).write_text('{"schema":1,"schema":1}')
        self.assertEqual(self.clean()['status'],'pending'); self.assert_protected()


if __name__ == '__main__':
    unittest.main()
