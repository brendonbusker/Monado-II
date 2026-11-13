// [XCDE] LINUX-070: checked driver-owned Linux guest heap.
// Design references: Peiikai/LASRecomp PR71/255 (MIT); authored for Monado.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <vulkan/vulkan.h>

typedef enum VkDriverHeapMode { VK_DRIVER_HEAP_NONE, VK_DRIVER_HEAP_PLACED, VK_DRIVER_HEAP_DMABUF } VkDriverHeapMode;
// Optional platform seam for authored failure tests; NULL uses mmap/munmap/close.
// fd < 0 restores fresh anonymous RW memory; fixed=false is only an fd probe.
typedef struct VkDriverHeapMapOps {
    void *(*map)(void *context, void *address, size_t size, int fd, bool fixed);
    int (*unmap)(void *context, void *address, size_t size);
    int (*close_fd)(void *context, int fd);
} VkDriverHeapMapOps;
typedef struct VkDriverHeapOptions {
    bool placed, dmabuf;
    VkDeviceSize map_alignment;
    const VkDriverHeapMapOps *map_ops;
    void *map_context;
} VkDriverHeapOptions;
typedef struct VkDriverHeap {
    VkBuffer buffer;
    VkDeviceMemory memory;
    VkDeviceSize size, allocation_size;
    uint32_t memory_type;
    void *address;
    VkDriverHeapMode mode;
    // Internal ownership retained on an unrecoverable cleanup failure.
    bool mapped, needs_restore;
    void *probe_address;  // retained if a probe unmap fails, for checked retry
    PFN_vkUnmapMemory2KHR unmap2;
    VkDriverHeapMapOps map_ops;
    void *map_context;
} VkDriverHeap;

// Caller exclusively owns an untouched anonymous RW reservation [address,size).
// Allocate its full capacity BEFORE publishing guest SetHeapSize. No live guest
// data may be remapped. All paths require coherent cached system memory (never
// discrete VRAM). out must be empty. Failure normally leaves it empty and leaves
// a fresh usable reservation. reservation_ok=false is fatal: do not use/fallback
// through that address or discard retained out ownership.
VkResult vk_driver_heap_create(VkPhysicalDevice physical, VkDevice device,
                               void *address, VkDeviceSize size, VkBufferUsageFlags usage,
                               const VkDriverHeapOptions *options, VkDriverHeap *out,
                               bool *reservation_ok, char *error, size_t error_size);
// Guest producers stopped and ALL recorded/submitted GPU users retired. Restores
// anonymous RW pages before releasing backing. Idempotent when empty. On failure
// ownership remains in out and reservation_ok=false; caller must stop safely.
VkResult vk_driver_heap_destroy(VkDevice device, VkDriverHeap *out,
                                bool *reservation_ok, char *error, size_t error_size);
const char *vk_driver_heap_mode_name(VkDriverHeapMode mode);
