# Windows parity — current development handoff

November 13, 2026. **Preparation only; no Windows features have been ported by
this branch update.** It incorporates the full released Linux **0.1.16** source
and replaces the November 10 / Linux 0.1.11 plan. The maintainer will reboot into
Windows for implementation and manual testing. Read root [AGENTS.md](../AGENTS.md).

## Decision: latest repository, existing Windows native backend

Use the latest **whole Monado II repository** as the development base, and its
`Monado_Windows/` as the working target. Bring the accepted portable Linux changes
across in coherent bundles, using `Monado_Linux/` and its tests as references.
Keep Windows fibers/TLS, allocation/write-watch, native process/file behavior and
Streamline/FidelityFX integrations. This combines the latest fixes with the
existing Windows foundation; converting the Linux tree wholesale would introduce
Linux syscalls, ELF libraries and driver assumptions while risking working
Windows features. No shared-core/renderer/code-generation redesign is required.

Reference identities:

| Reference | Identity |
|---|---|
| Accepted/released Linux reference | `v0.1.16`, commit `88e639ccab47d19b967e6a0ba2be354ba1393e1e` |
| Reference tree | `82264e2f5c971ca8016cf259dff3c9dacab26176` |
| Reference publication manifest SHA256 | `058581aeed4944184cd11724791856c8e3c55501c04c1988da4e4201d5855809` |
| Previous handoff branch tip | `01d7cdf9c98b24533b214ab9a633d09f972917bd` |
| Windows implementation in this preparation | Original, unchanged; native build/gameplay unvalidated by this fork |

The branch merge preserves the previous handoff history and includes current
main as its other parent. All implementation files initially equal the 0.1.16
reference; only preparation docs, branch guidance and their manifest differ.
The [source inventory](WINDOWS_PARITY_INVENTORY.json) records **545 Linux / 330
Windows files, 330 common paths, 48 changed common paths and 215 Linux-only paths**.
Those are source-path counts, not feature estimates: Linux-only includes scripts,
tests and nonportable platform code. The old 525/46/195 inventory is obsolete.

## Resume on the actual Windows installation

For a fresh checkout, run in PowerShell:

```powershell
git clone --branch codex/windows-parity https://github.com/brendonbusker/Monado-II.git Monado-II
Set-Location Monado-II
git status --short --branch
Get-Content AGENTS.md
Get-Content docs/WINDOWS_PORT_HANDOFF.md
```

For an existing checkout, first inspect its branch, changes and running jobs;
fetch the branch and integrate without discarding local work. Do not use a blind
reset, clean, checkout replacement or a second concurrent build. The README's
banner identifies this as preparation, not a Windows download ready for users.

Read root `CONTRIBUTING.md`, `LICENSE`, `NOTICE.md`, `CREDITS.md`, the per-port
contribution rules and relevant `docs/contracts/`, then [BUILD_WINDOWS.md](BUILD_WINDOWS.md).
Private inherited `docs/dev/HANDOFF.md`/task history is **not shipped** in this
public branch; its absent commands are not prerequisites or proof of a build.
Use this self-contained plan and the actual source. Historical author reports
remain distinct from this fork's native Windows evidence.

The user authorizes implementation, local component tests, builds and debugging
on Windows. Plan each coherent solution, then execute routine work; do not stop
at another high-level plan. Keep exact private evidence and a single private
project-root `PROJECT_MEMORY.md` (ignored), with private records under
`Monado_Windows/runs/`. The public handoff is a reference, not a second
current-state memory. Keep private memory/input/state outside clean publication
exports; never remove human files simply to make a source guard pass.

## Boundaries and expected user experience

- Root `game_files/exefs/` and `game_files/romfs/` are the single read-only input.
  Accept only the user's already-extracted DE **2.0.0** files, retain the existing
  checker and refuse unsupported input. A Windows folder link may select an
  existing Windows-accessible dump without moving it. A Linux absolute path is
  not automatically accessible after reboot; inspect the mounted folders first.
- All Windows build/generated/config/cache/log/save output remains separate under
  `Monado_Windows/`. Preserve human profiles, prior builds and the Linux port.
  Never write into shared input or convert native `.sav` format as a shortcut.
- New gameplay dev profiles use independent copies of the approved private 100%
  save seed if available. It is **not in GitHub**. Never reseed an existing profile,
  download a replacement save or test interrupted-save recovery on originals.
- **Gameplay/visible launcher testing is manual.** Do not start/control the game,
  press Play or terminate a human session without a request. Authored synthetic
  tests, native component/loader checks and compilation are authorized.
- Source-only commits/kits: no game/generated C or binary, translated game shader,
  cache, save, key, firmware, vendor SDK binary, unreviewed artwork or private log.
  Preserve licenses, attribution and exact source/package guards.

Target onboarding (to implement, **these root Windows scripts do not exist yet**):

```text
Monado-II/
  game_files/{exefs,romfs}/
  Build_Monado_II.bat
  Play_Monado_II.bat
  Monado_Windows/   # working source + separate local outputs/state
  Monado_Linux/     # current Linux reference; retain behavior
```

A user places their own input in `game_files`, runs **Build_Monado_II.bat**, then
opens the resulting native launcher `.exe` or **Play_Monado_II.bat**. A thin BAT
entry can call a reviewed PowerShell/Python driver and invoke Git Bash internally
where still needed. It should diagnose missing host prerequisites precisely,
fetch/pin permitted project-local dependencies, check input, generate/build,
verify the game/launcher DLL closure and report exact output/log paths. No WSL
or Linux sysroot is part of the target. A Windows-only kit must work without
`Monado_Linux/` present. The existing `Monado_Windows/build/xcde.exe` and
`xcde_launcher.exe` are inherited output names, not observed new build results.

Handle spaces and Unicode end to end, including command arguments, root input,
working directory, dependencies, state, DLL paths, reports and updater helpers.
Normal builds stay unelevated. No broad package upgrades, silent EULA acceptance,
process-name-wide kills or automatic game start. Default builds retain supported
vendor capabilities; runtime options remain honest and off where specified.

## Complete parity target and implementation order

Every checkbox is **planned, not implemented on Windows**. Sequence the work in
small buildable commits; do not silently omit gameplay features behind a finished
launcher. Existing authored Linux fixtures are specifications, not Windows passes.

### 1. Reconcile tools, harden the build and establish a native baseline

- [ ] Record Windows x86-64 version, GPU/driver, Git/Bash, Python, compiler/linker,
  SDL/Vulkan/shaderc/VMA, FFmpeg/Opus and optional vendor versions; inspect paths,
  actual input and running process identities. Keep prior artifacts intact.
- [ ] Detect and pin an appropriate Windows toolchain. The inherited route uses
  Git Bash, MSYS2 UCRT64, Windows Python and Zig **0.14.1**. Source CI uses Python
  3.14; verify runtime/generator requirements rather than inheriting Linux glibc
  or assuming the old Python3.12+ guide qualifies every current generator path.
- [ ] Audit/harden `Monado_Windows/scripts/{build_all,build_boot,build_rt_gfx,link_gfx}.sh`,
  `tools/launcher/build.sh`, `tools/setup_windows.ps1`, `tools/setup_game_files.ps1`,
  `scripts/copy_upscaler_dlls.sh` and `Build Monado.bat` before executing them.
- [ ] Preserve errors and previous outputs; use fresh per-build directories and
  explicit compile/link object lists instead of linking every stale object.
  Add root Build/Play wrappers, explicit input/state roots and receipts. Build
  the native baseline and verify DLL loading before manual gameplay.

Confirmed hazards: `build_boot.sh`'s `cc1` can turn compile failure into an echo;
`build_rt_gfx.sh` defaults to `taskkill /F /IM xcde.exe` without explicit
`XCDE_EXE`, and has unquoted C++ paths; scripts hardcode `/c/msys64/ucrt64` and
use object globs. Setup performs broad `pacman -Syuu` twice, unpinned pip and
winget agreement acceptance. The old BAT can offer to start the launcher.
Do not run those blindly or treat a printed success as evidence. The inherited
recipe in BUILD_WINDOWS is a starting reference, not a proven safe one-command
new build. First establish failure propagation/owned process behavior.

### 2. Preserve platform semantics and build save/exit safety first

- [ ] Retain native `runtime/platform/windows.c`, Windows fibers in
  `runtime/hle/fibers.c`, TLS/synchronization and crash behavior. Review applicable
  `runtime/{cpu.h,platform.h,kernel.c,ipc.c,ipc.h,rt.h}` corrections individually.
  `CreateFiberEx` currently uses flags0: explicitly test MXCSR/FPCR-equivalent
  state, cross-thread resume/TLS and synchronization; Linux FP fixes do not prove
  Windows fiber state safety. Preserve strict unsupported/error behavior.
- [ ] Implement disposable authored Win32 file-transaction fixtures before real
  save hooks: bounded binary reads, ordinary-file/reparse checks, exclusive temp
  creation, flush/replace/commit errors, journal retention, cancellation and retry.
  Do not zero out POSIX safety flags or report unsupported durability as success.
- [ ] Adapt `runtime/services/fs.c` and `runtime/hle/quickstep_save.c` together.
  The latter uses `openat/mkdirat/fstatat/renameat/unlinkat`, directory descriptors,
  `O_NOFOLLOW/O_DIRECTORY` and directory fsync. Native Windows sharing/locked-file,
  reparse and durability semantics need real adapters and failure tests.
- [ ] Preserve story/UID/fingerprint/hash/generation ownership and integrate Quick
  Step metadata into the payload transaction. Keep native `.sav` bytes/filenames
  compatible and hidden metadata beside the correct save; no unrelated best-effort
  settings write. Also cover atomic INI and shader/pipeline-cache writes.
- [ ] Transfer `services/am.[ch]`, applet lifecycle/exit locks, `host/main_boot.c`,
  watchdog and owned guest/worker/render/GPU shutdown coherently. Exit must return
  normally without a crash report or a long forced-termination freeze.

### 3. Transfer checked generator and portable gameplay bundles

- [ ] `tools/lifter/{gen,patchfmt}.py`, `games/xcde/patches.py`, classifications and
  relevant CPU/dispatch fixes: keep FunctionEntries before partition discovery,
  audited trade switch targets and strict checks. No success stubs or game-CPU
  fallback claims. Regenerate locally from verified input; never copy Linux
  generated outputs, caches or game binaries.
- [ ] High-FPS animation/held-repeat timing, **Normal30 / Fast60** menu navigation,
  footstep phase/threshold corrections and exact30FPS cutscene behavior through
  `hle/framepace.c`, `foley_trace.inc`, settings/parser and checked patch hooks.
- [ ] **99 manual slots + separate autosave per story**, four native visible cards,
  No data without empty files, bounded initial scanning and Continue/title checks:
  `expanded_saves.[ch]`, `expanded_save_scan.[ch]` plus their patch integration.
- [ ] Native title and System **Exit to desktop**, negative-default confirmation,
  existing Continue/Event Theatre/Extra Story rows and restrictions retained:
  `title_exit.[ch]`, `title_exit_model.h`, `system_exit.[ch]`,
  `desktop_exit_caption.[ch]` plus ordered shutdown above. No implied autosave.
- [ ] Stable **dedicated Quick Step slot**, **OFF by default**: native animated
  slot/picker, only owned Quick Step I–VI, normal ownership/transfers/removal,
  native sounds and row/portrait E indicators; no rejected ImGui overlay.
- [ ] Quick Step Save/Load/Continue restoration and ordinary-picker navigation:
  `quickstep_{slot,save,native,picker,stats,stats_ui,ui_memory}.[ch]`,
  `quickstep_native_ui.h`. Keep all characters, no boots/no native slot, empty
  native slots, unique/slotted/filled gear and Fiora's drones supported. The
  Continue hook composes with expanded saves; port the complete bundle.
- [ ] NPC trading dispatch and queued-rendering lifetime fixes associated with
  the Bionis Interior crash. For queued programs use the coherent bundle
  `nvn/{nvn.h,objects.c,cmdbuf.c,program_binding.h}` and
  `nvn/vulkan/{exec.c,shaders.c,shaders.h}`: code/constants snapshots, stage masks,
  pipeline metadata and cache identity must remain consistent.

Cheat patch declarations are generic; no Linux condition needs removing from
those declarations. Port helper objects, settings and checked hooks together.

Register **every** new helper in Windows compile **and link** lists. Preserve HLE
registration/guest-call Cpu+FP state and reset hooks on the actual COFF build.
Some Linux files already contain `_WIN32` branches; this is not evidence that the
new feature uses them correctly or that those branches contain all Linux repairs.

### 4. Current controls and all accepted cheats

- [ ] Immediate held-L2 camera/HUD prompt behavior, shoulder party-switch chords,
  optional D-pad walking arbitration and clear-on-release/reset/disconnect/menu/
  focus/rebinding behavior: `hle/{input.c,pad_modifier.h,party.c}`, kernel reset.
- [ ] **Explicitly port Windows party worker safety.** Latest `party.c` retains
  an infinite Sleep-loop Windows scanner and some direct HUD reads while the
  stop/join/reset and guarded read repairs are Linux-gated. Adapt epochs, valid
  object checks, lock/thread/event ownership and stop/join to Win32; simply copying
  the file is insufficient. Preserve native Windows discovery.
- [ ] SDL open-failure fallback, delayed arrival, active removal/reselection,
  neutral held state, bounded diagnostics and single ImGui handle ownership:
  `hle/input.c`, `platform/sdl_controller_diagnostics.h`, launcher. Preserve
  applicable Steam/SDL settings through the Windows launcher/child environment
  without duplicate physical+virtual inputs. No hardcoded device-name requirement.
- [ ] **Cheats tab:** independent enables for damage dealt, damage received,
  EXP/AP/SP/gold gained and no fall damage; all **OFF**. Six sliders cover0x–20x,
  **0.01x steps**, represented as integer0…2000percent (100=1x).
- [ ] Port `cheats_{combat,rewards}.[ch]`, `cheats_math.h`, settings/parser,
  generator hooks and launcher config round trips together. Preserve disabled/1x
  identity, party source/target eligibility, AI-party behavior, caps and single
  award scaling. Healing, spending and Expert Mode transfers of earned EXP stay
  native; already-earned gains remain after disabling. No fall damage applies to
  ordinary landings, not generic invulnerability. Faster Arts recharge excluded.
- [ ] Move the existing XC3 party-switch toggle to **Mods beneath Quick Step**,
  preserving its config key and current fixed behavior.

### 5. Launcher, providers and shader preparation

- [ ] Reuse the current Linux `tools/launcher/{launcher.cpp,theme.h,theme_resource.py,assets/}`
  presentation/native widgets, branding, larger1267×804 default (min640×480),
  language/input/audio/mod/cheat settings and responsive layout. Apply Unicode
  native process/file/state paths, owned handles and Windows DPI/font behavior.
- [ ] Generate artwork/font includes in Windows build. Use only the exact reviewed
  generated landscape and licensed DejaVu resources/notices. Windows-only kits
  currently exclude the Linux resource directory, and artwork policy is
  path-specific: add reviewed Windows resource paths and exact guard fixtures.
  Do not weaken guards into general image admission or add the local sword PNG.
- [ ] Preserve unknown/custom INI keys and bindings with atomic writes, real
  errors and post-game reload; ensure game/launcher interpret new settings alike.
- [ ] Newly selecting DLSS defaults to **DLAA / Native100%**, retaining explicit
  saved quality. This Linux UI transition is still Linux-gated; implement the
  Windows branch explicitly. **67% shaking remains unresolved**, not a repaired
  behavior to copy or advertise.
- [ ] Retain Windows **Streamline DLSS/DLAA and FidelityFX Vulkan FSR/FG** providers.
  Review resource/history ownership, shutdown/reset, import and cache corrections
  with actual Windows providers. Some latest Windows dlss_reset/shutdown branches
  are empty; portable declarations do not establish safe resource retirement.
  Do not substitute Linux NGX or experimental Linux FG presentation.
- [ ] Keep FG **experimental/OFF by default**, with honest capability and warning
  labels on Windows too. Validate with FG off first; no performance guarantee.
- [ ] Port honest shader-precompile complete/partial/cancel/fatal results, safe
  cache commit and explicit retry. Native Windows child supervision/cancellation
  must target only owned work. Preserve normal Windows shader/provider features.

### 6. Native updater and understandable prerequisites

- [ ] Reuse policy/fixtures from root `tools/{update_release,update_linux,update_retention}.py`,
  Linux `install_lease.py` and build/launcher supervision; implement native Windows
  archive/platform/version selection, verified staged source/build/manifest/DLL
  closure and accurate active-version metadata. The Linux driver is not a ready
  Windows updater. Never pick a Linux archive because its version is newer.
- [ ] Quiet popup **only when a newer compatible Windows implementation exists**,
  progress/cancel, automatic local rebuild when required, verified activation and
  restart without pressing Play. Windows exe/DLL locks need an owned native helper.
- [ ] **Current-only retention**, superseding the old handoff's rollback design:
  failed/cancelled preparation leaves current build selected; only after successful
  activation may recognized obsolete owned versions/downloads be removed. No
  local rollback helper/history. Manual older-version downloads remain available.
- [ ] Preserve complete saves/hidden Quick Step metadata, settings, input and useful
  caches. Use leases/ownership/reparse checks; safely defer busy, unknown or modified
  trees. Never follow an untrusted link/junction during cleanup or kill an unrelated
  process. Prove failure/activation/cleanup on disposable installations first.
- [ ] Adapt clear prerequisite diagnostics and exact package/tool/DLL instructions
  for Windows. Explicit local dependency setup can fetch reviewed pinned tools;
  elevation/system installation or vendor agreements require actual platform/user
  authorization. Do not transplant Fedora/dpkg/glibc/Distrobox repair.

### 7. Qualification, packaging and versioning

- [ ] Native Windows fixtures and build receipts, clean/incremental/failure builds,
  spaces/Unicode, missing tools/DLLs, compile/link failure propagation, config/cache/
  save transactions, locked-file/reparse/interruption cases and owned shutdown.
- [ ] Adapt port-selectable fixture harnesses. Many current tests hardcode
  `Monado_Linux`, ELF/rpath/pthread/mmap or skip outside Linux (e.g. rewards,
  party, controller discovery). A green source CI job on Windows is not proof of
  Windows runtime parity. Reuse pure pad/math/models and authored fixtures first.
- [ ] Maintain Linux behavior/packaging and the accepted source guard. Reviewed
  clean exports only; never run inherited unsafe game-copying packagers.
- [ ] Update Windows user/build/status/change notes and source-only kit metadata
  after actual implementation, with exact native build/component/gameplay limits.
  Until then keep **original implementation**, the version-free Windows filename
  and independent Windows identity. Do not borrow Linux0.1.16 as Windows's version.

The maintainer previously authorized committing implemented Windows work labelled
**Windows gameplay untested**, then testing it on their Windows installation.
This preparation does not produce a new release or justify a parity claim.
Plan a distinct Windows implementation/version and platform-aware update channel
when implemented; do not use the original kit's `source_release_version` as an
update signal. Stable Linux release/update metadata stays unchanged by this task.

## Manual acceptance checklist for the later Windows dev build

Provide the exact launcher/build/profile paths and changed features, then stop
for the maintainer's manual game test. Preserve all prior profiles/builds.

| Area | Required checks |
|---|---|
| Setup | Fresh root game_files build; spaces/Unicode; missing dependency message; existing input unmodified; error leaves accepted build usable; Windows-only kit self-contained |
| Launcher | Art/fonts/DPI/layout, all tabs, bindings, unknown settings, defaults and round trips, game start/return and report paths |
| Timing | 30/60/120/165 or chosen rates, title/menu Normal/Fast, battle Arts repeat, animations/cutscenes/footsteps |
| Saves | Main story and Future Connected, four visible cards through99manual+autosave, No data/no empty files, Continue/thumbnails, disposable failure recovery |
| Quick Step | All characters/ranks/gear cases, owned-gem transfer and removal, row+portrait E, native sounds, normal picker restore, save/load/Continue/restart persistence, OFF behavior |
| Exit | Title rows including Continue/Event Theatre/Extra Story; System; Cancel/No default; no autosave, freeze or crash report |
| Controls | L2 camera/HUD immediately and on release, party chords, walking arbitration, menus/focus/reset/disconnect/rebinding, delayed/failed-first/replaced controller, no stale or duplicate input |
| Cheats | Each off/0x/1x/fractional/20x, exact percentages/reopen, caps, party AI, normal healing/spending/Expert transfer, ordinary falls; no Arts recharge |
| Rendering | Trading and Bionis scenes, native Windows AMD/NVIDIA separately, Streamline/FidelityFX, DLSS new selection100% + saved quality preserved, cache/precompile cancel/retry; FG experimental last |
| Updater | Platform/version selection, popup/no-popup, checksum/manifest rejection, rebuild/cancel/failure, locked activation, active version marker, current-only cleanup with saves/metadata intact |

Missing hardware/scenes remain explicitly unqualified. A title screen or source
suite is intermediate evidence, not a full DE/Future Connected pass.

## Linux-only mechanisms and unresolved issues

Keep the useful portable semantics, not literal Linux implementations:

- RADV driver heap uses fixed-address mappings/dma-buf/fds; `nodcc` is a Mesa RADV
  option. **Neither is a generic Windows AMD setting.** Preserve Windows import/
  vendor policy and measure Windows AMD separately. Retain patrickksmdev's Linux
  provenance without claiming a new Windows graphics fix.
- No Linux sysroot, ELF loader, glibc floor, `ucontext`, Landlock, `/dev/hidraw`,
  private `/tmp` mounts or Linux UID/file-mode checks as Windows dependencies.
  Windows needs applicable native process/file/device/context behavior.
- Steam Deck detection remains likely, Ally X unconfirmed on Linux016. Those
  claims do not establish Windows handheld support.
- Scaled DLSS67% shaking, Valak/Makna shadow boxes, Makna sparkle flicker and blue
  pipe/plane reports remain open. Fullscreen helped one shadow symptom; it did
  not establish a general fix. FG can still stutter or reduce performance.

**First work after reboot:** reconcile the native host/checkout/input/state,
audit and harden baseline build failure/ownership behavior, implement root build
flow, then run a small real Windows generator/timing/FP/fiber/file-transaction
component cycle. Record actual errors and continue debugging before handoff.


## Concrete first probes after tool reconciliation

These commands are source-inspected starting probes, **not Windows passes from
this handoff**. Use fresh disposable outputs and bound any test process with an
owned timeout; stop only that child if it hangs. Do not reuse accepted outputs.

From repository-root PowerShell, after the Windows venv/test dependencies exist:

```powershell
.\Monado_Windows\.venv\Scripts\python.exe -B .\tests\test_function_entries.py EntryContract.test_guards_before_returning_entries_and_other_module_ignored EntryContract.test_wrong_build_or_any_changed_word_fails_closed EntryContract.test_whole_generator_emits_every_checked_dispatch_destination -v
```

Those three pure tests inspect the **Linux reference generator**, not a Windows
backport. Adapt a port-selectable fixture after transfer. Do not run the whole
file as a native Windows test: its native dispatch case uses mmap. The current
framepace runner is Linux-specific; build a Windows timing/FP fixture explicitly.

From Git Bash in `Monado_Windows`, after pinning/verifying the native Zig tool:

```sh
mkdir -p build/windows-parity-component-r1
.venv/Scripts/python -m ziglang cc -std=gnu11 -O1 -UNDEBUG -march=x86_64_v2 -ffp-contract=off -fno-strict-aliasing -w -Iruntime -o build/windows-parity-component-r1/test_fibers.exe tests/native/test_fibers.c runtime/hle/fibers.c
build/windows-parity-component-r1/test_fibers.exe
```

This adapts the actual inherited fiber fixture command to fresh output. It checks
fiber switching/migration basics; add actual FP/TLS/reset/ownership assertions as
needed, rather than interpreting that fixture alone as complete FP qualification.
The inherited `scripts/native_tests.sh` also overwrites fixed platform objects;
audit it before use. No test above accesses the user's game input or saves.
