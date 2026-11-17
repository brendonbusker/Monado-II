"""LINUX-097: explicit Smooth Motion intent and game-only environment boundary."""
from pathlib import Path
import importlib.util
import json
import hashlib
from types import SimpleNamespace
import os
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'Monado_Linux/scripts'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
native=launcher=precompile=None
if sys.platform=='linux':
    native=module('framegen_native_launch',SCRIPTS/'run_linux.py')
    with mock.patch.dict(sys.modules,{'run_linux':native}):
        launcher=module('framegen_launcher_launch',SCRIPTS/'launcher_linux.py')
        precompile=module('framegen_precompile_launch',SCRIPTS/'precompile_linux.py')
@unittest.skipUnless(sys.platform=='linux','Linux game launch boundary')
class FramegenLaunch(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='monado-framegen-launch-');self.addCleanup(temp.cleanup);self.root=Path(temp.name);self.state=self.root/'state';self.state.mkdir()
    def ini(self,text):
        (self.state/'xcde.ini').write_text(text);return self.state
    def test_explicit_selection_and_legacy_fsr_priority(self):
        for value in ('1','true'):
            self.assertTrue(native.smooth_motion_requested(self.ini('frame_gen_smooth_motion = '+value+'\n')))
        for value in ('','0','2','yes','TRUE','1junk','false','1 #comment','true ;comment'):
            self.assertFalse(native.smooth_motion_requested(self.ini('frame_gen_smooth_motion = '+value+'\n')))
        for fsr in ('1','2','-1','+1','1junk','1 #comment'):
            for text in ('frame_gen = '+fsr+'\nframe_gen_smooth_motion = 1\n','frame_gen_smooth_motion = 1\nframe_gen = '+fsr+'\n'):
                self.assertFalse(native.smooth_motion_requested(self.ini(text)))
        self.assertFalse(native.smooth_motion_requested(self.ini('cutscenes = 30fg\nframe_gen_smooth_motion = 1\n')))
        self.assertTrue(native.smooth_motion_requested(self.ini('cutscenes = 30fg #comment\nframe_gen_smooth_motion = 1\n')))
        self.assertTrue(native.smooth_motion_requested(self.ini('\ufeffframe_gen_smooth_motion = 0\nframe_gen_smooth_motion = true\ncutscenes = 30\n')))
        self.assertFalse(native.smooth_motion_requested(self.ini('frame_gen_smooth_motion = 1\nframe_gen_smooth_motion = invalid\n')))
    def test_missing_linked_nonregular_or_oversized_profile_never_enables(self):
        self.assertFalse(native.smooth_motion_requested(self.state))
        other=self.root/'outside.ini';other.write_text('frame_gen_smooth_motion = 1\n');(self.state/'xcde.ini').symlink_to(other)
        self.assertFalse(native.smooth_motion_requested(self.state));(self.state/'xcde.ini').unlink()
        os.mkfifo(self.state/'xcde.ini');self.assertFalse(native.smooth_motion_requested(self.state));(self.state/'xcde.ini').unlink()
        self.assertFalse(native.smooth_motion_requested(self.ini('#'+'x'*263000+'\nframe_gen_smooth_motion = 1\n')))
        self.assertFalse(native.smooth_motion_requested(self.ini('x'*511+'\nframe_gen_smooth_motion = 1\n')))
    def test_component_probe_requires_correct_layer_flag_and_native_elf(self):
        manifest=self.root/'layer.json';library=self.root/'libnvidia-present.so.authored'
        header=bytearray(64);header[:6]=b'\x7fELF\x02\x01';header[18:20]=(62).to_bytes(2,'little');library.write_bytes(header)
        doc={'layers':[{'name':'VK_LAYER_NV_present','enable_environment':{'NVPRESENT_ENABLE_SMOOTH_MOTION':'1'},'library_path':library.name}]};manifest.write_text(json.dumps(doc))
        self.assertTrue(native.smooth_motion_component([manifest],[self.root]))
        library.write_bytes(b'MZ'+bytes(62));self.assertFalse(native.smooth_motion_component([manifest],[self.root]));library.write_bytes(header)
        doc['layers'][0]['library_path']='../'+library.name;manifest.write_text(json.dumps(doc));self.assertFalse(native.smooth_motion_component([manifest],[self.root]))
        doc['layers'][0]['library_path']=library.name;doc['layers'][0]['enable_environment']['NVPRESENT_ENABLE_SMOOTH_MOTION']='0';manifest.write_text(json.dumps(doc));self.assertFalse(native.smooth_motion_component([manifest],[self.root]))
        manifest.write_text('{not valid JSON');self.assertFalse(native.smooth_motion_component([manifest],[self.root]))
        manifest.write_text('[]');self.assertFalse(native.smooth_motion_component([manifest],[self.root]))
    def test_game_environment_is_narrow_nonmutating_and_availability_gated(self):
        source={'PATH':'/authored/bin','SteamAppId':'123','NVPRESENT_ENABLE_SMOOTH_MOTION':'1','NVPRESENT_LOG_FILE':'/outside/log','NVPRESENT_QUEUE_FAMILY':'1','DISABLE_LAYER_NV_PRESENT_1':'1'};before=dict(source)
        for enabled in (False,True):
            result,report=native.frame_generation_environment(source,self.ini('frame_gen_smooth_motion = 1\n'),component_available=enabled)
            self.assertEqual(source,before);self.assertEqual(result['SteamAppId'],'123');self.assertEqual(report['external_driver_enabled'],enabled)
            self.assertEqual({k:v for k,v in result.items() if k.startswith('NVPRESENT_')},{'NVPRESENT_ENABLE_SMOOTH_MOTION':'1','NVPRESENT_LOG_LEVEL':'4'} if enabled else {})
            self.assertEqual(result.get('MONADO_CUDA_TASK_METADATA'),'1' if enabled else None)
            self.assertNotIn('DISABLE_LAYER_NV_PRESENT_1',result)
        result,report=native.frame_generation_environment(source,self.ini('frame_gen = 1\nframe_gen_smooth_motion = 1\n'),component_available=True)
        self.assertFalse(report['external_driver_enabled']);self.assertFalse(any(k.startswith('NVPRESENT_') for k in result))
    def test_only_explicit_scoped_game_namespace_mounts_writable_own_proc(self):
        helper=self.root/'bwrap';helper.write_bytes(b'authored nonexecuted namespace fixture');helper.chmod(0o700)
        with mock.patch.object(native,'BWRAP',helper),mock.patch.object(native,'X11_SOCKETS',self.root/'no-x11'),mock.patch.object(native,'NGX_UPDATER',self.root/'no-updater'),mock.patch.object(native.controller_environment,'namespace_metadata',return_value=None):
            ordinary,old=native.dlss_namespace(['/authored/never-run'],self.state,pid_namespace=False)
            self.assertEqual(old['cuda_task_metadata'],False);self.assertNotIn('--proc',ordinary);self.assertIn('--unshare-net',ordinary)
            smooth,new=native.dlss_namespace(['/authored/never-run'],self.state,pid_namespace=False,cuda_task_metadata=True)
            self.assertTrue(new['cuda_task_metadata']);self.assertEqual(smooth[smooth.index('--proc')+1],'/proc');self.assertNotIn('--unshare-pid',smooth);self.assertIn('--unshare-net',smooth)
            self.assertIn('--ro-bind',smooth);self.assertEqual(smooth[-1],'/authored/never-run')
            with self.assertRaises(ValueError):native.dlss_namespace(['/authored/never-run'],self.state,cuda_task_metadata=True)
    def test_actual_game_main_passes_only_saved_controlled_driver_selection(self):
        class ExecObserved(BaseException):pass
        source={'PATH':'/usr/bin:/bin','HOME':str(self.root),'NVPRESENT_ENABLE_SMOOTH_MOTION':'0','NVPRESENT_LOG_FILE':'/outside/log','SteamAppId':'123'}
        for smooth in (False,True):
            self.ini('frame_gen_smooth_motion = '+str(int(smooth))+'\n')
            launch={'argv':['/authored/no-game-exec'],'input':str(self.root/'input'),'state':str(self.state),'library_path':'/authored/libs'};captured={}
            def execute(path,args,environment):captured.update(environment);raise ExecObserved()
            with mock.patch.dict(os.environ,source,clear=True),mock.patch.object(sys,'argv',['run_linux.py','--executable','/authored/no-game-exec','--state-root',str(self.state),'--env','XCDE_INI=/untrusted/ignored.ini']),mock.patch.object(native,'plan',return_value=launch),mock.patch.object(native,'validate_runtime',return_value={}),mock.patch.object(native,'smooth_motion_component',return_value=True),mock.patch.object(native.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'authored checker pass','')),mock.patch.object(native.install_lease,'acquire_runtime',return_value=99),mock.patch.object(native.os,'listdir',return_value=['0','1','2']),mock.patch.object(native.os,'chdir'),mock.patch.object(native.os,'umask'),mock.patch.object(native.os,'execve',side_effect=execute):
                with self.assertRaises(ExecObserved):native.main()
            self.assertEqual(captured.get('NVPRESENT_ENABLE_SMOOTH_MOTION'),'1' if smooth else None)
            self.assertNotIn('NVPRESENT_LOG_FILE',captured);self.assertEqual(captured['SteamAppId'],'123')
    def test_actual_smooth_main_requires_scoped_native_protocol_and_host_boundary(self):
        self.ini('frame_gen_smooth_motion = 1\n')
        for protocol,kind,message in ((None,'bwrap-private-dlss','current full game build'),(1,'inherited-private-dlss','host Play supervisor')):
            launch={'argv':['/authored/no-game-exec'],'input':str(self.root/'input'),'state':str(self.state),'library_path':'/authored/libs',
                    'smooth_motion_planned':True,'cuda_task_metadata_protocol':protocol,'namespace':{'kind':kind}}
            with mock.patch.object(sys,'argv',['run_linux.py','--executable','/authored/no-game-exec','--state-root',str(self.state)]),mock.patch.object(native,'plan',return_value=launch),mock.patch.object(native,'smooth_motion_component',return_value=True),mock.patch.object(native.os,'execve') as execute,contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as result:native.main()
            self.assertEqual(result.exception.code,1);self.assertIn(message,error.getvalue());execute.assert_not_called()
    def test_observer_exact_startup_optin_dry_run_and_optional_failure(self):
        class ExecObserved(BaseException):pass
        self.ini('frame_gen_smooth_motion = 1\nshow_fps_overlay = 1\n')
        for dry,manifest_ok in ((True,True),(False,True),(False,False)):
            launch={'argv':['/authored/no-game-exec'],'input':str(self.root/'input'),'state':str(self.state),'library_path':'/authored/libs',
                    'smooth_motion_planned':True,'cuda_task_metadata_protocol':1,'observer_library':'/authored/checked/libmonado-present-observer.so',
                    'namespace':{'kind':'bwrap-private-dlss'},'execution_argv':['/authored/bwrap']};captured={}
            def execute(path,args,environment):captured.update(environment);raise ExecObserved()
            argv=['run_linux.py','--executable','/authored/no-game-exec','--state-root',str(self.state)]+(['--dry-run'] if dry else [])
            with mock.patch.dict(os.environ,{'PATH':'/usr/bin:/bin','MONADO_PRESENT_OBSERVER':'ambient-invalid','VK_LAYER_PATH':'/untrusted/layers','VK_ADD_LAYER_PATH':'/untrusted/add','VK_INSTANCE_LAYERS':'UNTRUSTED'},clear=True),mock.patch.object(sys,'argv',argv),mock.patch.object(native,'plan',return_value=launch),mock.patch.object(native,'smooth_motion_component',return_value=True),mock.patch.object(native,'private_runtime_environment',side_effect=lambda env,*args,**kwargs:env),mock.patch.object(native,'prepare_namespace_state',return_value=None),mock.patch.object(native,'validate_runtime',return_value={}),mock.patch.object(native.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'authored input check','')),mock.patch.object(native.present_observer_manifest,'prepare',return_value='/authored/private/layers',side_effect=None if manifest_ok else ValueError('foreign state')) as prepare,mock.patch.object(native.run_settings_log,'record_game_run',return_value={'run_id':'a'*32,'status':'recorded'}),mock.patch.object(native.install_lease,'acquire_runtime',return_value=99),mock.patch.object(native.os,'listdir',return_value=['0','1','2']),mock.patch.object(native.os,'chdir'),mock.patch.object(native.os,'umask'),mock.patch.object(native.os,'execve',side_effect=execute),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                if dry:self.assertEqual(native.main(),0)
                else:
                    with self.assertRaises(ExecObserved):native.main()
            if dry:prepare.assert_not_called();self.assertFalse(captured)
            else:
                prepare.assert_called_once_with(self.state,launch['observer_library'])
                self.assertEqual(captured.get('MONADO_PRESENT_OBSERVER'),'1' if manifest_ok else None)
                self.assertEqual(captured.get('MONADO_CUDA_TASK_METADATA'),'1')
                self.assertEqual(launch['frame_generation']['counter_available'],manifest_ok)
                if manifest_ok:
                    self.assertEqual(captured['VK_LAYER_PATH'],'/authored/private/layers');self.assertNotIn('VK_ADD_LAYER_PATH',captured);self.assertNotIn('VK_INSTANCE_LAYERS',captured)
        for text in ('frame_gen = 1\nframe_gen_smooth_motion = 1\nshow_fps_overlay = 1\n','show_fps_overlay = 1\n'):
            result,report=native.frame_generation_environment({'MONADO_PRESENT_OBSERVER':'1','MONADO_CUDA_TASK_METADATA':'1','VK_LAYER_PATH':'/old/unchanged'},self.ini(text),component_available=True)
            self.assertNotIn('MONADO_PRESENT_OBSERVER',result);self.assertFalse(report['observer_requested']);self.assertEqual(result['VK_LAYER_PATH'],'/old/unchanged')
    def test_driver_measurement_is_independent_of_overlay_visibility(self):
        for overlay in ('', 'show_fps_overlay = 0\n', 'show_fps_overlay = 1\n', 'show_fps_overlay = false\n', *('fps_overlay_mode = '+mode+'\n' for mode in ('off', 'number', 'compact', 'detailed', 'invalid'))):
            for available in (False, True):
                _, report = native.frame_generation_environment({}, self.ini('frame_gen_smooth_motion = 1\n' + overlay), component_available=available)
                self.assertEqual(report['observer_requested'], available)
                self.assertEqual(report['output_fps'], 'downstream-measurement-requested-not-yet-active' if available else 'application-presentations')
    def test_actual_launcher_prepare_only_sends_new_hint_to_matching_gui(self):
        gui=self.root/'gui';gui.mkdir();game=self.root/'game';game.mkdir()
        (game/'receipt.json').write_text(json.dumps({'generated':{'authored':True}}))
        args=SimpleNamespace(launcher_executable=gui/'no-ui',game_executable=game/'no-game',state_root=self.state,test_child_env=[],test_exit_after_child=False,ui_script=None,shot=None,shot_tab=None,shot_frame=None)
        base={'input':str(self.root/'input'),'state':str(self.state),'binary_sha256':'a'*64,'library_path':'/authored/libs'}
        source=hashlib.sha256((ROOT/'Monado_Linux/tools/launcher/launcher.cpp').read_bytes()).hexdigest()
        for matching in (False,True):
            (gui/'receipt.json').write_text(json.dumps({'artifact_kind':'linux-launcher','sources_before':{'tools/launcher/launcher.cpp':source if matching else '0'*64}}))
            plans=[{**base,'argv':[str(gui/'no-ui')]},{**base,'argv':[str(game/'no-game')]}]
            with mock.patch.object(native,'plan',side_effect=plans),mock.patch.object(native.install_layout,'build_port',return_value=ROOT/'Monado_Linux'),mock.patch.object(launcher,'validate_state',return_value=self.state),mock.patch.object(native,'smooth_motion_component',return_value=True) as component:
                result=launcher.prepare(args)
            self.assertEqual('--smooth-motion-layer-available' in result['argv'],matching)
            self.assertEqual(component.called,matching)
            if matching:self.assertEqual(result['argv'][result['argv'].index('--smooth-motion-layer-available')+1],'1')
            self.assertEqual(result['argv'][result['argv'].index('--game-executable')+1],str(game/'no-game'))
    def test_actual_gui_and_precompile_environments_do_not_admit_driver_fg(self):
        source={'PATH':'/usr/bin:/bin','NVPRESENT_ENABLE_SMOOTH_MOTION':'1','NVPRESENT_LOG_FILE':'/outside/log','DISABLE_LAYER_NV_PRESENT_1':'1','SteamAppId':'123'}
        self.ini('frame_gen_smooth_motion = 1\n')
        with mock.patch.dict(os.environ,source,clear=True):
            clean=launcher.clean_environment('/authored/libs')
        self.assertFalse(any(k.startswith('NVPRESENT_') for k in clean));self.assertEqual(clean['SteamAppId'],'123')
        build=self.root/'build';build.mkdir();sysroot=self.root/'sysroot';sysroot.mkdir();(sysroot/'.monado-deps.json').write_text('{}')
        receipt={'generated':{'authored':True},'precompile_protocol':1,'dependencies':{'sysroot':str(sysroot)},'sources_before':{'graphics-deps-linux.lock.json':'a'*64}};(build/'receipt.json').write_text(json.dumps(receipt))
        launch={'argv':[str(build/'no-game-exec')],'binary_sha256':'b'*64,'input':str(self.root/'input'),'state':str(self.state),'library_path':'/authored/libs'}
        with mock.patch.dict(os.environ,source,clear=True),mock.patch.object(native,'plan',return_value=launch),mock.patch.object(precompile,'check_input',return_value=subprocess.CompletedProcess([],0,'authored checker pass','')):
            result=precompile.prepare(build/'no-game-exec',self.state)
        self.assertFalse(any(k.startswith('NVPRESENT_') for k in result['environment']));self.assertNotIn('DISABLE_LAYER_NV_PRESENT_1',result['environment']);self.assertEqual(result['environment']['SteamAppId'],'123')
if __name__=='__main__':unittest.main()
