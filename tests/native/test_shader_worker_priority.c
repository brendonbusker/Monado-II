// [XCDE] LINUX-126: actual Linux priority function, real TID isolation + denials.
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef REAL_PRIORITY
static int current, fail_get, fail_set, set_calls, get_calls;
static long tid = 123;
static long fake_syscall(long number) { assert(number == SYS_gettid); return tid; }
static int fake_getpriority(int which, id_t who) {
    assert(which == PRIO_PROCESS && who == (id_t)tid);
    get_calls++;
    if (fail_get) { errno = EACCES; return -1; }
    return current;
}
static int fake_setpriority(int which, id_t who, int value) {
    assert(which == PRIO_PROCESS && who == (id_t)tid && value == 5);
    set_calls++;
    if (fail_set) { errno = EPERM; return -1; }
    current = value;
    return 0;
}
#define syscall fake_syscall
#define getpriority fake_getpriority
#define setpriority fake_setpriority
#endif
#include "shader_priority_section_fixture.h"
#ifndef REAL_PRIORITY
#undef syscall
#undef getpriority
#undef setpriority
#else
static int child_before, child_after;
static void *child(void *unused) {
    (void)unused;
    child_before = getpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid));
    errno = EDOM;
    plat_thread_shader_background();
    assert(errno == EDOM);
    plat_thread_shader_background();
    child_after = getpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid));
    assert(child_after == child_before || child_after == (child_before < 5 ? 5 : child_before));
    return NULL;
}
#endif

int main(int argc, char **argv) {
    assert(argc == 2);
#ifndef REAL_PRIORITY
    if (!strcmp(argv[1], "already-lower")) current = 10;
    else if (!strcmp(argv[1], "get-denied")) fail_get = 1;
    else if (!strcmp(argv[1], "set-denied")) fail_set = 1;
    else if (!strcmp(argv[1], "tid-denied")) tid = -1;
    else assert(!strcmp(argv[1], "normal"));
    errno = EDOM;
    plat_thread_shader_background();
    plat_thread_shader_background();
    assert(errno == EDOM);
    assert(get_calls == (tid > 0 ? 1 : 0));
    assert(set_calls == (tid > 0 && !fail_get && strcmp(argv[1], "already-lower") ? 1 : 0));
#else
    int before = getpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid));
    pthread_t thread;
    assert(!pthread_create(&thread, NULL, child, NULL));
    assert(!pthread_join(thread, NULL));
    assert(getpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid)) == before);
    printf("owned child nice %d -> %d; parent unchanged %d\n", child_before, child_after, before);
#endif
    printf("shader worker priority: PASS %s\n", argv[1]);
    return 0;
}
