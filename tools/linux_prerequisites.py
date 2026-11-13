#!/usr/bin/env python3
"""[XCDE] LINUX-066: read-only Linux prerequisite diagnosis and explicit repair.

This helper needs only Python 3.9+ standard library so it can explain a missing
3.14 build interpreter. Normal checks never install packages or read game/state
files. The existing pinned setup and runtime graph remain the final build gates.
Only explicit --install-deps, a confirmed Fedora 45 Distrobox and an interactive
ordinary user can reach the fixed container package-manager command.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = '/usr/bin:/bin'
INSPECT_PATH = '/usr/sbin:/sbin:' + BUILD_PATH
MAX_OUTPUT = 2 * 1024 * 1024
TOOLS = ('bash', 'pkg-config', 'dpkg-deb', 'readelf', 'mksquashfs', 'unsquashfs')
GNU_VERSIONS = ('GLIBCXX_3.4.32', 'CXXABI_1.3.9')
# Authored requirement inventory from the already audited e857 closure. This is
# keyed to the complete unchanged source lock, not the broader allowed boundary.
# It lets a first-time setup report all required native clients before extraction.
AUDITED_HOST_REQUIREMENTS = {
    'e85790dc4e846268ffaee48aa9b321997a58bc9de8786fbcf36f6b538518352d': (
        'ld-linux-x86-64.so.2', 'libOpenCL.so.1', 'libasound.so.2', 'libc.so.6',
        'libdecor-0.so.0', 'libdrm.so.2', 'libgbm.so.1', 'libgcc_s.so.1',
        'libm.so.6', 'libmvec.so.1', 'libpulse.so.0', 'libresolv.so.2',
        'libstdc++.so.6', 'libva-drm.so.2', 'libva-x11.so.2', 'libva.so.2',
        'libvdpau.so.1', 'libvpl.so.2')}
FEDORA_TOOLS = {'python3.14': 'python3.14', 'bash': 'bash',
    'pkg-config': 'pkgconf-pkg-config', 'dpkg-deb': 'dpkg', 'readelf': 'binutils',
    'nm': 'binutils', 'mksquashfs': 'squashfs-tools',
    'unsquashfs': 'squashfs-tools', 'bwrap': 'bubblewrap'}
FEDORA_LIBS = {'libasound.so.2': 'alsa-lib', 'libpulse.so.0': 'pulseaudio-libs',
    'libdecor-0.so.0': 'libdecor', 'libdrm.so.2': 'libdrm',
    'libgbm.so.1': 'mesa-libgbm', 'libEGL.so.1': 'libglvnd-egl',
    'libGL.so.1': 'libglvnd-glx', 'libGLX.so.0': 'libglvnd-glx',
    'libGLdispatch.so.0': 'libglvnd', 'libOpenGL.so.0': 'libglvnd-opengl',
    'libOpenCL.so.1': 'ocl-icd', 'libva.so.2': 'libva', 'libva-drm.so.2': 'libva',
    'libva-x11.so.2': 'libva', 'libvdpau.so.1': 'libvdpau',
    'libvpl.so.2': 'libvpl', 'libgcc_s.so.1': 'libgcc',
    'libstdc++.so.6': 'libstdc++'}
UBUNTU_TOOLS = dict(FEDORA_TOOLS, **{'pkg-config': 'pkg-config',
    'bwrap': 'bubblewrap', 'python3.14-venv': 'python3.14-venv'})
UBUNTU_LIBS = {'libasound.so.2': 'libasound2t64', 'libpulse.so.0': 'libpulse0',
    'libdecor-0.so.0': 'libdecor-0-0', 'libdrm.so.2': 'libdrm2',
    'libgbm.so.1': 'libgbm1', 'libEGL.so.1': 'libegl1', 'libGL.so.1': 'libgl1',
    'libGLX.so.0': 'libglx0', 'libGLdispatch.so.0': 'libglvnd0',
    'libOpenGL.so.0': 'libopengl0', 'libOpenCL.so.1': 'ocl-icd-libopencl1',
    'libva.so.2': 'libva2', 'libva-drm.so.2': 'libva-drm2',
    'libva-x11.so.2': 'libva-x11-2', 'libvdpau.so.1': 'libvdpau1',
    'libvpl.so.2': 'libvpl2', 'libgcc_s.so.1': 'libgcc-s1',
    'libstdc++.so.6': 'libstdc++6'}
ARCH_TOOLS = dict(FEDORA_TOOLS, **{'pkg-config': 'pkgconf'})
# Rolling Arch's package named python may move to another major version. Do not
# claim a reviewed CPython 3.14 provider or fabricate a python3.14 package name.
ARCH_TOOLS.pop('python3.14')
ARCH_LIBS = dict(FEDORA_LIBS, **{'libpulse.so.0': 'libpulse',
    'libgbm.so.1': 'mesa', 'libEGL.so.1': 'libglvnd', 'libGL.so.1': 'libglvnd',
    'libGLX.so.0': 'libglvnd', 'libOpenGL.so.0': 'libglvnd'})


def bounded_text(path, limit=MAX_OUTPUT):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing or oversized metadata: ' + str(path))
    return path.read_text(errors='replace')


def os_release(path=Path('/etc/os-release')):
    """Parse simple data, never source/eval a file or follow host OS metadata."""
    result = {}
    try:
        raw = bounded_text(path, 65536)
    except (OSError, ValueError):
        return result
    for line in raw.splitlines():
        match = re.fullmatch(r'([A-Z_]+)=(.*)', line)
        if not match or match[1] not in ('ID', 'ID_LIKE', 'VERSION_ID', 'PRETTY_NAME'):
            continue
        value = match[2]
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            continue
        if match[1] != 'PRETTY_NAME' and not re.fullmatch(r'[A-Za-z0-9 ._-]*', value):
            continue
        result[match[1]] = value
    return result


def ordinary_executable(path, *, directory=None):
    """Reject forwarding helpers and executables resolved outside system bins."""
    path = Path(path)
    try:
        target = path.resolve(strict=True)
        if not target.is_file() or not os.access(target, os.X_OK):
            return None
        if directory is not None and target.parent != Path(directory).resolve():
            return None
        if 'distrobox-host-exec' in str(target):
            return None
        return str(path)
    except (OSError, ValueError):
        return None


def system_tool(name, path=BUILD_PATH):
    selected = shutil.which(name, path=path)
    if selected is None:
        return None
    try:
        target = Path(selected).resolve(strict=True)
        roots = {Path(p).resolve() for p in path.split(':')}
        if target.parent not in roots or 'distrobox-host-exec' in str(target):
            return None
    except (OSError, ValueError):
        return None
    return ordinary_executable(selected)


def admin_tool(path):
    selected = ordinary_executable(path, directory='/usr/bin')
    if selected is None:
        return None
    info = Path(selected).resolve().stat()
    if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return None
    return selected


def run_readonly(argv, timeout=15):
    result = subprocess.run(list(map(str, argv)), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout,
        env={'PATH': INSPECT_PATH, 'LANG': 'C', 'LC_ALL': 'C'})
    if len(result.stdout or '') > MAX_OUTPUT or len(result.stderr or '') > MAX_OUTPUT:
        raise ValueError('Prerequisite inspection output exceeds its bound')
    return result


def detect_container(environ=None, *, markers=None, helper=None):
    environ = os.environ if environ is None else environ
    if markers is None:
        markers = [Path('/run/.containerenv'), Path('/.dockerenv')]
    marker = any(path.is_file() and not path.is_symlink() for path in markers)
    helper = Path('/usr/bin/distrobox-host-exec') if helper is None else Path(helper)
    helper_present = helper.is_file() and os.access(helper, os.X_OK)
    name = environ.get('CONTAINER_ID', '')
    safe_name = bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name))
    confirmed = bool(marker and helper_present and safe_name)
    return {'kind': 'distrobox' if confirmed else ('container' if marker else 'native'),
            'name': name if confirmed else None,
            'distrobox_confirmed': confirmed,
            'scope': 'Current userspace; container detection is not a security sandbox guarantee'}


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)*', value):
        return None
    return tuple(map(int, value.split('.')))


def find_python314():
    selected = sys.executable if sys.version_info[:2] == (3, 14) else shutil.which('python3.14')
    if not selected:
        return None
    try:
        result = run_readonly([selected, '-I', '-B', '-c',
            'import sys, venv; print("%d.%d.%d" % sys.version_info[:3])'])
        value = result.stdout.strip()
        return str(Path(selected).absolute()) if result.returncode == 0 and version_tuple(value) and version_tuple(value)[:2] == (3, 14) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def library_paths(names):
    paths = {}
    tool = system_tool('ldconfig', INSPECT_PATH)
    if tool:
        result = run_readonly([tool, '-p'])
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                match = re.fullmatch(r'\s*([^\s/]+)\s+\(([^)]*)\)\s+=>\s+(/[^\n]+)', line)
                if match and 'x86-64' in match[2]:
                    paths.setdefault(match[1], Path(match[3]))
    for name in names:
        if name in paths:
            continue
        for directory in ('/usr/lib/x86_64-linux-gnu', '/lib/x86_64-linux-gnu', '/usr/lib64', '/lib64', '/usr/lib', '/lib'):
            candidate = Path(directory) / name
            if candidate.is_file():
                paths[name] = candidate
                break
    return paths


def required_host_interfaces(root, lock):
    """Use actual receipted closure, never all allowed host interface names."""
    port = root / 'Monado_Linux'
    try:
        tag = hashlib.sha256((port / 'graphics-deps-linux.lock.json').read_bytes()).hexdigest()
        allowed = lock.get('runtime', {}).get('host_sonames', {})
        audited = AUDITED_HOST_REQUIREMENTS.get(tag)
        if audited and all(name in allowed for name in audited):
            return list(audited)
        selected = Path(bounded_text(port / '.deps/graphics/active-sysroot.txt', 8192).strip())
        base = (port / '.deps/graphics/sysroots').resolve()
        if selected.resolve() != selected or not selected.is_relative_to(base):
            return None
        marker = json.loads(bounded_text(selected / '.monado-deps.json'))
        names = marker.get('required_host_interfaces')
        if (marker.get('lock_sha256') != tag or not isinstance(names, list)
                or not names or any(not isinstance(name, str) or name not in allowed for name in names)):
            return None
        return sorted(set(names))
    except (OSError, ValueError, TypeError):
        return None


def package_maps(release):
    identity = release.get('ID', '')
    family = release.get('ID_LIKE', '').split()
    if identity in ('fedora', 'bazzite') or 'fedora' in family:
        return 'fedora', FEDORA_TOOLS, FEDORA_LIBS
    if identity in ('ubuntu', 'debian') or 'debian' in family:
        return 'debian', UBUNTU_TOOLS, UBUNTU_LIBS
    if identity in ('arch', 'cachyos', 'steamos') or 'arch' in family:
        return 'arch', ARCH_TOOLS, ARCH_LIBS
    return None, {}, {}


def inspect_environment(root=ROOT, without_dlss=False, game_only=False):
    root = Path(root).resolve()
    release = os_release()
    context = detect_container()
    report = {'schema': 1, 'mode': 'check', 'monado_version': 'unknown',
        'platform': sys.platform, 'architecture': platform.machine(),
        'distribution': release, 'context': context, 'build_path': BUILD_PATH,
        'issues': [], 'notes': [], 'tools': {}, 'packages': [],
        'read_only': True, 'scope': 'Prerequisite checks only; private setup/runtime graph remain mandatory'}
    def issue(kind, name, message, *, blocking_install=False):
        report['issues'].append({'kind': kind, 'name': name, 'message': message,
                                'blocks_installation': blocking_install})
    try:
        report['monado_version'] = json.loads(bounded_text(root / 'update-version.json', 65536)).get('version', 'unknown')
        lock = json.loads(bounded_text(root / 'Monado_Linux/graphics-deps-linux.lock.json'))
    except (OSError, ValueError, TypeError) as error:
        lock = {}
        issue('metadata', 'source', 'Cannot read prerequisite source metadata: ' + str(error), blocking_install=True)
    minimum = lock.get('runtime', {}).get('minimum_glibc', '2.43')
    if version_tuple(minimum) is None:
        issue('metadata', 'minimum-glibc', 'Invalid glibc requirement metadata.', blocking_install=True)
        minimum = '2.43'
    report['minimum_glibc'] = minimum
    if sys.platform != 'linux' or report['architecture'] != 'x86_64':
        issue('platform', 'linux-x86_64', 'This build requires Linux x86-64.', blocking_install=True)
    getconf = system_tool('getconf')
    report['glibc'] = None
    if getconf:
        try:
            result = run_readonly([getconf, 'GNU_LIBC_VERSION'])
            match = re.fullmatch(r'glibc (\d+(?:\.\d+)+)', result.stdout.strip())
            if result.returncode == 0 and match:
                report['glibc'] = match[1]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if report['glibc'] is None or version_tuple(report['glibc']) < version_tuple(minimum):
        issue('abi', 'glibc', 'Current glibc is %s; this build requires %s+. Use a compatible container/image; adding packages does not repair an older libc baseline.' % (report['glibc'] or 'unavailable', minimum), blocking_install=True)
    python = find_python314()
    report['python314'] = python
    if python is None:
        issue('tool', 'python3.14', 'No usable CPython 3.14 build environment was found (the standard-library venv module is required).')
        if release.get('ID') in ('ubuntu', 'debian'):
            issue('tool', 'python3.14-venv', 'CPython 3.14 venv support could not be verified.')
    required = [name for name in TOOLS if not game_only or name not in ('mksquashfs', 'unsquashfs')]
    if not without_dlss:
        required.extend(('nm', 'bwrap'))
    for name in required:
        selected = system_tool(name)
        report['tools'][name] = selected
        if not selected or name == 'bwrap' and selected != '/usr/bin/bwrap':
            issue('tool', name, 'Missing trusted build tool %s in %s.' % (name, BUILD_PATH))
    names = required_host_interfaces(root, lock)
    report['host_interfaces'] = names
    if names is None:
        report['notes'].append('Native client library requirements will be checked after private graphics dependencies are extracted; no allowed-but-unused interface is required by this check.')
        names = []
    if not without_dlss and 'libstdc++.so.6' not in names:
        names = [*names, 'libstdc++.so.6']
    try:
        providers = library_paths(names)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        providers = {}
        report['notes'].append('Library discovery incomplete: ' + str(error))
    report['host_providers'] = {}
    for name in names:
        path = providers.get(name)
        if path is None or not path.is_file():
            metadata = lock.get('runtime', {}).get('host_sonames', {}).get(name, {})
            issue('library', name, 'Missing native library ' + name + '.', blocking_install=metadata.get('category') == 'glibc')
        else:
            report['host_providers'][name] = str(path)
    cxx = providers.get('libstdc++.so.6')
    readelf = report['tools'].get('readelf')
    if 'libstdc++.so.6' in names and cxx is not None and cxx.is_file() and readelf:
        try:
            result = run_readonly([readelf, '-VW', cxx])
            definitions = result.stdout.split('Version definition section', 1)[-1].split('Version needs section', 1)[0]
            defined = set(re.findall(r'Name: ((?:GLIBCXX|CXXABI)_[A-Za-z0-9_.]+)', definitions))
            missing = sorted(set(GNU_VERSIONS) - defined)
            if result.returncode or missing:
                issue('abi', 'libstdc++.so.6', 'Native GNU C++ runtime lacks required versions: ' + ', '.join(missing or GNU_VERSIONS) + '. Use a compatible distribution runtime/image.', blocking_install=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            issue('abi', 'libstdc++.so.6', 'Cannot inspect native GNU C++ runtime: ' + str(error), blocking_install=True)
    family, tools, libs = package_maps(release)
    report['package_family'] = family
    packages = set()
    for item in report['issues']:
        package = tools.get(item['name']) if item['kind'] == 'tool' else libs.get(item['name']) if item['kind'] == 'library' else None
        item['package'] = package
        if package:
            packages.add(package)
    report['packages'] = sorted(packages)
    report['compatible'] = not report['issues']
    report['installation_supported'] = bool(release.get('ID') == 'fedora' and release.get('VERSION_ID') == '45' and context['distrobox_confirmed'] and report['glibc'] and version_tuple(report['glibc']) >= (2, 44))
    report['status'] = 'passed' if report['compatible'] else 'missing-prerequisites'
    report['instructions'] = instructions(report)
    return report


def instructions(report):
    release = report['distribution']; packages = report['packages']
    if any(item['blocks_installation'] for item in report['issues']):
        return ['Resolve the incompatible platform/runtime first; this script will not upgrade the OS or replace libc.']
    if not report['issues']:
        return []
    if not packages:
        return ['Install the reported requirements using your distribution documentation; no package mapping is known for this environment.']
    names = ' '.join(shlex.quote(name) for name in packages)
    if release.get('ID') == 'bazzite' and report['context']['kind'] == 'native':
        return ['Native Bazzite package layering: rpm-ostree install ' + names,
                'Reboot into the new deployment, then run ./Build_Monado_II.sh again. No host layering or reboot is performed by this script.']
    if release.get('ID') == 'steamos' and report['context']['kind'] == 'native':
        return ['Use a compatible Distrobox image with glibc ' + report['minimum_glibc'] + '+ and CPython 3.14, then run this same build script inside it. SteamOS is not unlocked or modified.']
    family = report['package_family']
    command = ('sudo dnf install ' if family == 'fedora' else 'sudo apt-get install ' if family == 'debian' else 'sudo pacman -S --needed ' if family == 'arch' else None)
    result = [command + names] if command else []
    if family == 'arch' and any(item['name'] == 'python3.14' for item in report['issues']):
        result.append('Provide a supported CPython 3.14 interpreter with venv support separately; the rolling distribution package named python may select another version. No exact package provider is asserted here.')
    if report['installation_supported']:
        result.append('To review/install these container packages and continue: ./Build_Monado_II.sh --install-deps')
    else:
        result.append('Automatic package installation is currently limited to confirmed Fedora 45 Distrobox environments. Existing native installs retain manual system-package setup.')
    return result


def format_report(report):
    release = report['distribution']
    context = report['context']
    lines = ['Monado II %s prerequisite check' % report['monado_version'],
        'Environment: %s; %s%s; glibc %s (required %s+)' % (
            release.get('PRETTY_NAME', release.get('ID', 'unknown distribution')),
            context['kind'], ' ' + context['name'] if context['name'] else '',
            report['glibc'] or 'unavailable', report['minimum_glibc'])]
    if report['compatible']:
        lines.append('Prerequisites: ready for the checked local build.')
    else:
        for item in report['issues']:
            lines.append('- ' + item['message'] + (' Package: ' + item['package'] + '.' if item.get('package') else ''))
        lines.extend(report['instructions'])
    if report['notes']:
        lines.extend('Note: ' + note for note in report['notes'])
    lines.append('No game or save files were read or changed. Private dependency setup and final loadability checks still run during the build.')
    return '\n'.join(lines)


def install_dependencies(report, *, inspector=None, runner=None):
    """Explicit interactive container-only transaction; never elevate the build."""
    if report['compatible']:
        return report
    if not report['installation_supported']:
        raise ValueError('Automatic installation refused: a confirmed Fedora 45 Distrobox is required. Follow the printed instructions.')
    if any(item['blocks_installation'] for item in report['issues']):
        raise ValueError('Automatic installation refused: this environment has an incompatible or unverified base runtime.')
    if not report['packages'] or any(not item.get('package') for item in report['issues']):
        raise ValueError('Automatic installation refused: not every missing prerequisite has a reviewed package mapping.')
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Package installation needs an interactive terminal. Background/update builds never install packages; run ./Build_Monado_II.sh --install-deps in a terminal.')
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise ValueError('Run the build as your ordinary container user. Only the package-manager command may use sudo.')
    # Re-check real context immediately before requesting any privilege. A
    # caller-provided/faked report alone cannot select a host installer.
    release = os_release(); context = detect_container()
    if release.get('ID') != 'fedora' or release.get('VERSION_ID') != '45' or not context['distrobox_confirmed']:
        raise ValueError('Container identity changed or could not be confirmed; package installation refused.')
    manager = admin_tool('/usr/bin/dnf5')
    sudo = admin_tool('/usr/bin/sudo')
    if manager is None or sudo is None:
        raise ValueError('Trusted /usr/bin/dnf5 and /usr/bin/sudo are required for explicit container repair. Use the printed manual command.')
    allowed = set(FEDORA_TOOLS.values()) | set(FEDORA_LIBS.values())
    packages = report['packages']
    if any(not isinstance(name, str) or name not in allowed for name in packages):
        raise ValueError('Package repair request contains an unreviewed package name.')
    command = [sudo, '--', manager, '--setopt=install_weak_deps=False', 'install', *packages]
    print('Installing prerequisites only in Fedora 45 Distrobox %s.' % context['name'], flush=True)
    print('Command: ' + shlex.join(command), flush=True)
    print('Review the package-manager transaction; it may request your container sudo password. Compilation will remain under your ordinary user.', flush=True)
    operation = runner or subprocess.run
    result = operation(command, env={'PATH': INSPECT_PATH, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}, check=False)
    if result.returncode:
        raise ValueError('Container package installation stopped (exit %s). Authentication, cancellation, unavailable packages or network errors must be resolved before retrying. Existing builds and saves were not touched.' % result.returncode)
    checked = (inspector or inspect_environment)()
    if not checked['compatible']:
        raise ValueError('Package installation finished but prerequisites are still incomplete:\n' + format_report(checked))
    checked.update(mode='install-deps', read_only=False, installed_packages=list(packages))
    return checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='read-only prerequisite diagnosis (default)')
    mode.add_argument('--install-deps', action='store_true', help='explicit interactive repair inside supported Distrobox only')
    parser.add_argument('--json', action='store_true', help='read-only machine-readable report')
    parser.add_argument('--without-dlss', action='store_true')
    parser.add_argument('--game-only', action='store_true')
    args = parser.parse_args(argv)
    if args.json and args.install_deps:
        parser.error('--json is read-only and cannot be combined with --install-deps')
    try:
        inspector = lambda: inspect_environment(without_dlss=args.without_dlss, game_only=args.game_only)
        report = inspector()
        if args.install_deps:
            if not report['compatible']:
                print(format_report(report), flush=True)
            report = install_dependencies(report, inspector=inspector)
        print(json.dumps(report, indent=2) if args.json else format_report(report))
        return 0 if report['compatible'] else 1
    except KeyboardInterrupt:
        print('Prerequisite setup cancelled; no build was started.', file=sys.stderr)
        return 130
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Monado II prerequisite check stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
