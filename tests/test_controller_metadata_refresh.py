"""LINUX-089: fixed-path metadata transport, no game or controller hardware."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'Monado_Linux/scripts'
native = context = None
if sys.platform == 'linux':
    import fcntl
    spec = importlib.util.spec_from_file_location('controller_metadata_runtime_fixture', SCRIPTS/'run_linux.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    context = native.controller_environment


@unittest.skipUnless(sys.platform == 'linux', 'Linux private controller metadata transport')
class MetadataRefresh(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='monado-authored-metadata-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root/'host-info'
        self.source.write_bytes(b'first complete authored metadata\n')
        self.source.chmod(0o600)
        self.state = self.root/'state'

    def mirror(self):
        plan = context.namespace_metadata({context.STEAM_INFO:str(self.source)}, self.state)
        mirror = native.prepare_namespace_state({'state':str(self.state),'namespace':{'controller_metadata':plan}},controller_refresh=True)
        self.addCleanup(mirror.close)
        return mirror

    def replace(self, content):
        path = self.root/'replacement'
        path.write_bytes(content); path.chmod(0o600)
        path.replace(self.source)

    def test_atomic_source_replacement_updates_complete_snapshot_and_second_mtime(self):
        with mock.patch.object(context.time, 'time', return_value=100):
            mirror = self.mirror()
            target = self.state/context.PRIVATE_INFO
            first = target.stat()
            self.replace(b'second complete authored metadata\n')
            self.assertTrue(mirror.poll(force=True))
            second = target.stat()
            self.assertNotEqual(first.st_ino, second.st_ino)
            self.assertGreater(int(second.st_mtime), int(first.st_mtime))
            self.assertEqual(target.read_bytes(), self.source.read_bytes())
            self.assertEqual(set(target.parent.iterdir()), {target,target.parent/'owner'})

    def test_unsafe_replacements_retain_last_valid_snapshot(self):
        mirror = self.mirror(); target=self.state/context.PRIVATE_INFO
        original=target.read_bytes()
        other=self.root/'unrelated';other.write_bytes(b'unrelated authored sentinel')
        self.source.unlink(); self.source.symlink_to(other)
        self.assertFalse(mirror.poll(force=True)); self.assertEqual(target.read_bytes(),original)
        self.source.unlink(); os.link(other,self.source)
        self.assertFalse(mirror.poll(force=True)); self.assertEqual(target.read_bytes(),original)
        self.source.unlink(); self.source.write_bytes(b'unsafe group writable');self.source.chmod(0o660)
        self.assertFalse(mirror.poll(force=True)); self.assertEqual(target.read_bytes(),original)
        self.source.unlink(); self.source.mkdir()
        self.assertFalse(mirror.poll(force=True));self.source.rmdir()
        os.mkfifo(self.source,0o600)
        self.assertFalse(mirror.poll(force=True));self.source.unlink()
        self.source.write_bytes(b'x'*(context.METADATA_LIMIT+1));self.source.chmod(0o600)
        self.assertFalse(mirror.poll(force=True));self.assertEqual(target.read_bytes(),original)
        self.replace(b'recovered valid authored metadata\n')
        self.assertTrue(mirror.poll(force=True))
        self.assertEqual(target.read_bytes(),self.source.read_bytes())
        self.assertEqual(other.read_bytes(),b'unrelated authored sentinel')

    def test_source_replacement_during_read_never_publishes_partial_or_wrong_inode(self):
        mirror=self.mirror();target=self.state/context.PRIVATE_INFO;original=target.read_bytes()
        self.replace(b'next complete authored metadata\n')
        real_read=context.os.read;changed=False
        def racing_read(fd,size):
            nonlocal changed
            data=real_read(fd,size)
            if not changed:
                changed=True
                self.replace(b'newest complete authored metadata\n')
            return data
        with mock.patch.object(context.os,'read',side_effect=racing_read):
            self.assertFalse(mirror.poll(force=True))
        self.assertEqual(target.read_bytes(),original)
        self.assertTrue(mirror.poll(force=True));self.assertEqual(target.read_bytes(),self.source.read_bytes())

    def test_source_parent_swapped_to_symlink_after_validation_is_not_followed(self):
        folder=self.root/'source-parent';folder.mkdir()
        self.source=folder/'info';self.source.write_bytes(b'first');self.source.chmod(0o600)
        mirror=self.mirror();target=self.state/context.PRIVATE_INFO
        original=target.read_bytes()
        other=self.root/'unrelated-parent';other.mkdir()
        secret=other/'info';secret.write_bytes(b'unrelated private authored sentinel');secret.chmod(0o600)
        folder.rename(self.root/'previous-parent');folder.symlink_to(other,target_is_directory=True)
        # Simulate replacement immediately after the ordinary canonical-path
        # check. Parent-component O_NOFOLLOW must independently reject it.
        with mock.patch.object(context,'metadata_file',return_value=self.source):
            self.assertFalse(mirror.poll(force=True))
        self.assertEqual(target.read_bytes(),original)
        self.assertEqual(secret.read_bytes(),b'unrelated private authored sentinel')

    def test_existing_foreign_mirror_content_is_never_overwritten(self):
        directory=self.state/context.PRIVATE_DIRECTORY
        directory.mkdir(parents=True,mode=0o700)
        unrelated=directory/'private-user-data';unrelated.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError,'unrecognized files'):
            self.mirror()
        self.assertEqual(unrelated.read_bytes(),b'preserve')

    def test_owned_interrupted_snapshot_staging_is_recovered_without_following_links(self):
        mirror=self.mirror();directory=self.state/context.PRIVATE_DIRECTORY
        mirror.close()
        staging=directory/'.next';staging.write_bytes(b'partial authored metadata');staging.chmod(0o600)
        again=self.mirror()
        self.assertFalse(staging.exists())
        self.assertEqual((directory/'info').read_bytes(),self.source.read_bytes())
        again.close()
        unrelated=self.root/'unrelated';unrelated.write_bytes(b'preserve')
        staging.symlink_to(unrelated)
        with self.assertRaisesRegex(ValueError,'staging file is unsafe'):
            self.mirror()
        self.assertTrue(staging.is_symlink())
        self.assertEqual(unrelated.read_bytes(),b'preserve')

    def test_planning_does_not_create_state_or_start_a_watcher(self):
        with mock.patch.object(context.threading,'Thread',side_effect=AssertionError('dry plan started thread')):
            plan=context.namespace_metadata({context.STEAM_INFO:str(self.source)},self.state)
            environment=context.private_environment({context.STEAM_INFO:str(self.source)},self.state,True)
        self.assertEqual(environment[context.STEAM_INFO],plan['target'])
        self.assertFalse(self.state.exists())

    def test_initial_snapshot_only_callers_keep_no_watcher_or_directory_descriptor(self):
        plan=context.namespace_metadata({context.STEAM_INFO:str(self.source)},self.state)
        before=set(os.listdir('/proc/self/fd'))
        with mock.patch.object(context.threading,'Thread',side_effect=AssertionError('snapshot started thread')):
            self.assertIsNone(native.prepare_namespace_state({'state':str(self.state),'namespace':{'controller_metadata':plan}}))
        self.assertEqual(set(os.listdir('/proc/self/fd')),before)
        self.assertEqual((self.state/context.PRIVATE_INFO).read_bytes(),self.source.read_bytes())

    def test_visible_readonly_host_path_keeps_atomic_replacement_visibility_without_mirror(self):
        # Outside /tmp and writable state, existing root RO bind already gives
        # a live path. No source file or parent-directory bind should freeze it.
        with tempfile.TemporaryDirectory(prefix='.metadata-visible-',dir=ROOT/'Monado_Linux') as temporary:
            path=Path(temporary).resolve()/'metadata';path.write_bytes(b'first');path.chmod(0o600)
            environment={context.STEAM_INFO:str(path)}
            self.assertIsNone(context.namespace_metadata(environment,self.state))
            self.assertEqual(context.private_environment(environment,self.state,True),environment)
            replacement=path.with_name('new');replacement.write_bytes(b'second');replacement.chmod(0o600)
            replacement.replace(path)
            self.assertEqual(Path(environment[context.STEAM_INFO]).read_bytes(),b'second')
            self.assertFalse(self.state.exists())


@unittest.skipUnless(sys.platform == 'linux', 'Linux private metadata namespace')
class MetadataNamespace(unittest.TestCase):
    def test_actual_readonly_directory_tracks_atomic_updates_and_rejects_alias_mutation(self):
        if not native.BWRAP.is_file():self.skipTest('bwrap unavailable')
        with tempfile.TemporaryDirectory(prefix='.metadata-namespace-',dir=ROOT/'Monado_Linux') as temporary, \
                tempfile.TemporaryDirectory(prefix='monado-authored-host-info-') as host:
            root=Path(temporary).resolve();state=root/'state';source=Path(host).resolve()/'info'
            source.write_bytes(b'first authored metadata');source.chmod(0o600)
            sibling=source.with_name('unrelated-host-file');sibling.write_bytes(b'private sentinel')
            probe=root/'probe.py'
            probe.write_text('''import errno,os,sys,time
from pathlib import Path
state,source=map(Path,sys.argv[1:])
assert not source.exists() and not source.with_name('unrelated-host-file').exists()
directories=[state/'steam-controller-metadata',Path('/tmp/steam-controller-metadata')]
for parent in (state,Path('/tmp')):
 try:parent.rename(parent.with_name(parent.name+'-moved'))
 except OSError as failure:assert failure.errno in (errno.EROFS,errno.EBUSY,errno.EACCES),failure
 else:raise AssertionError('metadata mount parent mutable: '+str(parent))
for directory in directories:
 assert (directory/'info').read_bytes()==b'first authored metadata'
 for operation in [lambda: (directory/'info').write_bytes(b'forbidden'),
                   lambda: (directory/'new').write_bytes(b'forbidden'),
                   lambda: (directory/'info').unlink(),
                   lambda: directory.rename(directory.with_name('moved-metadata')),
                   lambda: directory.rmdir()]:
  try:operation()
  except OSError as failure:assert failure.errno in (errno.EROFS,errno.EBUSY,errno.EACCES),failure
  else:raise AssertionError('private metadata alias mutable: '+str(directory))
(state/'ready').write_text('ready')
deadline=time.monotonic()+8
while (directories[0]/'info').read_bytes()!=b'second complete authored metadata':
 assert time.monotonic()<deadline,'metadata replacement stayed frozen'
 time.sleep(.01)
assert (directories[1]/'info').read_bytes()==b'second complete authored metadata'
print('PASS actual readonly aliases, no host siblings, live atomic replacement')
''')
            environment={context.STEAM_INFO:str(source),'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}
            with mock.patch.dict(os.environ,environment,clear=True):
                command,namespace=native.dlss_namespace(['/usr/bin/python3','-I','-B',str(probe),str(state),str(source)],state,pid_namespace=False)
                child_env=native.private_runtime_environment(environment,state,planned_namespace=True)
            mirror=native.prepare_namespace_state({'state':str(state),'namespace':namespace},controller_refresh=True)
            child=subprocess.Popen(command,env=child_env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+8
                while not (state/'ready').exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.01)
                if not (state/'ready').exists():
                    out,err=child.communicate(timeout=2)
                    if b'No permissions to create a new namespace' in err:
                        if os.environ.get('MONADO_REQUIRE_CONTROLLER_GUARD_NAMESPACE')=='1':self.fail(err.decode())
                        self.skipTest('host sandbox denies namespace creation')
                    self.fail((out+err).decode())
                replacement=source.with_name('replacement');replacement.write_bytes(b'second complete authored metadata');replacement.chmod(0o600);replacement.replace(source)
                self.assertTrue(mirror.poll(force=True))
                out,err=child.communicate(timeout=8)
                self.assertEqual(child.returncode,0,(out+err).decode())
                self.assertIn(b'PASS actual readonly aliases',out)
                self.assertEqual(sibling.read_bytes(),b'private sentinel')
                self.assertEqual(source.read_bytes(),b'second complete authored metadata')
            finally:
                mirror.close()
                if child.poll() is None:child.kill();child.wait(timeout=3)


@unittest.skipUnless(sys.platform == 'linux', 'Linux authored process/session fixtures')
class MetadataSupervisor(unittest.TestCase):
    def test_cli_mirror_supervisor_retains_lease_child_exit_and_no_force_kill(self):
        for status, interrupt in ((23,False),(0,True)):
            with self.subTest(status=status,interrupt=interrupt), \
                    tempfile.TemporaryDirectory(prefix='monado-metadata-cli-') as temporary:
                root=Path(temporary).resolve();state=root/'state';source=root/'host-info'
                source.write_text('first');source.chmod(0o600)
                lease=root/'readonly-lease';lease.write_text('authored lease sentinel')
                program=root/'child.py'
                program.write_text('''import fcntl,os,sys,time
from pathlib import Path
state=Path(sys.argv[1]);lease,private_directory,status=map(int,sys.argv[2:])
assert fcntl.fcntl(lease,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY
try:os.fstat(private_directory)
except OSError:pass
else:raise AssertionError('host mirror directory descriptor leaked into child')
(state/'child-ready').write_text('ready')
deadline=time.monotonic()+10
while (state/'steam-controller-metadata/info').read_text()!='second':
 assert time.monotonic()<deadline
 time.sleep(.01)
(state/'child-saw-update').write_text('yes')
while not (state/'finish').exists():
 assert time.monotonic()<deadline
 time.sleep(.01)
(state/'child-finished').write_text('yes')
sys.exit(status)
''')
                helper=root/'supervisor.py'
                helper.write_text('import os,sys\nfrom pathlib import Path\n'
                    'sys.path.insert(0,'+repr(str(SCRIPTS))+')\nimport run_linux as runtime\n'
                    'state=Path('+repr(str(state))+');source=Path('+repr(str(source))+')\n'
                    'context=runtime.controller_environment\n'
                    'plan=context.namespace_metadata({context.STEAM_INFO:str(source)},state)\n'
                    'mirror=runtime.prepare_namespace_state({"state":str(state),"namespace":{"controller_metadata":plan}},controller_refresh=True)\n'
                    'lease=os.open('+repr(str(lease))+',os.O_RDONLY|os.O_CLOEXEC)\n'
                    'try:\n code=runtime.wait_metadata_child([sys.executable,"-B",'+repr(str(program))+',str(state),str(lease),str(mirror.fileno()),'+repr(str(status))+'],dict(os.environ),lease,mirror)\n'
                    ' assert mirror.thread is None\n'
                    ' print("PASS CLI child lease, exit and joined mirror",flush=True)\n'
                    'finally:\n mirror.close()\n os.close(lease)\n'
                    'sys.exit(code)\n')
                child=subprocess.Popen([sys.executable,'-I','-B',str(helper)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    self.wait_file(state/'child-ready',child)
                    if interrupt:child.send_signal(signal.SIGTERM)
                    replacement=root/'replacement';replacement.write_text('second');replacement.chmod(0o600);replacement.replace(source)
                    self.wait_file(state/'child-saw-update',child)
                    self.assertIsNone(child.poll(),'signal prematurely terminated owned session')
                    (state/'finish').write_text('finish')
                    out,err=child.communicate(timeout=8)
                    self.assertEqual(child.returncode,143 if interrupt else status,(out+err).decode())
                    self.assertIn(b'PASS CLI child lease',out)
                    self.assertTrue((state/'child-finished').is_file())
                finally:
                    if child.poll() is None:child.kill();child.wait(timeout=3)

    def test_launcher_mirror_and_lease_survive_gui_exit_until_adopted_child_finishes(self):
        with tempfile.TemporaryDirectory(prefix='monado-metadata-supervisor-') as temporary:
            root=Path(temporary).resolve();state=root/'state';source=root/'host-info'
            source.write_text('first');source.chmod(0o600)
            adopted=root/'adopted.py'
            adopted.write_text('''import sys,time
from pathlib import Path
state=Path(sys.argv[1]);target=state/'steam-controller-metadata/info'
(state/'adopted-ready').write_text('ready')
deadline=time.monotonic()+10
while target.read_text()!='second':
 assert time.monotonic()<deadline,'supervisor stopped mirror when GUI exited'
 time.sleep(.01)
(state/'adopted-saw-update').write_text('yes')
while not (state/'finish').exists():
 assert time.monotonic()<deadline,'fixture finish timed out'
 time.sleep(.01)
''')
            gui=root/'gui.py';gui.write_text('import os,subprocess,sys\nfrom pathlib import Path\n'
                'state=Path('+repr(str(state))+')\n'
                'subprocess.Popen([sys.executable,"-B",'+repr(str(adopted))+',str(state)])\n'
                '(state/"gui-exited").write_text("yes")\nos._exit(0)\n')
            supervisor=root/'supervisor.py';supervisor.write_text('import os,sys\nfrom pathlib import Path\n'
                'sys.path.insert(0,'+repr(str(SCRIPTS))+')\nimport launcher_linux as launcher\n'
                'state=Path('+repr(str(state))+');source=Path('+repr(str(source))+')\n'
                'context=launcher.run_linux.controller_environment\n'
                'plan=context.namespace_metadata({context.STEAM_INFO:str(source)},state)\n'
                'mirror=launcher.run_linux.prepare_namespace_state({"state":str(state),"namespace":{"controller_metadata":plan}},controller_refresh=True)\n'
                'lock=launcher.acquire_lock(state)\nlog=os.open(state/"console.log",os.O_WRONLY|os.O_CREAT,0o600)\n'
                'try:\n code=launcher.wait_session([sys.executable,"-B",'+repr(str(gui))+'],dict(os.environ),lock,log,metadata_mirror=mirror)\n'
                ' assert code==0 and mirror.thread is None\n print("PASS adopted lifetime and joined mirror")\n'
                'finally:\n mirror.close()\n os.close(log)\n os.close(lock)\n')
            child=subprocess.Popen([sys.executable,'-I','-B',str(supervisor)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                self.wait_file(state/'gui-exited',child);self.wait_file(state/'adopted-ready',child)
                replacement=root/'replacement';replacement.write_text('second');replacement.chmod(0o600);replacement.replace(source)
                self.wait_file(state/'adopted-saw-update',child)
                lock=os.open(state/'.session.lock',os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    (state/'finish').write_text('finish')
                    out,err=child.communicate(timeout=8)
                    self.assertEqual(child.returncode,0,(out+err).decode())
                    self.assertIn(b'PASS adopted lifetime',out)
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                finally:os.close(lock)
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=3)

    def wait_file(self,path,child):
        deadline=time.monotonic()+8
        while not path.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.01)
        if not path.exists():
            if child.poll() is not None:
                out,err=child.communicate(timeout=2);self.fail((out+err).decode())
            self.fail('authored process fixture timed out: '+path.name)


if __name__=='__main__':unittest.main()
