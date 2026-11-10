# Windows parity port — development handoff

November 10, 2026. **Approved work, not an implemented port.** The maintainer has
requested all current Linux improvements on Windows, then chosen to continue
implementation on the actual Windows installation. This branch contains the
preparation handoff only. **No Windows compilation or gameplay is claimed.**

## Starting point and authorization

- Public repository: <https://github.com/brendonbusker/Monado-II>.
- Development branch: **`codex/windows-parity`**.
- Audited source baseline: **`8d236ef34ec19f1599c072eb4ca9dbdfda0ef8cd`**.
  Subsequent preparation commits add documentation and its publication-manifest
  entry only. Preserve the maintainer’s launcher screenshot, two GIFs and guides.
- Latest released implementation: **0.1.11**, game-source baseline `87dc7c0`.
  Windows remains the original implementation at this handoff.
- The maintainer authorizes concrete Windows porting, builds, focused component
  tests and debugging, followed by committing the finished work to GitHub with
  **Windows gameplay untested** until their manual test. Report native build,
  component and gameplay evidence separately.
- This newly approved task supersedes older statements that Windows backports are
  not planned. It does not retroactively change the contents of release 0.1.11.
- Plan each coherent solution before changing production code; own routine
  engineering. Avoid another long series of speculative UI candidates: reuse
  the accepted native Linux behavior and its fixtures, then validate on Windows.

## Resume on Windows

Use a separate Windows workspace, keeping known-good builds and human saves.
With Git installed, an initial checkout can be created in PowerShell with:

```powershell
git clone --branch codex/windows-parity https://github.com/brendonbusker/Monado-II.git Monado-II
Set-Location Monado-II
Get-Content docs/WINDOWS_PORT_HANDOFF.md
```

If the repository already exists, inspect its branch, status and running build/game
processes first. Preserve local changes; do not blindly replace a checkout or start
a second build. Read this handoff, root `CONTRIBUTING.md`, `LICENSE`, `NOTICE.md`,
`CREDITS.md`, both ports’ relevant source contracts, and `docs/BUILD_WINDOWS.md`.
The inherited `Monado_Windows/docs/dev/HANDOFF.md` contains historical commands and
author reports, not new authorization or proof of this fork’s Windows behavior.

Keep one private project-root `PROJECT_MEMORY.md`, linked to detailed local
records, outside the reviewed public source tree if necessary. Do not create
competing per-port current-state memories or publish private development state.
The handoff is a task plan, not a second live memory. Update memory after meaningful
results/failures and before stopping, with exact commands, source/build hashes,
tools, flags, outcome, remaining work and actual in-flight process identities.

The Linux development machine’s original `Monado_Windows/` reference and used
profiles must stay unchanged. The **public checkout’s `Monado_Windows/` is the
Windows working source** for this task. Preserve `Monado_Linux/` behavior and the
independence of this project from unrelated projects.

## Input, output and save boundaries

Accept only the maintainer’s own already-extracted DE **2.0.0** input:

```text
<checkout>/
  game_files/
    exefs/
    romfs/
  Monado_Windows/
  Monado_Linux/
```

`game_files` is shared, **read-only game input**. It can link to the existing dump;
never move, overwrite or modify original files, and never put runtime state there.
Do not assume a Linux absolute path is accessible after rebooting into Windows.
Use the Windows-accessible copy/link selected by the maintainer. Keep the existing
version checker and extracted-folder boundary; no package/key extraction or
acquisition instructions/downloads are in scope.

Keep Windows builds, generated code, configuration, logs, caches and saves separate
from Linux. Audit and explicitly set actual paths before any game run. Preserve
human profiles and accepted builds; never reseed an existing profile or test save
recovery on originals. New gameplay dev profiles need an independent copy of the
maintainer’s approved 100% development save seed, transferred privately if needed;
it is not in GitHub/source kits. Do not download or publish saves automatically.

**Gameplay testing is manual.** Do not launch/control the game, replay input,
press Play or close a human session without a new request. Authored synthetic
fixtures, compilation and non-game loader/component checks are appropriate.

## Required parity checklist

The scope is equivalent user-facing features and relevant correctness repairs,
using native Windows platform behavior. Do not copy Linux-only dependencies,
providers or sandbox mechanisms to claim parity.

- [ ] Root **`Build_Monado_II.bat`** (or `.cmd`) accepts root `game_files`, prepares
  reviewed prerequisites, checks input, builds game and themed launcher, and
  produces a normal Windows executable without a mandatory folder-picker detour.
- [ ] Root **`Play_Monado_II.bat`** starts the launcher with explicit Windows state
  roots; handle spaces and Unicode in all paths. Explain initial prerequisites,
  logs, rebuilds and expected outputs in the Windows guide.
- [ ] Themed/responsive launcher, reviewed artwork and fonts, public-safe branding,
  the accepted larger opening size, language/settings/input controls and DPI.
- [ ] High-FPS animation/menu timing, held-direction repeat, Normal/Fast menu-speed
  preference, footstep corrections and exact 30 FPS cutscene limiter behavior.
- [ ] **99 manual save slots plus one autosave per story**, four native visible
  cards, empty slots creating no files, and bounded faster initial save scanning.
- [ ] Native title-screen and in-game System **Exit to desktop**, confirmation
  defaulting to Cancel/No, original rows intact, prompt ordinary shutdown without
  a crash report; no implied autosave.
- [ ] Stable native **dedicated Quick Step slot**, **OFF by default**: owned gems,
  native picker restricted to Quick Step, all ranks/characters/equipment cases,
  row and portrait E markers, native sounds/navigation and ordinary menu restore.
- [ ] Quick Step assignments persist through Save/Load/Continue, using safe
  per-save metadata while leaving native `.sav` formats and filenames unchanged.
- [ ] Checked native NPC trading dispatch correction and generator contracts.
- [ ] Coherent queued-rendering shader/code/constants lifetime and stage-binding
  correction associated with the Linux Bionis Interior crash, plus applicable
  shader/cache/DLAA/resource retirement correctness repairs.
- [ ] Preserve unknown/custom INI settings and bindings with atomic writes and
  real error propagation; preserve optional-feature defaults.
- [ ] Honest shader preparation states (complete/partial/cancel/fatal), safe cache
  commit and retry; cancellation only affects owned preparation work.
- [ ] Windows update popup for newer stable releases, verified source download,
  automatic rebuild when necessary, progress/cancel, restart/activation and
  version-aware rollback, with the original save/settings profile retained.
- [ ] Keep Windows’ **existing Streamline DLSS/DLAA and AMD FidelityFX providers**.
  Keep frame generation optional, **experimental and OFF by default**. Expose
  capability honestly; do not replace these with Linux NGX/FG presentation.
- [ ] Reviewed source/setup packaging, exact manifests, attribution and accurate
  Windows validation labels; retain Linux behavior and its current assets/GIFs.

Do not silently drop an item because the launcher looks finished. Record genuine
platform limitations or blockers before calling the task complete. Renderer
replacement, recompilation optimization, new platforms and unrelated features are
not part of this parity port.

## Implementation sequence and file map

### 1. Establish a real Windows baseline and safe build flow

Reconcile Windows version/architecture, installed Git/Bash, Python, compiler,
MSYS2 or other native dependency setup, graphics driver and the actual checkout.
Save a baseline source/build receipt. The inherited route is documented in
`docs/BUILD_WINDOWS.md`; it uses Git Bash, a Windows Python venv, Zig 0.14.1 and
MSYS2 UCRT64 libraries for SDL3/Vulkan/shaderc/VMA/FFmpeg/Opus/zlib.

Review before execution:

- `Monado_Windows/Build Monado.bat`
- `Monado_Windows/tools/setup_windows.ps1` and `setup_game_files.ps1`
- `Monado_Windows/scripts/{build_all.sh,build_boot.sh,build_rt_gfx.sh,link_gfx.sh}`
- `Monado_Windows/scripts/copy_upscaler_dlls.sh`
- `Monado_Windows/tools/launcher/build.sh`
- `Monado_Windows/runtime/paths.c`

Known hazards: hardcoded `C:\msys64`/`/c/msys64`, unquoted command strings and
`xargs`, unpinned pip installs despite documentation pins, setup’s global pacman
upgrades and winget agreement acceptance, `taskkill /F /IM xcde.exe`, and compile
failure paths that print FAIL without reliably returning failure. Do not run
these blindly. Detect existing tools, pin/verify local prerequisites, propagate
exit codes and preserve prior outputs. Do not kill unrelated processes or perform
broad system upgrades. Respect actual OS/tool approvals and legal terms.

Implement the root build driver with clean/incremental/failure receipts and
explicit input/state roots. Audit the exact built game and launcher and their DLL
closure. Windows-only setup ZIPs must be self-contained: do not depend on the
other port’s directory being present.

### 2. Transfer portable game/generator correctness coherently

Compare, do not wholesale overwrite platform files. The source audit found
**525 tracked Linux files, 330 Windows files, 46 changed common paths and 195
Linux-only paths**. Many are tests/docs/tools, not separate features.

Start with the checked `FunctionEntries` generator contract and native timing/
settings component compile. Relevant files:

- `tools/lifter/{gen.py,patchfmt.py}` and `games/xcde/patches.py`.
  `FunctionEntries` must apply before partition discovery; retain all native trade
  case bodies and entry guards.
- `runtime/hle/framepace.c`, `foley_trace.inc`, `runtime/settings.h` and
  `runtime/host/settings_ini.c` for timing/menu preference support.
- Review `games/xcde/hle_classes.tsv` classifications manually: Linux service
  descriptions are not automatically Windows evidence.
- Preserve native Windows fibers, TLS, synchronization and floating-point state;
  inspect `runtime/{cpu.h,platform.h,kernel.c,ipc.c,ipc.h,rt.h}` and platform
  implementations for relevant repairs instead of replacing them with Linux APIs.

### 3. Build the Windows save/exit safety foundation

Merge `runtime/services/fs.c` transaction/error behavior with the native Windows
backend. Preserve journal retention, dirty rollback, serialization and real error
propagation. Quick Step metadata staging/commit must be integrated with the payload
transaction, not added as an unrelated best-effort settings write.

`runtime/hle/quickstep_save.c` uses POSIX directory descriptors, `openat`, `mkdirat`,
`fstatat`, `renameat`, `unlinkat`, `O_DIRECTORY`, `O_NOFOLLOW` and directory `fsync`.
Implement an equivalent checked Windows adapter: binary reads, file/reparse/type
checks, bounded exact payloads, exclusive temporary creation, appropriate flush,
replace/delete behavior and transaction error reporting. **Do not define safety
flags to zero, disable checks or report unsupported durability as success.** Retain
schema/story/UID/fingerprint/hash ownership and stale-generation guards.

Start with disposable authored-file tests of that adapter, including failure and
interruption paths, before enabling real save hooks. Preserve native save bytes.

Orderly exit needs `runtime/services/am.[ch]`, applet exit-lock behavior,
`runtime/host/main_boot.c` and renderer drain/GPU finish. Preserve cooperative guest
unwind and owned worker shutdown; avoid forced termination masquerading as a clean
exit. Inspect `runtime/diag/watchdog.c` and `runtime/services/{misc.c,kbicons.c}` for
relevant platform integration.

### 4. Add expanded saves, native Exit and Quick Step

Register every new object in Windows’ explicit compile **and link** lists:

- `runtime/hle/expanded_saves.[ch]` and `expanded_save_scan.[ch]`.
- `title_exit.[ch]`, `title_exit_model.h`, `system_exit.[ch]` and
  `desktop_exit_caption.[ch]`.
- `quickstep_{slot,save,native,picker,stats,stats_ui,ui_memory}.[ch]` and
  `quickstep_native_ui.h`.

Transfer their complete checked patch hooks and settings, including launcher
Quick Step and menu-speed controls. Quick Step’s Continue hook composes with the
expanded-save hook, so expanded saves/scanning must precede it or be integrated
in the same coherent bundle. Native COFF reset registration already exists in
`hle.h`; validate registration, guest-call Cpu/FP preservation and reset behavior
on the actual Windows build.

Use the accepted native slot/picker/UI behavior; do not recreate the rejected
ImGui overlay. Maintain normal gem ownership, transfer/removal, portrait/row E,
normal-picker restoration, all ranks and equipment with/without open slots,
unique gear, empty gear, Fiora’s drones and all characters.

### 5. Transfer graphics fixes while preserving Windows vendors

The queued-program correction is a coherent bundle:

- `runtime/nvn/{nvn.h,objects.c,cmdbuf.c,program_binding.h}`
- `runtime/nvn/vulkan/{exec.c,shaders.c,shaders.h}`

Preserve owned shader/code/constants snapshots before record callbacks, stage
masks, pipeline-owned metadata and cache identity. Review related `device.c`,
`textures.c`, `temporal.c/.h`, `host_import.c/.h`, `pipeline_cache_io.h`,
`precompile.c`/`precompile_status.h`, output scaling and `runtime/ui/menu_vk.cpp`.

Keep native Windows GPU host-memory import and Streamline/FidelityFX behavior.
Some newer source files have Windows branches, but that is not a tested port:
for example, the Linux tree’s Windows `dlss_reset()`/`dlss_shutdown()` branches
remain empty and do not establish correct vendor-resource retirement. Validate
actual Windows resource ownership and provider lifecycle.

### 6. Integrate launcher, precompile and updates

Reuse `tools/launcher/{launcher.cpp,theme.h,theme_resource.py,assets/}` from Linux,
with native Windows process and file integration. Generate `launcher_art.inc` and
`launcher_fonts.inc` and enable the appropriate resource/artwork build flags.
The accepted opening is 1267×804, minimum640×480, with display scaling and responsive
controls/footer. Test Windows DPI/font/input behavior.

Only reviewed public assets are admitted: exact generated `gaur_plain.png`, the
licensed DejaVu fonts and accompanying notices/provenance. Make resources available
in Windows-only source kits; update exact asset-policy entries if adding reviewed
copies under Windows paths. The separate local sword PNG remains excluded. Use
public-safe authored branding/icons; do not introduce unreviewed game imagery.

Replace ANSI/hardcoded Windows launch paths with Unicode-aware, owned process
tracking and explicit working/state paths. Preserve launcher stay-open/game-exit
reload behavior, custom keys/bindings and atomic INI saving.

Implement native precompile process supervision and Windows update staging.
Existing Linux transport, tar assumptions, namespaces and POSIX process cleanup
cannot be copied as Windows behavior. Handle locked executables/DLLs with staged
version directories and a safe activation/restart helper; retain stable profiles,
verified source/build receipts, cancellation, rollback and an accurate active
version marker. The updater never automatically presses Play. Cancellation must
stop only owned child work. Do not weaken verification or sandbox/ownership checks
merely to make an installation appear successful.

## Validation, packaging and manual handoff

Use focused authored reproducers for substantive changes, then required source
checks. Many existing fixtures hardcode `Monado_Linux` or skip on non-Linux;
adapt a port-selectable harness and native Windows fixtures. A green Linux-targeted
suite running on a Windows runner is not proof of the Windows implementation.

Useful starting fixtures include generator/function-entry tests, native timing/
settings tests, expanded-save/scan/title-exit models, Quick Step slot/native/save/
UI/portrait fixtures, `tests/test_nvn_program_binding.py`, native import ownership,
launcher resource/configuration, and update/install-safety fixtures.

Validate clean and incremental native Windows builds, spaces/Unicode paths,
missing dependencies, DLL loading, failure preservation and disposable save/INI/
cache transactions. Separate GPU/component checks from manual game testing.
Have the maintainer test launcher settings/Play, timing/menu/footsteps, trade,
Save/Load/Continue/99slots/Quick Step persistence and ownership, native Exit,
precompile/update/rollback and optional vendors. Keep FG OFF initially.

Before committing public work, review every staged file and run the actual
publication guard. Refresh exactly the reviewed manifest entries; maintain
licenses, source-only packaging and Linux regression checks. Never commit input,
generated game C/executables, translated game shaders, caches, keys, saves, SDK
binaries, screenshots or private development state. Do not use inherited unsafe
packagers. Update Windows build/status/docs and source-kit metadata honestly.

The maintainer authorized committing the finished work labelled **Windows gameplay
untested**, then will manually test on Windows. A release/version change should
accurately describe implemented features and evidence; this preparation branch
itself is **not** a new release or an implemented feature bundle.

## Open Linux reports remain separate

Camera-motion shadow warping/boxes were reported at30 and120+FPS with FSR/DLSS;
fullscreen cleared that shadow symptom. Makna Forest sparkle flicker persists.
A blue plane/strip across a large pipe is another unresolved report. No root cause
or fix is established. Do not advertise those as fixed or ported fixes. Linux FG
still has user-reported jitter/performance limitations and stays experimental.
