"""LINUX-120: live request concurrency and actual F1 controls, no game or SDL."""
from pathlib import Path
import os, shutil, subprocess, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]; PORT=ROOT/'Monado_Linux'
@unittest.skipUnless(sys.platform=='linux','Linux live cheat implementation')
class LiveCheats(unittest.TestCase):
    def run_case(self,ui):
        cc=os.environ.get('MONADO_TEST_CC') or shutil.which('clang')
        cxx=os.environ.get('MONADO_TEST_CXX') or shutil.which('clang++')
        if not cc or (ui and not cxx): self.skipTest('native Clang C/C++ required')
        env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','XCDE_','LARECOMP_','LASRECOMP_'))}
        env.pop('GLIBC_TUNABLES',None)
        flags=['-O1','-UNDEBUG','-Wall','-Wextra','-Werror','-ffp-contract=off','-fno-strict-aliasing','-pthread']
        if os.environ.get('MONADO_TEST_UBSAN')=='1':
            flags+=['-fsanitize=undefined','-fno-sanitize-recover=all'];env['UBSAN_OPTIONS']='halt_on_error=1'
        with tempfile.TemporaryDirectory(prefix='monado-live-cheats-') as t:
            d=Path(t); obj=d/'state.o'; binary=d/'fixture'
            commands=[[cc,'-std=c11',*flags,'-c',str(PORT/'runtime/hle/cheats_options.c'),'-o',str(obj)]]
            if ui:
                imgui=PORT/'third_party/imgui'
                commands+=[[cxx,'-std=c++17',*flags,'-DIMGUI_ENABLE_TEST_ENGINE','-I',str(imgui),str(ROOT/'tests/native/test_live_cheats_ui.cpp'),str(obj),*[str(imgui/(n+'.cpp')) for n in ['imgui','imgui_draw','imgui_tables','imgui_widgets']],'-o',str(binary)]]
            else: commands+=[[cc,'-std=c11',*flags,str(ROOT/'tests/native/test_live_cheats.c'),str(obj),'-o',str(binary)]]
            for cmd in commands:
                p=subprocess.run(cmd,cwd=d,env=env,text=True,capture_output=True,timeout=180)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(binary)],cwd=d,env=env,text=True,capture_output=True,timeout=45)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS',p.stdout)
    def test_actual_whole_F1_menu_tab_and_save(self):
        cc=os.environ.get('MONADO_TEST_CC');cxx=os.environ.get('MONADO_TEST_CXX')
        include=os.environ.get('MONADO_TEST_SDL_INCLUDE')
        if not include:
            base=Path(os.environ.get('MONADO_TEST_SDL_PORT',str(PORT)))
            marker=base/'.deps/graphics/active-sysroot.txt'
            if marker.is_file():include=str(Path(marker.read_text().strip())/'usr/include')
        if not cc or not cxx or not include:self.skipTest('native compiler and pinned SDL/Vulkan headers required')
        env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','XCDE_','LARECOMP_','LASRECOMP_'))};env.pop('GLIBC_TUNABLES',None)
        flags=['-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections','-pthread']
        if os.environ.get('MONADO_TEST_UBSAN')=='1':flags+=['-fsanitize=undefined','-fno-sanitize-recover=all']
        with tempfile.TemporaryDirectory(prefix='monado-f1-cheats-')as t:
            d=Path(t);obj=d/'state.o';binary=d/'menu';imgui=PORT/'third_party/imgui'
            generated=subprocess.run([sys.executable,'-B',str(PORT/'tools/gen_fps_fonts.py'),
                '--assets',str(PORT/'tools/launcher/assets/fonts'),'--output',str(d/'fps_fonts.h')],capture_output=True,text=True,timeout=30)
            self.assertEqual(generated.returncode,0,generated.stdout+generated.stderr)
            cmds=[[cc,'-std=c11',*flags,'-c',str(PORT/'runtime/hle/cheats_options.c'),'-o',str(obj)],
                [cxx,'-std=c++17',*flags,'-DIMGUI_ENABLE_TEST_ENGINE','-I'+str(d),'-I'+include,'-I'+str(imgui),'-I'+str(imgui/'backends'),
                 str(ROOT/'tests/native/test_f1_cheats_menu.cpp'),str(PORT/'runtime/ui/menu_vk.cpp'),str(obj),
                 *[str(imgui/(n+'.cpp'))for n in ['imgui','imgui_draw','imgui_tables','imgui_widgets']],'-Wl,--gc-sections','-lm','-o',str(binary)]]
            for cmd in cmds:
                p=subprocess.run(cmd,cwd=d,env=env,text=True,capture_output=True,timeout=180);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            for height in ('960', '720'):
                p=subprocess.run([str(binary),height],cwd=d,env=env,text=True,capture_output=True,timeout=30);self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('nine toggles, Save accessibility at'+height+'p',p.stdout)
    def test_request_snapshot_and_concurrent_publication(self):self.run_case(False)
    def test_actual_F1_controls_and_live_request(self):self.run_case(True)
if __name__=='__main__':unittest.main()
