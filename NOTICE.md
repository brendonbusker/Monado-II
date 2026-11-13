# Monado II notices

Monado II is a fork of Monado by TheMonadoGuy / Monado contributors, based on
LASRecomp by Peiikai. Preserve the complete inherited MIT copyright/permission
notice in each port's `LICENSE`, plus the root [LICENSE](LICENSE) and
[CREDITS](CREDITS.md). A fresh publication history does not change authorship.

Each port's detailed `NOTICE.md` records upstream code and dependency terms:
[Linux](Monado_Linux/NOTICE.md), [Windows](Monado_Windows/NOTICE.md). A platform-only
source kit includes the notice for its selected port; the other port's link applies
to the full source repository.

Reviewed source dependencies include Dear ImGui (MIT), SMAA and its upstream lookup
tables (MIT-style), AMD FidelityFX API headers (MIT), NVIDIA Streamline headers
(MIT), bcdec (MIT/Unlicense), and unmodified launcher DejaVu fonts (Bitstream Vera
license, DejaVu changes public domain). Full included notices accompany their
source. Unused third-party example fonts and examples are omitted from source kits.
SMAA.hlsl source encoding is normalized from upstream CP1252 to UTF-8; its license
and source characters are preserved. Two legacy test categories containing literal
generated-function signatures are conservatively held out; authored source guard
fixtures cover the public publication boundary instead.

Locally linked dependencies retain their own terms. In particular, the tested
Linux FFmpeg development packages enable GPL components; the optional NVIDIA NGX
SDK has proprietary terms. Source releases do not redistribute those runtime
libraries, vendor models or development sysroots. They are not approved portable
binary bundles. Selecting a future binary dependency bundle requires a separate
license/provenance review and corresponding notices/source obligations.

No game input, recompiled game code/binary, game-derived shader/cache, Nintendo
font, key, firmware, save, third-party mod or unreviewed local artwork/icon belongs
in this source distribution. Original authored shader source and licensed SMAA
lookup data are distinct from translated game shaders. No game-download or key
acquisition service is provided.

The reviewed Linux launcher illustration `gaur_plain.png` is the original
standalone image generated in the maintainer's Codex session on November 5, 2026
with OpenAI image generation, using the maintainer's generated UI concept as a
reference. No game input, screenshot, texture, shader or extracted game asset was
used. The restored file is the byte-identical original 1536×1024 RGB PNG,
2,621,747 bytes, SHA256
`4a863642bba750089667e10727cf72353875a7baf80a0903911e47d897d8fd0a`.
It is embedded in the native Linux launcher. Full provenance is recorded in
[ARTWORK_PROVENANCE.md](Monado_Linux/tools/launcher/assets/ARTWORK_PROVENANCE.md).
Inclusion makes no claim of exclusive copyright over AI-generated imagery or a
license from Nintendo/Monolith Soft for their designs or trademarks. The project
MIT license grants no such rights. Only this exact reviewed illustration is
admitted; the separate local sword icon and other unreviewed imagery are excluded.

The standard Linux local build fetches the pinned official NVIDIA SDK and builds
the native DLSS Super Resolution / DLAA provider. NVIDIA's separate SDK terms
apply; SDK binaries/models remain outside source kits and launcher images.
`--without-dlss` explicitly omits it. Setup failures are not treated as successful
DLSS builds, and existing runtime capability, namespace and network checks remain
required.

The optional local launcher AppImage builder downloads the exact hash-locked
official AppImage type2 runtime. Its source is MIT-licensed, with statically linked
dependencies under their respective terms. Preserved runtime/musl/libfuse/
squashfuse/zstd/zlib/mimalloc notices are in `tools/appimage/` and accompany each
locally generated image. The generic Roman numeral XPM is authored Monado II code
art under the project MIT license. Images contain the locally compiled launcher,
driver and notices; game executables and system/vendor library bundles stay out.
The generated image is a local workspace launcher, not a reviewed public binary
distribution or a substitute for the dependency notices of the external build.

Xenoblade Chronicles is a Nintendo trademark. Game content belongs to its rights
holders. Monado II is independent and unaffiliated; its source license grants no
rights to game content or other third-party intellectual property.


The Linux local runtime lock also pins ordinary transitive user-space dependency
packages. They are downloaded from their recorded official distribution origins,
verified and extracted only under the player's private build directory; their
copyright and license files remain there. Native glibc/GNU, graphics-driver,
audio and session interface boundaries are checked separately. No such runtime
package, driver, proprietary SDK or game executable is added to source releases
or launcher-only AppImages by this change. A future public binary bundle still
requires its own complete license and redistribution review.

The graphical-builder development preview has a separate binary packaging
boundary in `tools/build_builder_appimage.py`. Its explicit startup payload is
limited to the authored setup frontend, reviewed source template, CPython,
selected standard-library modules and support libraries, and SDL3. The exact
inventory and original copyright/license notices accompany the image; see
`tools/builder_appimage/BUNDLE_NOTICES.md`. It does not include the game's media
runtime closure, NVIDIA SDK, recompiled game or extracted game assets. This
specific setup payload does not authorize bundling arbitrary development
sysroots or other binaries. Existing source-only publication rules still apply.
