// [XCDE] LINUX-075: process-local RADV compatibility, before graphics startup.
#pragma once
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif
// Returns 0 on success, -1 with an error message on invalid policy/env failure.
int rt_radv_dcc_prepare(char *error, size_t error_size);
bool rt_radv_dcc_active(void);
#ifdef __cplusplus
}
#endif
