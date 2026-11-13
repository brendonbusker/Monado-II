"""Actual Linux party scanner/control implementation with authored memory/calls."""
from pathlib import Path
import os,shutil,subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(sys.platform=='linux','native Linux party backend')
class LinuxParty(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cc=os.environ.get('MONADO_TEST_CC') or shutil.which('clang')
  if not cc:raise unittest.SkipTest('Clang required')
  cls.temp=tempfile.TemporaryDirectory(prefix='monado-party-linux-');cls.addClassCleanup(cls.temp.cleanup)
  cls.binary=Path(cls.temp.name)/'party-test'
  cmd=[cc,'-std=gnu11','-O1','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing','-ffunction-sections','-fdata-sections','-pthread','-I',str(ROOT/'Monado_Linux/runtime'),str(ROOT/'tests/native/test_party_linux.c'),'-Wl,--gc-sections','-lm','-o',str(cls.binary)]
  if os.environ.get('MONADO_TEST_UBSAN')=='1':cmd[1:1]=['-fsanitize=undefined','-fno-sanitize-recover=all']
  r=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
  if r.returncode:raise AssertionError(r.stdout+r.stderr)
 def case(self,name):
  command=[str(self.binary),name]
  if os.environ.get('MONADO_TEST_NAMESPACE')=='1':command=['/usr/bin/bwrap','--unshare-user','--unshare-net','--ro-bind','/','/','--dev-bind','/dev','/dev','--ro-bind','/proc','/proc','--',*command]
  r=subprocess.run(command,cwd=self.temp.name,capture_output=True,text=True,timeout=30)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('native Linux party: PASS',r.stdout)
 def test_discovery_and_cache(self):self.case('discovery')
 def test_left_switch_preserves_reserve_cpu_and_fp(self):self.case('left')
 def test_right_switch_preserves_reserve_cpu_and_fp(self):self.case('right')
 def test_menu_cutscene_and_player_locks_refuse_mutation(self):self.case('no-control')
 def test_battle_skips_down_member_and_updates_hud(self):self.case('battle')
 def test_invalid_heap_group_and_readonly_list_refused(self):self.case('invalid')
 def test_guard_pages_and_gauge_prefix_never_fault(self):self.case('guarded')
 def test_worker_single_start_interruptible_join_and_reset(self):self.case('worker')
 def test_queued_active_macro_and_direct_camera_reset(self):self.case('macro-reset')
if __name__=='__main__':unittest.main()
