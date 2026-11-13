#!/usr/bin/env bash
# [XCDE] LINUX-066: ordinary build bootstrap; no OS-metadata eval or host forwarding.

monado_build_usage() {
    printf '%s\n' \
        'Usage: ./Build_Monado_II.sh [--install-deps] [--jobs 1-6] [--without-dlss] [--plan]' \
        '' 'Build locally using your own extracted DE 2.0.0 input; never start the game.' \
        '--install-deps  Request a supported container package transaction first.' \
        '                Only the package transaction uses sudo; builds stay your user.' \
        '--plan          Print the build plan without downloads, installations or builds.' \
        '--without-dlss  Omit NVIDIA DLSS/DLAA and experimental frame generation.' \
        '--jobs 1-6      Parallel compiler jobs (default 4).' \
        '--reuse-game P  Rebuild the launcher using a verified compatible game.' \
        '--game-only     Internal: build a game payload without a launcher.' \
        '--help          Show help without requiring Python or dependencies.' \
        '' 'Normal builds diagnose prerequisites and download private dependencies locally.' \
        'Missing native packages receive distribution-specific installation instructions.'
}

monado_find_python() {
    local kind=$1 source_root=${2:-} name candidate canonical parent_python=''
    local -a candidates=()
    for name in python3.14 python3 python3.15 python3.13 python3.12 python3.11 python3.10 python3.9; do
        candidate=$(type -P "$name" 2>/dev/null) || continue
        candidates+=("$candidate")
    done
    if [[ -n $source_root ]]; then candidates+=("$source_root/Monado_Linux/.venv/bin/python"); fi
    # Older update workers have a clean PATH but are themselves running the
    # installed CPython 3.14. Inspect only their executable link; never execute
    # an arbitrary parent terminal/program and never retain a volatile /proc path.
    if [[ -x /usr/bin/readlink ]]; then
        parent_python=$(/usr/bin/readlink -- "/proc/$PPID/exe" 2>/dev/null) || parent_python=''
        if [[ ${parent_python##*/} =~ ^python3(\.14)?$ ]]; then candidates+=("$parent_python"); fi
    fi
    for candidate in "${candidates[@]}"; do
        [[ $candidate == /* && -f $candidate && -x $candidate ]] || continue
        if [[ $kind == build ]]; then
            canonical=$("$candidate" -I -B -c 'import os,platform,sys;sys.exit(1) if not(platform.python_implementation()=="CPython" and sys.version_info[:2]==(3,14)) else print(os.path.realpath(sys.executable))' 2>/dev/null) || continue
        else
            canonical=$("$candidate" -I -B -c 'import os,platform,sys;sys.exit(1) if not(platform.python_implementation()=="CPython" and sys.version_info[:2]>=(3,9)) else print(os.path.realpath(sys.executable))' 2>/dev/null) || continue
        fi
        [[ $canonical == /* && $canonical != *$'\n'* && -f $canonical && -x $canonical ]] || continue
        printf '%s\n' "$canonical"; return 0
    done
    return 1
}

monado_read_os() {
    MONADO_OS_ID=unknown MONADO_OS_VERSION=unknown
    local line key value count=0
    [[ -r /etc/os-release ]] || return 0
    # Read bounded plain values from the current environment, never host metadata.
    while IFS= read -r -n 4096 line || [[ -n $line ]]; do
        count=$((count+1)); (( count <= 128 )) || break
        [[ $line == *=* ]] || continue
        key=${line%%=*}; value=${line#*=}
        case $value in \"*\") value=${value:1:${#value}-2} ;; \'*\') value=${value:1:${#value}-2} ;; esac
        [[ $value =~ ^[a-zA-Z0-9_.-]{1,64}$ ]] || continue
        case $key in ID) MONADO_OS_ID=$value ;; VERSION_ID) MONADO_OS_VERSION=$value ;; esac
    done < /etc/os-release
}

monado_is_distrobox() {
    # An inherited environment flag alone never authorizes a package operation.
    [[ ${CONTAINER_ID:-} =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] || return 1
    [[ -f /run/.containerenv && ! -L /run/.containerenv || -f /.dockerenv && ! -L /.dockerenv ]] || return 1
    [[ -f /usr/bin/distrobox-host-exec && -x /usr/bin/distrobox-host-exec ]] || return 1
}

monado_trusted_admin_tool() {
    local path=$1 metadata uid mode
    [[ -f $path && ! -L $path && -x $path && -x /usr/bin/stat ]] || return 1
    metadata=$(/usr/bin/stat -c '%u %a' -- "$path" 2>/dev/null) || return 1
    read -r uid mode <<< "$metadata"
    [[ $uid == 0 && $mode =~ ^[0-7]{3,4}$ ]] || return 1
    (( (8#$mode & 8#022) == 0 ))
}

monado_missing_python_help() {
    monado_read_os
    printf 'Monado II dependency check: %s %s\n' "$MONADO_OS_ID" "$MONADO_OS_VERSION" >&2
    printf '%s\n' 'Missing: CPython 3.14 (required build interpreter).' >&2
    case $MONADO_OS_ID in
        bazzite) printf '%s\n' 'Native Bazzite uses rpm-ostree; this script does not run dnf on its host.' \
            'Use your supported python3.14 package/environment. Missing dpkg-deb is supplied by dpkg:' \
            '  rpm-ostree install dpkg' 'Reboot to apply a pending deployment, then retry.' >&2 ;;
        steamos) printf '%s\n' 'Use a compatible Distrobox with Python 3.14 and glibc 2.43+; SteamOS is not unlocked or modified by this script.' >&2 ;;
        fedora) printf '%s\n' 'Fedora package: python3.14. In a supported Fedora 45 Distrobox, retry:' \
            '  ./Build_Monado_II.sh --install-deps' 'Native Fedora: sudo dnf install python3.14' >&2 ;;
        ubuntu|debian) printf '%s\n' 'On a compatible Ubuntu baseline: sudo apt-get install python3.14 python3.14-venv' \
            'Debian Trixie glibc 2.41 is below required 2.43; use a newer compatible container.' >&2 ;;
        arch|cachyos) printf '%s\n' 'Install CPython 3.14 using your distribution-supported method; a newer default Python does not replace this baseline.' >&2 ;;
        *) printf '%s\n' 'Install CPython 3.14 and venv support using your distribution; see docs/BUILD_LINUX.md.' >&2 ;;
    esac
    printf '%s\n' 'Generation and compilation have not started; existing input and saves stay in their selected locations.' >&2
}

monado_bootstrap_python() {
    # Only bootstrap the interpreter when no Python can run the stdlib doctor.
    if [[ ! -x /usr/bin/uname ]] || [[ $(/usr/bin/uname -s) != Linux || $(/usr/bin/uname -m) != x86_64 ]]; then
        printf '%s\n' 'Monado II requires Linux x86-64; nothing will be installed.' >&2; return 1
    fi
    monado_read_os
    if [[ $MONADO_OS_ID != fedora || $MONADO_OS_VERSION != 45 ]] || ! monado_is_distrobox; then
        printf '%s\n' 'Automatic installation requires a verified supported Distrobox; native/unknown environments receive manual instructions.' >&2
        monado_missing_python_help; return 1
    fi
    local libc='' major minor
    if [[ ! -x /usr/bin/getconf ]] || ! libc=$(/usr/bin/getconf GNU_LIBC_VERSION 2>/dev/null) ||
       [[ ! $libc =~ ^glibc[[:space:]]([0-9]+)\.([0-9]+)$ ]]; then
        printf '%s\n' 'Cannot verify container glibc; nothing will be installed.' >&2; return 1
    fi
    major=${BASH_REMATCH[1]}; minor=${BASH_REMATCH[2]}
    if (( major < 2 || (major == 2 && minor < 43) )); then
        printf 'Incompatible container: %s; requires glibc 2.43+. Nothing installed.\n' "$libc" >&2; return 1
    fi
    [[ -t 0 && -t 1 ]] || { printf '%s\n' '--install-deps needs an interactive terminal. Background updates never install packages.' >&2; return 1; }
    (( EUID != 0 )) || { printf '%s\n' 'Run the build as your normal container user; only its package command may use sudo.' >&2; return 1; }
    monado_trusted_admin_tool /usr/bin/dnf5 && monado_trusted_admin_tool /usr/bin/sudo && monado_trusted_admin_tool /usr/bin/env || {
        printf '%s\n' 'Trusted container dnf5/sudo unavailable. Install python3.14 with your container administrator, then retry.' >&2; return 1;
    }
    printf '%s\n' 'Missing Python 3.14 in Fedora 45 Distrobox.' 'Container transaction:' \
        '  sudo /usr/bin/dnf5 install --setopt=install_weak_deps=False python3.14' \
        'Review and confirm the transaction. Compilation continues as your normal user.' >&2
    /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
        /usr/bin/sudo /usr/bin/dnf5 install --setopt=install_weak_deps=False python3.14 || return $?
}

monado_build_entry() {
    local source_root=$1; shift
    local install=0 plan=0 help=0 dlss=1 game_only=0 framegen=0 reuse=0 value arg original equal
    local -a build_args=() doctor_args=(--check)
    # Validate arguments before any possible privileged package transaction.
    while (( $# )); do
        arg=$1; shift
        case $arg in
            --install-deps) install=1 ;;
            --plan) plan=1; build_args+=("$arg") ;;
            --help|-h) help=1 ;;
            --without-dlss) dlss=0; build_args+=("$arg") ;;
            --game-only) game_only=1; build_args+=("$arg") ;;
            --framegen) framegen=1; build_args+=("$arg") ;;
            --jobs|--reuse-game|--build-id|--jobs=*|--reuse-game=*|--build-id=*)
                original=$arg; equal=0
                if [[ $arg == *=* ]]; then equal=1; value=${arg#*=}; arg=${arg%%=*}; else
                    (( $# )) || { printf 'Build argument %s requires a value.\n' "$arg" >&2; return 2; }
                    value=$1; shift
                fi
                case $arg in
                    --jobs) [[ $value =~ ^\+?0*[1-6]$ ]] || { printf '%s\n' '--jobs must be an integer from 1 to 6.' >&2; return 2; } ;;
                    --build-id) [[ $value =~ ^[a-zA-Z0-9_-]+$ ]] && { (( equal )) || [[ $value != -* ]]; } || { printf '%s\n' 'Unsafe or malformed build identity.' >&2; return 2; } ;;
                    --reuse-game) [[ -n $value ]] && { (( equal )) || [[ $value != -* ]]; } || { printf '%s\n' '--reuse-game requires a path.' >&2; return 2; }; reuse=1 ;;
                esac
                if (( equal )); then build_args+=("$original"); else build_args+=("$arg" "$value"); fi ;;
            *) printf 'Unknown build argument: %s\nUse ./Build_Monado_II.sh --help.\n' "$arg" >&2; return 2 ;;
        esac
    done
    if (( help )); then monado_build_usage; return 0; fi
    if (( framegen && !dlss )); then printf '%s\n' '--framegen requires DLSS/DLAA; cannot combine with --without-dlss.' >&2; return 2; fi
    if (( game_only && reuse )); then printf '%s\n' '--game-only cannot reuse a game payload.' >&2; return 2; fi
    local build_python='' diagnostic_python=''
    build_python=$(monado_find_python build "$source_root") || true
    if (( plan )); then
        if [[ -z $build_python ]]; then monado_missing_python_help; return 1; fi
        exec "$build_python" -I -B "$source_root/tools/build_linux_app.py" "${build_args[@]}"
    fi
    diagnostic_python=$build_python
    if [[ -z $diagnostic_python ]]; then diagnostic_python=$(monado_find_python doctor "$source_root") || true; fi
    if [[ -z $diagnostic_python ]]; then
        if (( !install )); then monado_missing_python_help; return 1; fi
        monado_bootstrap_python || return $?
        diagnostic_python=$(monado_find_python doctor "$source_root") || { monado_missing_python_help; return 1; }
    fi
    (( install )) && doctor_args=(--install-deps)
    (( dlss )) || doctor_args+=(--without-dlss)
    (( game_only )) && doctor_args+=(--game-only)
    "$diagnostic_python" -I -B "$source_root/tools/linux_prerequisites.py" "${doctor_args[@]}" || return $?
    build_python=$(monado_find_python build "$source_root") || { monado_missing_python_help; return 1; }
    exec "$build_python" -I -B "$source_root/tools/build_linux_app.py" "${build_args[@]}"
}
