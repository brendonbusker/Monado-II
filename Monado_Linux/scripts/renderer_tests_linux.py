#!/usr/bin/env python3
"""LINUX-103: focused authored renderer contracts; production function extraction, no game data."""
import argparse,hashlib,json,os,shlex,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def extract(text,name):
    import re
    match=re.search(r'^([A-Za-z_][^\n;{}=]*\b'+re.escape(name)+r'\([^;]*?\)\s*\{)',text,re.M)
    if not match:raise RuntimeError('missing production function '+name)
    start=match.start();body=text.index('{',match.start());depth=1;end=body+1
    while depth:
        if text[end]=='{':depth+=1
        elif text[end]=='}':depth-=1
        end+=1
    return text[start:end]+'\n'
def generated_feedback(source,baseline=False):
    fixture=(ROOT/'tests/native/test_renderer_feedback_linux.c').read_text()
    names=['feedback_load_clear_ready','feedback_layout','feedback_sample_layout','feedback_aliases_pending','vk_feedback_boundary','snapshots_invalidate','vk_feedback_image_written','feedback_texture_written','feedback_written','vk_feedback_texture_gone','shader_texture_object','is_attachment','feedback_snapshot','snapshot_image','view_range','feedback_overlaps','feedback_color_mask','feedback_color_written','feedback_copy_bytes','resolve_feedback']
    if baseline:names=[n for n in names if n not in {'feedback_aliases_pending','vk_feedback_image_written','feedback_texture_written','feedback_snapshot','feedback_copy_bytes'}]
    declarations='''static TexBackend *pass_feedback[8];static unsigned pass_nfeedback,draw_feedback_mask;static bool pass_feedback_clear_only;
static NvnTexture *feedback_tex[9];static TexBackend *feedback_copy[9];static int nfeedback;
static NvnTexture *snap_tex[8];static bool snap_ok[8];static const char *snap_why[8],*snap_reason="?";
static uint64_t feedback_visibility=1;static int prof,naliases;
typedef struct {NvnTexture *key;TexBackend copy;VkImage source;uint64_t source_identity,visibility,frame;bool read_only_valid;}Snap;
static Snap snaps[16];static int nsnaps;static void feedback_written(NvnTexture *);
'''
    profile='' if baseline else source[source.index('// [XCDE] LINUX-126: optional interval counters'):source.index('static uint64_t feedback_visibility=1;')]
    performance='' if baseline else (ROOT/'tests/native/test_renderer_feedback_performance_linux.h').read_text()
    return fixture.replace('// GENERATED_PRODUCTION_FUNCTIONS',declarations+profile+'\n'.join(extract(source,n) for n in names)).replace('// GENERATED_SHARPEN_FUNCTION',extract(source,'fsr1_sharpen')).replace('// GENERATED_PERFORMANCE_TESTS',performance)
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--ubsan',action='store_true');p.add_argument('--real-device',action='store_true');a=p.parse_args();out=a.output.absolute()
    if out.exists() or out!=out.resolve() or not out.is_relative_to(ROOT/'runs'):p.error('fresh ordinary output under port runs required')
    out.mkdir(parents=True);record={'status':'running','scope':'authored renderer components; no game/window','commands':[]}
    sysroot=Path((ROOT/'.deps/graphics/active-sysroot.txt').read_text().strip());lib=sysroot/'usr/lib/x86_64-linux-gnu'
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LD_LIBRARY_PATH':str(lib),'UBSAN_OPTIONS':'halt_on_error=1'}
    if os.environ.get('VK_DRIVER_FILES'):env['VK_DRIVER_FILES']=os.environ['VK_DRIVER_FILES']
    def run(name,argv,expected_failure=False):
        start=time.monotonic();r=subprocess.run(list(map(str,argv)),env=env,cwd=out,capture_output=True,timeout=180)
        (out/(name+'.stdout.log')).write_bytes(r.stdout);(out/(name+'.stderr.log')).write_bytes(r.stderr)
        record['commands'].append({'name':name,'argv':list(map(str,argv)),'exit':r.returncode,'expected_failure':expected_failure,'seconds':time.monotonic()-start});save()
        if bool(r.returncode)!=expected_failure:raise RuntimeError(name+': '+r.stdout.decode()[-1500:]+r.stderr.decode()[-3500:])
        return r.stdout.decode()
    def save():(out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    try:
        source=(ROOT/'runtime/nvn/vulkan/exec.c').read_text();feedback=out/'feedback.c';feedback.write_text(generated_feedback(source))
        flags=['-O1','-UNDEBUG','-std=gnu11','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections','-I'+str(ROOT/'runtime'),'-I'+str(sysroot/'usr/include')]
        if a.ubsan:flags+=['-fsanitize=undefined','-fno-sanitize-recover=all']
        cc=ROOT/'.deps/bin/clang-cc'
        run('compile-feedback',[cc,*flags,feedback,'-Wl,--gc-sections','-lm','-o',out/'feedback'])
        print(run('feedback',[out/'feedback']),end='')
        # Each mutation removes a required property from the actual extracted
        # function. The same oracle must reject it, rather than only mirroring
        # a new implementation's successful path.
        faults=[('stale-write','vk_feedback_image_written','void vk_feedback_image_written(TexBackend *image){(void)image;}'),
                ('global-write','vk_feedback_image_written','void vk_feedback_image_written(TexBackend *image){(void)image;vk_feedback_boundary();}'),
                ('no-shared-reuse','feedback_snapshot','static Snap *feedback_snapshot(NvnTexture *t,TexBackend *src){(void)src;for(int i=0;i<nsnaps;i++)if(snaps[i].key==t)return &snaps[i];return NULL;}')]
        for name,function,replacement in faults:
            bad=out/(name+'.c');bad.write_text(feedback.read_text().replace(extract(source,function).strip(),replacement))
            run('compile-negative-'+name,[cc,*flags,bad,'-Wl,--gc-sections','-lm','-o',out/name])
            run('negative-'+name,[out/name],expected_failure=True)
        print('PASS feedback negative controls: stale writes, global over-invalidation and missing shared-backend reuse rejected')
        shader_flags=shlex.split(run('pkg-flags',[ROOT/'.deps/bin/pkg-config-graphics','--cflags','--libs','shaderc','sdl3']))
        shaders=out/'shaders';shaders.mkdir()
        run('compile-shaders',[cc,*flags,ROOT/'tests/native/test_renderer_shaders_linux.c',ROOT/'runtime/nvn/maxwell/translate.c',*shader_flags,'-Wl,--gc-sections','-lm','-o',out/'shader-fixture'])
        print(run('shaders',[out/'shader-fixture',shaders]),end='')
        if a.real_device:
            vk_flags=shlex.split(run('vk-flags',[ROOT/'.deps/bin/pkg-config-graphics','--cflags','--libs','vulkan']))
            run('compile-guard',[cc,'-O1','-ffunction-sections','-fdata-sections','-c',ROOT/'runtime/platform/linux_state_guard.c','-o',out/'guard.o'])
            cxx=ROOT/'.deps/bin/clang-cxx'
            run('compile-gpu',[cxx,'-std=c++17','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections',ROOT/'tests/native/test_renderer_gpu_linux.cpp',out/'guard.o',*vk_flags,'-Wl,--gc-sections','-Wl,-rpath,'+str(lib),'-o',out/'gpu-fixture'])
            state=out/'state';state.mkdir(mode=0o700)
            print(run('gpu',[out/'gpu-fixture',state,shaders]),end='')
            native=ROOT/'tests/native'
            run('compile-snapshot-recorder',[cc,*flags,'-DFEEDBACK_GPU_BRIDGE','-I'+str(native),'-c',feedback,'-o',out/'snapshot-recorder.o'])
            sanitizers=['-fsanitize=undefined','-fno-sanitize-recover=all'] if a.ubsan else []
            run('compile-snapshot-gpu',[cxx,'-std=c++17','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections',*sanitizers,native/'test_renderer_feedback_gpu_linux.cpp',out/'snapshot-recorder.o',out/'guard.o',*vk_flags,'-Wl,--gc-sections','-Wl,-rpath,'+str(lib),'-o',out/'snapshot-gpu-fixture'])
            snapshot_state=out/'snapshot-state';snapshot_state.mkdir(mode=0o700)
            print(run('snapshot-gpu',[out/'snapshot-gpu-fixture',snapshot_state]),end='')
            record['gpu_binary_sha256']=hashlib.sha256((out/'gpu-fixture').read_bytes()).hexdigest()
            record['snapshot_gpu_binary_sha256']=hashlib.sha256((out/'snapshot-gpu-fixture').read_bytes()).hexdigest()
            record['gpu_environment']=env
        record['sources']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [ROOT/'tests/native/test_renderer_gpu_linux.cpp',ROOT/'tests/native/test_framegen_linux.cpp',ROOT/'tests/native/test_renderer_feedback_gpu_linux.cpp',ROOT/'tests/native/test_renderer_feedback_gpu_bridge.h',ROOT/'tests/native/test_renderer_feedback_gpu_cases_linux.h',ROOT/'tests/native/test_renderer_feedback_performance_linux.h',ROOT/'runtime/platform/linux_state_guard.c',ROOT/'runtime/nvn/vulkan/exec.c',ROOT/'runtime/nvn/vulkan/bloom.h',ROOT/'runtime/nvn/vulkan/bloom_prefilter.h',ROOT/'runtime/nvn/vulkan/bloom_policy.h',ROOT/'runtime/nvn/maxwell/scaled_gather.h',ROOT/'runtime/nvn/maxwell/translate.c',ROOT/'tests/native/test_renderer_feedback_linux.c',ROOT/'tests/native/test_renderer_shaders_linux.c',Path(__file__)]};record['status']='passed'
    except Exception as e:record.update(status='failed',error=str(e));raise
    finally:save();print(out/'receipt.json')
if __name__=='__main__':main()
