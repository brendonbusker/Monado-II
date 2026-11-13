// [XCDE] LINUX-070: controlled backends execute actual kernel/renderer integration.
#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include "host_import.h"
#include "driver_heap.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); abort(); } } while (0)
#define LOG(...) ((void)0)
#define FATAL(...) do { fprintf(stderr,__VA_ARGS__); _Exit(86); } while (0)
#define HEAP_BASE 0x7240000000ull
#define HEAP_MAX 0xD0000000ull
#define VC_TAB 2
#define VC_PAGE 4096
#undef R_OK
#define R_OK 0
#define R_OUT_OF_RESOURCE 0xD001

typedef struct { uint64_t x[32]; } Cpu;
static struct {
    VkPhysicalDevice phys; VkDevice dev; void *vma;
    bool radv, host_import, heap_placed, heap_dmabuf;
    uint64_t heap_map_alignment;
    struct { struct { uint32_t maxStorageBufferRange; } limits; } props;
} g_vk;
static VkHostImport gmem;
static VkDriverHeap driver_heap;
static pthread_mutex_t guest_heap_lock = PTHREAD_MUTEX_INITIALIZER;
static bool guest_heap_decided;
static uint64_t heap_size, gmem_tried;
static int backend_calls, creates, driver_destroys, import_destroys, imports, flushes, regions;
static int tmp_calls;
static bool fail_create, reservation_restored = true, fail_destroy;
static uint64_t expected_old_heap;
static uint64_t kernel_heap_size(void) { return heap_size; }
void backend_init(void) { CHECK(heap_size == expected_old_heap); backend_calls++; }
static void renderer_flush(void) { flushes++; }
static void region_remove(uint64_t a) { CHECK(a == HEAP_BASE); }
static void region_add(uint64_t a,uint64_t n,int type,int perm) {
    CHECK(a == HEAP_BASE && n == heap_size && type == 5 && perm == 3);
    CHECK(guest_heap_decided); regions++;
}
#define diag_use(...) ((void)0)

VkResult vk_driver_heap_create(VkPhysicalDevice p,VkDevice d,void *a,VkDeviceSize n,VkBufferUsageFlags usage,
    const VkDriverHeapOptions *o,VkDriverHeap *out,bool *ok,char *error,size_t error_size) {
    (void)p; (void)d; snprintf(error,error_size,"injected create response");
    CHECK(heap_size == expected_old_heap && !gmem.buffer && !out->buffer);
    CHECK(a == (void*)(uintptr_t)HEAP_BASE && n == HEAP_MAX);
    CHECK(usage & VK_BUFFER_USAGE_STORAGE_BUFFER_BIT); CHECK(o->placed && o->dmabuf);
    creates++; *ok = reservation_restored;
    if (fail_create) return VK_ERROR_OUT_OF_HOST_MEMORY;
    *out=(VkDriverHeap){.buffer=(VkBuffer)(uintptr_t)0x100,.memory=(VkDeviceMemory)(uintptr_t)0x200,
        .size=n,.allocation_size=n,.memory_type=5,.address=a,.mode=VK_DRIVER_HEAP_PLACED};
    memset(a,0,65536); return VK_SUCCESS;
}
VkResult vk_driver_heap_destroy(VkDevice d,VkDriverHeap *out,bool *ok,char *error,size_t error_size) {
    (void)d; snprintf(error,error_size,"injected destroy response"); CHECK(out->buffer && out->memory);
    CHECK(gmem.buffer == out->buffer && !gmem.memory); driver_destroys++;
    if (fail_destroy) { *ok=false; return VK_ERROR_OUT_OF_HOST_MEMORY; }
    memset(out,0,sizeof *out); *ok=true; return VK_SUCCESS;
}
const char *vk_driver_heap_mode_name(VkDriverHeapMode mode) { (void)mode; return "fake placed"; }
VkResult vk_host_import_buffer(VkPhysicalDevice p,VkDevice d,void *host,VkDeviceSize accessible,
    VkDeviceSize n,VkBufferUsageFlags usage,VkHostImport *out,char *error,size_t error_size) {
    (void)p;(void)d;(void)usage;(void)error;(void)error_size;
    CHECK(!out->buffer && !driver_heap.buffer && host==(void*)(uintptr_t)HEAP_BASE && accessible==HEAP_MAX);
    imports++; *out=(VkHostImport){.buffer=(VkBuffer)(uintptr_t)0x300,.memory=(VkDeviceMemory)(uintptr_t)0x400,
        .size=n,.allocation_size=n}; return VK_SUCCESS;
}
void vk_host_import_destroy(VkDevice d,VkHostImport *out) {
    (void)d; CHECK(!driver_heap.buffer);
    if (out->buffer) { CHECK(out->memory == (VkDeviceMemory)(uintptr_t)0x400); import_destroys++; }
    memset(out,0,sizeof *out);
}
// Unrelated reset dependencies: the complete production reset function is used.
static void tmp_exec_reset(void) { tmp_calls++; }
static void tmp_reset(void) { tmp_calls++; }
static struct { int cap,n; int *e; } prog_tab,pipe_tab;
static int prog_tab_gen,g_cs_n,gcopy_gen,nwant,nxsh,vc_npend,vc_epoch;
static uint64_t vc_bytes;
static struct { VkBuffer buf; void *mem; } xsh[1],vc_tab[VC_TAB];
static void *vc_page_gpu;
static void vmaDestroyBuffer(void *vma,VkBuffer b,void *m) { (void)vma;(void)b;(void)m; abort(); }
static void vc_free_dead(bool yes) { CHECK(yes); }
static void st_defaults(void) {}
#include "heap_integration_source.h"
#include "set_heap_source.h"

static void clear_state(bool radv) {
    CHECK(!driver_heap.buffer && !gmem.buffer);
    memset(&g_vk,0,sizeof g_vk); g_vk.radv=radv; g_vk.host_import=true;
    g_vk.heap_placed=g_vk.heap_dmabuf=true; g_vk.heap_map_alignment=65536;
    g_vk.props.limits.maxStorageBufferRange=UINT32_MAX;
    heap_size=0;guest_heap_decided=false;backend_calls=creates=driver_destroys=import_destroys=imports=flushes=regions=tmp_calls=0;
    fail_create=fail_destroy=false;reservation_restored=true;expected_old_heap=0;
    unsetenv("XCDE_VK_HEAP"); unsetenv("LARECOMP_VK_NO_GMEM");
}
static Cpu heap_request(uint64_t n) {
    Cpu c={0};c.x[1]=n;set_heap(&c);return c;
}
static void expect_fatal(int kind) {
    pid_t pid=fork();CHECK(pid>=0);
    if (!pid) {
        alarm(5);
        if (kind==1) { fail_create=true;reservation_restored=false;heap_request(65536); }
        if (kind==2) { heap_request(65536);heap_size=131072;(void)gmem_info(); }
        if (kind==3) { heap_request(65536);fail_destroy=true;vk_exec_reset(); }
        if (kind==4) { setenv("XCDE_VK_HEAP","invalid",1);heap_request(65536); }
        _Exit(1);
    }
    int status;CHECK(waitpid(pid,&status,0)==pid);CHECK(WIFEXITED(status)&&WEXITSTATUS(status)==86);
}
int main(void) {
    void *mapping=mmap((void*)(uintptr_t)HEAP_BASE,65536,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    CHECK(mapping==(void*)(uintptr_t)HEAP_BASE);
    clear_state(true);
    Cpu c=heap_request(0);CHECK(c.x[0]==R_OK&&c.x[1]==HEAP_BASE);
    CHECK(!backend_calls&&!creates&&!guest_heap_decided&&!regions);
    c=heap_request(HEAP_MAX+1);CHECK(c.x[0]==R_OUT_OF_RESOURCE&&!backend_calls&&!creates);

    clear_state(false);setenv("XCDE_VK_HEAP","invalid",1);c=heap_request(65536);
    CHECK(c.x[0]==R_OK&&heap_size==65536&&guest_heap_decided&&backend_calls==1&&!creates);
    VkDescriptorBufferInfo view=gmem_info();CHECK(imports==1&&view.range==65536);
    heap_size=131072;gmem_prepare_command();CHECK(flushes==1&&import_destroys==1&&imports==2);
    vk_exec_reset();CHECK(import_destroys==2&&!guest_heap_decided);

    clear_state(true);setenv("XCDE_VK_HEAP","import",1);heap_request(65536);
    CHECK(!creates&&!gmem.buffer&&guest_heap_decided);view=gmem_info();CHECK(imports==1);
    vk_exec_reset();CHECK(import_destroys==1);

    clear_state(true);g_vk.host_import=false;heap_request(65536);
    CHECK(creates==1&&backend_calls==1&&gmem.buffer==driver_heap.buffer&&!gmem.memory);
    view=gmem_info();CHECK(view.range==65536&&view.buffer==driver_heap.buffer&&!imports);
    volatile uint64_t *word=(volatile uint64_t*)(uintptr_t)(HEAP_BASE+8192);*word=0x123456789abcdef0ull;
    expected_old_heap=65536;heap_request(131072);
    CHECK(creates==1&&backend_calls==1&&*word==0x123456789abcdef0ull);
    gmem_prepare_command();view=gmem_info();CHECK(view.range==131072&&!flushes&&!import_destroys&&!imports);
    CHECK(*word==0x123456789abcdef0ull);heap_request(65536);gmem_prepare_command();
    CHECK(gmem_info().range==131072); // Existing grow-only descriptor behavior is retained.
    vk_exec_reset();CHECK(driver_destroys==1&&!import_destroys&&!gmem.buffer&&!driver_heap.buffer&&!guest_heap_decided);
    CHECK(tmp_calls==2);
    heap_size=0;expected_old_heap=0;heap_request(65536);CHECK(creates==2&&backend_calls==2);
    vk_exec_reset();CHECK(driver_destroys==2&&!import_destroys);

    clear_state(true);fail_create=true;heap_request(65536);
    CHECK(creates==1&&!driver_heap.buffer&&!gmem.buffer&&guest_heap_decided);
    view=gmem_info();CHECK(imports==1&&view.range==65536);vk_exec_reset();CHECK(import_destroys==1);

    clear_state(true);expect_fatal(1);expect_fatal(2);expect_fatal(3);expect_fatal(4);
    CHECK(!creates&&!gmem.buffer&&!driver_heap.buffer&&!guest_heap_decided);
    CHECK(munmap(mapping,65536)==0);
    puts("heap lifecycle contracts: PASS");return 0;
}
