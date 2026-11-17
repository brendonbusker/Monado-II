"""LINUX-097: actual parser/launcher FG configuration contracts."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
PORT=ROOT/'Monado_Linux'
@unittest.skipUnless(sys.platform=='linux','native Linux FG settings')
class FramegenSettings(unittest.TestCase):
    def fixture(self,cxx):
        compiler=os.environ.get('MONADO_TEST_CXX' if cxx else 'MONADO_TEST_CC') or shutil.which('clang++' if cxx else 'clang')
        if not compiler:self.skipTest('native Clang required')
        environment={k:v for k,v in os.environ.items() if not k.startswith(('XCDE_','LARECOMP_','LASRECOMP_','LD_','NVPRESENT_'))}
        with tempfile.TemporaryDirectory(prefix='monado-framegen-settings-') as t:
            out=Path(t);binary=out/'fixture'
            cmd=[compiler,'-std=c++17' if cxx else '-std=c11','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections']
            if cxx:
                marker=Path(os.environ.get('MONADO_TEST_SDL_PORT',str(PORT)))/'.deps/graphics/active-sysroot.txt'
                if not marker.is_file():self.skipTest('Pinned SDL3 dependencies unavailable for actual launcher fixture')
                selected=Path(marker.read_text().strip());lib=selected/'usr/lib/x86_64-linux-gnu'
                cmd+=['-I'+str(selected/'usr/include'),'-I'+str(PORT/'third_party/imgui'),'-I'+str(PORT/'third_party/imgui/backends'),str(ROOT/'tests/native/test_framegen_launcher.cpp'),'-L'+str(lib),'-Wl,-rpath,'+str(lib),'-lSDL3']
            else:
                cmd+=['-DXCDE_LINUX_DLSS','-DXCDE_LINUX_FRAMEGEN',str(ROOT/'tests/native/test_framegen_settings.c'),str(PORT/'runtime/host/settings_ini.c'), str(PORT / 'runtime/hle/cheats_options.c'), '-pthread']
            cmd+=['-Wl,--gc-sections','-lm','-o',str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN')=='1':cmd[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all'];environment['UBSAN_OPTIONS']='halt_on_error=1'
            result=subprocess.run(cmd,cwd=out,env=environment,capture_output=True,text=True,timeout=180);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary),str(out/('state' if cxx else 'xcde.ini'))],cwd=out,env=environment,capture_output=True,text=True,timeout=30);self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('PASS',result.stdout)
    def test_actual_runtime_parser_and_save(self):self.fixture(False)
    def test_actual_launcher_parser_save_and_normalization(self):self.fixture(True)
if __name__=='__main__':unittest.main()
