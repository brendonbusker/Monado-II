"""Authored ELF dependency/load-only regressions; no game input or UI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
spec = importlib.util.spec_from_file_location('authored_runtime_check', PORT / 'scripts/linux_runtime_check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@unittest.skipUnless(sys.platform == 'linux', 'native Linux ELF loader checks')
class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        compiler = PORT / '.deps/bin/clang-cc'
        self.cc = str(compiler) if compiler.is_file() else shutil.which('clang')
        if not self.cc:
            self.skipTest('Clang is required for authored ELF fixtures')
        tmp = tempfile.TemporaryDirectory(prefix='monado runtime, with spaces ')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.port = self.base / 'Monado_Linux'
        self.sysroot = self.port / '.deps/graphics/sysroots/authored'
        self.libdir = self.sysroot / 'usr/lib/x86_64-linux-gnu'
        self.libdir.mkdir(parents=True)
        self.child = self.libdir / 'libmonado_fixture_child.so.3'
        self.binary = self.base / 'authored-root'
        self.constructed = self.base / 'constructor-must-not-run'
        self.compile_child()
        source = self.base / 'main.c'
        source.write_text('extern int monado_child(void); int main(void){return monado_child();}\n')
        self.compile([source, self.child, '-Xlinker', '-rpath', '-Xlinker', str(self.libdir), '-o', self.binary])
        names = set()
        for artifact in (self.binary, self.child):
            names.update(check.graph_module().inspect_elf(artifact)['needed'])
        names.discard(self.child.name)
        self.policy = {'schema': 1, 'root_sonames': [self.child.name],
            'library_dirs': ['usr/lib/x86_64-linux-gnu'],
            'owned_sonames': {self.child.name: {'path': 'usr/lib/x86_64-linux-gnu/' + self.child.name, 'package': 'authored'}},
            'host_sonames': {name: {'reason': 'Authored fixture native host interface', 'category': 'platform'} for name in names}}
        self.write_marker()

    def compile(self, arguments):
        result = subprocess.run([self.cc, *map(str, arguments)], capture_output=True, text=True,
                                timeout=60, env=check.clean_environment())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def compile_child(self, *, destination=None, soname=None, version='MONADO_CHILD_1', value=7):
        destination = destination or self.child
        soname = soname or destination.name
        source = self.base / ('child-' + str(value) + '.c')
        source.write_text('#include <stdio.h>\n'
            '__attribute__((constructor)) static void guard(void){FILE*f=fopen(' + json.dumps(str(self.constructed)) + ',"w");if(f)fclose(f);}\n'
            'int monado_child(void){return ' + str(value) + ';}\n')
        versions = self.base / ('versions-' + str(value) + '.map')
        versions.write_text(version + ' { global: monado_child; local: *; };\n')
        self.compile(['-shared', '-fPIC', source, '-Wl,-soname,' + soname,
                      '-Xlinker', '--version-script', '-Xlinker', str(versions), '-o', destination])
        return destination

    def write_marker(self):
        files = {self.child.name: {'path': 'usr/lib/x86_64-linux-gnu/' + self.child.name,
            'bytes': self.child.stat().st_size, 'sha256': check.digest(self.child)}}
        self.marker = {'lock_sha256': 'a' * 64,
            'runtime_policy': self.policy, 'runtime_policy_sha256': check.policy_digest(self.policy),
            'owned_runtime_files': files}
        (self.sysroot / '.monado-deps.json').write_text(json.dumps(self.marker))
        return files

    def test_valid_private_transitive_passes_without_running_constructor(self):
        result = check.check_artifacts([self.binary], self.sysroot, self.policy)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['policy'], 'closed-owned-with-explicit-host-boundaries')
        self.assertEqual(result['runtime_policy_sha256'], check.policy_digest(self.policy))
        self.assertFalse(self.constructed.exists())

    def test_only_wrong_major_available_is_not_an_abi_repair(self):
        wrong = self.libdir / 'libmonado_fixture_child.so.4'
        self.compile_child(destination=wrong, value=8)
        self.child.unlink()
        with mock.patch.dict(os.environ, {'LD_LIBRARY_PATH': str(self.libdir)}):
            with self.assertRaisesRegex(check.RuntimeDependencyError, 'owned_missing.*libmonado_fixture_child.so.3'):
                check.check_artifacts([self.binary], self.sysroot, self.policy)
        self.assertFalse(self.constructed.exists())

    def test_wrong_major_alias_and_wrong_version_are_rejected(self):
        self.compile_child(soname='libmonado_fixture_child.so.4', value=9)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'SONAME differs'):
            check.check_artifacts([self.binary], self.sysroot, self.policy)
        self.compile_child(version='MONADO_CHILD_2', value=10)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'version_missing'):
            check.check_artifacts([self.binary], self.sysroot, self.policy)
        self.assertFalse(self.constructed.exists())

    def test_ambient_loader_overrides_cannot_change_the_check(self):
        with mock.patch.dict(os.environ, {'LD_PRELOAD': '/missing-preload.so',
                'LD_AUDIT': '/missing-auditor.so', 'LD_LIBRARY_PATH': '/wrong/runtime',
                'GLIBC_TUNABLES': 'glibc.cpu.hwcaps=-AVX2'}):
            result = check.check_artifacts([self.binary], self.sysroot, self.policy)
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(self.constructed.exists())

    def test_changed_owned_bytes_cannot_be_blessed_as_current(self):
        self.compile_child(value=11)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'changed after setup'):
            check.check_artifacts([self.binary], self.sysroot, self.policy)
        self.assertFalse(self.constructed.exists())

    def test_legacy_receipt_is_loader_only_and_missing_child_still_fails(self):
        result = check.check_artifacts([self.binary], self.sysroot)
        self.assertEqual(result['policy'], 'legacy-loader-list-only')
        self.child.unlink()
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'loader check failed.*'):
            check.check_artifacts([self.binary], self.sysroot)
        self.assertFalse(self.constructed.exists())

    def test_runtime_policy_survives_new_source_lock_but_receipt_hash_is_strict(self):
        self.port.mkdir(exist_ok=True)
        (self.port / 'graphics-deps-linux.lock.json').write_text('{"newer":"source"}')
        policy, tag = check.load_policy(self.port, self.sysroot, expected_lock='a' * 64,
                                       expected_policy=check.policy_digest(self.policy))
        self.assertEqual(policy, self.policy)
        self.assertEqual(tag, 'a' * 64)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'differs from its successful receipt'):
            check.load_policy(self.port, self.sysroot, expected_lock='a' * 64, expected_policy='b' * 64)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'does not match the dependency lock'):
            check.load_policy(self.port, self.sysroot)

    def test_new_runtime_receipt_cannot_silently_downgrade_to_legacy_checks(self):
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'lacks its successful policy/file validation'):
            check.require_receipt_validation({'status': 'passed'}, self.marker)
        proof = {'schema': 1, 'status': 'passed', 'policy': 'closed-owned-with-explicit-host-boundaries',
                 'runtime_policy_sha256': check.policy_digest(self.policy),
                 'owned_runtime_files_sha256': check.policy_digest(self.marker['owned_runtime_files'])}
        self.assertEqual(check.require_receipt_validation({'runtime_validation': proof}, self.marker), proof)
        self.assertEqual(check.require_receipt_validation({'status': 'passed'}, {'lock_sha256': 'legacy'}), {})

    def test_changed_file_inventory_cannot_replace_the_receipted_inventory(self):
        expected = check.policy_digest(self.marker['owned_runtime_files'])
        self.compile_child(value=12)
        self.write_marker()
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'inventory differs from the selected build'):
            check.check_artifacts([self.binary], self.sysroot, self.policy, expected_files=expected)

    def test_non_debian_gnu_runtime_path_and_exact_abi_checks(self):
        other = self.base / 'arch-style/usr/lib'
        other.mkdir(parents=True)
        gnu = other / 'libstdc++.so.6'
        source, versions = self.base / 'gnu.c', self.base / 'gnu.map'
        source.write_text('int monado_gnu(void){return 1;}\n')
        versions.write_text('GLIBCXX_3.4.32 { global: monado_gnu; }; CXXABI_1.3.9 { };\n')
        self.compile(['-shared', '-fPIC', source, '-Wl,-soname,libstdc++.so.6',
                      '-Xlinker', '--version-script', '-Xlinker', str(versions), '-o', gnu])
        self.assertEqual(check.discover_gnu_cxx(host_paths={'libstdc++.so.6': gnu}), gnu)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'missing required ABI'):
            check.discover_gnu_cxx(host_paths={'libstdc++.so.6': gnu}, required_versions={'GLIBCXX_99'})
        self.compile(['-shared', '-fPIC', source, '-Wl,-soname,libstdc++.so.7', '-o', gnu])
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'SONAME libstdc'):
            check.discover_gnu_cxx(host_paths={'libstdc++.so.6': gnu})
        raw = bytearray(gnu.read_bytes()); raw[18:20] = (183).to_bytes(2, 'little'); gnu.write_bytes(raw)
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'not little-endian Linux x86-64'):
            check.discover_gnu_cxx(host_paths={'libstdc++.so.6': gnu})

    def test_output_library_cannot_masquerade_as_native_host_boundary(self):
        host = self.base / self.child.name
        host.write_bytes(self.child.read_bytes())
        source = self.base / 'host-main.c'
        source.write_text('extern int monado_child(void); int main(void){return monado_child();}\n')
        self.compile([source, host, '-Xlinker', '-rpath', '-Xlinker', str(self.base), '-o', self.binary])
        policy = dict(self.policy, owned_sonames={}, host_sonames={**self.policy['host_sonames'],
            self.child.name: {'reason': 'Authored fake native host', 'category': 'platform'}})
        hosts = check.host_library_paths()
        hosts[self.child.name] = host
        with self.assertRaisesRegex(check.RuntimeDependencyError, 'host interface cannot come from private runtime/output'):
            check.check_artifacts([self.binary], self.sysroot, policy, host_paths=hosts)
        self.assertFalse(self.constructed.exists())

    def test_game_link_cannot_pass_when_a_transitive_disappears_after_link(self):
        module_spec = importlib.util.spec_from_file_location('authored_builder_runtime_guard', PORT / 'scripts/build_linux.py')
        build = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(build)
        output = self.base / 'authored-component-build'; output.mkdir()
        source, obj = self.base / 'late-main.c', self.base / 'late-main.o'
        source.write_text('extern int monado_child(void); int main(void){return monado_child();}\n')
        self.compile(['-c', source, '-o', obj])
        builder = build.Builder.__new__(build.Builder)
        builder.output, builder.cxx, builder.sysroot, builder.runtime_policy = output, self.cc, self.sysroot, self.policy
        builder.libs = [str(self.child), '-Xlinker', '-rpath', '-Xlinker', str(self.libdir)]
        builder.receipt = {'objects': {'authored': {'path': str(obj)}}, 'runtime_resources': {}}
        builder.save = lambda: None
        def linked(_name, argv, **_kwargs):
            result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=60, env=check.clean_environment())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.child.unlink()  # reproduce a post-link host/dependency change
            return {'exit': result.returncode}, result.stdout
        builder.run = linked
        with self.assertRaisesRegex(ValueError, 'owned_missing'):
            builder.link()
        self.assertFalse((output / 'xcde-linux').exists())
        self.assertFalse(self.constructed.exists())

    def test_precompile_runtime_failure_precedes_cache_or_worker_writes(self):
        scripts = str(PORT / 'scripts')
        old = list(sys.path); sys.path.insert(0, scripts)
        try:
            module_spec = importlib.util.spec_from_file_location('authored_precompile_runtime_guard', PORT / 'scripts/precompile_linux.py')
            precompile = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(precompile)
        finally:
            sys.path[:] = old
        state = self.port / 'play/never-created'
        launch = {'argv': [str(self.binary)], 'state': str(state)}
        import contextlib, io
        with mock.patch.object(precompile, 'ROOT', self.port), \
                mock.patch.object(precompile, 'prepare', return_value=launch), \
                mock.patch.object(precompile.run_linux, 'validate_runtime', side_effect=ValueError('authored missing libbluray.so.3')), \
                mock.patch.object(precompile, 'supervise') as worker, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            precompile.main(['--executable', str(self.binary), '--state-root', str(state)])
        self.assertEqual(stopped.exception.code, 1)
        worker.assert_not_called()
        self.assertFalse(state.exists())

    def test_probe_owns_every_declared_root_without_running_it(self):
        lock = self.port / 'graphics-deps-linux.lock.json'
        lock.write_text(json.dumps({'schema': 1, 'runtime': self.policy}))
        self.marker['lock_sha256'] = check.digest(lock)
        (self.sysroot / '.monado-deps.json').write_text(json.dumps(self.marker))
        active = self.port / '.deps/graphics/active-sysroot.txt'
        active.write_text(str(self.sysroot))
        compiler = self.port / '.deps/bin/clang-cc'
        compiler.parent.mkdir(parents=True)
        # Model the pinned Zig wrapper's CPU spelling even when CI supplies an
        # ordinary Clang executable. Keep the same x86-64-v2 baseline, not a
        # dropped CPU option, and leave the production probe unchanged.
        import shlex
        version = subprocess.run([self.cc, '--version'], capture_output=True, text=True,
                                 timeout=60, env=check.clean_environment())
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        cpu = '-march=x86_64_v2' if 'ziglang' in version.stdout else '-march=x86-64-v2'
        adapter = self.base / 'probe-compiler.py'
        adapter.write_text('import os,sys\n'
            'args=[' + repr(cpu) + ' if arg=="-march=x86_64_v2" else arg for arg in sys.argv[1:]]\n'
            'os.execv(' + repr(self.cc) + ',[' + repr(self.cc) + ',*args])\n')
        compiler.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' +
                            shlex.quote(str(adapter)) + ' "$@"\n')
        compiler.chmod(0o755)
        output = self.port / 'authored-probe'
        result = check.probe(self.port, output=output)
        self.assertIn('-march=x86_64_v2', result['compile_argv'])
        needed = check.graph_module().inspect_elf(output / 'runtime-probe')['needed']
        self.assertTrue(set(self.policy['root_sonames']).issubset(needed))
        self.assertIn(self.child.name, check.graph_module().inspect_elf(self.child)['soname'])
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(self.constructed.exists())


if __name__ == '__main__':
    unittest.main()
