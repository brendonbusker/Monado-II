"""[XCDE] LINUX-077: narrowly preserve SDL/Steam controller launch context.

No executable, driver-library, output-path or arbitrary SDL variable is admitted.
Steam's optional metadata remains a read-only ordinary file; its contents are
never parsed, logged or copied into the project by this helper.
"""
import os
from pathlib import Path
import re
import stat

STEAM_INFO = 'SteamVirtualGamepadInfo'
PRIVATE_INFO = 'runtime/steam-virtual-gamepad-info'
BOOL_KEYS = frozenset((
    'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD',
    'SDL_JOYSTICK_HIDAPI', 'SDL_JOYSTICK_HIDAPI_STEAMDECK',
    'SDL_JOYSTICK_HIDAPI_XBOX', 'SDL_JOYSTICK_HIDAPI_PS4',
    'SDL_JOYSTICK_HIDAPI_PS5', 'SDL_JOYSTICK_HIDAPI_SWITCH',
    'SDL_JOYSTICK_DISABLE_UDEV', 'SDL_HIDAPI_UDEV',
    'SDL_JOYSTICK_LINUX_CLASSIC',
))
ID_KEYS = frozenset(('SteamAppId', 'SteamGameId', 'SteamOverlayGameId'))
LIST_KEYS = frozenset(('SDL_GAMECONTROLLER_IGNORE_DEVICES',
                       'SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'))
CONTEXT_KEYS = BOOL_KEYS | ID_KEYS | LIST_KEYS | frozenset((
    'SDL_GAMECONTROLLERCONFIG', STEAM_INFO))
_DEVICE_LIST = re.compile(r'(?:\s*0x[0-9a-fA-F]{1,4}/0x[0-9a-fA-F]{1,4}\s*(?:,|$))*\Z')


def metadata_file(value):
    """Return only a current-user, non-linked, non-shared writable target.

    Invalid optional integration data is omitted instead of stopping an ordinary
    game launch. Host filesystem permissions and all runtime guards still apply.
    """
    if not isinstance(value, str) or not value or len(os.fsencode(value)) >= 4096 or '\0' in value:
        return None
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        return None
    try:
        if path.resolve() != path:
            return None
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o022
                or before.st_size > 1024 * 1024):
            return None
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink) != (
                opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink):
            return None
    except (OSError, ValueError):
        return None
    return path


def preserve(environment):
    """Validate known input settings; never mutate the caller's environment."""
    result = {}
    for key in CONTEXT_KEYS:
        value = environment.get(key)
        if not isinstance(value, str) or '\0' in value:
            continue
        if key in BOOL_KEYS:
            if value in ('0', '1'):
                result[key] = value
        elif key in ID_KEYS:
            if re.fullmatch(r'[0-9]{1,20}', value) and int(value) < 1 << 64:
                result[key] = value
        elif key in LIST_KEYS:
            if len(value) <= 32768 and (not value or _DEVICE_LIST.fullmatch(value)):
                result[key] = value
        elif key == 'SDL_GAMECONTROLLERCONFIG':
            # SDL owns the mapping grammar; bound text, not a file/code path.
            if len(value.encode('utf-8')) <= 65536 and not any(ord(c) < 32 and c not in '\r\n\t' for c in value):
                result[key] = value
        elif key == STEAM_INFO:
            path = metadata_file(value)
            if path is not None:
                result[key] = str(path)
    return result


def namespace_metadata(environment, state):
    """Plan a single read-only file bind, before private /tmp hides its source."""
    source = metadata_file(environment.get(STEAM_INFO))
    if source is None:
        return None
    target = Path(state) / PRIVATE_INFO
    # Only run_linux's verified private_tmp_alias can authorize namespace reuse.
    # A matching filename alone must not bypass this read-only bind on a cold
    # launch. Inherited launches never call this fresh-namespace planner.
    return {'source': str(source), 'target': str(target)}


def private_environment(environment, state, planned_namespace):
    result = dict(environment)
    source = metadata_file(result.get(STEAM_INFO))
    if source is None:
        result.pop(STEAM_INFO, None)
    elif planned_namespace:
        result[STEAM_INFO] = str(Path(state) / PRIVATE_INFO)
    return result
