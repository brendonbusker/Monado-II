"""LINUX-103: quality policy and actual runtime/launcher contracts, no game data."""
from pathlib import Path
import os,shutil,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];PORT=ROOT/'Monado_Linux'
@unittest.skipUnless(sys.platform=='linux','Linux quality implementation')
class GraphicsQuality(unittest.TestCase):
 def fixture(self,name,sources,cxx=False,args=True):
  compiler=os.environ.get('MONADO_TEST_CXX' if cxx else 'MONADO_TEST_CC') or shutil.which('clang++' if cxx else 'clang') or shutil.which('c++' if cxx else 'cc')
  if not compiler:self.skipTest('native compiler unavailable')
  environment={k:v for k,v in os.environ.items() if not k.startswith(('XCDE_','LARECOMP_','LASRECOMP_','LD_','NVPRESENT_'))}
  with tempfile.TemporaryDirectory(prefix='monado-graphics-quality-') as t:
   out=Path(t);binary=out/'fixture';cmd=[compiler,'-std=c++17' if cxx else '-std=gnu11' if name in ('sampler','device-selection') else '-std=c11','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections']
   if cxx or name in ('sampler','device-selection'):
    marker=Path(os.environ.get('MONADO_TEST_SDL_PORT',str(PORT)))/'.deps/graphics/active-sysroot.txt'
    if not marker.is_file():self.skipTest('Pinned SDL3 unavailable')
    selected=Path(marker.read_text().strip());lib=selected/'usr/lib/x86_64-linux-gnu'
    cmd+=['-I'+str(selected/'usr/include'),'-I'+str(PORT/'third_party/imgui'),'-I'+str(PORT/'third_party/imgui/backends'),'-L'+str(lib),'-Wl,-rpath,'+str(lib),'-lSDL3']
   cmd += ['-DXCDE_LINUX_DLSS','-DXCDE_LINUX_FRAMEGEN']+[str(ROOT/s) for s in sources]+(['-Wl,--no-gc-sections'] if name=='runtime' else ['-Wl,--gc-sections'])+['-lm','-pthread','-o',str(binary)]
   if name=='device-selection':cmd+=['-lvulkan']
   if os.environ.get('MONADO_TEST_UBSAN')=='1':cmd[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all'];environment['UBSAN_OPTIONS']='halt_on_error=1'
   result=subprocess.run(cmd,cwd=out,env=environment,capture_output=True,text=True,timeout=180);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   result=subprocess.run([str(binary)]+([str(out/('state' if cxx else 'xcde.ini'))] if args else []),cwd=out,env=environment,capture_output=True,text=True,timeout=30)
   if name=='fsr4-launcher' and result.returncode==77 and 'tool sandbox denies local socket descriptor inspection' in result.stdout:self.skipTest(result.stdout.strip())
   self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('PASS',result.stdout)
 def test_actual_sampler_cache(self):self.fixture('sampler',['tests/native/test_sampler_cache_linux.c'],args=False)
 def test_gpu_selection_policy(self):self.fixture('gpu-policy',['tests/native/test_gpu_selection_policy.c'],args=False)
 def test_actual_gpu_probe(self):self.fixture('gpu-probe',['tests/native/test_gpu_probe_linux.cpp'],cxx=True,args=False)
 def test_actual_device_selection(self):self.fixture('device-selection',['tests/native/test_gpu_device_selection_linux.c'],args=False)
 def test_actual_runtime_settings(self):self.fixture('settings',['tests/native/test_graphics_quality_linux.c','Monado_Linux/runtime/host/settings_ini.c','Monado_Linux/runtime/hle/cheats_options.c'])
 def test_selective_prop_lod(self):self.fixture('prop',['tests/native/test_graphics_prop_lod.c'],args=False)
 def test_actual_overlay_and_pool_lifecycle(self):self.fixture('runtime',['tests/native/test_graphics_runtime_linux.c','Monado_Linux/runtime/hle/graphics.c','Monado_Linux/runtime/hle/foliage_distance.c'],args=False)
 def test_actual_quality_ui(self):self.fixture('ui',['tests/native/test_graphics_quality_ui.cpp']+['Monado_Linux/third_party/imgui/'+n for n in ['imgui.cpp','imgui_draw.cpp','imgui_tables.cpp','imgui_widgets.cpp']],cxx=True,args=False)
 def test_actual_launcher_roundtrip(self):self.fixture('launcher',['tests/native/test_graphics_launcher_linux.cpp'],cxx=True)
 def test_actual_fsr4_launcher(self):self.fixture('fsr4-launcher',['tests/native/test_fsr4_launcher.cpp'],cxx=True)
if __name__=='__main__':unittest.main()
