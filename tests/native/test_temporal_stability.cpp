// [XCDE] LINUX-056: execute actual temporal prep GLSL on authored images.
// No guest/game code, window, translated shader, input or human state.
#include <vulkan/vulkan.h>
// Existing fixture enables synchronization2 but not dynamic rendering. Add only
// this feature to its otherwise unchanged NGX/runtime-style device creation.
static VkResult temporal_device(VkPhysicalDevice physical, const VkDeviceCreateInfo *info,
                                const VkAllocationCallbacks *allocator, VkDevice *device) {
    auto create = *info;
    auto f12 = *static_cast<const VkPhysicalDeviceVulkan12Features *>(info->pNext);
    auto f13 = *static_cast<const VkPhysicalDeviceVulkan13Features *>(f12.pNext);
    f13.dynamicRendering = VK_TRUE; f12.pNext = &f13; create.pNext = &f12;
    return vkCreateDevice(physical, &create, allocator, device);
}
#define vkCreateDevice temporal_device
#define main monado_temporal_legacy_fixture_main
#include "../../Monado_Linux/tests/native/test_dlss_linux.cpp"
#undef main
#undef vkCreateDevice
#include <shaderc/shaderc.h>
extern "C" const char *temporal_stability_source(const char *, int *);

struct Texture {
    VkImage image{}; VkImageView view{}; VkDeviceMemory memory{};
    VkFormat format; uint32_t width, height; bool initialized{};
    Texture(VkFormat f, uint32_t w, uint32_t h, bool output) : format(f), width(w), height(h) {
        VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
        ci.imageType = VK_IMAGE_TYPE_2D; ci.format = f; ci.extent = {w,h,1};
        ci.mipLevels = ci.arrayLayers = 1; ci.samples = VK_SAMPLE_COUNT_1_BIT;
        ci.tiling = VK_IMAGE_TILING_OPTIMAL; ci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        ci.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
        if (output) ci.usage |= VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
        VK_OK(vkCreateImage(device,&ci,nullptr,&image));
        VkMemoryRequirements need{}; vkGetImageMemoryRequirements(device,image,&need);
        VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        ai.allocationSize = need.size; ai.memoryTypeIndex = memory_type(need.memoryTypeBits,0,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        VK_OK(vkAllocateMemory(device,&ai,nullptr,&memory)); VK_OK(vkBindImageMemory(device,image,memory,0));
        VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        vi.image=image; vi.viewType=VK_IMAGE_VIEW_TYPE_2D; vi.format=f; vi.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        VK_OK(vkCreateImageView(device,&vi,nullptr,&view));
    }
    ~Texture() { vkDestroyImageView(device,view,nullptr); vkDestroyImage(device,image,nullptr); vkFreeMemory(device,memory,nullptr); }
    void general() {
        if(initialized)return;
        VkImageMemoryBarrier b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
        b.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;b.newLayout=VK_IMAGE_LAYOUT_GENERAL;
        b.srcQueueFamilyIndex=b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
        b.image=image;b.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        b.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT|VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,nullptr,0,nullptr,1,&b);
        initialized=true;
    }
};
static VkDescriptorSetLayout descriptor_layout;
static VkPipelineLayout pipeline_layout;
static VkPipeline pipeline;
static VkDescriptorPool descriptors;
static VkSampler sampler;
static VkShaderModule compile(const char *name) {
    int stage{};const char *source=temporal_stability_source(name,&stage);CHECK(source);
    auto compiler=shaderc_compiler_initialize();auto options=shaderc_compile_options_initialize();CHECK(compiler&&options);
    shaderc_compile_options_set_target_env(options,shaderc_target_env_vulkan,shaderc_env_version_vulkan_1_3);
    shaderc_compile_options_set_optimization_level(options,shaderc_optimization_level_performance);
    auto result=shaderc_compile_into_spv(compiler,source,strlen(source),stage==0?shaderc_vertex_shader:shaderc_fragment_shader,name,"main",options);
    CHECK(result);
    if(shaderc_result_get_compilation_status(result)!=shaderc_compilation_status_success)fprintf(stderr,"%s\n",shaderc_result_get_error_message(result));
    CHECK(shaderc_result_get_compilation_status(result)==shaderc_compilation_status_success);
    VkShaderModuleCreateInfo ci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    ci.codeSize=shaderc_result_get_length(result);ci.pCode=reinterpret_cast<const uint32_t *>(shaderc_result_get_bytes(result));
    VkShaderModule module{};VK_OK(vkCreateShaderModule(device,&ci,nullptr,&module));
    shaderc_result_release(result);shaderc_compile_options_release(options);shaderc_compiler_release(compiler);return module;
}
static void make_pipeline() {
    VkDescriptorSetLayoutBinding bindings[4]{};
    for(uint32_t i=0;i<4;i++)bindings[i]={i,VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,1,VK_SHADER_STAGE_FRAGMENT_BIT,nullptr};
    VkDescriptorSetLayoutCreateInfo di{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};di.bindingCount=4;di.pBindings=bindings;
    VK_OK(vkCreateDescriptorSetLayout(device,&di,nullptr,&descriptor_layout));
    VkPushConstantRange range{VK_SHADER_STAGE_FRAGMENT_BIT,0,96};
    VkPipelineLayoutCreateInfo li{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};li.setLayoutCount=1;li.pSetLayouts=&descriptor_layout;li.pushConstantRangeCount=1;li.pPushConstantRanges=&range;
    VK_OK(vkCreatePipelineLayout(device,&li,nullptr,&pipeline_layout));
    auto vertex=compile("post.vert"),fragment=compile("tmp_prep.frag");
    VkPipelineShaderStageCreateInfo stages[2]{};
    for(unsigned i=0;i<2;i++){stages[i].sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;stages[i].stage=i?VK_SHADER_STAGE_FRAGMENT_BIT:VK_SHADER_STAGE_VERTEX_BIT;stages[i].module=i?fragment:vertex;stages[i].pName="main";}
    VkPipelineVertexInputStateCreateInfo vi{VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia{VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};ia.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkPipelineViewportStateCreateInfo vp{VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};vp.viewportCount=vp.scissorCount=1;
    VkPipelineRasterizationStateCreateInfo rs{VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};rs.polygonMode=VK_POLYGON_MODE_FILL;rs.lineWidth=1;
    VkPipelineMultisampleStateCreateInfo ms{VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
    VkPipelineColorBlendAttachmentState ca[4]{};for(auto &c:ca)c.colorWriteMask=15;
    VkPipelineColorBlendStateCreateInfo cb{VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};cb.attachmentCount=4;cb.pAttachments=ca;
    VkDynamicState dyn[]={VK_DYNAMIC_STATE_VIEWPORT,VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dy{VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};dy.dynamicStateCount=2;dy.pDynamicStates=dyn;
    VkFormat formats[]={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R16G16_SFLOAT,VK_FORMAT_R32_SFLOAT,VK_FORMAT_R8_UNORM};
    VkPipelineRenderingCreateInfo rendering{VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO};rendering.colorAttachmentCount=4;rendering.pColorAttachmentFormats=formats;
    VkGraphicsPipelineCreateInfo pi{VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};pi.pNext=&rendering;pi.stageCount=2;pi.pStages=stages;pi.pVertexInputState=&vi;pi.pInputAssemblyState=&ia;pi.pViewportState=&vp;pi.pRasterizationState=&rs;pi.pMultisampleState=&ms;pi.pColorBlendState=&cb;pi.pDynamicState=&dy;pi.layout=pipeline_layout;
    VK_OK(vkCreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&pi,nullptr,&pipeline));
    vkDestroyShaderModule(device,vertex,nullptr);vkDestroyShaderModule(device,fragment,nullptr);
    VkDescriptorPoolSize ps{VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,4};
    VkDescriptorPoolCreateInfo pool_ci{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};pool_ci.maxSets=1;pool_ci.poolSizeCount=1;pool_ci.pPoolSizes=&ps;
    VK_OK(vkCreateDescriptorPool(device,&pool_ci,nullptr,&descriptors));
    VkSamplerCreateInfo si{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};si.magFilter=si.minFilter=VK_FILTER_NEAREST;si.mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST;si.addressModeU=si.addressModeV=si.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;si.maxLod=0;
    VK_OK(vkCreateSampler(device,&si,nullptr,&sampler));
}
static float unhalf(uint16_t h) {
    uint32_t bits=(h&0x8000u)<<16;unsigned exponent=(h>>10)&31,mantissa=h&1023;
    if(exponent)bits|=(exponent+112)<<23|mantissa<<13;
    else if(mantissa){float value=std::ldexp(static_cast<float>(mantissa),-24);return h&0x8000u?-value:value;}
    float value;memcpy(&value,&bits,4);return value;
}
static float depth_value(uint32_t x,uint32_t y) { return .2f + static_cast<float>((x*7+y*13)%97)/200.f; }
static unsigned pattern(uint32_t x,uint32_t y,unsigned channel) {return (x*11+y*19+channel*43)%251;}
static void dimension_case(uint32_t w,uint32_t h) {
    Texture color(VK_FORMAT_R8G8B8A8_UNORM,w,h,false),depth(VK_FORMAT_R32_SFLOAT,w,h,false),velocity(VK_FORMAT_A2B10G10R10_UNORM_PACK32,w,h,false);
    Texture out_color(VK_FORMAT_R8G8B8A8_UNORM,w,h,true),out_motion(VK_FORMAT_R16G16_SFLOAT,w,h,true),out_depth(VK_FORMAT_R32_SFLOAT,w,h,true),out_hud(VK_FORMAT_R8_UNORM,w,h,true);
    size_t n=static_cast<size_t>(w)*h;
    Buffer upload(n*12),readback(n*16);
    VkDescriptorSetAllocateInfo ai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};ai.descriptorPool=descriptors;ai.descriptorSetCount=1;ai.pSetLayouts=&descriptor_layout;
    VkDescriptorSet set{};VK_OK(vkAllocateDescriptorSets(device,&ai,&set));
    VkDescriptorImageInfo images[]={{sampler,color.view,VK_IMAGE_LAYOUT_GENERAL},{sampler,depth.view,VK_IMAGE_LAYOUT_GENERAL},{sampler,color.view,VK_IMAGE_LAYOUT_GENERAL},{sampler,velocity.view,VK_IMAGE_LAYOUT_GENERAL}};
    VkWriteDescriptorSet writes[4]{};for(unsigned i=0;i<4;i++){writes[i].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[i].dstSet=set;writes[i].dstBinding=i;writes[i].descriptorCount=1;writes[i].descriptorType=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;writes[i].pImageInfo=&images[i];}
    vkUpdateDescriptorSets(device,4,writes,0,nullptr);
    unsigned draws=0;double max_static_px=0,max_camera_px=0,max_object_px=0;size_t negative_errors=0, negative_extent_errors=0;
    for(unsigned mode=0;mode<5;mode++)for(unsigned phase=0;phase<16;phase++) {
        auto *depths=reinterpret_cast<float *>(upload.host+n*4);auto *vectors=reinterpret_cast<uint32_t *>(upload.host+n*8);
        for(uint32_t y=0;y<h;y++)for(uint32_t x=0;x<w;x++){
            size_t p=static_cast<size_t>(y)*w+x;
            for(unsigned c=0;c<3;c++)upload.host[p*4+c]=static_cast<unsigned char>(pattern(x,y,c));upload.host[p*4+3]=255;
            depths[p]=depth_value(mode==3?(x+1)%w:x,y);vectors[p]=102u|(145u<<10);
        }
        upload.sync(false);begin();
        Texture *inputs[]={&color,&depth,&velocity};Texture *outputs[]={&out_color,&out_motion,&out_depth,&out_hud};
        for(auto *t:inputs)t->general();for(auto *t:outputs)t->general();
        barrier(VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_ACCESS_TRANSFER_WRITE_BIT);
        for(unsigned i=0;i<3;i++){VkBufferImageCopy copy{};copy.bufferOffset=n*4*i;copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};copy.imageExtent={w,h,1};vkCmdCopyBufferToImage(command,upload.buffer,inputs[i]->image,VK_IMAGE_LAYOUT_GENERAL,1,&copy);}
        barrier(VK_PIPELINE_STAGE_TRANSFER_BIT,VK_ACCESS_TRANSFER_WRITE_BIT,VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,VK_ACCESS_SHADER_READ_BIT);
        VkRenderingAttachmentInfo attachments[4]{};
        for(unsigned i=0;i<4;i++){attachments[i].sType=VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO;attachments[i].imageView=outputs[i]->view;attachments[i].imageLayout=VK_IMAGE_LAYOUT_GENERAL;attachments[i].loadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE;attachments[i].storeOp=VK_ATTACHMENT_STORE_OP_STORE;}
        VkRenderingInfo ri{VK_STRUCTURE_TYPE_RENDERING_INFO};ri.renderArea={{0,0},{w,h}};ri.layerCount=1;ri.colorAttachmentCount=4;ri.pColorAttachments=attachments;
        vkCmdBeginRendering(command,&ri);VkViewport vp{0,0,static_cast<float>(w),static_cast<float>(h),0,1};VkRect2D sc{{0,0},{w,h}};
        vkCmdSetViewport(command,0,1,&vp);vkCmdSetScissor(command,0,1,&sc);vkCmdBindPipeline(command,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);vkCmdBindDescriptorSets(command,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline_layout,0,1,&set,0,nullptr);
        float pc[24]{};pc[0]=pc[5]=pc[10]=pc[15]=1;pc[16]=(phase%4-.0f)/4.f-.375f;pc[17]=(phase/4)/4.f-.375f;pc[18]=w;pc[19]=h;pc[20]=pc[21]=1;
        if(mode==1){pc[12]=.0625f;pc[13]=.03125f;} // +1/32 UVx, -1/64 UVy
        if(mode==2)pc[22]=1;
        if(mode==4){pc[18]+=8;pc[19]+=4;} // Deliberately false active input extent.
        vkCmdPushConstants(command,pipeline_layout,VK_SHADER_STAGE_FRAGMENT_BIT,0,sizeof pc,pc);vkCmdDraw(command,3,1,0,0);vkCmdEndRendering(command);
        barrier(VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_ACCESS_TRANSFER_READ_BIT);
        for(unsigned i=0;i<4;i++){VkBufferImageCopy copy{};copy.bufferOffset=n*4*i;copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};copy.imageExtent={w,h,1};vkCmdCopyImageToBuffer(command,outputs[i]->image,VK_IMAGE_LAYOUT_GENERAL,readback.buffer,1,&copy);}
        barrier(VK_PIPELINE_STAGE_TRANSFER_BIT,VK_ACCESS_TRANSFER_WRITE_BIT,VK_PIPELINE_STAGE_HOST_BIT,VK_ACCESS_HOST_READ_BIT);finish();readback.sync(true);
        auto *mv=reinterpret_cast<const uint16_t *>(readback.host+n*4);auto *z=reinterpret_cast<const float *>(readback.host+n*8);size_t errors=0,color_errors=0;
        for(uint32_t y=0;y<h;y++)for(uint32_t x=0;x<w;x++){
            size_t p=static_cast<size_t>(y)*w+x;for(unsigned c=0;c<3;c++)if(readback.host[p*4+c]!=pattern(x,y,c))color_errors++;
            if(std::abs(z[p]-depth_value(x,y))>1e-7)errors++;
            float expected_x=mode==1?1.f/32:mode==2?102.f*102/(1023.f*1023):0;
            float expected_y=mode==1?-1.f/64:mode==2?-145.f*145/(1023.f*1023):0;
            double error=std::max(std::abs(unhalf(mv[p*2])-expected_x)*w,std::abs(unhalf(mv[p*2+1])-expected_y)*h);
            if(mode==0)max_static_px=std::max(max_static_px,error);if(mode==1)max_camera_px=std::max(max_camera_px,error);if(mode==2)max_object_px=std::max(max_object_px,error);
            CHECK(error<.01);
            CHECK(readback.host[n*12+p]==0);
        }
        if(mode==3){CHECK(errors>n/2);negative_errors+=errors;CHECK(color_errors==0);}
        else if(mode==4){CHECK(errors>n/2&&color_errors>n/2);negative_extent_errors+=errors;}
        else {CHECK(errors==0);CHECK(color_errors==0);}
        draws++;
    }
    printf("TEMPORAL_PREP {\"width\":%u,\"height\":%u,\"draws\":%u,\"static_max_error_px\":%.9f,\"camera_max_error_px\":%.9f,\"object_max_error_px\":%.9f,\"negative_shifted_depth_mismatches\":%zu,\"negative_wrong_extent_mismatches\":%zu}\n",w,h,draws,max_static_px,max_camera_px,max_object_px,negative_errors,negative_extent_errors);
    VK_OK(vkResetDescriptorPool(device,descriptors,0));
}
int main(int argc,char **argv) {
    const char *state=nullptr,*feature=nullptr;
    for(int i=1;i<argc;i++){if(!strcmp(argv[i],"--state-root")&&i+1<argc)state=argv[++i];else if(!strcmp(argv[i],"--feature-dir")&&i+1<argc)feature=argv[++i];else CHECK(!"unknown argument");}
    CHECK(state&&feature);private_state(state);std::string data=std::string(state)+"/ngx";CHECK(mkdir(data.c_str(),0700)==0);CHECK(ngx_linux_init(feature,data.c_str()));network_policy();create_device();make_pipeline();
    dimension_case(48,30);dimension_case(64,40);dimension_case(96,60);
    VK_OK(vkDeviceWaitIdle(device));vkDestroySampler(device,sampler,nullptr);vkDestroyDescriptorPool(device,descriptors,nullptr);vkDestroyPipeline(device,pipeline,nullptr);vkDestroyPipelineLayout(device,pipeline_layout,nullptr);vkDestroyDescriptorSetLayout(device,descriptor_layout,nullptr);
    ngx_linux_reset();ngx_linux_shutdown();vkDestroyFence(device,fence,nullptr);vkDestroyCommandPool(device,pool,nullptr);vkDestroyDevice(device,nullptr);vkDestroyInstance(instance,nullptr);
    printf("PASS actual authored temporal prep GLSL, three scaled extents and shifted-depth/false-active-extent negative controls; no game/UI\n");
}
