# Native display aspect ratios (Linux 0.1.19, experimental)

In Graphics, **Aspect ratio** offers these choices on every monitor:

| Choice | Behavior |
| --- | --- |
| Original (16:9) | Default, including existing configurations; keeps the original framing. |
| Match the display (experimental) | Follows the game window or fullscreen display proportions. |
| 16:10 (experimental) | Uses a fixed 16:10 view, including on a different monitor shape. |
| 21:9 (experimental) | Uses a fixed, exact 21:9 view. |
| 32:9 (experimental) | Uses a fixed 32:9 view. |

Fixed choices fit inside the window or fullscreen display, with centered black
bars when their proportions differ. They never stretch or crop the selected
view. For example, on a Steam Deck screen, Original keeps 16:9 bars and 16:10
fills the screen. You can select a fixed ratio independently of Window size.
Exact 21:9 is slightly narrower than a 3440×1440 monitor: select Match the display
to fill that monitor, or 21:9 to keep the exact selected ratio with small side bars.
Save settings and relaunch the game to apply a changed ratio.
Window presets include 1280×800, 1920×1200, 2560×1600, 2560×1080,
3440×1440, 5120×1440 and 7680×2160. Fullscreen follows the actual display.

The opt-in adapts game perspective cameras and CPU visibility frustums. Wider
windows add horizontal view; 16:10 adds vertical view while retaining the
original 16:9 scene. Menus, text and HUD retain a uniformly scaled, centered
16:9 canvas. World-space HUD markers are mapped into that same canvas. This
is not image stretching. Unsupported shapes outside 16:10 through 32:9 retain
original framing; tiny differences within 0.5% of 16:9 also retain that framing.

Fixed-frame video and artwork cannot reveal additional picture. They may remain
16:9, with bars or the existing scene behind them. Real-time cutscene framing,
special effects, offscreen UI composites, live resizing and temporal upscaling
still need manual coverage. The preview must not be described as fully tested
ultrawide support based on projection/component tests alone.

Return to Original if a scene or menu misbehaves. Please include the selected
aspect mode, window dimensions, upscaler, location and a short description when
reporting an issue. Existing save data needs no conversion; aspect is a launcher
preference in `xcde.ini`
(`aspect_ratio = original|native|16:10|21:9|32:9`). Existing `native` preferences
continue to mean Match the display; missing or invalid preferences use Original.
