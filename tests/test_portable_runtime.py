"""Game-free runtime transport: real authored ELF, no game or vendor execution."""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_bundle_under_test',ROOT/'tools/portable_runtime.py')
bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)
ABI='a'*64;SOURCE='b'*64

@unittest.skipUnless(sys.platform=='linux','Linux authored runtime bundle')
class PortableRuntime(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix='monado-runtime-bundle-');self.addCleanup(self.t.cleanup)
        self.base=Path(self.t.name);self.build=self.base/'build';self.build.mkdir()
        self.binary=self.build/'xcde-linux';cc=Path(os.environ.get('MONADO_TEST_CC',str(ROOT/'Monado_Linux/.deps/bin/clang-cc')))
        if not cc.is_file():self.skipTest('private Clang needed')
        source=self.base/'authored.c';source.write_text('int main(void){return 0;}\n')
        p=subprocess.run([str(cc),str(source),'-o',str(self.binary)],capture_output=True,text=True,timeout=60)
        self.assertEqual(p.returncode,0,p.stderr)
        self.receipt={'schema':1,'status':'passed','split_game':True,'gamecode_abi':{'id':ABI},
          'executable':{'path':str(self.binary),'sha256':bundle.digest(self.binary)},
          'sources_before':{'runtime/authored.c':'c'*64},'sources_after':{'runtime/authored.c':'c'*64},
          'objects':{'runtime/authored.c':{'path':'authored.o','source_sha256':'c'*64,'object_sha256':'d'*64},
                     'generated/main.c':{'path':'generated-main.o'}},
          'generated':{'generated/main.c':'e'*64},'input':{'path':'PRIVATE INPUT'},
          'commands':[{'name':'link-graphics','exit':0,'argv':['clang','authored.o','-o',str(self.binary)]}],
          'runtime_resources':{},'dlss_enabled':False,'fsr3_enabled':False,'framegen_enabled':False}
        self.save()
    def save(self):(self.build/'receipt.json').write_text(json.dumps(self.receipt))
    def export(self):
        target=self.base/'runtime.tar.gz';m=bundle.export_bundle(self.binary,target,SOURCE);return target,m
    def mutate(self,archive,fn):
        with tarfile.open(archive,'r:gz') as t:rows=[(m,t.extractfile(m).read()) for m in t]
        p=self.base/'mutant.tar.gz'
        with tarfile.open(p,'w:gz') as t:
            for m,data in rows:
                name,data=fn(m.name,data);info=tarfile.TarInfo(name);info.size=len(data);t.addfile(info,io.BytesIO(data))
        return p
    def test_roundtrip_excludes_game_and_private_build_inputs(self):
        (self.build/'lasgame.so').write_bytes(b'PRIVATE LOCAL GAME CODE')
        self.receipt['runtime_resources']['lasgame.so']={'sha256':bundle.digest(self.build/'lasgame.so')};self.save()
        archive,m=self.export();out=self.base/'imported'
        accepted=bundle.import_bundle(archive,out,m['archive_sha256'],ABI,SOURCE)
        self.assertEqual(accepted['abi_id'],ABI);self.assertEqual(bundle.digest(out/'xcde-linux'),bundle.digest(self.binary))
        self.assertFalse((out/'lasgame.so').exists())
        self.assertNotIn('PRIVATE INPUT',(out/'receipt.json').read_text())
        self.assertNotIn('generated/main.c',(out/'receipt.json').read_text())
    def test_external_hash_source_and_abi_required(self):
        archive,m=self.export()
        for sha,abi,source in [('0'*64,ABI,SOURCE),(m['archive_sha256'],'0'*64,SOURCE),(m['archive_sha256'],ABI,'0'*64)]:
            with self.assertRaises(ValueError):bundle.import_bundle(archive,self.base/'out',sha,abi,source)
        self.assertFalse((self.base/'out').exists())
    def test_requested_compile_policy_survives_without_private_commands(self):
        self.receipt['source_compile_policy']={
            'runtime/nvn/vulkan/exec.c':['-O2','-UNDEBUG','-ffp-contract=off','-fno-strict-aliasing']}
        self.receipt['source_compile_policy_kind']='requested options, not measured performance'
        self.save();archive,m=self.export();out=self.base/'imported'
        bundle.import_bundle(archive,out,m['archive_sha256'],ABI,SOURCE)
        clean=json.loads((out/'receipt.json').read_text())
        for name in ('source_compile_policy','source_compile_policy_kind'):
            self.assertEqual(clean[name],self.receipt[name])
        self.assertNotIn('commands',clean)
        self.assertNotIn('PRIVATE INPUT',(out/'receipt.json').read_text())
    def test_large_local_command_receipt_exports_only_compact_public_metadata(self):
        private='PRIVATE COMMAND PADDING '+('x'*bundle.MAX_JSON)
        self.receipt['commands'].append({'name':'authored-compile','exit':0,'argv':['clang',private]})
        self.save();raw=self.build/'receipt.json'
        self.assertGreater(raw.stat().st_size,bundle.MAX_JSON)
        self.assertLess(raw.stat().st_size,16*1024*1024)
        archive,manifest=self.export();out=self.base/'imported-large-local'
        self.assertLess(manifest['files']['receipt.json']['bytes'],bundle.MAX_JSON)
        bundle.import_bundle(archive,out,manifest['archive_sha256'],ABI,SOURCE)
        clean=(out/'receipt.json').read_text()
        self.assertNotIn('PRIVATE COMMAND PADDING',clean)
        self.assertNotIn('commands',json.loads(clean))
        self.assertNotIn('PRIVATE INPUT',clean)
    def test_local_build_receipt_above_16_mib_is_rejected_before_archive_creation(self):
        self.assertEqual(bundle.MAX_BUILD_RECEIPT,16*1024*1024)
        self.receipt['commands'].append({'name':'authored-compile','argv':['x'*(16*1024*1024)]})
        self.save()
        with mock.patch.object(bundle.tempfile,'mkstemp') as create:
            with self.assertRaisesRegex(ValueError,'bounded ordinary owned'):
                self.export()
            create.assert_not_called()
        self.assertFalse((self.base/'runtime.tar.gz').exists())
    def test_default_document_and_import_keep_2_mib_limit(self):
        self.assertEqual(bundle.MAX_JSON,2*1024*1024)
        oversized=bundle.encoded({'authored_padding':'x'*bundle.MAX_JSON})
        document=self.base/'oversized.json';document.write_bytes(oversized)
        with self.assertRaisesRegex(ValueError,'bounded ordinary owned'):
            bundle.document(document)
        archive,manifest=self.export()
        with tarfile.open(archive,'r:gz') as tar:
            clean=json.loads(tar.extractfile('receipt.json').read())
            transport=json.loads(tar.extractfile('manifest.json').read())
        clean['authored_padding']='x'*bundle.MAX_JSON
        data=bundle.encoded(clean)
        transport['files']['receipt.json'].update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        bad=self.mutate(archive,lambda name,original:(name,data if name=='receipt.json' else
            bundle.encoded(transport) if name=='manifest.json' else original))
        out=self.base/'oversized-import'
        with self.assertRaisesRegex(ValueError,'bounded ordinary owned'):
            bundle.import_bundle(bad,out,bundle.digest(bad),ABI,SOURCE)
        self.assertFalse(out.exists())
        self.assertFalse(list(self.base.glob('.runtime-import-*')))
    def test_oversized_cleaned_receipt_rejected_before_archive_creation(self):
        self.receipt['source_compile_policy_kind']='authored retained metadata '+('x'*bundle.MAX_JSON)
        self.save()
        with mock.patch.object(bundle.tempfile,'mkstemp') as create:
            with self.assertRaisesRegex(ValueError,'cleaned runtime receipt exceeds transport JSON bound'):
                self.export()
            create.assert_not_called()
        self.assertFalse((self.base/'runtime.tar.gz').exists())
    def test_oversized_transport_manifest_rejected_before_archive_creation(self):
        # Excluded local companions still contribute manifest requirements.
        # A larger raw-receipt allowance must not create an unimportable envelope.
        self.receipt['runtime_resources']={f'local-resource-{i}.bin':{'bytes':1,'sha256':'1'*64} for i in range(15000)}
        self.save()
        with mock.patch.object(bundle.tempfile,'mkstemp') as create:
            with self.assertRaisesRegex(ValueError,'runtime manifest exceeds transport JSON bound'):
                self.export()
            create.assert_not_called()
        self.assertFalse((self.base/'runtime.tar.gz').exists())
    def licence(self):
        path=self.build/'DejaVu-font-license.txt'
        path.write_bytes(b'Authored font redistribution notice fixture; no real font data\n')
        self.receipt['runtime_resources'][path.name]={
            'path':str(path),'bytes':path.stat().st_size,'sha256':bundle.digest(path)}
        self.receipt['fps_font_resources']={
            'schema':1,'scope':'authored font metadata fixture',
            'fonts':{'authored.ttf':{'bytes':12,'sha256':'1'*64,'symbol':'fps_font_sans'}},
            'licence':{'source':'LICENSE-DejaVu.txt','bytes':path.stat().st_size,'sha256':bundle.digest(path)},
            'header':{'bytes':64,'sha256':'2'*64}}
        self.save();return path
    def test_font_notice_included_by_default_and_metadata_survives_roundtrip(self):
        licence=self.licence();original=licence.read_bytes()
        archive,manifest=self.export();self.assertIn(licence.name,manifest['files'])
        self.assertNotIn(licence.name,manifest['required_local_resources'])
        out=self.base/'imported'
        accepted=bundle.import_bundle(archive,out,manifest['archive_sha256'],ABI,SOURCE)
        self.assertEqual(accepted['files'][licence.name]['sha256'],bundle.digest(licence))
        self.assertEqual((out/licence.name).read_bytes(),original)
        clean=json.loads((out/'receipt.json').read_text())
        self.assertEqual(clean['fps_font_resources'],self.receipt['fps_font_resources'])
        self.assertEqual(clean['runtime_resources'][licence.name],{
            'path':licence.name,'bytes':len(original),'sha256':bundle.digest(licence)})
        self.assertNotIn(str(self.base),(out/'receipt.json').read_text())
    def test_changed_font_notice_rejected_before_export(self):
        licence=self.licence();licence.write_bytes(b'authored unexpected changed notice')
        with self.assertRaisesRegex(ValueError,'companion differs'):
            self.export()
        self.assertFalse((self.base/'runtime.tar.gz').exists())
    def test_changed_font_notice_in_archive_rejected_before_install(self):
        licence=self.licence();archive,manifest=self.export()
        changed=self.mutate(archive,lambda name,data:(name,data+b'changed')if name==licence.name else(name,data))
        out=self.base/'imported'
        with self.assertRaisesRegex(ValueError,'member identity|member hash'):
            bundle.import_bundle(changed,out,bundle.digest(changed),ABI,SOURCE)
        self.assertFalse(out.exists())
    def test_changed_member_and_parent_escape_rejected(self):
        archive,m=self.export()
        bad=self.mutate(archive,lambda name,data:(name,data+b'changed') if name=='xcde-linux' else (name,data))
        with self.assertRaises(ValueError):bundle.import_bundle(bad,self.base/'out',bundle.digest(bad),ABI,SOURCE)
        bad.unlink()
        bad=self.mutate(archive,lambda name,data:('../escaped',data) if name=='xcde-linux' else (name,data))
        with self.assertRaises(ValueError):bundle.import_bundle(bad,self.base/'out',bundle.digest(bad),ABI,SOURCE)
        self.assertFalse((self.base/'escaped').exists())
    def test_existing_destination_and_symlink_never_overwritten(self):
        archive,m=self.export();out=self.base/'out';out.mkdir();(out/'human').write_text('keep')
        with self.assertRaises(ValueError):bundle.import_bundle(archive,out,m['archive_sha256'],ABI,SOURCE)
        self.assertEqual((out/'human').read_text(),'keep')
        link=self.base/'link';link.symlink_to(archive)
        with self.assertRaises(ValueError):bundle.import_bundle(link,self.base/'new',m['archive_sha256'],ABI,SOURCE)
    def test_game_link_provenance_refused(self):
        self.receipt['commands'][0]['argv'].insert(1,'generated-main.o');self.save()
        with self.assertRaisesRegex(ValueError,'game object'):self.export()
    def test_missing_or_stripped_symbol_table_refused(self):
        p=subprocess.run(['/usr/bin/strip',str(self.binary)],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);self.receipt['executable']['sha256']=bundle.digest(self.binary);self.save()
        with self.assertRaisesRegex(ValueError,'symbol table'):self.export()
