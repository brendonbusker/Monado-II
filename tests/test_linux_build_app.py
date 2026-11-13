"""Authored end-user build fixtures: no network/compiler/game/AppImage execution."""
import contextlib
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_build_linux_app', ROOT / 'tools/build_linux_app.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def inventory(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file() and not path.is_symlink()}


def make_image(path, contents=b'authored never-executed image fixture'):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(16)
    header[:4] = b'\x7fELF'
    header[8:11] = b'AI\x02'
    path.write_bytes(header + contents)
    path.chmod(0o755)
    receipt = dict(schema=1, status='passed', sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    Path(str(path) + '.receipt.json').write_text(json.dumps(receipt))


class LinuxLibraryRootGrammar(unittest.TestCase):
    def test_spaces_and_commas_are_representable(self):
        for root in ('/tmp/source with spaces', '/tmp/source,with,commas'):
            with self.subTest(root=root):
                self.assertIsNone(build.validate_linux_library_root(root))

    def test_linux_separator_and_windows_drive_colons_are_rejected(self):
        for root in ('/tmp/source:other', r'D:\authored\source'):
            with self.subTest(root=root), self.assertRaisesRegex(build.BuildError, 'colons or control'):
                build.validate_linux_library_root(root)

    def test_control_characters_are_rejected_before_any_filesystem_work(self):
        for character in map(chr, range(32)):
            with self.subTest(character=ord(character)), self.assertRaisesRegex(build.BuildError, 'colons or control'):
                build.validate_linux_library_root('/authored/' + character + '/source')


class NativeReceiptSize(unittest.TestCase):
    def test_supported_nested_build_receipt_exceeds_old_limit_but_remains_bounded(self):
        with tempfile.TemporaryDirectory(prefix='monado-native-receipt-') as tmp:
            path=Path(tmp).resolve()/'receipt.json'
            value={'commands':['authored long immutable compiler argument ' * 80] * 1000}
            path.write_text(json.dumps(value))
            self.assertGreater(path.stat().st_size,2*1024*1024)
            self.assertEqual(build.json_file(path),value)
            path.write_bytes(b' '*(build.MAX_BUILD_RECEIPT+1))
            with self.assertRaisesRegex(build.BuildError,'oversized build receipt'):
                build.json_file(path)


class LinuxBuildApp(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-build-app-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'source with spaces'
        self.port = self.root / 'Monado_Linux'
        self.port.mkdir(parents=True)
        self.input = self.root / 'game_files'
        (self.input / 'exefs').mkdir(parents=True)
        (self.input / 'romfs').mkdir()
        (self.input / 'exefs/authored-input-fixture.txt').write_text('no game data; never executed')
        self.commands = []
        self.fail_stage = None
        patch = mock.patch.object(build, 'preflight')
        patch.start(); self.addCleanup(patch.stop)
        if sys.platform == 'win32':
            # These authored planner fixtures do not launch Linux tools. The
            # Windows temporary drive is not a Linux search-path root; isolate
            # that platform boundary while retaining the filesystem assertions.
            # The real grammar check is exercised separately on every host above.
            patch = mock.patch.object(build, 'validate_linux_library_root')
            patch.start(); self.addCleanup(patch.stop)

    def runner(self, command, cwd, log):
        self.commands.append((command, cwd, log))
        log.write_text('AUTHORED NEVER-EXECUTED COMMAND RESULT\n')
        if self.fail_stage and self.fail_stage in ' '.join(command).replace('\\', '/'):
            return 17
        if any(str(value).endswith('/tools/build_launcher_appimage.py') or
               str(value).endswith('\\tools\\build_launcher_appimage.py') for value in command):
            make_image(Path(command[command.index('--output') + 1]))
        return 0

    def run_build(self, identity='test-first', *, dlss=True, framegen=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return build.build(self.root, 3, runner=self.runner,
                               locker=lambda port: contextlib.nullcontext(), identity=identity, dlss=dlss, framegen=framegen)

    def test_plan_without_input_is_read_only_and_executes_nothing(self):
        (self.input / 'exefs/authored-input-fixture.txt').unlink()
        (self.input / 'exefs').rmdir(); (self.input / 'romfs').rmdir(); self.input.rmdir()
        before = inventory(self.root)
        with mock.patch.object(build, 'ROOT', self.root), mock.patch.object(build.subprocess, 'Popen', side_effect=AssertionError('executed')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(build.main(['--plan']), 0)
        document = json.loads(output.getvalue())
        self.assertFalse(document['launches_game'])
        self.assertFalse(document['launches_gui'])
        self.assertEqual(document['mode'], 'plan')
        self.assertTrue(document['dlss_enabled'])
        self.assertTrue(document['framegen_enabled'])
        stages = {stage['name']: stage['argv'] for stage in document['commands']}
        self.assertIn('native-dlss-dependency', stages)
        self.assertIn('--dlss', stages['build-game'])
        self.assertIn('framegen-source', stages)
        self.assertIn('native-framegen-dependency', stages)
        self.assertIn('--framegen', stages['build-game'])
        self.assertEqual(before, inventory(self.root))
        self.assertEqual(sorted(p.name for p in self.port.iterdir()), [])

    def test_game_only_plan_is_read_only_and_has_no_launcher_or_appimage_commands(self):
        before = inventory(self.root)
        with mock.patch.object(build, 'ROOT', self.root), \
                mock.patch.object(build.subprocess, 'Popen', side_effect=AssertionError('executed')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(build.main(['--plan', '--game-only', '--build-id', 'payload-fixed', '--without-dlss']), 0)
        document = json.loads(output.getvalue())
        self.assertTrue(document['game_only'])
        self.assertFalse(document['launches_game'])
        self.assertFalse(document['launches_gui'])
        stages = {stage['name'] for stage in document['commands']}
        self.assertIn('generate-game', stages)
        self.assertIn('build-game', stages)
        self.assertFalse({'build-launcher', 'check-launcher', 'package-appimage'} & stages)
        self.assertEqual(document['paths']['game'], str(self.port / 'build/payload-fixed-game/xcde-linux'))
        self.assertNotIn('published', document['paths'])
        self.assertEqual(before, inventory(self.root))

    def test_game_only_refuses_reuse_and_unsafe_identity_before_build_commands(self):
        before = inventory(self.root)
        with self.assertRaisesRegex(build.BuildError, 'cannot reuse'):
            build.build(self.root, game_only=True, reuse_game=self.port / 'build/old/xcde-linux')
        with self.assertRaisesRegex(build.BuildError, 'unsafe build identity'):
            build.layout(self.root, 2, game_only=True, identity='../outside', dlss=False)
        self.assertEqual(self.commands, [])
        self.assertEqual(before, inventory(self.root))

    def test_game_only_build_cli_passes_fixed_identity_and_features(self):
        with mock.patch.object(build, 'build') as operation:
            self.assertEqual(build.main(['--game-only', '--build-id', 'payload-fixed', '--without-dlss']), 0)
        operation.assert_called_once_with(jobs=4, identity='payload-fixed', dlss=False,
                                          reuse_game=None, framegen=False, game_only=True)

    def test_game_only_preflight_does_not_require_squashfs_tools(self):
        other_spec = importlib.util.spec_from_file_location('monado_game_only_preflight', ROOT / 'tools/build_linux_app.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        with mock.patch.object(other.sys, 'platform', 'linux'), \
                mock.patch.object(other.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(other.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(other.shutil, 'which', side_effect=lambda name, **kwargs: None if name in ('mksquashfs', 'unsquashfs') else '/authored/' + name):
            other.preflight(dlss=False, game_only=True)
            with self.assertRaisesRegex(other.BuildError, 'squashfs-tools'):
                other.preflight(dlss=False)

    def test_runtime_dependency_failure_stops_before_generation_and_preserves_old_image(self):
        make_image(self.root / build.IMAGE, b'accepted prior launcher')
        before = inventory(self.input)
        image_before = (self.root / build.IMAGE).read_bytes()
        self.fail_stage = 'linux_runtime_check.py'
        with self.assertRaisesRegex(build.BuildError, 'check-runtime-dependencies failed'):
            self.run_build()
        self.assertEqual((self.root / build.IMAGE).read_bytes(), image_before)
        self.assertEqual(inventory(self.input), before)
        self.assertFalse(any('gen_all.py' in str(command) for command, _, _ in self.commands))

    def test_missing_input_stops_before_writes_or_downloads(self):
        (self.input / 'romfs').rmdir()
        before = inventory(self.root)
        with self.assertRaisesRegex(build.BuildError, 'game_files/exefs'):
            self.run_build()
        self.assertEqual(self.commands, [])
        self.assertEqual(before, inventory(self.root))

    @unittest.skipUnless(os.name == 'posix', 'native Linux dirfd creation fixture')
    def test_absent_input_creates_only_empty_layout_then_stops_without_commands(self):
        (self.input / 'exefs/authored-input-fixture.txt').unlink()
        (self.input / 'exefs').rmdir(); (self.input / 'romfs').rmdir(); self.input.rmdir()
        with self.assertRaisesRegex(build.BuildError, 'Created empty game_files/exefs'):
            self.run_build()
        self.assertEqual(self.commands, [])
        self.assertEqual(sorted(p.name for p in self.input.iterdir()), ['exefs', 'romfs'])
        self.assertEqual(list((self.input / 'exefs').iterdir()), [])
        self.assertEqual(list((self.input / 'romfs').iterdir()), [])
        self.assertEqual(list(self.port.iterdir()), [])

    def test_existing_link_with_missing_child_is_not_populated(self):
        external = self.base / 'existing input missing romfs'
        self.input.rename(external)
        (external / 'romfs').rmdir()
        try:
            self.input.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest('host does not permit directory symlinks: ' + str(error))
        before = inventory(external)
        with self.assertRaisesRegex(build.BuildError, 'game_files/exefs'):
            self.run_build()
        self.assertFalse((external / 'romfs').exists())
        self.assertEqual(before, inventory(external))
        self.assertEqual(self.commands, [])

    def test_dangling_input_link_is_preserved_and_no_target_created(self):
        (self.input / 'exefs/authored-input-fixture.txt').unlink()
        (self.input / 'exefs').rmdir(); (self.input / 'romfs').rmdir(); self.input.rmdir()
        target = self.base / 'absent external input'
        try:
            self.input.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest('host does not permit directory symlinks: ' + str(error))
        with self.assertRaisesRegex(build.BuildError, 'game_files/exefs'):
            self.run_build()
        self.assertTrue(self.input.is_symlink())
        self.assertFalse(target.exists())
        self.assertEqual(self.commands, [])

    def test_input_symlink_is_resolved_and_is_not_modified(self):
        external = self.base / 'external extracted input'
        self.input.rename(external)
        try:
            self.input.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest('host does not permit directory symlinks: ' + str(error))
        before = inventory(external)
        receipt = self.run_build()
        self.assertEqual(receipt['paths']['input'], str(external))
        self.assertEqual(before, inventory(external))
        self.assertTrue(self.input.is_symlink())

    def test_input_inside_output_source_is_rejected(self):
        external = self.port / 'misplaced-game-input'
        self.input.rename(external)
        try:
            self.input.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest('host does not permit directory symlinks: ' + str(error))
        with self.assertRaisesRegex(build.BuildError, 'disjoint'):
            self.run_build()
        self.assertEqual(self.commands, [])

    def test_managed_output_symlink_is_rejected_without_outside_writes(self):
        external = self.base / 'unrelated'
        external.mkdir()
        try:
            (self.port / 'runs').symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest('host does not permit directory symlinks: ' + str(error))
        with self.assertRaisesRegex(build.BuildError, 'symlinks'):
            self.run_build()
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual(self.commands, [])

    def test_missing_host_tool_is_a_friendly_error_without_system_install(self):
        # Load the original preflight before simulating Linux so conditional
        # imports still observe the real host, including Windows without fcntl.
        other_spec = importlib.util.spec_from_file_location('monado_build_original_preflight', ROOT / 'tools/build_linux_app.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        with mock.patch.object(other.sys, 'platform', 'linux'), \
                mock.patch.object(other.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(other.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(other.shutil, 'which', side_effect=lambda name, **kwargs: None if name == 'mksquashfs' else '/authored/' + name):
            with self.assertRaisesRegex(other.BuildError, 'squashfs-tools'):
                other.preflight()

    def test_dlss_preflight_requires_fixed_namespace_helper_but_optout_does_not(self):
        other_spec = importlib.util.spec_from_file_location('monado_build_dlss_preflight', ROOT / 'tools/build_linux_app.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        with mock.patch.object(other.sys, 'platform', 'linux'), \
                mock.patch.object(other.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(other.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(other.shutil, 'which', side_effect=lambda name, **kwargs: '/authored/' + name), \
                mock.patch.object(other, 'BWRAP', self.base / 'missing-bwrap'), \
                mock.patch.object(other.runtime_check, 'discover_gnu_cxx', side_effect=ValueError('authored missing GNU runtime')):
            with self.assertRaisesRegex(other.BuildError, 'bubblewrap.*without-dlss'):
                other.preflight()
            other.preflight(dlss=False)

    def test_dlss_preflight_checks_gnu_runtime_before_any_build(self):
        other_spec = importlib.util.spec_from_file_location('monado_build_gnu_preflight', ROOT / 'tools/build_linux_app.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        helper = self.base / 'authored-bwrap-placeholder'
        helper.write_text('never executed')
        with mock.patch.object(other.sys, 'platform', 'linux'), \
                mock.patch.object(other.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(other.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(other.shutil, 'which', side_effect=lambda name, **kwargs: '/authored/' + name), \
                mock.patch.object(other.os, 'access', return_value=True), \
                mock.patch.object(other, 'BWRAP', helper), \
                mock.patch.object(other.runtime_check, 'discover_gnu_cxx', side_effect=ValueError('authored missing GNU runtime')):
            with self.assertRaisesRegex(other.BuildError, 'GNU C\\+\\+ runtime'):
                other.preflight()

    def test_dlss_preflight_requires_nm_and_optout_does_not(self):
        other_spec = importlib.util.spec_from_file_location('monado_build_nm_preflight', ROOT / 'tools/build_linux_app.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        with mock.patch.object(other.sys, 'platform', 'linux'), \
                mock.patch.object(other.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(other.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(other.shutil, 'which', side_effect=lambda name, **kwargs: None if name == 'nm' else '/authored/' + name):
            with self.assertRaisesRegex(other.BuildError, 'Missing host build tools: nm'):
                other.preflight()
            other.preflight(dlss=False)

    def test_dlss_preflight_refuses_unreadable_gnu_runtime(self):
        other_spec = importlib.util.spec_from_file_location('monado_build_unreadable_gnu_preflight', ROOT / 'tools/build_linux_app.py')
        other = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(other)
        helper = self.base / 'authored-bwrap-placeholder'
        runtime = self.base / 'authored-libstdc++-placeholder'
        helper.write_text('never executed'); runtime.write_text('never loaded')
        with mock.patch.object(other.sys, 'platform', 'linux'), \
                mock.patch.object(other.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(other.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(other.shutil, 'which', side_effect=lambda name, **kwargs: '/authored/' + name), \
                mock.patch.object(other.os, 'access', side_effect=lambda path, mode: path == helper and mode == os.X_OK), \
                mock.patch.object(other, 'BWRAP', helper), \
                mock.patch.object(other.runtime_check, 'discover_gnu_cxx', side_effect=ValueError('authored unreadable GNU runtime')):
            with self.assertRaisesRegex(other.BuildError, 'GNU C\\+\\+ runtime'):
                other.preflight()

    def test_complete_pipeline_uses_fresh_paths_and_only_headless_checks(self):
        before = inventory(self.input)
        receipt = self.run_build()
        self.assertEqual(receipt['status'], 'passed')
        self.assertEqual(len(self.commands), len(receipt['commands']))
        stages = {entry['name']: command for entry, (command, _, _) in zip(receipt['commands'], self.commands)}
        self.assertTrue('check_dump.py' in self.commands[0][0][-2])
        self.assertIn('--install', self.commands[1][0])
        self.assertIn('--check', self.commands[2][0])
        self.assertIn('--simd', stages['generate-game'])
        self.assertIn('--generated', stages['build-game'])
        self.assertIn('--dlss', stages['build-game'])
        self.assertTrue(stages['native-dlss-dependency'][-1].endswith('/scripts/setup_linux_dlss.py') or
                        stages['native-dlss-dependency'][-1].endswith('\\scripts\\setup_linux_dlss.py'))
        names = [entry['name'] for entry in receipt['commands']]
        self.assertLess(names.index('check-input'), names.index('native-dlss-dependency'))
        self.assertLess(names.index('native-dlss-dependency'), names.index('generate-game'))
        self.assertLess(names.index('check-runtime-dependencies'), names.index('generate-game'))
        self.assertLess(names.index('native-dlss-dependency'), names.index('build-game'))
        self.assertIn('--dry-run', stages['check-launcher'])
        self.assertEqual(self.commands[-1][0], [str(self.root / build.IMAGE), '--appimage-extract-and-run', '--dry-run'])
        self.assertEqual(before, inventory(self.input))
        self.assertFalse((self.port / 'play').exists())
        self.assertTrue((self.root / build.IMAGE).is_file())
        self.assertEqual(build.image_pair(self.root / build.IMAGE)['sha256'], receipt['appimage_sha256'])
        self.assertTrue(receipt['dlss_enabled'])
        self.assertTrue(receipt['framegen_enabled'])
        self.assertIn('--framegen', stages['build-game'])
        self.assertIn('native-framegen-dependency', stages)
        self.assertEqual(Path(receipt['commands'][-1]['log']).name,
                         f'{len(receipt["commands"]):02d}-check-appimage.log')

    def test_without_dlss_explicitly_omits_sdk_and_build_flag(self):
        receipt = self.run_build(dlss=False)
        stages = {entry['name']: command for entry, (command, _, _) in zip(receipt['commands'], self.commands)}
        self.assertFalse(receipt['dlss_enabled'])
        self.assertFalse(receipt['framegen_enabled'])
        self.assertNotIn('native-dlss-dependency', stages)
        self.assertNotIn('framegen-source', stages)
        self.assertNotIn('native-framegen-dependency', stages)
        self.assertNotIn('--dlss', stages['build-game'])
        self.assertTrue(all('--framegen' not in c for c, _, _ in self.commands))
        self.assertEqual(Path(receipt['commands'][-1]['log']).name,
                         f'{len(receipt["commands"]):02d}-check-appimage.log')

    def test_without_dlss_plan_is_read_only_and_has_no_sdk_stage(self):
        before = inventory(self.root)
        with mock.patch.object(build, 'ROOT', self.root), mock.patch.object(build.subprocess, 'Popen', side_effect=AssertionError('executed')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(build.main(['--plan', '--without-dlss']), 0)
        plan = json.loads(output.getvalue())
        stages = {entry['name']: entry['argv'] for entry in plan['commands']}
        self.assertFalse(plan['dlss_enabled'])
        self.assertFalse(plan['framegen_enabled'])
        self.assertNotIn('native-dlss-dependency', stages)
        self.assertNotIn('framegen-source', stages)
        self.assertNotIn('native-framegen-dependency', stages)
        self.assertNotIn('--dlss', stages['build-game'])
        self.assertEqual(inventory(self.root), before)

    def test_without_dlss_cli_is_passed_to_the_builder(self):
        with mock.patch.object(build, 'build') as run:
            self.assertEqual(build.main(['--without-dlss', '--jobs', '2']), 0)
            run.assert_called_once_with(jobs=2, identity=None, dlss=False, reuse_game=None, framegen=False, game_only=False)

    def test_default_framegen_fetches_and_builds_missing_sdk_without_changing_runtime_checkbox(self):
        state = self.port / 'play/launcher'
        state.mkdir(parents=True)
        config = state / 'xcde.ini'
        config.write_text('[graphics]\nframe_gen = 0\ncutscenes = off\n')
        before = inventory(state)
        receipt = self.run_build()
        self.assertTrue(receipt['framegen_enabled'])
        stages = {row['name']: row['argv'] for row in receipt['commands']}
        self.assertIn('--fetch', stages['framegen-source'])
        dependency = stages['native-framegen-dependency']
        self.assertIn('--build', dependency)
        self.assertEqual(Path(dependency[dependency.index('--output') + 1]), self.port / '.deps/fsr/build/test-first')
        self.assertIn('--framegen', stages['build-game'])
        self.assertIn('--dlss', stages['build-game'])
        names = [row['name'] for row in receipt['commands']]
        self.assertLess(names.index('graphics-dependencies'), names.index('framegen-source'))
        self.assertLess(names.index('framegen-source'), names.index('native-framegen-dependency'))
        self.assertLess(names.index('native-framegen-dependency'), names.index('build-game'))
        self.assertEqual(inventory(state), before)

    def test_framegen_plan_reuses_verified_local_sdk_without_fetch_or_build(self):
        sdk = self.port / '.deps/fsr/build/verified-sdk'
        sdk.mkdir(parents=True)
        library = sdk / 'libmonado-fidelityfx.so'
        library.write_text('authored never-loaded library identity fixture')
        with mock.patch.object(build, 'existing_framegen_sdk', return_value={'library_path': str(library)}) as verify:
            before = inventory(self.root)
            paths, commands = build.layout(self.root, 2, identity='verify-sdk')
        verify.assert_called_once_with(self.port)
        stages = dict(commands)
        self.assertNotIn('framegen-source', stages)
        self.assertNotIn('--build', stages['native-framegen-dependency'])
        self.assertEqual(Path(stages['native-framegen-dependency'][-1]), self.port / 'scripts/setup_linux_fsr.py')
        self.assertEqual(paths['framegen_sdk'], sdk)
        self.assertEqual(inventory(self.root), before)

    def test_framegen_stale_sdk_fails_without_overwrite_fetch_or_game_commands(self):
        active = self.port / '.deps/fsr/active-build.txt'
        active.parent.mkdir(parents=True)
        active.write_text('authored stale dependency marker')
        script = self.port / 'scripts/setup_linux_fsr.py'
        script.parent.mkdir(parents=True)
        script.write_text('def verify_existing():\n    raise ValueError("SDK recipe hash changed")\n')
        before = inventory(self.root)
        with self.assertRaisesRegex(build.BuildError, 'SDK failed verification.*recipe hash changed'):
            self.run_build()
        self.assertEqual(self.commands, [])
        self.assertEqual(inventory(self.root), before)

    def test_framegen_without_dlss_stops_before_input_layout_or_preflight(self):
        before = inventory(self.root)
        with mock.patch.object(build, 'prepare_input_layout') as prepare, \
                mock.patch.object(build, 'preflight') as preflight, \
                self.assertRaisesRegex(build.BuildError, 'cannot be combined'):
            self.run_build(dlss=False, framegen=True)
        prepare.assert_not_called()
        preflight.assert_not_called()
        self.assertEqual(self.commands, [])
        self.assertEqual(inventory(self.root), before)

    def test_explicit_framegen_cli_conflict_is_rejected_before_builder_or_plan(self):
        before = inventory(self.root)
        for command in (['--without-dlss', '--framegen'], ['--plan', '--without-dlss', '--framegen']):
            with self.subTest(command=command), mock.patch.object(build, 'build') as operation, \
                    mock.patch.object(build, 'layout') as planner, contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(build.main(command), 1)
            operation.assert_not_called()
            planner.assert_not_called()
            self.assertIn('cannot be combined', error.getvalue())
        self.assertEqual(inventory(self.root), before)

    def test_framegen_dependency_failure_preserves_existing_image_before_game(self):
        make_image(self.root / build.IMAGE, b'previous known image')
        original = (self.root / build.IMAGE).read_bytes()
        self.fail_stage = '--build --output'
        with self.assertRaisesRegex(build.BuildError, 'native-framegen-dependency failed'):
            self.run_build()
        receipt = json.loads((self.port / 'runs/local-build/test-first/receipt.json').read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertTrue(receipt['framegen_enabled'])
        self.assertEqual(receipt['commands'][-1]['name'], 'native-framegen-dependency')
        self.assertFalse(any('--generated' in command for command, _, _ in self.commands))
        self.assertEqual((self.root / build.IMAGE).read_bytes(), original)

    def test_framegen_cli_optin_and_readonly_plan_record_the_feature(self):
        with mock.patch.object(build, 'build') as operation:
            self.assertEqual(build.main(['--framegen', '--jobs', '2']), 0)
            operation.assert_called_once_with(jobs=2, identity=None, dlss=True, reuse_game=None, framegen=True, game_only=False)
        before = inventory(self.root)
        with mock.patch.object(build, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build.main(['--plan', '--framegen']), 0)
        plan = json.loads(output.getvalue())
        self.assertTrue(plan['framegen_enabled'])
        self.assertEqual(inventory(self.root), before)

    def test_normal_cli_and_updater_command_without_feature_flag_include_framegen(self):
        # Older updater clients invoke only Build_Monado_II.sh --jobs N.
        # The current builder must add the provider without requiring new flags.
        with mock.patch.object(build, 'build') as operation:
            self.assertEqual(build.main(['--jobs', '4']), 0)
            operation.assert_called_once_with(jobs=4, identity=None, dlss=True, reuse_game=None, framegen=True, game_only=False)

    def test_nonboolean_feature_selections_are_rejected_before_any_writes(self):
        before = inventory(self.root)
        for dlss, framegen in ((1, None), ('yes', None), (True, 1), (True, 0), (True, 'false')):
            with self.subTest(dlss=dlss, framegen=framegen), \
                    mock.patch.object(build, 'prepare_input_layout') as prepare, \
                    mock.patch.object(build, 'preflight') as preflight, \
                    self.assertRaisesRegex(build.BuildError, 'must be booleans'):
                self.run_build(dlss=dlss, framegen=framegen)
            prepare.assert_not_called()
            preflight.assert_not_called()
        self.assertEqual(inventory(self.root), before)
        self.assertEqual(self.commands, [])

    def test_second_build_is_fresh_and_preserves_verified_previous_pair(self):
        self.run_build()
        old = (self.root / build.IMAGE).read_bytes()
        make_image(self.root / build.IMAGE, b'previous authored launcher')
        old = (self.root / build.IMAGE).read_bytes()
        receipt = self.run_build('test-second')
        backup = self.port / 'build/test-second-appimage/previous' / build.IMAGE
        self.assertEqual(backup.read_bytes(), old)
        self.assertEqual(receipt['status'], 'passed')
        self.assertNotEqual(receipt['paths']['generated'], str(self.port / 'generated/test-first'))

    def test_unknown_existing_appimage_is_preserved_before_any_commands(self):
        path = self.root / build.IMAGE
        path.write_text('unknown user file')
        with self.assertRaisesRegex(build.BuildError, 'incomplete existing'):
            self.run_build()
        self.assertEqual(path.read_text(), 'unknown user file')
        self.assertEqual(self.commands, [])

    def test_changed_existing_appimage_is_not_overwritten(self):
        path = self.root / build.IMAGE
        make_image(path)
        path.write_bytes(path.read_bytes() + b'changed')
        before = inventory(self.root)
        with self.assertRaisesRegex(build.BuildError, 'refusing to replace'):
            self.run_build()
        self.assertEqual(before, inventory(self.root))
        self.assertEqual(self.commands, [])

    def test_bad_input_checker_stops_before_dependencies_and_keeps_failure_log(self):
        self.fail_stage = 'check_dump.py'
        with self.assertRaisesRegex(build.BuildError, 'check-input failed'):
            self.run_build()
        self.assertEqual(len(self.commands), 1)
        receipt = json.loads((self.port / 'runs/local-build/test-first/receipt.json').read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['commands'][0]['exit'], 17)
        self.assertFalse((self.root / build.IMAGE).exists())

    def test_mid_build_failure_does_not_publish_or_touch_previous_image(self):
        path = self.root / build.IMAGE
        make_image(path, b'previous authored launcher')
        before = path.read_bytes()
        self.fail_stage = 'scripts/build_linux.py'
        with self.assertRaisesRegex(build.BuildError, 'build-game failed'):
            self.run_build()
        self.assertEqual(path.read_bytes(), before)
        receipt = json.loads((self.port / 'runs/local-build/test-first/receipt.json').read_text())
        receipt_names = [entry['name'] for entry in receipt['commands']]
        self.assertEqual(receipt_names[-1], 'build-game')
        self.assertIn('native-dlss-dependency', receipt_names)
        self.assertFalse(any('package-appimage' in str(log) for _, _, log in self.commands))

    def test_failed_dlss_setup_stops_before_generation_and_preserves_previous_image(self):
        path = self.root / build.IMAGE
        make_image(path, b'previous authored launcher')
        before = path.read_bytes()
        input_before = inventory(self.input)
        self.fail_stage = 'scripts/setup_linux_dlss.py'
        with self.assertRaisesRegex(build.BuildError, 'native-dlss-dependency failed'):
            self.run_build()
        receipt = json.loads((self.port / 'runs/local-build/test-first/receipt.json').read_text())
        names = [entry['name'] for entry in receipt['commands']]
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(names[-1], 'native-dlss-dependency')
        self.assertNotIn('generate-game', names)
        self.assertNotIn('build-game', names)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(inventory(self.input), input_before)

    def test_final_appimage_failure_restores_previous_image_and_receipt(self):
        path = self.root / build.IMAGE
        make_image(path, b'previous authored launcher')
        old_image = path.read_bytes()
        old_receipt = Path(str(path) + '.receipt.json').read_bytes()
        self.fail_stage = '--appimage-extract-and-run'
        with self.assertRaisesRegex(build.BuildError, 'startup check failed'):
            self.run_build()
        self.assertEqual(path.read_bytes(), old_image)
        self.assertEqual(Path(str(path) + '.receipt.json').read_bytes(), old_receipt)
        self.assertTrue((self.port / 'build/test-first-appimage' / ('failed-' + build.IMAGE)).is_file())

    def test_first_appimage_check_failure_does_not_leave_accepted_root_artifacts(self):
        self.fail_stage = '--appimage-extract-and-run'
        with self.assertRaisesRegex(build.BuildError, 'startup check failed'):
            self.run_build()
        self.assertFalse((self.root / build.IMAGE).exists())
        self.assertFalse(Path(str(self.root / build.IMAGE) + '.receipt.json').exists())

    def test_existing_generated_build_directory_is_never_reused(self):
        path = self.port / 'generated/test-first'
        path.mkdir(parents=True)
        with self.assertRaisesRegex(build.BuildError, 'must be fresh'):
            self.run_build()
        self.assertEqual(self.commands, [])

    def test_lock_is_nonblocking_and_scoped_to_this_port(self):
        if os.name != 'posix':
            self.skipTest('native POSIX advisory lock fixture')
        with build.build_lock(self.port):
            with self.assertRaisesRegex(build.BuildError, 'already running'):
                with build.build_lock(self.port):
                    self.fail('a second builder acquired the same lock')

    def test_cancelled_stage_preserves_previous_appimage_and_records_cancelled(self):
        path = self.root / build.IMAGE
        make_image(path, b'previous authored launcher')
        before = path.read_bytes()
        with mock.patch.object(self, 'runner', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_build()
        self.assertEqual(path.read_bytes(), before)
        receipt = json.loads((self.port / 'runs/local-build/test-first/receipt.json').read_text())
        self.assertEqual(receipt['status'], 'cancelled')
        self.assertEqual(receipt['commands'][-1]['status'], 'cancelled')

    @unittest.skipUnless(sys.platform == 'linux', 'native Linux process ownership fixture')
    def test_command_runner_logs_progress_and_does_not_inherit_loader_controls(self):
        log = self.port / 'authored-command.log'
        command = [sys.executable, '-I', '-c', 'import os; print("authored progress"); print("loader=" + str("LD_PRELOAD" in os.environ)); print("pythonpath=" + str("PYTHONPATH" in os.environ))']
        with mock.patch.dict(os.environ, {'LD_PRELOAD': '/untrusted', 'PYTHONPATH': '/untrusted'}):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(build.execute(command, self.port, log), 0)
        self.assertEqual(log.read_text(), 'authored progress\nloader=False\npythonpath=False\n')
        self.assertIn('authored progress', output.getvalue())
        self.assertEqual(build.descendants(), {})

    def test_owned_signal_uses_pidfd_and_refuses_changed_kernel_identity(self):
        owned = {101: ((101, 77), 100, 'S'), 102: ((102, 88), 101, 'S'), 103: ((103, 99), 101, 'Z')}
        current = {101: ((101, 77), 100, 'S'), 102: ((102, 999), 100, 'S')}
        with mock.patch.object(build.os, 'pidfd_open', create=True, return_value=44) as opened, mock.patch.object(build.os, 'close') as closed, mock.patch.object(build.signal, 'pidfd_send_signal', create=True) as sent, mock.patch.object(build, 'child_id', side_effect=lambda pid: current[pid]):
            build.signal_owned(owned, 9)  # Authored number; Windows has no SIGKILL constant.
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(closed.call_count, 2)
        sent.assert_called_once_with(44, 9)

    @unittest.skipUnless(sys.platform == 'linux', 'native Linux process ownership fixture')
    def test_command_refuses_existing_unrelated_child_without_signalling_it(self):
        child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
        try:
            with self.assertRaisesRegex(build.BuildError, 'unrelated existing children'):
                build.execute([sys.executable, '-I', '-c', 'pass'], self.port, self.port / 'unused-command.log')
            self.assertIsNone(child.poll())
        finally:
            child.terminate(); child.wait(timeout=5)

    @unittest.skipUnless(sys.platform == 'linux', 'native Linux subreaper and setsid fixture')
    def test_cancel_reaps_escaped_grandchild_and_restores_prior_subreaper_state(self):
        libc = ctypes.CDLL(None, use_errno=True)
        original = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(original), 0, 0, 0), 0)
        handler = signal.getsignal(signal.SIGINT)
        grandchild_code = ('import os,signal,sys,time; from pathlib import Path; '
                           'signal.signal(signal.SIGINT,signal.SIG_IGN); '
                           'Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)')
        stage_code = '''import json,os,signal,subprocess,sys,time
from pathlib import Path
signal.signal(signal.SIGINT,signal.SIG_IGN)
grandchild=subprocess.Popen([sys.executable,'-I','-c',sys.argv[3],sys.argv[2]],start_new_session=True)
while not Path(sys.argv[2]).exists(): time.sleep(0.005)
Path(sys.argv[1]).write_text(json.dumps(dict(stage=os.getpid(),grandchild=grandchild.pid,stage_group=os.getpgrp(),grandchild_group=os.getpgid(grandchild.pid))))
print('authored escaped worker ready',flush=True)
os.kill(os.getppid(),signal.SIGINT)
time.sleep(60)
'''
        try:
            for previous in (0, 1):
                with self.subTest(previous_subreaper=previous):
                    self.assertEqual(libc.prctl(36, previous, 0, 0, 0), 0)
                    identities = self.port / f'authored-workers-{previous}.json'
                    ready = self.port / f'authored-ready-{previous}.txt'
                    command = [sys.executable, '-I', '-c', stage_code, str(identities), str(ready), grandchild_code]
                    started = time.monotonic()
                    with contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaises(KeyboardInterrupt):
                            build.execute(command, self.port, self.port / f'authored-command-{previous}.log', cancel_grace=0.05, cleanup_timeout=5)
                    self.assertLess(time.monotonic() - started, 5)
                    record = json.loads(identities.read_text())
                    self.assertNotEqual(record['stage_group'], os.getpgrp())
                    self.assertNotEqual(record['stage_group'], record['grandchild_group'])
                    for pid in (record['stage'], record['grandchild']):
                        self.assertIsNone(build.child_id(pid))
                        with self.assertRaises(ChildProcessError):
                            os.waitpid(pid, os.WNOHANG)
                    self.assertEqual(build.descendants(), {})
                    actual = ctypes.c_int()
                    self.assertEqual(libc.prctl(37, ctypes.byref(actual), 0, 0, 0), 0)
                    self.assertEqual(actual.value, previous)
                    self.assertIs(signal.getsignal(signal.SIGINT), handler)
        finally:
            self.assertEqual(libc.prctl(36, original.value, 0, 0, 0), 0)


if __name__ == '__main__':
    unittest.main()
