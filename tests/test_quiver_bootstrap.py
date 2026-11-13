"""Desktop setup uses authored command fixtures, never real terminals or games."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'App_Monado_II.sh'


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Linux shell entrypoint')
class QuiverBootstrap(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-quiver-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.kit = self.base / 'My Games' / 'Monado II'
        self.kit.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.kit / SCRIPT.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        # Isolate terminal/dialog discovery from installed desktop applications.
        for name in ('dirname',):
            (self.bin / name).symlink_to(shutil.which(name))
        self.log = self.base / 'calls'
        self.environment = {'PATH': str(self.bin), 'DISPLAY': ':authored-fixture',
            'BOOTSTRAP_TEST_LOG': str(self.log), 'LC_ALL': 'C'}
        self.write(self.kit / 'Build_Monado_II.sh',
                   'printf "build\\0%s\\0" "$PWD" >> "$BOOTSTRAP_TEST_LOG"\nexit "${BUILD_EXIT:-0}"\n')
        self.write(self.kit / 'Play_Monado_II.sh',
                   'printf "play\\0" >> "$BOOTSTRAP_TEST_LOG"\nexit "${PLAY_EXIT:-0}"\n')
        self.input = self.kit / 'game_files/exefs/authored-input'
        self.input.parent.mkdir(parents=True)
        self.input.write_bytes(b'authored-input-preserve')
        self.save = self.kit / 'Monado_Linux/play/launcher/save/authored-save'
        self.save.parent.mkdir(parents=True)
        self.save.write_bytes(b'authored-save-preserve')

    def write(self, path, body):
        path.write_text('#!/bin/bash\n' + body)
        path.chmod(0o755)

    def terminal(self, name):
        # All arguments are recorded individually; execute only authored scripts.
        self.write(self.bin / name,
            'printf "terminal\\0%s\\0" "$0" >> "$BOOTSTRAP_TEST_LOG"\n'
            'printf "%s\\0" "$@" >> "$BOOTSTRAP_TEST_LOG"\n'
            'while [[ $# -gt 0 && $1 != -e && $1 != -- ]]; do shift; done\n'
            'shift\nexec "$@"\n')

    def run_script(self, *args, **environment):
        env = dict(self.environment, **environment)
        result = subprocess.run([shutil.which('bash'), str(self.kit / SCRIPT.name), *args],
            cwd=self.base, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        self.assertEqual(self.input.read_bytes(), b'authored-input-preserve')
        self.assertEqual(self.save.read_bytes(), b'authored-save-preserve')
        self.calls = self.log.read_bytes().split(b'\0') if self.log.exists() else []
        return result

    def test_existing_image_opens_only_checked_play(self):
        (self.kit / 'Monado-II-x86_64.AppImage').write_bytes(b'authored-image-fixture')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls, [b'play', b''])

    def test_existing_link_is_diagnosed_by_play_not_rebuilt(self):
        (self.kit / 'Monado-II-x86_64.AppImage').symlink_to('missing-image')
        result = self.run_script(PLAY_EXIT='7', DISPLAY='')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.calls, [b'play', b''])
        self.assertIn('./Play_Monado_II.sh', result.stderr)

    def test_each_terminal_preserves_spaced_paths_and_build_then_launcher(self):
        for name, prefix in (('x-terminal-emulator', ['-e']),
                             ('konsole', ['--nofork', '-e']),
                             ('gnome-terminal', ['--wait', '--']), ('xterm', ['-e'])):
            with self.subTest(terminal=name):
                if self.log.exists():
                    self.log.unlink()
                self.terminal(name)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls[:2], [b'terminal', os.fsencode(self.bin / name)])
                self.assertEqual(self.calls[2:2+len(prefix)], [s.encode() for s in prefix])
                self.assertIn(os.fsencode(self.kit / SCRIPT.name), self.calls)
                self.assertIn(b'--terminal-setup', self.calls)
                self.assertEqual(self.calls[-4:], [b'build', os.fsencode(self.kit), b'play', b''])
                (self.bin / name).unlink()

    def test_build_failure_and_cancellation_never_start_launcher(self):
        self.terminal('xterm')
        for code in ('1', '130', '143'):
            with self.subTest(code=code):
                if self.log.exists():
                    self.log.unlink()
                result = self.run_script(BUILD_EXIT=code)
                self.assertEqual(result.returncode, int(code))
                self.assertNotIn(b'play', self.calls)
                self.assertIn('Setup stopped (exit '+code+')', result.stdout)

    def test_failed_launcher_preserves_exit_code(self):
        (self.kit / 'Monado-II-x86_64.AppImage').write_bytes(b'authored-fixture')
        result = self.run_script(PLAY_EXIT='9', DISPLAY='')
        self.assertEqual(result.returncode, 9)
        self.assertIn('exit 9', result.stderr)

    def test_no_terminal_has_actionable_error_and_no_build(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn('./Build_Monado_II.sh', result.stderr)
        self.assertIn('game_files', result.stderr)
        self.assertEqual(self.calls, [])

    def test_terminal_start_failure_is_reported_and_no_build_runs(self):
        self.write(self.bin / 'xterm', 'exit 23\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 23)
        self.assertIn('setup did not complete (exit 23)', result.stderr)
        self.assertEqual(self.calls, [])

    def test_missing_terminal_uses_existing_kdialog_without_running_setup(self):
        self.write(self.bin / 'kdialog', 'printf "dialog\\0%s\\0" "$@" >> "$BOOTSTRAP_TEST_LOG"\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls[0], b'dialog')
        self.assertNotIn(b'build', self.calls)

    def test_missing_terminal_uses_existing_zenity_without_running_setup(self):
        self.write(self.bin / 'zenity', 'printf "dialog\\0%s\\0" "$@" >> "$BOOTSTRAP_TEST_LOG"\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls[0], b'dialog')
        self.assertIn(b'--error', self.calls)
        self.assertNotIn(b'build', self.calls)

    def test_unknown_arguments_do_not_start_anything(self):
        result = self.run_script('--unsupported', DISPLAY='')
        self.assertEqual(result.returncode, 64)
        self.assertIn('Usage:', result.stderr)
        self.assertEqual(self.calls, [])

    def test_headless_launch_reports_manual_command_without_opening_terminal(self):
        self.terminal('xterm')
        result = self.run_script(DISPLAY='', WAYLAND_DISPLAY='')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls, [])


class QuiverObservedSelection(unittest.TestCase):
    def test_canonical_setup_names_pass_observed_asset_filter(self):
        # Quiver assets.ts, blob379551113024f1de14f3f8d2398479dd3afe4b60:
        # auxiliary word/extension filter and accepted .zip/.tar.gz formats.
        auxiliary = re.compile(r'\.(json|sha\d*|md5|sig|asc|minisig|pdb|txt)$|'
            r'(^|[._-])(checksums?|sha\d*sums?|source|src|debug|symbols)([._-]|$)', re.I)
        for name in ('monado-ii-0.1.5-linux-setup.tar.gz',
                     'monado-ii-windows-original-implementation-setup.zip'):
            self.assertIsNone(auxiliary.search(name))
            self.assertRegex(name, r'\.(zip|tar\.gz)$')
        for name in ('monado-ii-0.1.5-linux-source.tar.gz', 'SHA256SUMS'):
            self.assertIsNotNone(auxiliary.search(name))

    def test_bootstrap_sorts_before_other_root_shell_entrypoints(self):
        # Quiver install.rs find_executable sorts by depth then lower-case name.
        scripts = [p for p in ROOT.iterdir() if p.is_file() and p.suffix == '.sh']
        self.assertEqual(sorted(scripts, key=lambda p: p.name.lower())[0].name, SCRIPT.name)


if __name__ == '__main__':
    unittest.main()
