"""Authored prerequisite/repair cases; no package installation or game input."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monado_linux_prerequisites', ROOT / 'tools/linux_prerequisites.py')
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class Terminal(io.StringIO):
    def isatty(self):
        return True


FEDORA = {'ID': 'fedora', 'VERSION_ID': '45', 'PRETTY_NAME': 'Fedora Linux 45'}
BOX = {'kind': 'distrobox', 'name': 'authored-box', 'distrobox_confirmed': True}
NATIVE = {'kind': 'native', 'name': None, 'distrobox_confirmed': False}


def completed(stdout='', code=0):
    return subprocess.CompletedProcess([], code, stdout, '')


def report(*, ready=False, supported=True):
    return {'schema': 1, 'mode': 'check', 'monado_version': '0.authored',
        'platform': 'linux', 'architecture': 'x86_64', 'distribution': dict(FEDORA),
        'context': dict(BOX), 'build_path': doctor.BUILD_PATH, 'minimum_glibc': '2.43',
        'glibc': '2.44', 'tools': {}, 'host_interfaces': [], 'host_providers': {},
        'packages': [] if ready else ['dpkg'], 'read_only': True,
        'issues': [] if ready else [{'kind': 'tool', 'name': 'dpkg-deb',
            'message': 'Missing dpkg-deb.', 'blocks_installation': False, 'package': 'dpkg'}],
        'notes': [], 'compatible': ready, 'installation_supported': supported,
        'status': 'passed' if ready else 'missing-prerequisites',
        'package_family': 'fedora', 'instructions': []}


class PrerequisiteData(unittest.TestCase):
    def test_os_release_is_data_not_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'os-release'
            marker = Path(temp) / 'must-not-exist'
            p.write_text('ID=fedora\nVERSION_ID="45"\nID_LIKE="fedora rhel"\n'
                'PRETTY_NAME="$(touch ' + str(marker) + ')"\n'
                'IGNORED=other\nID=$(bad)\n')
            result = doctor.os_release(p)
            self.assertEqual(result['ID'], 'fedora')
            self.assertEqual(result['VERSION_ID'], '45')
            self.assertEqual(result['ID_LIKE'], 'fedora rhel')
            self.assertIn('$(touch ', result['PRETTY_NAME'])
            self.assertNotIn('IGNORED', result)
            self.assertFalse(marker.exists())

    def test_environment_flag_alone_does_not_authorize_installation(self):
        self.assertEqual(doctor.detect_container({'CONTAINER_ID': 'fake'}, markers=[], helper='/missing')['kind'], 'native')

    def test_container_marker_alone_is_not_distrobox(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'containerenv'; marker.write_text('authored marker')
            value = doctor.detect_container({'CONTAINER_ID': 'fake'}, markers=[marker], helper='/missing')
            self.assertEqual(value['kind'], 'container')
            self.assertFalse(value['distrobox_confirmed'])

    def test_combined_distrobox_evidence_and_safe_name(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'containerenv'; marker.write_text('authored marker')
            helper = Path(temp) / 'helper'; helper.write_text('never executed'); helper.chmod(0o755)
            self.assertTrue(doctor.detect_container({'CONTAINER_ID': 'box-45'}, markers=[marker], helper=helper)['distrobox_confirmed'])
            self.assertFalse(doctor.detect_container({'CONTAINER_ID': 'box;touch /bad'}, markers=[marker], helper=helper)['distrobox_confirmed'])

    def test_fixed_tool_path_ignores_inherited_path(self):
        with mock.patch.object(doctor.shutil, 'which', return_value=None) as which:
            self.assertIsNone(doctor.system_tool('dpkg-deb'))
        which.assert_called_once_with('dpkg-deb', path='/usr/bin:/bin')

    def test_python_probe_verifies_venv_without_requiring_ensurepip(self):
        # Use the host's absolute path spelling, including a drive on Windows CI.
        selected = str(Path('/authored/python3.14').absolute())
        with mock.patch.object(doctor.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(doctor.sys, 'executable', selected), \
                mock.patch.object(doctor, 'run_readonly', return_value=completed('3.14.4\n')) as operation:
            self.assertEqual(doctor.find_python314(), selected)
        self.assertIn('venv', operation.call_args.args[0][-1])
        self.assertNotIn('ensurepip', operation.call_args.args[0][-1])

    def test_python_without_venv_is_not_ready(self):
        with mock.patch.object(doctor.sys, 'version_info', (3, 14, 4)), \
                mock.patch.object(doctor, 'run_readonly', return_value=completed(code=1)):
            self.assertIsNone(doctor.find_python314())

    @unittest.skipUnless(os.name == 'posix', 'Unix executable permissions')
    def test_forwarding_executable_is_not_a_trusted_manager(self):
        with tempfile.TemporaryDirectory() as temp:
            forwarding = Path(temp) / 'distrobox-host-exec'
            forwarding.write_text('never executed'); forwarding.chmod(0o755)
            link = Path(temp) / 'dnf5'; link.symlink_to(forwarding)
            self.assertIsNone(doctor.ordinary_executable(link, directory=temp))

    def test_audited_first_use_requirements_are_exact_not_allowed_boundary(self):
        lock = json.loads((ROOT / 'Monado_Linux/graphics-deps-linux.lock.json').read_text())
        names = doctor.required_host_interfaces(ROOT, lock)
        self.assertEqual(len(names), 18)
        self.assertIn('libasound.so.2', names)
        self.assertNotIn('libGL.so.1', names)
        self.assertIn('libGL.so.1', lock['runtime']['host_sonames'])

    def test_unknown_lock_does_not_require_every_allowed_interface(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); port = root / 'Monado_Linux'; port.mkdir()
            lock = {'runtime': {'host_sonames': {'libunused.so.1': {}}}}
            (port / 'graphics-deps-linux.lock.json').write_text(json.dumps(lock))
            self.assertIsNone(doctor.required_host_interfaces(root, lock))

    def test_receipted_actual_host_closure_can_support_a_new_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); port = root / 'Monado_Linux'; port.mkdir()
            lock = {'runtime': {'host_sonames': {'libused.so.1': {}, 'libunused.so.1': {}}}}
            raw = json.dumps(lock).encode(); (port / 'graphics-deps-linux.lock.json').write_bytes(raw)
            sysroot = port / '.deps/graphics/sysroots/authored'; sysroot.mkdir(parents=True)
            (port / '.deps/graphics/active-sysroot.txt').write_text(str(sysroot))
            marker = {'lock_sha256': hashlib.sha256(raw).hexdigest(), 'required_host_interfaces': ['libused.so.1']}
            (sysroot / '.monado-deps.json').write_text(json.dumps(marker))
            self.assertEqual(doctor.required_host_interfaces(root, lock), ['libused.so.1'])
            marker['required_host_interfaces'] = ['libunknown.so.1']
            (sysroot / '.monado-deps.json').write_text(json.dumps(marker))
            self.assertIsNone(doctor.required_host_interfaces(root, lock))

    def test_stale_marker_or_outside_sysroot_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); port = root / 'Monado_Linux'; port.mkdir()
            lock = {'runtime': {'host_sonames': {'libused.so.1': {}}}}
            (port / 'graphics-deps-linux.lock.json').write_text(json.dumps(lock))
            (port / '.deps/graphics').mkdir(parents=True)
            (port / '.deps/graphics/active-sysroot.txt').write_text('/usr/lib')
            self.assertIsNone(doctor.required_host_interfaces(root, lock))


class EnvironmentInspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        port = self.root / 'Monado_Linux'; port.mkdir()
        self.lock = {'runtime': {'minimum_glibc': '2.43', 'host_sonames': {
            'libasound.so.2': {'category': 'native-session'},
            'libunused.so.1': {'category': 'gpu-interface'}}}}
        (port / 'graphics-deps-linux.lock.json').write_text(json.dumps(self.lock))
        (self.root / 'update-version.json').write_text('{"version":"0.authored"}')
        self.library = self.root / 'authored-provider'; self.library.write_bytes(b'not executed')
        self.enter(mock.patch.object(doctor, 'os_release', return_value=dict(FEDORA)))
        self.enter(mock.patch.object(doctor, 'detect_container', return_value=dict(BOX)))
        self.enter(mock.patch.object(doctor.sys, 'platform', 'linux'))
        self.enter(mock.patch.object(doctor.platform, 'machine', return_value='x86_64'))
        self.enter(mock.patch.object(doctor, 'find_python314', return_value='/usr/bin/python3.14'))
        self.enter(mock.patch.object(doctor, 'system_tool', side_effect=lambda name, path=None: '/usr/bin/' + name))
        self.enter(mock.patch.object(doctor, 'required_host_interfaces', return_value=['libasound.so.2']))
        self.enter(mock.patch.object(doctor, 'library_paths', side_effect=lambda names: {name: self.library for name in names}))
        self.runner = self.enter(mock.patch.object(doctor, 'run_readonly', side_effect=self.run_readonly))

    def enter(self, patch):
        value = patch.start(); self.addCleanup(patch.stop); return value

    def run_readonly(self, argv, **kwargs):
        if argv[-1] == 'GNU_LIBC_VERSION':
            return completed('glibc 2.44\n')
        return completed('Version definition section:\n Name: GLIBCXX_3.4.32\n Name: CXXABI_1.3.9\nVersion needs section:\n')

    def test_ready_environment_is_read_only_and_reports_version_context(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = doctor.inspect_environment(self.root)
        self.assertTrue(result['compatible'])
        self.assertEqual(result['monado_version'], '0.authored')
        self.assertEqual(result['context']['kind'], 'distrobox')
        self.assertTrue(result['read_only'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_multiple_missing_tools_and_clients_are_aggregated_to_exact_packages(self):
        with mock.patch.object(doctor, 'find_python314', return_value=None), \
                mock.patch.object(doctor, 'system_tool', side_effect=lambda name, path=None: None if name in ('dpkg-deb', 'mksquashfs', 'unsquashfs') else '/usr/bin/' + name), \
                mock.patch.object(doctor, 'library_paths', return_value={'libstdc++.so.6': self.library}):
            result = doctor.inspect_environment(self.root)
        self.assertEqual(result['packages'], ['alsa-lib', 'dpkg', 'python3.14', 'squashfs-tools'])
        self.assertEqual(len(result['issues']), 5)

    def test_old_glibc_explains_incompatibility_before_package_repair(self):
        with mock.patch.object(doctor, 'run_readonly', side_effect=lambda argv, **kw: completed('glibc 2.41\n') if argv[-1] == 'GNU_LIBC_VERSION' else self.run_readonly(argv)):
            result = doctor.inspect_environment(self.root)
        self.assertFalse(result['compatible'])
        self.assertFalse(result['installation_supported'])
        self.assertTrue(any(item['name'] == 'glibc' and item['blocks_installation'] for item in result['issues']))
        self.assertIn('does not repair', doctor.format_report(result))

    def test_game_only_and_without_dlss_do_not_require_unneeded_tools(self):
        checked = []
        with mock.patch.object(doctor, 'system_tool', side_effect=lambda name, path=None: checked.append(name) or '/usr/bin/' + name):
            result = doctor.inspect_environment(self.root, without_dlss=True, game_only=True)
        self.assertTrue(result['compatible'])
        self.assertFalse({'nm', 'bwrap', 'mksquashfs', 'unsquashfs'} & set(checked))

    def test_version_requirements_cannot_be_satisfied_by_elf_needs(self):
        def run(argv, **kwargs):
            if argv[-1] == 'GNU_LIBC_VERSION':
                return completed('glibc 2.44\n')
            return completed('Version definition section:\n Name: GLIBCXX_3.4.30\nVersion needs section:\n Name: GLIBCXX_3.4.32\n Name: CXXABI_1.3.9\n')
        with mock.patch.object(doctor, 'run_readonly', side_effect=run):
            result = doctor.inspect_environment(self.root)
        self.assertTrue(any(item['name'] == 'libstdc++.so.6' and item['kind'] == 'abi' for item in result['issues']))

    def test_actual_gnu_requirement_is_checked_in_dlss_free_build(self):
        def run(argv, **kwargs):
            if argv[-1] == 'GNU_LIBC_VERSION':
                return completed('glibc 2.44\n')
            return completed('Version definition section:\n Name: GLIBCXX_3.4.30\n')
        with mock.patch.object(doctor, 'required_host_interfaces', return_value=['libstdc++.so.6']), \
                mock.patch.object(doctor, 'run_readonly', side_effect=run):
            result = doctor.inspect_environment(self.root, without_dlss=True)
        self.assertFalse(result['compatible'])
        self.assertTrue(any(item['name'] == 'libstdc++.so.6' and item['kind'] == 'abi' for item in result['issues']))

    def test_ubuntu_python_failure_includes_separate_venv_package(self):
        with mock.patch.object(doctor, 'os_release', return_value={'ID': 'ubuntu', 'VERSION_ID': '26.04'}), \
                mock.patch.object(doctor, 'find_python314', return_value=None):
            result = doctor.inspect_environment(self.root)
        self.assertEqual(result['packages'], ['python3.14', 'python3.14-venv'])

    def test_arch_missing_python_does_not_invent_a_rolling_package_provider(self):
        with mock.patch.object(doctor, 'os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(doctor, 'find_python314', return_value=None):
            result = doctor.inspect_environment(self.root)
        self.assertEqual(result['packages'], [])
        self.assertFalse(result['installation_supported'])
        self.assertNotIn('pacman -S', '\n'.join(result['instructions']))

    def test_bazzite_native_gets_layering_and_reboot_instructions(self):
        with mock.patch.object(doctor, 'os_release', return_value={'ID': 'bazzite', 'ID_LIKE': 'fedora', 'VERSION_ID': '45'}), \
                mock.patch.object(doctor, 'detect_container', return_value=dict(NATIVE)), \
                mock.patch.object(doctor, 'system_tool', side_effect=lambda name, path=None: None if name == 'dpkg-deb' else '/usr/bin/' + name):
            result = doctor.inspect_environment(self.root)
        self.assertFalse(result['installation_supported'])
        self.assertIn('rpm-ostree install dpkg', '\n'.join(result['instructions']))
        self.assertIn('Reboot', '\n'.join(result['instructions']))

    def test_steam_os_native_gets_container_guidance_without_unlock_commands(self):
        with mock.patch.object(doctor, 'os_release', return_value={'ID': 'steamos', 'ID_LIKE': 'arch'}), \
                mock.patch.object(doctor, 'detect_container', return_value=dict(NATIVE)), \
                mock.patch.object(doctor, 'system_tool', side_effect=lambda name, path=None: None if name == 'dpkg-deb' else '/usr/bin/' + name):
            result = doctor.inspect_environment(self.root)
        text = '\n'.join(result['instructions'])
        self.assertIn('Distrobox', text)
        self.assertNotIn('pacman', text)
        self.assertNotIn('steamos-readonly', text)

    def test_unknown_distribution_never_receives_guessed_package_installs(self):
        with mock.patch.object(doctor, 'os_release', return_value={'ID': 'authored-unknown'}), \
                mock.patch.object(doctor, 'find_python314', return_value=None):
            result = doctor.inspect_environment(self.root)
        self.assertFalse(result['installation_supported'])
        self.assertEqual(result['packages'], [])
        self.assertIn('no package mapping', '\n'.join(result['instructions']))


class ExplicitRepair(unittest.TestCase):
    def setUp(self):
        self.output = Terminal(); self.input = Terminal()
        self.patches = [mock.patch.object(doctor.sys, 'stdin', self.input),
            mock.patch.object(doctor.sys, 'stdout', self.output),
            mock.patch.object(doctor.os, 'geteuid', return_value=1000, create=True),
            mock.patch.object(doctor, 'os_release', return_value=dict(FEDORA)),
            mock.patch.object(doctor, 'detect_container', return_value=dict(BOX)),
            mock.patch.object(doctor, 'admin_tool', side_effect=lambda name: name)]
        for patch in self.patches:
            patch.start(); self.addCleanup(patch.stop)

    def test_explicit_transaction_uses_only_reviewed_container_command(self):
        operation = mock.Mock(return_value=completed())
        ready = report(ready=True)
        result = doctor.install_dependencies(report(), inspector=lambda: ready, runner=operation)
        argv = operation.call_args.args[0]
        self.assertEqual(argv, ['/usr/bin/sudo', '--', '/usr/bin/dnf5', '--setopt=install_weak_deps=False', 'install', 'dpkg'])
        self.assertNotIn('-y', argv)
        self.assertNotIn('LD_LIBRARY_PATH', operation.call_args.kwargs['env'])
        self.assertEqual(result['installed_packages'], ['dpkg'])
        self.assertFalse(result['read_only'])

    def test_complete_environment_never_invokes_a_package_manager(self):
        operation = mock.Mock(side_effect=AssertionError('package manager invoked'))
        value = report(ready=True)
        self.assertIs(doctor.install_dependencies(value, runner=operation), value)

    def test_native_or_unsupported_context_is_refused(self):
        operation = mock.Mock(side_effect=AssertionError('package manager invoked'))
        with self.assertRaisesRegex(ValueError, 'confirmed Fedora 45'):
            doctor.install_dependencies(report(supported=False), runner=operation)

    def test_noninteractive_updater_cannot_install(self):
        operation = mock.Mock(side_effect=AssertionError('package manager invoked'))
        with mock.patch.object(doctor.sys, 'stdin', io.StringIO()), self.assertRaisesRegex(ValueError, 'Background/update'):
            doctor.install_dependencies(report(), runner=operation)

    def test_running_entire_build_as_root_is_refused(self):
        with mock.patch.object(doctor.os, 'geteuid', return_value=0), self.assertRaisesRegex(ValueError, 'ordinary container user'):
            doctor.install_dependencies(report(), runner=mock.Mock(side_effect=AssertionError('invoked')))

    def test_changed_or_fake_context_is_checked_again_before_sudo(self):
        with mock.patch.object(doctor, 'detect_container', return_value=dict(NATIVE)), self.assertRaisesRegex(ValueError, 'identity changed'):
            doctor.install_dependencies(report(), runner=mock.Mock(side_effect=AssertionError('invoked')))

    def test_unsupported_abi_never_attempts_a_distribution_upgrade(self):
        value = report(); value['issues'][0]['blocks_installation'] = True
        with self.assertRaisesRegex(ValueError, 'base runtime'):
            doctor.install_dependencies(value, runner=mock.Mock(side_effect=AssertionError('invoked')))

    def test_unmapped_or_injected_package_is_refused(self):
        value = report(); value['packages'] = ['dpkg; touch /bad']
        with self.assertRaisesRegex(ValueError, 'unreviewed package'):
            doctor.install_dependencies(value, runner=mock.Mock(side_effect=AssertionError('invoked')))
        value = report(); value['issues'][0]['package'] = None
        with self.assertRaisesRegex(ValueError, 'reviewed package mapping'):
            doctor.install_dependencies(value, runner=mock.Mock(side_effect=AssertionError('invoked')))

    def test_missing_or_forwarded_admin_tools_are_refused(self):
        with mock.patch.object(doctor, 'admin_tool', return_value=None), self.assertRaisesRegex(ValueError, '/usr/bin/dnf5'):
            doctor.install_dependencies(report(), runner=mock.Mock(side_effect=AssertionError('invoked')))

    def test_cancel_or_offline_failure_stops_without_building(self):
        for code in (1, 130):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, 'installation stopped'):
                doctor.install_dependencies(report(), runner=lambda *a, **kw: completed(code=code))

    def test_install_success_still_requires_real_prerequisite_recheck(self):
        with self.assertRaisesRegex(ValueError, 'still incomplete'):
            doctor.install_dependencies(report(), inspector=lambda: report(), runner=lambda *a, **kw: completed())


class CommandLine(unittest.TestCase):
    def test_default_and_json_checks_do_not_repair(self):
        with mock.patch.object(doctor, 'inspect_environment', return_value=report()), \
                mock.patch.object(doctor, 'install_dependencies', side_effect=AssertionError('repair')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor.main(['--json']), 1)
        self.assertTrue(json.loads(output.getvalue())['read_only'])

    def test_json_install_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            doctor.main(['--json', '--install-deps'])
        self.assertEqual(error.exception.code, 2)

    def test_feature_flags_reach_inspection(self):
        with mock.patch.object(doctor, 'inspect_environment', return_value=report(ready=True)) as inspect, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(['--check', '--without-dlss', '--game-only']), 0)
        inspect.assert_called_once_with(without_dlss=True, game_only=True)


if __name__ == '__main__':
    unittest.main()
