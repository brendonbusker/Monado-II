# Platform status

Linux 0.1.16 preserves validated Steam/SDL input context, exposes existing HIDAPI
controller nodes through the native state guard, and improves device selection
and bounded discovery logs. It likely addresses the Steam Deck detection report;
ROG Ally X remains uncertain. Actual handheld testing is pending. Desktop/NVIDIA
gameplay was manually accepted. The RADV-only nodcc workaround is based on
patrickksmdev’s isolated RX 7600 test; the packaged affected-AMD case still needs
validation. See [handheld controllers](HANDHELD_CONTROLLERS.md) and
[RADV compatibility](AMD_RADV.md). A full local rebuild is required; save formats
and state locations are unchanged.

**Windows downloads remain the original implementation, without Linux additions.**
The version-free Windows filename and implementation identity do not advance with
Linux release numbers. Source snapshot versions are provenance only.

Linux 0.1.15 adds an optional Cheats tab with independent off-by-default battle
damage and EXP/AP/SP/gold multipliers, plus ordinary no-fall damage. Multipliers
span 0x–20x in 0.01x steps. The existing Xenoblade 3 party-switch control moves
from Controls to Mods beneath Quick Step, with its key and behavior retained.
The maintainer manually accepted the combined Linux build; authored native,
sanitizer, instruction and launcher tests provide separate component evidence.
Damage-over-time/status and comprehensive DE/FC coverage remain unqualified.
Native save formats are unchanged, but rewards earned remain after disabling
cheats. See [Cheats](CHEATS.md). A full local rebuild is required.

Linux 0.1.14 adds capability-gated driver-owned guest heap backing for Mesa RADV,
with safe fallback to the existing import. **AMD gameplay performance, including
the reported RX 6700 XT, still needs testing.** Controlled integrated-RADV memory
tests passed; the maintainer accepted NVIDIA gameplay qualitatively. These are
not AMD game-FPS results or measured NVIDIA performance parity. See
[AMD / RADV notes](AMD_RADV.md). Save formats and Windows implementation are unchanged.

Version 0.1.13 added early dependency diagnosis and explicit guided package repair
inside supported Fedora 45 Distrobox environments. Native hosts receive manual
instructions; ordinary builds and background updates never install packages.
The baseline remains CPython 3.14, glibc 2.43+ and the required native interfaces.
Fedora/Debian userspace checks, a fresh native build and a real 0.1.12 updater
rehearsal passed. Actual Steam Deck/Bazzite desktop gameplay and an interactive
privileged Distrobox transaction remain unverified.

Monado II targets native Linux x86-64 and Windows x86-64 with SDL/Vulkan. It is
not affiliated with Nintendo/Monolith Soft and includes no game files.

Linux development has run on Ubuntu26.04.1, Ryzen7900X and RTX4070SUPER with NVIDIA
595.99.02. The tested toolchain is CPython3.14, Zig0.14.1/Clang19.1.7 and a pinned
Ubuntu development sysroot. This is a tested development combination, not a broad
minimum-spec or portable binary compatibility promise.

Maintainer gameplay reached opening cutscenes, battles and first Shulk control;
high-FPS menus/repeat and reported footstep chatter were corrected. Optional shader
preparation was manually accepted. Native DLSS/DLAA had positive manual feedback;
synthetic output tests do not establish every game's temporal scenario.
The one-command Linux build includes the native DLSS/DLAA provider by default;
`--without-dlss` explicitly omits it. Selection still requires compatible NVIDIA
hardware/drivers and the existing runtime capability checks. Build prerequisites
are listed in the [Linux guide](BUILD_LINUX.md).
**Frame generation remains experimental and off by default.** The earlier
implementation was slow/glitchy in reported gameplay. Version0.1.5 fixes specific
warmup/history and deliberate pacing problems and adds an explicit local build
option. Manual testing found it mostly stable with remaining jitter/stutter and
preferred FG off. **Performance varies and may be worse with FG enabled.** Authored
tests do not establish improved physical display cadence, latency or all scenes.
Linux FSR3 Super Resolution is unavailable.

Version0.1.6 includes FG support in normal Linux builds and automatic rebuilds,
with the effect disabled in settings by default. Users enable it in the launcher
with DLSS/DLAA selected. Explicit DLSS-free builds omit both providers. This is an
availability correction, not a new pacing/performance fix.

Version 0.1.4 fixes Linux dependency flag handling in installation paths containing
spaces. It preserves existing input/profile locations and the variable-query
contract used by launcher setup.

Version 0.1.3 adds a Linux stable-release updater with source verification, local
build progress/cancellation and checked launcher restart. Presentation-only
updates can retain the compatible game; other source changes trigger a full local
rebuild. Original input and profile paths remain stable across managed versions.
Failure/cancellation during preparation preserves the previous selection, and
edited release-owned source stops installation. Full automated rebuilds of custom
footstep-diagnostic builds are refused safely. Current clients support ordinary
FG rebuilds; older experimental FG installations with pre-0.1.6 updater code need
a one-time manual upgrade.
The 0.1.2 launcher needs a one-time manual 0.1.3 source upgrade/build to gain
update support. The verified source kit can be applied to the same original
folder while keeping its profile/input/build directories; fresh kits in another
folder do not import old profiles. See [updating/rollback](BUILD_LINUX.md#4-update-and-roll-back).
This implementation does not establish broad clean-machine or interrupted-update
qualification; coverage limits below remain applicable.

Windows retains the original Monado implementation. Its original author reported
whole-game playability on NVIDIA RTX, including Future Connected. This fork has
not independently built or run that Windows source. The Linux improvements listed
in [TODO](../TODO.md) have not been backported. Windows development is approved;
[the current handoff](WINDOWS_PORT_HANDOFF.md) covers the pending implementation.
There is no Windows updater in this release.

The public launcher restores the exact original generated landscape artwork;
[provenance](../Monado_Linux/tools/launcher/assets/ARTWORK_PROVENANCE.md) records
its origin and limitations. It is not a game screenshot or extracted asset. The
separate unreviewed sword icon and proprietary-font decoding remain excluded.
Plain user/system TTF/OTF/TTC font input is supported. Public-only changes require
further integrated testing. Full-game, save-recovery, long-session, other-GPU and
clean-machine coverage remain incomplete. A regular release does not imply
Windows game-build or full-game qualification.

Linux0.1.8 adds native Exit to desktop entries on the title screen and System
menu, scoped Exit/Cancel-or-No confirmations, and ordered guest/render/GPU close.
The maintainer accepted both flows manually on the tested NVIDIA Linux candidate.
Existing menu rows/restrictions and saves/settings are preserved; unsaved progress
is not automatically saved. This feature is not backported to Windows.

Linux 0.1.9 expands each story to 99 manual save slots plus its own autosave.
The native four-card list scrolls through unused No data slots without creating
files. Existing native save formats and filenames remain unchanged, with separate
main-game and Future Connected saves. Continue and title save/clear checks include
extended slots through the native asynchronous readers and validation.

Initial Save/Load scans now batch ready native metadata steps within a bounded
call/time budget. Pending reads and callbacks yield; save writes and thumbnail
reads retain their ordinary cadence. These changes received positive manual
feedback on the Linux development build. Actual waits depend on I/O, populated
slots and host timing; startup and Continue scans can still add delay. This is
not qualification of 99 populated slots, every story/save/recovery case, or the
full game. Updating requires a local game rebuild; the updater retains the
original save/settings profile and shared input. No save conversion is required.
Windows retains its existing save implementation and has no backport scheduled.


Linux 0.1.11 makes the dedicated Quick Step slot stable following the maintainer's
manual acceptance. It remains off by default for the original-game preference.
Saved assignments and their actual movement bonuses restore through Load Game
and Continue, retaining the selected save's identity across native cache copies.
Native row/portrait E markers distinguish current-character and other-character
ownership; leaving the bonus picker restores the ordinary chooser and its native
menu feedback. Native `.sav` formats and filenames are unchanged; optional hidden
metadata must stay with the complete save folder. Updating requires a full local
game rebuild while keeping input and the original profile in place, without
save conversion. See the [Quick Step guide](QUICKSTEP.md).

The queued renderer now retains recorded shader programs and compiler constants,
correcting the reported Bionis Interior crash. The maintainer reports that everything looks
in order after this change. Exact scene coverage, all character/equipment cases,
Future Connected, save recovery, other hardware and the full game remain
incompletely qualified. Shadow boxes reported in Valak/Makna are queued for
investigation and are not fixed in 0.1.11. These changes are Linux-only; Windows
source is unchanged. Frame generation remains experimental and off by default.

Linux 0.1.10 fixed missing native dispatch cases in NPC trading; the maintainer
reports no trading crashes in the tested build. Its pinned private runtime includes
ordinary media/codec dependencies that previously came from the Ubuntu host. Native driver/audio/session interfaces,
glibc 2.43+ and required GNU ABI versions remain explicit host requirements.
Both completed build modes pass game/launcher and native companion load-only
checks in an isolated official Arch 2026.11 userspace (glibc 2.44, Python 3.14.9),
with system libbluray.so.4 and no system .so.3. Authored VP9/WebM, H264, Opus,
scaling and resampling tests also pass. This uses the maintainer's
host kernel and establishes neither an Arch desktop game run nor AMD/Wayland
GPU compatibility. Optional FFmpeg plugins and vendor GPU modules require their
own integration coverage. See the [Linux prerequisites](BUILD_LINUX.md).
