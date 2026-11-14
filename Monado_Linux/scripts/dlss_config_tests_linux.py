#!/usr/bin/env python3
"""[XCDE] LINUX-017: actual DLSS runtime/launcher configuration and output-scaling checks; no game, GPU or visible UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shlex
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ('scripts/dlss_config_tests_linux.py', 'tests/native/test_dlss_config_linux.c',
           'tests/native/test_launcher_settings_linux.c', 'tests/native/test_dlss_launcher_config_linux.cpp',
           'runtime/host/settings_ini.c', 'runtime/hle/bindings.c', 'runtime/settings.h',
           'runtime/nvn/output_scale.c', 'runtime/nvn/output_scale.h', 'runtime/ui/graphics_options.h',
           'runtime/host/xcde_aspect.c', 'runtime/host/xcde_aspect.h', # [XCDE] LINUX-089
           'tools/launcher/launcher.cpp', 'tools/launcher/linux_host.h', 'tools/launcher/theme.h',
           *('third_party/imgui/' + p + '.cpp' for p in ('imgui','imgui_draw','imgui_tables','imgui_widgets')))

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--roundoff-baseline-ref', help='optional local Git revision: compile its actual output_scale.c as negative roundoff control')
    parser.add_argument('--framegen', action='store_true', help='also verify the compiled native frame-generation settings policy')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64': parser.error('Linux x86-64 required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parent = ROOT / 'runs'
    if parent.is_symlink(): parser.error('runs must not be a symlink')
    parent.mkdir(exist_ok=True)
    if args.output:
        out = args.output.absolute()
        if out != out.resolve() or not out.is_relative_to(parent) or out.exists(): parser.error('fresh non-symlink output under runs required')
        out.mkdir(parents=True)
    else: out = Path(tempfile.mkdtemp(prefix='linux-dlss-config.', dir=parent))
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TMPDIR': str(out)}
    cc = ROOT / '.deps/bin/clang-cc'
    sysroot = Path((ROOT / '.deps/graphics/active-sysroot.txt').read_text().strip()).resolve()
    receipt = {'scope': 'actual DLSS config/serialization/option values/output scale and headless ImGui handler injection; no GPU/game/SDL window', 'status': 'running', 'cwd': str(ROOT),
               'host': list(platform.uname()), 'compiler': str(cc), 'compiler_sha256': digest(cc), 'sysroot': str(sysroot),
               'sources_before': {p: digest(ROOT / p) for p in SOURCES}, 'commands': []}
    def save(): (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    def run(name, argv, cwd=ROOT, expected_failure=False):
        argv = list(map(str, argv))
        row = {'name': name, 'argv': argv, 'cwd': str(cwd), 'env': env, 'timeout_seconds': 60, 'expected_failure': expected_failure}
        receipt['commands'].append(row); save()
        start = time.monotonic()
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        row['pid'] = p.pid; save()
        try: output, _ = p.communicate(timeout=60)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(p.pid, signal.SIGKILL); output, _ = p.communicate(timeout=5)
            row['timed_out_or_interrupted'] = True
        row.update(exit=p.returncode, seconds=time.monotonic() - start)
        log = out / (name + '.log'); log.write_bytes(output); row['log'] = str(log); save()
        if row.get('timed_out_or_interrupted') or (expected_failure and p.returncode == 0) or (not expected_failure and p.returncode):
            raise RuntimeError(f'{name} unexpected exit {p.returncode}: {output.decode(errors="replace")}')
        return output.decode()
    try:
        cxx = ROOT / '.deps/bin/clang-cxx'
        receipt['cxx_sha256'] = digest(cxx)
        lib = sysroot / 'usr/lib/x86_64-linux-gnu'
        receipt['sdl_sha256'] = digest(lib / 'libSDL3.so')
        pkgflags = shlex.split(run('pkg-flags', [ROOT / '.deps/bin/pkg-config-graphics', '--cflags', '--libs', 'sdl3']))
        flags = ['-O1', '-UNDEBUG', '-march=x86_64_v2', '-ffp-contract=off', '-fno-strict-aliasing',
                  '-ffunction-sections', '-fdata-sections', '-I' + str(ROOT / 'runtime'), '-I' + str(ROOT / 'runtime/nvn'),
                  '-Wl,--gc-sections', '-Wl,-rpath,' + str(lib), '-pthread']
        receipt['artifacts'] = {}
        for sdk in (False, True):
            name = 'sdk' if sdk else 'default'
            exe = out / ('test-dlss-config-' + name)
            modeflags = ['-DXCDE_LINUX_DLSS=1'] if sdk else []
            run('compile-' + name, [cc, *flags, *modeflags, ROOT / SOURCES[1], ROOT / 'runtime/host/xcde_aspect.c', *pkgflags, '-lm', '-o', exe])
            receipt['artifacts'][str(exe)] = digest(exe)
            for case in ('runtime','scale','forced-scale','roundoff'):
                state = out / (name + '-' + case); state.mkdir()
                print(run(name + '-' + case, [exe, case], cwd=state), end='')
        if args.framegen:
            fg_exe = out / 'test-framegen-config'
            run('compile-framegen', [cc, *flags, '-DXCDE_LINUX_DLSS=1', '-DXCDE_LINUX_FRAMEGEN=1', ROOT / SOURCES[1], ROOT / 'runtime/host/xcde_aspect.c', *pkgflags, '-lm', '-o', fg_exe])
            fg_state = out / 'framegen-settings-state'; fg_state.mkdir()
            print(run('framegen-runtime-policy', [fg_exe, 'runtime'], cwd=fg_state), end='')
        launcher = out / 'test-dlss-launcher-config'
        imgui = []
        for source in ('imgui','imgui_draw','imgui_tables','imgui_widgets'):
            obj = out / (source + '.o'); imgui.append(obj)
            run('compile-' + source, [cxx, '-std=c++17', '-O1', '-UNDEBUG', '-march=x86_64_v2',
                '-ffunction-sections', '-fdata-sections', '-Dfork=config_imgui_forbid_fork', '-I' + str(ROOT / 'third_party/imgui'),
                '-c', ROOT / ('third_party/imgui/' + source + '.cpp'), '-o', obj])
        run('compile-launcher', [cxx, '-std=c++17', *flags, '-I' + str(ROOT / 'third_party/imgui'),
            '-I' + str(ROOT / 'third_party/imgui/backends'), ROOT / 'tests/native/test_dlss_launcher_config_linux.cpp',
            *imgui, *pkgflags, '-lm', '-o', launcher])
        receipt['artifacts'][str(launcher)] = digest(launcher)
        state = out / 'launcher-state'; state.mkdir()
        print(run('launcher-config', [launcher, state], cwd=state), end='')
        for mode in ('default','sdk'):
            for q in range(5):
                inspected = run('cross-config-' + mode + '-' + str(q), [out / ('test-dlss-config-' + mode), 'inspect', state / ('quality' + str(q) + '.ini')], cwd=state)
                values = json.loads(inspected.splitlines()[-1])
                assert values['upscaler'] == (4 if mode == 'sdk' else 2) and values['upscale_quality'] == q
                assert values['frame_gen'] == 0 and values['cutscenes'] != 2

        if args.roundoff_baseline_ref:
            source = run('git-baseline-source', ['git','show', args.roundoff_baseline_ref + ':Monado_Linux/runtime/nvn/output_scale.c'])
            baseline = out / 'baseline-output-scale.c'; baseline.write_text(source)
            receipt['baseline_source_sha256'] = digest(baseline)
            control = out / 'test-dlss-config-baseline'
            run('compile-baseline', [cc, *flags, '-DXCDE_LINUX_DLSS=1', '-DTEST_OUTPUT_SCALE_SOURCE="' + str(baseline) + '"',
                ROOT / SOURCES[1], *pkgflags, '-lm', '-o', control])
            state = out / 'baseline-state'; state.mkdir()
            negative = run('baseline-roundoff-negative', [control, 'roundoff'], cwd=state, expected_failure=True)
            assert 'render 1304x733 versus output 1304x734' in negative and 'Assertion' in negative
            print(negative, end='')
        receipt['sources_after'] = {p: digest(ROOT / p) for p in SOURCES}
        if receipt['sources_before'] != receipt['sources_after']: raise RuntimeError('sources changed during test')
        receipt['status'] = 'passed'
    except Exception as e:
        receipt['status'] = 'failed'; receipt['error'] = str(e); raise
    finally:
        save(); print(out)
if __name__ == '__main__': main()
