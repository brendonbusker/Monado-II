# Linux handheld performance development work

This development candidate preserves the existing game features and graphics
correctness changes. It is a separate build for comparison with the accepted
development baseline. No specific gameplay FPS improvement is established yet.

- The launcher caps foreground drawing and reduces background drawing while
  continuing game, update and shader-preparation monitoring. Hidden/minimized
  windows stop painting. Controller navigation and hotplug remain serviced.
- The Vulkan execution and texture units explicitly request `-O2`, retaining
  assertions, the x86_64_v2 CPU baseline and strict floating-point/aliasing rules.
  With pinned Zig0.14.1, this produces the same compiler output as the previous
  requested `-O1`; it is explicit build intent, not an additional speedup.
- Known texture writes invalidate the relevant feedback snapshots. Unknown writes,
  guest visibility boundaries and live depth-copy aliases retain conservative
  global invalidation. Equivalent views sharing the exact backend can reuse a
  snapshot. Full subresource copies and required synchronization remain intact.
- On Linux integrated GPUs with at most eight available logical CPUs, optional
  pipeline refinements use one dedicated worker. Required compilation keeps the
  original worker pool and readiness behavior. The refinement worker requests
  lower priority for its own thread only; denied requests are nonfatal. Desktop
  discrete-GPU scheduling is unchanged. This does not cover every handheld CPU.

Developer diagnostics `XCDE_FB_STATS`, `XCDE_SHADER_WORKERS` and
`XCDE_SHADER_BACKGROUND` are direct-executable controls, not launcher preferences
or inherited shell settings. They are unnecessary for normal use. The feedback
byte counter estimates logical image-copy size, not measured physical bus traffic.
Worker overrides are bounded and invalid values retain the default policy.

For meaningful comparison, keep the scene, camera, settings, frame cap and power
profile the same. Test native game frame times with frame generation off first.
Separate shader compilation from warm gameplay; generated output FPS is a separate
measurement. Check frame-time spikes, input/audio and memory as well as averages.
Actual Steam Deck/Ally testing is needed before claiming a handheld improvement.

No game data, translated shader cache, generated game code or saves belong in
source/release packages. Build-local and test-local derived outputs stay private.
