"""Actual flock/inherited-descriptor and legacy-process maintenance fixtures."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
lease = None
if sys.platform == 'linux':
    import fcntl
    spec=importlib.util.spec_from_file_location('test_install_lease_impl',ROOT/'Monado_Linux/scripts/install_lease.py')
    lease=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lease)


@unittest.skipUnless(sys.platform=='linux','Linux flock and proc maintenance contract')
class LeaseTests(unittest.TestCase):
    def setUp(self):
        context=tempfile.TemporaryDirectory(prefix='monado lease space ')
        self.addCleanup(context.cleanup)
        self.owner=Path(context.name).resolve()
        self.port=self.owner/'Monado_Linux'
        self.port.mkdir()
        self.fds=[]
        self.children=[]
        self.addCleanup(self.finish)

    def finish(self):
        for child in self.children:
            if child.stdin:
                child.stdin.close()
            child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
        for fd in self.fds:
            os.close(fd)

    def hold(self,maintenance=False,port=None):
        fd=(lease.acquire_maintenance if maintenance else lease.acquire_runtime)(port or self.port)
        self.fds.append(fd)
        return fd

    def drop(self,fd):
        self.fds.remove(fd)
        os.close(fd)

    def test_shared_profiles_exclude_maintenance_until_last_holder_closes(self):
        first,second=self.hold(),self.hold()
        with self.assertRaises(BlockingIOError): self.hold(True)
        self.drop(first)
        with self.assertRaises(BlockingIOError): self.hold(True)
        self.drop(second)
        self.hold(True)

    def test_maintenance_excludes_runtime_and_second_maintenance(self):
        fd=self.hold(True)
        for exclusive in (True,False):
            with self.assertRaises(BlockingIOError): self.hold(exclusive)
        self.drop(fd)
        self.hold()

    def test_readonly_inherited_lease_pins_child_after_supervisor_closes(self):
        fd=self.hold()
        self.assertEqual(fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE,os.O_RDONLY)
        self.assertTrue(os.get_inheritable(fd))
        with self.assertRaises(OSError): os.write(fd,b'forbidden')
        child=subprocess.Popen([sys.executable,'-I','-B','-c',
            'import os,sys; os.fstat(int(sys.argv[1])); print("ready",flush=True); sys.stdin.read()',str(fd)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(fd,))
        self.children.append(child)
        self.assertEqual(child.stdout.readline(),b'ready\n')
        self.drop(fd)
        with self.assertRaises(BlockingIOError): self.hold(True)
        child.stdin.close(); child.stdin=None
        child.wait(timeout=5)
        self.hold(True)

    def test_managed_and_original_port_share_the_same_lease(self):
        import json
        workspace=self.port/'updates/update-authored/workspace'
        port=workspace/'Monado_Linux'; port.mkdir(parents=True)
        (workspace/'installation.json').write_text(json.dumps(dict(schema=1,owner=str(self.owner),workspace=str(workspace),game_port=str(self.port))))
        self.assertEqual(lease.lease_path(port),lease.lease_path(self.port))
        self.hold(port=port)
        with self.assertRaises(BlockingIOError): self.hold(True)

    def test_symlink_hardlink_nonempty_and_writable_lease_are_rejected(self):
        directory=self.port/'updates'; directory.mkdir()
        path=directory/'.runtime.lock'
        outside=self.owner/'outside'; outside.touch()
        path.symlink_to(outside)
        with self.assertRaises((OSError,ValueError)): self.hold()
        path.unlink(); os.link(outside,path)
        with self.assertRaises(ValueError): self.hold()
        path.unlink(); path.write_text('unknown contents')
        with self.assertRaises(ValueError): self.hold()
        self.assertEqual(path.read_text(),'unknown contents')
        path.write_text(''); path.chmod(0o666)
        with self.assertRaises(ValueError): self.hold()

    def test_symlink_parent_does_not_create_target_file(self):
        outside=self.owner/'outside'; outside.mkdir()
        (self.port/'updates').symlink_to(outside,target_is_directory=True)
        with self.assertRaises((ValueError, OSError)): self.hold()
        self.assertFalse((outside/'.runtime.lock').exists())

    def proc(self):
        proc=self.owner/'proc'; proc.mkdir()
        item=proc/'12345'; item.mkdir()
        (item/'stat').write_text('12345 (authored fixture) R '+'0 '*18+'12 0\n')
        (item/'exe').symlink_to('/usr/bin/true')
        (item/'cwd').symlink_to(self.owner)
        (item/'cmdline').write_bytes(b'/usr/bin/true\0')
        (item/'maps').write_text('')
        old=self.port/'updates/update-old'; old.mkdir(parents=True)
        return proc,item,old

    def test_legacy_exact_cwd_and_cmdline_pin_build(self):
        proc,item,old=self.proc()
        (item/'cwd').unlink(); (item/'cwd').symlink_to(old)
        self.assertTrue(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))
        (item/'cwd').unlink(); (item/'cwd').symlink_to(self.owner)
        (item/'cmdline').write_bytes(b'/usr/bin/python3\0'+os.fsencode(old/'scripts/run_linux.py')+b'\0')
        self.assertTrue(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))

    def test_legacy_maps_decode_spaces_and_respect_path_boundaries(self):
        proc,item,old=self.proc()
        escaped=str(old/'lib.so').replace(' ','\\040')
        (item/'maps').write_text('7f-80 r-xp 0000 00:00 0 '+escaped+'\n')
        self.assertTrue(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))
        (item/'maps').write_text('7f-80 r-xp 0000 00:00 0 '+str(old)+'-other/lib.so\n')
        self.assertFalse(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))

    def test_own_profile_exclusion_and_other_live_profile_deferral(self):
        proc,item,old=self.proc()
        profile=self.port/'play/launcher'; profile.mkdir(parents=True)
        fd=os.open(profile/'.session.lock',os.O_CREAT|os.O_RDWR,0o600); self.fds.append(fd)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.assertTrue(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))
        self.assertFalse(lease.legacy_process_in_use(self.owner,[old],exclude_lock_fds=(fd,),proc_root=proc))
        other=self.port/'runs/second'; other.mkdir(parents=True)
        second=os.open(other/'.precompile.lock',os.O_CREAT|os.O_RDWR,0o600); self.fds.append(second)
        fcntl.flock(second,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.assertTrue(lease.legacy_process_in_use(self.owner,[old],exclude_lock_fds=(fd,),proc_root=proc))

    def test_guard_holds_other_profile_lease_until_cleanup_finishes(self):
        proc,item,old=self.proc()
        profile=self.port/'runs/second'; profile.mkdir(parents=True)
        path=profile/'.session.lock'; path.touch(mode=0o600)
        fd=os.open(path,os.O_RDONLY); self.fds.append(fd)
        with lease.legacy_guard(self.owner,[old],proc_root=proc):
            with self.assertRaises(BlockingIOError): fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def restricted(self, item):
        original_readlink = lease.os.readlink
        original_open = Path.open
        def readlink(path, *args, **kwargs):
            if Path(path) in (item/'exe', item/'cwd'):
                raise PermissionError('authored non-dumpable process fixture')
            return original_readlink(path, *args, **kwargs)
        def opened(path, *args, **kwargs):
            if path == item/'maps':
                raise PermissionError('authored non-dumpable process fixture')
            return original_open(path, *args, **kwargs)
        return mock.patch.object(lease.os, 'readlink', side_effect=readlink), mock.patch.object(Path, 'open', opened)

    def test_unrelated_nondumpable_systemd_does_not_pin_history(self):
        proc,item,old=self.proc()
        (item/'cmdline').write_bytes(b'/usr/lib/systemd/systemd\0--user\0')
        links,maps=self.restricted(item)
        with links,maps:
            self.assertFalse(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))

    def test_potential_monado_or_ambiguous_interpreter_nondumpable_defers(self):
        proc,item,old=self.proc()
        for command in (b'/unreadable/monado-launcher\0', b'/usr/bin/python3\0-I\0-c\0opaque_code()\0'):
            (item/'cmdline').write_bytes(command)
            links,maps=self.restricted(item)
            with self.subTest(command=command),links,maps,self.assertRaisesRegex(ValueError,'potentially related'):
                lease.legacy_process_in_use(self.owner,[old],proc_root=proc)

    def test_embedded_victim_reference_pins_nondumpable_interpreter(self):
        proc,item,old=self.proc()
        snippet='from pathlib import Path; Path('+repr(str(old/'workspace/Monado_Linux'))+').open()'
        (item/'cmdline').write_bytes(b'/usr/bin/python3\0-I\0-c\0'+os.fsencode(snippet)+b'\0')
        links,maps=self.restricted(item)
        with links,maps:
            self.assertTrue(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))

    def test_unrelated_command_readable_old_library_mapping_still_pins(self):
        proc,item,old=self.proc()
        (item/'cmdline').write_bytes(b'/usr/bin/unrelated-app\0')
        escaped=str(old/'lib.so').replace(' ','\\040')
        (item/'maps').write_text('7f-80 r-xp 0000 00:00 0 '+escaped+'\n')
        self.assertTrue(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))


    def test_systemd_credential_helper_requires_real_parent_identity(self):
        proc,item,old=self.proc()
        (item/'cmdline').write_bytes(b'(sd-pam)\0')
        (item/'comm').write_text('(sd-pam)\n')
        (item/'stat').write_text('12345 ((sd-pam)) R 999 '+'0 '*17+'12 0\n')
        parent=proc/'999'; parent.mkdir()
        (parent/'comm').write_text('systemd\n')
        (parent/'stat').write_text('999 (systemd) S '+'0 '*18+'21 0\n')
        (parent/'cmdline').write_bytes(b'/usr/lib/systemd/systemd\0--user\0')
        (parent/'exe').symlink_to('/usr/lib/systemd/systemd')
        (parent/'cwd').symlink_to(self.owner)
        (parent/'maps').write_text('')
        links,maps=self.restricted(item)
        with links,maps:
            self.assertFalse(lease.legacy_process_in_use(self.owner,[old],proc_root=proc))
        (parent/'cmdline').write_bytes(b'/tmp/renamed-command\0')
        links,maps=self.restricted(item)
        with links,maps,self.assertRaisesRegex(ValueError,'potentially related'):
            lease.legacy_process_in_use(self.owner,[old],proc_root=proc)


    def test_invalid_process_inventory_defers(self):
        proc,item,old=self.proc()
        (item/'stat').write_text('malformed')
        with self.assertRaises(ValueError): lease.legacy_process_in_use(self.owner,[old],proc_root=proc)


if __name__=='__main__': unittest.main()
