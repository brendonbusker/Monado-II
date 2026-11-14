"""LINUX-093: production scene/HUD classifier with authored allocation metadata."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AspectComposite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=os.environ.get('MONADO_TEST_CC') or shutil.which('clang') or shutil.which('cc')
        if not compiler: raise unittest.SkipTest('C11 compiler required')
        cls.temp=tempfile.TemporaryDirectory(prefix='monado-aspect-composite-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary=Path(cls.temp.name)/('compositor.exe' if sys.platform=='win32' else 'compositor')
        command=[compiler,'-std=c11','-O1','-UNDEBUG','-ffp-contract=off',
                 str(ROOT/'tests/native/test_aspect_composite.c')]
        # MSVC's CRT provides math; '-lm' asks clang for nonexistent m.lib.
        if sys.platform != 'win32': command.append('-lm')
        command += ['-o',str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN')=='1':
            command[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all']
        result=subprocess.run(command,capture_output=True,text=True,timeout=90)
        if result.returncode: raise AssertionError(result.stdout+result.stderr)

    def scenario(self,name):
        result=subprocess.run([str(self.binary),name],cwd=self.temp.name,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('native aspect compositor: PASS',result.stdout)

    def test_multisource_scene_composites_keep_width_at_reduced_sizes(self):self.scenario('reduced')
    def test_portrait_atlas_and_square_minimap_remain_ui(self):self.scenario('ui')
    def test_fullscreen_scene_contract_rejects_unrelated_draws(self):self.scenario('boundaries')
    def test_scene_hud_and_resolution_transitions_do_not_carry_role(self):self.scenario('transitions')
    def test_retained_exact_size_classification(self):self.scenario('inherited')

if __name__=='__main__':unittest.main()
