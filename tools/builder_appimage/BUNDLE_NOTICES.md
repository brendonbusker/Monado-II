# Monado II standalone builder runtime

This AppImage contains the authored SDL3/ImGui setup interface, a private CPython
3.14 runtime, and the reviewed source-only Linux build template. It contains no
game files, generated game code, playable game executable, translated game
shaders, shader caches, saves, keys or proprietary vendor SDK.

The existing Linux x86-64 / glibc 2.43+ baseline is retained. Native desktop,
graphics, audio, input and GPU-driver interfaces remain supplied by the host;
this is not a container or an operating-system runtime. In particular the pinned
SDL3 library uses the host X11/Wayland, ALSA/PulseAudio, DRM/GBM, libdecor,
libxkbcommon and FriBidi interfaces. Required build tools remain checked by the
existing dependency doctor. GPU drivers and host system packages are never
installed silently.

Included components and complete notices:

- Monado II / Monado / LASRecomp authored source: MIT, root and per-port notices.
- Dear ImGui: MIT; `ImGui-LICENSE.txt`.
- DejaVu launcher fonts: Bitstream Vera / public-domain changes;
  `DejaVu-LICENSE.txt`.
- SDL3: zlib and incorporated permissive notices; `SDL3-copyright.txt`.
- Zig-linked LLVM C++ runtime: Apache-2.0 with LLVM exceptions;
  `LLVM-libcxx-LICENSE.txt`, `LLVM-libcxxabi-LICENSE.txt`,
  `LLVM-libunwind-LICENSE.txt`.
- CPython: PSF and incorporated permissive notices; `Python-copyright.txt` and
  the private standard library's `LICENSE.txt`.
- Python's bundled support libraries: Expat, OpenSSL, libffi, SQLite, zlib,
  bzip2, XZ/liblzma, Zstandard and libuuid. Their unmodified package copyright
  files are included by exact name. The liblzma runtime is under 0BSD; the
  Zstandard runtime is used under its BSD option; SQLite is public domain;
  libuuid is BSD. GPL-only tools/modules such as Readline and GDBM are excluded.
- Official AppImage type-2 runtime: complete component notices copied from the
  existing reviewed AppImage runtime packaging. `THIRD-PARTY-NOTICES.txt`
  describes only this runtime's source/build recipes; this overview describes
  the standalone payload. The upstream runtime statically links LGPL libfuse;
  the same release page provides `monado-ii-<version>-linux-builder-runtime-sources.tar.gz`
  with the corresponding source, upstream patch, build/relinking materials and
  complete LGPL text. `RUNTIME_SOURCES.md` in that companion explains rebuilding
  a modified runtime and reusing the unchanged builder payload.

The illustration is the exact standalone generated launcher artwork documented
in the source template's `ARTWORK_PROVENANCE.md`. No game screenshot is bundled.

This build's exact component paths, hashes, sizes, compiler commands
and archive readback result are recorded in its adjacent packaging receipt.
