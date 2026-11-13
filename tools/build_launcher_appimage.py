#!/usr/bin/env python3
"""Create a local launcher-only AppImage; never package a game or its inputs.

The resulting native frontend needs its adjacent source/build workspace. The
game, dependencies, Python environment, caches and saves stay outside the image.
Only a pinned official AppImage runtime is fetched; no game/SDK download occurs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
_layout_spec = importlib.util.spec_from_file_location('monado_appimage_install_layout', ROOT / 'Monado_Linux/scripts/install_layout.py')
install_layout = importlib.util.module_from_spec(_layout_spec)
_layout_spec.loader.exec_module(install_layout)
TEMPLATES = ROOT / 'tools/appimage'
LOCK = ROOT / 'appimage-runtime.lock.json'
RUNTIME_SHA = '617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46'
RUNTIME_BYTES = 944632
RUNTIME_URL = 'https://api.github.com/repos/AppImage/type2-runtime/releases/assets/657374641'
ALLOWED_HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
MANIFEST = 'usr/share/monado-ii/image-manifest.json'
LICENSES = ('AppImage-runtime-LICENSE.txt', 'libfuse-LGPL-2.1.txt', 'squashfuse-LICENSE.txt',
            'musl-COPYRIGHT.txt', 'zstd-LICENSE.txt', 'zlib-LICENSE.txt',
            'mimalloc-LICENSE.txt', 'THIRD-PARTY-NOTICES.txt')


class AppImageError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    path = Path(path).absolute()
    if '..' in path.parts or path.resolve() != path:
        raise AppImageError('path must be canonical without links or parent traversal: ' + str(path))
    return path


def regular(path, limit=64 * 1024 * 1024):
    path = ordinary(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise AppImageError('expected an ordinary single-link bounded file: ' + str(path))
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0) |
             getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    fd = os.open(path, flags)
    try:
        first = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (first.st_dev, first.st_ino):
            raise AppImageError('file identity changed before reading: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        last = os.fstat(fd)
        after = path.lstat()
        snapshot = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if snapshot(before) != snapshot(after) or snapshot(first) != snapshot(last) or len(data) != first.st_size or len(data) > limit:
            raise AppImageError('file changed while reading: ' + str(path))
        return data
    finally:
        os.close(fd)


def native(data, *, runtime=False):
    if (len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or
            int.from_bytes(data[18:20], 'little') != 62):
        raise AppImageError('expected native Linux x86-64 ELF')
    if runtime and data[8:11] != b'AI\x02':
        raise AppImageError('expected an AppImage type-2 runtime')


def runtime_lock():
    value = json.loads(regular(LOCK, 10000))
    runtime = value.get('runtime', {})
    if (type(value.get('schema')) is not int or value.get('schema') != 1 or
            value.get('project') != 'Monado II' or value.get('architecture') != 'x86_64' or
            runtime.get('repository') != 'AppImage/type2-runtime' or
            runtime.get('commit') != 'fedfad51acc2860b2916a1eef32ba4a500ff31ef' or
            runtime.get('release_id') != 417724209 or runtime.get('asset_id') != 657374641 or
            runtime.get('sha256') != RUNTIME_SHA or runtime.get('bytes') != RUNTIME_BYTES or
            runtime.get('url') != RUNTIME_URL):
        raise AppImageError('AppImage runtime lock differs from reviewed identity')
    return runtime


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or
            parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise AppImageError('runtime download redirected outside official GitHub HTTPS hosts')


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def fetch_runtime(identity, opener=None):
    safe_url(identity['url'])
    request = urllib.request.Request(identity['url'], headers={
        'Accept': 'application/octet-stream', 'User-Agent': 'Monado-II-local-AppImage-builder',
        'X-GitHub-Api-Version': '2022-11-28'})
    client = opener or urllib.request.build_opener(OfficialRedirect())
    with client.open(request, timeout=60) as response:
        safe_url(response.geturl())
        data = response.read(identity['bytes'] + 1)
    if len(data) != identity['bytes'] or digest(data) != identity['sha256']:
        raise AppImageError('official AppImage runtime size/hash differs; no unverified runtime is used')
    native(data, runtime=True)
    return data


def runtime_bytes(port):
    identity = runtime_lock()
    cache = ordinary(port / '.deps/appimage')
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / ('runtime-x86_64-' + identity['sha256'])
    if path.exists() or path.is_symlink():
        data = regular(path, identity['bytes'])
        if len(data) != identity['bytes'] or digest(data) != identity['sha256']:
            raise AppImageError('cached AppImage runtime differs; preserve/review it before retrying')
        native(data, runtime=True)
        return data
    data = fetch_runtime(identity)
    with path.open('xb') as stream:
        stream.write(data)
    return data


def verified_selection(launcher, game, root):
    """Reuse unchanged input/build/resource/state guards without executing a guest."""
    port = root / 'Monado_Linux'
    scripts = port / 'scripts'
    previous = list(sys.path)
    try:
        sys.path.insert(0, str(scripts))
        module = importlib.import_module('launcher_linux')
        _, arguments = module.arguments(['--launcher-executable', str(launcher),
            '--game-executable', str(game), '--state-root', str(install_layout.profile_port(port) / 'play/launcher'), '--dry-run'])
        plan = module.prepare(arguments)
    finally:
        sys.path[:] = previous
    return {'launcher_sha256': plan['launcher_sha256'], 'game_sha256': plan['game_sha256']}


def relative_build(path, root):
    path = ordinary(path)
    try:
        name = path.relative_to(root)
    except ValueError:
        raise AppImageError('build must belong to this Monado II workspace') from None
    if len(name.parts) < 4 or name.parts[0] != 'Monado_Linux' or name.parts[1] not in ('build', 'runs', 'accepted'):
        raise AppImageError('select a receipted Monado_Linux build, runs or accepted executable')
    return name.as_posix()


def source_files(root):
    result = {
        'AppRun': (regular(TEMPLATES / 'AppRun'), 0o755),
        'monado-ii.desktop': (regular(TEMPLATES / 'monado-ii.desktop'), 0o644),
        'monado-ii.xpm': (regular(TEMPLATES / 'monado-ii.xpm'), 0o644),
        '.DirIcon': (regular(TEMPLATES / 'monado-ii.xpm'), 0o644),
        'usr/lib/monado-ii/driver.py': (regular(TEMPLATES / 'driver.py'), 0o644),
    }
    for name in LICENSES:
        result['usr/share/doc/monado-ii/' + name] = (regular(TEMPLATES / name), 0o644)
    for name in ('LICENSE', 'CREDITS.md', 'NOTICE.md'):
        result['usr/share/doc/monado-ii/' + name] = (regular(root / name), 0o644)
    # Only the launcher's actually compiled licensed dependencies are noticed.
    result['usr/share/doc/monado-ii/ImGui-LICENSE.txt'] = (regular(root / 'Monado_Linux/third_party/imgui/LICENSE.txt'), 0o644)
    result['usr/share/doc/monado-ii/DejaVu-LICENSE.txt'] = (regular(root / 'Monado_Linux/tools/launcher/assets/fonts/LICENSE-DejaVu.txt'), 0o644)
    return result


def identity_map(files):
    return {name: {'sha256': digest(data), 'bytes': len(data), 'mode': mode}
            for name, (data, mode) in sorted(files.items())}


def check_tree(directory, files):
    expected_directories = set()
    for name in files:
        path = PurePosixPath(name)
        if (path.is_absolute() or str(path) != name or '\\' in name or ':' in name or
                any(part in ('', '.', '..') for part in name.split('/'))):
            raise AppImageError('invalid AppDir allowlist path')
        expected_directories.update(str(parent) for parent in path.parents if str(parent) != '.')
    actual_files, actual_directories = set(), set()
    for path in directory.rglob('*'):
        name = path.relative_to(directory).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            actual_directories.add(name)
            continue
        actual_files.add(name)
        if name not in files:
            raise AppImageError('unexpected AppDir file: ' + name)
        data, mode = files[name]
        if regular(path) != data or stat.S_IMODE(info.st_mode) != mode:
            raise AppImageError('AppDir identity/mode differs: ' + name)
    if actual_files != set(files) or actual_directories != expected_directories:
        raise AppImageError('AppDir contains unexpected or missing files/directories')


def command(argv, commands):
    # The launcher supervisor keeps its private 0077 mask. Squashfs readback
    # must retain the reviewed 0644/0755 payload modes; change only this child.
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=180,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}, umask=0o022)
    commands.append({'argv': list(map(str, argv)), 'exit': result.returncode,
                     'stdout': result.stdout[-6000:], 'stderr': result.stderr[-6000:]})
    if result.returncode:
        raise AppImageError('AppImage command failed: ' + str(argv[0]) + '\n' + result.stderr[-2000:])
    return result.stdout


def package(launcher, game, output, *, root=ROOT, selection_provider=None, runtime_provider=None, standalone_migration=None):
    if standalone_migration not in (None, 'retained-workspace-bootstrap'):
        raise AppImageError('unknown standalone migration receipt state')
    root = ordinary(root)
    launcher, game, output = map(ordinary, (launcher, game, output))
    port = root / 'Monado_Linux'
    launcher_name = relative_build(launcher, root)
    selected_game_port = install_layout.build_port(port, game)
    game_name = relative_build(game, selected_game_port.parent)
    selection_data = {'schema': 1, 'project': 'Monado II', 'launcher': launcher_name, 'game': game_name}
    if selected_game_port != port:
        selection_data['game_port'] = 'bound'
    if not output.is_relative_to(port / 'build') or output.suffix != '.AppImage':
        raise AppImageError('AppImage output must be a fresh .AppImage below Monado_Linux/build')
    receipt_path = output.with_name(output.name + '.receipt.json')
    if any(path.exists() or path.is_symlink() for path in (output, receipt_path)):
        raise AppImageError('refusing to replace an existing AppImage or receipt')
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise AppImageError('native Linux x86-64 is required for AppImage packaging')
    tools = {name: shutil.which(name) for name in ('mksquashfs', 'unsquashfs')}
    if not all(tools.values()):
        raise AppImageError('Install your distribution’s squashfs-tools package (mksquashfs and unsquashfs), then retry')
    selection = (selection_provider or verified_selection)(launcher, game, root)
    gui = regular(launcher)
    native(gui)
    if digest(gui) != selection['launcher_sha256']:
        raise AppImageError('launcher changed after receipt verification')
    # Existing plan/receipt guards hash the game; its bytes are never staged or included.
    files = source_files(root)
    files['usr/bin/monado-launcher'] = (gui, 0o755)
    files['usr/share/monado-ii/selection.json'] = (encoded(selection_data), 0o644)
    files[MANIFEST] = (encoded({'schema': 1, 'project': 'Monado II',
        'files': identity_map(files)}), 0o644)
    runtime = (runtime_provider or runtime_bytes)(port)
    native(runtime, runtime=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    ordinary(output.parent)
    commands = []
    with tempfile.TemporaryDirectory(prefix='.appimage-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        stage = temporary / 'AppDir'
        stage.mkdir()
        for name, (data, mode) in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        for path in stage.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
        check_tree(stage, files)
        squash = temporary / 'launcher.squashfs'
        command([tools['mksquashfs'], stage, squash, '-noappend', '-all-root', '-no-xattrs',
            '-comp', 'gzip', '-processors', '2', '-no-progress', '-mkfs-time', '0', '-all-time', '0'], commands)
        partial = temporary / 'launcher.AppImage'
        with partial.open('xb') as stream:
            stream.write(runtime)
            with squash.open('rb') as source:
                shutil.copyfileobj(source, stream)
        partial.chmod(0o755)
        readback = temporary / 'readback'
        command([tools['unsquashfs'], '-no-progress', '-no-xattrs', '-processors', '2',
            '-offset', str(len(runtime)), '-dest', readback, partial], commands)
        check_tree(readback, files)
        check_tree(stage, files)
        if regular(launcher) != gui or source_files(root) != {name: value for name, value in files.items()
                if name not in ('usr/bin/monado-launcher', 'usr/share/monado-ii/selection.json', MANIFEST)}:
            raise AppImageError('launcher or packaging source changed during packaging')
        data = regular(partial)
        # Atomic no-clobber publication; a racing existing output is preserved.
        os.link(partial, output)
    receipt = {'schema': 1, 'project': 'Monado II', 'status': 'passed',
        'artifact_kind': 'local-launcher-appimage', 'sha256': digest(data), 'bytes': len(data),
        'output': str(output), 'launcher': launcher_name, 'game': game_name,
        'game_port': 'bound' if selected_game_port != port else 'current',
        'launcher_sha256': selection['launcher_sha256'], 'game_sha256': selection['game_sha256'],
        'runtime_sha256': digest(runtime), 'runtime_bytes': len(runtime),
        'appdir_files': identity_map(files), 'archive_readback_verified': True,
        'contains_game_files': False, 'contains_game_executable': False,
        'contains_generated_game_code': False, 'contains_vendor_sdk': False,
        'requires_adjacent_workspace': True, 'commands': commands,
        'finished_utc': datetime.now(timezone.utc).isoformat()}
    if standalone_migration is not None:
        receipt['standalone_migration'] = standalone_migration
    with receipt_path.open('xb') as stream:
        stream.write(encoded(receipt))
    return receipt



def _load_authored_module(root, relative, name):
    path = ordinary(root / relative)
    regular(path, 8 * 1024 * 1024)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    return module


def reviewed_source_files(root):
    """Export an exact source allowlist, ignoring all input/build/runtime trees.

    Installed owners can legitimately expose a newer visible version marker;
    only the updater's verified original metadata may restore its manifest-bound
    bytes in the clean template. No save, dependency or game tree is enumerated.
    """
    core = _load_authored_module(root, 'tools/update_linux.py', '_monado_standalone_export_core')
    manifest = core.installed_sources(root)
    files = {}
    for name, identity in sorted(manifest['files'].items()):
        data = regular(root / name, 8 * 1024 * 1024)
        if (len(data) != identity['bytes'] or digest(data) != identity['sha256']) and name == 'update-version.json':
            data = core._original_metadata(root, manifest)
        if len(data) != identity['bytes'] or digest(data) != identity['sha256']:
            raise AppImageError('Source changed after export verification: ' + name)
        files[name] = (data, 0o755 if os.access(root / name, os.X_OK) else 0o644)
    data = regular(root / 'publication-manifest.json', 1024 * 1024)
    if json.loads(data) != manifest:
        raise AppImageError('Source manifest changed during template export')
    files['publication-manifest.json'] = (data, 0o644)
    return files



def standalone_build_environment(root=ROOT):
    """Only the reviewed persistent interpreter can clone its binary closure.

    Ordinary Fedora/Arch/source-script builds retain the established thin-image
    path. A malformed private-runtime marker is a hard error, not permission to
    silently switch modes after an attempted standalone package failed.
    """
    core = _load_authored_module(ordinary(root), 'tools/update_linux.py', '_monado_standalone_python_identity')
    return core.private_build_python() is not None


def standalone_package(launcher, game, output, *, root=ROOT):
    """Keep the old updater receipt contract around a standalone setup image.

    Native/input selection checks are unchanged. Only reviewed authored source
    is exported to a clean temporary tree. The standalone packager compiles its
    own authored frontend, uses locked local dependencies and performs its
    independent binary-bundle/notice/readback audit. It never packages the game.
    """
    root = ordinary(root)
    launcher, game, output = map(ordinary, (launcher, game, output))
    port = root / 'Monado_Linux'
    launcher_name = relative_build(launcher, root)
    selected_game_port = install_layout.build_port(port, game)
    game_name = relative_build(game, selected_game_port.parent)
    if not output.is_relative_to(port / 'build') or output.suffix != '.AppImage':
        raise AppImageError('AppImage output must be a fresh .AppImage below Monado_Linux/build')
    receipt_path = output.with_name(output.name + '.receipt.json')
    package_output = output.parent / 'standalone-package'
    if any(path.exists() or path.is_symlink() for path in (output, receipt_path, package_output)):
        raise AppImageError('refusing to replace an existing standalone AppImage, receipt or package directory')
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise AppImageError('native Linux x86-64 is required for AppImage packaging')
    selection = verified_selection(launcher, game, root)
    gui = regular(launcher)
    native(gui)
    if digest(gui) != selection['launcher_sha256']:
        raise AppImageError('launcher changed after receipt verification')
    legacy = dict(launcher=launcher_name, game=game_name,
                  game_port='bound' if selected_game_port != port else 'current',
                  launcher_sha256=selection['launcher_sha256'], game_sha256=selection['game_sha256'])
    files = reviewed_source_files(root)
    # A fresh update workspace has not packaged a thin image and therefore may
    # have no AppImage runtime yet. Use the same pinned, verified acquisition
    # boundary before the standalone packager reads its local dependency file.
    runtime_bytes(port)
    output.parent.mkdir(parents=True, exist_ok=True)
    ordinary(output.parent)
    with tempfile.TemporaryDirectory(prefix='.standalone-source-', dir=output.parent) as temporary:
        exported = Path(temporary) / 'source'
        exported.mkdir()
        for name, (data, mode) in files.items():
            path = exported / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
            path.chmod(mode)
        packager = _load_authored_module(exported, 'tools/build_builder_appimage.py', '_monado_legacy_standalone_packager')
        result = packager.package(exported, port, package_output, output, legacy_selection=legacy)
    # Preserve the complete standalone provenance while retaining the exact
    # source-updater schema and native selection used by existing clients.
    data = regular(output, 64 * 1024 * 1024)
    native(data, runtime=True)
    if (result.get('status') != 'passed' or result.get('artifact_kind') != 'standalone-builder-appimage'
            or result.get('archive_readback_verified') is not True or result.get('sha256') != digest(data)
            or result.get('bytes') != len(data) or result.get('requires_adjacent_workspace') is not False
            or any(result.get(key) is not False for key in ('contains_game_files', 'contains_game_executable',
                'contains_generated_game_code', 'contains_vendor_sdk'))):
        raise AppImageError('Standalone package failed the legacy updater receipt contract')
    if verified_selection(launcher, game, root) != selection or regular(launcher) != gui:
        raise AppImageError('Native selection changed during standalone packaging')
    previous = regular(receipt_path, 8 * 1024 * 1024)
    if json.loads(previous) != result:
        raise AppImageError('Standalone package receipt changed before legacy adaptation')
    result = dict(result, standalone_artifact_kind=result['artifact_kind'],
                  artifact_kind='local-launcher-appimage', **legacy)
    temporary_receipt = receipt_path.with_name('.' + receipt_path.name + '.standalone-partial')
    with temporary_receipt.open('xb') as stream:
        stream.write(encoded(result))
        stream.flush()
        os.fsync(stream.fileno())
    if regular(receipt_path, 8 * 1024 * 1024) != previous:
        temporary_receipt.unlink()
        raise AppImageError('Standalone receipt changed during adaptation')
    os.replace(temporary_receipt, receipt_path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher-executable', type=Path, required=True)
    parser.add_argument('--game-executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--standalone', action='store_true', help='use the independent setup image with reviewed persistent private Python; ordinary host builds retain their compatible workspace launcher')
    args = parser.parse_args(argv)
    try:
        standalone = args.standalone and standalone_build_environment()
        operation = standalone_package if standalone else package
        options = {'standalone_migration': 'retained-workspace-bootstrap'} if args.standalone and not standalone else {}
        result = operation(args.launcher_executable, args.game_executable, args.output, **options)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'AppImage build failed: ' + str(error) + '\n')
    print(json.dumps({key: result[key] for key in ('status', 'output', 'bytes', 'sha256', 'archive_readback_verified')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
