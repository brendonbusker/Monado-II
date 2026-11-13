"""Generate C for every module the game profile marks `lift` (T011/T013). Output: generated/<module>/*.c

Usage: gen_all.py [--profile games/xcde/profile.json] [--exefs targets/exefs] [--out generated] [--jobs N]
Prints a sha256 over the generated tree (names + contents) so a run can be compared with another (NFR-006).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def tree_hash(path):
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            h.update(os.path.relpath(p, path).replace(os.sep, '/').encode())
            with open(p, 'rb') as fh:
                h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def generator_command(python, generator, module, exefs, output, simd, patches, hle):
    # -B is an interpreter flag, not an inherited process setting. -E ignores
    # PYTHONDONTWRITEBYTECODE, so each generated-module child needs its own flag.
    return [python, '-B', '-E', '-s', generator, module['name'],
            os.path.join(exefs, module['name']), module['base'], output,
            '--simd', simd, '--patches', patches, '--hle', hle]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', default=os.path.join(ROOT, 'games', 'xcde', 'profile.json'))
    ap.add_argument('--exefs', default=os.path.join(ROOT, 'targets', 'exefs'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'generated'))
    ap.add_argument('--patches', default=os.path.join(ROOT, 'games', 'xcde', 'patches.py'))
    ap.add_argument('--hle', default=os.path.join(ROOT, 'games', 'xcde', 'hle_symbols.txt'))
    ap.add_argument('--simd', default='c', choices=('c', 'asm'))
    a = ap.parse_args(argv)
    prof = json.load(open(a.profile, encoding='utf-8'))
    gen = os.path.join(ROOT, 'tools', 'lifter', 'gen.py')
    procs = []
    t0 = time.time()
    for m in prof['modules']:
        if not m['lift']:
            continue
        out = os.path.join(a.out, m['name'])
        cmd = generator_command(sys.executable, gen, m, a.exefs, out, a.simd, a.patches, a.hle)
        log = open(os.path.join(a.out, m['name'] + '.log'), 'w') if os.path.isdir(a.out) else None
        if log is None:
            os.makedirs(a.out, exist_ok=True)
            log = open(os.path.join(a.out, m['name'] + '.log'), 'w')
        procs.append((m['name'], subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log))
    rc = 0
    for name, p, log in procs:
        r = p.wait()
        log.close()
        print(f'{name}: exit {r}')
        rc = rc or r
    print(f'generated in {time.time() - t0:.0f}s')
    if rc == 0:
        for m in prof['modules']:
            if m['lift']:
                print(f'{m["name"]}: sha256 {tree_hash(os.path.join(a.out, m["name"]))}')
    return rc


if __name__ == '__main__':
    sys.exit(main())
