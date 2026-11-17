// [XCDE] LINUX-129: true enemy HP, applied to fresh native derived stats.
// Native combat, protection flags, phase events, healing and rewards still run.
#include "../hle.h"
#include "../cheats_options.h"
#include "cheats_enemy_health.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>

#define STATUS_STATS UINT64_C(0x149c)
#define STATUS_DIRTY UINT64_C(0x1030)
#define ENEMY_KIND UINT64_C(0x700047f780)
#define ENEMY_STATS UINT64_C(0x700047f2b0)
#define HP_CURRENT UINT64_C(8)
#define HP_MAX UINT64_C(0xe8)
#define BUCKETS 1024u
#define INITIAL_DERIVED_RETURN UINT64_C(0x700047ebc0)

// Keys/links never change after publication. A destroyed instance is invalidated,
// then construction/initialization starts a new generation at a reused address.
// Nodes are retained until the runtime reset (after all guest threads stop), so
// readers never acquire a dangling host node. No active record is evicted.
typedef struct EnemyHp {
    struct EnemyHp *next;
    uint64_t status, generation;
    atomic_bool alive;
    atomic_bool ready;
    atomic_int applied;
    bool initializing; // protected by state_lock
} EnemyHp;

typedef struct Recompute {
    struct Recompute *next;
    Cpu *cpu;
    uint64_t stack, status, stats, generation;
    uint32_t old_max, old_current;
    int previous, requested;
    bool initializing;
} Recompute;

static _Atomic(EnemyHp *) buckets[BUCKETS];
static atomic_uint modified_count;
static pthread_mutex_t state_lock = PTHREAD_MUTEX_INITIALIZER;
static Recompute *recomputes;

static bool hp_range(uint64_t address, uint64_t bytes) {
    return address >= GUEST_LO && address < GUEST_HI && bytes <= GUEST_HI - address;
}

static unsigned bucket(uint64_t status) {
    return (unsigned)(((status >> 4) ^ (status >> 19)) & (BUCKETS - 1));
}

static EnemyHp *find(uint64_t status) {
    EnemyHp *node = atomic_load_explicit(&buckets[bucket(status)], memory_order_acquire);
    for (; node; node = node->next) if (node->status == status) return node;
    return NULL;
}

static bool enemy(uint64_t status) {
    if (!hp_range(status, STATUS_STATS + 0x138)) return false;
    uint64_t vtable = LD64(status);
    return hp_range(vtable, 0xd0) && LD64(vtable + 8) == ENEMY_KIND &&
           LD64(vtable + 0xc8) == ENEMY_STATS;
}

static void applied(EnemyHp *node, int value) {
    int old = atomic_load_explicit(&node->applied, memory_order_relaxed);
    if (old == 100 && value != 100) atomic_fetch_add_explicit(&modified_count, 1, memory_order_relaxed);
    if (old != 100 && value == 100) atomic_fetch_sub_explicit(&modified_count, 1, memory_order_relaxed);
    atomic_store_explicit(&node->applied, value, memory_order_release);
}

static void lifetime(uint64_t status, bool initializing) {
    if (!hp_range(status, STATUS_STATS + 0x138))
        FATAL("[cheats] enemy health construction ABI changed\n");
    pthread_mutex_lock(&state_lock);
    EnemyHp *node = find(status);
    if (!node) {
        node = calloc(1, sizeof *node);
        if (!node) FATAL("[cheats] cannot track enemy health lifetime\n");
        node->status = status;
        atomic_init(&node->alive, false);
        atomic_init(&node->ready, false);
        atomic_init(&node->applied, 100);
        unsigned index = bucket(status);
        node->next = atomic_load_explicit(&buckets[index], memory_order_relaxed);
        atomic_store_explicit(&buckets[index], node, memory_order_release);
    }
    applied(node, 100);
    ++node->generation;
    node->initializing = initializing;
    atomic_store_explicit(&node->ready, false, memory_order_release);
    atomic_store_explicit(&node->alive, true, memory_order_release);
    pthread_mutex_unlock(&state_lock);
}

void xcde_cheats_enemy_health_construct(Cpu *c) { lifetime(c->x[0], false); }

void xcde_cheats_enemy_health_initialize(Cpu *c) {
    if (!enemy(c->x[0])) FATAL("[cheats] enemy health initializer ABI changed\n");
    lifetime(c->x[0], true);
}

static void destroy(uint64_t status) {
    pthread_mutex_lock(&state_lock);
    EnemyHp *node = find(status);
    if (node) {
        applied(node, 100);
        ++node->generation;
        node->initializing = false;
        atomic_store_explicit(&node->ready, false, memory_order_release);
        atomic_store_explicit(&node->alive, false, memory_order_release);
    }
    pthread_mutex_unlock(&state_lock);
}
void xcde_cheats_enemy_health_destroy(Cpu *c) { destroy(c->x[0]); }
void xcde_cheats_enemy_health_destroy_component(Cpu *c) {
    if (c->x[0] > UINT64_MAX - 0x60) FATAL("[cheats] enemy health destructor ABI changed\n");
    destroy(c->x[0] + 0x60);
}

void xcde_cheats_enemy_health_update(Cpu *c) {
    int want = xcde_cheats_enemy_health_percent();
    if (want == 100 && !atomic_load_explicit(&modified_count, memory_order_relaxed)) return;
    uint64_t status = c->x[19];
    if (!enemy(status)) return;
    EnemyHp *node = find(status);
    if (!node || !atomic_load_explicit(&node->alive, memory_order_acquire)) {
        if (want == 100) return;
        FATAL("[cheats] enemy health update has no live instance\n");
    }
    // Construction does not initialize the native HP storage. During loading,
    // ordinary component refresh can run before the native base-stat initializer.
    // Do not force a stat refresh or interpret that storage as live health.
    if (!atomic_load_explicit(&node->ready, memory_order_acquire)) return;
    if (atomic_load_explicit(&node->applied, memory_order_acquire) == want) return;
    // This is the current actor's native CPU-owned update, before its dirty gate.
    // No renderer writes, cross-actor scans or steady-state locks/recalculations.
    ST64(status + STATUS_DIRTY, LD64(status + STATUS_DIRTY) | (UINT64_C(1) << 32));
}

void xcde_cheats_enemy_health_recompute_begin(Cpu *c) {
    uint64_t status = c->x[3], stats = c->x[0];
    if (!enemy(status)) return;
    int want = xcde_cheats_enemy_health_percent();
    pthread_mutex_lock(&state_lock);
    EnemyHp *node = find(status);
    if (!node || !atomic_load_explicit(&node->alive, memory_order_relaxed)) {
        pthread_mutex_unlock(&state_lock);
        if (want == 100) return; // Unknown native object remains exact when off.
        FATAL("[cheats] enemy health recompute has no live instance\n");
    }
    int previous = atomic_load_explicit(&node->applied, memory_order_relaxed);
    bool ready = atomic_load_explicit(&node->ready, memory_order_relaxed);
    // Only the checked call after native base initialization can transition a
    // constructed actor to live HP. An intermediate generic refresh, even while
    // initialization is in progress, must retain its exact native behavior.
    bool initializing = !ready && node->initializing && c->x[30] == INITIAL_DERIVED_RETURN;
    if (!ready && !initializing) {
        pthread_mutex_unlock(&state_lock);
        return;
    }
    if (want != 100 || previous != 100 || initializing) {
        if (stats != status + STATUS_STATS) FATAL("[cheats] enemy health stats ABI changed\n");
        Recompute *item = calloc(1, sizeof *item);
        if (!item) FATAL("[cheats] cannot retain enemy health recompute\n");
        *item = (Recompute){.next = recomputes, .cpu = c, .stack = c->sp,
            .status = status, .stats = stats, .generation = node->generation,
            .old_max = LD32(stats + HP_MAX), .old_current = LD32(stats + HP_CURRENT),
            .previous = previous, .requested = want, .initializing = initializing};
        recomputes = item;
    }
    pthread_mutex_unlock(&state_lock);
}

static uint32_t scaled_max(uint32_t native, int percent) {
    uint64_t value = (uint64_t)native * (unsigned)percent / 100;
    // Retain at least100 HP (or the smaller original maximum) when reducing HP.
    // A fixed1HP survival floor can then still reach a1% phase gate; rounding
    // never becomes coarser than the original for tiny native enemies.
    uint32_t floor = native < 100 ? native : 100;
    if (value < floor) value = floor;
    if (value > INT32_MAX) value = INT32_MAX;
    return (uint32_t)value;
}

static uint32_t fraction(uint32_t current, uint32_t before, uint32_t after) {
    if (!current) return 0; // Never resurrect a dead enemy on a live change.
    if (current >= before) return after;
    uint64_t value = ((uint64_t)current * after + before - 1) / before;
    return value ? (uint32_t)value : 1;
}

void xcde_cheats_enemy_health_max(Cpu *c) {
    uint64_t status = c->x[20], stats = c->x[19];
    if (!enemy(status)) return;
    pthread_mutex_lock(&state_lock);
    EnemyHp *node = find(status);
    if (!node || !atomic_load_explicit(&node->alive, memory_order_relaxed)) {
        pthread_mutex_unlock(&state_lock);
        if (xcde_cheats_enemy_health_percent() == 100) return;
        FATAL("[cheats] enemy health final stat has no live instance\n");
    }
    Recompute **link = &recomputes;
    while (*link && !((*link)->cpu == c && (*link)->stack == c->sp + 0xb0 &&
                       (*link)->status == status && (*link)->stats == stats)) link = &(*link)->next;
    Recompute *item = *link;
    if (item) {
        if (stats != status + STATUS_STATS || c->sp > UINT64_MAX - 0xb0)
            FATAL("[cheats] enemy health final stat ABI changed\n");
        *link = item->next;
        if (item->generation != node->generation) FATAL("[cheats] enemy health lifetime changed during recompute\n");
        if (item->requested != 100 || item->previous != 100) {
            uint32_t native = (uint32_t)c->x[8];
            if (!native || native > INT32_MAX) FATAL("[cheats] enemy health native maximum outside signed range\n");
            uint32_t maximum = item->requested == 100 ? native : scaled_max(native, item->requested);
            bool rebase = item->initializing ? item->requested != 100 : item->previous != item->requested;
            if (rebase) {
                uint32_t before = item->initializing ? native : item->old_max;
                if (!before || before > INT32_MAX || item->old_current > INT32_MAX)
                    FATAL("[cheats] enemy health prior HP outside signed range\n");
                ST32(stats + HP_CURRENT, fraction(item->old_current, before, maximum));
            }
            // An ordinary buff recomputation scales its fresh maximum but keeps
            // native current policy. Off/1x initial contexts only complete the
            // host lifecycle; they do not clamp or otherwise rewrite native HP.
            c->x[8] = maximum;
        }
        applied(node, item->requested);
        if (item->initializing) {
            node->initializing = false;
            atomic_store_explicit(&node->ready, true, memory_order_release);
        }
        free(item);
    } else if (atomic_load_explicit(&node->applied, memory_order_relaxed) != 100) {
        FATAL("[cheats] enemy health lost an owned recompute context\n");
    }
    pthread_mutex_unlock(&state_lock);
}

static bool owned(uint64_t status) {
    if (!atomic_load_explicit(&modified_count, memory_order_relaxed)) return false;
    if (!enemy(status)) return false;
    EnemyHp *node = find(status);
    return node && atomic_load_explicit(&node->alive, memory_order_acquire) &&
           atomic_load_explicit(&node->ready, memory_order_acquire) &&
           atomic_load_explicit(&node->applied, memory_order_acquire) != 100;
}

bool xcde_cheats_enemy_health_add(Cpu *c) {
    if (!owned(c->x[19])) return false;
    int64_t sum = (int64_t)(int32_t)c->x[8] + (int32_t)c->x[20];
    if (sum < 0) sum = 0;
    if (sum > INT32_MAX) sum = INT32_MAX;
    c->x[20] = (uint32_t)sum;
    return true; // Native clamp, dirty flags, protections and reactions follow.
}

bool xcde_cheats_enemy_health_floor_convert(Cpu *c) {
    uint64_t status = c->x[19];
    if (!owned(status)) return false;
    if (c->x[0] != status + STATUS_STATS) FATAL("[cheats] enemy health floor stats ABI changed\n");
    // Keep the native MUL's W8 result for register identity, but convert the
    // full product. Use the runtime's ARM FP operation, preserving FPCR/FPSR.
    uint64_t value = (uint64_t)LD32(c->x[0] + HP_MAX) * (uint16_t)c->x[9];
    FP_SETS(0, fromint_s(c, value, 64, 1, 0));
    return true;
}

void xcde_cheats_enemy_health_floor_clamp(Cpu *c) {
    uint64_t status = c->x[19];
    if (!owned(status)) return;
    uint32_t max = LD32(status + STATUS_STATS + HP_MAX);
    if ((uint32_t)c->x[22] > max) c->x[22] = max;
}

RT_ON_RESET(enemy_health_reset) {
    // Runtime contract: no guest threads remain, so readers cannot retain nodes.
    for (unsigned i = 0; i < BUCKETS; ++i) {
        EnemyHp *node = atomic_load_explicit(&buckets[i], memory_order_relaxed);
        while (node) { EnemyHp *next = node->next; free(node); node = next; }
        atomic_store_explicit(&buckets[i], NULL, memory_order_relaxed);
    }
    while (recomputes) { Recompute *next = recomputes->next; free(recomputes); recomputes = next; }
    atomic_store_explicit(&modified_count, 0, memory_order_relaxed);
}
