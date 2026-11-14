# Release artifacts and publication boundaries

## Current release: Linux 0.1.20

Release 0.1.20 adds **Show FPS on screen** in **Graphics → Quality**, off by
default, with a matching F1 setting. It remains visible in fullscreen and counts
rendered game frames, excluding generated frames and repeated presentations.
The existing title-bar FPS preference stays independent. Keep the overlay outside
frame-generation history.

The shared aspect correction applies to Match the display and the experimental
16:10, 21:9 and 32:9 modes. It handles reduced-resolution scene composites with
multiple inputs and aligns the renderer's checked aspect/FOV with its logical
camera. Original 16:9 remains the default; menus/HUD stay proportional. The
maintainer accepted desktop/NVIDIA gameplay and the counter. The reported
ultrawide framing issue still needs reporter testing; do not present it as a
confirmed all-hardware fix or full-game qualification.

The release requires a **full local game rebuild**. Preserve the existing saves,
settings, hidden Quick Step metadata and shared input without conversion. Users
need temporary space for the old and new builds. First-time cleanup of accumulated
update history can delay opening; the isolated long-history rehearsal took about
75 seconds for maintenance and checks. Unknown, modified or busy trees remain
protected/deferred. Keep this caveat in release notes.

Publish a regular release with the reviewed standalone builder, Linux setup kit
and byte-identical legacy source alias, original Windows kit, licensed builder
runtime source companion and combined SHA256SUMS. The Windows filename remains
version-free and the implementation remains original. Keep the inherited RADV
`nodcc` workaround and credit **patrickksmdev** for isolating and testing it.
Quick Step, cheats, the new FPS overlay and experimental frame generation stay
off by default. The following sections preserve earlier release history and
continuing packaging boundaries.

Linux 0.1.17 adds the graphical setup AppImage
**`monado-ii-0.1.17-linux-builder-x86_64.AppImage`**. It contains the authored
setup frontend, Python runtime, selected reviewed startup dependencies and source
template. It generates and builds the game locally from the player's own extracted
input. It contains no game executable, generated game code, game assets, vendor
SDK, translated game shaders/caches, keys, firmware, saves or user data.

This binary has a separate, explicit packaging boundary in
`tools/build_builder_appimage.py`. Its file inventory, copyright/license notices,
source-template guard, private-runtime checks and exact archive readback are
required. Before public distribution, review the exact dependency licenses and
fulfil applicable corresponding-source/build-material obligations. A successful
hash check alone does not establish redistribution rights. See
`tools/builder_appimage/BUNDLE_NOTICES.md`. This does not authorize packaging a
whole development sysroot, the media runtime or any game-derived binary.

The Linux `monado-ii-<version>-linux-setup.tar.gz` and Windows
`monado-ii-windows-original-implementation-setup.zip` remain **source/setup kits**.
Their existing source-only guards stay strict. Keep the byte-identical Linux
`-source.tar.gz` compatibility alias for older updaters. No game or SDK binary is
added to these archives. Each player generates game code locally from their own
legally dumped input.

Version 0.1.17 is a regular release, with GitHub's prerelease option disabled.
This status does not establish Windows, full-game, all-distro or handheld gameplay
coverage. The reviewed generated illustration remains subject to its exact
[provenance](../Monado_Linux/tools/launcher/assets/ARTWORK_PROVENANCE.md) and root
notice; other unreviewed imagery stays excluded.

The maintainer completed fresh graphical setup/build and accepted reopen, then
manually confirmed an updated existing installation opened and played normally.
That update needed two manually resumed packaging/startup corrections; do not
present it as an uninterrupted automatic-updater pass. Recovery has automated and
hidden-UI coverage; a real moved-folder picker test remains unqualified. Keep
these limits separate from native build and source-test results in release notes.
Updating preserves the original profile and shared input, and may require a full
local game rebuild. The new full-image path applies to installations using the
persistent private Python. Ordinary host-Python source clients retain their
workspace bootstrap; a new graphical AppImage can adopt them in place.

Windows uses a version-free filename and internal root, with `version: "original"`.
Do not assign the Linux release version to Windows or imply feature parity.
`source_release_version` records the containing reviewed source snapshot only.
The Windows kit excludes Linux-only `update-version.json`. Keep this policy until
Windows actually receives an explicitly approved update; then document its own
implementation version and changes. Historical assets may be renamed with byte
identity retained and checksum filenames updated; never silently repackage an old
release to claim a new implementation.

Version 0.1.16 includes the accepted desktop/NVIDIA controller + RADV build.
Describe the Steam Deck correction as likely and ROG Ally X compatibility as
uncertain: neither handheld has validated this build. Credit **patrickksmdev**
for isolating `nodcc` on RX 7600. Keep affected-AMD candidate validation separate
from the external report and the maintainer’s NVIDIA gameplay acceptance.
Native saves, profile locations, Quick Step default and experimental FG default
stay unchanged. Updating requires a full local rebuild.

Version 0.1.15 adds the optional Linux Cheats tab: independent off-by-default
party damage dealt/received, EXP/AP/SP/gold gain sliders (0x–20x in 0.01x steps),
and ordinary no-fall damage. The Xenoblade 3 party-switch control moves to Mods
below Quick Step. The maintainer manually accepted the combined build; broad
DE/FC and DoT/status coverage remain unqualified. Native save formats and profile
locations stay unchanged; rewards already earned persist after disabling. See
[Cheats](CHEATS.md). This release requires a full local game rebuild.

Version 0.1.14 added capability-gated driver-owned guest heap backing for Mesa
RADV, aimed at excessive user-pointer submission overhead, with checked fallback.
NVIDIA retains its existing import and device-feature path. **AMD gameplay
performance, including the reported RX 6700 XT, still needs testing.** Integrated
RADV memory-transfer tests passed, including full heap capacity. The maintainer
accepted NVIDIA gameplay qualitatively; no measured FPS parity or full-game claim
is made. See [AMD / RADV notes](AMD_RADV.md). A full local game rebuild is required.

The 0.1.13 prerequisite checks and explicit supported Fedora 45 Distrobox repair
remain included. Ordinary builds and background updates never install system
packages or request sudo. The glibc/Python baseline is unchanged; actual Steam
Deck/Bazzite desktop gameplay and privileged Distrobox installation are unverified.

The 0.1.12 current-only updater, held-L2/HUD/party controls and new-selection
DLAA / Native (100%) default are Linux-only. Explicit saved DLSS qualities are
preserved. Scaled DLSS shaking at 67% remains unresolved; Native (100%) is the
current workaround. Windows parity is approved but deferred until development
on Windows. The Windows implementation is unchanged. Quick Step remains stable
following manual acceptance and **off by default**; frame generation remains
experimental and off by default. Valak/Makna/pipe rendering reports remain open.
Do not imply full-game, other-hardware or actual Bazzite qualification.

After successful activation, the new launcher removes obsolete updater-owned
versions and downloads, including accumulated history from older clients. It
retains the active game payload and protects input, saves, hidden Quick Step
metadata, settings, mods and useful caches. Unknown, modified or busy trees are
deferred safely. Local rollback history is discontinued; manual downloads/builds
of older GitHub releases remain available. The first cleanup can delay opening:
an isolated long-history upgrade rehearsal took about 75 seconds for maintenance
and checks. State this in release notes, alongside the full rebuild and temporary
old-plus-new storage requirement. An old updater may place the first rebuilt game
in its version workspace, requiring one more full rebuild on the following update
to establish the independently reusable payload.

The current build-recipe changes require a full local game rebuild through
the Linux updater while retaining the original saves/settings profile and
read-only input. Do not package profiles or perform save conversion as part of
an update. Preserve optional Quick Step assignment metadata with its save folder.
The builder fetches the compatible media libraries privately; source kits and
launcher images do not distribute those runtime libraries or vendor SDK binaries.

The Linux source kit includes `Build_Monado_II.sh` and `Play_Monado_II.sh`. Users
can still create a workspace launcher locally. Native local images, receipts and
staging trees are not source-kit assets. The separately reviewed graphical builder
is an authored setup-binary asset, never a precompiled game. Use a fresh
reviewed export for release checks, not an end-user folder containing input or
generated builds. Never remove a user's input/state to make a release guard pass.

Version 0.1.3 introduces the Linux stable-release updater. The 0.1.2 launcher has
no update client, so users must manually apply/build 0.1.3 or newer once. The verified
source kit can be merged into the same original installation without deleting
its input/build/profile directories; the Linux guide gives the checksum and
clean-kit checks. A fresh kit in another folder remains a separate profile.
Later managed updates leave installed source directories untouched and
download reviewed source and rebuild locally, retaining a compatible game only
for conservatively classified launcher-only changes. No precompiled game or
vendor SDK is delivered by this updater, and it does not update Windows.
Release-owned source modifications stop automatic installation; user profiles
remain outside the source manifest. See the
[Linux update guide](BUILD_LINUX.md#4-update-and-roll-back).

Managed workspaces, downloads, generated outputs and logs under
`Monado_Linux/updates/` are runtime artifacts, excluded from tracked source and
release kits. Never package an end-user update directory. Version paths remain
fixed after building; activation changes a checked local pointer rather than
moving or replacing source, game input or saves. Release discovery accepts newer
stable versions and requires the official Linux source asset's size/SHA-256 plus
its exact source manifest and policy checks. Publish the matching version metadata
and Linux source-kit asset together; retaining a stable version tag alone does not
make an incompatible archive suitable for the updater.

Every Linux release must also include
`monado-ii-<version>-linux-source.tar.gz`, a **byte-identical compatibility alias**
of the Linux setup archive. Installed 0.1.3/0.1.4 clients require that filename and
the existing `monado-ii-<version>-linux-source/` internal directory. New clients
prefer the setup filename and retain the guarded source-name fallback. Keep both
Linux filenames in future stable releases so users can skip versions safely.
The names do not change the source-only policy or local rebuild requirements.
The packager emits SHA256SUMS entries for both identical Linux files; Windows
uses only its canonical setup name. Do not regenerate the compatibility archive
independently or alter its internal root.

From a reviewed clean public checkout:

```sh
# The strict packager requires canonical paths, without '..' or symlink aliases.
MONADO_RELEASE_SOURCE="$(pwd -P)"
MONADO_RELEASE_PARENT="$(dirname "$MONADO_RELEASE_SOURCE")"
python -B tools/publication_guard.py "$MONADO_RELEASE_SOURCE"
python -B tools/package_source_release.py --source "$MONADO_RELEASE_SOURCE" --platform linux --version 0.1.17 --output "$MONADO_RELEASE_PARENT/monado-ii-linux-release"
python -B tools/package_source_release.py --source "$MONADO_RELEASE_SOURCE" --platform windows --version 0.1.17 --output "$MONADO_RELEASE_PARENT/monado-ii-windows-release"
```

Outputs must be fresh. The packager verifies the exact publication manifest and
source policy before staging, selects one port plus common source, creates a
platform-specific manifest/status note, and checks archive readback. Artifact
checksums accompany output. Do not upload the whole development workspace or
reuse its Git history. The separately prepared public tree has a reviewed fresh
history; development notes, unreviewed artwork and personal paths remain local.

The manual **Source release kits** GitHub Actions workflow produces
`monado-ii-linux-setup` and `monado-ii-windows-original-implementation-setup` workflow artifacts after
checks; its read-only token does not publish a GitHub release, compile game code,
access secrets or fetch game input. The Linux workflow artifact contains both
Linux filenames and its checksum list. Download the artifacts from the exact
reviewed tag/commit. A workflow artifact alone is not available to the updater:
the maintainer must attach the verified archives to the matching GitHub Release.
CI runs authored source-tooling tests on Linux and Windows; it is not a Windows
game-build or gameplay pass.

For a normal release, verify both platform source-kit checksum lists. Build and
audit the standalone setup image separately, including its required notices and
corresponding-source/build materials. Combine their verified checksums into one
`SHA256SUMS`. Upload the builder AppImage, all three source/setup archives, the
checksum file and any required dependency-source/build-material artifact. The Linux
setup and compatibility alias must have equal bytes and digests. For example,
from the parent of the two fresh local packaging output directories:

```sh
MONADO_RELEASE_VERSION=0.1.17
(cd monado-ii-linux-release && sha256sum -c SHA256SUMS)
(cd monado-ii-windows-release && sha256sum -c SHA256SUMS)
cmp "monado-ii-linux-release/monado-ii-${MONADO_RELEASE_VERSION}-linux-setup.tar.gz" "monado-ii-linux-release/monado-ii-${MONADO_RELEASE_VERSION}-linux-source.tar.gz"
cat monado-ii-linux-release/SHA256SUMS monado-ii-windows-release/SHA256SUMS > SHA256SUMS
# After reviewing release-notes.md and the existing reviewed Git tag:
gh release create "v${MONADO_RELEASE_VERSION}" --verify-tag --repo brendonbusker/Monado-II --title "Monado II ${MONADO_RELEASE_VERSION}" --notes-file release-notes.md \
  "monado-ii-linux-release/monado-ii-${MONADO_RELEASE_VERSION}-linux-setup.tar.gz" \
  "monado-ii-linux-release/monado-ii-${MONADO_RELEASE_VERSION}-linux-source.tar.gz" \
  "monado-ii-windows-release/monado-ii-windows-original-implementation-setup.zip" SHA256SUMS
```

The source archives and checksum file above may also be attached through GitHub's
release editor. The separately audited builder AppImage and its required source/
build materials must be attached to the same release as well; the source-kit
workflow does not create or audit that binary.
Leave the prerelease option disabled for the normal stable updater channel;
label frame generation experimental in the notes and keep its warning/default.
After publication verify the remote filenames, byte sizes and digests, including
the compatibility alias, then exercise both current and older updater clients
against that release. Never overwrite an existing published archive to repair it;
publish a new version with a matching source manifest and version metadata.

Never use the inherited `scripts/make_dist.sh`: it bundled game/user data and is
excluded from the public export. The graphical setup binary needs its separate
dependency/asset/license review; a compiled game-derived executable remains outside
the allowed release contents. Hash/signature guards supplement, rather than
replace, provenance review. Any uncertain file stays out until resolved.
