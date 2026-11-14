"""LINUX-089: authored native projection fixtures and checked patch contracts."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
spec = importlib.util.spec_from_file_location('xcde_aspect_patches', PORT/'games/xcde/patches.py')
patches = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patches)


class CameraPatchContracts(unittest.TestCase):
    def generator(self):
        words = dict(patches.ASPECT_CAMERA_CONTEXT)
        words.update({site:entry[0] for site,entry in patches.ASPECT_CAMERA_PATCHES.items()})
        return SimpleNamespace(name='main',nso=SimpleNamespace(build_id=patches.ASPECT_BUILD_ID),
                               word=words.__getitem__,
                               lift=lambda site:SimpleNamespace(kind='op',code='AUTHORED_ORIGINAL;')),words

    def test_all_camera_frustum_render_and_hud_adapters_keep_native_instruction(self):
        gen,_=self.generator()
        self.assertEqual(len(patches.ASPECT_CAMERA_PATCHES),12)
        for site in patches.ASPECT_CAMERA_PATCHES:
            with self.subTest(site=hex(site)):
                patch=patches.PATCHES[site]
                self.assertEqual(patch.req,'LINUX-093' if site in (0x70006f7ea0,0x70006f8224) else 'LINUX-089')
                result=patch.apply(gen,site)
                self.assertEqual(result.count('AUTHORED_ORIGINAL;'),1)
                self.assertIn('xcde_aspect_',result)
                if site==0x70006f7ea0:
                    self.assertTrue(result.endswith('AUTHORED_ORIGINAL;'))
                    self.assertIn('xcde_aspect_render_ratio_bits',result)
                    self.assertIn('c->x[0] + 0x78',result)
                    self.assertIn('aspect_camera_data + 0x1f0',result)
                    self.assertLess(result.index('if (xcde_aspect_active())'),result.index('aspect_camera_data ='))
                else:self.assertTrue(result.startswith('AUTHORED_ORIGINAL;'))
                if site==0x70006f8224:
                    self.assertIn('xcde_aspect_render_fov_degrees_bits',result)
                    self.assertIn('c->x[0] + 0x78',result)
                    self.assertIn('aspect_camera_data + 0x1f0',result)

    def test_changed_build_or_module_is_refused(self):
        for name,build in [('sdk',patches.ASPECT_BUILD_ID),('main','00'*16),('main',patches.ASPECT_BUILD_ID+'00')]:
            gen,_=self.generator();gen.name=name;gen.nso.build_id=build
            with self.assertRaisesRegex(Exception,'checked DE 2.0.0 main'):
                patches.PATCHES[0x70005d913c].apply(gen,0x70005d913c)

    def test_every_selected_instruction_and_context_word_fails_closed(self):
        sites=list(patches.ASPECT_CAMERA_CONTEXT)+list(patches.ASPECT_CAMERA_PATCHES)
        for site in sites:
            with self.subTest(site=hex(site)):
                gen,words=self.generator();words[site]^=1
                patch_site=site if site in patches.ASPECT_CAMERA_PATCHES else 0x70005d913c
                with self.assertRaises(Exception):patches.PATCHES[patch_site].apply(gen,patch_site)

    def test_non_scalar_lifter_output_is_refused(self):
        gen,_=self.generator();gen.lift=lambda site:SimpleNamespace(kind='call',code='AUTHORED_ORIGINAL;')
        with self.assertRaisesRegex(ValueError,'plain scalar instruction'):
            patches.PATCHES[0x70005d913c].apply(gen,0x70005d913c)


@unittest.skipUnless(sys.platform=='linux','native Linux C11/pthread fixture')
class NativeAspect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=os.environ.get('MONADO_TEST_CC') or shutil.which('clang') or shutil.which('cc')
        if not cc:raise unittest.SkipTest('native C compiler unavailable')
        cls.temporary=tempfile.TemporaryDirectory(prefix='monado-native-aspect-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary=Path(cls.temporary.name)/'aspect'
        command=[cc,'-std=c11','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-pthread',
                 '-I',str(PORT/'runtime'),str(ROOT/'tests/native/test_xcde_aspect.c'),
                 str(PORT/'runtime/host/xcde_aspect.c'),'-lm','-o',str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN')=='1':command[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all']
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
        if result.returncode:raise AssertionError(result.stdout+result.stderr)

    def scenario(self,name):
        result=subprocess.run([str(self.binary),name],cwd=self.temporary.name,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('native XCDE aspect: PASS',result.stdout)
        self.assertEqual({p.name for p in Path(self.temporary.name).iterdir()},{self.binary.name})

    def test_original_and_reference_mode_are_bit_exact(self):self.scenario('identity')
    def test_unsupported_or_invalid_display_shape_resets_to_reference(self):self.scenario('bounds')
    def test_near_reference_deadband_matches_fitted_renderer_before_first_present(self):self.scenario('deadband')
    def test_16_10_adds_vertical_view_without_horizontal_crop(self):self.scenario('16:10')
    def test_21_9_adds_horizontal_view_and_matching_cpu_frustum(self):self.scenario('21:9')
    def test_32_9_adds_horizontal_view_and_matching_cpu_frustum(self):self.scenario('32:9')
    def test_world_markers_align_with_uniform_centered_hud_canvas(self):self.scenario('hud')
    def test_invalid_camera_and_repeated_resize_never_accumulate(self):self.scenario('invalid')
    def test_renderer_publishing_cannot_tear_factor_bits(self):self.scenario('concurrent')
    def test_renderer_uses_same_logical_camera_across_rounded_render_sizes(self):self.scenario('render-context')


if __name__=='__main__':unittest.main()
