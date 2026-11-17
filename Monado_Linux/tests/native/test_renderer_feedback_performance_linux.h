// [XCDE] LINUX-126: production-function recorder oracles. Authored textures only.
// Included in the generated fixture after the actual production functions.
static TexBackend unrelated_backend, distinct_backend;
static NvnTexture shared_texture, distinct_texture;
static void feedback_performance_tests(void) {
    assert(!feedback_stats.hits && !feedback_stats.misses && !feedback_stats.boundaries); // profiling is opt-in
    prof=1;memset(&feedback_stats,0,sizeof feedback_stats);memset(snaps,0,sizeof snaps);nsnaps=0;
    reset();g_vk.feedback_loop=false;fragment.out_mask=15;in_pass=true;
    resolve_feedback(&program);assert(copies==1 && ends==1 && feedback_stats.misses==1);
    uint64_t visibility=feedback_visibility;
    unrelated_backend=backend;unrelated_backend.image=(VkImage)(uintptr_t)999;unrelated_backend.image_identity+=10;
    vk_feedback_image_written(&unrelated_backend);
    assert(feedback_visibility==visibility);
    in_pass=true;resolve_feedback(&program);
    assert(copies==1 && in_pass && ends==1 && feedback_stats.hits==1 && feedback_stats.pass_breaks==1);
    assert(feedback_stats.bytes==16*8*4); // full RGBA8 source, once
    // An external write must refresh even the self-written interval snapshot.
    feedback_texture_written(&texture);resolve_feedback(&program);assert(copies==2 && !in_pass);
    assert(feedback_stats.invalidated==1 && feedback_stats.visibility==1);
    // Ordinary draw writes retain the original self-feedback image until a boundary.
    feedback_written(&texture);resolve_feedback(&program);assert(copies==2);
    // Unknown destinations and active depth-copy aliases keep the global fallback.
    vk_feedback_image_written(NULL);assert(feedback_visibility!=visibility);resolve_feedback(&program);assert(copies==3);
    visibility=feedback_visibility;naliases=1;vk_feedback_image_written(&unrelated_backend);naliases=0;
    assert(feedback_visibility!=visibility);resolve_feedback(&program);assert(copies==4);
    // Two live NVN objects over exactly the same backend share the full snapshot.
    shared_texture=texture;entries[1].tex=&shared_texture;
    resolve_feedback(&program);assert(copies==4 && feedback_stats.shared_hits==1);
    feedback_texture_written(&shared_texture);resolve_feedback(&program);assert(copies==5);
    // A different backend with an identical shape does not qualify as shared.
    distinct_backend=backend;distinct_backend.image=(VkImage)(uintptr_t)1001;distinct_backend.image_identity+=20;
    distinct_texture=texture;distinct_texture.backend=&distinct_backend;entries[1].tex=&distinct_texture;st.rt.color[0]=&distinct_texture;
    resolve_feedback(&program);assert(copies==6);
    distinct_backend.image_identity++;resolve_feedback(&program);assert(copies==7);
    frame++;resolve_feedback(&program);assert(copies==8);
    vk_feedback_texture_gone(&distinct_texture);resolve_feedback(&program);assert(copies==9);
    // Switching Vulkan handles and changing shape/allocation cannot reuse stale storage.
    unsigned old_retired=retired;distinct_backend.image=(VkImage)(uintptr_t)1002;distinct_backend.width=32;
    resolve_feedback(&program);assert(copies==10 && retired>old_retired && last_image.extent.width==32);
    TexBackend layered=backend;layered.format=VK_FORMAT_D32_SFLOAT_S8_UINT;layered.levels=2;layered.layers=3;
    assert(feedback_copy_bytes(&layered)==(16*8+8*4)*3*8);
    layered.format=VK_FORMAT_UNDEFINED;assert(feedback_copy_bytes(&layered)==0);
    assert(feedback_stats.misses==10 && feedback_stats.hits==3 && feedback_stats.shared_hits==1);
    assert(feedback_stats.image>=2 && feedback_stats.frame==1);
    prof=0;
    puts("PASS feedback performance: unrelated writes retain snapshots; exact shared-backend reuse; external/self-write distinction; unknown/alias/frame/image/lifetime fallbacks; opt-in bounded counters");
}
