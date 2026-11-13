# Quiver setup and review information

The primary release downloads are **setup/build kits**, named
`monado-ii-<version>-linux-setup.tar.gz` and
`monado-ii-windows-original-implementation-setup.zip`. They contain reviewed authored source and
setup entrypoints. The player builds locally using their own legally dumped,
already-extracted Switch Definitive Edition 2.0.0 files. No game files, keys,
firmware, generated game code/binaries, translated game shaders/caches, saves or
private SDK binaries are distributed. A local build is required before playing.

Windows remains the original implementation without the Linux additions. Its
version-free filename does not advance with Linux release numbers.

## Linux entrypoint

Configure Quiver's preferred Linux executable as **`App_Monado_II.sh`**, using a
direct/native runner. The name also sorts before the build-only shell entrypoint
under the observed Quiver default executable finder.

On first launch, this entrypoint opens an installed terminal for the existing local
build workflow. The terminal shows missing prerequisites, input placement, build
progress and errors. Place the user's input in `game_files/exefs` and
`game_files/romfs` beside the script, or use the existing supported folder link.
Retry the same entrypoint after resolving a reported prerequisite or input issue.
A successful build opens the ordinary settings launcher; it never automatically
presses Play or starts the game. Later launches open the existing checked launcher
AppImage through `Play_Monado_II.sh`.

Desktop first-build support needs an installed `x-terminal-emulator`, Konsole,
GNOME Terminal or xterm. No terminal or system package is installed automatically.
Without one, an already-installed KDialog/Zenity shows the manual build command
when available; stderr also contains the instructions. The normal terminal flow
remains `./Build_Monado_II.sh`, then `./Play_Monado_II.sh`. See
[Linux prerequisites and first-build details](BUILD_LINUX.md).

Keep the complete extracted folder after building. Its launcher AppImage uses
local adjacent outputs and game input; it is not a standalone distributed game.
Settings, caches and saves remain under `Monado_Linux/play/launcher`, outside the
read-only game input. Changing a Quiver program selection does not copy or move
these files. Use Monado II's in-launcher updater for its checked local rebuild,
profile preservation and rollback behavior.

## Windows boundary

The Windows kit retains the inherited source/build route. Install its documented
prerequisites yourself and follow [Windows build instructions](BUILD_WINDOWS.md)
in Git Bash; launch the inherited Windows launcher after the build. A packaged
Windows archive is not a verified one-click Quiver installation or a tested
Windows game. Do not configure the Linux shell bootstrap as a Windows program.

## What was verified

The observed Quiver launcher filename filter rejects separator-delimited `source`
and related auxiliary words. The canonical setup names pass that filter and use
recognized archive formats. The Linux `-source.tar.gz` compatibility alias exists
only for older Monado updaters, and is expected to remain hidden by Quiver.

The primary-source review also established that Quiver flattens a single archive
wrapper, discovers Linux shell scripts and executes the selected program with its
standard streams hidden. That is why a terminal-visible bootstrap is needed in
addition to renaming the release assets. Authored command fixtures verify the
bootstrap's space-safe arguments, build/launch order, failure/cancellation and
input/profile preservation. These checks do not establish catalog acceptance or
an end-to-end run inside the Quiver application.

Sources: [asset selection](https://github.com/tgeorgiadis/quiver-launcher/blob/41eec97383adc05bc30c8a9a54686b9fc75bf8ce/apps/launcher/src/assets.ts),
[archive and executable handling](https://github.com/tgeorgiadis/quiver-launcher/blob/41eec97383adc05bc30c8a9a54686b9fc75bf8ce/apps/launcher/src-tauri/src/install.rs),
[native launch handling](https://github.com/tgeorgiadis/quiver-launcher/blob/41eec97383adc05bc30c8a9a54686b9fc75bf8ce/apps/launcher/src-tauri/src/lib.rs).

## Suggested re-review explanation

Monado II now publishes platform-specific setup/build kits as GitHub Release
assets, rather than filenames identified as auxiliary source archives. The Linux
kit's `App_Monado_II.sh` provides visible first-run local setup and subsequently
opens the native launcher. Users must supply their own supported legal game dump;
game generation and compilation happen locally. The Windows kit retains a manual
build route with its validation limits documented. Please re-review the canonical
`-setup` downloads; the Linux `-source` asset is solely a legacy updater alias.
