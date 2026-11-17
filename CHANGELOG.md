# Changelog

## 0.1.29 - November 17, 2026

- When reopening a registered installation fails, the graphical builder
  preserves the error and log path and offers **Retry opening launcher**.
  The reopen guide explains which AppImage to use and how to keep the same
  data directory and extraction mode. The reported Bazzite failure still
  needs a retest on the original hardware. ([#20](https://github.com/brendonbusker/Monado-II/issues/20))
- Apply the guest dynamic-resolution policy to the graphics INI at its virtual
  RomFS path even when a mod uses different capitalization. Add adapted-aspect
  logs for the sampled image, viewport and crop. The reported ultrawide squeeze
  under load still needs testing on the original hardware. ([#12](https://github.com/brendonbusker/Monado-II/issues/12))
- Windows remains Experimental 0.1.0.

## 0.1.28 - November 17, 2026

- Keep the source-verification helper available when older launchers package an
  updated standalone AppImage. Verify it from the packager's own reviewed source
  without relying on global Python imports.

- Fix loading-screen crashes with Enemy health enabled by waiting for native HP
  initialization before scaling. Preliminary enemy refreshes retain native behavior.

- Add an independently disabled Enemy health multiplier in the launcher and live
  F1 Cheats tab, from 0.10x to 20.00x in 0.01x steps. Preserve remaining health on
  live changes, native phase/death protections and a small-health safety minimum.
  Include lifecycle and arithmetic safeguards. Prison Island loading was manually
  verified at 2x and 20x; broader scripted boss gameplay still needs testing.

- Keep local compiler receipts separately bounded from runtime transport metadata,
  allowing longer installation paths without enlarging accepted archive documents.

- Reduce hidden/background launcher drawing while preserving controller and
  game/update/precompile monitoring. Reuse feedback snapshots after unrelated
  known texture writes, retaining conservative visibility and alias boundaries.
- Limit optional pipeline refinement concurrency on small integrated-GPU Linux
  systems without changing the required compile pool or desktop NVIDIA policy.
  Handheld gameplay performance still needs testing. The targeted renderer `-O2`
  policy retains strict correctness flags; the pinned compiler already emitted
  equivalent code, so no additional speedup is claimed from that flag change.

- Replace the on-screen FPS checkbox with Off, Number only, Compact HUD and
  Detailed panel modes in the launcher and live F1 menu. Add smoother licensed
  typography and game-inspired panels, with existing enabled counters migrating
  to Compact HUD. Frame-rate measurements remain unchanged.
- Add live F1 Cheats controls with the launcher's individual toggles and exact
  0.00x–20.00x multipliers. Publish coherent settings to game events; Save
  remembers them for future launches. Existing damage and earned rewards are
  not reversed when a cheat is disabled.
- Add an optional movement-speed multiplier after native party movement bonuses.
  It starts disabled and does not change the game clock or save format.
- Move best-effort obsolete-update cleanup after the launcher session, retaining
  essential startup validation and immediate cleanup during update activation.
  Avoid repeated source checks that occurred before installation admission.
- Fix opening a new installation when an older registered installation has a
  different source policy. Each installation now loads its own updater helpers.
- Accept Bazzite's system-provided home-directory alias for default builder
  locations while retaining checks inside managed storage. Report the exact
  rejected launch argument or path and retain validated launch context in logs.
- Windows Experimental 0.1.0 remains unchanged.

## 0.1.27 - November 16, 2026

- Fix Fedora build failures caused by the packaged Python runtime exposing its
  private OpenSSL libraries to native `readelf` and `nm`. Inspectors now use the
  host library environment, with bounded, useful diagnostics when they fail.
- Fix SDL linking on hosts where CMake enables linker-generated dependency files
  that the pinned Zig linker does not support. Compiler/header dependencies and
  required desktop/audio backends remain enabled.
- Retain previous update, gameplay, graphics and save behavior. Failed preparation
  keeps the previous working build selected. Existing installs can retry normally.
- Windows remains **Experimental 0.1.0**, with unchanged release assets.

## 0.1.26 - November 16, 2026

- Fix updates from existing split-game installations when an older launcher asks
  to reuse the active game-code library from a previous update folder. The new
  self-bound payload correctly rejects that foreign build path; the builder now
  verifies that the request names the exact active game and regenerates locally
  from the validated game files instead. Native path, input, content and ABI
  checks remain enforced. Unrelated or tampered selections are still rejected.
- This fallback can take longer because game code is compiled again. It avoids
  importing a library outside the candidate payload and keeps existing gameplay,
  renderer options, input, saves, settings and Quick Step metadata intact.
- Retain the 0.1.25 cross-distribution dependency and launcher startup corrections.
  Failed preparation keeps the previous working build selected.
- Windows remains **Experimental 0.1.0**, with unchanged release assets and known
  temporal/DLSS flickering and hardware/gameplay qualification limits.

## 0.1.25 — November 16, 2026

- Fix Fedora/Distrobox portable SDL builds where a host package-tool wrapper
  accidentally selected a target-sysroot executable with incompatible libraries.
  Keep host build tools and pinned target development files separate, including
  the private startup-Python build.
- Prepare the private Python build's allowlisted non-glibc dependencies before
  build-time extension checks. Use native certificate stores and license text
  from pinned upstream sources, without Ubuntu-only host paths.
- Keep target header/library discovery inside the pinned sysroot and disable the
  unsupported optional SDL liburing backend. This prevents a host-only header
  from enabling code the isolated compiler cannot build; normal fallback remains.
- Keep older non-DLSS updater feature receipts compatible when introducing FSR3.
  Managed builds inherit verified selected-game capabilities when the caller
  provides no explicit frame-generation selection. Preserve newer FSR-only
  installations, modern fresh-build defaults and actual features during reuse;
  never mislabel a binary's compiled support.
- Preserve required X11/Wayland/audio support, pinned source/ABI checks and the
  earlier file-limit, cold-cache and portable launcher packaging corrections.
- Show dependency-build phases, elapsed progress and bounded nested failure
  details in outer logs. Cold-cache preparation is distinguished from a failure.
- Reduce repeated internal migration and source-policy work during launcher
  startup. Retain exact byte verification, changed-file rejection, installation
  leases and final artifact checks; do not use a persistent trust bypass.
- Preserve game input, native saves, settings, Quick Step metadata and existing
  gameplay/renderer features. Optional features retain their defaults.
- Windows remains **Experimental 0.1.0**, with unchanged release assets and the
  existing temporal/DLSS flickering and hardware/gameplay qualification limits.

## 0.1.24 — November 16, 2026

- Fix another older-installation update failure during launcher AppImage
  packaging. The CLI now preserves the default portable build selection when
  reusing a verified local runtime, so the rebuilt native launcher uses the
  supported glibc baseline instead of inheriting a newer host requirement.
  Preserve the explicit `--legacy-runtime` opt-out.
- Retain both earlier build corrections: temporary worker-only file-descriptor
  headroom for the full FFmpeg link, and preparation of pinned prerequisite
  caches before a cold private startup-Python build. No system limit changes
  or unrelated package installation are needed for these fixes.
- Keep checked source/runtime reuse, archive verification and the previous
  selection on failure. Existing saves, settings, game input and Quick Step
  metadata remain in place. No gameplay or renderer changes are included.
- Windows remains **Experimental 0.1.0**, with unchanged release materials and
  the existing temporal/DLSS flickering and qualification limits.

## 0.1.23 — November 16, 2026

- Fix a second cold-cache Linux update failure during launcher AppImage
  packaging. Prepare the pinned prerequisite source/sysroot cache before building
  the private startup Python in a fresh update workspace; previously this step
  requested offline prerequisites before that workspace had prepared them.
- Retain the 0.1.22 portable FFmpeg open-file-limit correction, including
  process-local soft-limit adjustment, restoration and explicit hard-cap
  diagnostics. No system limit changes or unrelated package installs are needed.
- Keep source/archive identity checks, local builds, prior-build selection on
  failure and existing saves/settings/input. No gameplay or renderer changes.
- Windows stays **Experimental 0.1.0**, with unchanged release assets and known
  temporal/DLSS flickering and qualification limits.

## 0.1.22 — November 16, 2026

- Fix a Linux setup/update failure while linking the portable FFmpeg libraries:
  `ProcessFdQuotaExceeded`. Desktop-launched builds can inherit a 1,024-file soft
  limit even when the same account permits a much higher limit in a terminal.
- Give only the portable dependency build worker enough file descriptors within
  its existing hard limit, record the limits in its receipt, and restore the soft
  limit afterward. No sudo or system configuration changes are required when the
  inherited hard limit is sufficient. Report an insufficient hard limit clearly.
- Keep the previous working installation selected if a build fails. Existing game
  input, saves, settings and Quick Step metadata are preserved; retry the update
  from the launcher. No gameplay or renderer behavior changes are included.
- Retain all 0.1.21 features. Windows remains **Experimental 0.1.0**, with its
  unchanged setup/update/source materials and existing qualification limits.

## 0.1.21 — November 15, 2026

- Add native temporal FSR3 upscaling on Linux, with compatible inputs for the
  existing experimental 2× frame generator. Preserve native NVIDIA DLSS/DLAA.
- Add optional experimental FSR4 Lite with local model preparation, capability
  checks and fallback handling. Models are prepared only on request; existing
  upscaling preferences are preserved.
- Add graphics quality controls shared by the launcher and F1 menu, including
  anti-aliasing/blur, filtering, foliage distance, shadows and effects. Original
  settings remain the default; settings that need a restart say so.
- Add optional controller vibration, off by default, GPU selection/diagnostics,
  and a local support ZIP that can be reviewed before sharing.
- Address issue #12's competing resolution controllers in non-original aspect
  modes. Correct fractional high-FPS frame-count thresholds and temporal history
  resets; preserve the Original aspect and native save formats.
- Correct renderer feedback visibility, scaled texture gathers and zero-sharpness
  handling. Add optional bloom stability modes with Original still selected.
- Expand the portable build path to an older glibc baseline with source-built
  SDL/media/Python components. Separate the authored runtime from locally built
  game code, retaining content/ABI checks and full source-build fallbacks.
- Fix FSR **Match display refresh** in the actual Linux game build. The game
  limiter now uses the shared frame-generation feature flag, retaining fractional
  refresh targets and restoring the normal cap when interpolation is unavailable.
- Record measured Game and Output FPS samples in the run log while generation is
  selected, including with the on-screen counter hidden. Preserve warmup and
  unavailable states, actual NVIDIA accepted/failed counters, and FSR readiness.
- Keep experimental frame generation off by default. Add a launcher method
  selector for FSR 3 interpolation (2×) and, when its installed driver components
  are detected, NVIDIA Smooth Motion (2×, RTX 40-series or newer). Methods are
  exclusive; NVIDIA's driver controls its own hardware support and fallback.
- Add an optional **Match display refresh** limit for FSR generation. A 180 Hz
  display can request 90 real frames plus 90 interpolated frames per second,
  subject to the chosen game FPS ceiling and actual performance. This does not
  implement 3× generation from 60 FPS or 120-to-180 arbitrary-phase interpolation.
- Pace FSR's generated/real pairs on a persistent output timeline, prepare the
  second image ahead when safely available, and retain a serial fallback.
  Recover from missed deadlines and swapchain changes without catch-up bursts.
  Use FIFO presentation when FSR generation and VSync are both enabled.
- The on-screen counter shows **Game** FPS and successful **Output** presentation
  requests for integrated FSR, plus classified **Generated** FPS. An optional local Vulkan observer measures NVIDIA
  downstream output submissions while Smooth Motion is selected. Neither
  number measures physical scanout. Generated-only NVIDIA identity is unavailable;
  unavailable measurements remain labelled rather than estimated as Game × 2.
- Move completed FSR pairs to a bounded presentation worker so output waits can
  overlap production of the next real frame. Keep explicit GPU/image/queue
  ownership, limited-capacity fallbacks, error validation and reset drainage.
- Add private per-run requested-settings snapshots and bounded native effective
  settings/display/limiter logs. Retain up to 16 unmodified owned run records.
- Fix NVIDIA CUDA initialization blocked by read-only process metadata. A verified
  host supervisor starts the selected game outside the GUI's inherited guard;
  only the opted-in game admits writes to its own thread metadata. The GUI,
  unrelated files and other processes remain confined. No driver/system changes.
- Preserve existing save formats, settings and the frame-generation-off path.
  Authored component/GPU tests do not establish smoothness, input latency or
  full-game compatibility. The maintainer accepted the Linux development build; physical ultrawide and
  handheld testing is still requested. See [frame generation](docs/FRAME_GENERATION.md).


### Windows Experimental 0.1.0

- Add a native portable graphical setup EXE that builds from your own extracted
  game folder, shows progress and returns to the settings launcher on later opens.
- Bring the modern launcher and gameplay options to Windows, including optional
  cheats, the dedicated Quick Step slot, 99 manual save slots, high-refresh timing,
  Exit to desktop, party controls, aspect choices and the on-screen FPS counter.
- Add native graphics/provider, shader-preparation, input recovery, support-report
  and checked update adapters with independent Windows version metadata.
- **Windows remains experimental.** DLSS/DLAA and temporal upscaling still have
  reported purple flashes/flickering. Native builds and title startup do not
  establish full-game, save/reload, provider, clean-machine or all-hardware coverage.
- Keep Windows at its own **0.1.0** version. Ship its matching source/update archive,
  metadata and native/Python corresponding-source and relink companions with the EXE.

### Updating and defaults

- Linux requires a full local rebuild; existing input, settings, saves and Quick
  Step metadata stay in the original profile. No save conversion is required.
- Original aspect/quality defaults remain. Quick Step, cheats, vibration and frame
  generation remain off by default. Optional Quick Step may still have quirks in
  untested equipment/story combinations; broader coverage will improve over time.
- Thanks to **patrickksmdev** for isolating and testing the retained RADV artifact
  workaround, and to the handheld/ultrawide reporters for continued testing.

## 0.1.20 — November 14, 2026

- Add **Show FPS on screen** in Graphics, off by default, with a matching F1
  setting. The input-transparent counter stays visible in fullscreen and reports
  real game/render FPS, excluding generated and repeated presentations. Preserve
  the separate title-bar FPS preference and keep text outside frame generation.
- Keep reduced-resolution scene composites at the selected aspect ratio when
  they sample multiple inputs. Preserve the centered proportional HUD and
  portrait rendering, with bounded aspect diagnostics for further reports.
- Derive the checked renderer camera's aspect from its logical camera rather
  than independently rounded render dimensions. Original 16:9 stays the default.
  These are candidate corrections for reported ultrawide framing changes;
  reporter hardware gameplay validation remains pending.
- The maintainer accepted desktop/NVIDIA gameplay and the on-screen counter.
  Physical ultrawide validation is still requested; these checks are not full-game
  or all-hardware qualification.
- Updating requires a full local game rebuild and retains existing saves, settings
  and game input. Original 16:9 remains the default; Quick Step, cheats, the new
  FPS counter and experimental frame generation remain off by default. Windows
  stays the original implementation with a version-free download name.

## 0.1.19 — November 13, 2026

- Recover missed controller connection/removal events and retry failed opens on
  focus return or bounded idle checks. Preserve healthy controller selection and
  release cached held input after an overlay/disconnection, in the game and launcher.
- Keep Steam controller metadata live across atomic file replacements through a
  validated, session-scoped private read-only snapshot; preserve filesystem and
  save confinement. Actual Steam Deck/ROG Ally overlay-return testing is pending.
- Add Match the display and explicit 16:10, 21:9 and 32:9 aspect choices alongside
  Original 16:9, plus handheld/ultrawide window presets. Fixed ratios fit inside
  any screen/window with centered bars instead of stretching; choices are not
  hidden based on the monitor. Checked camera, culling and HUD-marker adapters support 16:10,
  21:9 and 32:9; menus/HUD retain a centered, proportional 16:9 canvas. Original
  16:9 remains the default. Gameplay, cutscene/effect and resize validation is
  pending; see [aspect-ratio notes](docs/ASPECT_RATIOS.md). No save conversion.
- Publish all five aspect choices on every monitor, independent of the window-size
  presets. Use the selected ratio for the first camera and subsequent render
  targets; retain native DLAA/SR content-extent agreement and centered bars.
- Updating requires a full local game rebuild and preserves the original saves,
  settings and shared input. Quick Step, cheats and frame generation remain off
  by default; frame generation remains experimental. Windows stays the unchanged
  original implementation with a version-free download name.

## 0.1.18 — November 13, 2026

- Fix Linux updates that fail during `package-appimage` with
  `source already contains generated release-only files`, after the game and
  native launcher have already compiled successfully. This affects full
  AppImage packaging from a downloaded source kit, including long-standing
  installations migrated to the persistent private Python environment.
- Verify the source kit and its generated distribution metadata before creating
  a normalized temporary source export for packaging. Keep the strict
  clean-source packaging checks; installed source, input, saves and settings
  are not rewritten as part of that normalization.
- Fresh graphical setup uses a separate initial-build path and did not exercise
  the failing update packaging step. No game feature or native save format
  changes are included. Windows remains the unchanged original implementation.

## 0.1.17 — November 13, 2026

- Add a graphical Linux builder AppImage. Select your own extracted DE 2.0.0
  `exefs`/`romfs` folder and a final installation folder, choose optional NVIDIA
  DLSS support and shader preparation, and follow real local build progress.
  The image bundles setup code, Python and the reviewed source template; it does
  not contain a game, game-derived code/assets or vendor SDK.
- Reopen the same AppImage to use the checked installation's settings launcher.
  Adopt an existing installation in place without importing or converting saves.
  Existing source scripts and updater-compatible source archives remain available.
- Add **Locate game files** when an installation's remembered input is missing.
  Validate the supported version and exact executable inventory before reconnecting
  known input links. Preserve saves, settings and immutable build receipts; no
  immediate game rebuild is needed. A later update can rebuild once at the new path.
  Busy installations, cancellation and mismatched input preserve the old selection.
- Keep private setup Python outside the AppImage's temporary mount and prevent
  generated bytecode from invalidating its checked runtime cache after building.
- Fetch and verify the pinned AppImage runtime before first-time standalone
  packaging. Check the staged candidate instead of an older active launcher,
  and preserve native-wrapper sibling imports during inherited-image startup.
- The maintainer completed graphical fresh setup/build and accepted normal reopen.
  A local existing installation was updated and manually confirmed to open and
  play normally, with saves/settings and input preserved. Automated recovery and
  hidden-UI tests pass. The local migration needed manually resumed packaging
  fixes; a clean uninterrupted older-version update and a real moved-folder picker
  test remain unqualified. This is not full-game or all-distro coverage.
- Updating requires a full local rebuild while retaining the original profile.
  Quick Step and cheats remain off by default; frame generation stays experimental
  and off by default. Windows remains the unchanged original implementation.

## 0.1.16 — November 13, 2026

- Preserve validated Steam/SDL controller context through the launcher and game,
  including the flag SDL needs to recognize Steam's virtual gamepad. Retain
  associated mapping and device-filter settings.
- Allow existing HIDAPI controller device nodes through the native state-write
  guard, keeping game input, saves and unrelated files confined as before.
- Add bounded controller discovery diagnostics and recover another usable pad
  when an open fails or the selected controller disconnects. Let the launcher's
  SDL/ImGui backend own its controller handles.
- These changes are likely to address the reported Steam Deck detection failure.
  ROG Ally X compatibility remains uncertain; neither handheld has been tested
  with this release. The maintainer accepted desktop/NVIDIA gameplay. New or recreated
  native HID device nodes can require restarting the launcher; see
  [handheld controller notes](docs/HANDHELD_CONTROLLERS.md).

- Prepare the RADV-only `nodcc` driver option before graphics initialization to
  work around colorful glowing dots reported on the Radeon RX 7600. Keep lean
  formats, the driver-owned heap optimization and NVIDIA rendering policies as
  before. Preserve existing RADV debug flags and provide a diagnostic opt-out.
- Thanks to **patrickksmdev** for testing both switches separately at the same
  Colony 9 location and settings: `nodcc` alone removed the artifacts, while
  disabling lean formats alone did not. The reporter observed no noticeable FPS
  loss or added stuttering; this is qualitative RX 7600 evidence, not a universal
  AMD performance claim.
- The maintainer accepted NVIDIA gameplay on both the preceding `nodcc`
  candidate and this combined build. Affected-AMD validation of the packaged fix
  is still requested. Native save formats and state locations are unchanged;
  updating requires a full local rebuild. See [RADV notes](docs/AMD_RADV.md).
- Label Windows downloads as the **original implementation**, without borrowing
  the Linux version number. Windows has not received the Linux additions. Future
  Windows kits retain that identity until Windows is explicitly updated.

## 0.1.15 — November 12, 2026

- Add a separate Cheats launcher tab with independent, off-by-default controls
  for party damage dealt/received, EXP/AP/SP/gold gained and no fall damage.
  Multiplier sliders cover 0x–20x in 0.01x (1%) increments. Settings apply when
  starting the game; disabled and exact 1x paths retain native behavior.
- Scale new awards rather than editing balances. Preserve native eligibility,
  caps, spending, healing and Expert Mode transfers of EXP already earned. Native
  save formats stay unchanged; rewards already earned remain after disabling.
- Move the existing Xenoblade 3 party-switching control from Controls to Mods,
  immediately beneath Quick Step, keeping its setting and behavior.
- The maintainer manually accepted the combined Linux build. Focused native,
  sanitizer, instruction and launcher tests passed; comprehensive DE/FC and
  damage-over-time/status-effect coverage remain unqualified. See
  [Cheats](docs/CHEATS.md) for controls and scope. No Arts-recharge cheat or Windows
  feature backport is included.
- Updating requires a full local game rebuild. Saves, settings and hidden Quick
  Step metadata remain in place without native save conversion. The AMD/RADV
  correction from 0.1.14 remains included; AMD gameplay performance still needs
  testing.

## 0.1.14 — November 12, 2026

- Add a capability-gated, driver-owned guest heap path for Mesa RADV, aimed at
  excessive AMDGPU user-pointer submission overhead. Keep NVIDIA on its existing
  import path and retain a checked RADV fallback. **AMD gameplay performance,
  including the reported RX 6700 XT case, still needs testing.** No specific FPS
  improvement is promised.
- Add focused allocation/failure, device-policy and heap-lifecycle coverage, and
  an explicit render-worker thread name for Linux diagnostics. Save formats and
  input paths remain unchanged. See [RADV compatibility notes](docs/AMD_RADV.md).

- Controlled memory-transfer tests passed on an integrated RADV GPU, including the
  full 3.25 GiB heap. The maintainer manually accepted NVIDIA gameplay; this is
  qualitative feedback, not measured FPS parity or full-game qualification.
- Updating requires a full local game rebuild. The updater retains saves,
  settings and hidden Quick Step metadata without changing native save formats.
  Quick Step stays off by default; frame generation stays experimental and off.
  Windows gameplay implementation and the glibc/Python baseline are unchanged.

## 0.1.13 — November 12, 2026

- Diagnose Linux prerequisites before compilation, including the current
  distribution/container, Python 3.14, libc, tools and required native libraries.
  Missing dependencies include distribution-specific package instructions.
- Add explicit `./Build_Monado_II.sh --install-deps` repair for supported Fedora 45
  Distrobox environments. Only the reviewed package-manager command may request
  sudo; generation and compilation remain under the ordinary user. Native hosts
  retain manual system-package setup, and background updates never install or
  prompt. Unsupported libc baselines stop with compatible-environment guidance.
- Preserve clean build-tool discovery and show bounded actual compiler/loader
  diagnostics in build errors. Existing input, saves, settings and optional
  Quick Step metadata retain their formats and locations. No renderer or gameplay
  behavior is changed.
- Updating requires a full local game rebuild because the build recipes changed.
  The updater keeps the working version selected until the replacement passes
  its checks. Missing prerequisites do not trigger package installation during
  background updates; install the reported requirements before retrying.
- The baseline remains Linux x86-64-v2, CPython 3.14, glibc 2.43+ and the required
  native GNU/audio/graphics interfaces. Fedora 45 and Debian userspace checks,
  a fresh native build and a real 0.1.12 updater rehearsal passed; actual Steam
  Deck/Bazzite desktop gameplay and interactive Distrobox installation remain
  unverified. Windows implementation is unchanged. No cheats are included.

## 0.1.12 — November 10, 2026

- Keep only the active Linux launcher and its required game payload after a
  successful update. The first updated launch also cleans accumulated older
  updater-owned builds and abandoned downloads. Interrupted or blocked cleanup
  retries safely; saves, settings, hidden Quick Step metadata, mods, useful caches
  and game input stay in place. Native save formats are unchanged.
- Reuse one independently owned game payload for compatible launcher-only updates.
  Keep the working build until its replacement is built, checked and activated.
  Local rollback history is discontinued; older versions remain available as
  manual downloads/builds from GitHub releases.
- Updating to 0.1.12 requires a **full local game rebuild** and temporary space for
  the old and new builds. An older updater may place this first rebuilt game in
  its version workspace; the following update can require one additional full
  rebuild to put it in the new reusable payload location.
- First-start cleanup can delay the launcher opening. An isolated upgrade rehearsal
  with a long update history took about **75 seconds** for maintenance and checks.
  Duration depends on update history, files and storage. Cleanup status is recorded
  in `Monado_Linux/updates/retention-status.json`.
- Restore native held-L2 camera controls and control-help prompts immediately
  with XC3-style party switching enabled. Keep L2 + L1/R1 party shortcuts,
  selected-controller checks, safe release handling and ordinary native taps.
- Port the party-switch object-discovery worker to Linux. Use bounded reads of
  the owned guest heap, preserve native party ordering/leader/HUD calls, and stop
  the worker and clear synthetic controls during a guest reset. The maintainer
  manually accepted the revised camera, control-help and party-switching behaviour.
  Broader field/battle, Future Connected and hardware coverage remains incomplete.
- Keep optional D-pad walking from competing with held-ZL camera controls.
- Default a newly selected Linux DLSS mode to **DLAA / Native (100%)**. Keep
  explicit saved quality choices, including Quality (67%), when reopening settings.
  **Reported shaking at 67% remains unresolved.** Select Native (100%) as the
  current workaround; the default change does not fix scaled DLSS rendering.
- Frame generation remains experimental and off by default. This release adds no
  new Bazzite compatibility fix or Windows backport; reported rendering artifacts
  and broader distribution/gameplay coverage remain open.

## 0.1.11 — November 10, 2026

- Make the optional dedicated **Quick Step gem slot** stable following the
  maintainer's manual acceptance. It remains **off by default** for players who
  prefer the original equipment setup; normal gem ownership, potency and caps
  remain in effect.
- Restore the saved assignment and its actual movement bonus through Load Game
  and Continue. Preserve the selected save's identity through native save caches
  so the matching optional metadata is applied after loading.
- Correct equipped **E** markers on gem rows and character portraits, including
  the distinction between the current character and another owner. Restore the
  ordinary gem chooser after leaving the bonus slot and use native menu sounds
  for its actions.
- Preserve recorded shader programs and shader-compiler constants until queued
  rendering consumes them, correcting the reported Bionis Interior crash. The
  maintainer reports that everything looks in order after this fix; exact scene
  coverage and full-game rendering remain unqualified.
- Keep native `.sav` formats and filenames unchanged. Optional Quick Step
  metadata stays with its save in the hidden `.monado-quickstep` directory;
  back up the **complete save folder, including hidden files**. No conversion
  or update-time profile move is required.
- Updating requires a **full local game rebuild**. The Linux updater retains
  the original input, saves and settings. Linux and Windows source/setup kits
  continue, including the Linux `-source` compatibility download; these fixes are
  Linux-only and the Windows implementation is unchanged.
- Frame generation remains **experimental and off by default**. Reported shadow
  boxes in Valak/Makna are queued for investigation and are **not fixed** by this
  release. Broader character/equipment/save-recovery, Future Connected, hardware
  and full-game coverage remain incomplete.

## 0.1.10 — November 9, 2026

- Add an optional, character-owned **Quick Step gem slot** beside boots in
  Change Equipment. Use native artwork and the normal gem menu filtered to
  eligible owned Quick Step I–VI, including newly crafted gems. Support bare
  feet, socketless or unique armour, and Fiora's drones without taking an
  ordinary gem slot. Enable it in the launcher's Mods tab; it is **off by default**.
- **Quick Step remains experimental:** the dedicated slot can be hit-or-miss or
  show UI quirks. Expect quirkiness; further fixes and polish are planned for
  future builds. Normal gem ownership, potency and caps remain in effect.
  Assignments are paired with each save using optional metadata; native save
  files retain their format. See the [Quick Step guide](docs/QUICKSTEP.md).
- Fix NPC trading's missing native dispatch cases. The maintainer reports that
  trading no longer crashes in the tested development build.
- Supply the complete pinned private media/runtime dependency graph, including
  FFmpeg's required `libbluray.so.3`, independently of the system's `.so.4`.
  Check library integrity, ABI versions and loading before long builds, after
  linking, and before Play, shader preparation or update activation.
- Discover native GNU C++ libraries without an Ubuntu-specific path and document
  Arch/CachyOS prerequisites. Both build modes pass isolated Arch userspace
  loading checks; this does not establish CachyOS/AMD/Wayland gameplay.
- Preserve verified game reuse for future launcher-only updates when the new
  dependency-check sources are unchanged.
- Updating requires a **full local game rebuild**. The Linux updater retains
  the original input, saves and settings; no save conversion is required.
  These changes are Linux-only; the Windows source implementation is unchanged.
  Frame generation remains experimental, off by default, and performance varies.
- Quick Step and trading received positive maintainer feedback. Full-game,
  Future Connected, every character/equipment/save/recovery case and additional
  hardware remain incompletely qualified. Source/setup kits contain no game files.

## 0.1.9 — November 9, 2026

- Expand each story to **99 manual slots plus its separate autosave** on Linux, preserving the
  four-card native scrolling menu. Unused slots show No data and create no files.
- Preserve existing manual/autosave filenames and the native save format. Keep
  main-game and Future Connected saves separate; protect the legacy remembered
  slot field while tracking extended selections outside the saved payload.
- Include extended slots in Continue and title save/clear checks through native
  asynchronous readers and validation. These serial scans may add startup or
  Continue wait time. Existing save transactions and recovery behavior remain.
- Reduce frame-by-frame overhead in initial Save/Load metadata scans by batching
  ready native read steps within a small call/time budget. Yield for pending
  reads and callbacks; keep writes and thumbnail reads at their ordinary cadence.
  Add one scan summary per initial menu scan for measurement. Actual wait time
  depends on populated slots, I/O and the host; no universal speedup is promised.
- The maintainer accepted the expanded-save development build and the scan
  improvement manually. This does not qualify 99 populated slots, every
  main-game/Future Connected save or recovery case, or full-game completion.
- Updating older Linux builds requires a full local game rebuild. The updater
  performs it while retaining the original input, saves and settings in place;
  no save conversion is required. Windows keeps its existing implementation;
  these features are Linux-only and Windows backports are not currently planned.
- Continue regular Linux and Windows source/setup kits, requiring the player's
  own legally dumped DE 2.0.0 input. Frame generation remains experimental,
  disabled by default, and can perform worse when enabled.

## 0.1.8 — November 8, 2026

- Add **Exit to desktop** below Options on the Linux title screen and after
  Title Screen in the in-game System menu, using native menu styling and
  confirmation dialogs. Keep Cancel/No selected by default; the positive button
  says **Exit**. Unsaved progress is not automatically saved.
- Preserve the existing title and System menu actions, including Continue,
  Load Game, New Game+, Event Theatre and main/Extra Story switching. The System
  entry follows Title Screen's availability restrictions; unavailable optional
  layout elements leave the original menu intact.
- On Linux host close, stop and join guest producers, drain queued rendering,
  then finish GPU and pipeline-cache work. Preserve the existing exit lock/grace
  and avoid graphics-library teardown while a render worker is still active.
- Fix confirmation ownership validation so the native endpoint object address
  is checked correctly. Retain dialog ownership, choice-count and negative-default
  checks. Add native regression coverage for caption linkage, original menu
  preservation, confirmation callbacks and render-completion waits during shutdown.
- The maintainer manually accepted both exit paths on the Linux candidate.
  Updating older Linux builds requires a local game rebuild; existing saves and
  settings stay in their original installation. Windows source is unchanged;
  this release does not add the new exit UI to Windows.

## 0.1.7 — November 8, 2026

- Retry transient Linux graphics-dependency download failures with bounded
  attempts and short backoff. Report the package and attempt so a timeout can be
  diagnosed. Keep HTTPS certificate verification, pinned sizes/hashes and strict
  cleanup; invalid cached files or integrity failures still stop the build.
- Reuse verified official package archives from the original installation during
  managed updates, copying them into the new workspace without changing the old
  cache. This avoids downloading the same graphics dependencies again when the
  exact locked files are already available.
- Preserve previous-version selection on failure, FG support in normal builds
  with the effect off by default, and version-aware update/rollback behavior.
  Game input, settings and saves stay in their original locations.

## 0.1.6 — November 8, 2026

- Include native frame-generation support in normal Linux builds and automatic
  rebuilds. The user chooses whether to enable it in the launcher; it remains
  **experimental and disabled in settings by default**. No extra build flag is
  needed. Explicit `--without-dlss` omits both providers because FG requires
  DLSS/DLAA. Keep `--framegen` accepted for older build commands.
- Rebuild older DLSS games that lack FG support instead of reusing them without
  the feature. Current updaters can rebuild ordinary FG builds automatically;
  footstep-diagnostic builds remain manual. Older custom FG installations using
  pre-0.1.6 updater code still need a one-time manual upgrade.
- Make the original installation's `update-version.json` reflect the active
  version. Preserve the original version in a manifest-checked backup and keep
  game input, saves and settings in place. Add `Rollback_Monado_II.sh` so rollback
  uses the retained version-aware updater and restores the visible version too.
- Keep canonical Quiver setup downloads, the Linux legacy updater compatibility
  download and checksum verification. No FG algorithm or performance improvement
  is claimed; performance can vary or be worse with it enabled.

## 0.1.5 — November 8, 2026

- Publish Linux and Windows **setup/build kits** with canonical `-setup` download
  names so Quiver's observed asset filter can recognize them. Keep a Linux
  compatibility download for installed updaters; game generation remains local.
- **Linux frame generation is experimental. Performance varies:** it can reduce
  performance, stutter or show visual glitches. Leave it off for normal play.
  Maintainer testing found the candidate mostly stable but preferred FG off;
  these changes do not establish a smoother experience or full-game coverage.

- Add explicit `--framegen` to the Linux local build, with pinned source setup,
  verified local SDK reuse, matched build-feature receipts and default-off runtime
  settings. Keep full experimental/diagnostic updater rebuilds manual.
- Preserve interpolation history through successful warmup instead of resetting it
  during ordinary repeated presentation. Restore ordinary pacing on failure/off.
- Prepare and submit the retained real image before the existing presentation
  deadline, overlapping that work with the wait. Bound deliberate waiting by the
  selected real-frame interval, keeping the SDK's measured motion timing intact.
- Count observed deliberate wait time as host idle, so it cannot falsely trigger
  the game's busy-time adaptation. GPU readiness and resource retirement remain.
- Add actual-source clock/history/heuristic regressions and authored GPU profiling
  at 720p/1440p. These are component results, not proof of improved display cadence.
- Keep shared input links ignored and limit source-header checks to declared
  shipped files, excluding local dependencies/builds from that source-kit test.

## 0.1.4 — November 8, 2026

- Fix Linux dependency compiler/linker flags when the installation folder contains
  spaces, such as `My Games/Monado II`. Apply FDO sysroot rules only to pkg-config flag
  requests, preserving literal variable queries used by launcher setup. Tested
  with pkgconf 1.8.1 and 2.5.1. Existing folders do not need to be renamed or moved.
- Add real pkg-config regression coverage for spaced paths. Preserve the existing
  input location, save profile, native DLSS/DLAA and updater behavior. Users build
  locally from their own input; no game-derived binaries or caches are shipped.
- Continue regular Linux and Windows source/setup kits. This is a Linux build
  tooling fix; Windows runtime/backports and full-game coverage are unchanged.

## 0.1.3 — November 7, 2026

- Add a **Linux stable-release updater**. Normal startup quietly checks the
  official release; a newer version offers **Update** or **Later**. Update
  verifies/downloads the source kit, builds locally with progress and Cancel,
  then restarts the launcher without pressing Play.
- Keep every managed version at a fixed path under `Monado_Linux/updates/`.
  Compatible presentation-only updates retain the verified game; other changes
  rebuild it locally. Preserve the existing DLSS build choice and the original
  shared input, saves and settings. Download/build/validation failure or
  cancellation leaves the previous selection active. Edited release-owned source
  stops automatic installation so local changes can be merged manually.
- Add explicit previous-version selection with
  `Monado_Linux/.venv/bin/python -I -B tools/update_linux.py --rollback` from the
  original installation root while its default profile is closed. This changes
  the active pointer; it does not restore/delete builds, input or saves.
- Bootstrap requires one manual **0.1.3 source upgrade/build**: 0.1.2 has no
  updater. Merge the verified source kit into the same original folder and rebuild
  to retain its profile; fresh kits elsewhere do not import old profiles. Full
  automated rebuilds of custom
  experimental frame-generation or footstep-diagnostic builds currently stop
  safely and require a manual rebuild. No Windows updater/backports are included.
- Retain the existing native Linux port, high-refresh animation/menu/footstep
  corrections, menu-speed preference, shader preparation, default DLSS/DLAA and
  generated launcher artwork. Frame generation remains optional and experimental.
  Continue **TheMonadoGuy / Monado contributors' Monado** and **Peiikai's
  LASRecomp**, with their notices preserved; see [credits](CREDITS.md).
- Publish regular Linux and Windows **source/setup kits**, requiring the player's
  own legally dumped DE 2.0.0 input and local game generation. No game files,
  compiled game binary, private SDK or runtime update directory is distributed.
  Existing Windows/full-game validation limits remain unchanged.

## 0.1.2 — November 7, 2026

- Restore the original generated landscape artwork to the launcher's left panel,
  with the exact asset recorded in
  [provenance](Monado_Linux/tools/launcher/assets/ARTWORK_PROVENANCE.md). No game
  screenshot or extracted game input was used; the separate local sword icon
  remains excluded.
- Include native **DLSS Super Resolution / DLAA** in the one-command Linux build
  by default. Fetch the pinned official NVIDIA SDK locally and pass the existing
  native-provider build option. `--without-dlss` explicitly omits it; setup
  failures stop the build instead of silently removing the feature.
- Check DLSS prerequisites up front: bubblewrap at `/usr/bin/bwrap`, `nm`, and
  the readable GNU C++ runtime. Preserve runtime GPU capability, state isolation,
  namespace and network checks.
- Keep the verified workspace GUI accessible when the AppImage launcher enters
  the DLSS private `/tmp` namespace. Retain embedded-GUI identity verification and
  the original build/input/state checks.
- Publish regular Linux and Windows source/setup releases. Players still provide
  their own legally dumped input and generate game code locally; no game binary
  or private SDK is shipped. Windows game-build and full-game coverage remain
  incomplete. Frame generation remains separate, optional and experimental.

## 0.1.1-source-preview — November 7, 2026

- Repair fresh source builds on hosts without `ensurepip`: bootstrap pip from its
  exact official locked wheel inside the workspace, with useful failure messages.
- Restore the omitted licensed bcdec header required by keyboard button prompts;
  add a source-kit relative-header closure check for both ports.

- Add a one-command Linux local build: `./Build_Monado_II.sh` checks prerequisites
  and input, installs locked workspace tools/dependencies, generates game code and
  builds the game, launcher and a local **Monado-II-x86_64.AppImage**.
- Create an empty `game_files/exefs` and `game_files/romfs` layout on the first
  explicit build if absent, then stop for the player's own extracted input.
  Existing folders or links are never filled or overwritten; external input can
  remain in place through a symlink.
- Add stage progress/logs/receipts, fresh outputs and protection of previous
  launcher images/builds and saves when rebuilding.
- The AppImage contains the native launcher and uses its sibling build workspace.
  Existing game/input/state/lease/receipt checks remain in effect; the bundled GUI
  must exactly match the verified original build. No game-derived data is included.
- Add `./Play_Monado_II.sh` to open the generated image without requiring FUSE.
  Opening the launcher and pressing Play remain user actions.
- Replace the long Linux command sequence with setup/build/play instructions,
  prerequisite guidance, external-input linking and honest workspace requirements.
  Optional DLSS/FG setup remains separate; Windows backports remain pending.
- Keep all generated AppImages, staging directories and filesystem payloads out
  of tracked source/releases. This download remains a source/setup kit; the
  launcher AppImage and game executable are generated locally.

## 0.1.0-source-preview — November 7, 2026

First public Monado II source preview, continuing **TheMonadoGuy / Monado
contributors' Monado** and **Peiikai's LASRecomp**. See [credits](CREDITS.md).
Separate Linux and Windows source/setup kits are provided. Neither kit is a
precompiled playable game; each player must build locally using their own legally
dumped DE 2.0.0 files from their own legally obtained Switch and game.

### Linux additions and improvements

- **Native Linux x86-64 port:** Linux fibers, thread-local and floating-point state
  handling, synchronization, platform services, reproducible local build tooling,
  and SDL/Vulkan integration without Wine or Proton.
- **High-refresh timing corrections:** menu/interface animations use elapsed game
  time, and held-direction navigation no longer accelerates with rendering FPS.
  This includes title/menu navigation and battle arts selection. The corrections
  adapt to the actual frame timing, rather than targeting only 165 FPS.
- **Menu navigation speed setting:** choose Normal (30 FPS style, default) or
  Fast (60 FPS style). This changes held menu/arts navigation cadence without
  changing world speed or animation speed.
- **High-FPS footstep correction:** animation phase and walk/run threshold repairs
  address the repeated, rapid footstep/grass sounds reported at high refresh rates.
- **30 FPS cutscene limiter correction:** retain the original cutscene period
  when a higher or fractional output rate is selected.
- **Native DLSS Super Resolution and DLAA:** optional NVIDIA NGX/Vulkan integration,
  native-resolution DLAA handling, temporal-history resets and resource-lifetime
  safeguards. SDK binaries/models are not bundled; optional setup is separate.
- **Working shader precompilation:** launcher progress, Stop, explicit retry and
  resume using locally recorded variants. Completed, partial, cancelled and failed
  runs have distinct results. Cache writes are checked and atomic; cancellation
  preserves useful completed work. This does not promise every shader or no hitches.
- **Experimental AMD frame generation:** optional FSR 3 interpolation, including a
  cutscene-only setting and compatibility with DLSS/DLAA. Off by default. Reported
  gameplay is slow and visually glitchy; leaving it off is recommended.
- **Redesigned native launcher:** responsive navy/crimson/cyan styling, embedded
  licensed fonts, clearer sections and action buttons, bilingual controls, and a
  larger 1267×804 default opening size. Existing settings and input-remapping flows
  are retained. The public preview uses a neutral Monado II wordmark; the local
  scenic artwork and sword icon are excluded pending redistribution review.
- **Safer launcher settings and state:** preserve custom/unknown settings, save
  configuration atomically, reload after game exit, and keep configuration, logs,
  caches and saves separate from read-only game input. A profile lease prevents
  conflicting game/precompiler sessions; Linux process/filesystem isolation is
  checked before launch.
- **Runtime correctness repairs:** applet focus/lifecycle and graceful close,
  IPC validation and scheduler synchronization, explicit save/commit error
  propagation with journal retention on failure, checked Vulkan host-memory
  import, and shader/pipeline-cache validation and safer persistence.

These are targeted corrections, not a claim that all high-FPS behavior or save
recovery is solved. See [platform status](docs/PLATFORM_STATUS.md) and
[remaining work](TODO.md).

### Windows source kit

- Preserves the original Windows Monado implementation and its attribution,
  including its existing DLSS/DLAA, AMD frame generation and shader precompilation.
  Those features originated upstream.
- Adds Monado II project documentation, build guidance and source-release
  safeguards. The public snapshot accepts plain TTF/OTF/TTC font input and omits
  proprietary-font decoding on both platforms.
- **The Linux gameplay fixes and launcher redesign have not been backported to
  Windows.** They are tracked in [TODO](TODO.md). This fork has not independently
  built or gameplay-tested the Windows port; Windows tooling CI is not a game-build
  validation.

### Publication and known limits

- Explicit reviewed source manifests, content/provenance checks, Linux/Windows
  authored tooling fixtures, deterministic platform archives, readback verification
  and SHA-256 checksums protect the source-only release boundary.
- No game input, generated game code/executables, translated game shaders, caches,
  keys, firmware, saves, private SDK binaries or uncertain artwork is included.
  The project will not provide game files or tell anyone where to obtain them.
- Linux manual testing reached opening cutscenes, battles and first Shulk control;
  DLSS and shader precompilation received positive feedback. Full DE, Future
  Connected, long sessions, save/recovery, other hardware and clean-machine builds
  remain incompletely validated. Public-only font/theme changes need further
  integrated validation.
- Linux FSR 3.1 Super Resolution, NVIDIA native frame generation, DLSS 5 and Ray
  Reconstruction are not implemented. Frame-generation repairs and Windows
  backports remain future work.
