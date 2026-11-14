"""LINUX-077: actual controller-context filtering and private metadata routing."""
import importlib.util
import errno
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
SCRIPTS = PORT / 'scripts'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = launcher = context = None
if sys.platform == 'linux':
    native = load('controller_run_linux_test', SCRIPTS / 'run_linux.py')
    context = native.controller_environment
    with mock.patch.dict(sys.modules, {'run_linux': native}):
        launcher = load('controller_launcher_test', SCRIPTS / 'launcher_linux.py')


@unittest.skipUnless(sys.platform == 'linux', 'Linux controller launch context')
class ControllerEnvironment(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-controller-environment-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.metadata = self.root / 'authored-steam-info'
        self.metadata.write_text('authored SDL controller metadata fixture\n')
        self.metadata.chmod(0o600)

    def test_actual_launcher_preserves_related_input_context_together(self):
        source = {'SteamAppId': '123', 'SteamGameId': str((1 << 64)-1),
                  'SteamVirtualGamepadInfo': str(self.metadata),
                  'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD': '1',
                  'SDL_GAMECONTROLLER_IGNORE_DEVICES': '0x28de/0x1205,0x054c/0x0ce6',
                  'SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT': '0x045e/0x028e',
                  'SDL_GAMECONTROLLERCONFIG': 'authored mapping,not a code path\nsecond mapping',
                  'SDL_JOYSTICK_HIDAPI_STEAMDECK': '0', 'SDL_JOYSTICK_DISABLE_UDEV': '1'}
        before = dict(source)
        with mock.patch.dict(os.environ, source, clear=True):
            child = launcher.clean_environment('/authored/private-libs')
        for key, value in source.items():
            self.assertEqual(child.get(key), value, key)
        self.assertEqual(source, before)

    def test_unknown_loader_and_game_state_controls_stay_filtered(self):
        source = {'SDL_DYNAMIC_API': '/unsafe/driver.so', 'SDL_DYNAPI': '/unsafe/driver.so',
                  'SDL_NOT_REVIEWED': '1', 'LD_PRELOAD': '/unsafe/preload.so',
                  'LD_LIBRARY_PATH': '/unsafe/libs', 'XCDE_INI': '/unsafe/config',
                  'SteamUnreviewedControl': '1', 'RADV_DEBUG': 'authored'}
        with mock.patch.dict(os.environ, source, clear=True):
            child = launcher.clean_environment('/reviewed/private-libs')
        self.assertEqual(child['LD_LIBRARY_PATH'], '/reviewed/private-libs')
        for key in set(source)-{'LD_LIBRARY_PATH'}:
            self.assertNotIn(key, child)

    def test_malformed_or_unbounded_input_values_are_omitted(self):
        source = {'SteamAppId': '../bad', 'SteamGameId': str(1 << 64),
                  'SteamOverlayGameId': '1'*21,
                  'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD': 'sometimes',
                  'SDL_GAMECONTROLLER_IGNORE_DEVICES': 'file:/unsafe/config',
                  'SDL_GAMECONTROLLERCONFIG': 'x'*65537}
        self.assertEqual(context.preserve(source), {})
        self.assertEqual(context.preserve({'SDL_GAMECONTROLLERCONFIG': 'bad\0data'}), {})

    def test_metadata_requires_current_user_ordinary_safe_file(self):
        self.assertEqual(context.metadata_file(str(self.metadata)), self.metadata)
        linked = self.root / 'linked'; linked.symlink_to(self.metadata)
        hard = self.root / 'hard'; os.link(self.metadata, hard)
        self.assertIsNone(context.metadata_file(str(linked)))
        self.assertIsNone(context.metadata_file(str(self.metadata)))
        hard.unlink()
        self.metadata.chmod(0o666)
        self.assertIsNone(context.metadata_file(str(self.metadata)))
        self.assertIsNone(context.metadata_file(str(self.root)))
        self.assertIsNone(context.metadata_file('relative/path'))

    def test_only_private_metadata_directory_is_readonly_at_both_aliases(self):
        state = self.root / 'private-state'
        source = {context.STEAM_INFO: str(self.metadata)}
        with mock.patch.dict(os.environ, source, clear=True):
            command, namespace = native.dlss_namespace(['/authored/executable'], state)
        metadata = namespace['controller_metadata']
        target = str(state / context.PRIVATE_INFO)
        directory = str(state/context.PRIVATE_DIRECTORY)
        self.assertEqual(metadata, {'source': str(self.metadata), 'target': target,
                                    'directory': directory, 'kind': 'private-mirror-v1'})
        self.assertNotIn(str(self.metadata), command)
        bind = command.index(directory)
        private_tmp = next(i for i in range(len(command)-2)
                           if command[i:i+3] == ['--bind', str(state), '/tmp'])
        self.assertGreater(bind, private_tmp)
        self.assertEqual(command[bind-1:bind+2], ['--ro-bind', directory, directory])
        self.assertIn('/tmp/'+context.PRIVATE_DIRECTORY, command)
        result = native.private_runtime_environment(source, state, planned_namespace=True)
        self.assertEqual(result[context.STEAM_INFO], target)
        self.assertEqual(source[context.STEAM_INFO], str(self.metadata))
        mirror = native.prepare_namespace_state({'state': str(state), 'namespace': namespace},controller_refresh=True)
        self.addCleanup(mirror.close)
        self.assertEqual((state/context.PRIVATE_INFO).read_text(), 'authored SDL controller metadata fixture\n')
        self.assertEqual(self.metadata.read_text(), 'authored SDL controller metadata fixture\n')

    def test_placeholder_never_overwrites_existing_data(self):
        state = self.root / 'private-state'; (state/'runtime').mkdir(parents=True)
        (state/'runtime').chmod(0o700)
        target = state/context.PRIVATE_INFO; target.parent.mkdir(mode=0o700)
        target.write_text('existing private data'); target.chmod(0o600)
        namespace = {'controller_metadata': context.namespace_metadata({context.STEAM_INFO: str(self.metadata)},state)}
        with self.assertRaisesRegex(ValueError, 'unrecognized files'):
            native.prepare_namespace_state({'state': str(state), 'namespace': namespace})
        self.assertEqual(target.read_text(), 'existing private data')

    def test_inherited_rebased_metadata_is_retained_without_rebinding(self):
        state = self.root / 'private-state'; (state/'runtime').mkdir(parents=True)
        (state/'runtime').chmod(0o700)
        target = state/context.PRIVATE_INFO; target.parent.mkdir(mode=0o700)
        target.write_text('authored inherited metadata'); target.chmod(0o600)
        environment = {context.STEAM_INFO: str(target)}
        self.assertIsNone(context.namespace_metadata(environment, state),
                          'matching filename cannot bypass isolation on a cold launch')
        self.assertNotIn(context.STEAM_INFO, context.private_environment(environment,state,True))
        self.assertEqual(target.read_text(), 'authored inherited metadata')
        with mock.patch.object(native, 'private_tmp_alias', return_value=True):
            self.assertEqual(native.private_runtime_environment(environment, state), environment)

    def test_no_steam_context_preserves_normal_namespace(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            _, namespace = native.dlss_namespace(['/authored/executable'], self.root/'state')
        self.assertNotIn('controller_metadata', namespace)
        self.assertEqual(context.private_environment({'AUTHORED': 'value'}, self.root/'state', True), {'AUTHORED': 'value'})


@unittest.skipUnless(sys.platform == 'linux', 'Pinned SDL Steam virtual controller test')
class SteamControllerContextNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dependency_port = Path(os.environ.get('MONADO_TEST_SDL_PORT', PORT))
        wrapper = dependency_port/'.deps/bin/pkg-config-graphics'
        compiler = os.environ.get('MONADO_TEST_CC') or str(dependency_port/'.deps/bin/clang-cc')
        if not wrapper.is_file() or not Path(compiler).is_file():
            raise unittest.SkipTest('Pinned SDL3/Clang dependencies unavailable')
        marker = dependency_port/'.deps/graphics/active-sysroot.txt'
        root = Path(marker.read_text().strip())
        cls.environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                           'LD_LIBRARY_PATH': str(root/'usr/lib/x86_64-linux-gnu'),
                           'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy',
                           'SDL_JOYSTICK_HIDAPI': '0'}
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-steam-virtual-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name)/'steam-virtual'
        flags = subprocess.run([str(wrapper), '--cflags', '--libs', 'sdl3'],
                               capture_output=True, text=True, timeout=30, env=cls.environment)
        if flags.returncode: raise AssertionError(flags.stdout+flags.stderr)
        command = [compiler, '-std=c11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                   str(ROOT/'tests/native/test_controller_environment.c'),
                   *shlex.split(flags.stdout),
                   '-Wl,-rpath,'+cls.environment['LD_LIBRARY_PATH'], '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        result = subprocess.run(command, env=cls.environment, capture_output=True, text=True, timeout=120)
        if result.returncode: raise AssertionError(result.stdout+result.stderr)

    def test_actual_launcher_environment_reaches_pinned_sdl_in_child_process(self):
        baseline = subprocess.run([str(self.binary), '0'], env=self.environment,
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(baseline.returncode, 0, baseline.stdout+baseline.stderr)
        with mock.patch.dict(os.environ, {**self.environment,
                'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD': '1'}, clear=True):
            fixed = launcher.clean_environment(self.environment['LD_LIBRARY_PATH'])
        result = subprocess.run([str(self.binary), '1'], env=fixed,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


@unittest.skipUnless(sys.platform == 'linux', 'Linux native private metadata namespace')
class ControllerMetadataNamespace(unittest.TestCase):
    def test_actual_file_readonly_mount_and_inherited_child_reuse(self):
        if not native.BWRAP.is_file():
            self.skipTest('bwrap unavailable')
        if PORT.resolve().is_relative_to(Path('/tmp').resolve()):
            self.skipTest('native namespace fixture requires source outside private /tmp')
        with tempfile.TemporaryDirectory(prefix='.controller-namespace-', dir=PORT) as workspace, \
                tempfile.TemporaryDirectory(prefix='monado-authored-steam-info-') as metadata_root:
            workspace = Path(workspace).resolve()
            metadata = Path(metadata_root).resolve()/'metadata'
            metadata.write_text('Monado authored metadata, no game content\n')
            metadata.chmod(0o600)
            state = workspace/'play/private'
            target = state/context.PRIVATE_INFO
            probe = workspace/'probe.py'
            probe.write_text('''from pathlib import Path
import errno,importlib.util,os,sys
source,target,state,runner = map(Path,sys.argv[1:])
assert not source.exists(), 'host /tmp source unexpectedly visible'
expected='Monado authored metadata, no game content\\n'
for path in [target,Path('/tmp')/'steam-controller-metadata/info']:
 assert path.read_text()==expected, 'metadata alias unreadable: '+str(path)
 try:
  with path.open('wb') as stream: stream.write(b'forbidden')
 except OSError as failure: assert failure.errno in (errno.EACCES,errno.EROFS),failure
 else: raise AssertionError('metadata alias writable: '+str(path))
assert os.environ['SteamVirtualGamepadInfo']==str(target)
assert os.environ['SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD']=='1'
spec=importlib.util.spec_from_file_location('controller_inherited_fixture',runner)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert module.private_tmp_alias(state)
again=module.private_runtime_environment(dict(os.environ),state)
assert again['SteamVirtualGamepadInfo']==str(target)
print('PASS read-only metadata both aliases and inherited GUI/game namespace reuse')
''')
            source_environment = {context.STEAM_INFO: str(metadata),
                                  'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD': '1'}
            with mock.patch.dict(os.environ, source_environment, clear=True):
                command, namespace = native.dlss_namespace(
                    ['/usr/bin/python3', '-I', '-B', str(probe), str(metadata), str(target),
                     str(state), str(SCRIPTS/'run_linux.py')], state, pid_namespace=False)
                environment = native.private_runtime_environment(
                    launcher.clean_environment('/authored/private-libs'), state, planned_namespace=True)
            mirror = native.prepare_namespace_state({'state': str(state), 'namespace': namespace},controller_refresh=True)
            self.addCleanup(mirror.close)
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=20)
            if result.returncode:
                denied = ('bwrap: no permissions to create a new namespace',
                          'bwrap: creating new namespace failed: operation not permitted',
                          'bwrap: unshare user namespace: operation not permitted')
                if any(message in result.stderr.lower() for message in denied):
                    self.skipTest('host sandbox denies namespace creation: '+result.stderr.strip())
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('PASS read-only metadata both aliases', result.stdout)
            self.assertEqual(metadata.read_text(), 'Monado authored metadata, no game content\n')
            self.assertEqual(target.read_bytes(), metadata.read_bytes(), 'only private snapshot should receive metadata')


if __name__ == '__main__':
    unittest.main()
