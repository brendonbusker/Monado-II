#!/usr/bin/env python3
"""Build the standalone authored setup AppImage, without touching game input.

This is a separate binary packaging boundary from source-only release archives.
It compiles only the setup frontend and private Python entry wrapper. Every
bundled file has an explicit identity, licence and checked archive readback.
The existing game/runtime ABI baseline is retained; no GPU driver is bundled.
"""
from __future__ import annotations
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_launcher_appimage as image
import builder_bootstrap as bootstrap
import package_source_release as release

TEMPLATES = ROOT / 'tools/builder_appimage'
EXTENSIONS = {'_asyncio', '_bz2', '_codecs_cn', '_codecs_hk', '_codecs_iso2022',
    '_codecs_jp', '_codecs_kr', '_codecs_tw', '_ctypes', '_decimal', '_hashlib',
    '_hmac', '_interpchannels', '_interpqueues', '_interpreters', '_lsprof',
    '_lzma', '_multibytecodec', '_multiprocessing', '_posixshmem', '_queue',
    '_sqlite3', '_ssl', '_uuid', '_zoneinfo', '_zstd', 'mmap', 'resource', 'termios'}
PYTHON_LIBS = {'libz.so.1': 'zlib1g', 'libexpat.so.1': 'libexpat1',
    'libssl.so.3': 'libssl3t64', 'libcrypto.so.3': 'libssl3t64',
    'libffi.so.8': 'libffi8', 'libsqlite3.so.0': 'libsqlite3-0',
    'libbz2.so.1.0': 'libbz2-1.0', 'liblzma.so.5': 'liblzma5',
    'libzstd.so.1': 'libzstd1', 'libuuid.so.1': 'libuuid1'}
HOST_ABI = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2',
    'librt.so.1', 'ld-linux-x86-64.so.2'}
SDL_HOST = {'libasound.so.2', 'libX11.so.6', 'libXext.so.6', 'libXcursor.so.1',
    'libXi.so.6', 'libXfixes.so.3', 'libXrandr.so.2', 'libXss.so.1', 'libXtst.so.6',
    'libpulse.so.0', 'libfribidi.so.0', 'libdrm.so.2', 'libgbm.so.1',
    'libwayland-egl.so.1', 'libwayland-cursor.so.0', 'libwayland-client.so.0',
    'libxkbcommon.so.0', 'libdecor-0.so.0'}
MANIFEST = bootstrap.MANIFEST


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def run(argv, commands, *, env=None, cwd=None, timeout=180):
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'PYTHONDONTWRITEBYTECODE': '1'}
    if env:
        environment.update(env)
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=environment,
        capture_output=True, text=True, timeout=timeout)
    commands.append(dict(argv=list(map(str, argv)), exit=result.returncode,
                         stdout=result.stdout[-4000:], stderr=result.stderr[-4000:]))
    if result.returncode:
        raise ValueError('Builder command failed: ' + str(argv[0]) + '\n' + result.stderr[-3000:])
    return result.stdout


def needed(path, commands):
    text = run(['/usr/bin/readelf', '-dW', path], commands)
    return set(re.findall(r'\(NEEDED\).*\[(.*?)\]', text))


def compile_frontend(root, dependency_port, output, commands, jobs):
    """Read accepted compiler/SDL inputs; every compiler cache is output-local."""
    dependency_port = image.ordinary(dependency_port)
    selected = image.regular(dependency_port / '.deps/graphics/active-sysroot.txt', 4096).decode().strip()
    sysroot = image.ordinary(Path(selected))
    if not sysroot.is_relative_to(dependency_port / '.deps/graphics/sysroots'):
        raise ValueError('SDL headers/library must belong to the selected dependency port')
    python = dependency_port / '.venv/bin/python'
    # The environment's Python entry is deliberately a symlink. It is an
    # existing compiler tool, not a packaged file or a writable build location.
    if not python.is_file():
        raise ValueError('Missing pinned Zig environment in --dependency-port')
    version = run([python, '-I', '-B', '-m', 'ziglang', 'version'], commands)
    if version.strip() != '0.14.1':
        raise ValueError('Builder frontend requires the pinned Zig 0.14.1 compiler')
    build = output / 'compile'
    build.mkdir()
    (build / 'obj').mkdir()
    env = {'ZIG_GLOBAL_CACHE_DIR': str(build / 'zig-global'),
           'ZIG_LOCAL_CACHE_DIR': str(build / 'zig-local'), 'TMPDIR': str(build)}
    resources = run([sys.executable, '-I', '-B', root / 'Monado_Linux/tools/launcher/theme_resource.py',
        '--assets', root / 'Monado_Linux/tools/launcher/assets', '--output', build / 'inc'], commands)
    (build / 'resources.json').write_text(resources)
    port = root / 'Monado_Linux'
    cpp = ['third_party/imgui/' + name + '.cpp' for name in
        ('imgui', 'imgui_draw', 'imgui_tables', 'imgui_widgets')]
    cpp += ['third_party/imgui/backends/imgui_impl_sdl3.cpp',
            'third_party/imgui/backends/imgui_impl_sdlrenderer3.cpp', 'tools/builder/builder.cpp']
    flags = ['-O1', '-UNDEBUG', '-std=c++17', '-march=x86_64_v2', '-ffp-contract=off',
        '-fno-strict-aliasing', '-fvisibility=hidden', '-pthread',
        '-ffunction-sections', '-fdata-sections', '-DMONADO_LAUNCHER_RESOURCES=1',
        '-DMONADO_LAUNCHER_ARTWORK=1', '-I' + str(build / 'inc'),
        '-I' + str(port / 'third_party/imgui'), '-I' + str(port / 'third_party/imgui/backends'),
        '-I' + str(sysroot / 'usr/include')]
    compiler = [python, '-I', '-B', '-m', 'ziglang']
    def compile_one(name):
        obj = build / 'obj' / (name.replace('/', '_') + '.o')
        run([*compiler, 'c++', '-target', 'x86_64-linux-gnu', *flags,
            '-c', port / name, '-o', obj], commands, env=env, timeout=300)
        return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        objects = list(pool.map(compile_one, cpp))
    libdir = sysroot / 'usr/lib/x86_64-linux-gnu'
    executable = build / 'monado-builder'
    run([*compiler, 'c++', '-target', 'x86_64-linux-gnu', '-march=x86_64_v2', *objects,
        '-L' + str(libdir), '-lSDL3', '-lm', '-ldl', '-pthread', '-Wl,--gc-sections',
        '-Xlinker', '-rpath', '-Xlinker', '$ORIGIN/../lib', '-o', executable],
        commands, env=env, timeout=300)
    wrapper = build / 'python3.14'
    run([*compiler, 'cc', '-target', 'x86_64-linux-gnu', '-O1', '-march=x86_64_v2',
        root / 'tools/builder_appimage/python_entry.c', '-o', wrapper], commands, env=env)
    return executable, wrapper, sysroot


def add(files, name, source, mode=0o644):
    bootstrap.relative(name)
    if name in files:
        raise ValueError('Duplicate builder file: ' + name)
    files[name] = (image.regular(Path(source).resolve()), mode)


def private_python(files, wrapper, commands, python=Path('/usr/bin/python3.14')):
    python = image.ordinary(python)
    probe = json.loads(run([python, '-I', '-B', '-c',
        'import json,sys,sysconfig;print(json.dumps(dict(version=list(sys.version_info[:3]),prefix=sys.base_prefix,stdlib=sysconfig.get_path("stdlib"))))'], commands))
    if probe['version'][:2] != [3, 14]:
        raise ValueError('Private builder Python must be CPython 3.14')
    stdlib = image.ordinary(Path(probe['stdlib']))
    base = image.ordinary(Path(probe['prefix']))
    private_base = (base / 'monado-private-python.json').is_file()
    if private_base:
        marker = json.loads(image.regular(base / 'monado-private-python.json', 16384))
        if marker.get('schema') != 1 or marker.get('project') != 'Monado II' or marker.get('python') != [3, 14]:
            raise ValueError('Private Python provenance marker is invalid')
        python = base / 'bin/python3.14.real'
    files['usr/python/monado-private-python.json'] = (encoded(dict(schema=1, project='Monado II', python=[3, 14], runtime_kind='standalone-builder')), 0o644)
    add(files, 'usr/python/bin/python3.14', wrapper, 0o755)
    add(files, 'usr/python/bin/python3.14.real', python, 0o755)
    omitted = {'test', 'tests', '__pycache__', 'site-packages', 'dist-packages',
        'config-3.14-x86_64-linux-gnu', 'lib-dynload', 'curses', 'dbm', 'turtledemo',
        'tkinter', 'idlelib'}
    for source in sorted(stdlib.rglob('*')):
        name = source.relative_to(stdlib)
        if (any(part in omitted for part in name.parts) or source.is_dir()
                or source.suffix != '.py' or name.as_posix() in ('sitecustomize.py', 'turtle.py')):
            continue
        add(files, 'usr/python/lib/python3.14/' + name.as_posix(), source)
    add(files, 'usr/python/lib/python3.14/LICENSE.txt', stdlib / 'LICENSE.txt')
    modules = []
    for name in sorted(EXTENSIONS):
        path = stdlib / 'lib-dynload' / (name + '.cpython-314-x86_64-linux-gnu.so')
        if not path.is_file():
            raise ValueError('Missing reviewed CPython extension: ' + name)
        add(files, 'usr/python/lib/python3.14/lib-dynload/' + path.name, path, 0o755)
        modules.append(path)
    packaged = set(PYTHON_LIBS)
    for path in [python, *modules]:
        unknown = needed(path, commands) - packaged - HOST_ABI
        if unknown:
            raise ValueError('Unreviewed Python runtime dependency: ' + ', '.join(sorted(unknown)))
    for soname, package in PYTHON_LIBS.items():
        source = (base / 'lib' if private_base else Path('/usr/lib/x86_64-linux-gnu')) / soname
        unknown = needed(source, commands) - packaged - HOST_ABI
        if unknown:
            raise ValueError('Unreviewed Python support dependency: ' + ', '.join(sorted(unknown)))
        add(files, 'usr/python/lib/' + soname, source, 0o755)
    for package in sorted(set(PYTHON_LIBS.values()) | {'python3.14'}):
        name = 'Python-copyright.txt' if package == 'python3.14' else package + '-copyright.txt'
        copyright = (base / 'share/doc/monado-ii' / name if private_base else Path('/usr/share/doc') / package / 'copyright')
        add(files, 'usr/share/doc/monado-ii/' + name, copyright)
        add(files, 'usr/python/share/doc/monado-ii/' + name, copyright)
    apache = (base / 'share/doc/monado-ii/Apache-2.0.txt' if private_base else Path('/usr/share/common-licenses/Apache-2.0'))
    add(files, 'usr/share/doc/monado-ii/Apache-2.0.txt', apache)
    add(files, 'usr/python/share/doc/monado-ii/Apache-2.0.txt', apache)
    return probe


def authored_template(root, output):
    version = json.loads(image.regular(root / 'update-version.json'))['version']
    receipt = release.package(root, 'linux', version, output / 'source-kit')
    return output / 'source-kit' / receipt['archive'], receipt


def bundle_files(root, frontend, wrapper, sysroot, dependency_port, archive, commands):
    files = {}
    for name, source, mode in (
        ('AppRun', root / 'tools/builder_appimage/AppRun', 0o755),
        ('monado-ii.desktop', root / 'tools/appimage/monado-ii.desktop', 0o644),
        ('monado-ii.xpm', root / 'tools/appimage/monado-ii.xpm', 0o644),
        ('.DirIcon', root / 'tools/appimage/monado-ii.xpm', 0o644),
        ('usr/bin/monado-builder', frontend, 0o755),
        ('usr/lib/monado-ii/builder_bootstrap.py', root / 'tools/builder_bootstrap.py', 0o644),
        (bootstrap.ARCHIVE, archive, 0o644),
        ('usr/share/doc/monado-ii/BUNDLE_NOTICES.md', root / 'tools/builder_appimage/BUNDLE_NOTICES.md', 0o644)):
        add(files, name, source, mode)
    base_entry = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
    probe = private_python(files, wrapper, commands, python=base_entry)
    sdl = sysroot / 'usr/lib/x86_64-linux-gnu/libSDL3.so.0'
    unknown = needed(sdl, commands) - SDL_HOST - HOST_ABI
    if unknown:
        raise ValueError('Unreviewed SDL interface dependency: ' + ', '.join(sorted(unknown)))
    add(files, 'usr/lib/libSDL3.so.0', sdl, 0o755)
    unknown = needed(frontend, commands) - {'libSDL3.so.0'} - HOST_ABI
    if unknown:
        raise ValueError('Unreviewed frontend dependency: ' + ', '.join(sorted(unknown)))
    add(files, 'usr/share/doc/monado-ii/SDL3-copyright.txt', sysroot / 'usr/share/doc/libsdl3-0/copyright')
    for name in image.LICENSES:
        source = root / ('tools/builder_appimage/APPIMAGE_RUNTIME_NOTICES.txt' if name == 'THIRD-PARTY-NOTICES.txt' else 'tools/appimage/' + name)
        add(files, 'usr/share/doc/monado-ii/' + name, source)
    for name in ('LICENSE', 'CREDITS.md', 'NOTICE.md'):
        add(files, 'usr/share/doc/monado-ii/' + name, root / name)
    add(files, 'usr/share/doc/monado-ii/ImGui-LICENSE.txt', root / 'Monado_Linux/third_party/imgui/LICENSE.txt')
    add(files, 'usr/share/doc/monado-ii/DejaVu-LICENSE.txt', root / 'Monado_Linux/tools/launcher/assets/fonts/LICENSE-DejaVu.txt')
    zigroot = dependency_port / '.venv/lib/python3.14/site-packages/ziglang/lib'
    for component in ('libcxx', 'libcxxabi', 'libunwind'):
        add(files, 'usr/share/doc/monado-ii/LLVM-' + component + '-LICENSE.txt', zigroot / component / 'LICENSE.TXT')
    return files, probe


def package(root, dependency_port, output, image_path, *, jobs=4, legacy_selection=None):
    root, dependency_port, output, image_path = map(image.ordinary, (root, dependency_port, output, image_path))
    if output.exists() or image_path.exists() or image_path.with_name(image_path.name + '.receipt.json').exists():
        raise ValueError('Builder output, AppImage and receipt must all be fresh')
    if output.is_relative_to(root) or image_path.is_relative_to(root):
        raise ValueError('Builder artifacts must be separate from the reviewed source workspace')
    if not 1 <= jobs <= 6 or image_path.suffix != '.AppImage':
        raise ValueError('Use 1..6 compile workers and a .AppImage output')
    source_document, source_manifest = release._document(root)
    release._guard(root)
    output.mkdir(mode=0o700, parents=True)
    commands = []
    try:
        frontend, wrapper, sysroot = compile_frontend(root, dependency_port, output, commands, jobs)
        archive, source_receipt = authored_template(root, output)
        files, python = bundle_files(root, frontend, wrapper, sysroot, dependency_port, archive, commands)
        migration = {'adjacent_workspace': True} if legacy_selection is not None else None
        if legacy_selection is not None:
            for key in ('launcher', 'game'):
                bootstrap.relative(legacy_selection.get(key))
            if legacy_selection.get('game_port', 'current') not in ('bound', 'current'):
                raise ValueError('Invalid legacy game port selection')
        files[MANIFEST] = (encoded(dict(schema=1, project='Monado II', kind='standalone-builder', migration=migration,
            minimum_glibc='2.43', contains_game_files=False, contains_game_executable=False,
            contains_generated_game_code=False, contains_vendor_sdk=False, files=image.identity_map(files))), 0o644)
        stage = output / 'AppDir'
        stage.mkdir()
        for name, (data, mode) in files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(mode)
        for path in stage.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
        image.check_tree(stage, files)
        bootstrap.validate_image(stage)
        runtime = image.regular(dependency_port / '.deps/appimage' / ('runtime-x86_64-' + image.RUNTIME_SHA), image.RUNTIME_BYTES)
        if image.digest(runtime) != image.RUNTIME_SHA:
            raise ValueError('Pinned AppImage runtime identity differs')
        image.native(runtime, runtime=True)
        squash = output / 'builder.squashfs'
        image.command(['/usr/bin/mksquashfs', stage, squash, '-noappend', '-all-root', '-no-xattrs',
            '-comp', 'gzip', '-processors', '2', '-no-progress', '-mkfs-time', '0', '-all-time', '0'], commands)
        temporary = output / 'builder.AppImage'
        with temporary.open('xb') as stream:
            stream.write(runtime)
            with squash.open('rb') as incoming:
                shutil.copyfileobj(incoming, stream)
        temporary.chmod(0o755)
        readback = output / 'readback'
        image.command(['/usr/bin/unsquashfs', '-no-progress', '-no-xattrs', '-processors', '2',
            '-offset', str(len(runtime)), '-dest', readback, temporary], commands)
        image.check_tree(readback, files)
        bootstrap.validate_image(readback)
        final_document, final_manifest = release._document(root)
        if final_manifest != source_manifest or final_document != source_document:
            raise ValueError('Reviewed source changed during builder compilation/packaging')
        data = image.regular(temporary, bootstrap.MAX_BYTES)
        if legacy_selection is not None and len(data) > 64 * 1024 * 1024:
            raise ValueError('Migration AppImage exceeds existing updater 64 MiB limit')
        image_path.parent.mkdir(parents=True, exist_ok=True)
        os.link(temporary, image_path)
        temporary.unlink()
        receipt = dict(schema=1, project='Monado II', status='passed', artifact_kind='standalone-builder-appimage',
            output=str(image_path), sha256=image.digest(data), bytes=len(data),
            runtime_sha256=image.RUNTIME_SHA, source_manifest_sha256=image.digest(source_manifest),
            archive_readback_verified=True,
            requires_adjacent_workspace=False, contains_game_files=False,
            contains_game_executable=False, contains_generated_game_code=False,
            contains_vendor_sdk=False, game_build_performed=False, private_python=python,
            source_receipt=source_receipt, appdir_files=image.identity_map(files),
            compile_dependencies=dict(zig_version='0.14.1',
                zig_sha256=release.digest(dependency_port / '.venv/lib/python3.14/site-packages/ziglang/zig'),
                sysroot_marker_sha256=release.digest(sysroot / '.monado-deps.json')), 
            migration=migration, legacy_selection=legacy_selection,
            host_sdl_interfaces=sorted(SDL_HOST), commands=commands,
            finished_utc=datetime.now(timezone.utc).isoformat())
        with image_path.with_name(image_path.name + '.receipt.json').open('xb') as stream:
            stream.write(encoded(receipt))
        (output / 'receipt.json').write_bytes(encoded(receipt))
        return receipt
    except Exception:
        (output / 'failure.json').write_bytes(encoded(dict(status='failed', commands=commands)))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--dependency-port', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='fresh authored frontend/package output directory')
    parser.add_argument('--image', type=Path, required=True, help='fresh standalone AppImage outside source')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args(argv)
    try:
        receipt = package(args.source, args.dependency_port, args.output, args.image, jobs=args.jobs)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Standalone builder packaging failed: ' + str(error) + '\n')
    print(json.dumps({key: receipt[key] for key in ('status', 'output', 'sha256', 'bytes', 'archive_readback_verified', 'game_build_performed')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
