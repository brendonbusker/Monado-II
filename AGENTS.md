# Monado II Windows parity development

This branch prepares the Windows port of the accepted Linux features through
Linux **0.1.16**. Read [the Windows handoff](docs/WINDOWS_PORT_HANDOFF.md) first,
then root `CONTRIBUTING.md`, `LICENSE`, `NOTICE.md`, `CREDITS.md`, the relevant
per-port contribution/source contracts and [Windows build guide](docs/BUILD_WINDOWS.md).
The handoff is a plan and reference map, not a claim that Windows was updated.

The user has authorized implementation, local builds, focused tests and debugging
on their actual Windows installation. Plan each coherent change, then implement
and validate it without repeatedly asking to continue. On Linux, stop after this
preparation; do not start Windows implementation or an unrelated Linux feature.

Use this latest repository as the reference and `Monado_Windows/` as the working
target. Reuse accepted portable Linux game logic, native UI and fixtures in
coherent bundles. Retain Windows platform/fibers and Streamline/FidelityFX providers;
do not wholesale convert the Linux directory or introduce a renderer/shared-core
rewrite. Preserve Linux runtime/build behavior and the separation of both ports.

Reconcile checkout/branch/local changes, host tools, dependencies and running
processes before work. Use `codex/` branches and small traceable source commits.
Do not blindly overwrite local changes, kill processes by image name, run broad
system upgrades or accept vendor agreements. Audit inherited setup/build scripts
before executing them. Respect actual OS/tool approvals; ordinary builds stay
unelevated. Use checked project-local tools/dependencies where practical.

Only the user's own already-extracted DE 2.0.0 input belongs in root `game_files/`.
Keep it read-only; no game/key/firmware downloads, package extraction or acquisition
instructions. Keep Windows generated output, builds, state, logs and saves under
its own port paths. Preserve human saves/configuration and known-good builds.
New dev profiles use independent private copies of the approved development seed
if available; never reseed an existing/USED profile or download/publish saves.
Never test save recovery on originals. Native `.sav` format and story separation
must remain compatible; keep hidden Quick Step metadata with its save folder.

Game and visible-launcher testing is manual unless the user specifically requests
a session. Do not automatically start the game, press Play, replay controls or
close a human session. Compilation, authored synthetic fixtures, native component
and non-game loader checks are authorized. Passing source CI or a Linux fixture
on Windows does not establish a native Windows build or gameplay result.

Maintain one private project-root `PROJECT_MEMORY.md`, with detailed private
evidence and exact resume steps. Do not publish private memories or competing
per-port state files. Preserve failed hypotheses, exact commands/tools/flags,
source/build hashes, actual test results/skips, remaining coverage and live jobs.
Private input/state/memory makes an ordinary dev checkout unsuitable for strict
publication checks; create a separate reviewed clean source export, never delete
human files to make a guard pass.

No game/generated code, executable, translated shader/cache, key, save, SDK binary,
unreviewed artwork or private log belongs in commits or source releases. Refresh
the exact manifest only after provenance review; preserve all attribution and
source/package guards. The reviewed artwork policy is path-specific: Windows-only
kits must include their own reviewed resources under explicitly reviewed paths.

Keep Quick Step and every cheat off by default; frame generation experimental
and off. Port current-only update retention, without local rollback history,
while keeping the working build on preparation failure and protecting saves.
Linux RADV/heap, Landlock, hidraw, namespace and distro-package behavior are not
Windows features. DLSS 67% shaking and the reported shadows/sparkles/blue pipe
are unresolved; do not advertise inherited bugs as fixes.

Windows release identity stays **original implementation** until Windows actually
receives implemented changes. A preparation merge/source CI does not justify a
new Windows version or a release. Later implementation may be committed with
precise native-build/component/gameplay labels; arrange the maintainer's manual
test before claiming parity. This task does not authorize a new release now.
