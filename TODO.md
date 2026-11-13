# Monado II TODO

Unchecked items are potential or planned work, not implemented/validated features.
**Windows parity is approved for development on the maintainer's Windows host.**
This preparation branch includes Linux0.1.16 as the reference and leaves Windows
runtime source unchanged. Use [the current handoff](docs/WINDOWS_PORT_HANDOFF.md)
and [source inventory](docs/WINDOWS_PARITY_INVENTORY.json); older deferred notes
and the 0.1.11 plan do not describe the current scope.

## Windows parity — ordered work

- [ ] Audit native host/tools/dependencies; harden inherited build failure handling,
  paths, process ownership and object lists; root game_files → Build/Play BAT →
  native launcher/game executables with reproducible receipts.
- [ ] Preserve Windows fibers/TLS/FP/synchronization and vendor providers; implement
  safe native save/config/cache transactions and orderly owned exit first.
- [ ] Port checked generator/trading/timing/menu/footstep bundles, expanded99saves
  and bounded scanning, native Exit, queued-program/constants lifetime correction.
- [ ] Port complete stable OFF-default Quick Step native UI, ownership/portrait E,
  sounds/navigation and Save/Load/Continue metadata without native save conversion.
- [ ] Port fixed L2/HUD/party controls, Win32 party worker safety, reset/release
  handling and robust SDL controller selection/diagnostics/context delivery.
- [ ] Port Cheats tab: six0x–20x sliders in0.01x steps plus no-fall; all OFF, native
  eligibility/caps/spending/Expert transfer preserved; no faster Arts recharge.
- [ ] Port themed/responsive launcher/resources/DPI/config preservation, party
  toggle to Mods under Quick Step, newly selected DLSS Native100% default.
- [ ] Adapt honest precompile status/cancel/retry and Windows provider lifecycle;
  retain Streamline/FidelityFX, FG experimental/OFF. Scaled67% shaking is unresolved.
- [ ] Implement verified platform-aware Windows updater/rebuild/activation and
  current-only retention, protecting saves and deferring busy/modified trees;
  no local rollback history and no Linux archive/version confusion.
- [ ] Adapt native Windows fixtures and clean/incremental/failure build checks;
  manual feature matrix/AMD+NVIDIA/DE+FC; report missing coverage honestly.
- [ ] Review Windows-only source kit resources, source guards, notices and build
  documentation; assign a distinct Windows identity only after implementation.

Linux-specific sysroot/Landlock/hidraw/namespace/distro repair/RADV mechanisms are
not Windows features to copy. Retain existing Windows platform and vendor support.
Preparation/source CI does not establish native Windows build or gameplay parity.

## Linux correctness and coverage

- [x] Stabilize the dedicated Quick Step slot: restore saved bonuses through
  Load Game/Continue, native row/portrait E markers, normal chooser restoration
  and native menu feedback. Keep it off by default for the original-game preference.
- [ ] Expand Quick Step character, equipment, save/recovery and Future Connected
  coverage beyond the accepted manual scenarios.
- [x] Preserve recorded shader programs and compiler constants for queued draws;
  the Bionis Interior crash correction received positive manual feedback.
- [x] Restore held-L2 camera input and native control-help prompts with optional
  XC3-style party switching; provide Linux party discovery and keep optional
  D-pad walking from competing with held-ZL controls. The maintainer accepted
  the revised controls manually.
- [ ] Expand field/battle, Future Connected and controller coverage for those
  camera and party-switching controls.
- [x] Default newly selected Linux DLSS to DLAA / Native (100%) while preserving
  explicit saved quality choices.
- [ ] Diagnose and fix reported DLSS Quality (67%) shaking. Native (100%) is the
  current workaround; the 0.1.12 selection default is not a rendering fix.
- [ ] Investigate reported shadow boxes in Valak/Makna. They are not fixed in
  0.1.12; exact causes and affected scenes remain to be established.
- [ ] Confirm actual CachyOS/AMD/Wayland gameplay and additional distribution
  builds. Isolated Arch userspace loading/media passes do not cover native GPU,
  audio/session or optional plugin behavior.
- [ ] Reconcile current-version Bazzite diagnostics and qualify host/container,
  Python and GUI/CLI environment handling. The historical missing-codec report
  used the older dependency set; no new Bazzite fix is included in 0.1.12.
- [ ] Improve experimental frame-generation pacing/performance and visual quality
  after the current publication work; keep its warning and off-by-default setting.
- [ ] Validate more gameplay, demanding scenes, long sessions and Future Connected.
- [ ] Validate disposable save/reload/journal recovery and failure durability.
- [ ] Expand extended-save coverage across main-game and Future Connected,
  including 99 populated manual slots, thumbnails, Continue and recovery.
- [ ] Expand high-FPS follower/damping/cutscene coverage and FP exception semantics.
- [ ] Test AMD/Intel/other hardware and remaining diagnostics/input behavior.
- [ ] Validate the public plain-font, restored-artwork and DLSS paths across more
  gameplay scenarios, drivers and hardware.

## Releases and onboarding

- [x] Add a one-command Linux local build and generated launcher AppImage that
  keeps game data outside its payload and preserves checked workspace state.
- [x] Restore the exact generated launcher illustration with provenance and
  default DLSS/DLAA support, with an explicit `--without-dlss` build option.
- [x] Add Linux stable-release offers, verified source downloads, local update
  builds, progress/cancellation and stable profiles.
- [x] Retain only the current launcher and its required game payload after checked
  activation; clean accumulated updater-owned history without changing saves,
  hidden Quick Step metadata, settings, mods or useful caches. Remove local
  rollback history; manual downgrades remain available through GitHub releases.
- [x] Rehearse the installed 0.1.11 upgrade and first-start cleanup using an
  independent copy, checking protected profile contents and legacy bootstrap
  selection. This did not change the original installation or test gameplay.
- [ ] Expand real-system update/restart/interruption and manual-downgrade
  validation across supported environments.
- [ ] Improve first-start cleanup responsiveness and measure longer update
  histories; the isolated long-history rehearsal took about 75 seconds for
  maintenance and post-checks, with duration depending on files and storage.
- [x] Include FG capability in normal Linux builds and support ordinary FG full
  rebuilds with the 0.1.6+ updater, retaining the off-by-default runtime setting.
- [ ] Support automated full rebuilds of footstep-diagnostic builds without
  dropping their diagnostic features. Pre-0.1.6 custom FG clients need one manual upgrade.
- [ ] Validate the workspace launcher AppImage on more distributions/desktops;
  it currently requires the complete local build folder and its absolute receipts.

- [ ] Run real clean-machine Linux and Windows local-build checks.
- [ ] Test public source/setup kits on both platforms; Windows remains unvalidated
  by this fork until those checks are recorded.
- [ ] Review future authored-launcher/installer binaries and dependency notices
  separately. Never publish a game-derived executable or cache.
- [ ] Review further proposed artwork/icons before adding them to source/releases;
  only the exact illustration recorded in the provenance is currently admitted.
- [x] Provide a safe, user-friendly local build flow without bundling game content.
