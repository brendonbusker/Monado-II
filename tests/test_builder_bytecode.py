"""Interpreter flags keep the sealed setup runtime free of bytecode caches.

Only authored argv and native recorder fixtures are executed; no game input,
generator invocation, gameplay or user Python cache is consumed or modified.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / 'Monado_Linux/tools/gen_all.py'


@unittest.skipUnless(GENERATOR.is_file(), 'Linux generator source is not in this source kit')
class GeneratorBytecodeFlags(unittest.TestCase):
    def test_module_child_disables_bytecode_even_with_ignore_environment(self):
        spec = importlib.util.spec_from_file_location('authored_generator_argv', GENERATOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        command = module.generator_command('/authored/venv/bin/python', '/authored source/generator.py',
            {'name': 'authored-module', 'base': '0x0'}, '/authored input/exefs', '/authored output',
            'c', '/authored source/patches.py', '/authored source/hle.txt')
        self.assertEqual(command[:5], ['/authored/venv/bin/python', '-B', '-E', '-s',
                                      '/authored source/generator.py'])
        self.assertEqual(command[5:], ['authored-module', str(Path('/authored input/exefs') / 'authored-module'),
                                      '0x0', '/authored output', '--simd', 'c', '--patches',
                                      '/authored source/patches.py', '--hle', '/authored source/hle.txt'])
        self.assertEqual(command.count('-B'), 1)


@unittest.skipUnless(sys.platform == 'linux', 'Private interpreter wrapper uses Linux /proc/self/exe')
class PrivatePythonBytecodeFlags(unittest.TestCase):
    def test_wrapper_adds_flag_before_all_user_options_and_preserves_venv_entry(self):
        compiler = os.environ.get('MONADO_TEST_CC') or shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('C compiler required for private interpreter argv fixture')
        with tempfile.TemporaryDirectory(prefix='monado-python-flags-') as directory:
            root = Path(directory).resolve() / 'private runtime with spaces'
            binary = root / 'bin'
            binary.mkdir(parents=True)
            (root / 'lib').mkdir()
            recorder = root / 'recorder.c'
            recorder.write_text('#include <stdio.h>\nint main(int argc,char **argv){'
                                'for(int i=0;i<argc;i++)puts(argv[i]);return 0;}\n')
            wrapper = binary / 'python3.14'
            real = binary / 'python3.14.real'
            environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
            for source, output in ((recorder, real), (ROOT / 'tools/builder_appimage/python_entry.c', wrapper)):
                result = subprocess.run([compiler, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                                         str(source), '-o', str(output)],
                                        env=environment, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # The entry symlink models a venv. argv[0] must remain the venv name,
            # even though /proc/self/exe resolves the persistent runtime wrapper.
            venv = root.parent / 'venv with spaces/bin'
            venv.mkdir(parents=True)
            entry = venv / 'python'
            entry.symlink_to(wrapper)
            for arguments in (['-E', '-s', '-c', 'authored code argument'],
                              ['-I', '-B', '-c', 'authored code argument']):
                result = subprocess.run([str(entry), *arguments], env=environment,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.splitlines(), [str(entry), '-B', *arguments])


if __name__ == '__main__':
    unittest.main()
