"""Issue #20: Atomic HOME aliases, strict managed paths and native startup errors.

Only authored folders/files and pre-SDL production validation are exercised.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(sys.platform == 'linux', 'Linux builder paths')
class BuilderPaths(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-atomic-paths-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / 'var/home/authored user'
        self.home.mkdir(parents=True)
        self.alias = self.root / 'home'
        self.alias.symlink_to(self.root / 'var/home', target_is_directory=True)
        self.environment = mock.patch.dict(os.environ, {'HOME': str(self.alias / self.home.name)}, clear=False)
        self.environment.start(); self.addCleanup(self.environment.stop)
        os.environ.pop('XDG_DATA_HOME', None)
        self.bootstrap = load('monado_atomic_bootstrap', ROOT / 'tools/builder_bootstrap.py')

    def test_default_home_alias_resolves_before_creating_managed_data(self):
        selected = self.bootstrap.data_directory()
        self.assertEqual(selected, self.home / '.local/share/monado-ii-builder')
        self.assertTrue(selected.is_dir())
        os.environ['HOME'] = str(self.home)
        self.assertEqual(self.bootstrap.data_directory(), selected)

    def test_xdg_base_alias_resolves_but_managed_leaf_cannot_be_a_link(self):
        os.environ['XDG_DATA_HOME'] = str(self.alias / self.home.name / 'data with spaces')
        selected = self.bootstrap.data_directory()
        self.assertEqual(selected, self.home / 'data with spaces/monado-ii-builder')
        selected.rmdir()
        other = self.root / 'elsewhere'; other.mkdir()
        selected.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.bootstrap.data_directory()
        self.assertEqual(list(other.iterdir()), [])

    def test_explicit_data_alias_stays_rejected_and_ordinary_path_unchanged(self):
        requested = self.alias / self.home.name / 'explicit data'
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.bootstrap.data_directory(requested)
        self.assertFalse((self.home / 'explicit data').exists())
        selected = self.bootstrap.data_directory(self.home / 'explicit data')
        self.assertEqual(selected, self.home / 'explicit data')

    def test_home_descendant_links_and_relative_xdg_remain_rejected(self):
        other = self.root / 'outside'; other.mkdir()
        (self.home / '.local').symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.bootstrap.data_directory()
        self.assertEqual(list(other.iterdir()), [])
        os.environ['XDG_DATA_HOME'] = 'relative-data'
        with self.assertRaisesRegex(ValueError, 'absolute'):
            self.bootstrap.data_directory()

    def test_default_output_uses_canonical_home_without_creating_it(self):
        backend = load('monado_atomic_backend', ROOT / 'tools/builder_backend.py')
        source = self.root / 'source'; source.mkdir()
        session = self.root / 'session'; session.mkdir()
        state = self.root / 'state'; state.mkdir()
        with mock.patch.object(backend.Broker, 'version', return_value='authored-fixture'):
            broker = backend.Broker(source, session, state)
        self.addCleanup(broker.close)
        self.assertEqual(broker.status['output'], str(self.home / 'Games/Monado-II'))
        self.assertFalse((self.home / 'Games').exists())

    def test_play_script_explains_reopen_routes_and_checks_the_adjacent_image(self):
        owner = self.home / 'Monado II'
        owner.mkdir()
        wrapper = owner / 'Play_Monado_II.sh'
        wrapper.write_bytes((ROOT / wrapper.name).read_bytes())
        image = owner / 'Monado-II-x86_64.AppImage'
        alias = self.alias / self.home.name / owner.name / wrapper.name
        invocation = ['bash', str(alias), '--dry-run']
        fixture = self.root / 'authored_launcher'
        fixture.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
        fixture.chmod(0o700)
        for state in ('missing', 'nonexecutable', 'symlink'):
            with self.subTest(state=state):
                if state == 'nonexecutable':
                    image.write_bytes(fixture.read_bytes())
                elif state == 'symlink':
                    image.unlink()
                    image.symlink_to(fixture)
                result = subprocess.run(invocation, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertIn('same standalone AppImage', result.stderr)
                self.assertIn('--data-dir', result.stderr)
                self.assertIn('./Build_Monado_II.sh', result.stderr)
        image.unlink()
        image.write_bytes(fixture.read_bytes())
        image.chmod(0o700)
        result = subprocess.run(invocation, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['--appimage-extract-and-run', '--dry-run'])


@unittest.skipUnless(sys.platform == 'linux', 'native Linux launcher validation')
class NativeLaunchContext(unittest.TestCase):
    def test_actual_pre_sdl_validation_identifies_each_argument(self):
        compiler = os.environ.get('MONADO_TEST_CXX')
        local = ROOT / 'Monado_Linux/.deps/bin/clang-cxx'
        if not compiler:
            compiler = str(local) if local.is_file() else shutil.which('clang++') or shutil.which('c++')
        if not compiler and os.environ.get('MONADO_TEST_CC'):
            sibling = Path(os.environ['MONADO_TEST_CC']).with_name('clang-cxx')
            if sibling.is_file():
                compiler = str(sibling)
        if not compiler:
            self.skipTest('C++ compiler unavailable')
        launcher = (ROOT / 'Monado_Linux/tools/launcher/launcher.cpp').read_text()
        host = (ROOT / 'Monado_Linux/tools/launcher/linux_host.h').read_text()
        canonical = 'static bool canonical(' + host.split('static bool canonical(', 1)[1].split('static bool beneath(', 1)[0]
        context = launcher.split('// [XCDE] LINUX-122: begin launch-context validation.', 1)[1].split(
            '// [XCDE] LINUX-122: end launch-context validation.', 1)[0]
        source = '''#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sys/stat.h>
namespace launcher_linux { static std::string project, game_project, input, game;
''' + canonical + '}\n' + context + '''
int main(int argc, char **argv) {
    if (argc == 1) return linux_launch_context(nullptr,nullptr,nullptr,nullptr,nullptr,0,5)?0:2;
    if (argc != 8) return 3;
    return linux_launch_context(argv[1],argv[2],argv[3],argv[4],argv[5],atoi(argv[6]),atoi(argv[7]))?0:2;
}
'''
        with tempfile.TemporaryDirectory(prefix='monado-native-paths-') as temporary:
            root = Path(temporary).resolve()
            fixture = root / 'fixture.cpp'; fixture.write_text(source)
            binary = root / 'fixture'
            compiled = subprocess.run([compiler, '-std=c++17', '-O1', '-UNDEBUG', str(fixture), '-o', str(binary)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            project = root / 'var/home/authored user/Monado II'; project.mkdir(parents=True)
            inputs = root / 'var/home/authored user/game_files'; inputs.mkdir()
            game = project / 'xcde-linux'; game.write_text('authored nonexecutable placeholder')
            state = root / 'new private state'
            values = [str(project), str(project), str(inputs), str(game), str(state), '0', '5']
            def run(arguments):
                return subprocess.run([str(binary), *arguments], cwd=root, capture_output=True, text=True, timeout=10)
            result = run([])
            self.assertEqual(result.returncode, 2)
            self.assertIn('--project-root', result.stderr)
            self.assertIn('same standalone builder AppImage', result.stderr)
            self.assertIn('--data-dir', result.stderr)
            self.assertIn('adjacent Monado-II-x86_64.AppImage', result.stderr)
            self.assertIn('Play_Monado_II.sh', result.stderr)
            self.assertIn('optional', result.stderr)
            result = run(values)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(state.exists())
            bad = [(0, 'relative', '--project-root'), (1, str(root / 'missing'), '--game-project-root'),
                   (2, str(game), '--input-root'), (3, str(inputs), '--game-executable'),
                   (4, 'relative state', '--state-root'), (5, '5', '--shot-tab'), (6, '0', '--shot-frame')]
            for position, value, flag in bad:
                arguments = values.copy(); arguments[position] = value
                with self.subTest(flag=flag):
                    result = run(arguments)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(flag, result.stderr)
                    self.assertFalse(state.exists())
            alias = root / 'home'; alias.symlink_to(root / 'var/home', target_is_directory=True)
            arguments = values.copy(); arguments[0] = str(alias / 'authored user/Monado II')
            result = run(arguments)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--project-root', result.stderr)
            self.assertIn(str(project), result.stderr)


if __name__ == '__main__':
    unittest.main()
