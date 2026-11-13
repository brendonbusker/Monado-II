#!/usr/bin/env bash
# Build locally from the player's extracted input. Never run the game.
set -euo pipefail
monado_source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# Diagnose missing Python before the Python build program starts.
source "$monado_source_root/tools/linux_prerequisites.sh"
monado_build_entry "$monado_source_root" "$@"
