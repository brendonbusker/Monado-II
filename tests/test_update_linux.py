"""Authored transaction and save-preservation fixtures; no real game or profile."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import update_linux as u
import update_release as r
if sys.platform=='linux':
    import fcntl


def manifest(root, files):
    files = dict(files, **{'publication-policy.json': b'{"schema":1,"licensed_media":{}}'})
    for name, data in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        if name.endswith('.sh'):p.chmod(0o755)
    (root/'publication-manifest.json').write_text(json.dumps({'schema':1,'project':'Monado II','source_only':True,'files':{n:{'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest()} for n,d in files.items()}}))


def image(root):
    data=bytearray(128);data[:4]=b'\x7fELF';data[8:11]=b'AI\x02'
    p=root/u.IMAGE;p.write_bytes(data);p.chmod(0o755)
    receipt={'status':'passed','artifact_kind':'local-launcher-appimage','bytes':128,'sha256':hashlib.sha256(data).hexdigest(),'archive_readback_verified':True}
    receipt.update({k:False for k in ['contains_game_executable','contains_game_files','contains_generated_game_code','contains_vendor_sdk']})
    Path(str(p)+'.receipt.json').write_text(json.dumps(receipt))


@unittest.skipUnless(sys.platform=='linux','Linux installation/lease fixtures')
class Transactions(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='monado-updater-owned-');self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name);self.owner=self.base/'owner';self.owner.mkdir();self.port=self.owner/'Monado_Linux'
        self.state=self.port/'play/launcher';(self.state/'save').mkdir(parents=True)
        (self.state/'.session.lock').write_bytes(b'')
        (self.state/'save/slot').write_bytes(b'AUTHORED SAVE SENTINEL');(self.state/'xcde.ini').write_bytes(b'fps = 165\nframe_gen = 0\n')
        (self.owner/'game_files/exefs').mkdir(parents=True);(self.owner/'game_files/romfs').mkdir()
        (self.owner/'game_files/romfs/synthetic').write_bytes(b'AUTHORED INPUT SENTINEL')
        self.game=self.port/'build/local-20260101T000000Z-12345678-game/xcde-linux';self.gui=self.port/'build/local-20260101T000000Z-12345678-launcher/monado-launcher'
        for p in [self.game,self.gui]:p.parent.mkdir(parents=True);p.write_bytes(b'NONEXECUTED AUTHORED PLACEHOLDER')
        (self.game.parent/'receipt.json').write_text('{"dlss_enabled":true,"framegen_enabled":true}')
        helper=(Path(__file__).resolve().parents[1]/'Monado_Linux/scripts/install_layout.py').read_bytes()
        self.files={'README.md':b'# Authored fixture\n','Build_Monado_II.sh':b'#!/bin/sh\nexit 1\n','Monado_Linux/scripts/install_layout.py':helper,'Monado_Linux/runtime/fixture.c':b'// authored runtime\n','Monado_Linux/tools/launcher/launcher.cpp':b'// old GUI\n','update-version.json':b'{"schema":1,"protocol":1,"version":"0.1.3"}'}
        for name in ('Rollback_Monado_II.sh','tools/update_linux.py','tools/installation_version.py',
                     'tools/update_retention.py','Monado_Linux/scripts/install_lease.py'):
            self.files[name]=(Path(__file__).resolve().parents[1]/name).read_bytes()
        manifest(self.owner,self.files);self.candidate=self.base/'candidate';self.candidate.mkdir()
        self.new=dict(self.files);self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.4"}';self.new['Monado_Linux/tools/launcher/launcher.cpp']=b'// new GUI\n';manifest(self.candidate,self.new)
        self.before=self.protected();self.commands=[];self.events=[]
        # Build/image payloads above are deliberately non-executable; runtime
        # loading is independently exercised by authored ELF fixtures.
        runtime_patch=mock.patch.object(u,'verify_runtime_selection',return_value={'status':'passed','scope':'authored fixture'})
        self.runtime_check=runtime_patch.start();self.addCleanup(runtime_patch.stop)
    def protected(self):
        return {str(p.relative_to(self.owner)):(p.read_bytes(),p.stat().st_mtime_ns) for d in [self.state,self.owner/'game_files'] for p in d.rglob('*') if p.is_file()}
    def fetch(self,offer,destination,**kwargs):destination.mkdir();return Path(shutil.copytree(self.candidate,destination/'source'))
    def runner(self,command,workspace,log,emit,cancel):
        self.commands.append(command)
        self.assertEqual(self.before,self.protected())
        if '--game-only' in command:
            build_id=command[command.index('--build-id')+1]
            port=workspace/'Monado_Linux'
            game=port/'build'/(build_id+'-game')/'xcde-linux'
            game.parent.mkdir(parents=True)
            data=bytearray(64);data[:6]=b'\x7fELF\x02\x01';data[18:20]=(62).to_bytes(2,'little')
            game.write_bytes(data);game.chmod(0o700)
            flags={'dlss_enabled':'--without-dlss' not in command,'framegen_enabled':'--without-dlss' not in command}
            native_receipt=dict(status='passed',executable={'path':str(game),'sha256':u._file_digest(game)},**flags)
            (game.parent/'receipt.json').write_text(json.dumps(native_receipt))
            run=port/'runs/local-build'/build_id;run.mkdir(parents=True)
            (run/'receipt.json').write_text(json.dumps({'schema':1,'status':'passed','commands':[]}))
            metadata=port/'.deps/metadata';metadata.mkdir(parents=True)
            (metadata/'game-payload.json').write_text(json.dumps({'schema':1,'artifact_kind':'local-game-payload',
                'status':'passed','build_id':build_id,'game':{'path':str(game),'build_port':str(port),
                'sha256':u._file_digest(game),'receipt_sha256':u.digest(game.parent/'receipt.json')},
                'build_receipt_sha256':u.digest(run/'receipt.json')}))
        else:
            self.assertIn('--reuse-game',command)
            gui=workspace/'Monado_Linux/build/new-gui/monado-launcher'
            gui.parent.mkdir(parents=True);gui.write_bytes(b'AUTHORED NEVER EXECUTED GUI')
            image(workspace)
            receipt_path=workspace/(u.IMAGE+'.receipt.json');receipt=json.loads(receipt_path.read_text())
            game=Path(command[command.index('--reuse-game')+1]);game_port=game.parents[2]
            receipt.update(launcher=gui.relative_to(workspace).as_posix(),game=game.relative_to(game_port.parent).as_posix())
            receipt_path.write_text(json.dumps(receipt))
        log.write_text('authored completion; no compiler/game/image executed\n')
    def session(self,*,workspace=None,game=None,gui=None,**kwargs):
        defaults={'discover':lambda _:dict(version='0.1.4',tag='v0.1.4'),'fetch':self.fetch,'runner':self.runner};defaults.update(kwargs)
        s=u.Session(workspace or self.owner,self.state,gui or self.gui,game or self.game,**defaults)
        self.addCleanup(s.close);return s
    def prepare(self,s,cancel=None):return s.install(s.check()['id'],self.events.append,cancel or threading.Event())
    def assertProtected(self):self.assertEqual(self.before,self.protected())
    def lease(self):
        fd=os.open(self.state/'.session.lock',os.O_RDWR|os.O_CREAT,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return fd
    def sync(self,workspace):
        fd=self.lease()
        try:return u.sync_installation_version(workspace,self.state,fd)
        finally:os.close(fd)
    def rollback(self,workspace):
        fake=types.SimpleNamespace(acquire_lock=lambda state:self.lease())
        with mock.patch.object(u,'ROOT',workspace),mock.patch.dict(sys.modules,{'launcher_linux':fake}):
            u.rollback(self.owner)
    def test_no_update_is_quiet_and_creates_no_update_paths(self):
        self.assertIsNone(self.session(discover=lambda _:None).check());self.assertFalse((self.port/'updates').exists());self.assertProtected()
    def test_legacy_game_is_detached_once_and_activation_retires_history(self):
        s=self.session();p=self.prepare(s)
        self.assertTrue(p['rebuild'])
        self.assertEqual(len(self.commands),2)
        self.assertIn('--game-only',self.commands[0])
        self.assertIn('--reuse-game',self.commands[1])
        self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
        command=s.activate(p);record=u.json_read(self.port/'updates/active.json')
        self.assertEqual(record['version'],'0.1.4')
        self.assertEqual(command[-2:],['--state-root',str(self.state)])
        workspace=self.owner/record['workspace'];binding=u.json_read(workspace/'installation.json')
        payload=Path(binding['game_port']).parent
        self.assertTrue(payload.parent.name.startswith('payload-'))
        self.assertNotEqual(binding['game_port'],str(self.port))
        self.assertEqual(self.commands[1][-1],str(payload/'Monado_Linux/build'/(u.json_read(payload/'Monado_Linux/.deps/metadata/game-payload.json')['build_id']+'-game')/'xcde-linux'))
        self.assertEqual(u.dispatch_active(self.owner,['--dry-run'])[-1],'--dry-run')
        self.assertIsNone(u.dispatch_active(workspace,[]))
        self.assertEqual(u.version(self.owner),'0.1.4');u.installed_sources(self.owner)
        self.assertEqual(u.json_read(self.port/'updates/previous.json'),{'schema':3,'selection':None})
        self.assertEqual(u.json_read(self.port/'updates/version-bridge.json')['workspace'],record['workspace'])
        self.assertFalse(self.game.exists());self.assertFalse(self.gui.exists())
        self.assertEqual((self.owner/'README.md').read_bytes(),self.files['README.md']);self.assertProtected()

    def test_subsequent_launcher_only_update_reuses_direct_payload_and_removes_previous_gui(self):
        first=self.session();p=self.prepare(first);first.activate(p)
        old_workspace=self.owner/p['record']['workspace']
        payload_port=Path(u.json_read(old_workspace/'installation.json')['game_port'])
        marker=u.json_read(payload_port/'.deps/metadata/game-payload.json');game=Path(marker['game']['path'])
        game_before=game.read_bytes(),(game.parent/'receipt.json').read_bytes()
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.5"}'
        self.new['Monado_Linux/tools/launcher/launcher.cpp']=b'// newer GUI\n';manifest(self.candidate,self.new)
        self.commands.clear()
        second=self.session(workspace=old_workspace,game=game,gui=old_workspace/'Monado_Linux/build/new-gui/monado-launcher',
            discover=lambda _:dict(version='0.1.5',tag='v0.1.5'))
        prepared=self.prepare(second)
        self.assertFalse(prepared['rebuild']);self.assertEqual(len(self.commands),1)
        self.assertEqual(self.commands[0][-2:],['--reuse-game',str(game)])
        self.assertTrue(old_workspace.exists());second.activate(prepared)
        workspace=self.owner/prepared['record']['workspace']
        self.assertFalse(old_workspace.exists());self.assertTrue(game.exists())
        self.assertEqual(u.json_read(workspace/'installation.json')['game_port'],str(payload_port))
        self.assertEqual(game_before,(game.read_bytes(),(game.parent/'receipt.json').read_bytes()))
        self.assertEqual(u.json_read(self.port/'updates/previous.json'),{'schema':3,'selection':None})
        self.assertEqual(u.json_read(self.port/'updates/version-bridge.json')['workspace'],prepared['record']['workspace'])
        self.assertEqual(u.version(self.owner),'0.1.5');u.installed_sources(self.owner);self.assertProtected()

    def test_runtime_change_triggers_independent_game_payload_then_launcher_reuse(self):
        self.new['Monado_Linux/runtime/fixture.c']+=b'// changed\n';manifest(self.candidate,self.new)
        s=self.session();p=self.prepare(s)
        self.assertTrue(p['rebuild']);self.assertIn('--game-only',self.commands[0])
        self.assertNotIn('--reuse-game',self.commands[0]);self.assertIn('--reuse-game',self.commands[1])
        binding=u.json_read(self.owner/p['record']['workspace']/'installation.json')
        self.assertTrue(Path(binding['game_port']).parent.parent.name.startswith('payload-'))
        self.assertNotIn('--without-dlss',self.commands[0]);self.assertProtected()

    def test_game_changing_update_keeps_old_payload_until_activation_then_retires_it(self):
        first=self.session();prepared=self.prepare(first);first.activate(prepared)
        old_workspace=self.owner/prepared['record']['workspace']
        old_port=Path(u.json_read(old_workspace/'installation.json')['game_port'])
        old_game=Path(u.json_read(old_port/'.deps/metadata/game-payload.json')['game']['path'])
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.5"}'
        self.new['Monado_Linux/runtime/fixture.c']+=b'// new gameplay source\n';manifest(self.candidate,self.new)
        self.commands.clear()
        second=self.session(workspace=old_workspace,game=old_game,gui=old_workspace/'Monado_Linux/build/new-gui/monado-launcher',
            discover=lambda _:dict(version='0.1.5',tag='v0.1.5'))
        prepared=self.prepare(second);new_workspace=self.owner/prepared['record']['workspace']
        new_port=Path(u.json_read(new_workspace/'installation.json')['game_port'])
        self.assertTrue(prepared['rebuild']);self.assertEqual(len(self.commands),2)
        self.assertNotEqual(old_port,new_port)
        self.assertTrue(old_game.exists());self.assertTrue(old_workspace.exists())
        self.assertEqual(u.json_read(self.port/'updates/active.json')['version'],'0.1.4')
        second.activate(prepared)
        self.assertFalse(old_workspace.exists());self.assertFalse(old_port.exists())
        new_game=Path(u.json_read(new_port/'.deps/metadata/game-payload.json')['game']['path'])
        self.assertTrue(new_game.exists())
        self.assertEqual(u.json_read(self.port/'updates/active.json')['version'],'0.1.5')
        self.assertEqual(u.json_read(self.port/'updates/previous.json')['selection'],None)
        self.assertProtected()

    def test_failed_update_with_existing_active_version_preserves_active_payload_and_metadata(self):
        first=self.session();prepared=self.prepare(first);first.activate(prepared)
        workspace=self.owner/prepared['record']['workspace']
        port=Path(u.json_read(workspace/'installation.json')['game_port'])
        game=Path(u.json_read(port/'.deps/metadata/game-payload.json')['game']['path'])
        kept={path:path.read_bytes() for path in (self.port/'updates/active.json',
            self.port/'updates/version-bridge.json',self.port/'updates/previous.json',
            self.owner/'update-version.json',game,game.parent/'receipt.json')}
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.5"}'
        self.new['Monado_Linux/runtime/fixture.c']+=b'// trigger rebuild\n';manifest(self.candidate,self.new)
        def failure(*args):raise ValueError('authored active-update compiler failure')
        second=self.session(workspace=workspace,game=game,gui=workspace/'Monado_Linux/build/new-gui/monado-launcher',
            discover=lambda _:dict(version='0.1.5',tag='v0.1.5'),runner=failure)
        with self.assertRaisesRegex(ValueError,'active-update compiler failure'):
            self.prepare(second)
        self.assertEqual({path:path.read_bytes() for path in kept},kept)
        self.assertTrue(workspace.exists());self.assertIsNone(second.lock_fd)
        self.assertEqual(u.dispatch_active(self.owner,[])[0],str(workspace/u.IMAGE))
        self.assertProtected()
    def test_older_standard_game_without_framegen_requires_full_rebuild_even_for_launcher_update(self):
        for recorded in (False, None):
            with self.subTest(recorded=recorded):
                receipt={'dlss_enabled':True}
                if recorded is not None:receipt['framegen_enabled']=recorded
                (self.game.parent/'receipt.json').write_text(json.dumps(receipt))
                s=self.session();p=self.prepare(s)
                self.assertTrue(p['rebuild']);self.assertIn('--game-only',self.commands[-2]);self.assertIn('--reuse-game',self.commands[-1])
                self.assertNotIn('--without-dlss',self.commands[-1])
                binding=u.json_read(self.owner/p['record']['workspace']/'installation.json')
                self.assertTrue(Path(binding['game_port']).parent.parent.name.startswith('payload-'))
                self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
                s.close()
    def test_foley_diagnostic_full_rebuild_stops_before_build_and_preserves_state(self):
        (self.game.parent/'receipt.json').write_text('{"dlss_enabled":true,"framegen_enabled":true,"foley_trace":true}')
        self.new['Monado_Linux/runtime/fixture.c']+=b'// changed\n';manifest(self.candidate,self.new)
        with self.assertRaisesRegex(ValueError,'diagnostic game build requires a manual rebuild'):
            self.prepare(self.session())
        self.assertFalse(self.commands);self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
    def test_missing_runtime_prevents_preparation_and_keeps_previous_selection(self):
        self.runtime_check.side_effect=ValueError('authored missing libbluray.so.3')
        session=self.session()
        with self.assertRaisesRegex(ValueError,'missing libbluray'):
            self.prepare(session)
        self.assertFalse((self.port/'updates/active.json').exists())
        self.assertEqual((self.owner/'update-version.json').read_bytes(),self.files['update-version.json'])
        self.assertProtected()
    def test_runtime_changed_after_build_cannot_activate_or_touch_version(self):
        session=self.session();prepared=self.prepare(session)
        self.runtime_check.side_effect=ValueError('authored runtime provider changed')
        before=self.protected();marker=(self.owner/'update-version.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'runtime provider changed'):
            session.activate(prepared)
        self.assertFalse((self.port/'updates/active.json').exists())
        self.assertFalse((self.port/'updates/previous.json').exists())
        self.assertEqual((self.owner/'update-version.json').read_bytes(),marker)
        self.assertEqual(self.protected(),before)
        self.assertProtected()
    def test_failed_build_preserves_sources_pointer_saves_and_input(self):
        def failure(*_):raise ValueError('authored compiler failure')
        s=self.session(runner=failure)
        with self.assertRaisesRegex(ValueError,'compiler failure'):self.prepare(s)
        self.assertFalse((self.port/'updates/active.json').exists());u.installed_sources(self.owner);self.assertIsNone(s.lock_fd);self.assertProtected()
    def test_cancel_before_fetch_does_not_create_update_tree(self):
        s=self.session();cancel=threading.Event();cancel.set()
        with self.assertRaises(r.UpdateCancelled):self.prepare(s,cancel)
        self.assertFalse((self.port/'updates').exists());self.assertProtected()
    def test_cancel_after_build_does_not_activate(self):
        cancel=threading.Event()
        def runner(*args):self.runner(*args);cancel.set()
        s=self.session(runner=runner)
        with self.assertRaises(r.UpdateCancelled):self.prepare(s,cancel)
        self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
        self.assertEqual((self.owner/'update-version.json').read_bytes(),self.files['update-version.json'])
        self.assertFalse((self.port/'updates/bootstrap-version.json').exists())
    def test_local_source_edits_are_preserved_and_install_refused(self):
        p=self.owner/'README.md';p.write_bytes(b'user local edits\n');s=self.session()
        with self.assertRaisesRegex(ValueError,'Local source changes'):self.prepare(s)
        self.assertEqual(p.read_bytes(),b'user local edits\n');self.assertFalse((self.port/'updates').exists());self.assertProtected()
    def test_downloaded_version_mismatch_stops_before_build(self):
        self.new['update-version.json']=self.files['update-version.json'];manifest(self.candidate,self.new);s=self.session()
        with self.assertRaisesRegex(ValueError,'version metadata'):self.prepare(s)
        self.assertFalse(self.commands);self.assertProtected()
    def test_damaged_built_image_is_rejected(self):
        def bad(command,workspace,*args):
            self.runner(command,workspace,*args)
            if '--game-only' not in command:(workspace/u.IMAGE).write_bytes(b'authored corruption')
        s=self.session(runner=bad)
        with self.assertRaisesRegex(ValueError,'pair failed'):self.prepare(s)
        self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
    def test_stale_offer_and_unowned_prepared_value_are_rejected(self):
        s=self.session();offer=s.check()
        with self.assertRaisesRegex(ValueError,'stale'):s.install('incorrect',self.events.append,threading.Event())
        p=s.install(offer['id'],self.events.append,threading.Event())
        with self.assertRaisesRegex(ValueError,'owned prepared'):s.activate(dict(p))
        self.assertProtected()
    def test_update_lock_serializes_different_profiles(self):
        first=self.session();self.prepare(first)
        with self.assertRaisesRegex(ValueError,'already running'):self.prepare(self.session())
        self.assertProtected()
    def test_modified_prepared_source_cannot_activate(self):
        s=self.session();p=self.prepare(s);(self.owner/p['record']['workspace']/'README.md').write_bytes(b'authored corruption\n')
        with self.assertRaisesRegex(ValueError,'Local source changes'):s.activate(p)
        self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
    def test_commit_failure_after_replace_restores_old_selection(self):
        s=self.session();p=self.prepare(s);real=u.durable_replace
        def fail(path,value):
            real(path,value)
            if path.name=='active.json':raise OSError('authored fsync failure')
        with mock.patch.object(u,'durable_replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'fsync'):s.activate(p)
        self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()
        self.assertEqual(u.version(self.owner),'0.1.3');u.installed_sources(self.owner)
    def test_pointer_traversal_and_symlink_are_refused(self):
        d=self.port/'updates';d.mkdir();u.write_new(d/'active.json',{'schema':1,'workspace':'../../elsewhere'})
        with self.assertRaisesRegex(ValueError,'active update'):u.dispatch_active(self.owner,[])
        (d/'active.json').unlink();(d/'active.json').symlink_to(self.owner/'README.md')
        with self.assertRaisesRegex(ValueError,'canonical'):u.dispatch_active(self.owner,[])
        self.assertProtected()
    def test_dlss_optout_and_standard_framegen_capability_are_preserved(self):
        path=self.game.parent/'receipt.json';path.write_text('{"dlss_enabled":false}')
        for rebuild in (False,True):
            command=u.build_command(self.candidate,self.game,rebuild)
            self.assertIn('--without-dlss',command);self.assertNotIn('--framegen',command)
        path.write_text('{"dlss_enabled":true,"framegen_enabled":true}')
        full=u.build_command(self.candidate,self.game,True)
        self.assertEqual(full,[str(self.candidate/'Build_Monado_II.sh')])
        self.assertIn('--reuse-game',u.build_command(self.candidate,self.game,False))
        self.assertIn('--framegen',u.build_command(self.candidate,self.game,False))

    def test_direct_reuse_cannot_silently_drop_standard_framegen_capability(self):
        path=self.game.parent/'receipt.json'
        for receipt in ({'dlss_enabled':True,'framegen_enabled':False},{'dlss_enabled':True}):
            path.write_text(json.dumps(receipt))
            with self.subTest(receipt=receipt),self.assertRaisesRegex(ValueError,'full rebuild is required'):
                u.build_command(self.candidate,self.game,False)

    def test_without_dlss_launcher_update_can_reuse_opted_out_game(self):
        (self.game.parent/'receipt.json').write_text('{"dlss_enabled":false,"framegen_enabled":false}')
        s=self.session();p=self.prepare(s)
        self.assertTrue(p['rebuild']);self.assertIn('--game-only',self.commands[0]);self.assertIn('--reuse-game',self.commands[1])
        self.assertIn('--without-dlss',self.commands[0]);self.assertIn('--without-dlss',self.commands[1]);self.assertNotIn('--framegen',self.commands[1])
        self.assertProtected()

    def test_invalid_framegen_receipt_is_not_silently_reused(self):
        path=self.game.parent/'receipt.json'
        for value in ({'dlss_enabled':True,'framegen_enabled':'false'},
                      {'dlss_enabled':False,'framegen_enabled':True}):
            path.write_text(json.dumps(value))
            for rebuild in (False,True):
                with self.subTest(value=value,rebuild=rebuild),self.assertRaisesRegex(ValueError,'invalid frame-generation'):
                    u.build_command(self.candidate,self.game,rebuild)

    def test_root_startup_without_active_version_is_read_only(self):
        self.assertFalse(self.sync(self.owner))
        self.assertFalse((self.port/'updates').exists());self.assertProtected()

    def test_old_activation_startup_migrates_marker_and_repairs_known_crash_state(self):
        s=self.session();p=self.prepare(s);workspace=self.owner/p['record']['workspace']
        u.durable_replace(self.port/'updates/previous.json',{'schema':1,'selection':None})
        u.durable_replace(self.port/'updates/active.json',p['record']);s.close()
        self.assertEqual(u.version(self.owner),'0.1.3')
        self.assertTrue(self.sync(workspace));self.assertEqual(u.version(self.owner),'0.1.4')
        self.assertFalse(self.sync(workspace));u.installed_sources(self.owner)
        # Simulate an interruption after active.json became durable but before
        # its derived marker was replaced. Only verified historical bytes repair.
        (self.owner/'update-version.json').write_bytes(self.files['update-version.json'])
        with self.assertRaisesRegex(ValueError,'installed-version marker'):u.installed_sources(self.owner)
        self.assertTrue(self.sync(workspace));self.assertEqual(u.version(self.owner),'0.1.4')
        self.assertProtected()

    def test_marker_failure_after_replacement_restores_pointer_and_original_source_bytes(self):
        s=self.session();p=self.prepare(s);real=u._replace_metadata
        calls=[]
        def fail(path,data):
            real(path,data);calls.append(data)
            if len(calls)==1:raise OSError('authored marker fsync failure')
        with mock.patch.object(u,'_replace_metadata',side_effect=fail):
            with self.assertRaisesRegex(OSError,'marker fsync'):s.activate(p)
        self.assertFalse((self.port/'updates/active.json').exists())
        self.assertEqual((self.owner/'update-version.json').read_bytes(),self.files['update-version.json'])
        u.installed_sources(self.owner);self.assertProtected()

    def test_rollback_is_clear_manual_downgrade_refusal_without_any_state_changes(self):
        s=self.session();p=self.prepare(s);workspace=self.owner/p['record']['workspace'];s.activate(p)
        selected=(self.port/'updates/active.json').read_bytes()
        marker=(self.owner/'update-version.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'Local rollback is no longer available.*GitHub'):
            self.rollback(workspace)
        self.assertEqual((self.port/'updates/active.json').read_bytes(),selected)
        self.assertEqual((self.owner/'update-version.json').read_bytes(),marker)
        u.installed_sources(self.owner);self.assertProtected()

    def test_unknown_root_wrapper_marker_or_backup_are_never_overwritten(self):
        s=self.session();p=self.prepare(s)
        wrapper=self.owner/'Rollback_Monado_II.sh';wrapper.write_bytes(b'#!/bin/sh\n# USER OWNED\n')
        with self.assertRaisesRegex(ValueError,'Local source changes'):s.activate(p)
        self.assertEqual(wrapper.read_bytes(),b'#!/bin/sh\n# USER OWNED\n')
        self.assertFalse((self.port/'updates/active.json').exists());self.assertProtected()

    def test_unknown_untracked_legacy_wrapper_is_not_replaced_or_adopted(self):
        self.files.pop('Rollback_Monado_II.sh');manifest(self.owner,self.files)
        wrapper=self.owner/'Rollback_Monado_II.sh';wrapper.write_bytes(b'#!/bin/sh\n# USER OWNED\n')
        s=self.session();p=self.prepare(s)
        with self.assertRaisesRegex(ValueError,'unknown or modified'):s.activate(p)
        self.assertEqual(wrapper.read_bytes(),b'#!/bin/sh\n# USER OWNED\n')
        self.assertFalse((self.port/'updates/bootstrap-version.json').exists())
        self.assertEqual((self.owner/'update-version.json').read_bytes(),self.files['update-version.json'])

    def test_legacy_owner_without_recovery_sources_migrates_to_current_only(self):
        for name in ('Rollback_Monado_II.sh','tools/installation_version.py'):
            self.files.pop(name);(self.owner/name).unlink()
        self.files['tools/update_linux.py']=b'# Authored legacy bootstrap placeholder\n'
        original=b'{"schema":1,"protocol":1,"version":"0.1.4"}\n'
        self.files['update-version.json']=original;manifest(self.owner,self.files)
        source_manifest=(self.owner/'publication-manifest.json').read_bytes()
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.6"}\n'
        manifest(self.candidate,self.new)
        s=self.session(discover=lambda _:dict(version='0.1.6',tag='v0.1.6'));p=self.prepare(s)
        workspace=self.owner/p['record']['workspace']
        u.durable_replace(self.port/'updates/previous.json',{'schema':1,'selection':None})
        u.durable_replace(self.port/'updates/active.json',p['record']);s.close()
        self.assertTrue(self.sync(workspace));self.assertEqual(u.version(self.owner),'0.1.6')
        self.assertEqual((self.owner/'Rollback_Monado_II.sh').read_bytes(),self.new['Rollback_Monado_II.sh'])
        self.assertFalse((self.owner/'tools/installation_version.py').exists())
        self.assertEqual((self.owner/'publication-manifest.json').read_bytes(),source_manifest)
        u.installed_sources(self.owner)
        with self.assertRaisesRegex(ValueError,'Local rollback is no longer available'):
            self.rollback(workspace)
        self.assertEqual(u.version(self.owner),'0.1.6')
        self.assertEqual(u.json_read(self.port/'updates/previous.json'),{'schema':3,'selection':None})
        self.assertEqual(u.json_read(self.port/'updates/version-bridge.json')['workspace'],p['record']['workspace'])
        for name,data in self.files.items():
            if name!='update-version.json':self.assertEqual((self.owner/name).read_bytes(),data)
        u.installed_sources(self.owner);self.assertProtected()

    def test_only_owner_version_marker_gets_a_manifest_bound_override(self):
        s=self.session();p=self.prepare(s);workspace=self.owner/p['record']['workspace'];s.activate(p)
        for name,data in self.files.items():
            if name!='update-version.json':self.assertEqual((self.owner/name).read_bytes(),data)
        (self.owner/'README.md').write_bytes(b'USER AUTHORED CHANGE\n')
        with self.assertRaisesRegex(ValueError,'Local source changes'):u.installed_sources(self.owner)
        (self.owner/'README.md').write_bytes(self.files['README.md'])
        bad=workspace/'Monado_Linux/updates';bad.mkdir()
        (bad/'bootstrap-version.json').write_bytes((self.port/'updates/bootstrap-version.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'only the original installation'):u.installed_sources(workspace)

    def test_version_sync_rejects_the_wrong_profile_lease_before_writes(self):
        fd=os.open(self.owner/'wrong-lock',os.O_RDWR|os.O_CREAT,0o600)
        try:
            with self.assertRaisesRegex(ValueError,'profile lease mismatch'):
                u.sync_installation_version(self.owner,self.state,fd)
        finally:os.close(fd)
        self.assertFalse((self.port/'updates').exists());self.assertProtected()

    def test_mutated_backup_or_unrecognized_marker_refuses_repair(self):
        s=self.session();p=self.prepare(s);workspace=self.owner/p['record']['workspace'];s.activate(p)
        marker=self.owner/'update-version.json';good=marker.read_bytes()
        marker.write_bytes(b'{"schema":1,"protocol":1,"version":"9.9.9"}')
        with self.assertRaisesRegex(ValueError,'installed-version marker'):self.sync(workspace)
        self.assertEqual(u.version(self.owner),'9.9.9');marker.write_bytes(good)
        backup=self.port/'updates/bootstrap-version.json';document=u.json_read(backup)
        document['original_metadata']='{"schema":1,"protocol":1,"version":"9.9.9"}'
        backup.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError,'original source manifest'):self.sync(workspace)
        self.assertEqual(marker.read_bytes(),good);self.assertProtected()

    def test_original014_managed015_then016_retires015_and_retains014_metadata_backup(self):
        original=b'{"schema":1,"protocol":1,"version":"0.1.4"}'
        self.files['update-version.json']=original;manifest(self.owner,self.files)
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.5"}';manifest(self.candidate,self.new)
        s=self.session(discover=lambda _:dict(version='0.1.5',tag='v0.1.5'));p=self.prepare(s)
        old_workspace=self.owner/p['record']['workspace']
        u.durable_replace(self.port/'updates/previous.json',{'schema':1,'selection':None})
        u.durable_replace(self.port/'updates/active.json',p['record']);s.close()
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.6"}';manifest(self.candidate,self.new)
        payload=Path(u.json_read(old_workspace/'installation.json')['game_port'])
        game=Path(u.json_read(payload/'.deps/metadata/game-payload.json')['game']['path'])
        gui=old_workspace/'Monado_Linux/build/new-gui/monado-launcher'
        session=self.session(workspace=old_workspace,game=game,gui=gui,
            discover=lambda _:dict(version='0.1.6',tag='v0.1.6'))
        prepared=self.prepare(session);new_workspace=self.owner/prepared['record']['workspace'];session.activate(prepared)
        self.assertEqual(u.version(self.owner),'0.1.6');u.installed_sources(self.owner)
        self.assertFalse(old_workspace.exists());self.assertTrue(game.exists())
        self.assertEqual(u.json_read(self.port/'updates/previous.json'),{'schema':3,'selection':None})
        self.assertEqual(u.json_read(self.port/'updates/version-bridge.json')['workspace'],new_workspace.relative_to(self.owner).as_posix())
        backup=u.json_read(self.port/'updates/bootstrap-version.json')
        self.assertEqual(backup['original_metadata'].encode(),original)
        u.installed_sources(self.owner);self.assertProtected()

    def test_committed_activation_survives_missing_support_and_full_status_disk(self):
        session=self.session();prepared=self.prepare(session)
        selected=self.owner/prepared['record']['workspace']
        real=u.durable_replace
        def full_status(path,value):
            if Path(path).name=='retention-status.json':
                raise OSError('authored disk full while reporting cleanup')
            return real(path,value)
        with mock.patch.object(u,'_support_module',side_effect=OSError('authored missing cleanup helper')):
            with mock.patch.object(u,'durable_replace',side_effect=full_status):
                command=session.activate(prepared)
        self.assertEqual(command[0],str(selected/u.IMAGE))
        self.assertEqual(u.json_read(self.port/'updates/active.json'),prepared['record'])
        self.assertEqual(u.version(self.owner),'0.1.4')
        self.assertIsNone(session.lock_fd)
        self.assertProtected()

    def active_payload(self):
        session=self.session();prepared=self.prepare(session);session.activate(prepared)
        workspace=self.owner/prepared['record']['workspace']
        port=Path(u.json_read(workspace/'installation.json')['game_port'])
        game=Path(u.json_read(port/'.deps/metadata/game-payload.json')['game']['path'])
        self.new['update-version.json']=b'{"schema":1,"protocol":1,"version":"0.1.5"}'
        manifest(self.candidate,self.new)
        self.commands.clear()
        return workspace,port,game

    def test_reused_payload_rejects_malformed_ownership_before_any_build(self):
        workspace,port,game=self.active_payload()
        path=port.parent.parent/'payload.json';original=u.json_read(path)
        selected=(self.port/'updates/active.json').read_bytes()
        for change in ({'owner':str(self.base/'unrelated')},{'id':'payload-other'},
                       {'workspace':'../workspace'},{'kind':'not-game-payload'},
                       {'schema':True},{'schema':2},{'unexpected':'user data'}):
            with self.subTest(change=change):
                self.commands.clear()
                path.write_text(json.dumps(dict(original,**change)))
                session=self.session(workspace=workspace,game=game,
                    gui=workspace/'Monado_Linux/build/new-gui/monado-launcher',
                    discover=lambda _:dict(version='0.1.5',tag='v0.1.5'))
                try:
                    with self.assertRaisesRegex(ValueError,'ownership marker'):
                        self.prepare(session)
                finally:
                    session.close()
                self.assertEqual(self.commands,[])
                self.assertEqual((self.port/'updates/active.json').read_bytes(),selected)
                self.assertTrue(game.exists());self.assertProtected()
        path.write_text(json.dumps(original))

    def test_reused_payload_refuses_indirect_binding_even_inside_same_installation(self):
        workspace,port,game=self.active_payload()
        path=port.parent/'installation.json';original=u.json_read(path)
        path.write_text(json.dumps(dict(original,game_port=str(self.port))))
        selected=(self.port/'updates/active.json').read_bytes()
        session=self.session(workspace=workspace,game=game,
            gui=workspace/'Monado_Linux/build/new-gui/monado-launcher',
            discover=lambda _:dict(version='0.1.5',tag='v0.1.5'))
        with self.assertRaisesRegex(ValueError,'direct self binding'):
            self.prepare(session)
        self.assertEqual(self.commands,[])
        self.assertEqual((self.port/'updates/active.json').read_bytes(),selected)
        self.assertTrue(game.exists());self.assertProtected()
        path.write_text(json.dumps(original))

    def test_reused_payload_refuses_mismatched_native_result_marker(self):
        workspace,port,game=self.active_payload()
        path=port/'.deps/metadata/game-payload.json';original=u.json_read(path)
        selected=(self.port/'updates/active.json').read_bytes()
        changes=[{'status':'failed'},{'schema':True},{'build_id':'../escape'},{'game':None},{'game':[]},
                 {'build_receipt_sha256':'0'*64},
                 {'game':dict(original['game'],path=str(game.parent/'different-game'))},
                 {'game':dict(original['game'],build_port=str(self.port))},
                 {'game':dict(original['game'],sha256='0'*64)},
                 {'game':dict(original['game'],receipt_sha256='0'*64)}]
        for change in changes:
            with self.subTest(change=change):
                self.commands.clear()
                path.write_text(json.dumps(dict(original,**change)))
                session=self.session(workspace=workspace,game=game,
                    gui=workspace/'Monado_Linux/build/new-gui/monado-launcher',
                    discover=lambda _:dict(version='0.1.5',tag='v0.1.5'))
                try:
                    with self.assertRaisesRegex(ValueError,'native game payload'):
                        self.prepare(session)
                finally:
                    session.close()
                self.assertEqual(self.commands,[])
                self.assertEqual((self.port/'updates/active.json').read_bytes(),selected)
                self.assertTrue(game.exists());self.assertProtected()
        path.write_text(json.dumps(original))

    def test_payload_result_rejects_unsafe_build_identity_before_filesystem_selection(self):
        _,port,game=self.active_payload()
        marker=u.json_read(port/'.deps/metadata/game-payload.json')
        self.assertEqual(u.payload_result(port.parent,marker['build_id']),game)
        for identity in (None,True,'','../outside','nested/path','a'*129,'space here','bad:identity'):
            with self.subTest(identity=identity),self.assertRaisesRegex(ValueError,'build identity'):
                u.payload_result(port.parent,identity)
        self.assertTrue(game.exists());self.assertProtected()

    def test_payload_result_refuses_failed_build_even_when_marker_hash_is_updated(self):
        _,port,game=self.active_payload()
        marker_path=port/'.deps/metadata/game-payload.json';marker=u.json_read(marker_path)
        run_receipt=port/'runs/local-build'/marker['build_id']/'receipt.json'
        document=u.json_read(run_receipt);document['status']='failed'
        run_receipt.write_text(json.dumps(document))
        marker['build_receipt_sha256']=u.digest(run_receipt);marker_path.write_text(json.dumps(marker))
        with self.assertRaisesRegex(ValueError,'checked build receipt'):
            u.payload_result(port.parent,marker['build_id'])
        self.assertTrue(game.exists());self.assertProtected()

    def legacy_updater(self):
        # Read immutable authored source locally, never download or run a game.
        # Exported source kits lack Git history, so only this historical-reader
        # integration fixture is optional there; current updater cases still run.
        commit='8d236ef34ec19f1599c072eb4ca9dbdfda0ef8cd'
        root=Path(__file__).resolve().parents[1]
        fixture=self.base/'unchanged-011-helper';tools=fixture/'tools';tools.mkdir(parents=True)
        if not shutil.which('git'):
            self.skipTest('unchanged 0.1.11 reader requires local baseline Git history')
        for name in ('update_linux.py','update_release.py','installation_version.py','publication_guard.py'):
            result=subprocess.run(['git','show',commit+':tools/'+name],cwd=root,
                capture_output=True,timeout=10)
            if result.returncode:
                self.skipTest('unchanged 0.1.11 reader baseline is absent from this source export')
            self.assertLessEqual(len(result.stdout),1024*1024)
            (tools/name).write_bytes(result.stdout)
        expected='781f8f236d409c2e0ddfbcf80558d5981e35f07b8e5a1fa10622a37459ecf72d'
        self.assertEqual(hashlib.sha256((tools/'update_linux.py').read_bytes()).hexdigest(),expected)
        spec=importlib.util.spec_from_file_location('monado_unchanged_011_fixture',tools/'update_linux.py')
        module=importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules):
            for name in ('update_release','installation_version','publication_guard'):
                sys.modules.pop(name,None)
            spec.loader.exec_module(module)
        module.ROOT=self.owner
        return module

    def test_unchanged_011_dispatches_current_but_raw_rollback_refuses_retired_history(self):
        workspace,port,game=self.active_payload()
        baseline=self.legacy_updater()
        selection=self.port/'updates/active.json';visible=self.owner/'update-version.json'
        previous=self.port/'updates/previous.json';bridge=self.port/'updates/version-bridge.json'
        self.assertEqual(u.json_read(previous),{'schema':3,'selection':None})
        before={path:path.read_bytes() for path in (selection,visible,previous,bridge)}
        self.assertEqual(baseline.dispatch_active(self.owner,['--dry-run']),
            [str(workspace/u.IMAGE),'--appimage-extract-and-run','--dry-run'])
        self.assertEqual(baseline.layout_module(self.owner).game_port(workspace/'Monado_Linux'),port)
        with self.assertRaisesRegex(ValueError,'(?:invalid|unsupported) previous version'):
            baseline.rollback(self.owner)
        self.assertEqual({path:path.read_bytes() for path in before},before)
        self.assertTrue(game.exists());self.assertProtected()

    def test_retired_history_tombstone_survives_startup_and_cannot_select_a_version(self):
        workspace,_,_=self.active_payload()
        previous=self.port/'updates/previous.json'
        self.assertEqual(u.json_read(previous),{'schema':3,'selection':None})
        self.assertFalse(self.sync(workspace))
        self.assertEqual(u.json_read(previous),{'schema':3,'selection':None})
        selected=u.json_read(self.port/'updates/active.json')
        u.durable_replace(previous,{'schema':3,'selection':selected})
        with self.assertRaisesRegex(ValueError,'previous version'):
            u._previous_selection(self.owner)
        self.assertEqual(u.json_read(self.port/'updates/active.json'),selected)
        self.assertProtected()

    def test_failed_activation_then_bootstrap_cleanup_does_not_leave_a_dangling_bridge(self):
        session=self.session();prepared=self.prepare(session)
        real=u._replace_metadata
        def fail(path,data):
            if data!=self.files['update-version.json']:
                raise OSError('authored activation marker failure')
            return real(path,data)
        with mock.patch.object(u,'_replace_metadata',side_effect=fail):
            with self.assertRaisesRegex(OSError,'marker failure'):
                session.activate(prepared)
        session.close()
        self.assertFalse((self.port/'updates/active.json').exists())
        self.assertTrue((self.port/'updates/version-bridge.json').exists())
        self.assertFalse(self.sync(self.owner))
        self.assertFalse((self.port/'updates/version-bridge.json').exists())
        self.assertFalse((self.owner/prepared['record']['workspace']).exists())
        next_session=self.session();next_prepared=self.prepare(next_session)
        self.assertEqual(next_prepared['record']['version'],'0.1.4')
        self.assertProtected()

    def test_long_native_receipt_features_remain_readable_with_a_strict_upper_bound(self):
        path=self.game.parent/'receipt.json'
        value={'dlss_enabled':True,'framegen_enabled':True,'commands':['authored long compiler argument '*100]*1000}
        path.write_text(json.dumps(value))
        self.assertGreater(path.stat().st_size,2*1024*1024)
        self.assertTrue(u.game_features(self.game)['framegen_enabled'])
        path.write_bytes(b' '*(u.MAX_GAME_RECEIPT+1))
        with self.assertRaises(ValueError):u.game_features(self.game)
        self.assertProtected()

if __name__=='__main__':unittest.main()
