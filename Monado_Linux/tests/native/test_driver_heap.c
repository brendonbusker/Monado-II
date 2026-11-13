// [XCDE] LINUX-070: authored small-range failure tests, no game data.
#define _GNU_SOURCE
#include "../../runtime/nvn/vulkan/driver_heap.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %d: %s\n", __LINE__, #x); abort(); } } while (0)
static VkMemoryPropertyFlags types[4];
static VkDeviceSize required, capacity = 8192;
static uint32_t bits, selected;
static int creates, destroys, allocates, frees, binds, closes, restores, probes, placed_maps;
static int fail_create, fail_alloc, fail_bind, fail_export, fail_probe, fail_fixed, fail_restore, fail_plain_unmap;
static int no_map_entry, no_fd_entry, no_export, wrong_placed, requirement_dedicated;
static int fail_probe_unmap, backing_fd, last_export_fd, fail_placed_fixed, incompatible_export;
static VkDriverHeapMode creating_mode;
static void *driver_mapping;
static void reset(void) {
    memset(types, 0, sizeof types);
    types[0] = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT | VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
    types[1] = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    types[2] = types[1] | VK_MEMORY_PROPERTY_HOST_CACHED_BIT;
    types[3] = types[2] | VK_MEMORY_PROPERTY_PROTECTED_BIT;
    required = capacity; bits = 15; selected = UINT32_MAX;
    creates = destroys = allocates = frees = binds = closes = restores = probes = placed_maps = 0;
    fail_create = fail_alloc = fail_bind = fail_export = fail_probe = fail_fixed = fail_restore = fail_plain_unmap = 0;
    no_map_entry = no_fd_entry = no_export = wrong_placed = requirement_dedicated = 0;
    creating_mode = VK_DRIVER_HEAP_NONE; driver_mapping = NULL;
    fail_probe_unmap = fail_placed_fixed = incompatible_export = 0; backing_fd = last_export_fd = -1;
}
static void *map_pages(void *ctx, void *address, size_t size, int fd, bool fixed) {
    (void)ctx; CHECK(size == capacity);
    if (fd < 0) { restores++; CHECK(fixed); if (fail_restore) return MAP_FAILED; }
    else if (!fixed) { probes++; if (fail_probe) return MAP_FAILED; }
    else if (fail_fixed) { CHECK(munmap(address, size) == 0); return MAP_FAILED; }
    return mmap(address, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | (fixed ? MAP_FIXED : 0), -1, 0);
}
static int unmap_pages(void *ctx, void *address, size_t size) { (void)ctx; return fail_probe_unmap ? -1 : munmap(address, size); }
static int close_fd(void *ctx, int fd) { (void)ctx; CHECK(fd == 0); closes++; return 0; }
static const VkDriverHeapMapOps ops = {map_pages, unmap_pages, close_fd};
static VkDriverHeapOptions options(bool placed, bool dma) {
    return (VkDriverHeapOptions){.placed = placed, .dmabuf = dma, .map_alignment = 4096, .map_ops = &ops};
}
VKAPI_ATTR VkResult VKAPI_CALL fake_map2(VkDevice d, const VkMemoryMapInfo *mi, void **out) {
    (void)d; CHECK(mi->memory && mi->offset == 0 && mi->size == VK_WHOLE_SIZE);
    if (!(mi->flags & VK_MEMORY_MAP_PLACED_BIT_EXT)) {
        if (fail_probe) return VK_ERROR_MEMORY_MAP_FAILED;
        driver_mapping = mmap(NULL, capacity, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    } else {
        const VkMemoryMapPlacedInfoEXT *p = mi->pNext; placed_maps++;
        CHECK(p && p->sType == VK_STRUCTURE_TYPE_MEMORY_MAP_PLACED_INFO_EXT);
        if (fail_fixed || fail_placed_fixed) { CHECK(munmap(p->pPlacedAddress, capacity) == 0); return VK_ERROR_MEMORY_MAP_FAILED; }
        driver_mapping = mmap(wrong_placed ? NULL : p->pPlacedAddress, capacity, PROT_READ | PROT_WRITE,
            MAP_PRIVATE | MAP_ANONYMOUS | (wrong_placed ? 0 : MAP_FIXED), -1, 0);
    }
    CHECK(driver_mapping != MAP_FAILED); *out = driver_mapping; return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL fake_unmap2(VkDevice d, const VkMemoryUnmapInfo *ui) {
    (void)d; CHECK(ui->memory && driver_mapping);
    if (fail_plain_unmap && !ui->flags) return VK_ERROR_MEMORY_MAP_FAILED;
    CHECK(ui->flags == 0 || ui->flags == VK_MEMORY_UNMAP_RESERVE_BIT_EXT);
    CHECK(munmap(driver_mapping, capacity) == 0); driver_mapping = NULL; return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL fake_get_fd(VkDevice d, const VkMemoryGetFdInfoKHR *fi, int *fd) {
    (void)d; CHECK(fi->memory && fi->handleType == VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT);
    if (fail_export) return VK_ERROR_INVALID_EXTERNAL_HANDLE;
    *fd = backing_fd >= 0 ? (last_export_fd = dup(backing_fd)) : 0; CHECK(*fd >= 0); return VK_SUCCESS; // FD zero is valid and must be closed.
}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice d, const char *name) {
    (void)d;
    if (!strcmp(name, "vkMapMemory2KHR")) return no_map_entry ? NULL : (PFN_vkVoidFunction)fake_map2;
    if (!strcmp(name, "vkUnmapMemory2KHR")) return no_map_entry ? NULL : (PFN_vkVoidFunction)fake_unmap2;
    CHECK(!strcmp(name, "vkGetMemoryFdKHR")); return no_fd_entry ? NULL : (PFN_vkVoidFunction)fake_get_fd;
}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceExternalBufferProperties(VkPhysicalDevice d, const VkPhysicalDeviceExternalBufferInfo *q, VkExternalBufferProperties *out) {
    (void)d; CHECK(q->usage == VK_BUFFER_USAGE_STORAGE_BUFFER_BIT);
    out->externalMemoryProperties.externalMemoryFeatures = no_export ? 0 : VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT;
    out->externalMemoryProperties.compatibleHandleTypes = incompatible_export ? 0 : VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT;
}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice d, VkPhysicalDeviceMemoryProperties *out) {
    (void)d; memset(out, 0, sizeof *out); out->memoryTypeCount = 4;
    for (int i = 0; i < 4; ++i) out->memoryTypes[i].propertyFlags = types[i];
}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateBuffer(VkDevice d, const VkBufferCreateInfo *bi, const VkAllocationCallbacks *a, VkBuffer *out) {
    (void)d; (void)a; CHECK(bi->size == capacity && bi->usage == VK_BUFFER_USAGE_STORAGE_BUFFER_BIT); creates++;
    creating_mode = bi->pNext ? VK_DRIVER_HEAP_DMABUF : VK_DRIVER_HEAP_PLACED;
    if (bi->pNext) CHECK(((const VkExternalMemoryBufferCreateInfo *)bi->pNext)->handleTypes == VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT);
    if (fail_create) return VK_ERROR_OUT_OF_DEVICE_MEMORY; *out = (VkBuffer)(uintptr_t)creates; return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL vkGetBufferMemoryRequirements2(VkDevice d, const VkBufferMemoryRequirementsInfo2 *q, VkMemoryRequirements2 *out) {
    (void)d; CHECK(q->buffer); out->memoryRequirements = (VkMemoryRequirements){required, 4096, bits};
    ((VkMemoryDedicatedRequirements *)out->pNext)->requiresDedicatedAllocation = requirement_dedicated;
}
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateMemory(VkDevice d, const VkMemoryAllocateInfo *ai, const VkAllocationCallbacks *a, VkDeviceMemory *out) {
    (void)d; (void)a; CHECK(ai->allocationSize == capacity); selected = ai->memoryTypeIndex; allocates++;
    const VkMemoryDedicatedAllocateInfo *ded = ai->pNext;
    if (creating_mode == VK_DRIVER_HEAP_DMABUF) {
        const VkExportMemoryAllocateInfo *ex = ai->pNext; CHECK(ex->sType == VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO);
        CHECK(ex->handleTypes == VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT); ded = ex->pNext;
    }
    CHECK(ded->sType == VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO && ded->buffer);
    if (fail_alloc) return VK_ERROR_OUT_OF_HOST_MEMORY; *out = (VkDeviceMemory)(uintptr_t)allocates; return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL vkBindBufferMemory(VkDevice d, VkBuffer b, VkDeviceMemory m, VkDeviceSize offset) {
    (void)d; CHECK(b && m && offset == 0); binds++; return fail_bind ? VK_ERROR_OUT_OF_DEVICE_MEMORY : VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL vkDestroyBuffer(VkDevice d, VkBuffer b, const VkAllocationCallbacks *a) { (void)d; (void)a; CHECK(b); destroys++; }
VKAPI_ATTR void VKAPI_CALL vkFreeMemory(VkDevice d, VkDeviceMemory m, const VkAllocationCallbacks *a) { (void)d; (void)a; CHECK(m && destroys > frees); frees++; }
static VkResult create(VkDriverHeapOptions *o, VkDriverHeap *h, void *address, bool *safe, char error[256]) {
    return vk_driver_heap_create((VkPhysicalDevice)(uintptr_t)1, (VkDevice)(uintptr_t)2, address, capacity,
        VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, o, h, safe, error, 256);
}
static void check_empty(VkDriverHeap *h) { CHECK(!h->buffer && !h->memory && !h->size && !h->mode && !h->mapped && !h->needs_restore && !h->probe_address); }
int main(void) {
    long page = sysconf(_SC_PAGESIZE); CHECK(page == 4096);
    uint8_t *range = mmap(NULL, capacity + 2 * page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0); CHECK(range != MAP_FAILED);
    uint8_t *heap = range + page; range[0] = 0xA7; range[page + capacity] = 0xB8;
    VkDriverHeap h = {0}; char error[256]; bool safe; unsigned cases = 0;
    for (int mode = 0; mode < 2; ++mode) {
        reset(); memset(heap, 0xC1, capacity); VkDriverHeapOptions o = options(mode == 0, mode == 1);
        CHECK(create(&o, &h, heap, &safe, error) == VK_SUCCESS && safe && selected == 2);
        CHECK(h.mode == (mode ? VK_DRIVER_HEAP_DMABUF : VK_DRIVER_HEAP_PLACED) && h.size == capacity);
        for (size_t j = 0; j < capacity; ++j) CHECK(heap[j] == 0);
        CHECK(range[0] == 0xA7 && range[page + capacity] == 0xB8);
        memset(heap, 0x55, capacity);
        CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe);
        check_empty(&h); CHECK(destroys == 1 && frees == 1 && restores == 1 && closes == (mode ? 1 : 0));
        CHECK(heap[0] == 0 && heap[capacity - 1] == 0);
        CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && destroys == 1);
        cases++;
    }
    for (int mode = 0; mode < 2; ++mode) for (int kind = 0; kind < 12; ++kind) {
        reset(); VkDriverHeapOptions o = options(mode == 0, mode == 1);
        switch (kind) {
        case 0: fail_create = 1; break;
        case 1: fail_alloc = 1; break;
        case 2: fail_bind = 1; break;
        case 3: fail_probe = 1; break;
        case 4: fail_fixed = 1; break;
        case 5: required += page; break;
        case 6: bits = 3; break; // cached memory not usable by the buffer
        case 7: types[2] &= ~VK_MEMORY_PROPERTY_HOST_COHERENT_BIT; break;
        case 8: types[2] |= VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT; break;
        case 9: types[2] |= VK_MEMORY_PROPERTY_DEVICE_COHERENT_BIT_AMD; break;
        case 10: if (mode) fail_export = 1; else no_map_entry = 1; break;
        case 11: if (mode) no_export = 1; else o.map_alignment = 16384; break;
        }
        CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && safe && error[0]); check_empty(&h);
        CHECK(destroys == creates - fail_create && frees == allocates - fail_alloc);
        if (kind == 4) CHECK(restores == 1);
        CHECK(range[0] == 0xA7 && range[page + capacity] == 0xB8);
        heap[0] = 0x5A; CHECK(heap[0] == 0x5A); cases++;
    }
    reset(); VkDriverHeapOptions o = options(true, true); no_map_entry = 1;
    CHECK(create(&o, &h, heap, &safe, error) == VK_SUCCESS && h.mode == VK_DRIVER_HEAP_DMABUF);
    CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS); cases++;
    reset(); o = options(false, false); CHECK(create(&o, &h, heap, &safe, error) == VK_ERROR_EXTENSION_NOT_PRESENT && safe && !creates); cases++;
    reset(); o = options(true, false); requirement_dedicated = 1;
    CHECK(create(&o, &h, heap, &safe, error) == VK_SUCCESS); fail_restore = 1;
    CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) != VK_SUCCESS && !safe && h.memory && !frees);
    fail_restore = 0; CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe); cases++;
    reset(); o = options(false, true); fail_fixed = fail_restore = 1;
    CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && !safe && h.memory && !frees);
    fail_restore = 0; CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe); cases++;
    reset(); o = options(true, false); wrong_placed = 1;
    CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && safe && restores == 1 && !driver_mapping); cases++;
    reset(); o = options(false, true); no_fd_entry = 1;
    CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && safe && !creates); cases++;
    reset(); o = options(true, false); CHECK(create(&o, &h, heap + 1, &safe, error) != VK_SUCCESS && safe && !creates); cases++;
    for (int mode = 0; mode < 2; ++mode) {
        reset(); o = options(mode == 0, mode == 1);
        if (mode) fail_probe_unmap = 1; else fail_plain_unmap = 1;
        CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && !safe && h.memory && h.probe_address && !frees);
        fail_probe_unmap = fail_plain_unmap = 0;
        CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe);
        check_empty(&h); cases++;
    }
    reset(); o = options(true, true); fail_placed_fixed = 1;
    CHECK(create(&o, &h, heap, &safe, error) == VK_SUCCESS && safe && h.mode == VK_DRIVER_HEAP_DMABUF);
    CHECK(restores == 1 && creates == 2 && destroys == 1 && frees == 1);
    CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe && restores == 2); cases++;
    reset(); o = options(false, true); incompatible_export = 1;
    CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && safe && !creates); cases++;
    reset(); o = options(true, false); types[2] |= VK_MEMORY_PROPERTY_PROTECTED_BIT;
    CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && safe && !allocates); cases++;
    reset(); o = options(true, false); CHECK(create(&o, &h, heap, &safe, error) == VK_SUCCESS);
    VkBuffer prior = h.buffer; CHECK(create(&o, &h, heap, &safe, error) != VK_SUCCESS && safe && h.buffer == prior && creates == 1 && !frees);
    CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe); cases++;
    // Real POSIX mapping path: exported fd is a small authored memfd. This tests
    // actual MAP_SHARED/fixed replacement, close, and anonymous restoration.
    reset(); o = options(false, true); o.map_ops = NULL;
    backing_fd = memfd_create("monado-authored-heap-test", MFD_CLOEXEC); CHECK(backing_fd >= 0);
    CHECK(ftruncate(backing_fd, capacity) == 0);
    uint8_t marker = 0x77; CHECK(pwrite(backing_fd, &marker, 1, 0) == 1);
    CHECK(create(&o, &h, heap, &safe, error) == VK_SUCCESS && safe);
    CHECK(fcntl(last_export_fd, F_GETFD) < 0 && errno == EBADF);
    CHECK(pread(backing_fd, &marker, 1, 0) == 1 && marker == 0);
    heap[0] = 0x42; CHECK(pread(backing_fd, &marker, 1, 0) == 1 && marker == 0x42);
    CHECK(vk_driver_heap_destroy((VkDevice)(uintptr_t)2, &h, &safe, error, 256) == VK_SUCCESS && safe);
    heap[0] = 0x13; CHECK(pread(backing_fd, &marker, 1, 0) == 1 && marker == 0x42);
    CHECK(close(backing_fd) == 0); cases++;
    CHECK(range[0] == 0xA7 && range[page + capacity] == 0xB8);
    CHECK(munmap(range, capacity + 2 * page) == 0);
    printf("driver heap: %u authored cases PASS\n", cases);
}
