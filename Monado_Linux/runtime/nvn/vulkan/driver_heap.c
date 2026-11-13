// [XCDE] LINUX-070: driver-owned heap avoids whole-heap AMDGPU userptr
// revalidation. Design references: Peiikai/LASRecomp PR71/255 (MIT). This
// helper owns no game data; the caller supplies a fresh reserved address range.
#define _GNU_SOURCE
#include "driver_heap.h"
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <limits.h>

static VkResult fail(char *error, size_t size, VkResult result, const char *why) {
    if (error && size) snprintf(error, size, "%s (VkResult %d)", why, result);
    return result;
}
static void *os_map(void *context, void *address, size_t size, int fd, bool fixed) {
    (void)context;
    int flags = fd >= 0 ? MAP_SHARED : MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE;
    if (fixed) flags |= MAP_FIXED;
    return mmap(address, size, PROT_READ | PROT_WRITE, flags, fd, 0);
}
static int os_unmap(void *context, void *address, size_t size) {
    (void)context; return munmap(address, size);
}
static int os_close(void *context, int fd) { (void)context; return close(fd); }
static const VkDriverHeapMapOps os_ops = {os_map, os_unmap, os_close};
const char *vk_driver_heap_mode_name(VkDriverHeapMode mode) {
    return mode == VK_DRIVER_HEAP_PLACED ? "placed map" : mode == VK_DRIVER_HEAP_DMABUF ? "dma-buf" : "none";
}

VkResult vk_driver_heap_destroy(VkDevice device, VkDriverHeap *out,
                                bool *reservation_ok, char *error, size_t error_size) {
    if (error && error_size) error[0] = 0;
    if (!reservation_ok) return fail(error, error_size, VK_ERROR_INITIALIZATION_FAILED, "missing reservation result");
    *reservation_ok = true;
    if (!out) return fail(error, error_size, VK_ERROR_INITIALIZATION_FAILED, "missing heap ownership");
    if (out->probe_address) {
        bool failed;
        if (out->mode == VK_DRIVER_HEAP_PLACED) {
            VkMemoryUnmapInfoKHR ui = {.sType = VK_STRUCTURE_TYPE_MEMORY_UNMAP_INFO_KHR, .memory = out->memory};
            failed = !out->unmap2 || out->unmap2(device, &ui) != VK_SUCCESS;
        } else failed = !out->map_ops.unmap || out->map_ops.unmap(out->map_context, out->probe_address, (size_t)out->size);
        if (failed) {
            *reservation_ok = false;
            return fail(error, error_size, VK_ERROR_MEMORY_MAP_FAILED, "driver heap probe cleanup failed; ownership retained");
        }
        out->probe_address = NULL;
    }
    if (out->mapped && out->mode == VK_DRIVER_HEAP_PLACED) {
        VkMemoryUnmapInfoKHR ui = {.sType = VK_STRUCTURE_TYPE_MEMORY_UNMAP_INFO_KHR,
            .memory = out->memory, .flags = VK_MEMORY_UNMAP_RESERVE_BIT_EXT};
        VkResult result = out->unmap2 ? out->unmap2(device, &ui) : VK_ERROR_EXTENSION_NOT_PRESENT;
        if (result != VK_SUCCESS) {
            *reservation_ok = false;
            return fail(error, error_size, result, "driver heap unmap failed; ownership retained");
        }
        out->mapped = false;
    }
    if (out->needs_restore) {
        if (!out->map_ops.map || out->map_ops.map(out->map_context, out->address, (size_t)out->size, -1, true) != out->address) {
            *reservation_ok = false;
            return fail(error, error_size, VK_ERROR_MEMORY_MAP_FAILED, "cannot restore anonymous guest reservation; ownership retained");
        }
        out->mapped = out->needs_restore = false;
    }
    if (out->buffer) vkDestroyBuffer(device, out->buffer, NULL);
    if (out->memory) vkFreeMemory(device, out->memory, NULL);
    memset(out, 0, sizeof *out);
    return VK_SUCCESS;
}

static VkResult create_mode(VkPhysicalDevice physical, VkDevice device, void *address,
                             VkDeviceSize size, VkBufferUsageFlags usage,
                             const VkDriverHeapOptions *options, VkDriverHeapMode mode,
                             VkDriverHeap *out, bool *reservation_ok, char *error, size_t error_size) {
    VkDriverHeap h = {.address = address, .size = size, .mode = mode,
        .map_ops = options->map_ops ? *options->map_ops : os_ops, .map_context = options->map_context};
    VkResult result = VK_ERROR_INITIALIZATION_FAILED;
    const char *why = "driver heap allocation failed";
    PFN_vkMapMemory2KHR map2 = NULL;
    PFN_vkGetMemoryFdKHR get_fd = NULL;
    if (mode == VK_DRIVER_HEAP_PLACED) {
        VkDeviceSize alignment = options->map_alignment;
        if (!alignment || (alignment & (alignment - 1)) || (uintptr_t)address % alignment || size % alignment)
            return fail(error, error_size, VK_ERROR_MEMORY_MAP_FAILED, "placed heap address or size alignment");
        map2 = (PFN_vkMapMemory2KHR)vkGetDeviceProcAddr(device, "vkMapMemory2KHR");
        h.unmap2 = (PFN_vkUnmapMemory2KHR)vkGetDeviceProcAddr(device, "vkUnmapMemory2KHR");
        if (!map2 || !h.unmap2)
            return fail(error, error_size, VK_ERROR_EXTENSION_NOT_PRESENT, "placed heap mapping entry points unavailable");
    } else {
        get_fd = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(device, "vkGetMemoryFdKHR");
        if (!get_fd) return fail(error, error_size, VK_ERROR_EXTENSION_NOT_PRESENT, "dma-buf export entry point unavailable");
        VkPhysicalDeviceExternalBufferInfo eq = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO,
            .usage = usage, .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
        VkExternalBufferProperties ep = {.sType = VK_STRUCTURE_TYPE_EXTERNAL_BUFFER_PROPERTIES};
        vkGetPhysicalDeviceExternalBufferProperties(physical, &eq, &ep);
        if (!(ep.externalMemoryProperties.externalMemoryFeatures & VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT) ||
            !(ep.externalMemoryProperties.compatibleHandleTypes & VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT))
            return fail(error, error_size, VK_ERROR_INVALID_EXTERNAL_HANDLE, "buffer usage cannot export dma-buf");
    }
    VkExternalMemoryBufferCreateInfo external = {.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
        .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .pNext = mode == VK_DRIVER_HEAP_DMABUF ? &external : NULL,
        .size = size, .usage = usage, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    result = vkCreateBuffer(device, &bi, NULL, &h.buffer);
    if (result != VK_SUCCESS) { why = "vkCreateBuffer for driver heap"; goto cleanup; }
    VkMemoryDedicatedRequirements dedicated = {.sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_REQUIREMENTS};
    VkMemoryRequirements2 requirements = {.sType = VK_STRUCTURE_TYPE_MEMORY_REQUIREMENTS_2, .pNext = &dedicated};
    VkBufferMemoryRequirementsInfo2 rq = {.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_REQUIREMENTS_INFO_2, .buffer = h.buffer};
    vkGetBufferMemoryRequirements2(device, &rq, &requirements);
    // Mapping the whole allocation must replace exactly the caller's reservation,
    // never adjacent guest regions. memoryMapRangePlaced is not enabled/needed.
    if (requirements.memoryRequirements.size != size ||
        !requirements.memoryRequirements.alignment || size % requirements.memoryRequirements.alignment) {
        result = VK_ERROR_MEMORY_MAP_FAILED; why = "driver heap allocation does not fit the exact reservation"; goto cleanup;
    }
    VkPhysicalDeviceMemoryProperties memory;
    vkGetPhysicalDeviceMemoryProperties(physical, &memory);
    const VkMemoryPropertyFlags need = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT | VK_MEMORY_PROPERTY_HOST_CACHED_BIT;
    const VkMemoryPropertyFlags reject = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT | VK_MEMORY_PROPERTY_PROTECTED_BIT | VK_MEMORY_PROPERTY_DEVICE_COHERENT_BIT_AMD;
    h.memory_type = UINT32_MAX;
    for (uint32_t i = 0; i < memory.memoryTypeCount; ++i) {
        VkMemoryPropertyFlags flags = memory.memoryTypes[i].propertyFlags;
        if ((requirements.memoryRequirements.memoryTypeBits & (1u << i)) && (flags & need) == need && !(flags & reject)) {
            h.memory_type = i; break;
        }
    }
    if (h.memory_type == UINT32_MAX) {
        result = VK_ERROR_FEATURE_NOT_PRESENT; why = "driver heap needs CPU-cached coherent system memory"; goto cleanup;
    }
    VkMemoryDedicatedAllocateInfo ded = {.sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO, .buffer = h.buffer};
    VkExportMemoryAllocateInfo export = {.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO,
        .pNext = &ded, .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
    VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .pNext = mode == VK_DRIVER_HEAP_DMABUF ? (const void *)&export : &ded,
        .allocationSize = size, .memoryTypeIndex = h.memory_type};
    result = vkAllocateMemory(device, &ai, NULL, &h.memory);
    if (result != VK_SUCCESS) { why = "vkAllocateMemory for driver heap"; goto cleanup; }
    h.allocation_size = size;
    result = vkBindBufferMemory(device, h.buffer, h.memory, 0);
    if (result != VK_SUCCESS) { why = "vkBindBufferMemory for driver heap"; goto cleanup; }
    if (mode == VK_DRIVER_HEAP_PLACED) {
        VkMemoryMapInfoKHR mi = {.sType = VK_STRUCTURE_TYPE_MEMORY_MAP_INFO_KHR,
            .memory = h.memory, .size = VK_WHOLE_SIZE};
        VkMemoryUnmapInfoKHR ui = {.sType = VK_STRUCTURE_TYPE_MEMORY_UNMAP_INFO_KHR, .memory = h.memory};
        void *probe = NULL;
        result = map2(device, &mi, &probe);
        if (result != VK_SUCCESS) { why = "driver heap plain mapping probe"; goto cleanup; }
        result = h.unmap2(device, &ui);
        if (result != VK_SUCCESS) { // Cannot free an allocation the driver failed to unmap.
            h.probe_address = probe;
            *out = h; *reservation_ok = false;
            return fail(error, error_size, result, "driver heap probe unmap failed; ownership retained");
        }
        if (!probe) { result = VK_ERROR_MEMORY_MAP_FAILED; why = "driver returned an empty heap mapping"; goto cleanup; }
        VkMemoryMapPlacedInfoEXT placed = {.sType = VK_STRUCTURE_TYPE_MEMORY_MAP_PLACED_INFO_EXT, .pPlacedAddress = address};
        mi.pNext = &placed; mi.flags = VK_MEMORY_MAP_PLACED_BIT_EXT;
        void *mapped = NULL;
        h.needs_restore = true; // Even a refused placed map may replace the reservation.
        result = map2(device, &mi, &mapped);
        if (result == VK_SUCCESS) h.mapped = true;
        if (result != VK_SUCCESS || mapped != address) {
            if (result == VK_SUCCESS) result = VK_ERROR_MEMORY_MAP_FAILED;
            why = "driver heap fixed placed mapping"; goto cleanup;
        }
    } else {
        VkMemoryGetFdInfoKHR fi = {.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR,
            .memory = h.memory, .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
        int fd = -1;
        result = get_fd(device, &fi, &fd);
        if (result != VK_SUCCESS || fd < 0) {
            if (fd >= 0) h.map_ops.close_fd(h.map_context, fd);
            if (result == VK_SUCCESS) result = VK_ERROR_INVALID_EXTERNAL_HANDLE;
            why = "driver heap dma-buf export"; goto cleanup;
        }
        void *probe = h.map_ops.map(h.map_context, NULL, (size_t)size, fd, false);
        if (probe == MAP_FAILED || !probe) {
            h.map_ops.close_fd(h.map_context, fd);
            result = VK_ERROR_MEMORY_MAP_FAILED; why = "dma-buf mapping probe"; goto cleanup;
        }
        if (h.map_ops.unmap(h.map_context, probe, (size_t)size)) {
            h.map_ops.close_fd(h.map_context, fd);
            // Keep the backing alive: a probe mapping could still refer to it.
            h.probe_address = probe;
            *out = h; *reservation_ok = false;
            return fail(error, error_size, VK_ERROR_MEMORY_MAP_FAILED, "dma-buf probe unmap failed; ownership retained");
        }
        h.needs_restore = true;
        void *mapped = h.map_ops.map(h.map_context, address, (size_t)size, fd, true);
        h.map_ops.close_fd(h.map_context, fd);
        if (mapped == MAP_FAILED || mapped != address) {
            result = VK_ERROR_MEMORY_MAP_FAILED; why = "driver heap fixed dma-buf mapping"; goto cleanup;
        }
        h.mapped = true;
    }
    memset(address, 0, (size_t)size);
    *out = h;
    return VK_SUCCESS;
cleanup:
    {
        char saved[192]; snprintf(saved, sizeof saved, "%s", why);
        VkResult cleanup_result = vk_driver_heap_destroy(device, &h, reservation_ok, error, error_size);
        if (cleanup_result != VK_SUCCESS) { *out = h; return cleanup_result; }
        return fail(error, error_size, result, saved);
    }
}

VkResult vk_driver_heap_create(VkPhysicalDevice physical, VkDevice device,
                               void *address, VkDeviceSize size, VkBufferUsageFlags usage,
                               const VkDriverHeapOptions *options, VkDriverHeap *out,
                               bool *reservation_ok, char *error, size_t error_size) {
    if (error && error_size) error[0] = 0;
    if (!reservation_ok) return fail(error, error_size, VK_ERROR_INITIALIZATION_FAILED, "missing reservation result");
    *reservation_ok = true;
    long page = sysconf(_SC_PAGESIZE);
    if (!options || !out || !address || !size || !usage || page <= 0 ||
        size > SIZE_MAX || size > UINTPTR_MAX - (uintptr_t)address ||
        (uintptr_t)address % (unsigned long)page || size % (unsigned long)page ||
        out->buffer || out->memory || out->size || out->mode || out->mapped || out->needs_restore || out->probe_address ||
        (options->map_ops && (!options->map_ops->map || !options->map_ops->unmap || !options->map_ops->close_fd)))
        return fail(error, error_size, VK_ERROR_INITIALIZATION_FAILED, "invalid or occupied driver heap arguments");
    if (!options->placed && !options->dmabuf)
        return fail(error, error_size, VK_ERROR_EXTENSION_NOT_PRESENT, "no driver heap mapping capability");
    VkResult result = VK_ERROR_EXTENSION_NOT_PRESENT;
    if (options->placed) {
        result = create_mode(physical, device, address, size, usage, options, VK_DRIVER_HEAP_PLACED,
                              out, reservation_ok, error, error_size);
        if (result == VK_SUCCESS || !*reservation_ok) return result;
    }
    if (options->dmabuf)
        result = create_mode(physical, device, address, size, usage, options, VK_DRIVER_HEAP_DMABUF,
                              out, reservation_ok, error, error_size);
    return result;
}
