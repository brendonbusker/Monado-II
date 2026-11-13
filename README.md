# Monado II

> **Windows development branch — preparation only.** This branch includes the
> Linux0.1.16 reference and an updated [Windows port handoff](docs/WINDOWS_PORT_HANDOFF.md).
> Windows runtime source is still the original implementation. New Windows build
> scripts and Linux-feature backports have not been implemented or tested yet.


**Xenoblade Chronicles: Definitive Edition, recompiled for PC.**

A community fork of **Monado** by **TheMonadoGuy / Monado contributors**, built
on **Peiikai’s LASRecomp**. Monado II adds a native Linux port and optional
quality-of-life features, while preserving the original Windows implementation.

<p align="center">
  <img src="https://github.com/user-attachments/assets/69fabc08-665d-41bc-8900-f707138d630f" alt="Monado II’s native Linux launcher, with artwork, graphics settings and build tools" width="1000" />
</p>

[![Source CI](https://github.com/brendonbusker/Monado-II/actions/workflows/source-ci.yml/badge.svg?branch=main)](https://github.com/brendonbusker/Monado-II/actions/workflows/source-ci.yml)
[![Release](https://img.shields.io/github/v/release/brendonbusker/Monado-II)](https://github.com/brendonbusker/Monado-II/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Get started](#getting-started) · [Latest release](https://github.com/brendonbusker/Monado-II/releases/latest) · [Linux guide](docs/BUILD_LINUX.md) · [Windows guide](docs/BUILD_WINDOWS.md) · [Changelog](CHANGELOG.md)

> [!IMPORTANT]
> **Bring your own legally dumped game.** Downloads contain source and setup
> tools, not a playable game. You must own the game and supply your own extracted
> **Definitive Edition 2.0.0** files from your own legally obtained Nintendo Switch.
> No game files, keys or firmware are provided.

## Linux highlights

| Feature | What it adds |
|---|---|
| Native launcher | A themed settings screen, controller configuration and a locally generated launcher AppImage. |
| High-refresh improvements | Timing, animation, menu-navigation and footstep corrections, plus a choice of 30 FPS-style or faster 60 FPS-style menu navigation. |
| DLSS Super Resolution / DLAA | Native support on compatible NVIDIA hardware, included in normal Linux builds. |
| Shader preparation | Prepare shaders before playing with the launcher’s **Precompile shaders** button. |
| Exit to desktop | Native title-screen and in-game System menu entries, with confirmation and Cancel/No selected by default. Exiting does not save progress. |
| Built-in updates | Stable-release notifications, local rebuilds when required, progress, cancellation and automatic cleanup of superseded builds. |
| Optional cheats | A separate Cheats tab with off-by-default damage/reward multipliers (0x–20x in 0.01x steps) and no fall damage. [Controls and limits](docs/CHEATS.md). |
| Clearer Linux setup | Early dependency checks, distro-specific package instructions and optional guided Fedora 45 Distrobox repair. |

The Linux-specific launcher, timing, menu, save, Quick Step and cheat improvements have
not been backported. Windows retains its upstream launcher and vendor/shader
integrations. Backporting is approved for development on Windows; see the
[current handoff](docs/WINDOWS_PORT_HANDOFF.md). No backport is implemented yet.

### A dedicated Quick Step gem slot

Equip an owned Quick Step gem in an extra character slot without using an ordinary
equipment gem slot. The option uses the game’s native equipment menus and is
**off by default**, so you can keep the original equipment setup.

<img src="https://github.com/user-attachments/assets/ec5a4ae7-495b-4208-8cbe-e851116582ee" alt="Equipping a Quick Step gem in the optional dedicated slot through the native equipment menu" width="870" />

Linux **0.1.11** stabilizes saved assignments, Load Game/Continue restoration,
equipped indicators and native menu feedback. See the [Quick Step guide](docs/QUICKSTEP.md).

### More room for your playthroughs

**99 manual saves plus a separate autosave for each story.** Main-game and Future
Connected saves stay separate. Scroll through four native save cards at a time;
unused slots show **No data** and create no files until used. Existing saves keep
their native format and filenames.

<img src="https://github.com/user-attachments/assets/8899b35a-1867-4712-9c4a-0372738c01c0" alt="Scrolling through the expanded save list while keeping four native save cards visible" width="870" />

Initial Save/Load scanning batches ready native read steps within a small budget
and yields for pending I/O and callbacks. Menus and Continue scanning can still
take time; 99 populated slots and every save/recovery case have not been qualified.

## Getting started

Download a setup/build kit from the [latest release](https://github.com/brendonbusker/Monado-II/releases/latest)
and verify it against the release’s **SHA256SUMS** file. Both kits contain reviewed
source and setup tools. **You build locally from your own game dump.**

| Platform | Current setup kit | Full instructions |
|---|---|---|
| Linux x86-64 | [Linux `.tar.gz`](https://github.com/brendonbusker/Monado-II/releases/download/v0.1.16/monado-ii-0.1.16-linux-setup.tar.gz) | [Linux build guide](docs/BUILD_LINUX.md) |
| Windows x86-64 | [Original Windows implementation `.zip`](https://github.com/brendonbusker/Monado-II/releases/download/v0.1.16/monado-ii-windows-original-implementation-setup.zip) | [Windows build guide](docs/BUILD_WINDOWS.md) |

> **Windows is the original implementation.** Linux release numbers and the
> Linux features shown above do not describe the Windows download. Its version-free
> filename stays unchanged until Windows itself receives updates.

### Linux quick start

1. Extract the Linux kit into a folder you want to keep.
2. Check the [prerequisites](docs/BUILD_LINUX.md), then place your own extracted
   input in `game_files/exefs/` and `game_files/romfs/` inside that folder.
   The guide also explains how to link an existing input folder without moving it.
3. Open a terminal in the extracted folder and run:

   ```sh
   ./Build_Monado_II.sh
   ./Play_Monado_II.sh
   ```

The build generates **`Monado-II-x86_64.AppImage`** for the launcher.
`Play_Monado_II.sh` also works without FUSE. **Keep the build folder alongside the
AppImage**: the game executable, libraries and state live outside its launcher
payload. The image is a workspace launcher, not a standalone game download.

For Quiver and other Linux app launchers, select **`App_Monado_II.sh`**. It shows
first-build progress in an installed terminal, then opens the launcher. See
[Quiver setup and limitations](docs/QUIVER.md).

Since 0.1.13, the build checks prerequisites before compilation and reports the matching
distribution packages when something is missing. In a supported Fedora 45
Distrobox, `./Build_Monado_II.sh --install-deps` requests guided package repair.
Native hosts receive manual instructions; ordinary builds and background updates
never install system packages. See [prerequisite checks](docs/BUILD_LINUX.md#prerequisite-checks-and-guided-repair).

Normal Linux builds include **DLSS Super Resolution / DLAA** and frame-generation
capability. The build fetches the pinned official NVIDIA SDK locally; its binaries
and models are not included in source kits or launcher images. To omit both
providers, use:

```sh
./Build_Monado_II.sh --without-dlss
```

**Frame generation is experimental and disabled by default.** To try it, select
DLSS/DLAA and enable the launcher checkbox; no extra build flag is needed.
Performance varies: it may run worse, stutter or show visual glitches. Leaving it
off is recommended. See [experimental frame generation](docs/BUILD_LINUX.md#experimental-frame-generation).

### Your game files

**No game files are included in this repository or its releases.** You must own a
legally obtained copy of Xenoblade Chronicles: Definitive Edition and supply your
own legally dumped files from your own legally obtained Nintendo Switch console,
including the supported **2.0.0 update**.

**I will not provide game files, keys, firmware, download links, or tell anyone
where to get them. I will not provide instructions for obtaining or dumping them.**
Requests for those files, links or instructions will not be answered.

Only already-extracted **`exefs/` and `romfs/`** folders are accepted. Package/key
extraction is not supported. Game-derived C, executables, shaders and caches are
generated locally and must stay out of Git and releases. Do not post game files,
keys, saves, generated game code, shaders or caches in issues or pull requests;
read the [contribution rules](CONTRIBUTING.md).

The source tree keeps `Monado_Linux/` and `Monado_Windows/` separate. Use one
read-only game-input location, with independent per-port generated files, builds,
configuration, caches, logs and saves. Never direct runtime output into game input.

## Updating and keeping your saves

The Linux launcher checks quietly for newer stable releases on startup. When an
update is available, choose **Update** or **Later**. Updating downloads the source
kit, prepares it locally with progress and cancellation, then restarts the
launcher. It never presses Play.

- Compatible launcher-only updates retain the verified game build; other updates
  rebuild the game locally.
- Saves, settings and shared game input stay in the original installation.
  Failed or cancelled preparation keeps the previous version selected.
- **Updating to 0.1.16 requires a full local game rebuild** for the updated build
  runtime and build recipes. The updater handles this without converting, replacing or
  deleting your saves. Missing prerequisites leave the working version selected
  and show instructions for retrying.
- Keep the **complete save folder, including hidden files**, when backing up or
  moving saves. Quick Step metadata accompanies the unchanged native `.sav` files.
- From **0.1.6**, the original folder’s `update-version.json` reflects the active
  version. After successful activation, only the current launcher and its game
  payload are retained. Older releases can be downloaded and built manually.

The updater is available from **0.1.3**. **0.1.2 has no updater**: apply a verified
0.1.3-or-newer Linux source kit to the same original installation and rebuild once,
preserving input and profile directories. A fresh kit in a new folder is a separate
installation and does not import an older profile. Follow
[Linux updates and storage](docs/BUILD_LINUX.md#4-update-and-roll-back).

New downloads use the **`-setup` kit**. A legacy Linux **`-source`** archive remains
in releases solely for installed-updater compatibility. Both contain source, not
precompiled playable games. No compiled game binary, private vendor SDK binary,
game-derived cache or user data is distributed. **0.1.16 is a regular stable
release**; the optional Quick Step feature is stable, while frame generation
remains experimental. Windows has no updater in this release.

Version **0.1.14** targets severe AMD/RADV submission overhead with a
capability-gated memory path and safe fallback. **AMD gameplay performance still
needs testing**, including on the reported RX 6700 XT. NVIDIA gameplay received
positive maintainer feedback. See [AMD / RADV compatibility notes](docs/AMD_RADV.md)
for the distinction between memory tests and game-performance coverage.

Linux **0.1.16** preserves Steam/SDL controller context and improves HIDAPI access
and device selection. This likely addresses the reported **Steam Deck** detection
issue; **ROG Ally X remains unconfirmed** and neither handheld has been tested on
this release. Desktop/NVIDIA gameplay received positive manual feedback. See
[handheld controller notes](docs/HANDHELD_CONTROLLERS.md) for restart limitations
and reporting guidance. The RADV-only `nodcc` workaround targets colorful
RX 7600 artifacts; thanks to **patrickksmdev** for isolating and testing it.

## Platform status and limitations

| Platform | Current state |
|---|---|
| **Linux x86-64** | Native SDL/Vulkan port. Opening cutscenes and battles through first character control were tested by the maintainer. Expanded saves, scan responsiveness, Quick Step, trading and the Bionis Interior crash correction received positive manual feedback. |
| **Windows x86-64** | Original Monado implementation retained. The original author reported full-game playability on NVIDIA RTX; this fork has not independently built or validated Windows. Windows parity development is approved; implementation and native validation remain pending. |

Full-game, **Future Connected**, long-session, other-GPU/driver and save/recovery
coverage remain incomplete. Passing source CI and component tests do not establish
full-game compatibility. **FSR 3.1 Super Resolution is unavailable on Linux**;
Windows retains its own vendor integrations. See [platform status](docs/PLATFORM_STATUS.md)
and [remaining work](TODO.md).

The public source accepts plain **TTF/OTF/TTC** font input. It does not ship Nintendo
fonts or proprietary-font deobfuscation. The Linux launcher uses the Monado II
wordmark/theme and the reviewed generated landscape illustration; its exact asset
and origin are documented in [artwork provenance](Monado_Linux/tools/launcher/assets/ARTWORK_PROVENANCE.md).
The separate local sword icon is excluded. Broader gameplay/UI validation remains
incomplete.

## Guides and reference

| Guide | What you’ll find |
|---|---|
| [Linux build instructions](docs/BUILD_LINUX.md) | Requirements, game-input layout, building, updates and storage. |
| [Windows build instructions](docs/BUILD_WINDOWS.md) | Building the preserved Windows implementation. |
| [Cheats guide](docs/CHEATS.md) | Optional multipliers, no fall damage, controls and save behavior. |
| [Quick Step guide](docs/QUICKSTEP.md) | Enabling the optional slot, equipping gems and keeping save metadata. |
| [Quiver setup](docs/QUIVER.md) | Launcher entrypoint and integration limitations. |
| [Release verification](docs/RELEASING.md) | Setup-kit contents, checksums and publication boundaries. |
| [Changelog](CHANGELOG.md) | Releases and differences from upstream Monado. |
| [Platform status](docs/PLATFORM_STATUS.md) | Validation, supported paths and known limitations. |
| [Contributing](CONTRIBUTING.md) | Source, attribution and content rules. |

## Credits and license

**Monado II is a fork, not a claim to the original recompiler/runtime.** Credit
belongs to **TheMonadoGuy / Monado contributors** for Monado and **Peiikai** for
LASRecomp. The name acknowledges the original project and the game. Full
attribution is in [CREDITS](CREDITS.md).

This fork was developed using AI coding tools throughout, under maintainer
direction and with manual testing. The original Monado author also documented
substantial AI assistance. Human review, tests and reproducible results matter;
known limitations are tracked openly.

Monado II’s authored code is **MIT-licensed**; see [LICENSE](LICENSE). Dependencies
retain their respective terms in [NOTICE](NOTICE.md). The source license grants
no rights to Nintendo/Monolith Soft game content, trademarks, fonts, artwork or
other third-party assets.

Monado II is an independent community project and is not affiliated with or
endorsed by Nintendo or Monolith Soft.
