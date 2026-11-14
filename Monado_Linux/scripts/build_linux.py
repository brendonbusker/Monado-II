#!/usr/bin/env python3
"""[XCDE] LINUX-002/006: explicit native graphics build, never launches the game.

Default: compile the authored runtime/renderer only. Generated game source is
neither created nor consumed unless --generated is supplied. Fresh ignored output
is mandatory; successful outputs are atomically renamed and receipts retain every
command, input hash and failure. --keep-going is a diagnostic compile audit only.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
_runtime_spec = importlib.util.spec_from_file_location('monado_build_runtime_check', Path(__file__).with_name('linux_runtime_check.py'))
runtime_check = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime_check)
# [XCDE] LINUX-072: compile the opt-in reward and combat/fall adapters into the
# actual native game recipe; a launcher preference alone is not an implementation.
RUNTIME = '''loader dispatch kernel ipc fnprof platform/linux platform/linux_state_guard services/fs services/romfs_virtual
services/am services/acc services/time services/hid_set services/kbicons services/misc services/audio services/hwopus
hle/heaps hle/pl hle/vi hle/nvn_boot hle/fibers hle/fiber_context_linux hle/input hle/party hle/bindings hle/movie
hle/framepace hle/title_exit hle/desktop_exit_caption hle/system_exit hle/expanded_saves hle/expanded_save_scan
hle/quickstep_slot hle/quickstep_save hle/quickstep_native hle/quickstep_picker hle/quickstep_stats hle/quickstep_stats_ui hle/quickstep_ui_memory hle/cheats_rewards hle/cheats_combat host/stubs host/settings_ini host/stubs_gfx host/xcde_aspect host/gamelib_static host/main_boot
diag/diag diag/sampler diag/watchdog diag/crashdump paths'''.split()
NVN = '''astc cmdbuf formats maxwell/translate objects output_scale smaa_data tegra texpatch
vulkan/device vulkan/exec vulkan/host_import vulkan/driver_heap vulkan/radv_dcc_compat vulkan/precompile vulkan/shaders vulkan/textures vulkan/temporal'''.split()
CPP = ['third_party/imgui/' + n + '.cpp' for n in ('imgui', 'imgui_draw', 'imgui_tables', 'imgui_widgets')]
CPP += ['third_party/imgui/backends/imgui_impl_vulkan.cpp', 'runtime/nvn/vulkan/imgui_glue.cpp',
        'runtime/ui/menu_vk.cpp', 'runtime/nvn/vulkan/dlss.cpp', 'runtime/nvn/vulkan/vma.cpp']
PACKAGES = ['sdl3', 'vulkan', 'shaderc', 'libavcodec', 'libavformat', 'libavutil', 'libswscale', 'libswresample', 'opus']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def command_failure(record, limit=6000):
    """[XCDE] LINUX-066: bounded actual diagnostics, without following log links."""
    parts = [f"{record['name']} failed (exit {record.get('exit', 'unknown')})."]
    if record.get('spawn_error'):
        parts.append(str(record['spawn_error']))
    for field in ('stderr', 'stdout'):
        value = record.get(field)
        if not value:
            continue
        path = Path(value)
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    continue
                stream.seek(max(0, info.st_size - limit))
                raw = stream.read(limit)
            text = raw.decode('utf-8', errors='replace').strip()
            if text:
                text = ''.join(character if character in '\n\t' or ord(character) >= 32 and ord(character) != 127 else '?' for character in text)
                parts.append('Diagnostic log: ' + str(path))
                if info.st_size > limit:
                    parts.append('(last ' + str(limit) + ' bytes; full output remains in the log)')
                parts.append(text)
                break
        except (OSError, ValueError):
            continue
    return '\n'.join(parts)


def check_correctness_macros(macros):
    # Zig's optimized C driver implies NDEBUG unless explicitly undone. Keep
    # inherited assertions and strict floating-point behavior in this port.
    if re.search(r'^#define (?:NDEBUG|__FAST_MATH__)(?:\s|$)', macros, re.MULTILINE):
        raise RuntimeError('compiler disables assertions or enables fast math')


def authored_sources(with_dlss=False, with_framegen=False):
    sources = [ROOT / ('runtime/' + n + '.c') for n in RUNTIME] + [ROOT / ('runtime/nvn/' + n + '.c') for n in NVN] + [ROOT / n for n in CPP]
    if with_dlss:
        sources.append(ROOT / 'runtime/nvn/vulkan/dlss_linux.cpp')
    if with_framegen:
        sources.append(ROOT / 'runtime/nvn/vulkan/framegen_linux.cpp')
    return sources


def generated_sources(path):
    target = path.absolute()
    if target.is_symlink() or target.resolve() != target or not any(target.is_relative_to(ROOT / d) for d in ('generated', 'build', 'runs')):
        raise ValueError('generated source must be a real directory below this Linux port generated/, build/ or runs/')
    result = []
    for module in ('main', 'sdk'):
        directory = target / module
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f'missing real generated module directory: {directory}')
        files = sorted(directory.glob('*.c'))
        if not any(p.name == module + '_table.c' for p in files) or len(files) < 2:
            raise ValueError(f'{module}: generated chunks and function table are required')
        for source in files:
            if source.is_symlink() or not re.fullmatch(module + r'_(?:[0-9]+|table)\.c', source.name):
                raise ValueError(f'unexpected generated source: {source}')
        result += files
    return result


def fresh_output(requested):
    if requested:
        target = requested.absolute()
        if target.is_symlink() or target.resolve() != target or not any(target.is_relative_to(ROOT / d) for d in ('build', 'runs')):
            raise ValueError('output must be a fresh, non-symlink directory below Monado_Linux/build or runs')
        target.mkdir(parents=True, exist_ok=False)
        return target
    parent = ROOT / 'build'
    if parent.is_symlink():
        raise ValueError('build directory cannot be a symlink')
    parent.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='linux.', dir=parent))


def source_snapshot():
    # Bind compiler inputs broadly, including conditional local headers. System
    # dependency identities are separate; this is not a full transitive SDK lock.
    names = [ROOT / 'scripts/build_linux.py', ROOT / 'scripts/linux_runtime_check.py',
             ROOT / 'scripts/linux_runtime_graph.py', ROOT / 'graphics-deps-linux.lock.json',
             ROOT / 'requirements-linux.lock', ROOT / 'tools/gen_smaa_inc.py',
             ROOT / 'dlss-linux.lock.json', ROOT / 'scripts/setup_linux_dlss.py',
             ROOT / 'fsr-linux.lock.json', ROOT / 'scripts/setup_linux_fsr.py']
    for dirname in ('runtime', 'third_party'):
        names += [p for p in (ROOT / dirname).rglob('*') if p.is_file() and p.suffix in ('.c', '.cpp', '.h', '.hpp', '.inc', '.hlsl')]
    icon = ROOT / 'local_assets/monado-icon.png'
    if icon.is_symlink() or (icon.exists() and not icon.is_file()):
        raise ValueError('local game icon must be an ordinary file')
    if icon.exists():
        names.append(icon)
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(names)}


class Builder:
    def __init__(self, output, args):
        self.output, self.args = output, args
        self.lock = threading.Lock()
        self.failed = threading.Event()
        self.env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                    'TMPDIR': str(output / 'tmp')}
        for name in ('tmp', 'obj', 'logs', 'inc'):
            (output / name).mkdir()
        self.cc = ROOT / '.deps/bin/clang-cc'
        self.cxx = ROOT / '.deps/bin/clang-cxx'
        self.sysroot = Path((ROOT / '.deps/graphics/active-sysroot.txt').read_text().strip()).resolve()
        self.libdir = self.sysroot / 'usr/lib/x86_64-linux-gnu'
        self.runtime_policy, _ = runtime_check.load_policy(ROOT, self.sysroot)
        self.library_path = runtime_check.library_path(self.sysroot, self.runtime_policy)
        self.receipt = {'schema': 1, 'scope': ('native graphics executable build; never launched' if args.generated else
                                  'native authored graphics runtime objects; no game launch'),
                        'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running',
                        'cwd': str(ROOT), 'output': str(output), 'argv': sys.argv, 'jobs': args.jobs,
                        'host': list(platform.uname()), 'commands': [], 'objects': {},
                        'sources_before': source_snapshot(), 'generated': {}, 'errors': [],
                        'dependencies': {'sysroot': str(self.sysroot), 'compiler_wrappers': {
                            str(p.relative_to(ROOT)): digest(p) for p in (self.cc, self.cxx)}}}
        self.save()

    def save(self):
        temporary = self.output / 'receipt.json.tmp'
        temporary.write_text(json.dumps(self.receipt, indent=2) + '\n')
        temporary.replace(self.output / 'receipt.json')

    def run(self, name, argv, *, timeout=180):
        out = self.output / 'logs' / (name + '.stdout.log')
        err = self.output / 'logs' / (name + '.stderr.log')
        record = {'name': name, 'argv': list(map(str, argv)), 'cwd': str(ROOT), 'env': self.env,
                  'stdout': str(out), 'stderr': str(err), 'timeout_seconds': timeout}
        start = time.monotonic()
        with self.lock:
            self.receipt['commands'].append(record)
            self.save()
        with out.open('wb') as stdout, err.open('wb') as stderr:
            try:
                proc = subprocess.Popen(record['argv'], cwd=ROOT, env=self.env, stdout=stdout, stderr=stderr,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
            except OSError as failure:
                record.update(exit=127, spawn_error=str(failure), seconds=time.monotonic() - start)
                with self.lock:
                    self.failed.set()
                    self.save()
                print(command_failure(record), flush=True)
                return record, ''
            record['pid'] = proc.pid
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                record['timed_out'] = True
            except BaseException:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise
        record.update(exit=proc.returncode, seconds=time.monotonic() - start)
        with self.lock:
            if proc.returncode:
                self.failed.set()
            self.save()
        print(f'{name}: {"PASS" if proc.returncode == 0 else "FAIL"} ({record["seconds"]:.2f}s)', flush=True)
        if proc.returncode:
            print(command_failure(record), flush=True)
        return record, out.read_text(errors='replace')

    def setup(self):
        for name, compiler in (('cc-version', self.cc), ('cxx-version', self.cxx)):
            record, _ = self.run(name, [compiler, '--version'])
            if record['exit']:
                raise RuntimeError(f'{name} failed')
        pkg = ROOT / '.deps/bin/pkg-config-graphics'
        record, flags = self.run('pkg-cflags', [pkg, '--cflags', *PACKAGES])
        if record['exit']:
            raise RuntimeError('graphics development flags unavailable')
        self.cflags = shlex.split(flags)
        record, flags = self.run('pkg-libs', [pkg, '--libs', *PACKAGES])
        if record['exit']:
            raise RuntimeError('graphics development libraries unavailable')
        self.libs = shlex.split(flags)
        self.libs += ['-lz', '-lm', '-ldl', '-pthread', '-Xlinker', '-rpath', '-Xlinker', self.library_path, '-rdynamic']
        sdl = (self.libdir / 'libSDL3.so').resolve(strict=True)
        self.receipt['dependencies']['linked_libraries'] = {
            'sdl3': {'path': str(sdl), 'sha256': digest(sdl)}}
        record, checked = self.run('runtime-dependency-preflight', [sys.executable, '-B',
            ROOT / 'scripts/linux_runtime_check.py', '--probe', '--port', ROOT,
            '--output', self.output / 'runtime-probe'], timeout=180)
        if record['exit']:
            raise RuntimeError('Linux runtime dependencies are not loadable; see runtime-dependency-preflight stderr')
        self.receipt['runtime_preflight'] = json.loads(checked)
        self.flags = ['-O1', '-UNDEBUG', '-march=x86_64_v2', '-ffp-contract=off', '-fno-strict-aliasing',
                      '-fvisibility=hidden', '-pthread', '-Iruntime', '-Iruntime/nvn', '-Ithird_party',
                      '-Iruntime/nvn/vulkan', '-Ithird_party/imgui', '-Ithird_party/imgui/backends',
                      '-Ithird_party/streamline/include', '-Ithird_party/smaa/Textures', '-I' + str(self.output / 'inc'),
                      '-DGAMELIB_ID="linux-dev"', *self.cflags]
        # [XCDE] LINUX-013: explicit passive developer trace, absent in normal builds.
        self.receipt['foley_trace'] = self.args.foley_trace
        if self.args.foley_trace:
            self.flags += ['-DXCDE_FOLEY_TRACE=1']
        self.receipt['dlss_enabled'] = bool(getattr(self.args, 'dlss', False))
        self.receipt['precompile_protocol'] = 1  # [XCDE] LINUX-018 checked supervisor/backend contract
        if self.receipt['dlss_enabled']:
            self.setup_dlss()
        self.receipt['framegen_enabled'] = bool(getattr(self.args, 'framegen', False))
        if self.receipt['framegen_enabled']:
            self.setup_framegen()
        for name, compiler, language in (('cc-predefines', self.cc, 'c'), ('cxx-predefines', self.cxx, 'c++')):
            record, macros = self.run(name, [compiler, *self.flags, '-dM', '-E', '-x', language, '/dev/null'])
            if record['exit']:
                raise RuntimeError(f'{name} failed')
            check_correctness_macros(macros)
        self.receipt['assertions_enabled'] = True
        record, _ = self.run('smaa-include', [sys.executable, '-B', ROOT / 'tools/gen_smaa_inc.py',
                                            ROOT / 'third_party/smaa/SMAA.hlsl', self.output / 'inc/smaa_hlsl.inc'])
        if record['exit']:
            raise RuntimeError('authored SMAA include generation failed')
        self.receipt['smaa_include_sha256'] = digest(self.output / 'inc/smaa_hlsl.inc')
        self.save()

    def copy_runtime_resource(self, source, filename, expected):
        """[XCDE] LINUX-017: unchanged, receipted companion bytes; never execute."""
        if source.is_symlink() or not source.is_file() or digest(source) != expected:
            raise ValueError('runtime resource differs from its verified source: ' + str(source))
        if Path(filename).name != filename:
            raise ValueError('runtime resource must be a companion filename')
        target = self.output / filename
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        if digest(source) != expected or digest(target) != expected:
            raise RuntimeError('runtime resource changed while copying: ' + filename)
        self.receipt.setdefault('runtime_resources', {})[filename] = {
            'path': str(target), 'source': str(source), 'sha256': expected,
            'bytes': target.stat().st_size}

    def setup_dlss(self):
        """Optional offline SDK verification and isolated vendor-loader module."""
        spec = importlib.util.spec_from_file_location('monado_setup_linux_dlss', ROOT / 'scripts/setup_linux_dlss.py')
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        lock_path = ROOT / 'dlss-linux.lock.json'
        lock_bytes = lock_path.read_bytes()
        sdk = setup.setup(lock_bytes, offline=True)  # no implicit network/download
        sdk_lock = json.loads(lock_bytes)
        locked_hashes = {entry['path']: entry['sha256'] for entry in sdk_lock['files']}
        archive = sdk / 'lib/Linux_x86_64/libnvsdk_ngx.a'
        runtime = sdk / 'lib/Linux_x86_64/rel/libnvidia-ngx-dlss.so.310.9.1'
        gnu_runtime = runtime_check.discover_gnu_cxx()
        self.receipt['dependencies']['dlss'] = {
            'lock_sha256': hashlib.sha256(lock_bytes).hexdigest(),
            'sdk': str(sdk), 'sdk_receipt_sha256': digest(sdk / '.monado-dlss.json'),
            'files': {str(sdk / entry['path']): entry['sha256'] for entry in sdk_lock['files']},
            'gnu_cxx_runtime': {'path': str(gnu_runtime), 'sha256': digest(gnu_runtime)},
            'scope': 'local development only; NVIDIA license retained; no vendor code run by build'}
        self.flags += ['-DXCDE_LINUX_DLSS=1', '-I' + str(sdk / 'include')]
        export_map = self.output / 'inc/ngx-exports.map'
        export_map.write_text('{ global: monado_ngx_api; local: *; };\n')
        partial = self.output / 'libmonado-ngx.so.partial'
        final = self.output / 'libmonado-ngx.so'
        # Compile declarations with Clang's GNU ABI, without Zig's libc++ link.
        # The proprietary archive alone uses GNU libstdc++; no STL types cross
        # the bridge. A version script keeps its constructors/symbols private.
        record, _ = self.run('dlss-loader-module', [self.cc, *self.flags, '-x', 'c++',
            '-std=c++17', '-shared', '-fPIC', '-nostdlib++',
            ROOT / 'runtime/nvn/vulkan/dlss_ngx_loader.cpp', '-x', 'none', archive,
            gnu_runtime, '-ldl', '-Xlinker', '--version-script', '-Xlinker', str(export_map),
            '-Wl,--no-undefined', '-o', partial])
        if record['exit']:
            raise RuntimeError('isolated NVIDIA loader module build failed')
        record, symbols = self.run('dlss-loader-exports', ['/usr/bin/nm', '-D', '--defined-only', partial])
        if record['exit'] or [line.split()[-1] for line in symbols.splitlines() if line.strip()] != ['monado_ngx_api']:
            raise RuntimeError('NVIDIA loader module must export only its authored ABI getter')
        record, dynamic = self.run('dlss-loader-dynamic', ['/usr/bin/readelf', '-dW', partial])
        needed = re.findall(r'\(NEEDED\).*\[(.*?)\]', dynamic)
        if record['exit'] or 'libstdc++.so.6' not in needed or any(name.startswith('libc++') for name in needed):
            raise RuntimeError('NVIDIA loader module has an unexpected C++ runtime dependency')
        partial.replace(final)
        self.receipt.setdefault('runtime_resources', {})[final.name] = {
            'path': str(final), 'sha256': digest(final), 'bytes': final.stat().st_size,
            'scope': 'authored ABI bridge plus separately licensed NVIDIA static SDK loader'}
        self.receipt['dlss_loader'] = {'export_map_sha256': digest(export_map), 'needed': needed,
            'exported_symbols': ['monado_ngx_api'], 'vendor_code_executed': False}
        self.copy_runtime_resource(runtime, runtime.name,
                                   locked_hashes['lib/Linux_x86_64/rel/' + runtime.name])
        self.copy_runtime_resource(sdk / 'LICENSE.txt', 'NVIDIA-DLSS-LICENSE.txt', locked_hashes['LICENSE.txt'])
        icon = ROOT / 'local_assets/monado-icon.png'
        if icon.exists() or icon.is_symlink():
            if icon.is_symlink() or not icon.is_file() or not 0 < icon.stat().st_size <= 8 * 1024 * 1024:
                raise ValueError('local game icon must be an ordinary PNG of at most 8 MiB')
            data = icon.read_bytes()
            if len(data) < 33 or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
                raise ValueError('local game icon must have a PNG IHDR')
            width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16777216):
                raise ValueError('local game icon dimensions are unreasonable')
            expected = self.receipt['sources_before'].get('local_assets/monado-icon.png')
            self.copy_runtime_resource(icon, 'icon.png', expected)
        self.save()

    def setup_framegen(self):
        # [XCDE] LINUX-020: offline verification only; dependency setup is a separate explicit build.
        import importlib.util
        spec = importlib.util.spec_from_file_location('monado_setup_linux_fsr', ROOT / 'scripts/setup_linux_fsr.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dependency = module.verify_existing()
        self.flags += ['-DXCDE_LINUX_FRAMEGEN=1']
        self.receipt['dependencies']['framegen'] = dependency
        self.copy_runtime_resource(Path(dependency['library_path']), 'libmonado-fidelityfx.so', dependency['library_sha256'])
        self.copy_runtime_resource(Path(dependency['license_path']), 'FidelityFX-MIT.txt', dependency['license_sha256'])
        self.save()

    def check_input(self):
        # Always retain the inherited DE version checker; never generate/extract
        # packages or write state into this selected shared input directory.
        selected = ROOT.parent / 'game_files'
        record, _ = self.run('check-game-input', [ROOT / '.venv/bin/python', '-B',
                                                ROOT / 'tools/extract/check_dump.py', selected], timeout=120)
        if record['exit']:
            raise RuntimeError('selected extracted DE 2.0.0 input failed its checker')
        self.receipt['input'] = {'path': str(selected.resolve()), 'exefs': {
            p.name: digest(p) for p in sorted((selected / 'exefs').iterdir()) if p.is_file()}}
        self.save()

    def link(self):
        temporary = self.output / 'xcde-linux.partial'
        objects = [self.receipt['objects'][name]['path'] for name in sorted(self.receipt['objects'])]
        record, _ = self.run('link-graphics', [self.cxx, '-march=x86_64_v2', *objects,
                                             *self.libs, '-o', temporary], timeout=300)
        if record['exit']:
            self.receipt['errors'].append('graphics link failed; see link-graphics stderr')
            self.save()
            return None
        with temporary.open('rb') as stream:
            header = stream.read(64)
        if len(header) < 64 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 62:
            raise RuntimeError('linked output is not a native little-endian x86-64 ELF')
        companions = [Path(meta['path']) for name, meta in self.receipt.get('runtime_resources', {}).items()
                      if '.so' in name]
        self.receipt['runtime_validation'] = runtime_check.check_artifacts(
            [temporary, *companions], self.sysroot, self.runtime_policy)
        self.save()
        return temporary


    def compile(self, source):
        if self.failed.is_set() and not self.args.keep_going:
            return None
        relative = str(source.relative_to(ROOT))
        name = relative.replace('/', '_')
        obj = self.output / 'obj' / (name + '.o')
        temporary = obj.with_suffix('.o.partial')
        before = digest(source)
        extra = ['-std=c++17'] if source.suffix == '.cpp' else []
        if relative == 'runtime/host/main_boot.c':
            extra += ['-DXCDE_GFX']
        if relative == 'runtime/kernel.c':
            # [XCDE] LINUX-070: XCDE_GFX is entry-file-only. Keep the native
            # heap hook explicit without changing standalone kernel fixtures.
            extra += ['-DXCDE_LINUX_RADV_HEAP=1']
        record, _ = self.run(name, [self.cxx if source.suffix == '.cpp' else self.cc,
                                    *self.flags, *extra, '-c', source, '-o', temporary])
        after = digest(source)
        with self.lock:
            if record['exit'] or before != after:
                if before != after:
                    record['source_changed'] = True
                self.failed.set()
                self.receipt['errors'].append(relative)
                self.save()
                return None
            temporary.replace(obj)
            self.receipt['objects'][relative] = {'path': str(obj), 'source_sha256': after, 'object_sha256': digest(obj)}
            self.save()
        return obj

    def finish(self, error=None):
        after = source_snapshot()
        self.receipt['sources_after'] = after
        for name, expected in self.receipt['generated'].items():
            try:
                unchanged = digest(ROOT / name) == expected
            except OSError:
                unchanged = False
            if not unchanged:
                self.receipt['errors'].append('generated input changed during build: ' + name)
        changed = self.receipt['sources_before'] != after
        self.receipt['sources_changed_during_build'] = changed
        if changed:
            self.receipt['errors'].append('authored source/header snapshot changed during build; rebuild stable sources')
        # Bind companion binaries/artwork and external link inputs at completion,
        # including object-only DLSS audits. A receipt never blesses changed bytes.
        resources = list(self.receipt.get('runtime_resources', {}).values())
        resources += list(self.receipt.get('dependencies', {}).get('linked_libraries', {}).values())
        dlss = self.receipt.get('dependencies', {}).get('dlss', {})
        if dlss:
            resources += [dlss['gnu_cxx_runtime']]
            resources += [{'path': str(Path(dlss['sdk']) / '.monado-dlss.json'),
                           'sha256': dlss['sdk_receipt_sha256']}]
            resources += [{'path': path, 'sha256': expected} for path, expected in dlss['files'].items()]
        for resource in resources:
            path = Path(resource['path'])
            try:
                unchanged = not path.is_symlink() and path.is_file() and digest(path) == resource['sha256']
            except OSError:
                unchanged = False
            if not unchanged:
                self.receipt['errors'].append('runtime resource/dependency changed during build: ' + str(path))
        if error:
            self.receipt['errors'].append(str(error))
        self.receipt['status'] = 'failed' if self.failed.is_set() or self.receipt['errors'] else 'passed'
        self.receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        self.save()
        return self.receipt['status'] == 'passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='fresh output below this Linux port runs/ or build/')
    parser.add_argument('--jobs', type=int, choices=range(1, 7), default=4)
    parser.add_argument('--only', nargs='+', help='exact authored source paths relative to this Linux source root')
    parser.add_argument('--generated', type=Path, help='existing main/sdk generated C directory; validates selected game input, compiles and links full graphics ELF')
    parser.add_argument('--keep-going', action='store_true', help='compile audit: retain all failures; never accepts a failed build')
    parser.add_argument('--foley-trace', action='store_true', help='bounded local diagnostic for grass/footstep investigation; no gameplay correction')
    parser.add_argument('--dlss', action='store_true', help='offline-verify pinned NVIDIA SDK and build native SR/DLAA provider plus private loader module; never executes vendor code')
    parser.add_argument('--framegen', action='store_true', help='offline-verify the native FidelityFX dependency and include optional interpolation alongside DLSS')
    args = parser.parse_args()
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        parser.error('native Linux x86-64 required')
    if args.generated and args.only:
        parser.error('--only cannot be combined with a complete link')
    if args.framegen and not args.dlss:
        parser.error('initial Linux frame generation requires --dlss')
    available = authored_sources(with_dlss=args.dlss, with_framegen=args.framegen)
    generated = generated_sources(args.generated) if args.generated else []
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {str(p.relative_to(ROOT)) for p in available}
        if unknown:
            parser.error('unknown sources: ' + ', '.join(sorted(unknown)))
        available = [p for p in available if str(p.relative_to(ROOT)) in wanted]
    output = fresh_output(args.output)
    print(f'Linux build output: {output}', flush=True)
    builder = Builder(output, args)
    error, executable = None, None
    try:
        builder.setup()
        if generated:
            builder.check_input()
            builder.receipt['generated'] = {str(p.relative_to(ROOT)): digest(p) for p in generated}
            builder.save()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = {pool.submit(builder.compile, source): source for source in [*available, *generated]}
            for completed, future in enumerate(concurrent.futures.as_completed(pending), 1):
                result = future.result()
                # A frontend can report actual completed compilation units;
                # it must never substitute an estimated timer for build work.
                print(f'[compile {completed}/{len(pending)}] '
                      f'{"done" if result is not None else "failed/skipped"}', flush=True)
        if generated and not builder.failed.is_set():
            executable = builder.link()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as failure:
        error = failure
    passed = builder.finish(error)
    if passed and executable:
        final = output / 'xcde-linux'
        executable.replace(final)
        builder.receipt['executable'] = {
            'path': str(final), 'sha256': digest(final)}
        builder.save()
    scope = 'graphics ELF linked; not run' if passed and executable else 'runtime object build; no accepted executable'
    print(f'{"PASS" if passed else "FAIL"}: {scope}\nReceipt: {output / "receipt.json"}', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
