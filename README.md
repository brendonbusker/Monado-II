# Monado II

> **Linux 0.1.29 and Windows Experimental 0.1.0 are available.**
> Linux 0.1.29 improves launcher reopen diagnostics and retry, fixes a graphics
> mod overlay bypass and adds diagnostics for adapted aspect ratios.
> Existing Linux installations can update normally; saves and settings are preserved.
> Windows now includes the modern launcher and gameplay options, with known
> temporal/DLSS flickering and incomplete hardware/gameplay qualification.

**Xenoblade Chronicles: Definitive Edition, recompiled for PC.**

A community fork of **Monado** by **TheMonadoGuy / Monado contributors**, built
on **Peiikai’s LASRecomp**. Monado II adds a native Linux port and optional
quality-of-life features, alongside a new experimental native Windows port.

<p align="center">
  <img src="https://github.com/user-attachments/assets/69fabc08-665d-41bc-8900-f707138d630f" alt="Monado II’s native Linux launcher, with artwork, graphics settings and build tools" width="1000" />
</p>

[![Source CI](https://github.com/brendonbusker/Monado-II/actions/workflows/source-ci.yml/badge.svg?branch=main)](https://github.com/brendonbusker/Monado-II/actions/workflows/source-ci.yml)
[![Release](https://img.shields.io/github/v/release/brendonbusker/Monado-II)](https://github.com/brendonbusker/Monado-II/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Get started](#getting-started) · [Latest release](https://github.com/brendonbusker/Monado-II/releases/latest) · [Linux guide](docs/BUILD_LINUX.md) · [Windows guide](docs/BUILD_WINDOWS.md) · [Changelog](CHANGELOG.md)

> [!IMPORTANT]
> **Bring your own legally dumped game.** Downloads contain setup software and
> source, not a playable game. You must own the game and supply your own extracted
> **Definitive Edition 2.0.0** files from your own legally obtained Nintendo Switch.
> No game files, keys or firmware are provided.

## Features

| Feature | What it adds |
|---|---|
| Graphical setup and launcher | Open one Linux AppImage, select your extracted game folder and build location, watch the local build, then use the themed settings launcher. |
| High-refresh improvements | Timing, animation, menu-navigation and footstep corrections, plus a choice of 30 FPS-style or faster 60 FPS-style menu navigation. |
| Temporal upscaling | Native FSR3, NVIDIA DLSS / DLAA and optional experimental FSR4 Lite. Provider availability depends on the platform and hardware. |
| Graphics controls | Original defaults, optional quality controls, GPU selection and a local support report. |
| Frame generation | Experimental FSR 3 interpolation (2×), refresh matching and separate game/output counters. Linux also offers NVIDIA Smooth Motion when supported driver components are installed. Off by default. |
| Controller vibration | Optional rumble, off by default. |
| Shader preparation | Prepare shaders before playing with the launcher’s **Precompile shaders** button. |
| Exit to desktop | Native title-screen and in-game System menu entries, with confirmation and Cancel/No selected by default. Exiting does not save progress. |
| Built-in updates | Stable-release notifications, local rebuilds when required, progress, cancellation and automatic cleanup of superseded builds. |
| Optional cheats | A separate Cheats tab with off-by-default damage/reward multipliers (0x–20x in 0.01x steps) and no fall damage. [Controls and limits](docs/CHEATS.md). |
| Handheld controller recovery | Recheck detection after focus/device changes and keep Steam controller metadata current. Steam Deck/ROG Ally hardware testing is still needed. [Compatibility notes](docs/HANDHELD_CONTROLLERS.md). |
| Aspect-ratio choices | Original 16:9, Match the display and experimental 16:10 / 21:9 / 32:9, with proportional menus/HUD. [Controls and limits](docs/ASPECT_RATIOS.md). |
| On-screen FPS counter | On Linux, **Show FPS on screen** offers Off, Number only, Compact HUD and Detailed panel in **Graphics → Quality** and the live **F1** menu. Off by default; separates Game FPS from submitted FSR or measured NVIDIA driver output when available. [Frame-generation notes](docs/FRAME_GENERATION.md). |
| Clearer Linux setup | Early dependency checks, distro-specific package instructions and optional guided Fedora 45 Distrobox repair. |

The applicable gameplay and launcher features now have native Windows
implementations in **Windows Experimental
0.1.0**. Windows provider support and gameplay coverage remain experimental; see
[platform status](docs/PLATFORM_STATUS.md) and the [Windows guide](docs/BUILD_WINDOWS.md).

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

Download from the [latest release](https://github.com/brendonbusker/Monado-II/releases/latest)
and verify the download against **SHA256SUMS**. The recommended Linux download is
one graphical builder AppImage. **The game is still built locally from your own dump.**

| Platform | Recommended download | Full instructions |
|---|---|---|
| Linux x86-64 | [Graphical builder AppImage](https://github.com/brendonbusker/Monado-II/releases/download/v0.1.29/monado-ii-0.1.29-linux-builder-x86_64.AppImage) | [Linux setup and build guide](docs/BUILD_LINUX.md) |
| Windows x86-64 | [Windows Experimental 0.1.0 setup EXE](https://github.com/brendonbusker/Monado-II/releases/download/v0.1.29/MonadoII-Windows-Setup.exe) | [Windows build guide](docs/BUILD_WINDOWS.md) |

> **Windows is experimental and independently versioned.** Download and run
> **MonadoII-Windows-Setup.exe**. It builds locally from your own extracted game
> folder and returns to the settings launcher on later opens. DLSS/DLAA purple
> flashes and flickering are still reported; broader testing is needed.

### Linux quick start

1. Make the downloaded AppImage executable in your file manager's permissions,
   then open it. If FUSE is unavailable, use the [extraction-mode command](docs/BUILD_LINUX.md#graphical-setup-recommended).
2. Choose **Set up Monado II** and select your own extracted **DE 2.0.0** folder
   containing `exefs` and `romfs`. Your files stay in their existing location.
3. Choose a final installation folder, whether to include NVIDIA DLSS support,
   and whether to prepare shaders after building.
4. Build, following the progress and details. When ready, open the settings
   launcher and choose **Play** yourself.

Open the **same AppImage** later to return to your checked installation. It
contains the setup frontend, Python runtime and reviewed source template—not the
game. Keep the installed build folder and its input available. If you already
have Monado II installed, **Use an existing installation** adopts it in place,
including its settings, saves and current update. See the [graphical setup guide](docs/GRAPHICAL_BUILDER.md).

The [Linux source/setup kit](https://github.com/brendonbusker/Monado-II/releases/download/v0.1.29/monado-ii-0.1.29-linux-setup.tar.gz)
remains available for terminal builds and existing updaters. After extracting it
and arranging its `game_files/exefs` and `game_files/romfs` input, the established
commands are still:

```sh
./Build_Monado_II.sh
./Play_Monado_II.sh
```

That route generates its checked launcher AppImage locally. Keep its complete
installation folder; a launcher image is not a standalone game. Quiver's source-kit
entrypoint remains **`App_Monado_II.sh`**. See [Quiver setup and limitations](docs/QUIVER.md).

Since 0.1.13, the build checks prerequisites before compilation and reports the matching
distribution packages when something is missing. In a supported Fedora 45
Distrobox, `./Build_Monado_II.sh --install-deps` requests guided package repair.
Native hosts receive manual instructions; ordinary builds and background updates
never install system packages. See [prerequisite checks](docs/BUILD_LINUX.md#prerequisite-checks-and-guided-repair).

Normal Linux builds include **native FSR3 temporal upscaling**, **DLSS Super
Resolution / DLAA**, optional FSR4 Lite support and experimental frame generation.
The NVIDIA SDK is prepared locally; its binaries/models are excluded from source
kits and launcher images. To omit the NVIDIA SDK while retaining FSR3, use:

```sh
./Build_Monado_II.sh --without-dlss --framegen
```

**Frame generation is experimental and disabled by default.** The launcher offers
FSR 3 interpolation (2×) with working DLSS/DLAA, FSR3 or prepared FSR4 temporal
inputs, optional display-refresh matching and separate Game/Output/Generated counters. NVIDIA Smooth Motion is a separate alternative
when supported driver components are installed. Performance varies: either method
may run worse, stutter or show visual glitches. See [methods, requirements and
testing](docs/FRAME_GENERATION.md).

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
- **Updating Linux to 0.1.29 requires a full local game rebuild.** The updater
  keeps your existing saves, settings and game input in place; no save conversion
  is needed.
  Missing prerequisites leave the working version selected and show instructions
  for retrying.
- Keep the **complete save folder, including hidden files**, when backing up or
  moving saves. Quick Step metadata accompanies the unchanged native `.sav` files.
- From **0.1.6**, the original folder’s `update-version.json` reflects the active
  version. After successful activation, only the current launcher and its game
  payload are retained. Older releases can be downloaded and built manually.

If the game-input folder moves, reopen Monado II and use **Locate game files** to
select its new location. The supported version and executable identity are checked
before reconnecting; saves/settings stay put and the game is not immediately
rebuilt. Close other sessions for that installation first. A later update may
rebuild once to record the new path. Moving the entire installed build still
requires rebuilding at its final location.

Existing host-Python source installations retain their workspace launcher when
updating. Installations using the graphical builder's private Python can produce
a full standalone setup image during updates. The original installation icon still
forwards to the active build. A new graphical AppImage can adopt an existing
installation without moving its input or profile.

The updater is available from **0.1.3**. **0.1.2 has no updater**: apply a verified
0.1.3-or-newer Linux source kit to the same original installation and rebuild once,
preserving input and profile directories. A fresh kit in a new folder is a separate
installation and does not import an older profile. Follow
[Linux updates and storage](docs/BUILD_LINUX.md#4-update-and-roll-back).

Source-kit downloads use the **`-setup` kit**. A legacy Linux **`-source`** archive remains
in releases solely for installed-updater compatibility. Both contain source, not
precompiled playable games. No compiled game binary, private vendor SDK binary,
game-derived cache or user data is distributed. The graphical AppImage contains
setup software and reviewed startup dependencies; game/runtime compilation stays local.
**0.1.29 is a regular Linux release.** Optional frame generation and non-original
aspect modes remain experimental. Original 16:9 remains the default. The Windows
experimental setup has its own versioned update metadata and retains its profile
through checked updates; a Linux-only version does not advance Windows.

Version **0.1.14** targets severe AMD/RADV submission overhead with a
capability-gated memory path and safe fallback. **AMD gameplay performance still
needs testing**, including on the reported RX 6700 XT. NVIDIA gameplay received
positive maintainer feedback. See [AMD / RADV compatibility notes](docs/AMD_RADV.md)
for the distinction between memory tests and game-performance coverage.

Linux **0.1.19** builds on 0.1.16’s Steam/SDL controller support with recovery
checks after focus/device changes and live Steam controller metadata. It targets
loss of controls after opening Steam/QAM, but **actual Steam Deck and ROG Ally X
validation is still needed**. The maintainer does not have either handheld to
verify it. See [handheld controller notes](docs/HANDHELD_CONTROLLERS.md) for limits
and reporting guidance. The retained RADV-only `nodcc` workaround targets colorful
RX 7600 artifacts; thanks to **patrickksmdev** for isolating and testing it.

In Graphics, **Aspect ratio** now offers **Original (16:9)**, **Match the display**,
**16:10**, **21:9** and **32:9** on every monitor. Original remains the default.
Fixed choices fit inside the screen/window with bars when the proportions differ;
Match the display follows the drawable. Menus and HUD keep their proportions.
These new modes are **experimental**: actual handheld/ultrawide gameplay,
cutscenes, effects and live resizing still need testing. See the
[aspect-ratio guide](docs/ASPECT_RATIOS.md).

## Platform status and limitations

| Platform | Current state |
|---|---|
| **Linux x86-64** | Native SDL/Vulkan port. Opening cutscenes and battles through first character control were tested by the maintainer. Expanded saves, scan responsiveness, Quick Step, trading and the Bionis Interior crash correction received positive manual feedback. |
| **Windows x86-64** | Experimental 0.1.0 native build, portable graphical setup and modern gameplay/launcher features. Native builds and title startup were tested; temporal/DLSS flickering remains reported. Full-game, save/reload, provider, clean-machine and other-hardware qualification is incomplete. |

Full-game, **Future Connected**, long-session, other-GPU/driver and save/recovery
coverage remain incomplete. Passing source CI and component tests do not establish
full-game compatibility. Native FSR3 and optional experimental FSR4 Lite now have
Linux component/GPU checks; their gameplay and performance still need testing.
Windows has native provider adapters with separate qualification limits. See [platform status](docs/PLATFORM_STATUS.md)
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
| [Linux setup and build instructions](docs/BUILD_LINUX.md) | Graphical setup, requirements, terminal builds, updates and storage. |
| [Graphical builder](docs/GRAPHICAL_BUILDER.md) | Folder selection, local build progress, existing installs and moved-input recovery. |
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
