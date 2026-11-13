// [XCDE] LINUX-004: enforce state-only filesystem mutations before runtime workers.
#pragma once
#include <stdbool.h>
#include <stddef.h>

// state must be an existing canonical directory validated by rt_paths_init_linux.
// Must run single-threaded, before opening any runtime output. Refuses inherited
// writable regular-file descriptors outside state, including redirected stdio.
// Restricts contents/create/remove/rename/link/truncate; reads remain unrestricted.
// Device writes are allowed only on enumerated character devices used by SDL/GPU.
// [XCDE] LINUX-077: this includes existing strictly named /dev/hidraw[0-9]+ nodes.
// Rules bind existing device inodes; a newly created HID node after startup may
// require restarting the launcher. Host permissions are never elevated.
// This is not a general hostile-code sandbox (metadata, IPC and ioctls are outside
// this policy). Never continue a game/precompile run after failure.
bool rt_linux_state_guard(const char *state, char *error, size_t error_size);
