# Linux handheld controller compatibility

Linux 0.1.16 repairs two application-side compatibility gaps:
Steam's controller context was discarded before starting the launcher, and the
native state guard omitted HIDAPI device nodes used by some controllers. It
also improves controller open-failure handling and adds discovery diagnostics.
The changes likely address the reported Steam Deck detection failure. ROG Ally X
compatibility remains uncertain. Actual testing on both handhelds is still
required; the maintainer accepted desktop/NVIDIA gameplay on the combined build.

## Steam Input and handheld middleware

When launching through Steam, use a normal gamepad layout for the Monado II
shortcut. The launcher preserves a validated set of Steam/SDL input settings,
including the option required to accept Steam's virtual gamepad. It retains
the associated physical-device filters and mappings to avoid duplicate input.
Other controller drivers retain SDL's normal selection policy.

On systems using Handheld Daemon, the Ally's controller can appear under an
emulated controller name. Monado uses the gamepad exposed by the host rather
than requiring the name to contain "ASUS" or "Ally". If Steam itself cannot see
the controller, check the host's controller or handheld-middleware setup first.
Monado does not install drivers or alter device permissions.

## Connection and reconnect behavior

The game tries other eligible controllers if the first one cannot be opened,
and can select a remaining controller after the active one disconnects. The
launcher uses its existing SDL/ImGui controller navigation and hotplug handling.

The write guard admits existing, strictly named HID raw character devices at
startup. A new or recreated HID raw node after the launcher starts is outside
that initial permission set. Some native HIDAPI reconnect or resume cases may
therefore require closing and reopening the launcher with the controller already
connected. Ordinary event-device input can still work through SDL's read-only
fallback; this limitation does not establish that every reconnect fails.
Reopening also refreshes the session metadata if Steam recreates it after a
controller-mode change or resume.

## Reporting a detection failure

Check whether the Controls tab lists a controller, then include:

- Monado version and whether you started it through Steam Game Mode, Desktop
  Mode or a container.
- Whether Steam and other applications detect the controller.
- Whether an external USB/Bluetooth controller works.
- The controller discovery lines from the active profile's
  `logs/launcher.log` and, if you started the game, `logs/launcher-game.log`.

Discovery logs distinguish raw joysticks from mapped gamepads and include SDL
versions, bounded device names, vendor/product IDs, GUIDs and open failures.
They do not record button streams or controller serial numbers. An empty
gamepad list can mean a missing mapping, filtering, inaccessible devices or
missing host discovery support; it is not proof of a GPU problem.

Game input stays read-only and native save formats remain unchanged. This
controller work retains the separate RADV `nodcc` workaround and its existing
validation limits in [AMD/RADV notes](AMD_RADV.md).
