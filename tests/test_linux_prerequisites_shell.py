"""Authored shell entry fixtures; no package, compiler, game or GUI execution."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')


@unittest.skipUnless(os.name == 'posix' and BASH, 'Linux Bash entrypoint')
class PrerequisiteEntry(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-prerequisite-shell-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'My Games' / 'Monado II'
        (self.root / 'tools').mkdir(parents=True)
        shutil.copyfile(ROOT / 'Build_Monado_II.sh', self.root / 'Build_Monado_II.sh')
        shutil.copyfile(ROOT / 'tools/linux_prerequisites.sh', self.root / 'tools/linux_prerequisites.sh')
        self.bin = self.base / 'bin'; self.bin.mkdir()
        (self.bin / 'dirname').symlink_to(shutil.which('dirname'))
        self.log = self.base / 'commands'
        self.env = {'PATH': str(self.bin), 'LANG': 'C', 'LC_ALL': 'C',
                    'SHELL_TEST_LOG': str(self.log)}
        self.input = self.root / 'game_files/exefs/authored-input'
        self.input.parent.mkdir(parents=True); self.input.write_bytes(b'AUTHORED INPUT')
        self.save = self.root / 'Monado_Linux/play/launcher/save/authored-save'
        self.save.parent.mkdir(parents=True); self.save.write_bytes(b'AUTHORED SAVE')

    def python(self, name='python3.14'):
        path = self.bin / name
        path.write_text('''#!/bin/bash
if [[ ${3:-} == -c ]]; then
    if [[ ${4:-} == *'==(3,14)'* ]]; then
        [[ $0 == */python3.14 && ${FAKE_314_AVAILABLE:-1} == 1 ]]
        result=$?
        (( result == 0 )) || exit "$result"
    fi
    printf '%s\\n' "$0"
    exit 0
fi
printf 'CALL\\0%s\\0' "$0" >> "$SHELL_TEST_LOG"
printf '%s\\0' "$@" >> "$SHELL_TEST_LOG"
case ${3:-} in
    */linux_prerequisites.py) exit "${DOCTOR_EXIT:-0}" ;;
    */build_linux_app.py) exit "${BUILD_EXIT:-0}" ;;
esac
exit 99
''')
        path.chmod(0o755)
        return path

    def run_entry(self, *args, **environment):
        # Most entry tests deliberately have an ordinary shell parent. Separate
        # actual-Python-parent tests exercise the old updater compatibility route.
        result = subprocess.run([BASH, '-c', '"$@"; result=$?; exit "$result"', 'fixture',
            BASH, str(self.root / 'Build_Monado_II.sh'), *args],
            cwd=self.base, env=dict(self.env, **environment), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(self.input.read_bytes(), b'AUTHORED INPUT')
        self.assertEqual(self.save.read_bytes(), b'AUTHORED SAVE')
        self.calls = self.log.read_bytes().split(b'\0') if self.log.exists() else []
        return result

    def test_help_needs_no_python_and_runs_no_child(self):
        result = self.run_entry('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--install-deps', result.stdout)
        self.assertIn('--plan', result.stdout)
        self.assertEqual(self.calls, [])

    def test_exact_interpreter_and_spaced_arguments_are_preserved(self):
        selected = self.python()
        reused = '/authored/My Games/earlier/xcde-linux'
        result = self.run_entry('--jobs', '3', '--reuse-game', reused,
                                '--build-id', 'authored-fixed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls, [b'CALL', os.fsencode(selected), b'-I', b'-B',
            os.fsencode(self.root / 'tools/linux_prerequisites.py'), b'--check',
            b'CALL', os.fsencode(selected), b'-I', b'-B',
            os.fsencode(self.root / 'tools/build_linux_app.py'), b'--jobs', b'3',
            b'--reuse-game', reused.encode(), b'--build-id', b'authored-fixed', b''])

    def test_install_flag_goes_only_to_doctor_and_preserves_build_features(self):
        self.python()
        result = self.run_entry('--install-deps', '--without-dlss', '--game-only', '--jobs=2')
        self.assertEqual(result.returncode, 0, result.stderr)
        split = self.calls.index(b'CALL', 1)
        self.assertIn(b'--install-deps', self.calls[:split])
        self.assertIn(b'--without-dlss', self.calls[:split])
        self.assertIn(b'--game-only', self.calls[:split])
        self.assertNotIn(b'--install-deps', self.calls[split:])
        self.assertEqual(self.calls[-4:], [b'--without-dlss', b'--game-only', b'--jobs=2', b''])

    def test_plan_with_install_flag_never_calls_doctor_or_install(self):
        self.python()
        result = self.run_entry('--install-deps', '--plan', '--jobs', '4')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.count(b'CALL'), 1)
        self.assertNotIn(os.fsencode(self.root / 'tools/linux_prerequisites.py'), self.calls)
        self.assertNotIn(b'--install-deps', self.calls)
        self.assertIn(b'--plan', self.calls)

    def test_plan_missing_python_is_read_only(self):
        result = self.run_entry('--install-deps', '--plan')
        self.assertEqual(result.returncode, 1)
        self.assertIn('CPython 3.14', result.stderr)
        self.assertIn('compilation have not started', result.stderr)
        self.assertEqual(self.calls, [])

    def test_diagnostic_interpreter_can_report_missing_build_python(self):
        selected = self.python('python3')
        result = self.run_entry(DOCTOR_EXIT='7')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.calls.count(b'CALL'), 1)
        self.assertEqual(self.calls[1], os.fsencode(selected))
        self.assertIn(os.fsencode(self.root / 'tools/linux_prerequisites.py'), self.calls)

    def test_doctor_failure_never_starts_build(self):
        self.python()
        result = self.run_entry('--install-deps', DOCTOR_EXIT='130')
        self.assertEqual(result.returncode, 130)
        self.assertEqual(self.calls.count(b'CALL'), 1)
        self.assertNotIn(os.fsencode(self.root / 'tools/build_linux_app.py'), self.calls)

    def test_build_failure_is_preserved(self):
        self.python()
        result = self.run_entry(BUILD_EXIT='17')
        self.assertEqual(result.returncode, 17)
        self.assertEqual(self.calls.count(b'CALL'), 2)

    def test_normal_missing_all_python_does_not_bootstrap(self):
        result = self.run_entry()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Missing: CPython 3.14', result.stderr)
        self.assertEqual(self.calls, [])

    def test_fake_container_env_cannot_install(self):
        result = self.run_entry('--install-deps', CONTAINER_ID='forged-example')
        self.assertEqual(result.returncode, 1)
        self.assertIn('verified supported Distrobox', result.stderr)
        self.assertEqual(self.calls, [])

    def test_invalid_arguments_never_probe_or_install(self):
        self.python()
        invalid = [('--unknown',), ('--jobs',), ('--jobs', '7'), ('--jobs=0',),
                   ('--build-id', '../../outside'), ('--reuse-game',),
                   ('--build-id', '-bad'), ('--reuse-game', '-bad'),
                   ('--reuse-game=',), ('--without-dlss', '--framegen'),
                   ('--game-only', '--reuse-game', '/authored/old')]
        for args in invalid:
            with self.subTest(args=args):
                result = self.run_entry('--install-deps', *args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(self.calls, [])

    def test_legacy_integer_spellings_keep_argparse_semantics(self):
        self.python()
        for value in ('03', '+3', '0003'):
            with self.subTest(value=value):
                if self.log.exists(): self.log.unlink()
                result = self.run_entry('--jobs', value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls[-3:], [b'--jobs', value.encode(), b''])

    def test_equals_arguments_keep_argparse_option_value_boundary(self):
        self.python()
        result = self.run_entry('--build-id=-authored-id', '--reuse-game=/authored/My Games/old', '--jobs=03')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls[-4:], [b'--build-id=-authored-id',
            b'--reuse-game=/authored/My Games/old', b'--jobs=03', b''])

    def test_noninteractive_bootstrap_refuses_before_any_package_transaction(self):
        # Exercise the real trusted-glibc and terminal guards after authored
        # context fixtures; no system namespace/manager identity is substituted.
        script = ('source "$1"; '
                  'monado_read_os() { MONADO_OS_ID=fedora; MONADO_OS_VERSION=45; }; '
                  'monado_is_distrobox() { return 0; }; monado_bootstrap_python')
        result = subprocess.run([BASH, '-c', script, 'fixture',
            str(self.root / 'tools/linux_prerequisites.sh')], env=self.env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Container transaction:', result.stderr)
        if 'interactive terminal' not in result.stderr:
            self.assertTrue('glibc' in result.stderr or 'Linux x86-64' in result.stderr, result.stderr)
        self.assertFalse(self.log.exists())

    def real_python_tools(self):
        source = '''import os,sys
with open(os.environ['SHELL_TEST_LOG'],'ab') as out:
 out.write(b'CALL\\0'+os.fsencode(sys.executable)+b'\\0')
 for arg in sys.argv:out.write(os.fsencode(arg)+b'\\0')
'''
        for name in ('linux_prerequisites.py', 'build_linux_app.py'):
            (self.root / 'tools' / name).write_text(source)

    @unittest.skipUnless(sys.version_info[:2] == (3, 14), 'Actual CPython3.14 required')
    def test_existing_port_python_survives_clean_worker_path(self):
        self.real_python_tools()
        selected = self.root / 'Monado_Linux/.venv/bin/python'
        selected.parent.mkdir(parents=True)
        selected.symlink_to(Path(sys.executable).resolve())
        result = self.run_entry('--jobs', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.count(b'CALL'), 2)
        self.assertEqual(self.calls[1], os.fsencode(Path(sys.executable).resolve()))
        self.assertNotIn(b'/proc/', b' '.join(self.calls))

    @unittest.skipUnless(sys.version_info[:2] == (3, 14), 'Actual CPython3.14 required')
    def test_old_updater_python_parent_survives_clean_worker_path(self):
        self.real_python_tools()
        # The current real CPython parent is outside this deliberately empty PATH.
        result = subprocess.run([BASH, str(self.root / 'Build_Monado_II.sh'), '--jobs', '2'],
            env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_bytes().split(b'\0')
        self.assertEqual(calls.count(b'CALL'), 2)
        self.assertEqual(calls[1], os.fsencode(Path(sys.executable).resolve()))
        self.assertNotIn(b'/proc/', b' '.join(calls))
        self.assertEqual(self.input.read_bytes(), b'AUTHORED INPUT')
        self.assertEqual(self.save.read_bytes(), b'AUTHORED SAVE')


if __name__ == '__main__':
    unittest.main()
