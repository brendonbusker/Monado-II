# Graphical Linux setup and launcher

From Linux 0.1.17, the standalone builder AppImage provides graphical setup before
a game has been built. It is the recommended first-run entrypoint. The established
source-build route remains available in [BUILD_LINUX.md](BUILD_LINUX.md).

## First setup

1. Open the standalone Monado II AppImage. It does not need an adjacent checkout
   or a separately installed Python interpreter.
2. Choose **Set up Monado II**, select your own extracted DE 2.0.0 folder
   containing `exefs` and `romfs`, and check the files.
3. Choose an empty final installation folder. You can type a new folder path.
   Existing unrelated folders and edited workspaces are protected from replacement.
4. Choose whether to include NVIDIA DLSS support and prepare shaders. The
   advanced worker setting limits parallel compilation to 1–6 workers.
5. Build. Progress comes from the actual build stages and completed compilation
   units. Details include a retained log and missing-dependency instructions.
6. Open the settings launcher, configure the game, and press Play yourself.

The AppImage includes setup code, its Python runtime and the reviewed source
template. The compiler and other locked build dependencies download during
setup. No game files are included, uploaded, moved or downloaded. Monado II does
not provide game files or advice on where to obtain them. Players must use their
own legally dumped game files from their own legally obtained game and Switch.

The selected input stays in its original location. A `game_files` link in the
installation points to it. Keep that folder available when playing or updating.
Build outputs, dependencies, generated code, caches, settings and saves belong
to the installation, outside the shared input. Choose the final destination
before building: native receipts bind absolute paths, so moving an installed
workspace requires rebuilding there.

Closing setup while building asks to cancel. Cancellation stops owned workers,
retains logs and safe completed work, and never treats an incomplete build as
ready. Retry uses fresh native outputs and can reuse verified downloaded tools.
An interrupted source copy or modified source is preserved for inspection rather
than overwritten. Shader preparation is optional; if it fails after a successful
build, the settings launcher remains available and shader preparation can be
retried there.

## Subsequent opens and existing installations

The same standalone AppImage remembers a successfully checked installation and
opens its current settings launcher directly. `--setup` returns to setup. The
**Use an existing installation** action adopts a checked source-build installation
in place, including its original input, settings, saves and active update.
It does not import or convert save contents. Missing or modified installations
produce diagnostics instead of selecting an unverified game.

If you move the game files, reopen Monado II. **Locate game files** lets you
select the new folder containing `exefs` and `romfs`. It checks the supported
version and matches the executable files against your existing build before
reconnecting the installation. It leaves your saves, settings and installed
game unchanged and does not immediately rebuild it. Cancel leaves the existing
selection alone. Close other launchers, games or updates for that installation
before reconnecting. Moving the entire installed workspace is a separate action
and still requires rebuilding at its final destination.

The original build receipt retains the old input path. A subsequent update may
therefore rebuild its game payload once at the new path; it keeps the same save
and settings directory. If files disappear while an update is already open,
close the launcher and reopen it to locate them, then retry the update.

The setup registry and content-addressed Python/source cache live under
`$XDG_DATA_HOME/monado-ii-builder`, or `~/.local/share/monado-ii-builder` when XDG
data is unset. `--data-dir PATH` selects a separate registry/cache for testing.
Removing this registry does not delete the installed game or its saves; choose
**Use an existing installation** to link it again. Keep the Python cache while
an installation uses it: its virtual environment needs that persistent runtime.
The AppImage's temporary mount is never used as a permanent virtualenv base.

Existing source scripts, launcher-only images and source updater archive formats
are retained. Existing host-Python source installations keep their checked
workspace-bound image packaging path; they do not need Ubuntu-specific Python
files to update. Installations created with the standalone launcher's private
Python can package a full standalone image during later updates. The original
workspace icon still forwards to the active update and remains a workspace
bootstrap. A new standalone image can adopt that same installation in place.
The maintainer completed graphical fresh setup/build and accepted normal reopen.
An existing local installation was updated and manually confirmed to open and
play normally, with profile and input preservation checks passing. That migration
needed manually resumed packaging fixes. A clean uninterrupted older-version
update and a real moved-folder picker test remain unqualified; automated recovery
and hidden-UI checks are distinct from those manual cases.

## Requirements and scope

This changes setup presentation and interpreter packaging. It retains the current
Linux x86-64-v2, glibc 2.43+ and native GNU/driver/audio/session requirements.
It does not replace the operating system, install drivers or run sudo. Missing
host tools receive the existing distribution-specific guidance. Build and run
inside the same compatible environment when using Distrobox.

The wizard has no FSR selector. Supported graphics settings remain in the normal
settings launcher after building. FSR 4 and a Windows setup executable are not
implemented by this release. Future Windows work should reuse the setup protocol
with a portable Windows backend, rather than introduce an installer requirement.

## Maintainer validation

The separate authored setup-binary packaging entry is
`tools/build_builder_appimage.py`.
It compiles the setup frontend, checks the source template against publication
policy, packages a minimal explicit runtime closure with notices, and reads the
archive back to verify exact file identities. It never generates or builds a
game. Its outputs must be separate from the reviewed source tree. Source-only
release guards continue to reject compiled binaries, game input, generated game
code, translated shaders, caches, SDKs and saves.

`--self-check` on the standalone AppImage checks and materializes its startup
payload without opening setup or building a game. Hidden renderer fixtures,
synthetic workers and dry runs do not establish successful real generation,
shader preparation, gameplay, platform parity or save/reload coverage.
