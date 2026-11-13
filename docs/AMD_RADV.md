# AMD / RADV compatibility

## Colorful glowing dots (0.1.16)

The Linux graphics executable prepares `RADV_DEBUG=nodcc` before platform
workers, shader precompilation, SDL and Vulkan initialization. RADV consumes this
driver-specific option; NVIDIA and other Vulkan drivers retain their existing
rendering policies. This does not disable lean formats or undo the driver-owned
guest heap described below. Existing RADV debug flags are preserved and `nodcc`
is added only when its exact token is absent.

Thanks to **patrickksmdev**, who tested the switches separately on an RX 7600
(RADV NAVI33) at the same Colony 9 location/settings in 0.1.14. `nodcc` alone
removed the colorful dots; `XCDE_LEAN_FORMATS=0` alone did not. The reporter saw
no noticeable FPS drop or additional stuttering. This is qualitative evidence
for that configuration, not proof of the underlying driver/application fault or
every AMD GPU, scene or performance outcome. The maintainer accepted NVIDIA
gameplay on the combined build; affected-AMD validation of this packaged
workaround remains requested.

For diagnostics, `XCDE_RADV_DCC_WORKAROUND=0` prevents the automatic addition;
absence or exactly `1` enables it. Supply the control through the checked
`Monado_Linux/scripts/run_linux.py` runner's explicit `--env` argument alongside
the installation's normal `--executable` and isolated `--state-root` arguments.
Inherited XCDE controls are intentionally filtered by normal launchers. Opting
out does not remove an explicitly supplied `nodcc` from `RADV_DEBUG`. No system
environment, driver, game input, save format or save location is changed.

The startup log reports the effective `nodcc` flag only when the selected Vulkan
driver is RADV. DCC is a lossless bandwidth optimization; disabling it can cost
performance in some workloads. Compare the same scene/settings after shader
warmup when reporting an issue. No general FPS improvement or zero-cost claim
is made.

## Driver-owned guest heap (0.1.14)

This Linux change targets severe AMD/RADV CPU submission overhead.
**AMD gameplay performance still needs testing**, including on the reported
RX 6700 XT. No particular FPS gain is promised.
Headless memory-transfer tests passed on a Ryzen 7900X integrated RADV GPU,
including full 3.25 GiB capacity. This does not validate the reported RX 6700 XT.
The maintainer manually accepted NVIDIA gameplay on the existing import path.
This is qualitative feedback, not a measured FPS comparison or full-game coverage.

The alternative backing is selected only for Mesa RADV, using driver identity
and actual device capabilities. NVIDIA keeps the original checked host-pointer
import, device extension list and feature chain. The first heap request waits for
Vulkan initialization before choosing its backing; normal frame timing and GPU
synchronization remain unchanged.

Driver-owned memory means a coherent CPU-cached system-memory allocation shared
with Vulkan, not moving the CPU's entire heap into discrete VRAM. The runtime maps
it before the game writes any heap data, keeps its address stable on heap growth,
and restores ordinary anonymous memory after GPU-idle teardown. It tries placed
mapping first, then dma-buf mapping; unsupported or refused mappings fall back to
the existing import. An unrecoverable reservation-restoration failure is fatal.

Startup logs distinguish `RADV driver memory (placed map)`, `RADV driver memory
(dma-buf)`, ordinary non-RADV host import, and a safe RADV fallback with its reason.
The diagnostic runtime control `XCDE_VK_HEAP=import` selects the previous RADV
path; `auto` and `driver` try the driver-owned backing on RADV only. Supply it explicitly
through the checked runner's `--env` argument: inherited XCDE variables are
intentionally filtered. It is not a new launcher preference. No driver, kernel,
system permission or package changes are needed to use the fallback.

Validation separates controlled native failure/lifecycle tests, real NVIDIA
memory-import tests, maintainer manual NVIDIA gameplay, and actual AMD testing.
Passing the first two does not prove AMD performance or unchanged game FPS.
For comparisons keep the same scene, graphics settings and warmed caches, and
record the driver version and logged backing mode. Disable external Vulkan
frame-generation/overlay layers for a clean baseline. Keep normal save backups.

References: [LASRecomp PR255](https://github.com/peiikai/LASRecomp/pull/255),
[Savage Wind RADV changes](https://github.com/Revivedx/SavageWindRecomp/commit/bc13314040d805482bb2f9017aa8ad5de7ca2ba9).
