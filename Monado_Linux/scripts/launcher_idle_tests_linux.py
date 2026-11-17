#!/usr/bin/env python3
"""[XCDE] LINUX-126: actual launcher idle/lifecycle tests using SDL dummy only.

Use a passed current launcher receipt for its exact toolchain and nonlauncher
objects. Inject only OS presentation/focus facts and authored child/IPC sources.
Never execute a game ELF, display a window or read a player's input/state.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from boot_smoke_linux import bounded_process

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/native/test_launcher_idle_linux.cpp'
CASES = ('foreground', 'background-game', 'hidden-child', 'hidden-broker-exit',
         'hidden-broker-disconnect', 'hidden-update-ready', 'hidden-update-cancel', 'hidden-precompile-cancel', 'focus-controller')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, action='append')
    args = parser.parse_args()
    build, output = args.build.resolve(), args.output.absolute()
    if not (build.is_relative_to(ROOT / 'build') or build.is_relative_to(ROOT / 'runs')):
        parser.error('build must be under this port build/ or runs/')
    if output.exists() or output != output.resolve() or not output.is_relative_to(ROOT / 'runs'):
        parser.error('fresh canonical private runs/ output required')
    receipt = json.loads((build / 'receipt.json').read_text())
    if receipt.get('status') != 'passed' or receipt.get('artifact_kind') != 'linux-launcher':
        parser.error('passed native Linux launcher receipt required')
    for name, expected in receipt['sources_after'].items():
        if digest(ROOT / name) != expected:
            parser.error('current source differs from launcher receipt: ' + name)
    os.umask(0o077)
    output.mkdir(parents=True)
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'TMPDIR': str(output), 'SDL_VIDEO_DRIVER': 'dummy', 'SDL_RENDER_DRIVER': 'software',
                   'LD_LIBRARY_PATH': receipt['dependencies']['sysroot'] + '/usr/lib/x86_64-linux-gnu'}
    result = {'scope': __doc__, 'build_receipt_sha256': digest(build / 'receipt.json'),
              'fixture_sha256': digest(FIXTURE), 'runner_sha256': digest(__file__),
              'status': 'running', 'commands': [], 'cases': []}

    def save():
        (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')

    def run(name, command, seconds=20):
        row = {'name': name, 'argv': list(map(str, command)), 'cwd': str(ROOT), 'environment': environment}
        result['commands'].append(row)
        save()
        completion = {}
        try:
            bounded_process(row['argv'], cwd=ROOT, env=environment, seconds=seconds, completion=completion)
        finally:
            row.update(completion.get('record', {}))
            for stream in ('stdout', 'stderr'):
                content = completion.get(stream, b'')
                (output / (name + '.' + stream + '.log')).write_bytes(content)
                row[stream + '_sha256'] = hashlib.sha256(content).hexdigest()
            save()
        if row.get('exit') != 0 or row.get('timed_out') or row.get('remaining_owned_pids') or row.get('cleanup_errors'):
            raise RuntimeError(name + ': inspect preserved command logs')
        print(name, 'PASS', flush=True)
        return completion.get('stdout', b'').decode(errors='replace')

    command = list(next(c for c in receipt['commands'] if '-c' in c['argv'] and
                   str(c['argv'][c['argv'].index('-c') + 1]).endswith('tools/launcher/launcher.cpp'))['argv'])
    command[command.index('-c') + 1] = str(FIXTURE)
    command[command.index('-o') + 1] = str(output / 'fixture.o')
    run('compile-fixture', command, 120)
    command = list(next(c for c in receipt['commands'] if c['name'] == 'link-launcher')['argv'])
    command[command.index(receipt['objects']['tools/launcher/launcher.cpp']['path'])] = str(output / 'fixture.o')
    binary = output / 'launcher-idle-fixture'
    command[command.index('-o') + 1] = str(binary)
    run('link-fixture', command, 120)
    result['binary_sha256'] = digest(binary)
    for case in args.case or CASES:
        work = output / case
        project, source, state = work / 'project', work / 'authored-input', work / 'state'
        (project / 'scripts').mkdir(parents=True)
        (source / 'exefs').mkdir(parents=True)
        (source / 'romfs').mkdir()
        state.mkdir()
        (source / 'exefs/main').write_text('AUTHORED FIXTURE; NO GAME DATA\n')
        placeholder = project / 'never-executed'
        placeholder.write_text('AUTHORED PLACEHOLDER; NEVER EXECUTED\n')
        placeholder.chmod(0o700)
        (state / 'xcde.ini').write_text('volume = 27\nlauncher_lang = en\n')
        text = run(case, [binary, case, '--project-root', project, '--input-root', source,
                          '--game-executable', placeholder, '--state-root', state])
        match = re.search(r'^launcher idle: PASS (.+)$', text, re.M)
        if not match:
            raise RuntimeError(case + ': missing fixture result')
        result['cases'].append(dict(field.split('=', 1) for field in match[1].split()))
        save()
    result['status'] = 'passed'
    save()


if __name__ == '__main__':
    main()
