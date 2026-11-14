"""LINUX-094: production runtime and launcher FPS-overlay preference persistence."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PORT=ROOT/'Monado_Linux'

@unittest.skipUnless(sys.platform=='linux','native Linux settings paths')
class FpsOverlaySettings(unittest.TestCase):
    def compiler(self,cxx=False):
        override=os.environ.get('MONADO_TEST_CXX' if cxx else 'MONADO_TEST_CC')
        local=PORT/'.deps/bin'/('clang-cxx' if cxx else 'clang-cc')
        result=override or (str(local) if local.is_file() else shutil.which('c++' if cxx else 'cc'))
        if not result:self.skipTest('native C/C++ compiler required')
        return result

    def check_fixture(self,cxx):
        environment={k:v for k,v in os.environ.items() if not k.startswith(('XCDE_','LARECOMP_','LASRECOMP_','LD_'))}
        environment.pop('GLIBC_TUNABLES',None)
        environment.update(LANG='C.UTF-8',LC_ALL='C.UTF-8')
        with tempfile.TemporaryDirectory(prefix='monado-fps-settings-') as temporary:
            directory=Path(temporary);binary=directory/'fixture'
            command=[self.compiler(cxx),'-std=c++17' if cxx else '-std=c11','-O1','-UNDEBUG',
                     '-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections']
            if cxx:
                # Public source CI has no private runtime dependencies. Keep
                # this actual-launcher fixture available on a configured host,
                # without turning missing setup into a source-test failure.
                dependency_port=Path(os.environ.get('MONADO_TEST_SDL_PORT',str(PORT)))
                marker=dependency_port/'.deps/graphics/active-sysroot.txt'
                if not marker.is_file():
                    self.skipTest('Pinned SDL3 dependencies unavailable for actual launcher fixture')
                selected=Path(marker.read_text().strip())
                libraries=selected/'usr/lib/x86_64-linux-gnu'
                command += ['-I'+str(selected/'usr/include'),'-I'+str(PORT/'third_party/imgui'),
                            '-I'+str(PORT/'third_party/imgui/backends'),
                            str(ROOT/'tests/native/test_fps_overlay_launcher.cpp'),'-L'+str(libraries),
                            '-Wl,-rpath,'+str(libraries),'-lSDL3']
            else:
                command += [str(ROOT/'tests/native/test_fps_overlay_settings.c'),str(PORT/'runtime/host/settings_ini.c')]
            command += ['-Wl,--gc-sections','-lm','-o',str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN')=='1':
                command[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all']
                environment['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=1'
            compiled=subprocess.run(command,cwd=directory,env=environment,capture_output=True,text=True,timeout=180)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(binary),str(directory/('state' if cxx else 'xcde.ini'))],
                                  cwd=directory,env=environment,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS',result.stdout)

    def test_runtime_default_roundtrip_and_legacy_title_independence(self):self.check_fixture(False)
    def test_actual_launcher_load_save_reload_and_translation(self):self.check_fixture(True)

if __name__=='__main__':unittest.main()
