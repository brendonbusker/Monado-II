> Public snapshot: detailed local engineering evidence is retained
> privately; evidence links below lead to the public coverage summary.

# Linux change ledger for inherited source

## November 14, 2026: LINUX-094 optional fullscreen FPS counter

- `runtime/settings.h`, `runtime/host/settings_ini.c`, launcher and F1 UI:
  independent OFF-default `show_fps_overlay`; preserve title-bar FPS settings.
- New `runtime/ui/fps_meter.h`, `fps_overlay_draw.h`, `menu_vk.cpp` and menu API:
  monotonic real-frame sampling and separate input-transparent ImGui context,
  readable physical-output layout, warmup/resume/reset handling.
- `runtime/nvn/vulkan/device.c`: sample once per real acquired game frame; draw
  FPS after generation on each output without entering retained/interpolated
  images. Enabled window captures include it. Reset after render drain on reboot.
- Extend authored native presentation fixtures with overlay ordering, image
  layouts, captures and both FG outputs; add meter/config/launcher/UI fixtures.
  No game data, runtime CPU fallback, new dependencies or global overlay service.

## November 14, 2026: LINUX-093 aspect stability candidate

- `runtime/nvn/vulkan/exec.c`, new `runtime/nvn/aspect_composite.h`: preserve
  existing scene/HUD rules and recognize a conservative fullscreen scene-source
  contract for reduced-resolution, multi-input composites. Keep portrait/atlas/
  minimap/instanced UI handling and proportional HUD. Add bounded decision logs.
- `runtime/host/xcde_aspect.[ch]`, `games/xcde/patches.py`: use the same checked
  logical camera for renderer projection/FOV qualification, independent of
  rounded render dimensions. Preserve Original identity and nonreference cameras.
- `runtime/nvn/vulkan/device.c`: bounded selected-aspect/output-placement logs.
- Authored native fixtures reproduce old classifier/camera rounding failures;
  actual reporter ultrawide gameplay remains to be confirmed. No game data,
  translated shaders or external renderer implementation added to source.

The supplied archive did not contain `docs/UPSTREAM.md`, despite references to it in its contribution guide and notices. This file begins the Linux ledger; it does not reconstruct or certify the author's missing historical ledger.

Source provenance: the user-selected 547-file snapshot is recorded in project-root `docs/linux_port/source_snapshot_20261104.json`. Its notices attribute the generator/runtime base to LASRecomp commit `136f679` under MIT. No upstream checkout or Git history is bundled or assumed.

LINUX-001/002 initially added local packaging safeguards and a Linux component-test script without changing runtime/lifter behavior. Subsequent changes follow below; preserve `[XCDE]` annotations.

## November 4, 2026 — LINUX-002/003

| Inherited file | Linux change and purpose |
|---|---|
| `runtime/hle/fibers.c` | Preserve Windows branch; add guarded native Linux contexts, synchronized transfer/migration, destination thread fields, FP/unwind cleanup and reset. New `fiber_context_linux.{c,h}` and `fibers.h` support this implementation. |
| `runtime/kernel.c`, `runtime/rt.h` | Clean up native roots after guest return/unwind and reclaim fibers after joins; atomic cooperative stop flag, destination TLS accessor barriers and dispatch of the free deterministic baton during blocked shutdown; LP64 trace arguments; bounded Linux diagnostics return an explicit unavailable result when thread-list lock cannot be acquired, avoiding an unlocked walk during reset. |
| `runtime/platform/linux.c`, `runtime/platform.h` | Complete re-exec arguments, checked executable paths/process handles, interrupted waits, affinity/thread names, x86-64-v2 CPU preflight, per-thread alternate signal-stack ownership/cleanup and reliable interrupted PC reporting. |
| `runtime/host/main_boot.c` | Conditional Windows startup/export code, bounded same-PID Linux re-exec, pthread periodic watchdog with checked intervals. |
| `runtime/diag/watchdog.c` | Linux pthread/monotonic reporting and checked stall intervals; Windows branch retained. |
| `tests/native/test_fibers.c` | Preserve Windows tests; add Linux migration/register/FP/stack/lifecycle/death coverage. |
| `NOTICE.md` | Identify the GPL-enabled FFmpeg binaries actually tested in the local Linux development sysroot; preserve original source and Windows dependency attributions. |

New authored Linux test fixtures, focused runner, dependency lock and setup script
are covered by the repository license. No game-derived source/shaders or external
backend implementation was copied into this patch. glibc synchronous contexts and
installed/local libraries supply the platform APIs. Exact evidence and limits are
recorded in root `docs/linux_port/2026-11-04-linux-platform.md`.

Canonical current state lives only in project-root `PROJECT_MEMORY.md`.

## November 4, 2026 — LINUX-002/004/005/006

| Inherited file | Linux change and purpose |
|---|---|
| `runtime/paths.c`, `paths.h` | Explicit validated input/state roots, safe output creation, isolated defaults and refusal to delete shared input; old fixed probe overwrite removed. |
| `runtime/host/main_boot.c` | Initialize paths/write guard before platform logs, worker startup and precompile; checked game suffix paths. |
| `runtime/platform/linux.c`, `platform.h` | State-only logs and real Linux memory residency/map diagnostics with explicit Linux semantics. |
| `runtime/kernel.c` | Atomic heap-size publication to the asynchronous renderer; guest region synchronization unchanged. |
| `runtime/nvn/vulkan/exec.c` | Checked shared host-memory import, compatible coherent memory and explicit failure; retire imports only after render-worker flush and before heap remap; Linux memory labels. |
| `runtime/nvn/vulkan/precompile.c` | Checked POSIX 64-bit file extent and input suffix validation before output writes. |
| `runtime/nvn/vulkan/dlss.cpp`, `temporal.c` | Retain Windows implementation; report DLL-backed optional modes unavailable on Linux. |
| `runtime/ui/menu_vk.cpp`, `runtime/host/settings_ini.c` | Honest Linux options/fallback notices, preserved C linkage and embedded menu font; no false vendor-success result. |
| `runtime/services/kbicons.c`, `runtime/services/fs.c` | Native font/cache support and fail-before-write save mount truncation checks. |
| `scripts/platform_tests_linux.py`, native platform/boot tests | Real path/guard integration, pipe capture, compiler baseline handling, enabled assertions and memory observations. |
| `graphics-deps-linux.lock.json`, `NOTICE.md` | Pin/attribute local zlib dependency; preserve existing license distinctions. |

New authored files include build/CLI/resource/path/GPU runners, Landlock state
write guard, host-import helper, graphics options and focused synthetic fixtures.
No external backend implementation, game source/assets or translated shaders
were copied into tracked source. Source-level render ownership checks complement
actual helper/device tests; they do not establish live renderer integration.
[Detailed evidence](../../docs/PLATFORM_STATUS.md)
records accepted build, failed hypotheses, exact commands and missing coverage.


## November 4, 2026 — LINUX-002/007

| Inherited file | Linux change and purpose |
|---|---|
| `tools/lifter/test_simd.py` | Correct source root, restore binary differential harness, verify complete outputs/failures, bounded exclusive evidence directories/commands/hashes; fix same-base/index synthetic store addresses. No emitted game semantics changed. |
| `runtime/cpu.h`, `platform.h`, `platform/linux.c`, `kernel.c` | Establish and check host FP baseline at fresh Linux guest pthread entry; preserve saved fiber environments. Document portable accessors' role. Exact noninteractive error-dialog control preserves fatal logs/exit. |
| `tests/native/test_kernel_fibers_linux.c` | Reproduce polluted-parent rounding/FTZ/DAZ at actual guest entry and verify parent preservation in both scheduler modes. |
| `runtime/services/am.c` | Implement boot-lifetime suspended-tick event91 with distinct copied handles, and counter90 for the explicitly active-only application lifecycle; normal waits are not process suspension. WindowController10 models idempotent foreground acquisition for the already-focused native app; no new desktop/focus transition. |

New authored SIMD/FP/IPC/fatal-notice fixtures and the bounded strict-boot supervisor
retain reproducible failures and explicit architectural/coverage limits. No game
assets/generated code or external service implementation copied. Detailed evidence
and current acceptance state: [SIMD/FPCR and strict boot](../../docs/PLATFORM_STATUS.md).


## November 4, 2026 — LINUX-007/008 applet lifecycle

| Inherited file | Change and purpose |
|---|---|
| `runtime/services/am.c` | One synchronized boot-state owner, validated focus/notification policy, independent lifecycle event handles and real native-close/exit-lock coordination. Native app stays active; no invented HOME/sleep suspension. |
| `runtime/ipc.c` | Bound domain CMIF payload/object bytes and exclude domain header from service payload size; malformed requests fail before handlers read absent data. |
| `runtime/kernel.c` | Dispatch an idle deterministic baton after external event wake, guarding virtual timer callback reentry. Existing blocked host-notification failure reproduced first. |
| `runtime/nvn/vulkan/device.c` | Route SDL_QUIT and continuous/idle event polling through the tested native close adapter; guest cleanup continues under LockExit. Explicit guest exit behavior retained. |
| `runtime/services/fs.c` | Propagate File.Flush/Commit persistence failures; check recursive traversal/file sync and Linux directory sync before deleting rollback journal. Wider creation/recovery durability remains unproved. |
| `scripts/am_tests_linux.py`, `tests/native/test_am_linux.c` | Actual normal/domain IPC, malformed lengths/flags, state reset/race, real SDL events, close deadlines, blocked wake and virtual timer regression tests. |

New authored `runtime/services/am.h`, `runtime/host/applet_lifecycle_ui.h`, save
fixture/runner and detailed evidence accompany these changes. No external code,
game source/assets or generated shaders were copied. The15second grace period
releases an exit lock; existing GPU teardown can still delay process termination.
[Lifecycle evidence](../../docs/PLATFORM_STATUS.md).

## November4,2026 — LINUX-008 parental client lifecycle

`runtime/services/misc.c` now distinguishes initialized factory0 from factory1
clients awaiting Initialize1, with synchronized per-object ownership, close/reset
cleanup and an explicitly unavailable native parental-policy provider. No host or
console policy is read, disabled or enforced. Inherited policy-query stubs retain
their outputs and remain classified as stubs; unsupported commands remain strict.
`runtime/ipc.h`/`ipc.c` preserve send-PID descriptor presence independently of its
placeholder value. New authored focused IPC fixture/runner cover that contract.
Public libnx client shapes and an ignored local SDK audit inform the interface;
no external implementation or generated game source is copied. The native client
lifecycle does not claim full Horizon initialization or parental-control parity.
[Lifecycle evidence](../../docs/PLATFORM_STATUS.md).

## November4,2026 — LINUX-009 native graphical launcher

`tools/launcher/launcher.cpp` retains the inherited SDL3/ImGui settings interface
and Windows branch, adding native Linux paths/guarded state, checked atomic
settings saves, preserved custom settings/last-key precedence, supported-capability
UI and child process lifecycle. `linux_host.h` supplies Linux argv/exec/wait,
local report, atomic file and bounded SDL test-event helpers. Existing translation
strings are treated as text where appropriate to remove format-string warnings.
No external implementation or new UI library is copied. Bundled ImGui/SDL licenses
remain unchanged.

New Linux build/entry/UI/settings test scripts and authored fixtures preserve
receipted builds, state locks, actual settings-parser parity and actual UI Play
validation. Workspace shell/desktop entries open the native launcher. Game source
and generated code are unchanged by this launcher cycle. Linux precompile is
explicitly unavailable until failure/skip semantics are validated; no false
success or automatic skip was added. Atomic GUI save retention is tested before
rename; post-rename directory-sync failure cannot promise rollback. Inherited
in-game settings-save and malformed-parser gaps remain recorded.
[Launcher evidence](../../docs/PLATFORM_STATUS.md).


The launcher’s existing post-child settings reload now rescans mods and clears
stale binding capture; a real UI-loop fixture reproduces success/failure exits.
The bounded test supervisor records pending TERM/HUP/INT signals and raises only
between bounded pipe-drain polls, preventing a reproduced consume-before-retain
output loss. One absolute deadline and descendant cleanup remain enforced.
Actual-UI test receipts also preserve interruptions and evidence-write failures,
and reject forced cleanup as a clean pass. These are local test-tool correctness
changes, not changes to the game’s signal/timing behavior.


## November4,2026 — LINUX-010 native play-report refusal

`runtime/services/misc.c` now registers Linux-only `prepo:u` command10103
(SaveReportWithUserOld2). It validates the IPC envelope, then returns the known
Prepo PermissionDenied result under the project's explicit no-telemetry policy.
It never inspects, stores or transmits report contents. Unknown commands retain
strict diagnostics and cannot report success outside strict mode. This is not
full Horizon play-report/offline-setting parity. Public command/result contracts
and the selected SDK caller were audited; no external implementation was copied.
New synthetic actual-IPC tests preserve the original abort and validate normal/
domain responses, protected buffers, malformed requests, reset and strictness.
Launcher entry defaults select the new receipted game while preserving older
builds and the existing GUI. [Evidence](../../docs/PLATFORM_STATUS.md).


## November4,2026 — LINUX-010 idle-time extension state

`runtime/services/am.c` adds Linux ISelfController62/63 setter/getter state,
validated enum/envelopes and existing mutex/reset ownership. The active native
application retains SDL's existing game-lifetime screen-idle inhibition request
for all modes; no fake console timers/transitions or guest-thread SDL calls.
This does not guarantee compositor/system suspend behavior. Existing AM fixture
and runner add normal/domain/shared-object/reset/concurrent state checks and
malformed-request failures, preserving a before-fix strict62 reproducer. No
external implementation, game code, renderer or platform changes were copied.
[New Game evidence](../../docs/PLATFORM_STATUS.md).

## November5,2026 — LINUX-011 high-FPS GUI timing

`runtime/hle/framepace.c` supplies the existing engine's elapsed seconds to the
GUI animation clock at its own update callback, through a checked instruction
hook in `games/xcde/patches.py`. The original two-reference-period frame clamp,
GUI/node speed and pause behavior remain; world/skeletal/cutscene clocks are not
globally rescaled. The same file corrects rounded native-cutscene limiter targets
by switching the exact interval/period pair. Synthetic native tests cover clock
boundaries, state preservation and failures; optional selected-input component
analysis remains local and generates no distributable game content. No outside
implementation was copied. Integrated behavior still needs manual validation.
[Timing evidence](../../docs/PLATFORM_STATUS.md).

## November5,2026 — LINUX-012 held-input repeat

`runtime/hle/framepace.c` and `games/xcde/patches.py` replace the fixed reference
period at27 checked held-duration reads with the existing engine's elapsed time,
capped at the framework's two reference periods. This preserves borrowed input
records, raw held/press/release masks, per-object timer reset and repeat policy.
The scalar load and its upper-vector clearing remain explicit. Boundary tests and
selected-code consumer probes cover native30Hz and variable/high rates; manual
title/menu/battle validation remains separate. No external implementation copied.
[Repeat evidence](../../docs/PLATFORM_STATUS.md).

## November5,2026 — LINUX-013 passive grass/footstep diagnostics

`runtime/hle/foley_trace.inc`, included by framepace.c, logs bounded local event
metadata only when explicitly compiled with `scripts/build_linux.py --foley-trace`.
Six checked hooks retain original instructions and observe accepted markers,
contact-count changes, authored/surface sound requests and animation resets.
Ordinary builds disable the helper; no game-state edits, sound suppression,
playback-rate changes or audio correction is claimed. Native/selected-code negative
controls and passive CPU/memory/budget tests are recorded separately from live
listening. Existing clock/object synchronization is reused; enabled logging has
overhead. No external implementation copied.
[Audio investigation](../../docs/PLATFORM_STATUS.md).


## November5,2026 — LINUX-017 native Linux NGX SR / DLAA

Adapted `runtime/nvn/vulkan/{dlss.cpp,temporal.c,temporal.h,device.c,exec.c,textures.c}` and `runtime/nvn/output_scale.c` for the separately licensed native NGX provider, portable temporal prep/HUD, completed-submission resource retirement, reset/borrowed-pointer lifetime, and native DLAA pixel extents. New authored provider/bridge/API files use pinned ignored SDK headers/library; no SDK implementation copied. `runtime/{host/settings_ini.c,ui/graphics_options.h,ui/menu_vk.cpp}` and the existing native launcher retain supported mode mappings while exposing qualified DLSS and keeping Linux FSR3/framegen unavailable. Linux build/checked entry isolate and verify local companion resources. No generator/timing/game patches changed; no renderer replacement or DLSS5/FG integration. Component evidence and manual integration limits: [Linux DLSS record](../../docs/PLATFORM_STATUS.md).

LINUX-017 startup correction: checkedentry now isolates desktop XDG runtime locks while preserving Wayland/audio/DBus endpoints. Native Linux dlss.cpp enables the supported bufferDeviceAddress feature explicitly when NGX requests its extension; unsupported hardware falls back without feature use. Exact pre-fix failures and focused tests remain in the active Linux DLSS record.

## LINUX-020 native frame generation

Adapted `runtime/nvn/vulkan/{temporal.c,temporal.h,device.c,exec.c}` plus newLinuxinterpolation/pacinghelpers to the locally source-built AMD FidelityFXSDK1.1.4 compute API. ExistingVulkan/SDLrenderer/ordinaryswapchain/guestclockretained; generated+retainedrealimagesonrenderthread, no SDKWindowsproxy/presenter. NewproviderwrapperverifiesABI/source/version andcontexttimelineownership; LinuxF1/parser/launcher/build/checkedentrycapabilitygates retainunsupportedfallback. SDKsource/license/provenance arepinnedby `fsr-linux.lock.json`/`scripts/setup_linux_fsr.py`; originalsourceignored, build-working-copy portabilitypatches preserveasserts/typedalignment/bounds andallrequiredshaderpermutations. Newauthoredfixtures validatepixels,HUD,history/lifetime,sourcepresentationorder/monotonicpacing andUI/config. No generator/gameCPUoptimization, no framegeneration fromduplicatedsimulation. NativeGPUcomponentpassesdo notqualifyphysicalgamepacing; [Linuxrecord](../../docs/PLATFORM_STATUS.md).

## LINUX-021 experimental feature status

Linux-only wording in `runtime/ui/menu_vk.cpp` and `tools/launcher/launcher.cpp`
marks frame generation experimental and warns about slow performance/visual
glitches after user testing. Behavior, defaults, Windows labels and renderer are
unchanged. Checked entry and UI test defaults select the fresh023 pair; obsolete
local outputs were removed after archiving their metadata. No external code copied.
[Cleanup and validation record](../../docs/PLATFORM_STATUS.md).


## November 7, 2026 — LINUX-025 public Linux onboarding

The reviewed public export overrides `scripts/launcher_linux.py` with a narrow
verified-copy option for the launcher AppImage: original GUI/game receipt, state,
input, namespace and lease checks remain; only the native GUI executable path is
substituted after byte-identical ELF validation. Existing private development
launcher/build defaults are preserved. Root build/Play commands and local-only
AppImage packager/driver make the public source kit easier to build. Game-derived
code/binaries and all runtime state stay out of the image and source releases.
Focused authored and isolated clean-build evidence is in the project Linux record;
full gameplay and broad distribution compatibility are separate validation gates.


## November 8, 2026 — LINUX-028 spaced installation paths

`scripts/setup_linux_graphics.py` enables FDO sysroot rules only for pkg-config
flag requests, so spaced paths are prefixed after fragment parsing. Literal
variable/metadata queries keep their raw path contract; inherited FDO rules are
cleared. Both pkgconf 1.8.1 and 2.5.1 are tested. Real authored pkg-config fixtures
cover spaces and shell metacharacters, variable queries and a tiny C compile; no
external implementation copied. Native build flags/dependency pins are unchanged.
[Build-path repair record](../../docs/PLATFORM_STATUS.md).


## LINUX-029 — frame-generation candidate

Adapted device.c, framegen_pacing_linux.h and temporal_fg_linux.inc to preserve
valid warmup history, overlap retained-image preparation with a bounded absolute
presentation deadline, and account actual intentional idle without changing SDK
motion timing or guest/input/audio progression. First GPU readiness and completion-
bound resource lifetime remain. Added actual-source clock/heuristic regressions
and optional authored GPU timing/pixel oracles. Public build/update helpers preserve
explicit opt-in and feature identity; no external implementation copied. This is
a component-tested candidate, not full-game/physical-presentation qualification.


## November 8, 2026 — LINUX-033 title-menu Exit candidate

`games/xcde/patches.py` adds checked DE2.0.0 title-controller hooks for spare-row
insertion, native authored text and cancel-default confirmation. Original actions
and native cancellation bookkeeping remain guest-owned; confirmed Exit requests
the existing AM close path. Native callback copies retain logical ownership.
`scripts/build_linux.py` registers the authored `runtime/hle/title_exit.c` bridge;
`runtime/services/am.h` documents its existing non-UI-thread-safe request API.
New authored row model/header and synthetic bridge/model fixtures cover preserved
row order/status/capacity/alignment, CPU state, dialog text boundaries, direct and
cloned callbacks, Cancel/confirmation and no story-switch dispatch. Existing AM
fixture additionally requests close from a separate thread while the guest waits.
No game layout/font/texture/localized text, lifted code or downloaded save belongs
in these changes. Candidate manual acceptance remains pending; no release claim.


## November8,2026 — LINUX-033 revision2

The caption adapter uses a checked native post-build hook and logical message
ownership to change only the positive Exit caption. System extends its six-row
native controller in separate guest storage, constructs the resource's seventh
widget and preserves Title Screen availability/default No and native cancellation
bookkeeping. Missing optional seventh-row resources leave the original six rows.
No inline parent fields, game message tables or assets are replaced.

`runtime/host/applet_lifecycle_ui.h` and `runtime/nvn/vulkan/device.c` now stop/join
guest producers after unchanged AM readiness, drain rendering, then directly
perform existing GPU-idle/cache termination. This prevents the observed live-NGX
render worker from overlapping libc vendor teardown on requested host close.
Generic guest ExitProcess/emergency paths remain separate. Native fixtures cover
live guests after UnlockExit in both scheduling modes and the old exit-order
negative control; the normal AM runner includes these cases. Caption and System
fixtures check ownership, six-row byte preservation, restrictions, callbacks,
CPU state, construction/reuse and optional-resource fallbacks. Integrated visual/
Vulkan/NGX shutdown acceptance remains manual; this is an unreleased candidate.


## November8local/9UTC,2026 — LINUX-033 revision3

The native message endpoint backlink stores the manager endpoint object's
address, not its vtable value. Correct the caption ownership comparison and its
authored fixture to preserve that distinction. Keep all other ownership, UI,
choice-count and negative-default checks; report a bounded mismatch mask when
they fail. The corrected fixture reproduces the r2 pre-confirmation abort, then
checks valid address linkage, corrupt ownership/defaults, packet immutability
and complete CPU restoration. Actual confirmation and GPU shutdown remain manual.

The AM fixture additionally uses an authored pthread render-completion queue:
a guest blocked outside kernel waits reaches its next safe point only after the
worker completes during UI stop/join. Both scheduling modes verify guest join,
then worker drain/join, then process finish. This does not exercise exec.c/Vulkan.


## November9,2026 — LINUX-035 development candidate

`games/xcde/patches.py` and authored `runtime/hle/expanded_saves.c/.h` extend the
native logical save records to99manual slots plus the existing autosave for
each story. Existing file IDs0..2 and00a remain; extra manual IDs3..98 use the
original native formatter and journaled save mount. Four physical cards, native
sort/scrolling/No data, native file jobs and visible thumbnail uploads remain.
Metadata grows in the former thumbnail arena; CPU images move to appended
allocation storage. All affected bases, extents, sort end and bounds are checked
against the selected DE2.0.0 input. Empty entries create no save or picture files.

The native remembered-slot field holds four bits. The adapter preserves the
serialized format and neighboring flags, uses nativezero for extended IDs, and
tracks actual UI selection separately perstory. Native scoped-owner validation,
CPU/FP preservation, destructor/reset cleanup and failure controls accompany it.

`runtime/hle/expanded_save_scan.c/.h` adds compact serial extra-ID stages around
the original title Continue and availability/clear-save checks. Existing native
readers/validators/field-aware payload copies remain; no four-bit mask growth or
100fullpayload allocation. Continue retains a winning constructed payload and
its actual logical ID. Per-owner generations and pending-task drain prevent
reset/reuse from retargeting IO. Serial checks may increase title/Continue wait.

The Linux build includes both adapters. Authored native/model/scanner fixtures
and real host-filesystem synthetic tests cover indexes/ownership/POD layouts,
selection/story separation, register/FP restoration, originalslot/autosave/system
preservation, nooverwrite, lazy empty lookups, commit failures/retry and synthetic
recovery. No production FS/journal, save format, renderer or Windows change.
This remains an unreleased development candidate pending manual testing.


## November9,2026 — LINUX-036 bounded initial save metadata scan

The checked native UI call in `games/xcde/patches.py` runs its original function
first, then calls the authored `expanded_saves.c/.h` initial-read pump. Its own
extra work is limited to seven additional native metadata FSM calls and a soft
500microsecond budget checked between calls. Existing native file readers,
validation, sorting and save transactions remain. A pending read, unsettled
callback handle, unchanged progress or budget limit yields normally. Writes,
other operations, populated menu models and changed owner generations prevent
extra work. Known thumbnail-read phases pause this metadata-only pump.

The helper preserves the complete post-original-call CPU/FP state, reserves each
initial owner against reentry, keeps no mutex across guest calls, and logs one
integer summary per scan. The native visible-card update itself runs once, with
four physical cards and all100 metadata identities retained. Continue/title scan
adapters and the filesystem are unchanged. Authored fixture coverage includes
call/time limits, callback busy-clear/handle-live windows, pending writes,
thumbnail pause/resume, owner generations/reset/reentry and CPU preservation.
Actual menu-opening latency and real asynchronous save/load remain manual tests.

## November9,2026 — LINUX-039 dedicated Quick Step development candidate

`runtime/settings.h`, `host/settings_ini.c` and `tools/launcher/launcher.cpp`
add a strict default-off preference and a built-in Mods checkbox. The original
launcher translations, ordinary mods and settings remain. Authored native and
actual-launcher configuration fixtures check default/reset, invalid/duplicate
keys, canonical save/reload and existing settings preservation.

New authored `runtime/hle/quickstep_slot`, `quickstep_ui` and `quickstep_save`
adapters are connected through checked DE2.0.0 hooks in `games/xcde/patches.py`.
The equipment presentation uses the existing Dear ImGui/Vulkan renderer, with
owned snapshots and guest-thread commands; native equipment socket counts stay
unchanged. Narrow `runtime/hle/input.c` and `host/stubs_gfx.c` changes quarantine
consumed controls until release. The bonus slot uses an actual native gem and
native effect decoding/aggregation, with bounded independent scratch storage.

`runtime/services/fs.c` pairs optional authored reference metadata with the native
save transaction. Native save payloads are unchanged. Focused tests use authored
synthetic inventory, UI objects and filesystem data; private native ABI probes
remain outside distributable source. No game code, data, fonts or asset bytes are
copied into the adapters or fixtures. This is a local development candidate with
manual gameplay and save/reload validation pending, not a released feature.

All19 new hook sites require their exact original instruction words. Temporary
stat calculations receive no bonus injection; a deferred, generation-checked
repair at the native function's final epilogue restores active character effects
after previews complete. Native actor recalculation uses the active record path.
Save metadata is staged in memory before native writes, verified against the
actual file at Commit, then flushed within the existing rollback journal. Failed
snapshot copies refuse mutation; partial writes or metadata failures retain the
journal. Existing journal cleanup and power-loss durability limits remain.
Per-boot reset now drops the host journal registry while preserving disk rollback,
so a same-root remount recovers payload and metadata together. Failed recovery
poisons save I/O until remount succeeds; it cannot silently discard the rollback.
An authored failing reset/remount reproducer and recovery-error controls cover
this correction. These tests do not qualify arbitrary power-loss recovery.

## November 9, 2026 — LINUX-040 native Quick Step UI

Replace the rejected LINUX-039 ImGui tile and popup with authored native control
and picker adapters (`runtime/hle/quickstep_native` and `quickstep_picker`). The
control obtains a separate instance from the game's already-loaded layout factory,
keeps only the genuine gem subtree and uses native icon binding/focus/animations.
The original twenty equipment/gem/fashion indices and ordinary socket data stay
unchanged. The filtered native list uses actual owned Quick Step instances with
original icons, descriptions, sorting, favourites and No data. No game resource
bytes or generated native bodies are distributed. The r3 revision below adds
empty-slot tinting through the existing native colour multiplier.

`games/xcde/patches.py` uses instruction-word-checked native input, list callback,
count, character/pane lifecycle and destructor hooks. Mid-frame consumed input
uses the existing native handled epilogue; picker close preserves the tail-call
LR. Bonus callbacks bypass ordinary detach/staged socket writes. Native slot
resources are released before their sequence's loader. `scripts/build_linux.py`
links the new modules. `input.c`, `host/stubs_gfx.c` and `ui/menu_vk.cpp` return to
the stable 0.1.9 behavior; no special overlay input capture remains.

Correct the backend ownership contract: item byte +11 and BDEE0 represent
favourites, not equipment attachment. Inspect actual native gear references,
including unworn gear, and hook the accepted ordinary socket store at17B81C after
capacity/intrinsic checks. Assignment and removal validate both instance identity
and adoption epoch; native helpers never execute under the ownership mutex.
Authored C fixtures plus private selected-input ARM probes cover these contracts;
component passes do not establish integrated visual, gameplay or save acceptance.

### LINUX-040 r2 — specialized native loader guard

The first native development candidate failed manual testing: its extra icon never
appeared because an exact class guard accepted only the base layout loader. The
game uses the specialized equipment loader. `runtime/hle/quickstep_native.c` now
accepts only the independently verified base or specialized class paired with its
expected virtual factory method. The specialized native factory and layout
selector remain in use; alias, ancestry, refcount and ordinary-socket guards stay
intact. Bounded stage/reason diagnostics replace the opaque creation failure.

The authored fixture exercises the specialized class, selector and full-size
273-node/361-component synthetic layout, plus wrong-class/method, alias, focus
and lifetime controls. An ignored source copy restoring only the prior base-only
guard reproduces the pre-allocation failure. Actual selected-input ARM probes
remain private, including in-memory metadata checks of the compressed native
layout. This fixes the proven initialization rejection; rendered placement and
complete native interaction still require manual acceptance. No game asset bytes,
generated code or saves are included in source.

### LINUX-040 r3 — assignment, crafted gems and native presentation

Fix the bonus picker's Confirm path before ordinary equipment socket checks;
retain the original router epilogue, cancellation, sorting and favourites. Remove
the invalid requirement for a nonzero static gem definition while retaining real
instance, serial, rank, effect, value, attachment and save-identity validation.
Assignment/clearing refreshes the native character summary through its baseline
path. The pure reference/epoch query lets yielding presenters revalidate without
calling native code under the backend ownership mutex.

The slot adapter keeps a genuine native cream backing, full-size icon and socket
badge, compensating the native parent transform and anchoring them at the actual
right table edge. A time-based 120 ms reveal uses native transforms. Empty icons
receive the native green colour multiplier, which also affects their dark fill;
filled icons retain native colours. Source layouts and original controls remain
unchanged; no texture, font or generated game code is distributed.

New `runtime/hle/quickstep_stats` and `quickstep_stats_ui` adapters present the
bonus through native localized skill names and formatting. They merge an existing
Quick Step effect at its original cap or render a separate record. A full set of
eight ordinary effects receives a separately instanced native ninth control;
the original fixed eight-record buffers stay untouched. Original transforms and
inline row counts are restored before native destruction. Checked renderer and
lifecycle hooks, authored ownership/alias/reentry fixtures and private native ABI
probes cover these boundaries. Actual visuals, movement, save/reload and both
stories remain subject to manual testing of this revision.

### LINUX-040 r4 — native allocation, availability and mini-table revision

The r3 manual test found a native null allocation while the summary adapter
created another complete equipment scene. `quickstep_stats_ui` now constructs a
base loader for the exact already-linked stats resource, advances its real
dependency/font readiness once per UI tick, validates cache/raw identity, and
attaches only that container through the native component API. Native parent
transforms, clipping and lifetime are inherited. Existing eight-record summaries
and nineteen original row controls stay intact; the extra row and loader have
checked teardown, pending-work and ordinary-preview isolation.
If a parent retires during a yielding constructor and ownership can no longer be
proved, its ambiguous resource capsule is retained until guest reset. Its loader
and scratch buffer are never recycled into a replacement owner; normal cleanup
still runs once after active helpers return.

New authored `quickstep_ui_memory` samples the active native variable-size arena
under its native recursive mutex, releases that mutex before layout/texture
construction, and revalidates ownership. It checks policy headroom and largest
free block, preserves CPU/FP state, and bounds diagnostics. This is not an atomic
reservation or a proved bound on arbitrary font/GPU/concurrent allocation costs;
no native arena is resized. Resource refusals retain the original UI and are
reported, rather than supplying fake successful objects.

The picker adds exact owned-row styling and both native Plus-menu item paths,
without overriding the global ordinary-socket validator. A typed completed-popup
lease preserves bonus ownership through Cancel/Remove, stale callbacks and
teardown; ordinary menus keep their own behaviour. Authored fixtures cover both
idle and active picker panes across playable main/extra-story characters and
absent, socketless, unique, empty-socket and occupied-socket equipment.

The native slot revision retains original icon/badge proportions and a separate
socket underlay. A small original nine-part window supplies the mini-table and
focus frame, with native corner-preserving scaling; only the empty socket
underlay receives the green multiplier. Its runtime asset is read-only and held
in memory until guest reset. An exact privately owned-row batch filter omits
its baked wide background through the existing native cleanup path; original
rows and separately drawn children are unchanged. No game asset bytes are added
to source or release packages. Visual alignment, real allocation headroom and
integrated gameplay/save behaviour still require manual acceptance.

### LINUX-040 r5 — equip completion and bounded native focus

The bonus picker now follows the original native equip feedback and presentation
close sequence after a verified bonus assignment. It keeps its ownership guard
through the close callback and restores the original pane and row selection.
Ordinary equipment commit and socket mutation remain outside this path; rejected
or stale selections stay silent and do not report success. The private small
card uses its own bounded native focus frame rather than a normal-width gem-row
selection animation. Authored fixtures and native probes cover these transitions;
actual sound, visual polish and gameplay acceptance are manual checks.

A clean native common window supplies symmetric card corners and a persistent
dark rim, with the same two small nodes and no redistributed texture bytes.
Private background ownership remains valid across a transient character change,
while native input and effects still require the current character lease.
The effects-row loader validates its own exact native cache-handle type rather
than borrowing the unrelated ownership-reference type from a nested wrapper;
exact original resource identity and source topology checks remain required.


### LINUX-041/042 — trade entries and Linux runtime closure

The Linux generator accepts optional requirement-tagged FunctionEntries metadata
in the existing patch file. The selected main build and all dispatch/entry words
are verified before partitioning; five native trade cases now have original
bodies and dispatch entries. No instruction replacement or CPU fallback is used.
Authored partition/Unicorn/native tests and selected-input audits cover this fix.

The local graphics dependency lock now describes the complete non-platform
DT_NEEDED/version graph, immutable private library hashes and explicit native
host interfaces. Setup extracts only verified archives without maintainer scripts
or host installation. The builder and runners check declared ELF dependencies,
ABI versions and trusted loader resolution without executing game constructors.
GNU C++ discovery supports native distribution paths. Update validation occurs
before activation and preserves the prior selection/profile on failure. Source
and launcher packages still exclude all local runtime libraries, game/generated
code, caches, keys and saves. Arch userspace load/media tests are distinct from
actual GPU/gameplay qualification; the Linux build guide records the boundary.

### LINUX-054 — current-only update storage

Authored `tools/update_retention.py` and `scripts/install_lease.py` add bounded,
journaled cleanup and installation leases around update activation and runtime
admission. The updater keeps the checked current launcher and its directly bound
game payload, removes recognized obsolete updater-owned workspaces/downloads,
and retries blocked cleanup on later startup. The original profile, native saves,
hidden Quick Step metadata, mods, useful caches and shared game input are outside
cleanup. Local rollback selection is retired; the legacy compatibility entrypoint
reports that downgrades use manually downloaded GitHub release kits.

Compatible launcher-only updates can reuse an independently owned game payload.
Game changes require a fresh validated payload before activation. A legacy updater
can place its first updated game in the version workspace, requiring one further
full rebuild when a later update first detaches that payload. Temporary peak
storage includes the existing and replacement builds. Original bootstrap source
and tool support remain; build paths are never relocated to reclaim space.

Authored fixtures cover ownership, leases, interrupted cleanup and legacy readers.
An isolated installed-0.1.11 upgrade rehearsal completed native build, activation,
first-start cleanup and legacy bootstrap checks with all protected profile file
hashes unchanged. Long-history first-start maintenance and post-checks took about
75 seconds in that rehearsal; this does not establish universal startup time,
actual GUI/gameplay or other-distribution compatibility.

### LINUX-055 — native held camera controls and Linux party switching

The Linux SDL route forwards a physical L2 hold immediately through its configured
native bindings, including neutral holds that drive the control-help display.
Release ends that hold without a synthetic second tap. Only selected-controller
shoulder press edges request the optional L2 + L1/R1 party switch. Shoulders are
masked before queued edges arrive and stay consumed through their own release.
Focus/menu resets, disconnects, option changes and rebinding cancel stale gestures.
A small authored reducer preserves disabled/scripted passthrough; SDL state/reset
publication is serialized. Optional D-pad walking yields to held logical ZL.

The inherited party discovery/cache/thread path was Windows-only and returned an
empty result on Linux. A Linux pthread worker now scans only the declared guest
heap, skips unresident pages and uses bounded self-process reads for protected or
changing mappings. It publishes a synchronized cache; background work never calls
or writes guest game logic. A requested switch revalidates native objects, control
locks, party/list/group/HUD ranges and writable mappings before the existing native
leader-change sequence. Full Cpu and virtual/host FP state are preserved around
its guest calls. Reset/exit stop and join the worker; queued synthetic arts input
and direct-camera state are cleared at guest reset.

Authored fixtures exercise the actual Linux discovery and switching code, with
only native game-function calls represented by test boundaries. Coverage includes
rotation/reserves, control locks, downed members, HUD/follower updates, malformed
or protected memory, CPU/FP preservation, worker restart and pending-control reset.
Real SDL virtual-controller fixtures separately test the input route. The
maintainer manually accepted the revised L2 camera, native help and party-switching
controls. This does not qualify every field/battle state, Future Connected,
controller, performance or hardware configuration. No game asset or generated
game code is added to source.

### LINUX-056 — DLSS selection default

The Linux launcher selects DLAA / Native (100%) when changing from another
upscaler to DLSS. Missing or invalid DLSS quality also defaults to native after
the complete configuration is parsed; explicit saved quality choices remain.
Actual headless launcher/configuration fixtures cover selection and serialization.

Authored jittered-scene NGX and actual temporal-preparation GPU fixtures exercise
coherent synthetic inputs. They do not establish the cause or a fix for reported
in-game instability at 67%. Native (100%) remains the current workaround; the
released change adjusts selection/configuration defaults, leaving rendering,
history mathematics and shader inputs unchanged. Broader investigation remains
open, with temporary development diagnostics excluded from the release.


### LINUX-070 / 0.1.14 — RADV guest heap backing

The Linux runtime negotiates driver-owned, fixed-address guest heap backing only
for Mesa RADV. NVIDIA and other drivers retain the checked host-pointer import.
The first nonzero SetHeapSize waits for device readiness before publishing any
heap memory, then allocates full capacity once. Placed mapping is preferred;
checked dma-buf export is the alternate path. CPU-cached coherent system memory,
reservation restoration, stable growth and exclusive GPU-idle reset ownership
are required. A failed safe probe retains the original import; failed reservation
restoration stops rather than running with invalid memory.

Design references: Peiikai's MIT LASRecomp PRs71/255 and the MIT Savage Wind
runtime's RADV heap approach. Their AMD hardware results motivated this change;
Monado's AMD performance remains unverified. Authored failure fixtures and actual
production lifecycle/device-policy fixtures cover the integration. No GPL runtime
implementation was copied. See the validation limits in docs/AMD_RADV.md at the
repository root. No generator, shader mathematics or save formats are changed.


### LINUX-072 / 0.1.15 — optional Linux cheats

Authored adapters add independent runtime-configured battle damage dealt/received,
EXP/AP/SP/gold gained and ordinary fall immunity. Every option defaults off;
fixed integer percentages0..2000 represent0x..20x in0.01x steps. Exact disabled/1x
routes retain original instructions/calls. Checked word guards bind both battle
dispatch paths, eleven new-award calls, positive gold add and the native no-fall
return path/context. Existing bonus-EXP transfers, gold spending/setters and
healing dispatch stay native. Native reward eligibility, level-ups, skill bonuses,
notifications and caps remain; no native save format changes.

The launcher gains a Cheats tab with per-option toggles and bounded sliders;
Xenoblade3 party switching moves to Mods beneath Quickstep, retaining its key and
behavior. Settings save/load preserves slider values and enable states. The actual
Linux build recipe includes both authored helpers. Configuration, arithmetic,
ABI/scratch ownership, guarded generated-C emission and native ImGui fixtures
exercise the change; selected-input instruction probes remain private, separate
from authored distributable fixtures. No copied game function/asset data or
external cheat implementation is included. The maintainer manually accepted
the combined Linux build; DoT/status and comprehensive DE/FC coverage are not established.
See repository-root docs/CHEATS.md. Arts-recharge and Windows parity are deferred.

### LINUX-075 — early RADV nodcc compatibility

An authored Linux helper prepares the exact RADV `nodcc` driver flag in the
single-threaded graphics startup path, including precompilation. It retains
other flags, has an explicit diagnostic opt-out and reports the effective flag
only for the selected RADV driver. No shared environment mutation occurs after
workers start; no lean-format, heap, shader mathematics, synchronization,
NVIDIA feature-chain or save-format change is made. Native fixtures cover flag
composition, failure handling and startup ordering. The driver-specific flag
is ignored by non-RADV drivers.

Credit patrickksmdev for isolating the RX 7600/NAVI33 workaround: `nodcc` alone
removed the reported Colony 9 dots; lean formats off alone did not. Reported
performance was unchanged by feel, not a measured cross-GPU benchmark. The
preceding candidate passed the maintainer's qualitative NVIDIA gameplay check;
affected-AMD artifact validation remains pending.

### LINUX-077 — Linux handheld controller integration

Preserve a narrowly validated set of Steam/SDL controller settings through the
launcher and child game. This includes SDL's Steam-virtual-gamepad acceptance
flag, associated mappings and ignore lists, and optional read-only controller
metadata in the existing private runtime namespace. Loader and state filters
remain separate from this input context.

The native state guard admits only existing, strictly named hidraw character
devices through checked non-following handles. Host permissions and filesystem
confinement remain enforced. New/recreated HID nodes are not automatically
admitted after restriction; affected reconnect cases require restarting the
launcher. This is not a universal hotplug or suspend/resume qualification.
The read-only metadata bind also follows its original inode; atomic replacement
by Steam is refreshed on the next launcher start, while in-place updates remain
visible.

The authored input adapter checks open failures and tries remaining eligible
controllers, recovers selection after removal, and records bounded discovery
diagnostics. The GUI retains upstream ImGui SDL ownership rather than leaking
extra opens. Authored SDL virtual-device, environment and isolated device-policy
fixtures exercise these paths without game data. No third-party controller
implementation, game-derived mapping, renderer policy or native save format is
changed. Actual Steam Deck/ROG Ally X testing remains pending; see repository-root
docs/HANDHELD_CONTROLLERS.md.


## LINUX-089 — controller lifecycle and XCDE native aspect adapters

Authored input.c recovery and the Linux copy of upstream MIT ImGui's
imgui_impl_sdl3.cpp gain bounded missed-event/disconnected-handle recovery,
healthy automatic-selection preservation and neutral input release. SDL handle
ownership remains on its event thread. No Windows-reference files changed.

Controller metadata now uses a validated, marker-owned private snapshot directory
with atomic live refresh through the outer Python supervisor; safe external paths
remain direct. The directory is read-only at both namespace aliases. The Landlock
write policy, updater cancellation, save/profile confinement and session leases
are unchanged. Existing startup hidraw-inode restrictions remain; this does not
claim universal physical hotplug/suspend support. Synthetic recovery/namespace
checks do not establish actual Steam Deck/ROG Ally compatibility.

New authored xcde_aspect.c plus build-ID/instruction/context-checked scalar
adapters update XCDE logical cameras/culling, renderer projection and HUD markers.
The existing output-scale/presented-UI fitting foundation is retained; native
aspect is opt-in and original mode is identity. UI canvas math is component-tested.
No upstream widescreen implementation or third-party mod was copied; no game code
or generated data is included. Real gameplay/effect/resize coverage is manual.

LINUX-090 extends the authored settings, launcher and output policy with explicit
16:10/21:9/32:9 selections independent of the drawable. Chosen cameras and render
targets use the same shape from startup; existing Vulkan upscaler/present and FG
rectangles fit the chosen content inside the screen with bars. Original/native
configuration values and defaults remain compatible. No upstream camera or
presentation code was imported for these choices; real gameplay remains manual.
