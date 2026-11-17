# Experimental Linux frame generation

Frame generation inserts interpolated pictures between rendered game frames.
It can improve motion smoothness, but it does not increase the game's simulation
rate or reduce input latency by itself. It remains **off by default**. This dev
build needs manual gameplay testing; visual artifacts and uneven pacing remain
possible.

## Choose one method

In the launcher's **Graphics** tab, choose a **Frame generation** method:

| Method | Requirements | Counter behavior |
|---|---|---|
| Off | Any supported configuration | Rendered game FPS |
| FSR 3 interpolation (2×, experimental) | A normal native build with working DLSS/DLAA, FSR3 or prepared FSR4 temporal input | Game, Output and classified Generated FPS (submitted) |
| NVIDIA Smooth Motion (2×, experimental) | Installed Linux NVIDIA Smooth Motion driver components and a supported RTX 40-series or newer GPU | Game FPS and measured driver Output when available; generated-only count unavailable |

Integrated FSR generation accepts qualified temporal inputs from DLSS/DLAA,
native FSR3 and prepared FSR4 Lite. Spatial FSR1 and bilinear scaling do not
provide these inputs. This is separate from DLSS Frame Generation. NVIDIA Smooth Motion is a separate driver method;
component detection alone does not prove that a particular GPU can generate
frames. The driver makes that decision. No driver installation or update is
performed by the launcher.

Change NVIDIA Smooth Motion in the launcher and restart the game. It cannot be
enabled live with F1. The launcher enables its driver flag only for the game,
not for the launcher or shader preparation. Do not stack either method with an
external frame-generation tool or another driver override. Selecting a launcher
method disables the other integrated choice.

## FSR refresh matching

Enable **Match display refresh** to use half the current display refresh rate as
the real-frame ceiling, while respecting your chosen game FPS limit. The saved
FPS preference is retained. For example:

| Display | Game FPS setting | Requested real / total output ceilings |
|---|---|---|
| 180 Hz | 120 FPS | 90 / 180 FPS |
| 180 Hz | 60 FPS | 60 / 120 FPS |
| 144 Hz | Unlimited | 72 / 144 FPS |

The cap takes effect once FSR has usable history and successfully generates a
pair. When the provider is unavailable or disabled, the ordinary game FPS limit
applies. **VSync** selects FIFO presentation for FSR generation, including at
game FPS settings above 60. A bounded presentation worker waits for completed GPU work and paces the output
while the next real frame can be prepared. It uses a separate queue where available
and a synchronized fallback elsewhere. Swapchain capacity or a busy driver can
still limit overlap. The output timeline avoids deliberate catch-up bursts after
a slow frame; actual performance still determines delivered output.

This provider generates one midpoint image per real frame. It does not generate
two distinct intermediate images for 60-to-180 FPS, or arbitrary phases for
120-to-180 FPS. True multi-frame generation is not included: an authored
variable-phase prototype did not pass the moving-edge, disocclusion and
translucent-HUD quality gate. The cutscene-only FSR option remains 30-to-60 FPS
and does not use display matching.

## Reading the FPS counter

Choose **Show FPS on screen** under **Graphics → Quality**, in the launcher or
in-game **F1** menu. Changes in F1 apply immediately; **Save** remembers the mode.
It remains off by default and is separate from the window title counter.

- **Off** hides the overlay.
- **Number only** shows rendered Game FPS as a number with no label or panel.
- **Compact HUD** emphasizes Game FPS with smaller frame-generation readings.
- **Detailed panel** shows Game, Output and Generated readings in separate rows.

Existing enabled counters migrate to Compact HUD. The appearance choices use the
same measurement logic and preserve unavailable readings. The two panel styles
use bundled, licensed fonts; no extra font installation or game UI assets are
required.

- **Game** counts successfully acquired rendered game frames, excluding
  generated images and repeated presentations.
- **Output (submitted)** counts successful presentation requests, including FSR
  interpolation. It is not a measurement of distinct pictures physically shown
  by the display; the compositor, driver or monitor can still discard or repeat
  images.
- **Generated** counts classified successful interpolated submissions for the
  integrated FSR method, excluding native and repeated images. It shares the
  Output sampling window and is not an estimate obtained by subtraction.
- **Output (driver submitted)** is measured by an authored Vulkan observer below
  NVIDIA's frame-generation layer. It counts successful downstream presentation
  requests, including any driver-added output. Measurement is requested when
  starting Smooth Motion and continues while the on-screen counter is hidden.
- **Generated unavailable** means those downstream calls do not provide a
  qualified native/generated identity. Subtracting Game FPS from Output would
  miscount dropped, delayed or skipped native frames, so no generated-only number
  is invented.
- **Output external (unavailable)** means downstream measurement is unsupported
  or failed. A supported counter needs a short sampling warmup. Method selection
  is a request to the driver; startup diagnostics
  can reveal a driver fallback even when the layer loaded successfully.

The host counter is drawn after FSR interpolation and kept out of its retained
history. Counter values alone do not establish smooth motion or input latency.

## Suggested dev-build comparison

Start with **DLSS/DLAA at Native (100%)**, the same resolution and game FPS cap,
and frame generation off. Then try FSR 2×, VSync and display matching with the
on-screen counter enabled. At 180 Hz and a 120 FPS game setting, look for about
90 Game / 180 Output when the scene can sustain it. Compare camera movement,
character motion, menus, HUD, cutscenes and resize/Alt-Tab recovery.

Restart with NVIDIA Smooth Motion as a separate comparison if available. The
optional measured driver-output counter still reports submissions, not physical
scanout. A 180 Hz display cannot show more than 180 distinct refreshes per second,
even if the driver submits more. Scaled DLSS shaking previously
reported at 67% is a separate unresolved issue; use Native first so it does not
confound this frame-generation test. Leave generation off if either method is
worse for your configuration.

## Per-run diagnostics

Each real launch receives a run ID and a small requested-settings record under
`logs/game-runs`. Up to 16 unmodified, owned records are retained. Native log rows
with the same run ID report parsed/effective settings, display refresh,
presentation mode, the policy target and actual applied limiter values. Changes
are logged within a fixed budget. Unknown/private keys and keybindings are omitted.
These records help distinguish the last saved settings from what an earlier run
actually used; shader preparation and dry runs do not create gameplay records.

While frame generation is selected, a short measured FPS sample is recorded about
every two seconds, including when the on-screen counter is hidden. Samples report
rendered Game FPS, accepted Output FPS and measurement readiness. NVIDIA samples
also retain the observer's accepted/failed counters and sampling window; they do
not estimate generated-only FPS. FSR input readiness distinguishes interpolation
from ordinary output during unsupported scenes. An unavailable or warming counter
is labelled explicitly. These samples use the same measurements as the display.

The native CUDA compatibility exception is limited to the game's own thread
metadata, and only requested for Smooth Motion. It allows NVIDIA to name its own
threads; other process paths, game input and unrelated files retain their write
restrictions. The launcher stays under its existing guard and asks its verified
host supervisor to start the selected game. No system packages, kernel modules
or driver settings are installed or changed.

The application's existing VSync option selects FIFO for integrated FSR at all
FPS caps. With Smooth Motion at game settings above 60 or Unlimited, the
application retains MAILBOX and the driver handles downstream presentation. A
checked VSync box therefore does not establish a strict refresh-rate output cap
for that external method. Use the run's actual presentation diagnostics.

## Cutscenes and prerecorded videos

Eligible real-time 3D cutscenes can use the selected generation method. FSR's
cutscene-only mode targets 30 rendered / 60 output FPS. Prerecorded videos have
their own source frame rate and currently bypass the game's 3D FSR interpolation
path. A high rendering or presentation counter during a video does not establish
an equally high number of distinct movie images. Dedicated video interpolation
has not been implemented. NVIDIA's whole-process driver method has no integrated
cutscene-only switch; its effect on prerecorded movie images remains unverified.
