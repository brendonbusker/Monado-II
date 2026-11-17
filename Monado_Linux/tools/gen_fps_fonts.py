#!/usr/bin/env python3
"""Embed the two unmodified, licensed FPS fonts into a build-local C++ header.

No game assets, installed fonts or network requests are used. The native build
binds these source bytes and carries the unchanged licence as a companion.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

FONTS = (('DejaVuSans.ttf', 'fps_font_sans'),
         ('DejaVuSerif-Bold.ttf', 'fps_font_serif'))
LICENSE = 'LICENSE-DejaVu.txt'
MAX_ASSET = 2 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_source(path, *, font=False):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError('FPS font source must be canonical without links')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_ASSET:
        raise ValueError('FPS font source must be a bounded ordinary single-link file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(MAX_ASSET + 1)
        after = os.fstat(stream.fileno())
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if (identity(before) != identity(opened) or identity(opened) != identity(after)
            or identity(after) != identity(path.lstat()) or len(data) != before.st_size
            or path.resolve() != path):
        raise ValueError('FPS font source changed while reading')
    if font and (len(data) < 12 or data[:4] not in (b'\x00\x01\x00\x00', b'OTTO')):
        raise ValueError('FPS font source needs an sfnt signature')
    return data


def generate(assets, output_header):
    assets, output_header = Path(assets).absolute(), Path(output_header).absolute()
    if assets.resolve() != assets or not assets.is_dir():
        raise ValueError('FPS font directory must be canonical')
    if (output_header.parent.resolve() != output_header.parent
            or not output_header.parent.is_dir() or output_header.exists() or output_header.is_symlink()):
        raise ValueError('FPS font header requires a fresh file in an ordinary directory')
    # Check every source before creating the generated file.
    sources = [(name, symbol, read_source(assets / name, font=True)) for name, symbol in FONTS]
    licence = read_source(assets / LICENSE)
    if 'Bitstream' not in licence.decode('utf-8'):
        raise ValueError('FPS fonts require their complete redistribution notice')
    lines = ['// Generated from unmodified DejaVu fonts; see DejaVu-font-license.txt.', '#pragma once', '']
    for name, symbol, data in sources:
        lines.append('inline constexpr unsigned char ' + symbol + '[] = {')
        lines.extend('    ' + ','.join('0x%02x' % value for value in data[start:start + 24]) + ','
                     for start in range(0, len(data), 24))
        lines.extend(('};', ''))
    encoded = '\n'.join(lines).encode('ascii')
    with output_header.open('xb') as stream:
        stream.write(encoded)
    return dict(schema=1, scope='unmodified licensed FPS font embedding only',
                fonts={name: dict(bytes=len(data), sha256=digest(data), symbol=symbol)
                       for name, symbol, data in sources},
                licence=dict(source=LICENSE, bytes=len(licence), sha256=digest(licence)),
                header=dict(bytes=len(encoded), sha256=digest(encoded)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.assets, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
