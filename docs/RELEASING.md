# Release assets and publication boundaries

Linux and Windows use independent implementation versions. The combined GitHub
release is ordinary/latest for Linux stable update discovery; Windows is clearly
labelled experimental in its identity, download instructions and release notes.
Do not mark the whole release prerelease merely to label Windows experimental,
since both current update clients check the ordinary latest release.

## Linux0.1.28

Publish the reviewed standalone builder AppImage, Linux source/setup tarball,
byte-identical legacy `-source.tar.gz` alias, AppImage runtime source/relink
companion and combinedSHA256SUMS. The internal legacy source-root name is retained
for existing Linux updater compatibility. Source archives contain no binaries,
input, generated code, game shaders/caches, saves, keys or vendor SDKs.

The public0.1.28 standalone AppImage contains setup software and its reviewed
private startup runtime. Game/runtime compilation remains local. Local migration
images may also contain a verified authored runtime; that local transport is not
a public binary redistribution approval. The
locally generated game-code library is excluded. Vendor/model resources omitted
from the public bundle are prepared locally under their own terms. Packaging
requires exact source, license, ABI, symbol/link-provenance and archive readback
checks; a transport envelope alone is not redistribution approval.

From a canonical, clean, reviewed export, use `tools/publication_guard.py`,
`tools/package_source_release.py --platform linux`,
`tools/build_builder_appimage.py`, and
`tools/package_builder_runtime_sources.py`. Outputs must be fresh and outside
reviewed source. Never delete a player's input/state to satisfy a source guard.
Retain private receipts, dependency identities and compiler commands separately.
Check standalone self-test/hidden startup and actual old-client source discovery,
checksum, extraction and rebuild classification before activation/publication.
A migration AppImage must also fit the installed updater's64MiB bound.
For 0.1.28, retain the earlier build-path regression fixtures and qualify an
isolated existing-installation update, including full native game and launcher
preparation and activation. Do not modify the immutable old updater or relabel a
newer binary to make the test pass. Keep the accepted development source and
manual 2x/20x Prison Island result separate from release packaging evidence.
Historical 0.1.24-to-0.1.26 split-game regeneration evidence remains recorded;
a source-discovery pass alone does not establish a successful update.

## WindowsExperimental0.1.0

The user-facing download is **MonadoII-Windows-Setup.exe**. Also publish its exact
`monado-ii-windows-0.1.0-setup.zip`, `monado-ii-windows-update.json`, native source
and Python/tool source companions, Windows notes and combined checksums. The
source/update ZIP must match the EXE's embedded source. Do not substitute a new
archive from a different source freeze without rebuilding/requalifying the EXE.

The native companion includes matching component sources, recipes, patches,
notices and frontend relink inputs. The Python/tool companion provides its matching
source/license closure. These materials must remain available with the EXE;
experimental status does not remove component license requirements. The Windows
updater reads its own metadata and does not infer a Windows version from Linux.
See [Windows release materials](../Monado_Windows/docs/WINDOWS_RELEASE.md) and
[corresponding sources](../Monado_Windows/docs/WINDOWS_RELEASE_SOURCES.md).

Build/package a new Windows EXE on native Windows with pinned inputs and the
reviewed Windows release collectors. A Linux session may statically verify and
upload supplied Windows assets, but cannot claim a new native Windows build or
gameplay pass. Known temporal/DLSS flashes and incomplete qualification remain
explicit in the experimental release notes.

## Workflow and final checks

The manual source-release workflow packages the Linux source kit only. It does
not build or publish the Windows EXE. The old `--platform windows` legacy source
packager is retained for historical source fixtures and refuses the modern native
Windows builder tree, preventing it being mislabeled as the original implementation.
Current Windows releases use their native packager and independent metadata.

Inspect exact assets, release checksum entries, public source history, notes,
update identities and package/source guards. Never use inherited broad distribution
scripts or upload a development workspace. Keep authored/licensed source and
component attribution; never upload game-derived data, private logs or user state.
Source CI and packaging checks are separate from gameplay/full-game qualification.


Retain the 0.1.27 regression checks: the packaged-Python OpenSSL collision
reproducer and the real pinned CMake/Zig negative/control linker fixture.
Distinguish Fedora userspace component checks from a full Fedora/CachyOS
installation. Keep the GLIBC ceiling, source checks and required SDL backends.
