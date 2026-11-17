// [XCDE] LINUX-126: actual resolve_feedback -> Vulkan copies -> exact pixel oracle.
// FEEDBACK_BASELINE lets the same authored sequence quantify the old policy's
// redundant copies; it does not accept stale pixels or weaken the oracle.
static void gpu_external_write(TexBackend *image) {
#ifdef FEEDBACK_BASELINE
    (void)image;vk_feedback_boundary();
#else
    vk_feedback_image_written(image);
#endif
}
int feedback_snapshot_gpu_cases(void) {
    VkImageCreateInfo ci={.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,.format=VK_FORMAT_R8G8B8A8_UNORM,
        .extent={16,8,1},.mipLevels=1,.arrayLayers=1,.samples=VK_SAMPLE_COUNT_1_BIT,.tiling=VK_IMAGE_TILING_OPTIMAL,
        .usage=VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_SAMPLED_BIT};
    backend=(TexBackend){.width=16,.height=8,.depth=1,.layers=1,.levels=1,.samples=1,.format=ci.format,
        .aspect=VK_IMAGE_ASPECT_COLOR_BIT,.base_type=VK_IMAGE_VIEW_TYPE_2D,.image_identity=1};
    VK_CHECK(feedback_gpu_create(&ci,&backend.image));feedback_gpu_init(backend.image,backend.aspect);
    TexBackend other=backend;other.image_identity=2;
    VK_CHECK(feedback_gpu_create(&ci,&other.image));feedback_gpu_init(other.image,other.aspect);
    reset();g_vk.feedback_loop=false;fragment.out_mask=15;
    feedback_gpu_clear(backend.image,0);feedback_gpu_clear(other.image,1);
    resolve_feedback(&program);assert(copies==1);feedback_gpu_expect(feedback_copy[0]->image,16,8,0);
    // Updating B must leave A's snapshot and pixels intact.
    feedback_gpu_clear(other.image,2);gpu_external_write(&other);resolve_feedback(&program);
#ifdef FEEDBACK_BASELINE
    assert(copies==2);
#else
    assert(copies==1);
#endif
    feedback_gpu_expect(feedback_copy[0]->image,16,8,0);
    // Updating A really must refresh its snapshot, including self-feedback.
    feedback_gpu_clear(backend.image,2);gpu_external_write(&backend);resolve_feedback(&program);
    feedback_gpu_expect(feedback_copy[0]->image,16,8,2);
    unsigned before=copies;NvnTexture shared=texture;entries[1].tex=&shared;
    resolve_feedback(&program);
#ifdef FEEDBACK_BASELINE
    assert(copies==before+1);
#else
    assert(copies==before);
#endif
    feedback_gpu_expect(feedback_copy[0]->image,16,8,2);
    // A normal self-writing draw retains the interval's original snapshot.
    feedback_gpu_clear(backend.image,1);feedback_written(&shared);before=copies;
    resolve_feedback(&program);assert(copies==before);feedback_gpu_expect(feedback_copy[0]->image,16,8,2);
    vk_feedback_boundary();resolve_feedback(&program);assert(copies==before+1);feedback_gpu_expect(feedback_copy[0]->image,16,8,1);
    // The global unknown-write fallback, frame boundary, allocation serial and
    // texture lifetime are not weakened by destination-aware invalidation.
    feedback_gpu_clear(backend.image,0);gpu_external_write(NULL);resolve_feedback(&program);feedback_gpu_expect(feedback_copy[0]->image,16,8,0);
    before=copies;frame++;resolve_feedback(&program);assert(copies==before+1);
    before=copies;backend.image_identity++;resolve_feedback(&program);assert(copies==before+1);
    vk_feedback_texture_gone(&shared);before=copies;resolve_feedback(&program);assert(copies==before+1);
    feedback_gpu_expect(feedback_copy[0]->image,16,8,0);
    printf("SNAPSHOT_GPU actual production copies=%u barriers=%u image allocations=%u; all RGBA8 readbacks exact; no game/WSI/performance claim\n",copies,barriers,images);
    return 0;
}
