"""Managed source/build reuse fixtures; all executable bytes are authored mocks."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_managed_build_test', ROOT / 'tools/build_linux_app.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
native_spec = importlib.util.spec_from_file_location('monado_managed_native_producer',
    ROOT / 'Monado_Linux/scripts/build_linux.py')
native_builder = importlib.util.module_from_spec(native_spec)
native_spec.loader.exec_module(native_builder)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and not p.is_symlink()}


def write_elf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = bytearray(64)
    data[:6] = b'\x7fELF\x02\x01'
    data[18:20] = (62).to_bytes(2, 'little')
    path.write_bytes(data)
    path.chmod(0o700)


class ManagedBuild(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-managed-build-')
        self.addCleanup(temporary.cleanup)
        self.owner = Path(temporary.name).resolve() / 'original with spaces'
        self.original = self.owner / 'Monado_Linux'
        self.workspace = self.original / 'updates/release-2/workspace'
        self.port = self.workspace / 'Monado_Linux'
        self.port.mkdir(parents=True)
        self.input = self.owner / 'game_files'
        (self.input / 'exefs').mkdir(parents=True)
        (self.input / 'romfs').mkdir()
        (self.input / 'exefs/authored-fixture.txt').write_text('authored input fixture, no game content')
        try:
            (self.workspace / 'game_files').symlink_to(self.input, target_is_directory=True)
        except OSError as error:
            self.skipTest('directory link unavailable: ' + str(error))
        (self.workspace / 'installation.json').write_text(json.dumps({'schema': 1,
            'owner': str(self.owner), 'workspace': str(self.workspace), 'game_port': str(self.original)}))
        self.state = self.original / 'play/launcher'
        (self.state / 'saves').mkdir(parents=True)
        (self.state / 'saves/authored-save.txt').write_text('preserve authored save fixture')
        (self.state / 'xcde.ini').write_text('[fixture]\nvalue=preserve\n')
        self.game = self.original / 'build/accepted-game/xcde-linux'
        write_elf(self.game)
        # Derive script/lock names from the real native receipt producer. Keep
        # native inputs authored and tiny; do not mirror the reuse consumer list.
        # Model the Linux producer's POSIX receipt keys on either CI host.
        names = [name.replace('\\', '/') for name in native_builder.source_snapshot()]
        names = [name for name in names if not name.startswith(('runtime/', 'third_party/'))]
        names.append('runtime/authored.c')
        snapshot = {}
        for name in names:
            for port in (self.original, self.port):
                path = port / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('authored source fixture: ' + name)
            snapshot[name] = sha(self.port / name)
        self.sysroot = self.original / '.deps/graphics/sysroots/authored'
        self.marker(self.sysroot, snapshot['graphics-deps-linux.lock.json'])
        self.receipt = {'schema': 1, 'status': 'passed', 'errors': [], 'dlss_enabled': False,
            'framegen_enabled': False, 'precompile_protocol': 1,
            'executable': {'path': str(self.game), 'sha256': sha(self.game)},
            'generated': {'generated/authored/main/main_table.c': 'authored generation identity'},
            'sources_before': snapshot, 'sources_after': dict(snapshot),
            'dependencies': {'sysroot': str(self.sysroot)},
            'input': {'path': str(self.input), 'exefs': {'authored-fixture.txt': sha(self.input / 'exefs/authored-fixture.txt')}}}
        self.save_receipt()
        self.commands = []
        patch = mock.patch.object(build, 'preflight')
        patch.start()
        self.addCleanup(patch.stop)
        if sys.platform == 'win32':
            # Metadata/source/state tests use authored, never-run Linux ELFs.
            # Only replace the unavailable Linux path-list boundary on Windows;
            # real receipt ownership, hashes, source closure and paths still run.
            patch = mock.patch.object(build, 'validate_linux_library_root')
            patch.start(); self.addCleanup(patch.stop)
            patch = mock.patch.object(build.run_linux.runtime_check, 'library_path',
                side_effect=lambda sysroot, policy=None: str(Path(sysroot) / 'usr/lib/x86_64-linux-gnu'))
            patch.start(); self.addCleanup(patch.stop)

    def marker(self, sysroot, lock):
        (sysroot / 'usr/lib/x86_64-linux-gnu').mkdir(parents=True)
        (sysroot / '.monado-deps.json').write_text(json.dumps({'lock_sha256': lock}))

    def save_receipt(self):
        (self.game.parent / 'receipt.json').write_text(json.dumps(self.receipt))

    def runner(self, command, cwd, log):
        self.commands.append(command)
        log.write_text('authored command fixture; never executed')
        if any(Path(str(value)).name == 'build_launcher_appimage.py' for value in command):
            target = Path(command[command.index('--output') + 1])
            target.parent.mkdir(parents=True)
            data = bytearray(64)
            data[:4] = b'\x7fELF'
            data[8:11] = b'AI\x02'
            target.write_bytes(data)
            target.chmod(0o700)
            Path(str(target) + '.receipt.json').write_text(json.dumps({'status': 'passed', 'sha256': sha(target)}))
        return 0

    def test_bound_game_plan_uses_original_sysroot_input_and_stable_state(self):
        before = files(self.state)
        result = build.run_linux.plan(self.game, self.state, port=self.port)
        self.assertEqual(result['build_port'], str(self.original))
        self.assertEqual(result['library_path'], str(self.sysroot / 'usr/lib/x86_64-linux-gnu'))
        self.assertEqual(result['input'], str(self.input))
        self.assertEqual(result['argv'], [str(self.game), '--state-root', str(self.state), str(self.input)])
        self.assertEqual(files(self.state), before)

    def test_current_gui_can_use_owner_state_and_local_test_runs(self):
        gui = self.port / 'build/gui/monado-launcher'
        write_elf(gui)
        sysroot = self.port / '.deps/graphics/sysroots/authored'
        self.marker(sysroot, 'gui-lock')
        receipt = {'status': 'passed', 'executable': {'path': str(gui), 'sha256': sha(gui)},
            'dependencies': {'sysroot': str(sysroot)}, 'sources_before': {'graphics-deps-linux.lock.json': 'gui-lock'}}
        (gui.parent / 'receipt.json').write_text(json.dumps(receipt))
        for state in (self.state, self.port / 'runs/private-test'):
            self.assertEqual(build.run_linux.plan(gui, state, port=self.port)['build_port'], str(self.port))
        with self.assertRaisesRegex(ValueError, 'allowed Linux'):
            build.run_linux.plan(gui, self.port / 'play/split-profile', port=self.port)

    def test_bound_game_cannot_borrow_the_candidate_sysroot(self):
        sysroot = self.port / '.deps/graphics/sysroots/not-the-original'
        self.marker(sysroot, self.receipt['sources_before']['graphics-deps-linux.lock.json'])
        self.receipt['dependencies']['sysroot'] = str(sysroot)
        self.save_receipt()
        with self.assertRaisesRegex(ValueError, 'valid local graphics sysroot'):
            build.run_linux.plan(self.game, self.state, port=self.port)

    def test_substituted_input_and_unbound_original_game_are_rejected(self):
        (self.workspace / 'game_files').unlink()
        (self.workspace / 'game_files').mkdir()
        with self.assertRaisesRegex(ValueError, 'input must match'):
            build.run_linux.plan(self.game, self.state, port=self.port)
        (self.workspace / 'installation.json').unlink()
        with self.assertRaisesRegex(ValueError, 'current or bound'):
            build.run_linux.plan(self.game, self.state, port=self.port)

    def test_reuse_plan_omits_game_generation_and_compilation_only(self):
        before = files(self.owner)
        paths, commands = build.layout(self.workspace, 2, identity='reuse-plan', dlss=False, reuse_game=self.game)
        stages = dict(commands)
        self.assertNotIn('generate-game', stages)
        self.assertNotIn('build-game', stages)
        self.assertIn('install-tools', stages)
        self.assertIn('graphics-dependencies', stages)
        self.assertIn('build-launcher', stages)
        self.assertEqual(paths['game'], self.game)
        self.assertEqual(paths['state'], self.state)
        self.assertEqual(files(self.owner), before)

    def game_only_runner(self, command, cwd, log):
        result = self.runner(command, cwd, log)
        if any(Path(str(value)).name == 'build_linux.py' for value in command):
            (self.port / '.deps/metadata').mkdir(parents=True, exist_ok=True)
            game = Path(command[command.index('--output') + 1]) / 'xcde-linux'
            write_elf(game)
            sysroot = self.port / '.deps/graphics/sysroots/authored'
            if not sysroot.exists():
                self.marker(sysroot, self.receipt['sources_before']['graphics-deps-linux.lock.json'])
            receipt = dict(self.receipt, executable={'path': str(game), 'sha256': sha(game)},
                           dependencies={'sysroot': str(sysroot)})
            (game.parent / 'receipt.json').write_text(json.dumps(receipt))
        return result

    def test_game_only_publishes_verified_payload_marker_and_keeps_profile_original_image(self):
        (self.workspace / 'installation.json').write_text(json.dumps({'schema': 1,
            'owner': str(self.owner), 'workspace': str(self.workspace), 'game_port': str(self.port)}))
        original_image = self.owner / build.IMAGE
        original_image.write_text('original bootstrap remains untouched')
        before = files(self.state), files(self.input), files(self.original / 'build')
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(build.run_linux, 'validate_runtime', return_value={'status': 'passed'}) as checked:
            receipt = build.build(self.workspace, 2, runner=self.game_only_runner,
                locker=lambda port: contextlib.nullcontext(), identity='immutable-payload', dlss=False, game_only=True)
        game = self.port / 'build/immutable-payload-game/xcde-linux'
        marker = json.loads((self.port / '.deps/metadata/game-payload.json').read_text())
        self.assertEqual(marker['artifact_kind'], 'local-game-payload')
        self.assertEqual(marker['status'], 'passed')
        self.assertEqual(marker['build_id'], 'immutable-payload')
        self.assertEqual(marker['game']['path'], str(game))
        self.assertEqual(marker['game']['sha256'], sha(game))
        self.assertEqual(marker['game']['receipt_sha256'], sha(game.parent / 'receipt.json'))
        self.assertEqual(marker['game']['build_port'], str(self.port))
        self.assertEqual(marker['build_receipt_sha256'], sha(self.port / 'runs/local-build/immutable-payload/receipt.json'))
        self.assertEqual(receipt['status'], 'passed')
        checked.assert_called_once()
        self.assertEqual(before, (files(self.state), files(self.input), files(self.original / 'build')))
        self.assertEqual(original_image.read_text(), 'original bootstrap remains untouched')
        self.assertFalse((self.workspace / build.IMAGE).exists())
        self.assertFalse(any('build_launcher' in str(command) or '--dry-run' in command for command in self.commands))
        with self.assertRaisesRegex(build.BuildError, 'receipt already exists'):
            build.layout(self.workspace, 2, identity='another-game', dlss=False, game_only=True)

    def test_game_only_validation_failure_does_not_publish_payload_or_launcher(self):
        for name in ('missing-native-receipt', 'runtime-rejected'):
            with self.subTest(name=name):
                identity = 'game-' + name
                runner = self.runner if name == 'missing-native-receipt' else self.game_only_runner
                with contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.object(build.run_linux, 'validate_runtime', side_effect=ValueError('authored runtime rejection')):
                    with self.assertRaises((ValueError, OSError, build.BuildError)):
                        build.build(self.workspace, 2, runner=runner,
                            locker=lambda port: contextlib.nullcontext(), identity=identity, dlss=False, game_only=True)
                self.assertFalse((self.port / '.deps/metadata/game-payload.json').exists())
                self.assertFalse((self.workspace / build.IMAGE).exists())
                receipt = json.loads((self.port / ('runs/local-build/' + identity) / 'receipt.json').read_text())
                self.assertEqual(receipt['status'], 'failed')

    def test_payload_marker_failure_records_failed_build_and_preserves_profile(self):
        before = files(self.state), files(self.input)
        original = build.write_json
        marker = self.port / '.deps/metadata/game-payload.json'
        def write(path, document):
            if path == marker:
                raise PermissionError('authored marker publication failure')
            return original(path, document)
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(build.run_linux, 'validate_runtime', return_value={'status': 'passed'}), \
                mock.patch.object(build, 'write_json', side_effect=write):
            with self.assertRaisesRegex(PermissionError, 'marker publication'):
                build.build(self.workspace, 2, runner=self.game_only_runner,
                    locker=lambda port: contextlib.nullcontext(), identity='marker-failure', dlss=False, game_only=True)
        self.assertFalse(marker.exists())
        receipt = json.loads((self.port / 'runs/local-build/marker-failure/receipt.json').read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(before, (files(self.state), files(self.input)))

    def test_reuse_build_publishes_only_inside_candidate_and_preserves_old_receipt_state_input(self):
        active = self.owner / build.IMAGE
        active.write_text('original active bootstrap fixture')
        original_receipt = (self.game.parent / 'receipt.json').read_bytes()
        input_before, state_before = files(self.input), files(self.state)
        with contextlib.redirect_stdout(io.StringIO()):
            receipt = build.build(self.workspace, 2, runner=self.runner,
                locker=lambda port: contextlib.nullcontext(), identity='retained', dlss=False, reuse_game=self.game)
        self.assertEqual(receipt['status'], 'passed')
        self.assertEqual(receipt['reused_game']['sha256'], sha(self.game))
        self.assertEqual(active.read_text(), 'original active bootstrap fixture')
        self.assertTrue((self.workspace / build.IMAGE).is_file())
        self.assertEqual(self.commands[-1], [str(self.workspace / build.IMAGE), '--appimage-extract-and-run', '--dry-run'])
        self.assertEqual((self.game.parent / 'receipt.json').read_bytes(), original_receipt)
        self.assertEqual(files(self.input), input_before)
        self.assertEqual(files(self.state), state_before)

    def test_reuse_rejects_feature_mismatch_or_incomplete_receipt_before_commands(self):
        for key, value in (('dlss_enabled', True), ('framegen_enabled', True), ('generated', {}), ('status', 'failed'),
                           ('sources_after', {}), ('errors', ['an original failure'])):
            original = self.receipt[key]
            self.receipt[key] = value
            self.save_receipt()
            with self.subTest(key=key), self.assertRaises(build.BuildError):
                build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)
            self.assertEqual(self.commands, [])
            self.receipt[key] = original
        self.save_receipt()

    def test_reuse_rejects_changed_and_new_native_sources(self):
        source = self.port / 'runtime/authored.c'
        original = source.read_bytes()
        source.write_text('changed authored source')
        with self.assertRaisesRegex(build.BuildError, 'native source differs'):
            build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)
        source.write_bytes(original)
        (self.port / 'runtime/new_source.c').write_text('new authored source')
        with self.assertRaisesRegex(build.BuildError, 'source closure differs'):
            build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)

    def test_reuse_rejects_tampered_game_and_changed_selected_input(self):
        self.game.write_bytes(self.game.read_bytes() + b'tampered')
        with self.assertRaisesRegex(ValueError, 'successful build receipt'):
            build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)
        write_elf(self.game)
        (self.input / 'exefs/authored-fixture.txt').write_text('changed input fixture')
        with self.assertRaisesRegex(build.BuildError, 'input differs'):
            build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)

    def test_reuse_cli_is_explicitly_forwarded_to_builder(self):
        with mock.patch.object(build, 'build') as operation:
            self.assertEqual(build.main(['--reuse-game', str(self.game), '--without-dlss']), 0)
            operation.assert_called_once_with(jobs=4, identity=None, dlss=False, reuse_game=self.game, framegen=False, game_only=False)

    def test_normal_reuse_rejects_older_dlss_game_without_framegen_before_writes(self):
        self.receipt['dlss_enabled'] = True
        self.save_receipt()
        before = files(self.owner)
        with self.assertRaisesRegex(build.BuildError, 'frame-generation flag differs'):
            build.layout(self.workspace, 2, reuse_game=self.game)
        self.assertEqual(files(self.owner), before)
        self.assertEqual(self.commands, [])

    def test_reuse_requires_explicit_boolean_framegen_receipt_metadata(self):
        for value in (None, 0, 1, 'false', [], {}):
            self.receipt['framegen_enabled'] = value
            self.save_receipt()
            with self.subTest(value=value), self.assertRaisesRegex(build.BuildError, 'frame-generation flag differs'):
                build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)
        del self.receipt['framegen_enabled']
        self.save_receipt()
        with self.assertRaisesRegex(build.BuildError, 'frame-generation flag differs'):
            build.layout(self.workspace, 2, dlss=False, reuse_game=self.game)
        self.assertEqual(self.commands, [])

    def test_framegen_reuse_requires_matching_flags_and_retains_old_companions(self):
        self.receipt['dlss_enabled'] = self.receipt['framegen_enabled'] = True
        resources = {}
        for name in ('libmonado-ngx.so', 'libnvidia-ngx-dlss.so.310.9.1', 'NVIDIA-DLSS-LICENSE.txt',
                     'libmonado-fidelityfx.so', 'FidelityFX-MIT.txt'):
            path = self.game.parent / name
            path.write_text('authored never-loaded companion: ' + name)
            resources[name] = {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}
        self.receipt['runtime_resources'] = resources
        self.save_receipt()
        with self.assertRaisesRegex(build.BuildError, 'frame-generation flag differs'):
            build.layout(self.workspace, 2, dlss=True, framegen=False, reuse_game=self.game)
        original = files(self.game.parent)
        with mock.patch.object(build, 'existing_framegen_sdk', side_effect=AssertionError('do not rebuild old SDK')), \
                mock.patch.object(build.run_linux, 'dlss_namespace', side_effect=lambda argv, state: (argv, {'kind': 'authored'})):
            paths, commands = build.layout(self.workspace, 2, reuse_game=self.game)
        self.assertEqual(paths['game'], self.game)
        self.assertFalse(any(name in ('framegen-source', 'native-framegen-dependency', 'generate-game', 'build-game') for name, _ in commands))
        self.assertEqual(files(self.game.parent), original)

    def test_reused_receipt_change_during_launcher_build_stops_before_publication(self):
        original = self.runner
        def mutate(command, cwd, log):
            result = original(command, cwd, log)
            if any(Path(str(value)).name == 'build_launcher_appimage.py' for value in command):
                self.receipt['finished_utc'] = 'changed receipt fixture'
                self.save_receipt()
            return result
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(build.BuildError, 'identity changed'):
            build.build(self.workspace, 2, runner=mutate, locker=lambda port: contextlib.nullcontext(),
                        identity='changed-receipt', dlss=False, reuse_game=self.game)
        self.assertFalse((self.workspace / build.IMAGE).exists())


if __name__ == '__main__':
    unittest.main()
