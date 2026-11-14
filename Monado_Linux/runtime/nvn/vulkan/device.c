// Vulkan device, window, swapchain and presentation (counterpart of the window/present half of metal.m).
#include "../../diag/diag.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_vulkan.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../../paths.h"
#include "../../settings.h"
#include "../../host/xcde_aspect.h" // [XCDE] LINUX-089
#include "../../ui/menu.h"
#include "../../host/applet_lifecycle_ui.h"  // [XCDE] LINUX-007: honor guest exit cleanup
#include "vk.h"
#include "dlss.h"
#include "../output_scale.h"
#include "../renderer.h"
#ifdef __linux__
#include "pipeline_cache_io.h"  // [XCDE] LINUX-018
#include "radv_dcc_compat.h"  // [XCDE] LINUX-075: prepared before graphics init
#endif
#include "../../env_cache.h"  // (last: cached getenv)

VkG g_vk;
static SDL_Window *window;
static atomic_bool ui_ready;
static VkDebugUtilsMessengerEXT messenger;

// ================================================================== instance / device
static VKAPI_ATTR VkBool32 VKAPI_CALL debug_cb(VkDebugUtilsMessageSeverityFlagBitsEXT sev, VkDebugUtilsMessageTypeFlagsEXT type,
                                               const VkDebugUtilsMessengerCallbackDataEXT *d, void *user) {
    (void)type, (void)user;
    if (sev < VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT) return VK_FALSE;
    // [XCDE] T151: each distinct message id once (with its first text) and how often it repeats, so one run shows every
    // kind of problem instead of 500 copies of the first one
    static struct { int32_t id; uint64_t n; } seen[512];
    static int nseen;
    static pthread_mutex_t lk = PTHREAD_MUTEX_INITIALIZER;
    pthread_mutex_lock(&lk);
    int i = 0;
    while (i < nseen && seen[i].id != d->messageIdNumber) i++;
    if (i == nseen && nseen < 512) { seen[nseen].id = d->messageIdNumber; seen[nseen].n = 0; nseen++; }
    uint64_t n = i < 512 ? ++seen[i].n : 0;
    pthread_mutex_unlock(&lk);
    static int all = -1;  // [XCDE] spec_lowend_gpu R2: XCDE_VALIDATION_ALL=<n> logs the first n of each id in full
    if (all < 0) all = getenv("XCDE_VALIDATION_ALL") ? atoi(getenv("XCDE_VALIDATION_ALL")) : 0;
    if (n == 1) LOG("[validation] NEW %s: %s\n", d->pMessageIdName ? d->pMessageIdName : "?", d->pMessage);
    else if (n <= (uint64_t)all) LOG("[validation] #%llu %s: %s\n", (unsigned long long)n, d->pMessageIdName ? d->pMessageIdName : "?", d->pMessage);
    else if (n == 100 || n == 10000) LOG("[validation] %s seen %llu times\n", d->pMessageIdName ? d->pMessageIdName : "?", (unsigned long long)n);
    return VK_FALSE;
}

// LARECOMP_VK_VALIDATION=1: Khronos validation layer (MSYS2 package vulkan-validation-layers)
static void create_instance(void) {
    Uint32 n_sdl = 0;
    const char *const *sdl_ext = SDL_Vulkan_GetInstanceExtensions(&n_sdl);
    const char *ext[32];
    uint32_t n_ext = 0;
    for (Uint32 i = 0; i < n_sdl && n_ext < 14; i++) ext[n_ext++] = sdl_ext[i];
    bool validate = getenv("LARECOMP_VK_VALIDATION") != NULL;
    if (validate) ext[n_ext++] = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
    {   // [XCDE] DLSS (dlss.cpp): Streamline's instance extensions
        extern int dlss_instance_exts(const char **out, int max);
        const char *dx[8];
        int nd = dlss_instance_exts(dx, 8);
        for (int i = 0; i < nd && n_ext < 32; i++) {
            bool dup = false;
            for (uint32_t j = 0; j < n_ext; j++) dup |= !strcmp(ext[j], dx[i]);
            if (!dup) ext[n_ext++] = dx[i];
        }
    }
    const char *layers[] = {"VK_LAYER_KHRONOS_validation"};
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "LARecomp",
                             .pEngineName = "LARecomp", .apiVersion = VK_API_VERSION_1_3};
    VkInstanceCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app,
                               .enabledExtensionCount = n_ext, .ppEnabledExtensionNames = ext,
                               .enabledLayerCount = validate ? 1 : 0, .ppEnabledLayerNames = layers};
    VkResult r = vkCreateInstance(&ci, NULL, &g_vk.inst);
    if (r != VK_SUCCESS && validate) {
        LOG("[vk] validation layer unavailable (%d); continuing without\n", r);
        ci.enabledLayerCount = 0;
        // [XCDE] LINUX-017: debug extension is not necessarily last after NGX.
        for (uint32_t i = 0; i < ci.enabledExtensionCount; i++)
            if (!strcmp(ext[i], VK_EXT_DEBUG_UTILS_EXTENSION_NAME)) {
                memmove(ext + i, ext + i + 1, (--ci.enabledExtensionCount - i) * sizeof *ext); break;
            }
        validate = false;
        r = vkCreateInstance(&ci, NULL, &g_vk.inst);
    }
    if (r != VK_SUCCESS) FATAL("vkCreateInstance: %d (is a Vulkan 1.3 driver installed?)\n", r);
    if (validate) {
        PFN_vkCreateDebugUtilsMessengerEXT f =
            (PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(g_vk.inst, "vkCreateDebugUtilsMessengerEXT");
        VkDebugUtilsMessengerCreateInfoEXT mi = {
            .sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT,
            .messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT,
            .messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT |
                           VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT,
            .pfnUserCallback = debug_cb};
        if (f) f(g_vk.inst, &mi, NULL, &messenger);
    }
}

static bool has_ext(VkExtensionProperties *e, uint32_t n, const char *name) {
    for (uint32_t i = 0; i < n; i++) if (!strcmp(e[i].extensionName, name)) return true;
    return false;
}

// Discrete GPU first (LARECOMP_GPU=<index> picks one), needs Vulkan 1.3 and a queue that can present.
static void pick_device(void) {
    uint32_t n = 0;
    vkEnumeratePhysicalDevices(g_vk.inst, &n, NULL);
    if (!n) FATAL("no Vulkan device\n");
    VkPhysicalDevice *pd = calloc(n, sizeof *pd);
    vkEnumeratePhysicalDevices(g_vk.inst, &n, pd);
    int want = getenv("LARECOMP_GPU") ? atoi(getenv("LARECOMP_GPU")) : -1, best = -1, best_score = -1;
    for (uint32_t i = 0; i < n; i++) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(pd[i], &p);
        LOG("[vk] gpu %u: %s (api %u.%u.%u)\n", i, p.deviceName, VK_API_VERSION_MAJOR(p.apiVersion),
            VK_API_VERSION_MINOR(p.apiVersion), VK_API_VERSION_PATCH(p.apiVersion));
        if (p.apiVersion < VK_API_VERSION_1_3) continue;
        int score = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 3 : p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? 2 : 1;
        if ((int)i == want) score = 100;
        if (score > best_score) { best_score = score; best = (int)i; }
    }
    if (best < 0) FATAL("no Vulkan 1.3 device\n");
    g_vk.phys = pd[best];
    free(pd);
    vkGetPhysicalDeviceProperties(g_vk.phys, &g_vk.props);
    uint32_t nq = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &nq, NULL);
    VkQueueFamilyProperties *qp = calloc(nq, sizeof *qp);
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &nq, qp);
    g_vk.qfam = UINT32_MAX;
    for (uint32_t i = 0; i < nq; i++) {
        VkBool32 present = VK_FALSE;
        vkGetPhysicalDeviceSurfaceSupportKHR(g_vk.phys, i, g_vk.surface, &present);
        if ((qp[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) && (qp[i].queueFlags & VK_QUEUE_COMPUTE_BIT) && present) { g_vk.qfam = i; break; }
    }
    free(qp);
    if (g_vk.qfam == UINT32_MAX) FATAL("no graphics+present queue\n");
    LOG("[vk] using %s\n", g_vk.props.deviceName);
}

static bool g_fault_ext;
// After VK_ERROR_DEVICE_LOST: what the driver says faulted (VK_EXT_device_fault), into the log.
void vk_device_fault_report(void) {
    static int once;
    if (once++ || !g_fault_ext) return;
    PFN_vkGetDeviceFaultInfoEXT get = (PFN_vkGetDeviceFaultInfoEXT)vkGetDeviceProcAddr(g_vk.dev, "vkGetDeviceFaultInfoEXT");
    if (!get) return;
    VkDeviceFaultCountsEXT c = {.sType = VK_STRUCTURE_TYPE_DEVICE_FAULT_COUNTS_EXT};
    if (get(g_vk.dev, &c, NULL) != VK_SUCCESS) { LOG("[vk] device fault: no info\n"); return; }
    VkDeviceFaultAddressInfoEXT addr[16];
    VkDeviceFaultVendorInfoEXT vend[16];
    if (c.addressInfoCount > 16) c.addressInfoCount = 16;
    if (c.vendorInfoCount > 16) c.vendorInfoCount = 16;
    c.vendorBinarySize = 0;
    VkDeviceFaultInfoEXT info = {.sType = VK_STRUCTURE_TYPE_DEVICE_FAULT_INFO_EXT, .pAddressInfos = addr, .pVendorInfos = vend};
    if (get(g_vk.dev, &c, &info) != VK_SUCCESS && 0) return;
    LOG("[vk] device fault: %s\n", info.description);
    static const char *const kind[] = {"none", "read invalid", "write invalid", "execute invalid", "ip unknown", "ip invalid", "ip valid"};
    for (uint32_t i = 0; i < c.addressInfoCount; i++)
        LOG("[vk]   address %s %#llx (precision %#llx)\n", addr[i].addressType < 7 ? kind[addr[i].addressType] : "?",
            (unsigned long long)addr[i].reportedAddress, (unsigned long long)addr[i].addressPrecision);
    for (uint32_t i = 0; i < c.vendorInfoCount; i++)
        LOG("[vk]   vendor: %s (code %#llx data %#llx)\n", vend[i].description, (unsigned long long)vend[i].vendorFaultCode,
            (unsigned long long)vend[i].vendorFaultData);
}

// [XCDE] Swapchain calls through Streamline's proxies while DLSS is loaded (dlss.cpp: its manual hooking mode
// intercepts these); otherwise Vulkan's own.
static PFN_vkCreateSwapchainKHR sc_create = vkCreateSwapchainKHR;
static PFN_vkDestroySwapchainKHR sc_destroy = vkDestroySwapchainKHR;
static PFN_vkGetSwapchainImagesKHR sc_images = vkGetSwapchainImagesKHR;
static PFN_vkAcquireNextImageKHR sc_acquire = vkAcquireNextImageKHR;
static PFN_vkQueuePresentKHR sc_present = vkQueuePresentKHR;
static PFN_vkDeviceWaitIdle sc_wait_idle = vkDeviceWaitIdle;
static void sc_proxies(void) {
    extern PFN_vkVoidFunction dlss_proxy(VkDevice dev, const char *name);
    PFN_vkVoidFunction f;
#define PROXY(var, name) if ((f = dlss_proxy(g_vk.dev, name))) var = (void *)f
    PROXY(sc_create, "vkCreateSwapchainKHR"); PROXY(sc_destroy, "vkDestroySwapchainKHR");
    PROXY(sc_images, "vkGetSwapchainImagesKHR"); PROXY(sc_acquire, "vkAcquireNextImageKHR");
    PROXY(sc_present, "vkQueuePresentKHR"); PROXY(sc_wait_idle, "vkDeviceWaitIdle");
#undef PROXY
}

static void create_device(void) {
    uint32_t ne = 0;
    vkEnumerateDeviceExtensionProperties(g_vk.phys, NULL, &ne, NULL);
    VkExtensionProperties *ep = calloc(ne, sizeof *ep);
    vkEnumerateDeviceExtensionProperties(g_vk.phys, NULL, &ne, ep);
    const char *ext[48];
    uint32_t n_ext = 0;
    ext[n_ext++] = VK_KHR_SWAPCHAIN_EXTENSION_NAME;
    g_vk.custom_border = has_ext(ep, ne, VK_EXT_CUSTOM_BORDER_COLOR_EXTENSION_NAME);
    if (g_vk.custom_border) ext[n_ext++] = VK_EXT_CUSTOM_BORDER_COLOR_EXTENSION_NAME;
    g_vk.divisor = has_ext(ep, ne, VK_EXT_VERTEX_ATTRIBUTE_DIVISOR_EXTENSION_NAME);
    if (g_vk.divisor) ext[n_ext++] = VK_EXT_VERTEX_ATTRIBUTE_DIVISOR_EXTENSION_NAME;
    g_vk.host_import = has_ext(ep, ne, VK_EXT_EXTERNAL_MEMORY_HOST_EXTENSION_NAME);  // guest heap as a GPU buffer (exec.c)
    if (g_vk.host_import) ext[n_ext++] = VK_EXT_EXTERNAL_MEMORY_HOST_EXTENSION_NAME;
    // [XCDE] LINUX-070: LASRecomp's RADV heap work (MIT, Peiikai; PRs 71/255)
    // avoids amdgpu revalidating a whole userptr heap on every submission. The
    // NVIDIA and non-RADV device extension/feature chains remain as before.
    g_vk.radv = g_vk.heap_placed = g_vk.heap_dmabuf = false;
    g_vk.heap_map_alignment = 0;
#ifdef __linux__
    if (g_vk.props.vendorID == 0x1002) {
        VkPhysicalDeviceDriverProperties driver = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
        VkPhysicalDeviceProperties2 query = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &driver};
        vkGetPhysicalDeviceProperties2(g_vk.phys, &query);
        g_vk.radv = driver.driverID == VK_DRIVER_ID_MESA_RADV;
    }
    if (g_vk.radv) {
        g_vk.heap_dmabuf = has_ext(ep, ne, VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME) &&
                           has_ext(ep, ne, VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME);
        if (g_vk.heap_dmabuf) {
            ext[n_ext++] = VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME;
            ext[n_ext++] = VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME;
        }
        if (has_ext(ep, ne, VK_EXT_MAP_MEMORY_PLACED_EXTENSION_NAME) &&
            has_ext(ep, ne, VK_KHR_MAP_MEMORY_2_EXTENSION_NAME)) {
            VkPhysicalDeviceMapMemoryPlacedFeaturesEXT placed = {
                .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAP_MEMORY_PLACED_FEATURES_EXT};
            VkPhysicalDeviceFeatures2 features = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &placed};
            vkGetPhysicalDeviceFeatures2(g_vk.phys, &features);
            VkPhysicalDeviceMapMemoryPlacedPropertiesEXT alignment = {
                .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAP_MEMORY_PLACED_PROPERTIES_EXT};
            VkPhysicalDeviceProperties2 properties = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &alignment};
            vkGetPhysicalDeviceProperties2(g_vk.phys, &properties);
            VkDeviceSize a = alignment.minPlacedMemoryMapAlignment;
            g_vk.heap_placed = placed.memoryMapPlaced && placed.memoryUnmapReserve && a && !(a & (a - 1));
            if (g_vk.heap_placed) {
                g_vk.heap_map_alignment = a;
                ext[n_ext++] = VK_KHR_MAP_MEMORY_2_EXTENSION_NAME;
                ext[n_ext++] = VK_EXT_MAP_MEMORY_PLACED_EXTENSION_NAME;
            }
        }
        LOG("[vk] RADV guest heap capabilities: placed %s, dma-buf %s, map alignment %llu\n",
            g_vk.heap_placed ? "yes" : "no", g_vk.heap_dmabuf ? "yes" : "no",
            (unsigned long long)g_vk.heap_map_alignment);
        // [XCDE] LINUX-075: report the effective driver flag only for RADV.
        // NVIDIA/other drivers do not consume RADV_DEBUG; their policies stay as before.
        LOG("[vk] RADV DCC compatibility: RADV_DEBUG nodcc=%s (lean-format policy unchanged)\n",
            rt_radv_dcc_active() ? "on" : "off");
    }
#endif
    bool fault = has_ext(ep, ne, VK_EXT_DEVICE_FAULT_EXTENSION_NAME);  // device-lost diagnostics (vk_device_fault_report)
    if (fault) ext[n_ext++] = VK_EXT_DEVICE_FAULT_EXTENSION_NAME;
    // [XCDE] the driver's real per-heap usage and budget for VMA (the [mem] report; a 512 MB iGPU carve-out shows how
    // close it runs) - allocation decisions don't change
    bool budget = has_ext(ep, ne, VK_EXT_MEMORY_BUDGET_EXTENSION_NAME) && !(getenv("XCDE_VK_BUDGET") && atoi(getenv("XCDE_VK_BUDGET")) == 0);
    if (budget) ext[n_ext++] = VK_EXT_MEMORY_BUDGET_EXTENSION_NAME;
    g_fault_ext = fault;
    // [XCDE] T173: vertex fetch past a stream's bound size reads 0 on Maxwell (the game's near-camera fade reads its
    // opacity from a 4-byte stream at stride 4: vertices 1..n must see 0, not the guest memory that follows)
    bool robust2 = has_ext(ep, ne, VK_EXT_ROBUSTNESS_2_EXTENSION_NAME);
    if (robust2) ext[n_ext++] = VK_EXT_ROBUSTNESS_2_EXTENSION_NAME;
    // [XCDE] T188: graphics pipeline libraries - a new render-state combination is a fast link of prebuilt pieces
    // instead of a whole pipeline compile. Only where the driver says linking is fast. LARECOMP_VK_GPL=0: off.
    bool gpl = has_ext(ep, ne, VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME) && has_ext(ep, ne, VK_KHR_PIPELINE_LIBRARY_EXTENSION_NAME);
    { const char *e = getenv("LARECOMP_VK_GPL"); if (e && !atoi(e)) gpl = false; }
    VkPhysicalDeviceGraphicsPipelineLibraryFeaturesEXT gplhave = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_FEATURES_EXT};
    if (gpl) {
        VkPhysicalDeviceFeatures2 q = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &gplhave};
        vkGetPhysicalDeviceFeatures2(g_vk.phys, &q);
        VkPhysicalDeviceGraphicsPipelineLibraryPropertiesEXT gp = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_PROPERTIES_EXT};
        VkPhysicalDeviceProperties2 pq = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &gp};
        vkGetPhysicalDeviceProperties2(g_vk.phys, &pq);
        gpl = gplhave.graphicsPipelineLibrary && gp.graphicsPipelineLibraryFastLinking;
        LOG("[vk] graphics pipeline library: feature %d, fast linking %d\n", (int)gplhave.graphicsPipelineLibrary,
            (int)gp.graphicsPipelineLibraryFastLinking);
    }
    if (gpl) { ext[n_ext++] = VK_KHR_PIPELINE_LIBRARY_EXTENSION_NAME; ext[n_ext++] = VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME; }
    g_vk.gpl = gpl;
    free(ep);

    // features the backend relies on (all present on current desktop drivers)
    VkPhysicalDeviceRobustness2FeaturesEXT r2have = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT};
    // [XCDE] FSR 3 (temporal.c): its shaders use half floats and, on AMD, wave64 compute where the device has them
    VkPhysicalDeviceVulkan13Features h13 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES, .pNext = robust2 ? &r2have : NULL};
    VkPhysicalDeviceVulkan12Features h12 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES, .pNext = &h13};
    VkPhysicalDeviceFeatures2 have = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &h12};
    vkGetPhysicalDeviceFeatures2(g_vk.phys, &have);
    VkPhysicalDeviceRobustness2FeaturesEXT r2 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT,
                                                 .robustBufferAccess2 = r2have.robustBufferAccess2 && have.features.robustBufferAccess};
    g_vk.robust2 = r2.robustBufferAccess2;
    VkPhysicalDeviceVertexAttributeDivisorFeaturesEXT div = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VERTEX_ATTRIBUTE_DIVISOR_FEATURES_EXT,
        .vertexAttributeInstanceRateDivisor = VK_TRUE, .vertexAttributeInstanceRateZeroDivisor = VK_FALSE};
    VkPhysicalDeviceCustomBorderColorFeaturesEXT cbc = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_CUSTOM_BORDER_COLOR_FEATURES_EXT, .customBorderColors = VK_TRUE,
        .customBorderColorWithoutFormat = VK_TRUE, .pNext = g_vk.divisor ? &div : NULL};
    VkPhysicalDeviceVulkan13Features f13 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES,
                                            .dynamicRendering = VK_TRUE, .synchronization2 = VK_TRUE,
                                            .shaderDemoteToHelperInvocation = VK_TRUE, .shaderTerminateInvocation = VK_TRUE,
                                            .maintenance4 = VK_TRUE, .pipelineCreationCacheControl = VK_TRUE,  // [XCDE] T188
                                            .subgroupSizeControl = h13.subgroupSizeControl, .computeFullSubgroups = h13.computeFullSubgroups,
                                            .pNext = g_vk.custom_border ? (void *)&cbc : g_vk.divisor ? (void *)&div : NULL};
    VkPhysicalDeviceVulkan12Features f12 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES,
                                            .timelineSemaphore = VK_TRUE, .shaderInt8 = VK_TRUE, .samplerMirrorClampToEdge = VK_TRUE,
                                            .uniformAndStorageBuffer8BitAccess = VK_TRUE, .storageBuffer8BitAccess = VK_TRUE,
                                            .scalarBlockLayout = VK_TRUE, .shaderFloat16 = h12.shaderFloat16, .pNext = &f13,
                                            .samplerFilterMinmax = h12.samplerFilterMinmax};  // [XCDE] NVN reduction filters
    g_vk.minmax = h12.samplerFilterMinmax;
    VkPhysicalDeviceGraphicsPipelineLibraryFeaturesEXT gplf = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_GRAPHICS_PIPELINE_LIBRARY_FEATURES_EXT,
                                                               .graphicsPipelineLibrary = VK_TRUE, .pNext = &f12};
    VkPhysicalDeviceVulkan11Features f11 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES,
                                            .storageBuffer16BitAccess = VK_TRUE, .pNext = gpl ? (void *)&gplf : (void *)&f12};
    VkPhysicalDeviceFaultFeaturesEXT ff = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FAULT_FEATURES_EXT, .deviceFault = VK_TRUE,
                                           .pNext = &f11};
    if (g_vk.robust2) { r2.pNext = fault ? (void *)&ff : (void *)&f11; }
    VkPhysicalDeviceFeatures2 f = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2,
                                   .pNext = g_vk.robust2 ? (void *)&r2 : fault ? (void *)&ff : (void *)&f11};
#ifdef __linux__
    // [XCDE] LINUX-070: map the complete allocation at offset zero; range-placed
    // mappings are not requested. Reserve-on-unmap lets reset keep its guest VA.
    VkPhysicalDeviceMapMemoryPlacedFeaturesEXT heap_features = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAP_MEMORY_PLACED_FEATURES_EXT,
        .memoryMapPlaced = VK_TRUE, .memoryUnmapReserve = VK_TRUE, .pNext = f.pNext};
    if (g_vk.heap_placed) f.pNext = &heap_features;
#endif
    LOG("[vk] robustBufferAccess2: %s\n", g_vk.robust2 ? "on" : "not available");
    VkPhysicalDeviceFeatures *b = &f.features, *h = &have.features;
    b->independentBlend = h->independentBlend;
    b->dualSrcBlend = h->dualSrcBlend;
    b->fillModeNonSolid = h->fillModeNonSolid;
    b->samplerAnisotropy = h->samplerAnisotropy;
    b->textureCompressionBC = h->textureCompressionBC;
    b->shaderInt64 = h->shaderInt64;
    b->shaderInt16 = h->shaderInt16; // [XCDE] LINUX-020: optional FidelityFX half/integer shader permutations.
    b->depthBiasClamp = h->depthBiasClamp;
    b->depthClamp = h->depthClamp;
    b->largePoints = h->largePoints;
    b->wideLines = h->wideLines;
    b->imageCubeArray = h->imageCubeArray;
    b->sampleRateShading = h->sampleRateShading;
    b->fragmentStoresAndAtomics = h->fragmentStoresAndAtomics;
    b->shaderStorageImageReadWithoutFormat = h->shaderStorageImageReadWithoutFormat;  // [XCDE] SULD / SUST
    b->shaderStorageImageWriteWithoutFormat = h->shaderStorageImageWriteWithoutFormat;
    b->vertexPipelineStoresAndAtomics = h->vertexPipelineStoresAndAtomics;
    b->robustBufferAccess = h->robustBufferAccess;  // guest shaders index cbufs freely: keep OOB reads harmless
    b->shaderClipDistance = h->shaderClipDistance;
    b->geometryShader = h->geometryShader;  // [XCDE] the game's point-sprite geometry shaders
    b->logicOp = h->logicOp;  // [XCDE] T176: ColorState logic ops (the probe-lighting index map ORs its slots)
    g_vk.logic_op = h->logicOp;
    if (!h->shaderInt64) LOG("[vk] warning: no shaderInt64 (64-bit address math in shaders)\n");
    // [XCDE] DLSS (dlss.cpp): Streamline's device extensions, features and queues (after ours, same family)
    uint32_t extra_g = 0, extra_c = 0;
    {
        dlss_device_requirements(g_vk.inst, g_vk.phys, ext, &n_ext, 48, &f12, &f13, &extra_g, &extra_c);
    }
    // Queues: ours (index 0 of qfam), Streamline's after it in the same family, and [XCDE] FSR 3 frame generation's
    // present / image-acquire / async-compute queues (temporal.c), picked as AMD's sample does: each from a family
    // with a queue left (present: graphics + compute + present; acquire: preferably no graphics / compute;
    // compute: preferably compute without graphics). Without them (or with frame generation off) nothing changes.
    float prio[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1};
    uint32_t nf = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &nf, NULL);
    VkQueueFamilyProperties qp[16];
    if (nf > 16) nf = 16;
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &nf, qp);
    uint32_t used[16] = {0};
    used[g_vk.qfam] = 1 + extra_g + extra_c;
    if (used[g_vk.qfam] > qp[g_vk.qfam].queueCount) used[g_vk.qfam] = qp[g_vk.qfam].queueCount;
    {
        extern bool tmp_frame_gen_wanted(void);
        uint32_t fam[3] = {UINT32_MAX, UINT32_MAX, UINT32_MAX}, idx[3] = {0};  // present, acquire, compute
        // Linux interpolation uses the render queue synchronously, not the Windows SDK swapchain's threads.
        if (
#ifndef __linux__
            tmp_frame_gen_wanted()
#else
            false
#endif
        ) {
#define FREE(i) (used[i] < qp[i].queueCount && used[i] < 16)
#define HAS(i, b) ((qp[i].queueFlags & (b)) == (b))
            for (uint32_t i = 0; i < nf && fam[0] == UINT32_MAX; i++) {
                VkBool32 pr = VK_FALSE;
                vkGetPhysicalDeviceSurfaceSupportKHR(g_vk.phys, i, g_vk.surface, &pr);
                if (pr && HAS(i, VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT) && FREE(i)) fam[0] = i, idx[0] = used[i]++;
            }
            for (int pass = 0; pass < 3 && fam[1] == UINT32_MAX; pass++)
                for (uint32_t i = 0; i < nf && fam[1] == UINT32_MAX; i++) {
                    bool ok = pass == 0 ? !(qp[i].queueFlags & (VK_QUEUE_COMPUTE_BIT | VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_TRANSFER_BIT))
                            : pass == 1 ? !(qp[i].queueFlags & (VK_QUEUE_COMPUTE_BIT | VK_QUEUE_GRAPHICS_BIT))
                            : !(qp[i].queueFlags & VK_QUEUE_GRAPHICS_BIT);
                    if (ok && FREE(i)) fam[1] = i, idx[1] = used[i]++;
                }
            for (int pass = 0; pass < 2 && fam[2] == UINT32_MAX; pass++)
                for (uint32_t i = 0; i < nf && fam[2] == UINT32_MAX; i++) {
                    bool ok = HAS(i, VK_QUEUE_COMPUTE_BIT) && (pass == 1 || !(qp[i].queueFlags & VK_QUEUE_GRAPHICS_BIT));
                    if (ok && FREE(i)) fam[2] = i, idx[2] = used[i]++;
                }
#undef FREE
#undef HAS
            if (fam[0] == UINT32_MAX || fam[1] == UINT32_MAX || fam[2] == UINT32_MAX) {
                LOG("[vk] no free queues for frame generation (present %d acquire %d compute %d): off\n", (int)fam[0], (int)fam[1], (int)fam[2]);
                for (int k = 0; k < 3; k++) if (fam[k] != UINT32_MAX) used[fam[k]]--;
                fam[0] = fam[1] = fam[2] = UINT32_MAX;
            }
        }
        for (int k = 0; k < 3; k++) { g_vk.fg_fam[k] = fam[k]; g_vk.fg_idx[k] = idx[k]; }
    }
    VkDeviceQueueCreateInfo qi[16];
    uint32_t nqi = 0;
    for (uint32_t i = 0; i < nf; i++)
        if (used[i]) qi[nqi++] = (VkDeviceQueueCreateInfo){.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = i,
                                                           .queueCount = used[i], .pQueuePriorities = prio};
    VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &f, .queueCreateInfoCount = nqi,
                             .pQueueCreateInfos = qi, .enabledExtensionCount = n_ext, .ppEnabledExtensionNames = ext};
    VK_CHECK(vkCreateDevice(g_vk.phys, &di, NULL, &g_vk.dev));
    vkGetDeviceQueue(g_vk.dev, g_vk.qfam, 0, &g_vk.queue);
    for (int k = 0; k < 3; k++)
        if (g_vk.fg_fam[k] != UINT32_MAX) vkGetDeviceQueue(g_vk.dev, g_vk.fg_fam[k], g_vk.fg_idx[k], &g_vk.fg_queue[k]);
    {   // [XCDE] DLSS: the device for Streamline; its swapchain proxies
        extern void dlss_device_created(VkInstance inst, VkPhysicalDevice phys, VkDevice dev, uint32_t qfam);
        dlss_device_created(g_vk.inst, g_vk.phys, g_vk.dev, g_vk.qfam);
        sc_proxies();
    }

    VmaAllocatorCreateInfo ai = {.physicalDevice = g_vk.phys, .device = g_vk.dev, .instance = g_vk.inst,
                                 .vulkanApiVersion = VK_API_VERSION_1_3,
                                 .flags = budget ? VMA_ALLOCATOR_CREATE_EXT_MEMORY_BUDGET_BIT : 0};
    VK_CHECK(vmaCreateAllocator(&ai, &g_vk.vma));

    VkSemaphoreTypeCreateInfo st = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO,
                                    .semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE, .initialValue = 0};
    VkSemaphoreCreateInfo si = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext = &st};
    VK_CHECK(vkCreateSemaphore(g_vk.dev, &si, NULL, &g_vk.timeline));
    VkCommandPoolCreateInfo pi = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                  .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = g_vk.qfam};
    VK_CHECK(vkCreateCommandPool(g_vk.dev, &pi, NULL, &g_vk.pool));

    // pipeline cache: cache/vk_pipelines.bin (written by vk_pipeline_cache_save)
    size_t sz = 0;
    void *data = NULL;
    FILE *fp = fopen("cache/vk_pipelines.bin", "rb");
    if (fp) {
        fseek(fp, 0, SEEK_END);
        sz = (size_t)ftell(fp);
        fseek(fp, 0, SEEK_SET);
        data = malloc(sz);
        if (fread(data, 1, sz, fp) != sz) sz = 0;
        fclose(fp);
    }
    VkPipelineCacheCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO, .initialDataSize = sz,
                                    .pInitialData = data};
    if (vkCreatePipelineCache(g_vk.dev, &pc, NULL, &g_vk.pcache) != VK_SUCCESS) {
        pc.initialDataSize = 0;
        VK_CHECK(vkCreatePipelineCache(g_vk.dev, &pc, NULL, &g_vk.pcache));
    }
    free(data);
}

void vk_pipeline_cache_save(void);
static _Atomic int pc_saving;
static void *pc_save_thread(void *arg) {
    (void)arg;
    vk_pipeline_cache_save();
    atomic_store(&pc_saving, 0);
    return NULL;
}
void vk_pipeline_cache_save_async(void) {
    int z = 0;
    if (!atomic_compare_exchange_strong(&pc_saving, &z, 1)) return;  // (one at a time)
    pthread_t t;
    if (pthread_create(&t, NULL, pc_save_thread, NULL) != 0) { atomic_store(&pc_saving, 0); return; }
    pthread_detach(t);
}

void vk_pipeline_cache_save(void) {
    // [XCDE] test runs (hidden window: rtrun.sh / drive_env.sh) read the player's cache but never write it: a test build
    // translates shaders differently, and the last process to exit replaced the file - the player's next start then
    // compiled ~730 pipelines while loading (24 s, 1-2 s freezes; party session's diagnosis). XCDE_SAVE_CACHE=1: save anyway.
    if (getenv("LARECOMP_HIDDEN") && !getenv("XCDE_SAVE_CACHE")) return;
#ifdef __linux__
    if (!vk_pipeline_cache_save_checked()) LOG("[vk] pipeline cache write failed; previous complete cache retained when possible\n");
#else
    size_t sz = 0;
    if (vkGetPipelineCacheData(g_vk.dev, g_vk.pcache, &sz, NULL) != VK_SUCCESS || !sz) return;
    void *data = malloc(sz);
    if (vkGetPipelineCacheData(g_vk.dev, g_vk.pcache, &sz, data) == VK_SUCCESS) {
        mkdir("cache", 0755);
        char tmp[64];  // (per process: test runs and the user's game save the same cache)
        snprintf(tmp, sizeof tmp, "cache/vk_pipelines.bin.%d.tmp", (int)getpid());
        FILE *f = fopen(tmp, "wb");
        if (f) {
            bool ok = fwrite(data, 1, sz, f) == sz;
            fclose(f);
            if (ok) { remove("cache/vk_pipelines.bin"); rename(tmp, "cache/vk_pipelines.bin"); }
            else remove(tmp);
        }
    }
    free(data);
#endif
}

// [XCDE] LINUX-018: explicit precompile is allowed to persist its private cache
// despite its hidden window, and completion must observe any storage failure.
#ifdef __linux__
bool vk_pipeline_cache_save_checked(void) {
    static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
    pthread_mutex_lock(&lock);
    bool ok = mkdir("cache", 0755) == 0 || errno == EEXIST;
    if (ok) ok = vk_pipeline_cache_write_file(g_vk.dev, g_vk.pcache, "cache/vk_pipelines.bin");
    pthread_mutex_unlock(&lock);
    return ok;
}
#endif

// ================================================================== swapchain
static bool g_vsync_fifo;  // FIFO chosen by the V-Sync option (backend_present's repeat presents)
static VkPresentModeKHR present_mode(void) {
    // MAILBOX by default: the game paces itself (vi.c's emulated 60 Hz vsync), and with FIFO every submission
    // queued behind the one waiting for a window image, so the game's fence waits followed the presentation engine:
    // a throttled / captured / busy compositor slowed the whole game (4-21 fps with the GPU mostly idle; mailbox:
    // 60). No tearing. LARECOMP_VK_PRESENT=fifo|immediate|mailbox to choose.
    // [XCDE] V-Sync option (xcde.ini vsync = 1, the default; FPS 30 / 60): FIFO. The game's limiter aims at 0.997 x the
    // period (~60.2 fps), which on the Switch the display holds to its vblanks; with mailbox nothing did, so against a
    // 59.99x Hz monitor some frames were shown twice and others never, at a steady "60 fps" in the counters (the user:
    // feels laggy, frametime flat). FIFO shows each frame once. Above 60 / unlimited: mailbox (FIFO would cap it).
    const char *e = getenv("LARECOMP_VK_PRESENT");
    bool vs = !e && g_settings.vsync && g_settings.fps > 0 && g_settings.fps <= 60 && !getenv("XCDE_FPS_PERIOD_SCALE") &&
              (!getenv("LARECOMP_HIDDEN") || getenv("XCDE_VSYNC_TEST")) && !diag_deterministic();  // (test runs: as before)
    if (vs) e = "fifo";
    { static int logged; if (!logged++) LOG("[vk] present mode %s%s\n", e ? e : "mailbox", vs ? " (V-Sync option)" : ""); }
    VkPresentModeKHR want = !e || !strcmp(e, "mailbox") ? VK_PRESENT_MODE_MAILBOX_KHR
                          : !strcmp(e, "immediate") ? VK_PRESENT_MODE_IMMEDIATE_KHR : VK_PRESENT_MODE_FIFO_KHR;
    uint32_t n = 0;
    vkGetPhysicalDeviceSurfacePresentModesKHR(g_vk.phys, g_vk.surface, &n, NULL);
    VkPresentModeKHR m[16];
    if (n > 16) n = 16;
    vkGetPhysicalDeviceSurfacePresentModesKHR(g_vk.phys, g_vk.surface, &n, m);
    g_vsync_fifo = vs;
    for (uint32_t i = 0; i < n; i++) if (m[i] == want) return want;
    return VK_PRESENT_MODE_FIFO_KHR;
}

// [XCDE] how many times each frame is presented (1: once). FPS 30 with V-Sync on a 60 Hz monitor (the user: frame times
// not flat at 30, flat at 60): the game's limiter aims at 0.997 x 2 refreshes, so its frames drift against the vblanks
// and every few seconds one is shown for 1 or 3 refreshes instead of 2. Presenting each frame refresh / FPS times in
// FIFO shows it for exactly that many refreshes, and the presents themselves hold the game to the display. Only when the
// refresh is a whole multiple of the FPS (within 1 %), and not with frame generation (its swapchain paces itself).
// XCDE_REPEAT_PRESENT=0: off.
// the window's display refresh (Hz; 0: unknown), checked every 2 s (the window may move to another monitor). Render
// thread only (SDL); other threads read vk_display_hz_cached.
static volatile float g_display_hz;
float vk_display_hz_cached(void) { return g_display_hz; }
float vk_display_hz(void) {
    static float hz = -1;
    static uint64_t checked;
    if (!window) return 0;
    if (hz < 0 || SDL_GetTicksNS() - checked > 2000000000ull) {
        checked = SDL_GetTicksNS();
        const SDL_DisplayMode *dm = SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(window));
        hz = dm ? dm->refresh_rate : 0;
        g_display_hz = hz;
    }
    return hz;
}

static int repeat_presents(void) {
    static int off = -1;
    if (off < 0) off = getenv("XCDE_REPEAT_PRESENT") && atoi(getenv("XCDE_REPEAT_PRESENT")) == 0;
    extern bool tmp_fg_active(void);
    extern int xcde_present_fps(void);  // (FPS setting, or 30 while a cutscene is held at 30: framepace.c)
    int fps = xcde_present_fps();
    float hz = vk_display_hz();
    // [XCDE] LINUX-029: warmup/history belongs to one real frame too. A
    // repeat redraw must not consume its inputs or reset that history.
    bool fg_owns_interval = tmp_fg_active();
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
    extern bool tmp_fg_repeat_suppressed(void);
    fg_owns_interval = tmp_fg_repeat_suppressed();
#endif
    if (off || !g_vsync_fifo || fg_owns_interval || fps <= 0 || !window) return 1;
    if (hz <= 0) return 1;
    float r = hz / (float)fps;
    int n = (int)lroundf(r);
    if (n < 2 || n > 8 || fabsf(r - n) > 0.01f * n) return 1;
    static int logged_fps;
    if (logged_fps != fps) { logged_fps = fps; LOG("[vk] V-Sync at %d fps on a %.2f Hz display: each frame presented %d times\n", fps, hz, n); }
    return n;
}

static void create_swapchain(void) {
    VkSurfaceCapabilitiesKHR caps;
    VK_CHECK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(g_vk.phys, g_vk.surface, &caps));
    int w, h;
    SDL_GetWindowSizeInPixels(window, &w, &h);
    VkExtent2D ext = caps.currentExtent.width != UINT32_MAX ? caps.currentExtent : (VkExtent2D){(uint32_t)w, (uint32_t)h};
    if (!ext.width || !ext.height) return;  // minimised
    uint32_t nf = 0;
    vkGetPhysicalDeviceSurfaceFormatsKHR(g_vk.phys, g_vk.surface, &nf, NULL);
    VkSurfaceFormatKHR fmts[64];
    if (nf > 64) nf = 64;
    vkGetPhysicalDeviceSurfaceFormatsKHR(g_vk.phys, g_vk.surface, &nf, fmts);
    // scanout shows the bytes the game wrote (see the raw views in the present pass): a UNORM swapchain like Metal's
    VkSurfaceFormatKHR sf = fmts[0];
    for (uint32_t i = 0; i < nf; i++)
        if (fmts[i].format == VK_FORMAT_B8G8R8A8_UNORM && fmts[i].colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) { sf = fmts[i]; break; }
    uint32_t count = caps.minImageCount + 1;
    if (caps.maxImageCount && count > caps.maxImageCount) count = caps.maxImageCount;
    if (count > 8) count = 8;
    VkSwapchainKHR old = g_vk.swapchain;
    VkSwapchainCreateInfoKHR ci = {
        .sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, .surface = g_vk.surface, .minImageCount = count,
        .imageFormat = sf.format, .imageColorSpace = sf.colorSpace, .imageExtent = ext, .imageArrayLayers = 1,
        .imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE, .preTransform = caps.currentTransform,
        .compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR, .presentMode = present_mode(), .clipped = VK_TRUE,
        .oldSwapchain = old};
    VK_CHECK(sc_create(g_vk.dev, &ci, NULL, &g_vk.swapchain));
    for (uint32_t i = 0; i < g_vk.sc_count; i++) vkDestroyImageView(g_vk.dev, g_vk.sc_views[i], NULL);
    if (old) sc_destroy(g_vk.dev, old, NULL);
    static bool fg_tried;  // [XCDE] FSR 3 frame generation (temporal.c): AMD's swapchain replaces this one, once
    if (!fg_tried) {
        fg_tried = true;
        extern bool tmp_fg_install(VkSwapchainKHR *sc, const VkSwapchainCreateInfoKHR *ci, PFN_vkCreateSwapchainKHR *create,
                                   PFN_vkDestroySwapchainKHR *destroy, PFN_vkGetSwapchainImagesKHR *images,
                                   PFN_vkAcquireNextImageKHR *acquire, PFN_vkQueuePresentKHR *present);
        tmp_fg_install(&g_vk.swapchain, &ci, &sc_create, &sc_destroy, &sc_images, &sc_acquire, &sc_present);
    }
    g_vk.sc_format = sf.format;
    g_vk.sc_extent = ext;
    g_vk.sc_count = 0;  // (count first: AMD's frame-generation swapchain fills exactly what it reports)
    sc_images(g_vk.dev, g_vk.swapchain, &g_vk.sc_count, NULL);
    if (g_vk.sc_count > 8) g_vk.sc_count = 8;
    memset(g_vk.sc_images, 0, sizeof g_vk.sc_images);
    VkResult ir = sc_images(g_vk.dev, g_vk.swapchain, &g_vk.sc_count, g_vk.sc_images);
    if (getenv("XCDE_TMP_LOG")) LOG("[vk] swapchain %p: %u images (%d)%c", (void *)g_vk.swapchain, g_vk.sc_count, (int)ir, 10);
    for (uint32_t i = 0; i < g_vk.sc_count; i++) {
        VkImageViewCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = g_vk.sc_images[i],
                                    .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = sf.format,
                                    .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        VK_CHECK(vkCreateImageView(g_vk.dev, &vi, NULL, &g_vk.sc_views[i]));
    }
}

static void recreate_swapchain(void) {
    sc_wait_idle(g_vk.dev);
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
    extern void tmp_fg_invalidate(void);
    tmp_fg_invalidate();
#endif
    create_swapchain();
}

// ================================================================== frames (start screen and game)
// Acquire semaphores rotate per frame in flight; a slot is reused once the submission that waited on it is done.
#define FRAMES 3
static VkSemaphore acquire_sem[FRAMES], done_sem[8];
static uint64_t slot_seq[FRAMES];
static int slot;

static VkSemaphore binary_semaphore(void) {
    VkSemaphoreCreateInfo si = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    VkSemaphore s;
    VK_CHECK(vkCreateSemaphore(g_vk.dev, &si, NULL, &s));
    return s;
}

static void image_barrier(VkCommandBuffer cb, VkImage img, VkImageLayout from, VkImageLayout to) {
    VkImageMemoryBarrier2 b = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2,
                               .srcStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, .srcAccessMask = VK_ACCESS_2_MEMORY_WRITE_BIT,
                               .dstStageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT,
                               .dstAccessMask = VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT,
                               .oldLayout = from, .newLayout = to, .image = img,
                               .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
                               .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED};
    VkDependencyInfo di = {.sType = VK_STRUCTURE_TYPE_DEPENDENCY_INFO, .imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &b};
    vkCmdPipelineBarrier2(cb, &di);
}

typedef struct { uint32_t image; VkSemaphore acquired; bool ok; } Frame;
static Frame cur_frame;

// Acquire the next window image and begin rendering into it (cleared to `clear`). Returns false when there is
// nothing to draw into (minimised window).
static volatile bool sc_dirty;  // [XCDE] the F1 menu changed V-Sync: a new swapchain with the new present mode
void vk_request_swapchain_recreate(void) { sc_dirty = true; }
bool vk_frame_begin(const float clear[4]) {
    cur_frame.ok = false;
    if (sc_dirty && g_vk.swapchain) { sc_dirty = false; recreate_swapchain(); }
    int w, h;
    SDL_GetWindowSizeInPixels(window, &w, &h);
    if (!w || !h) return false;  // minimised
    if (!g_vk.swapchain || (uint32_t)w != g_vk.sc_extent.width || (uint32_t)h != g_vk.sc_extent.height) recreate_swapchain();
    if (!g_vk.swapchain) return false;
    static int trace = -1;
    if (trace < 0) trace = getenv("LARECOMP_VK_TRACE") != NULL;
    if (trace) LOG("[vk] frame begin %dx%d (swapchain %ux%u)\n", w, h, g_vk.sc_extent.width, g_vk.sc_extent.height);
    slot = (slot + 1) % FRAMES;
    if (!acquire_sem[slot]) acquire_sem[slot] = binary_semaphore();
    vk_wait_seq(slot_seq[slot]);
    extern void vk_rq_at(const char *where);
    extern const char *volatile g_rq_where;
    const char *was_at = g_rq_where;
    vk_rq_at("acquiring a swapchain image");
    VkResult r = sc_acquire(g_vk.dev, g_vk.swapchain, UINT64_MAX, acquire_sem[slot], VK_NULL_HANDLE, &cur_frame.image);
    vk_rq_at(was_at);
    if (r == VK_ERROR_OUT_OF_DATE_KHR) {
        recreate_swapchain();
        r = sc_acquire(g_vk.dev, g_vk.swapchain, UINT64_MAX, acquire_sem[slot], VK_NULL_HANDLE, &cur_frame.image);
    }
    if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) { LOG("[vk] acquire failed: %d\n", r); return false; }
    cur_frame.acquired = acquire_sem[slot];
    slot_seq[slot] = vk_pending_seq();
    VkCommandBuffer cb = vk_cmd();
    { extern float vk_frame_clear[4]; for (int i = 0; i < 4; i++) vk_frame_clear[i] = clear[i]; }  // (exec.c: the HUD-less copy)
    image_barrier(cb, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
    VkRenderingAttachmentInfo ca = {.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageView = g_vk.sc_views[cur_frame.image],
                                    .imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                                    .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
                                    .clearValue.color.float32 = {clear[0], clear[1], clear[2], clear[3]}};
    VkRenderingInfo ri = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = {{0, 0}, g_vk.sc_extent}, .layerCount = 1,
                          .colorAttachmentCount = 1, .pColorAttachments = &ca};
    vkCmdBeginRendering(cb, &ri);
    VkViewport vp = {0, 0, (float)g_vk.sc_extent.width, (float)g_vk.sc_extent.height, 0, 1};
    VkRect2D sc = {{0, 0}, g_vk.sc_extent};
    vkCmdSetViewport(cb, 0, 1, &vp);
    vkCmdSetScissor(cb, 0, 1, &sc);
    cur_frame.ok = true;
    return true;
}

// Passes of their own between vk_frame_begin and vk_frame_end (exec.c post passes): end the window image's
// rendering, and begin it again keeping what was drawn.
void vk_frame_suspend(void) {
    if (cur_frame.ok) vkCmdEndRendering(vk_cmd());
}
void vk_frame_resume(void) {
    if (!cur_frame.ok) return;
    VkCommandBuffer cb = vk_cmd();
    VkRenderingAttachmentInfo ca = {.sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageView = g_vk.sc_views[cur_frame.image],
                                    .imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                                    .loadOp = VK_ATTACHMENT_LOAD_OP_LOAD, .storeOp = VK_ATTACHMENT_STORE_OP_STORE};
    VkRenderingInfo ri = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = {{0, 0}, g_vk.sc_extent}, .layerCount = 1,
                          .colorAttachmentCount = 1, .pColorAttachments = &ca};
    vkCmdBeginRendering(cb, &ri);
    VkViewport vp = {0, 0, (float)g_vk.sc_extent.width, (float)g_vk.sc_extent.height, 0, 1};
    VkRect2D sc = {{0, 0}, g_vk.sc_extent};
    vkCmdSetViewport(cb, 0, 1, &vp);
    vkCmdSetScissor(cb, 0, 1, &sc);
}

VkExtent2D vk_frame_extent(void) { return g_vk.sc_extent; }
void *vk_frame_cmd(void) { return (void *)vk_cmd(); }

static void save_window_image(VkCommandBuffer cb, VkSpan *out) {
    uint32_t w = g_vk.sc_extent.width, h = g_vk.sc_extent.height;
    *out = vk_readback((uint64_t)w * h * 4);
    image_barrier(cb, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    VkBufferImageCopy rg = {.bufferOffset = out->off, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                            .imageExtent = {w, h, 1}};
    vkCmdCopyImageToBuffer(cb, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, out->buf, 1, &rg);
    image_barrier(cb, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
}

// End rendering into the window image and present it. shot_path: also save the window image as PNG.
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
#include "framegen_pacing_linux.h"
static bool fg_present_second;
static uint64_t fg_second_deadline; // [XCDE] LINUX-029: absolute spacing, applied after preparing the real image.
static uint64_t fg_submitted_generated, fg_submitted_real;
#endif
void vk_frame_end(const char *shot_path) {
    if (!cur_frame.ok) return;
    VkCommandBuffer cb = vk_cmd();
    vkCmdEndRendering(cb);
    VkSpan shot = {0};
    extern bool diag_flicker_wanted(void);
    bool hash_it = diag_hash_wanted() || diag_flicker_wanted();  // [XCDE] T029: per-frame hash of the window image (+ T173 flicker check)
    if (shot_path || hash_it) save_window_image(cb, &shot);
    VkImageLayout final_layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
    VkImage retained_real = VK_NULL_HANDLE;
    float frame_ms = 0;
    uint64_t deadline = 0;
    const VkExtent2D pair_extent = g_vk.sc_extent;
    const VkFormat pair_format = g_vk.sc_format;
    const VkSwapchainKHR pair_swapchain = g_vk.swapchain;
    bool pair = false;
    if (!fg_present_second && !shot_path && !hash_it) {
        extern bool tmp_fg_record_present(VkCommandBuffer, VkImage, VkImage *, float *);
        image_barrier(cb, g_vk.sc_images[cur_frame.image], final_layout, VK_IMAGE_LAYOUT_GENERAL);
        final_layout = VK_IMAGE_LAYOUT_GENERAL;
        pair = tmp_fg_record_present(cb, g_vk.sc_images[cur_frame.image], &retained_real, &frame_ms);
    }
#endif
    image_barrier(cb, g_vk.sc_images[cur_frame.image], final_layout, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    uint32_t img = cur_frame.image;
    if (!done_sem[img]) done_sem[img] = binary_semaphore();
    uint64_t seq = vk_pending_seq();
    vk_submit_extra(cur_frame.acquired, done_sem[img], VK_NULL_HANDLE);
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
    // GPU readiness anchors pacing. Queueing two unready images with only a CPU sleep can show them together.
    if (pair) vk_wait_seq(seq);
    else if (fg_present_second && fg_second_deadline) {
        // [XCDE] LINUX-029: overlap acquisition/recording/GPU copy with the
        // existing deadline. The present semaphore still enforces GPU readiness.
        uint64_t elapsed = 0;
        fg_pacing_wait_elapsed(fg_second_deadline, &elapsed);
        extern __thread uint64_t g_blocked_ns;
        g_blocked_ns += elapsed; // deliberate host idle is not game/GPU busy work
    }
#endif
    VkPresentInfoKHR pi = {.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, .waitSemaphoreCount = 1, .pWaitSemaphores = &done_sem[img],
                           .swapchainCount = 1, .pSwapchains = &g_vk.swapchain, .pImageIndices = &img};
    extern void vk_rq_at(const char *where);
    extern const char *volatile g_rq_where;
    const char *was_pr = g_rq_where;
    vk_rq_at("vkQueuePresentKHR");
    VkResult r = sc_present(g_vk.queue, &pi);
    vk_rq_at(was_pr);
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
    if (r == VK_SUCCESS || r == VK_SUBOPTIMAL_KHR) {
        if (pair) fg_submitted_generated++; else fg_submitted_real++;
        if (pair && fg_submitted_generated % 120 == 1)
            LOG("[fg] submitted %llu generated + %llu real images; game/rendered FPS counter unchanged\n",
                (unsigned long long)fg_submitted_generated, (unsigned long long)fg_submitted_real);
    } else { extern void tmp_fg_invalidate(void); tmp_fg_invalidate(); }
    if (pair && r == VK_SUCCESS) {
        uint64_t now = fg_pacing_now();
        // [XCDE] LINUX-029: SDK motion timing remains measured. Presentation
        // alone bounds its idle budget by the selected real-frame interval.
        extern int xcde_present_fps(void);
        float pacing_ms = fg_pacing_interval_ms(frame_ms, xcde_present_fps());
        if (!fg_pacing_deadline(now, pacing_ms, &deadline)) deadline = now;
    }
#endif
    if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR) recreate_swapchain();
    cur_frame.ok = false;
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
    if (pair && r == VK_SUCCESS && g_vk.swapchain == pair_swapchain) {
        const float clear[4] = {0, 0, 0, 1};
        if (vk_frame_begin(clear)) {
            bool same = g_vk.sc_format == pair_format && g_vk.sc_extent.width == pair_extent.width && g_vk.sc_extent.height == pair_extent.height;
            bool blit = false;
            if (!same) {
                VkFormatProperties src_props, dst_props;
                vkGetPhysicalDeviceFormatProperties(g_vk.phys, pair_format, &src_props);
                vkGetPhysicalDeviceFormatProperties(g_vk.phys, g_vk.sc_format, &dst_props);
                blit = (src_props.optimalTilingFeatures & VK_FORMAT_FEATURE_BLIT_SRC_BIT) &&
                    (dst_props.optimalTilingFeatures & VK_FORMAT_FEATURE_BLIT_DST_BIT);
            }
            if (same || blit) {
                VkCommandBuffer second = vk_cmd();
                vkCmdEndRendering(second);
                image_barrier(second, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL);
                VkImageCopy copy = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                    .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .extent = {
                        pair_extent.width < g_vk.sc_extent.width ? pair_extent.width : g_vk.sc_extent.width,
                        pair_extent.height < g_vk.sc_extent.height ? pair_extent.height : g_vk.sc_extent.height, 1}};
                vk_full_barrier(second);
                if (same) vkCmdCopyImage(second, retained_real, VK_IMAGE_LAYOUT_GENERAL, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_GENERAL, 1, &copy);
                else {
                    VkImageBlit region = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                        .srcOffsets = {{0, 0, 0}, {(int32_t)pair_extent.width, (int32_t)pair_extent.height, 1}},
                        .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                        .dstOffsets = {{0, 0, 0}, {(int32_t)g_vk.sc_extent.width, (int32_t)g_vk.sc_extent.height, 1}}};
                    vkCmdBlitImage(second, retained_real, VK_IMAGE_LAYOUT_GENERAL, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_GENERAL, 1, &region, VK_FILTER_NEAREST);
                }
                image_barrier(second, g_vk.sc_images[cur_frame.image], VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
                vk_frame_resume(); // end helper expects one active rendering scope; no HUD/menu/guest work is repeated.
            } else {
                // A format without transfer-blit support falls back to the existing real-frame redraw, never an empty frame.
                extern void vk_present_redraw(VkCommandBuffer);
                vk_present_redraw(vk_cmd());
            }
            fg_second_deadline = deadline;
            fg_present_second = true;
            vk_frame_end(NULL);
            fg_present_second = false;
            fg_second_deadline = 0;
        } else { extern void tmp_fg_invalidate(void); tmp_fg_invalidate(); }
    }
#endif
    if (shot_path || hash_it) {
        vk_wait_seq(seq);
        uint32_t w = g_vk.sc_extent.width, h = g_vk.sc_extent.height;
        uint8_t *px = shot.ptr;
        bool bgr = g_vk.sc_format == VK_FORMAT_B8G8R8A8_UNORM || g_vk.sc_format == VK_FORMAT_B8G8R8A8_SRGB;
        for (uint64_t i = 0; bgr && i < (uint64_t)w * h; i++) { uint8_t t = px[i * 4]; px[i * 4] = px[i * 4 + 2]; px[i * 4 + 2] = t; }
        for (uint64_t i = 0; i < (uint64_t)w * h; i++) px[i * 4 + 3] = 255;
        if (diag_hash_wanted()) diag_frame_hash(diag_frame() + 1, px, w, h);
        { extern void diag_flicker_check(uint64_t, const uint8_t *, uint32_t, uint32_t, void (*)(const char *, const uint8_t *, uint32_t, uint32_t));
          if (diag_flicker_wanted()) diag_flicker_check(diag_frame() + 1, px, w, h, vk_save_png); }
        if (shot_path) vk_save_png(shot_path, px, w, h);
    }
}

void vk_save_png(const char *path, const uint8_t *rgba, uint32_t w, uint32_t h) {
    SDL_Surface *s = SDL_CreateSurfaceFrom((int)w, (int)h, SDL_PIXELFORMAT_ABGR8888, (void *)rgba, (int)w * 4);
    if (!s || !SDL_SavePNG(s, path)) LOG("[vk] saving %s failed: %s\n", path, SDL_GetError());
    else LOG("[vk] saved %s (%ux%u)\n", path, w, h);
    SDL_DestroySurface(s);
}

// ================================================================== game presentation (metal.m backend_present)
// Draws the game's image into the window with the widescreen crop, then the overlay menu.
extern void vk_present_draw(VkCommandBuffer cb, TexBackend *b, float vx, float vy, float vw, float vh, const float pv[8]);
void renderer_submit(void);
void renderer_set_scale(float sx, float sy);
uint64_t renderer_present_count(void);
void renderer_save_texture_tex(TexBackend *b, const char *path);

static uint64_t frames, total_frames, g_frame_counter;
uint64_t renderer_present_count(void) { return total_frames; }
uint64_t vk_frame_counter(void) { return g_frame_counter; }
static float g_shot_crop[4] = {0, 0, 1, 1};
static double last_fps_time;
static NvnTexture *g_last_presented;

const float *vk_shot_crop(void) { return g_shot_crop; }

void backend_present(NvnTexture *t);
void backend_represent(void) {
    if (g_last_presented) backend_present(g_last_presented);
    else SDL_Delay(16);
}

// [XCDE] diagnostics: XCDE_DUP_CHECK=1 - a 64x36 thumbnail of every presented game image (GPU blit + readback, read
// back 3 frames later), compared with the previous one: "[dup]" every 120 frames = how many frames repeated the last
// image exactly (cutscenes at FPS 60 that animate at 30 show every other frame repeated). Costs ~nothing, no stalls.
static void dup_check(TexBackend *b) {
    static int on = -1;
    if (on < 0) on = getenv("XCDE_DUP_CHECK") != NULL;
    if (!on || !b || !b->image || (b->aspect & ~VK_IMAGE_ASPECT_COLOR_BIT)) return;
    enum { W = 64, H = 36, N = 4 };
    static VkImage img; static VmaAllocation img_mem;
    static VkBuffer buf[N]; static VmaAllocation buf_mem[N]; static uint8_t *ptr[N]; static uint64_t seq[N];
    static uint8_t last[W * H * 4];
    static int slot, nframes, ndup, have_last;
    static char pat[121];
    VkCommandBuffer cb = vk_cmd();
    if (!img) {
        VkImageCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R8G8B8A8_UNORM,
                                .extent = {W, H, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
                                .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
        VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
        if (vmaCreateImage(g_vk.vma, &ci, &ai, &img, &img_mem, NULL) != VK_SUCCESS) { on = 0; return; }
        vk_image_init_layout(cb, img, VK_IMAGE_ASPECT_COLOR_BIT);
        for (int i = 0; i < N; i++) {
            VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = W * H * 4, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
            VmaAllocationCreateInfo bai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
                                           .flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT};
            VmaAllocationInfo info;
            if (vmaCreateBuffer(g_vk.vma, &bi, &bai, &buf[i], &buf_mem[i], &info) != VK_SUCCESS) { on = 0; return; }
            ptr[i] = info.pMappedData;
        }
    }
    // the oldest slot: its copy has finished by now (or wait for it)
    int s = slot % N;
    if (seq[s]) {
        if (vk_completed_seq() < seq[s]) vk_wait_seq(seq[s]);
        vmaInvalidateAllocation(g_vk.vma, buf_mem[s], 0, VK_WHOLE_SIZE);
        if (have_last) {
            int d = 0;
            for (int i = 0; i < W * H * 4; i++) d += abs((int)ptr[s][i] - (int)last[i]);
            bool dup = d < W * H / 4;  // (mean difference < 1/16 level: noise-free repeat; the dithering of distant
            ndup += dup;               //  objects alone changes a few thumbnail texels)
            pat[nframes % 120] = d == 0 ? '=' : dup ? '-' : '.';
            { static long lo = -2, hi; if (lo == -2) { const char *e = getenv("XCDE_DUP_VALUES"); lo = e ? atol(e) : -1; hi = lo + 90; }
              if (lo >= 0 && nframes >= lo && nframes < hi) LOG("[dupv] %d %d\n", nframes, d); }
            if (++nframes % 120 == 0) { pat[120] = 0; LOG("[dup] %d of 120 frames repeated the previous image: %s\n", ndup, pat); ndup = 0; }
        }
        memcpy(last, ptr[s], sizeof last);
        have_last = 1;
    }
    vk_full_barrier(cb);
    VkImageBlit bl = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .srcOffsets = {{0, 0, 0}, {(int32_t)b->width, (int32_t)(b->height * 55 / 100), 1}},  // (top 55 %: no dialogue box)
                      .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .dstOffsets = {{0, 0, 0}, {W, H, 1}}};
    vkCmdBlitImage(cb, b->image, VK_IMAGE_LAYOUT_GENERAL, img, VK_IMAGE_LAYOUT_GENERAL, 1, &bl, VK_FILTER_LINEAR);
    vk_full_barrier(cb);
    VkBufferImageCopy c = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {W, H, 1}};
    vkCmdCopyImageToBuffer(cb, img, VK_IMAGE_LAYOUT_GENERAL, buf[s], 1, &c);
    vk_full_barrier(cb);
    seq[s] = vk_pending_seq();
    slot++;
}

// [XCDE] T224 diagnostics: a video of real-time play without the capture stalls of XCDE_SHOTS (animation steps, frame
// pacing, flicker): every presented game image, scaled to 480x270 on the GPU and read back 3 frames later (no stall),
// appended to build/rec.raw (RGBA; XCDE_REC_SIZE, XCDE_REC_OUT) with each frame's number and present time (ns) in build/rec.txt.
// F10 starts / stops it (at most 1200 frames a recording, each one overwrites the last), or XCDE_REC=<from>:<to>
// (presented frames).
// [XCDE] T240 XCDE_REC_SCAN=<dir>[:<threshold=40>[:<block px=40>]]: the recorder's frames are not written but searched
// as they come (tools/flicker_scan.py in the game, for tours of hours): a block of the image that differs from both the
// frame k before and k after (k = 1, 2, 3, 4, 6, 8) much more than those two differ from each other - an area wrong for
// a few frames that comes back. Each hit is logged ("[flicker]") and saved as <dir>/flicker_<frame>.ppm (before, the
// frame, after side by side). Camera cuts don't count (before and after differ too).
enum { SCAN_RING = 17 };
static void scan_frame(const uint8_t *px, uint32_t W, uint32_t H, uint64_t fno) {
    static char dir[400];
    static float thr = 40;
    static uint32_t B = 40, bw, bh;
    static uint8_t *ring[SCAN_RING];
    static float *lum[SCAN_RING];
    static uint64_t num[SCAN_RING], n, last_hit;
    static int nhits;
    if (!bw) {
        const char *e = getenv("XCDE_REC_SCAN");
        const char *c = strchr(e[0] && e[1] == ':' ? e + 2 : e, ':');  // (past a drive letter: E:/...)
        snprintf(dir, sizeof dir, "%.*s", c ? (int)(c - e) : (int)strlen(e), e);
        if (c) { thr = strtof(c + 1, (char **)&c); if (*c == ':') B = (uint32_t)atoi(c + 1); }
        if (B < 8) B = 8;
        bw = W / B, bh = H / B;
        for (int i = 0; i < SCAN_RING; i++) ring[i] = malloc((size_t)W * H * 4), lum[i] = calloc(bw * bh, sizeof(float));
        LOG("[flicker] scanning %ux%u frames, %ux%u px blocks, threshold %.0f, hits in %s\n", W, H, B, B, thr, dir);
    }
    int s = (int)(n % SCAN_RING);
    memcpy(ring[s], px, (size_t)W * H * 4);
    num[s] = fno;
    float *L = lum[s];
    for (uint32_t by = 0; by < bh; by++)
        for (uint32_t bx = 0; bx < bw; bx++) {
            uint32_t sum = 0;
            for (uint32_t y = by * B; y < by * B + B; y += 2) {
                const uint8_t *p = px + ((size_t)y * W + bx * B) * 4;
                for (uint32_t x = 0; x < B; x += 2, p += 8) sum += p[0] * 77u + p[1] * 150u + p[2] * 29u;
            }
            L[by * bw + bx] = sum / 256.0f / ((B / 2) * (B / 2));
        }
    n++;
    if (n < SCAN_RING) return;
    // the frame 8 back (all its windows have their after frame now)
    static const int ks[] = {1, 2, 3, 4, 6, 8};
    uint64_t mi = n - 1 - 8;
    float best = 0;
    int bk = 0;
    uint32_t bb = 0;
    for (int ki = 0; ki < 6; ki++) {
        int k = ks[ki];
        const float *a = lum[(mi - k) % SCAN_RING], *m = lum[mi % SCAN_RING], *b = lum[(mi + k) % SCAN_RING];
        for (uint32_t i = 0; i < bw * bh; i++) {
            float da = fabsf(m[i] - a[i]), db = fabsf(m[i] - b[i]);
            float sc = (da < db ? da : db) - fabsf(a[i] - b[i]) * 2;
            if (sc > best) best = sc, bk = k, bb = i;
        }
    }
    uint64_t f = num[mi % SCAN_RING];
    if (best <= thr || (last_hit && f - last_hit <= 8)) return;
    last_hit = f;
    // tools/flicker_view.py's tests, so that only the hits worth a look are saved: "calm" - the whole before and after
    // images nearly the same (in fast action and flashes they match by chance: a fault there can't be told from an
    // effect); "back" - the block's pixels come back as they were (before and after alike pixel by pixel, the frame
    // unlike both). XCDE_REC_SCAN_ALL=1 saves every hit.
    const float *la = lum[(mi - bk) % SCAN_RING], *lb = lum[(mi + bk) % SCAN_RING];
    float calm = 0;
    for (uint32_t i = 0; i < bw * bh; i++) calm += fabsf(la[i] - lb[i]);
    calm /= bw * bh;
    const uint8_t *im[3] = {ring[(mi - bk) % SCAN_RING], ring[mi % SCAN_RING], ring[(mi + bk) % SCAN_RING]};
    double dab = 0, dma = 0, dmb = 0, mm = 0, ma = 0;
    for (uint32_t y = (bb / bw) * B; y < (bb / bw) * B + B; y++)
        for (uint32_t x = (bb % bw) * B; x < (bb % bw) * B + B; x++) {
            size_t o = ((size_t)y * W + x) * 4;
            int ya = im[0][o] * 77 + im[0][o + 1] * 150 + im[0][o + 2] * 29, ym = im[1][o] * 77 + im[1][o + 1] * 150 + im[1][o + 2] * 29,
                yb = im[2][o] * 77 + im[2][o + 1] * 150 + im[2][o + 2] * 29;
            dab += abs(ya - yb), dma += abs(ym - ya), dmb += abs(ym - yb), mm += ym, ma += ya + yb;
        }
    bool back = dab < 0.35 * (dma < dmb ? dma : dmb), dark = mm < ma / 2 - 20.0 * 256 * B * B;
    LOG("[flicker] frame %llu: block %u,%u (px %u,%u), %d-frame window, strength %.0f%s%s%s\n", (unsigned long long)f, bb % bw, bb / bw,
        (bb % bw) * B, (bb / bw) * B, bk, best, calm < 6 ? " calm" : "", back ? " back" : "", dark ? " dark" : "");
    static int all = -1;
    if (all < 0) all = getenv("XCDE_REC_SCAN_ALL") != NULL;
    if (!all && !(calm < 6 && back)) return;
    if (nhits++ >= 3000) return;
    char path[512];
    snprintf(path, sizeof path, "%s/flicker_%08llu.ppm", dir, (unsigned long long)f);
    FILE *fp = fopen(path, "wb");
    if (!fp) return;
    fprintf(fp, "P6\n%u %u\n255\n", W * 3, H);
    uint8_t *rowb = malloc((size_t)W * 9);
    for (uint32_t y = 0; y < H; y++) {
        for (int j = 0; j < 3; j++)
            for (uint32_t x = 0; x < W; x++) memcpy(rowb + ((size_t)j * W + x) * 3, im[j] + ((size_t)y * W + x) * 4, 3);
        fwrite(rowb, 1, (size_t)W * 9, fp);
    }
    free(rowb);
    fclose(fp);
}

static volatile int g_rec_key;  // (F10: 1 start, 2 stop)
void vk_rec_toggle(void) { g_rec_key = g_rec_key == 1 || g_rec_key == 3 ? 2 : 1; }
static void rec_frame(TexBackend *b) {
    static int on = -1;
    static long from, to;
    static int scan = -1;
    if (on < 0) { const char *e = getenv("XCDE_REC"); on = e && sscanf(e, "%ld:%ld", &from, &to) == 2 && to > from; if (!on) from = to = -1; on = 1; }
    if (scan < 0 && (scan = getenv("XCDE_REC_SCAN") != NULL) && from < 0) from = 0, to = 0x7fffffffL;
    if (g_rec_key == 1) { from = (long)total_frames; to = from + 1200; g_rec_key = 3; LOG("[rec] recording from frame %ld (F10 stops)\n", from); }
    if (g_rec_key == 2) { to = (long)total_frames; g_rec_key = 0; LOG("[rec] stopped at frame %ld\n", to); }
    if (!on || !b || !b->image || (b->aspect & ~VK_IMAGE_ASPECT_COLOR_BIT)) return;
    if (from < 0) return;
    enum { N = 4 };
    static uint32_t W = 0, H = 0;  // XCDE_REC_SIZE=<w>x<h> (default 480x270; 1280x720 for glitch hunting)
    if (!W) { const char *e = getenv("XCDE_REC_SIZE"); if (!e || sscanf(e, "%ux%u", &W, &H) != 2 || !W || !H) W = 480, H = 270; }
    static VkImage img; static VmaAllocation img_mem;
    static VkBuffer buf[N]; static VmaAllocation buf_mem[N]; static uint8_t *ptr[N]; static uint64_t seq[N], when[N], fno[N];
    static int slot;
    static FILE *raw, *txt;
    long f = (long)total_frames;
    VkCommandBuffer cb = vk_cmd();
    if (!img) {
        VkImageCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R8G8B8A8_UNORM,
                                .extent = {W, H, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
                                .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
        VmaAllocationCreateInfo ai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
        if (vmaCreateImage(g_vk.vma, &ci, &ai, &img, &img_mem, NULL) != VK_SUCCESS) { on = 0; return; }
        vk_image_init_layout(cb, img, VK_IMAGE_ASPECT_COLOR_BIT);
        for (int i = 0; i < N; i++) {
            VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = W * H * 4, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
            VmaAllocationCreateInfo bai = {.usage = VMA_MEMORY_USAGE_AUTO_PREFER_HOST,
                                           .flags = VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT | VMA_ALLOCATION_CREATE_MAPPED_BIT};
            VmaAllocationInfo info;
            if (vmaCreateBuffer(g_vk.vma, &bi, &bai, &buf[i], &buf_mem[i], &info) != VK_SUCCESS) { on = 0; return; }
            ptr[i] = info.pMappedData;
        }
    }
    if (!scan && (long)total_frames == from && seq[slot % N] == 0) {  // (a new recording: new files)
        if (raw) fclose(raw);
        if (txt) fclose(txt);
        char rp[512], tp[512];  // XCDE_REC_OUT=<path without extension> (default build/rec): .raw and .txt
        const char *o = getenv("XCDE_REC_OUT");
        snprintf(rp, sizeof rp, "%s.raw", o ? o : "build/rec");
        snprintf(tp, sizeof tp, "%s.txt", o ? o : "build/rec");
        raw = fopen(rp, "wb");
        txt = fopen(tp, "w");
        if (!raw || !txt) { from = to = -1; return; }
    }
    if (!raw && !scan) return;
    int s = slot % N;
    if (seq[s]) {  // the oldest slot's copy: done by now (or wait for it), written out
        if (vk_completed_seq() < seq[s]) vk_wait_seq(seq[s]);
        vmaInvalidateAllocation(g_vk.vma, buf_mem[s], 0, VK_WHOLE_SIZE);
        if (scan) scan_frame(ptr[s], W, H, fno[s]);
        else fwrite(ptr[s], 1, W * H * 4, raw), fprintf(txt, "%llu %llu\n", (unsigned long long)fno[s], (unsigned long long)when[s]);
        seq[s] = 0;
    }
    if (f >= to && g_rec_key == 3) { g_rec_key = 0; LOG("[rec] 1200 frames recorded\n"); }
    if (f < from || f >= to) {
        if (f >= to && raw) { fflush(raw); fflush(txt); }
        return;
    }
    vk_full_barrier(cb);
    VkImageBlit bl = {.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .srcOffsets = {{0, 0, 0}, {(int32_t)b->width, (int32_t)b->height, 1}},
                      .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .dstOffsets = {{0, 0, 0}, {W, H, 1}}};
    vkCmdBlitImage(cb, b->image, VK_IMAGE_LAYOUT_GENERAL, img, VK_IMAGE_LAYOUT_GENERAL, 1, &bl, VK_FILTER_LINEAR);
    vk_full_barrier(cb);
    VkBufferImageCopy c = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {W, H, 1}};
    vkCmdCopyImageToBuffer(cb, img, VK_IMAGE_LAYOUT_GENERAL, buf[s], 1, &c);
    vk_full_barrier(cb);
    seq[s] = vk_pending_seq();
    when[s] = plat_now_ns();
    fno[s] = (uint64_t)f;
    slot++;
}

void backend_present(NvnTexture *t) {
    {   // [XCDE] T240 XCDE_TRACE_PRESENT=<from>:<to>: each presented frame's texture and the draws since the last present
        // (a frame shown out of order: was the image drawn that frame, or an older one presented again?)
        static long tf = -1, tt;
        static uint64_t last_draws;
        extern uint64_t vk_draws_total(void);
        if (tf < 0) { tf = 0; if (!getenv("XCDE_TRACE_PRESENT") || sscanf(getenv("XCDE_TRACE_PRESENT"), "%ld:%ld", &tf, &tt) != 2) tf = tt = 0; }
        uint64_t dn = vk_draws_total();
        if ((long)total_frames >= tf && (long)total_frames <= tt && tt)
            LOG("[present] frame %llu: texture %p (%ux%u), %llu draws since the last present\n", (unsigned long long)total_frames, (void *)t,
                t ? t->width : 0, t ? t->height : 0, (unsigned long long)(dn - last_draws));
        last_draws = dn;
        static uint64_t wa, wn;  // (XCDE_WATCH_MEM: the watched range's first words at each traced present)
        static int wi;
        if (!wi) { wi = 1; const char *e = getenv("XCDE_WATCH_MEM"); if (e) sscanf(e, "%llx:%llx", (unsigned long long *)&wa, (unsigned long long *)&wn); }
        if (wn && (long)total_frames >= tf && (long)total_frames <= tt && tt) {
            const float *w = (const float *)(uintptr_t)wa;
            LOG("[watchmem] present %llu: %g %g %g %g%c", (unsigned long long)total_frames, w[0], w[1], w[2], w[3], 10);
        }
    }
    {   // [XCDE] T240 test: XCDE_TEST_HITCH=<from>:<to>:<ms> - every presented frame in between takes <ms> longer (a hitch
        // without a pipeline wait: does the game's own response to a long frame darken hair as a build wait did?)
        static long hf = -1, ht, hms;
        if (hf < 0) { hf = 0; if (!getenv("XCDE_TEST_HITCH") || sscanf(getenv("XCDE_TEST_HITCH"), "%ld:%ld:%ld", &hf, &ht, &hms) != 3) hf = ht = 0; }
        if (ht && (long)total_frames >= hf && (long)total_frames <= ht) SDL_Delay((uint32_t)hms);
    }
    {   // [XCDE] T240: a loading frame waits for the shader / pipeline build work (exec.c vk_prewarm_hold)
        extern uint64_t vk_draws_total(void);
        extern void vk_prewarm_hold(uint64_t frame_draws);
        static uint64_t last;
        uint64_t dn = vk_draws_total();
        vk_prewarm_hold(dn - last);
        last = dn;
    }
    g_last_presented = t;
    TexBackend *b = vk_tex(t, true);
    b->presented = true;
    vk_end_pass();
    dup_check(b);
    rec_frame(b);
    {   // [XCDE] "[hitch]": a frame over 25 ms and twice the recent average since the last present - what the render worker waited for in it (draws
        // waiting for pipelines; pipelines made from the disk cache / linked from libraries / compiled whole, count +
        // time on the build threads; bytes uploaded). At most 300 lines a run; XCDE_LOG_HITCH=0: off.
        static int on = -1, n;
        static uint64_t last, prev[9];
        if (on < 0) { const char *e = getenv("XCDE_LOG_HITCH"); on = !(e && *e == '0'); }
        extern void vk_hitch_counters(uint64_t c[9]);
        uint64_t now = SDL_GetTicksNS(), c[9];
        vk_hitch_counters(c);
        static double avg = 16.7e6;  // (recent frame time: a hitch = over twice it, and over 25 ms)
        uint64_t dt = last ? now - last : 0;
        if (last && dt > 25000000 && dt > 1.35 * avg && total_frames > 300) {  // (XCDE_HITCH_SAMPLE=1: what the CPU did in it)
            extern void diag_hitch_sample(double ms);
            diag_hitch_sample(dt / 1e6);
        }
        if (on && last && dt > 25000000 && dt > 2 * avg && n < 300 && total_frames > 300) {
            n++;
            LOG("[hitch] frame %llu: %.1f ms | draws waited %.1f ms (%llu) | pipelines cached %llu (%.1f ms) linked %llu (%.1f ms) whole %llu (%.1f ms) | upload %.1f MB\n",
                (unsigned long long)total_frames, (now - last) / 1e6, (c[0] - prev[0]) / 1e6, (unsigned long long)(c[1] - prev[1]),
                (unsigned long long)(c[3] - prev[3]), (c[2] - prev[2]) / 1e6, (unsigned long long)(c[5] - prev[5]), (c[4] - prev[4]) / 1e6,
                (unsigned long long)(c[7] - prev[7]), (c[6] - prev[6]) / 1e6, (c[8] - prev[8]) / 1048576.0);
        }
        if (dt && dt < 200000000) avg = avg * 0.95 + dt * 0.05;
        last = now;
        memcpy(prev, c, sizeof prev);
    }
    static const float black[4] = {0, 0, 0, 1};
    uint64_t t0 = SDL_GetTicksNS();
    // [XCDE] perf: a hidden deterministic run (tests) only draws into the window when that frame is captured or hashed.
    // Windows composes even a hidden window's presents at the monitor's refresh: every test run was capped at exactly
    // 60 fps wall-clock (measured: 145-150 fps in light scenes without the present, frame 6400 vs 3022 after 58 s).
    static int headless = -1;
    if (headless < 0) headless = getenv("LARECOMP_HIDDEN") && diag_deterministic() && !getenv("XCDE_PRESENT_ALWAYS");
    static long win_shot = -1;
    if (win_shot < 0) win_shot = getenv("LARECOMP_WINDOW_SHOT") ? atol(getenv("LARECOMP_WINDOW_SHOT")) : 0;
    bool shot = win_shot && (long)total_frames + 1 == win_shot;
    const char *xshot = diag_shot_path(total_frames + 1);
    extern bool diag_flicker_wanted(void);
    bool want_window = !headless || shot || xshot || diag_hash_wanted() || diag_flicker_wanted();
    bool have = want_window && vk_frame_begin(black);
    uint64_t nd = SDL_GetTicksNS() - t0;
    if (nd > 30000000) {
        static int warned;
        if (warned++ < 20) LOG("[vk] acquire blocked %llums\n", (unsigned long long)(nd / 1000000));
    }
    double vx = 0, vy = 0, vw = 0, vh = 0;  // the game image's placement in the window
    float crop[4] = {0, 0, 1, 1};           // uv origin and size
    if (have || !want_window) {  // (headless frames still advance the scale / widescreen state as a presented one would)
        double dw = g_vk.sc_extent.width, dh = g_vk.sc_extent.height;
        extern void widescreen_frame_end(uint64_t frame);
        widescreen_frame_end(total_frames);
        extern void widescreen_set_factor(float f);
        extern bool widescreen_allowed(void);
        // render scale + placement in the window: runtime/nvn/output_scale.c (Video tab "Internal resolution");
        // no GPU timer here (-1): dynamic resolution goes by the frame time
        OutScale os;
        output_scale(dw, dh, widescreen_allowed(), SDL_GetTicksNS() / 1e9, -1, &os);
        double sx = os.sx, sy = os.sy, shape = os.shape;
        vx = os.vx, vy = os.vy, vw = os.vw, vh = os.vh;
        // interiors / dungeons: their 16:9 centre, or the part inside a room wider than one screen
        extern void widescreen_present_crop(uint64_t, double, float *, double *, double *, double *, double *);
        widescreen_present_crop(total_frames, shape, crop, &vx, &vy, &vw, &vh);
        widescreen_set_factor((float)shape);
        renderer_set_scale((float)sx, (float)sy);
        memcpy(g_shot_crop, crop, sizeof crop);
    }
    if (have) {
        VkCommandBuffer cb = vk_cmd();
        float pv[8] = {renderer_origin_lower_left() ? 1.0f : 0.0f, 0, 0, 0, crop[0], crop[1], crop[2], crop[3]};
        vk_present_draw(cb, b, (float)vx, (float)vy, (float)vw, (float)vh, pv);
        static long menu_at = -1;
        if (menu_at < 0) menu_at = getenv("LARECOMP_MENU_AT") ? atol(getenv("LARECOMP_MENU_AT")) : 0;
        if (menu_at && (long)total_frames + 1 == menu_at) { extern void menu_test_open(void); menu_test_open(); }
        menu_render((void *)cb, g_vk.sc_extent.width, g_vk.sc_extent.height);
        vk_frame_end(shot ? "build/window.png" : xshot);
        {   // XCDE_PRESENT_STATS=1: game frame intervals (first present of each), every 120 frames
            static int on = -1;
            if (on < 0) on = getenv("XCDE_PRESENT_STATS") != NULL;
            static uint64_t lastp, mn = ~0ull, mx, sum, cnt, n17, n33, n50;
            uint64_t now = SDL_GetTicksNS();
            if (on && lastp) {
                uint64_t d = now - lastp;
                if (d < mn) mn = d;
                if (d > mx) mx = d;
                sum += d; cnt++;
                n17 += d < 25000000; n33 += d >= 25000000 && d < 41700000; n50 += d >= 41700000;
                if (cnt == 120) {
                    LOG("[present] 120 frames: min %.1f avg %.1f max %.1f ms | <25 ms %llu, 25-42 %llu, >42 %llu\n", mn / 1e6, sum / 1e6 / cnt,
                        mx / 1e6, (unsigned long long)n17, (unsigned long long)n33, (unsigned long long)n50);
                    mn = ~0ull; mx = sum = cnt = n17 = n33 = n50 = 0;
                }
            }
            lastp = now;
        }
        for (int k = repeat_presents(); k > 1; k--) {  // (see repeat_presents)
            extern void vk_present_redraw(VkCommandBuffer cb);
            if (!vk_frame_begin(black)) break;
            vk_present_redraw(vk_cmd());
            menu_render((void *)vk_cmd(), g_vk.sc_extent.width, g_vk.sc_extent.height);
            vk_frame_end(NULL);
        }
        extern void vk_gmem_check(uint64_t frame);
        vk_gmem_check(total_frames + 1);
        if (shot && getenv("LARECOMP_EXIT_AFTER_SHOT")) { fflush(stderr); _exit(0); }
    } else {
        renderer_submit();
    }
    extern void vk_prof_frame(uint64_t frame, uint64_t present_ns);
    vk_prof_frame(total_frames, SDL_GetTicksNS() - t0);
    frames++;
    total_frames++;
    g_frame_counter++;
    diag_frame_tick(total_frames);
    extern void vk_pace_frame(void);
    vk_pace_frame();  // (exec.c: the game's 30 fps mode when frames don't fit 60)
    extern void input_frame(uint64_t frame);
    input_frame(total_frames);
    static long slow_ms = -1;
    if (slow_ms < 0) slow_ms = getenv("LARECOMP_SLOW_FRAME_MS") ? atol(getenv("LARECOMP_SLOW_FRAME_MS")) : 0;
    static long slow_until = -1;  // LARECOMP_SLOW_FRAME_UNTIL=<frame>: the stall ends there (frame pacing recovery tests)
    if (slow_until < 0) slow_until = getenv("LARECOMP_SLOW_FRAME_UNTIL") ? atol(getenv("LARECOMP_SLOW_FRAME_UNTIL")) : 0;
    if (slow_ms > 0 && total_frames > 2600 && (!slow_until || (long)total_frames < slow_until)) SDL_Delay((Uint32)slow_ms);
    extern void fnprof_frame(uint64_t frame);
    fnprof_frame(total_frames);
    extern void warp_frame(uint64_t frame);
    warp_frame(total_frames);
    extern void reboot_test_frame(uint64_t frame);  // runtime/main.c (LARECOMP_REBOOT_AT)
    reboot_test_frame(total_frames);
    extern void save_editor_frame(uint64_t frame);
    save_editor_frame(total_frames);
    extern void vk_level_change_check(void);
    vk_level_change_check();
    static long shot_every = -1;
    if (shot_every < 0) { const char *e = getenv("LARECOMP_SCREENSHOT_EVERY"); shot_every = e ? atol(e) : 0; }
    extern bool g_debug_frame;
    static long debug_at = -1;
    if (debug_at < 0) { const char *e = getenv("LARECOMP_DEBUG_FRAME"); debug_at = e ? atol(e) : 0; }
    extern volatile int g_debug_frame_request;
    if (g_debug_frame_request) { g_debug_frame_request = 0; debug_at = (long)total_frames + 1; }
    // LARECOMP_DEBUG_FRAMES=<n> (with LARECOMP_DEBUG_FRAME / F9): dump n consecutive frames (build/pass_<frame>_NNN.png)
    static long debug_n = -1;
    if (debug_n < 0) { const char *e = getenv("LARECOMP_DEBUG_FRAMES"); debug_n = e && atol(e) > 1 ? atol(e) : 1; }
    g_debug_frame = debug_at && total_frames >= (uint64_t)debug_at && total_frames < (uint64_t)debug_at + (uint64_t)debug_n;
    {   // LARECOMP_GPUPROF_AT=<frame>[,<frame>...]: GPU time per pass of those frames ("[gpuprof]" in the log)
        extern bool g_gpuprof_frame;
        extern void vk_gpuprof_report(void);
        if (g_gpuprof_frame) { g_gpuprof_frame = false; vk_gpuprof_report(); }
        const char *e = getenv("LARECOMP_GPUPROF_AT");
        for (const char *p = e; p && *p;) {
            long at = strtol(p, (char **)&p, 10);
            if (at == (long)total_frames) { g_gpuprof_frame = true; break; }
            if (*p == ',') p++; else break;
        }
    }
    if (g_debug_frame) LOG("===== debug frame %llu =====\n", (unsigned long long)total_frames);
    {   // LARECOMP_SHOT_AT=<frame>,<frame>,... (ascending): the game image at those frames -> build/frames/frame_N.png
        static const char *next;
        static int init;
        if (!init) { init = 1; next = getenv("LARECOMP_SHOT_AT"); if (next) mkdir("build/frames", 0755); }
        while (next && *next) {
            long at = strtol(next, (char **)&next, 10);
            if ((long)total_frames < at) { while (next > getenv("LARECOMP_SHOT_AT") && next[-1] != ',') next--; break; }
            if ((long)total_frames == at) {
                char path[256];
                snprintf(path, sizeof path, "build/frames/frame_%05llu.png", (unsigned long long)total_frames);
                renderer_save_texture_tex(b, path);
            }
            if (*next == ',') next++;
        }
    }
    static long shot_from = -1;
    if (shot_from < 0) { const char *e = getenv("LARECOMP_SCREENSHOT_FROM"); shot_from = e ? atol(e) : 0; }
    if (shot_every && total_frames % shot_every == 0 && (long)total_frames >= shot_from) {
        char path[256];
        if (shot_from) mkdir("build/frames", 0755);
        snprintf(path, sizeof path, shot_from ? "build/frames/frame_%05llu.png" : "build/frame_%05llu.png",
                 (unsigned long long)total_frames);
        renderer_save_texture_tex(b, path);
        // a series (SCREENSHOT_FROM) runs on until LARECOMP_WINDOW_SHOT exits
        if (getenv("LARECOMP_EXIT_AFTER_SHOT") && !shot_from) { fflush(stderr); _exit(0); }
    }
    double now = SDL_GetTicks() / 1000.0;
    static double fps_iv = -1, prev_present, max_gap;
    if (fps_iv < 0) fps_iv = getenv("LARECOMP_FPS_INTERVAL") ? atof(getenv("LARECOMP_FPS_INTERVAL")) : 2.0;
    if (prev_present > 0 && now - prev_present > max_gap) max_gap = now - prev_present;
    prev_present = now;
    if (now - last_fps_time >= fps_iv) {
        extern const char *game_level_name(void);
        if (last_fps_time > 0)
            LOG("[vk] t=%.1f frame %llu %.1f fps max %.0fms level %s (%s)\n", now, (unsigned long long)total_frames,
                frames / (now - last_fps_time), max_gap * 1000.0, game_level_name(), renderer_stats());
        if (g_settings.show_fps && last_fps_time > 0 && window) {  // [XCDE] launcher option: frame rate in the title bar
            char title[128];
            snprintf(title, sizeof title, "Xenoblade Chronicles: Definitive Edition (Recomp) - %.0f fps", frames / (now - last_fps_time));
            SDL_SetWindowTitle(window, title);
        }
        {   // [XCDE] the pipeline cache is also written every 2 minutes, not only at a clean exit: a crash or a killed
            // process used to lose every pipeline built in the session (the next start compiled them all again)
            // [XCDE] on a thread of its own, and only when pipelines were made since: serializing + writing the 100+ MB
            // cache on the render thread was a ~100 ms freeze every 2 minutes (user: "it still stutters"; [hitch] log
            // with nothing else in those frames)
            static double last_pc_save;
            static uint64_t made_at_save;
            if (!last_pc_save) last_pc_save = now;
            if (now - last_pc_save >= 120) {
                last_pc_save = now;
                extern void vk_hitch_counters(uint64_t c[9]);
                uint64_t c[9];
                vk_hitch_counters(c);
                uint64_t made = c[3] + c[5] + c[7];
                if (made != made_at_save) { made_at_save = made; vk_pipeline_cache_save_async(); }
            }
        }
        max_gap = 0;
        frames = 0;
        last_fps_time = now;
    }
}

// ================================================================== UI thread
void vk_exec_init(void);
void vk_shaders_init(void);

// exit() from any thread: let the GPU finish, keep the pipeline cache, then end the process without the DLL
// teardown (driver / validation-layer threads can stall it for minutes while the game's threads still run).
static _Noreturn void quick_exit_handler(void) {
    static int trace = -1;
    if (trace < 0) trace = getenv("LARECOMP_VK_TRACE") != NULL;
    if (trace) LOG("[vk] exit: waiting for the GPU\n");
    if (g_vk.dev) {
        sc_wait_idle(g_vk.dev);
        if (trace) LOG("[vk] exit: saving the pipeline cache\n");
        for (int i = 0; i < 500 && atomic_load(&pc_saving); i++) SDL_Delay(10);  // (a periodic save still writing)
        vk_pipeline_cache_save();
    }
    if (trace) LOG("[vk] exit: terminating\n");
    fflush(stdout);
    fflush(stderr);
#if defined(_WIN32) || defined(__linux__)
    plat_terminate();
#endif
    abort();  // plat_terminate must not return.
}

static _Noreturn void ui_finish_host_exit(void) {
    LOG("[am] native close permitted\n");
#ifdef __linux__
    // [XCDE] LINUX-033: retain AM's cleanup/exit-lock deadline, then stop
    // producers and drain the renderer before GPU/cache work and termination.
    // Do not enter libc's graphics-library teardown with a live NGX worker.
    extern void backend_drain(void);
    LOG("[vk] exit: stopping guest producers and draining render work\n");
    applet_ui_finish_exit(backend_drain, quick_exit_handler);
    abort();  // the process-finishing callback must not return.
#else
    exit(0);
#endif
}

void ui_window_init(void) {
    if (window) return;
    atexit(quick_exit_handler);
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    settings_load();
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) FATAL("SDL_Init: %s\n", SDL_GetError());
    int win_w = g_window_w, win_h = g_window_h;  // [XCDE] xcde.ini
    if (getenv("LARECOMP_WINDOW")) sscanf(getenv("LARECOMP_WINDOW"), "%dx%d", &win_w, &win_h);
    SDL_WindowFlags wflags = SDL_WINDOW_VULKAN | SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY;
    if (getenv("LARECOMP_HIDDEN")) wflags |= SDL_WINDOW_HIDDEN;
    {   // scripted test runs (user input ignored: runtime/hle/input.c input_user_blocked) open without taking the
        // keyboard focus from whatever the player is doing
        const char *v = getenv("LARECOMP_NO_USER_INPUT");
        bool scripted = v ? atoi(v) != 0 : (getenv("LARECOMP_INPUT") || getenv("LARECOMP_DOORJUMP_TEST") || getenv("LARECOMP_PLACE") ||
                                            getenv("LARECOMP_HOST_INPUT") || getenv("LARECOMP_BIND_TEST"));
        if (scripted) SDL_SetHint(SDL_HINT_WINDOW_ACTIVATE_WHEN_SHOWN, "0");
    }
    window = SDL_CreateWindow("Xenoblade Chronicles: Definitive Edition (Recomp)", win_w, win_h, wflags);
    if (!window) FATAL("SDL_CreateWindow: %s\n", SDL_GetError());
    rt_window_icon(window);
    // the Fullscreen setting applies from the start screen on (not only once the game runs); test windows stay windows
    if (g_settings.fullscreen && !getenv("LARECOMP_WINDOW") && !getenv("LARECOMP_HIDDEN")) SDL_SetWindowFullscreen(window, true);
    {   // [XCDE] DLSS: Streamline must be loaded before the Vulkan instance (dlss.cpp)
        extern bool dlss_init_early(void);
        dlss_init_early();
    }
    create_instance();
    if (!SDL_Vulkan_CreateSurface(window, g_vk.inst, NULL, &g_vk.surface)) FATAL("SDL_Vulkan_CreateSurface: %s\n", SDL_GetError());
    pick_device();
    create_device();
    create_swapchain();
    // [XCDE] LINUX-089/090: first camera and render target use the same selected
    // ratio. Match display follows the drawable; explicit choices fit inside it.
    if (g_vk.sc_extent.height)
        xcde_aspect_set_factor((float)xcde_aspect_target_factor(
            (double)g_vk.sc_extent.width / (double)g_vk.sc_extent.height / (16.0 / 9.0)));
    vk_exec_init();
    vk_shaders_init();
}

SDL_Window *ui_window(void) { return window; }

void backend_init(void) {
    while (!atomic_load(&ui_ready)) SDL_Delay(1);
    LOG("[vk] %s, swapchain %ux%u\n", g_vk.props.deviceName, g_vk.sc_extent.width, g_vk.sc_extent.height);
}

// ---- in-place reboot (runtime/main.c teardown; main thread, guest threads stopped)
void backend_reset(void) {
    if (!g_vk.dev) return;
    // [XCDE] LINUX-017: stopped guests can still have queued renderer jobs.
    extern void backend_drain(void);
    backend_drain();
    sc_wait_idle(g_vk.dev);
    extern void vk_textures_reset(void);
    extern void vk_exec_reset(void);
    // [XCDE] LINUX-017: invalidate borrowed texture pointers before freeing textures.
    vk_exec_reset();
    vk_textures_reset();
    g_last_presented = NULL;
}
void backend_guest_memory_reset(void) {}  // (exec.c re-imports the heap on first use)
void backend_clear_window(void) {
    static const float black[4] = {0, 0, 0, 1};
    if (g_vk.dev && vk_frame_begin(black)) vk_frame_end(NULL);
}

// [XCDE] LINUX-089: SDL device ownership stays on this UI event thread.
extern void input_poll_controller(void);
int ui_run(void) {
    ui_window_init();
    atomic_store(&ui_ready, true);
    for (;;) {
        if (rt_reboot_requested()) return rt_reboot_requested();  // (runtime/main.c tears the game down)
        input_poll_controller();
        SDL_Event e;
        while (SDL_WaitEventTimeout(&e, 16)) {
            // Also service recovery under continuous mouse/controller traffic.
            input_poll_controller();
            // [XCDE] LINUX-007: close requests notify the guest; LockExit keeps
            // its cleanup running until UnlockExit or the bounded host deadline.
            // Poll before input filtering, including continuous event traffic.
            if (applet_ui_should_exit(&e)) {
                ui_finish_host_exit();
            }
            if (e.type == SDL_EVENT_QUIT) continue;
            extern bool input_user_blocked(const SDL_Event *e);
            if (input_user_blocked(&e)) continue;  // scripted test runs: the real keyboard / mouse / pads do nothing (as metal.m)
            if (menu_handle_event(&e)) continue;
            input_handle_event(&e);
        }
        if (applet_ui_should_exit(NULL)) {
            ui_finish_host_exit();
        }
        menu_apply_window_requests(window);
    }
}
