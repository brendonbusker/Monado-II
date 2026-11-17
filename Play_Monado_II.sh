#!/usr/bin/env bash
# [XCDE] LINUX-025: run the locally generated launcher image without needing FUSE.
set -euo pipefail
monado_kit_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
monado_launcher_image="$monado_kit_root/Monado-II-x86_64.AppImage"
if [[ ! -f "$monado_launcher_image" || -L "$monado_launcher_image" || ! -x "$monado_launcher_image" ]]; then
    printf '%s\n' \
        'This script requires the executable Monado-II-x86_64.AppImage beside it.' \
        'For a graphical build, reopen the same standalone AppImage. Reuse the same --data-dir if you set one.' \
        'For a terminal build, run ./Build_Monado_II.sh to create the adjacent launcher image.' >&2
    exit 1
fi
# The official runtime extracts only the small launcher payload temporarily.
# Game input, generated game code, configuration, caches and saves stay outside.
exec "$monado_launcher_image" --appimage-extract-and-run "$@"
