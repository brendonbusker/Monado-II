#!/usr/bin/env python3
"""Hash-locked project-local FSR4 preparation tools. Never installs packages."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request

import setup_linux_fsr4 as component

ROOT = component.ROOT
BASE = ROOT / '.deps/fsr4'
DXIL_SOURCE_SHA256 = 'f4f65256e6f76ad0ba8d453c62689687079988ad23408414b42e3e7701dc9c1c'
DXIL_PATCHED_SHA256 = '76d23c96a7ef8378e04dc0c704a4f5df3671b3e71ad3f61ac901ce19be9b1c84'

def source_identity(lock):
    inputs={name:item for name,item in lock['files'].items() if name.startswith('third_party/fsr4cap/') and Path(name).suffix in ('.c','.h','.py','.patch')}
    return hashlib.sha256(json.dumps({'inputs':inputs,'dependencies':lock['dependencies']},sort_keys=True).encode()).hexdigest()


def fetch(item, offline=False):
    cache = component.ordinary(BASE / 'downloads', BASE)
    cache.mkdir(parents=True, exist_ok=True)
    target = component.ordinary(cache / (item['path'] + '-' + item['commit'] + '.tar.gz'), cache)
    if target.exists():
        if component.digest(target) != item['archive_sha256']:
            raise ValueError('cached FSR4 source hash mismatch: ' + str(target))
        return target
    if offline:
        raise ValueError('offline FSR4 tool source missing: ' + item['path'])
    request = urllib.request.Request(item['url'], headers={'User-Agent': 'Monado-II-local-FSR4-preparation'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(item['archive_bytes'] + 1)
    if len(data) != item['archive_bytes'] or hashlib.sha256(data).hexdigest() != item['archive_sha256']:
        raise ValueError('downloaded FSR4 source hash mismatch: ' + item['path'])
    temporary = target.with_name('.' + target.name + '.' + str(os.getpid()))
    with temporary.open('xb') as stream:
        stream.write(data)
    os.replace(temporary, target)
    return target


def unpack(archive, destination):
    destination = component.ordinary(destination, BASE, fresh=True)
    destination.mkdir(parents=True)
    expanded = 0
    seen = set()
    with tarfile.open(archive, 'r:gz') as tf:
        for member in tf:
            parts = Path(member.name).parts
            if len(parts) < 2:
                if member.isdir(): continue
                raise ValueError('invalid archive root')
            rel = Path(*parts[1:])
            if rel.is_absolute() or '..' in rel.parts or rel in seen:
                raise ValueError('unsafe/duplicate archive member')
            if member.isdir(): continue
            if not member.isfile() or member.size > 16_000_000:
                raise ValueError('nonregular or oversized archive member')
            expanded += member.size
            if expanded > 300_000_000:
                raise ValueError('oversized expanded tool source')
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(tf.extractfile(member).read())
            target.chmod(0o644)
            seen.add(rel)


def class_bindings_source(source, delta):
    """Apply only the locked, single-file FSR4 class-bindings patch."""
    if hashlib.sha256(source).hexdigest() != DXIL_SOURCE_SHA256:
        raise ValueError('pinned dxil-spirv source changed before class-bindings patch')
    hunks = re.split(rb'(?m)^@@ -([1-9][0-9]*),[0-9]+ \+[0-9]+,[0-9]+ @@[^\n]*\n', delta)
    if len(hunks) != 11 or hunks[0].splitlines()[2:] != [b'--- a/dxil_spirv.cpp', b'+++ b/dxil_spirv.cpp']:
        raise ValueError('unexpected dxil-spirv class-bindings patch layout')
    original = source.splitlines(keepends=True)
    patched = []
    next_line = 0
    for start, body in zip(hunks[1::2], hunks[2::2]):
        offset = int(start) - 1
        lines = body.splitlines(keepends=True)
        if any(line[:1] not in (b' ', b'-', b'+') for line in lines):
            raise ValueError('invalid dxil-spirv class-bindings hunk')
        before = [line[1:] for line in lines if not line.startswith(b'+')]
        if offset < next_line or not before or original[offset:offset + len(before)] != before:
            raise ValueError('dxil-spirv class-bindings patch context changed')
        patched.extend(original[next_line:offset])
        patched.extend(line[1:] for line in lines if not line.startswith(b'-'))
        next_line = offset + len(before)
    patched.extend(original[next_line:])
    result = b''.join(patched)
    if hashlib.sha256(result).hexdigest() != DXIL_PATCHED_SHA256:
        raise ValueError('dxil-spirv class-bindings patch produced unexpected source')
    return result


def build(output, jobs=4, offline=False):
    lock = component.verify_source()
    out = component.ordinary(output, BASE / 'tools', fresh=True)
    out.mkdir(parents=True)
    (out / 'logs').mkdir()
    (out / 'bin').mkdir()
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TMPDIR': str(out),
           'ZIG_GLOBAL_CACHE_DIR': str(out / 'zig-global'), 'ZIG_LOCAL_CACHE_DIR': str(out / 'zig-local')}
    receipt = {'schema': 1, 'status': 'running', 'recipe_sha256': component.digest(__file__),
               'source_identity': source_identity(lock), 'output': str(out), 'commands': []}
    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    def run(name, args, cwd=ROOT, timeout=900):
        before = time.monotonic()
        with (out / 'logs' / (name + '.log')).open('wb') as log:
            process=subprocess.Popen(list(map(str,args)),cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=process.wait(timeout=timeout)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait()
        receipt['commands'].append({'name': name, 'argv': list(map(str, args)), 'cwd': str(cwd),
                                    'seconds': time.monotonic() - before, 'exit': code})
        save()
        if code:
            raise RuntimeError(name + ' failed; see ' + str(out / 'logs' / (name + '.log')))
    try:
        save()
        for item in lock['dependencies']:
            unpack(fetch(item, offline), out / 'source' / item['path'])
        source = out / 'source/dxil-spirv'
        for name, destination in [('spirv-headers', 'third_party/spirv-headers'),
                                  ('SPIRV-Tools', 'third_party/SPIRV-Tools'),
                                  ('SPIRV-Cross', 'third_party/SPIRV-Cross'),
                                  ('dxbc-spirv', 'subprojects/dxbc-spirv')]:
            p = source / destination
            if p.is_dir() and not any(p.iterdir()): p.rmdir()
            shutil.move(str(out / 'source' / name), p)
        delta = component.ordinary(ROOT / 'third_party/fsr4cap/dxil-spirv-class-bindings.patch', ROOT)
        target = component.ordinary(source / 'dxil_spirv.cpp', source)
        target.write_bytes(class_bindings_source(target.read_bytes(), delta.read_bytes()))
        receipt['source_patch'] = {'name': 'class-bindings-patch', 'patch': component.resource(delta),
                                   'before_sha256': DXIL_SOURCE_SHA256, 'after': component.resource(target)}
        (out / 'logs/class-bindings-patch.log').write_text('Applied and verified the pinned dxil-spirv class-bindings patch.\n')
        save()
        tools = json.loads((ROOT / '.deps/build-tools/active-tools.json').read_text())
        for item in tools.values():
            if component.digest(component.ordinary(item['path'])) != item['sha256']:
                raise ValueError('CMake/Ninja identity changed')
        cmake = tools['cmake']['path']; ninja = tools['ninja']['path']
        run('configure', [cmake, '-S', source, '-B', out / 'build', '-G', 'Ninja',
            '-DCMAKE_MAKE_PROGRAM=' + ninja, '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=' + str(ROOT / '.deps/bin/clang-cc'),
            '-DCMAKE_CXX_COMPILER=' + str(ROOT / '.deps/bin/clang-cxx'),
            '-DPYTHON_EXECUTABLE=' + sys.executable, '-DPython3_EXECUTABLE=' + sys.executable,
            '-DSPIRV_SKIP_TESTS=ON', '-DSPIRV_SKIP_EXECUTABLES=OFF', '-DSPIRV_WERROR=OFF',
            '-DSPIRV_CROSS_ENABLE_TESTS=OFF', '-DSPIRV_CROSS_ENABLE_CLI=OFF',
            '-DCMAKE_DISABLE_FIND_PACKAGE_Git=ON'])
        run('compile-tools', [cmake, '--build', out / 'build', '--parallel', str(jobs), '--target',
                              'dxil-spirv', 'spirv-as', 'spirv-dis', 'spirv-val'])
        for name, path in [('dxil-spirv', 'dxil-spirv'), ('spirv-as', 'third_party/SPIRV-Tools/tools/spirv-as'),
                           ('spirv-dis', 'third_party/SPIRV-Tools/tools/spirv-dis'),
                           ('spirv-val', 'third_party/SPIRV-Tools/tools/spirv-val')]:
            shutil.copy2(out / 'build' / path, out / 'bin' / name)
        # Keep the dependency beside dxil-spirv; its original build RPATH remains valid.
        shared = out / 'build/libdxil-spirv-c-shared.so.2.74.0'
        if shared.is_file():
            shutil.copy2(shared, out / 'bin/libdxil-spirv-c-shared.so.2')
        cap = ROOT / 'third_party/fsr4cap'
        zig = [ROOT / '.venv/bin/python', '-B', '-m', 'ziglang', 'cc', '-target', 'x86_64-windows-gnu']
        run('capture-tool', [*zig, '-std=c11', '-O1', '-I' + str(cap / 'ffx/api/include'),
            '-I' + str(cap / 'ffx/upscalers/include'), cap / 'fsr4cap.c', cap / 'capture.c', cap / 'rootsig.c',
            '-o', out / 'bin/fsr4cap.exe', '-ld3d12', '-ldxguid', '-static'])
        run('driver-shim', [*zig, '-std=c11', '-O1', '-shared', cap / 'amdxc64.c',
                            '-o', out / 'bin/amdxc64.dll', '-static'])
        receipt['tools'] = {p.name: component.resource(p) for p in (out / 'bin').iterdir() if p.is_file()}
        receipt['status'] = 'passed'
        save()
        marker = component.ordinary(BASE / 'active-tools.json', BASE)
        temp = marker.with_name('.active-tools.' + str(os.getpid()))
        temp.write_text(json.dumps({'schema': 1, 'receipt_path': str(out / 'receipt.json')}) + '\n')
        os.replace(temp, marker)
    except BaseException as error:
        receipt.update(status='failed', error=str(error))
        raise
    finally:
        save()
    return verify_existing()


def verify_existing():
    lock=component.verify_source()
    marker = component.ordinary(BASE / 'active-tools.json', BASE)
    item = json.loads(marker.read_text())
    path = component.ordinary(item['receipt_path'], BASE / 'tools')
    receipt = json.loads(path.read_text())
    if (item.get('schema') != 1 or receipt.get('status') != 'passed' or
        receipt.get('recipe_sha256') != component.digest(__file__) or
        receipt.get('source_identity') != source_identity(lock)):
        raise ValueError('FSR4 preparation tools recipe changed')
    for name, tool in receipt['tools'].items():
        p = component.ordinary(path.parent / 'bin' / name, path.parent)
        if component.resource(p) != tool:
            raise ValueError('FSR4 preparation tool changed: ' + name)
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', action='store_true'); ap.add_argument('--output', type=Path)
    ap.add_argument('--jobs', type=int, choices=range(1, 9), default=4)
    ap.add_argument('--offline', action='store_true')
    args = ap.parse_args()
    try:
        if args.build and not args.output: raise ValueError('--build requires fresh --output')
        print(json.dumps(build(args.output, args.jobs, args.offline) if args.build else verify_existing(), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        ap.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
