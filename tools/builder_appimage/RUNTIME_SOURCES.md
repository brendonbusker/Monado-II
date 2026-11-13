# AppImage runtime source and relinking materials

This companion accompanies the public Monado II builder AppImage. It contains
official sources for its separate AppImage type-2 runtime, libfuse 3.15.0,
and squashfuse 0.5.2, together with the runtime's build scripts
and libfuse patch, full LGPL 2.1 text, a local-source relinking recipe and this
guide. `MANIFEST.json` and `SHA256SUMS` identify every companion file. It contains
no game input, game-derived code, playable game executable, shader/cache, save,
key, vendor SDK or compiled runtime executable. The runtime and squashfuse archives are verbatim upstream archives. The
libfuse source archive retains all preferred library/interface/build/manual-page
source bytes, omitting only `doc/html/` (generated documentation) and
`doc/fast17-vangoor.pdf` (an unrelated academic paper). `MANIFEST.json` records
the original official archive hash plus a per-file hash/size/mode inventory for
every retained and excluded file. The original archive itself is not modified
in the download cache. No library source, interface or build script is omitted.

The exact original runtime is AppImage/type2-runtime revision
`fedfad51acc2860b2916a1eef32ba4a500ff31ef`, binary SHA-256
`617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46`.
Its MIT source statically links LGPL-2.1 libfuse. Library modifications and
relinking for personal use, including reverse engineering to debug those
modifications, are permitted under the supplied licenses. Source and relinking
materials are distributed from the same release page as the AppImage using the
LGPL 2.1 section 6(a)/(d) route; there is no request-only source offer.

The preferred sources and upstream libfuse patch correspond to the recorded
revision. Upstream uses `alpine:3.21` and distribution packages for musl, zstd,
zlib, mimalloc and the compiler. Those package revisions were not fully pinned
by upstream. The recipe below rebuilds a replacement runtime; it does not claim
a byte-identical reproduction of the downloaded official executable. The
permissive library notices accompanying the AppImage remain applicable. The
builder/CPython/SDL payload is a separate aggregate and stays unchanged when
replacing the FUSE runtime.

## Rebuild with a modified libfuse

Install/use a Docker implementation yourself if you want this optional developer
workflow. None of these commands run during Monado setup. Run them from the
extracted companion folder. The build dependencies install inside the container.

```sh
sha256sum -c SHA256SUMS
mkdir relink-work
tar -xf archives/appimage-type2-runtime-fedfad51.tar.gz -C relink-work
tar -xf archives/fuse-3.15.0-source.tar.gz -C relink-work
tar -xf archives/squashfuse-0.5.2.tar.gz -C relink-work
patch -d relink-work/fuse-3.15.0 -p1 < relink-work/type2-runtime-fedfad51acc2860b2916a1eef32ba4a500ff31ef/patches/libfuse/mount.c.diff
cp Dockerfile.runtime-relink relink-work/Dockerfile
printf '%s\n' 'https://github.com/AppImage/type2-runtime/commit/fedfad5' > relink-work/type2-runtime-fedfad51acc2860b2916a1eef32ba4a500ff31ef/src/runtime/version
```

Make your changes in `relink-work/fuse-3.15.0`. Keep its license/change notices.
The recipe builds that local tree rather than downloading a replacement copy,
then rebuilds squashfuse and statically relinks the runtime against your library.

```sh
docker buildx build --platform linux/amd64 --output type=local,dest=./relinked-runtime relink-work
```

The output includes `relinked-runtime/runtime-x86_64` and its debug file. The
original upstream build workflow and alternative instructions are in the
runtime source archive's `BUILD.md` and `.github/workflows/build.yaml`.

## Use the rebuilt runtime with the original builder payload

Copy the original builder AppImage into this working folder as `original.AppImage`.
The runtime reports the boundary of its SquashFS payload. Preserve that payload
and prepend your rebuilt runtime:

```sh
chmod +x original.AppImage
offset="$(./original.AppImage --appimage-offset)"
tail -c "+$((offset + 1))" original.AppImage > builder-payload.squashfs
cat relinked-runtime/runtime-x86_64 builder-payload.squashfs > Monado-II-custom-runtime.AppImage
chmod +x Monado-II-custom-runtime.AppImage
./Monado-II-custom-runtime.AppImage --appimage-extract-and-run --dry-run
```

Run the modified copy separately from managed installation/update directories.
Its outer checksum naturally differs from an official image; immutable managed
receipts are not rewritten. The standalone copy can open setup with `--setup`
and adopt your existing installation. No game rebuild or save conversion is
needed to replace only the AppImage mount runtime.

## Original sources

- AppImage runtime source, scripts and patch: <https://github.com/AppImage/type2-runtime/tree/fedfad51acc2860b2916a1eef32ba4a500ff31ef>
- libfuse source: <https://github.com/libfuse/libfuse/releases/tag/fuse-3.15.0>
- squashfuse source: <https://github.com/vasi/squashfuse/tree/0.5.2>
- LGPL 2.1: <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>

The source archives remain under their original licenses. Authored Monado II
packaging code/recipe/documentation is MIT; `LICENSE-Monado-II.txt` accompanies it.
