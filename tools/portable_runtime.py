#!/usr/bin/env python3
"""[XCDE] LINUX-103: data-only, game-free native runtime bundle transport.

This is a developer/local-install envelope, not a redistribution approval. It
never includes the locally recompiled game library, input, saves or shader caches.
An external verified archive hash, current source manifest and ABI are required
for import. Runtime/library pairing belongs to the normal native builder.
"""
import argparse
import ctypes
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

HEX=re.compile(r'[0-9a-f]{64}\Z')
MAX_TOTAL=1024*1024*1024
MAX_FILES=128
MAX_JSON=2*1024*1024
# [XCDE] LINUX-126 R2: local compiler commands/log identities grow with authored
# source/flags. Only export may read this larger owned build receipt; transported
# documents and import keep their independent 2 MiB bound after sanitization.
MAX_BUILD_RECEIPT=16*1024*1024
EXCLUDED={'lasgame.so','lasgame.so.id'}
PUBLIC_RESOURCES={'libmonado-fidelityfx.so','FidelityFX-MIT.txt','libmonado-fsr3.so',
                  'AMD-FidelityFX-LICENSE.txt','libmonado-present-observer.so','DejaVu-font-license.txt'}


def inspect_with_host_tool(argv):
    # The standalone builder's Python requires private libraries; native host
    # inspection tools must instead use their own distribution's loader set.
    result = subprocess.run(argv, capture_output=True, text=True, errors='replace', timeout=30,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError('Runtime inspection command failed (exit ' + str(result.returncode)
            + '): ' + str(argv[0]) + '\nstdout:\n' + result.stdout[-4096:]
            + '\nstderr:\n' + result.stderr[-4096:])
    if len(result.stdout) > 8 * 1024 * 1024:
        raise ValueError('Runtime inspection output exceeds its bound: ' + str(argv[0]))
    return result

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def ordinary(path,maximum=MAX_TOTAL):
    p=Path(path).absolute()
    if p!=p.resolve():raise ValueError('bundle path cannot traverse symlinks: '+str(p))
    s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.geteuid() or s.st_size>maximum:
        raise ValueError('bundle member must be bounded ordinary owned file: '+str(p))
    return p

def document(path,maximum=MAX_JSON):
    return json.loads(ordinary(path,maximum).read_text())

def encoded(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()

def no_replace(source,destination):
    # Linux's atomic no-replace operation also protects an existing empty folder.
    libc=ctypes.CDLL(None,use_errno=True)
    rename=libc.renameat2;rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(-100,os.fsencode(source),-100,os.fsencode(destination),1):
        e=ctypes.get_errno();raise OSError(e,os.strerror(e),str(destination))

def fresh_destination(path):
    p=Path(path).absolute()
    if p.parent!=p.parent.resolve() or not p.parent.is_dir() or p.exists() or p.is_symlink():
        raise ValueError('bundle destination must be fresh under an ordinary existing directory')
    return p

def validate_name(name):
    p=PurePosixPath(name)
    if (p.is_absolute() or len(p.parts)!=1 or name in EXCLUDED or
        not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',name)):
        raise ValueError('invalid or game-derived runtime bundle filename: '+name)
    return name

def inspect_runtime(binary,receipt):
    b=ordinary(binary)
    with b.open('rb') as f:h=f.read(64)
    if (len(h)!=64 or h[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(h[18:20],'little')!=62 or
        int.from_bytes(h[16:18],'little') not in (2,3) or not int.from_bytes(h[56:58],'little')):
        raise ValueError('native x86-64 little-endian ELF runtime required')
    if receipt.get('status')!='passed' or receipt.get('split_game') is not True:
        raise ValueError('successful separate-game runtime receipt required')
    if receipt.get('executable',{}).get('sha256')!=digest(b):raise ValueError('runtime differs from receipt')
    abi=receipt.get('gamecode_abi',{}).get('id')
    if not isinstance(abi,str) or not HEX.fullmatch(abi):raise ValueError('versioned content ABI required')
    if receipt.get('sources_before')!=receipt.get('sources_after') or not receipt.get('sources_before'):
        raise ValueError('runtime source closure changed or is absent')
    # Require an inspectable symbol table. A stripped image cannot demonstrate
    # the absence of lifted functions by merely hiding their symbol names.
    r=inspect_with_host_tool(['/usr/bin/readelf','-SW',str(b)])
    if '.symtab' not in r.stdout:raise ValueError('runtime symbol table required for game-code exclusion')
    r=inspect_with_host_tool(['/usr/bin/nm','--defined-only',str(b)])
    names={line.split()[-1] for line in r.stdout.splitlines() if line.split()}
    if not {'main','_start'}.issubset(names):raise ValueError('runtime executable entry points missing')
    if any(re.fullmatch(r'f_[0-9a-fA-F]{10,}',line.split()[-1]) for line in r.stdout.splitlines() if line.split()):
        raise ValueError('runtime contains lifted game functions')
    # Bind the actual successful native link to authored objects, not game units.
    links=[c for c in receipt.get('commands',[]) if c.get('name')=='link-graphics' and c.get('exit')==0]
    if not links and not receipt.get('runtime_link_objects'):
        raise ValueError('authored runtime link provenance missing')
    if links:
        argv=set(map(str,links[-1]['argv']))
        for name in receipt.get('generated',{}):
            row=receipt.get('objects',{}).get(name,{})
            if row.get('path') in argv:raise ValueError('game object was linked into runtime')
        if any('gamelib_entry_linux' in x for x in argv):raise ValueError('game table entry linked into runtime')
    return abi

def export_bundle(executable,destination_archive,source_manifest_sha256,*,include_resources=None):
    if not HEX.fullmatch(source_manifest_sha256):raise ValueError('source manifest SHA256 required')
    binary=ordinary(executable);receipt=document(binary.parent/'receipt.json',MAX_BUILD_RECEIPT);abi=inspect_runtime(binary,receipt)
    target=fresh_destination(destination_archive)
    sources={'xcde-linux':binary};resources={};required={}
    all_local=include_resources=='all-local'
    selected=PUBLIC_RESOURCES if include_resources is None else set(receipt.get('runtime_resources',{})) if all_local else set(include_resources)
    for name,row in receipt.get('runtime_resources',{}).items():
        if name in EXCLUDED:continue
        validate_name(name)
        if name not in selected:
            required[name]={'bytes':row.get('bytes'),'sha256':row['sha256']};continue
        p=ordinary(binary.parent/name)
        if digest(p)!=row['sha256']:raise ValueError('companion differs from receipt: '+name)
        sources[name]=p;resources[name]={'path':name,'bytes':p.stat().st_size,'sha256':row['sha256']}
    # Never embed game input/objects, generated-unit hashes or private build logs.
    clean={k:receipt[k] for k in ('schema','status','split_game','gamecode_abi','sources_before','sources_after',
        'dlss_enabled','fsr3_enabled','fsr4_enabled','framegen_enabled','assertions_enabled','precompile_protocol',
        'cuda_task_metadata_protocol','fps_font_resources','source_compile_policy',
        'source_compile_policy_kind') if k in receipt}
    clean['executable']={'path':'xcde-linux','sha256':digest(binary)};clean['runtime_resources']=resources
    clean['runtime_link_objects']={name:{'source_sha256':row.get('source_sha256'),'object_sha256':row.get('object_sha256')}
        for name,row in receipt.get('objects',{}).items() if name not in receipt.get('generated',{}) and name!='runtime/host/gamelib_entry_linux.c'}
    if not clean['runtime_link_objects']:clean['runtime_link_objects']=receipt.get('runtime_link_objects',{})
    metadata=encoded(clean)
    if len(metadata)>MAX_JSON:raise ValueError('cleaned runtime receipt exceeds transport JSON bound')
    files={name:{'bytes':p.stat().st_size,'sha256':digest(p),'mode':0o755 if name=='xcde-linux' or '.so' in name else 0o644}
           for name,p in sources.items()}
    files['receipt.json']={'bytes':len(metadata),'sha256':hashlib.sha256(metadata).hexdigest(),'mode':0o644}
    if len(files)>MAX_FILES or sum(x['bytes'] for x in files.values())>MAX_TOTAL:raise ValueError('runtime bundle exceeds bounds')
    manifest={'schema':1,'format':'monado-authored-runtime','abi_id':abi,'source_manifest_sha256':source_manifest_sha256,
              'files':files,'required_local_resources':required,'distribution':'local-development-not-a-redistribution-approval',
              'game_code_included':False,'features':{k:bool(receipt.get(k,False)) for k in ('dlss_enabled','fsr3_enabled','fsr4_enabled','framegen_enabled')}}
    manifest_data=encoded(manifest)
    if len(manifest_data)>MAX_JSON:raise ValueError('runtime manifest exceeds transport JSON bound')
    fd,temp=tempfile.mkstemp(prefix='.runtime-bundle-',dir=target.parent);os.close(fd)
    try:
        with tarfile.open(temp,'w:gz') as tar:
            for name in sorted(files):
                info=tarfile.TarInfo(name);info.size=files[name]['bytes'];info.mode=files[name]['mode'];info.mtime=0
                if name=='receipt.json':tar.addfile(info,io.BytesIO(metadata))
                else:
                    with sources[name].open('rb') as f:tar.addfile(info,f)
            info=tarfile.TarInfo('manifest.json');info.size=len(manifest_data);info.mode=0o644;tar.addfile(info,io.BytesIO(manifest_data))
        # Detect changing build artifacts even if a concurrent writer raced tar.
        for name,p in sources.items():
            if digest(p)!=files[name]['sha256']:raise ValueError('runtime changed during export')
        no_replace(temp,target)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    manifest['archive_sha256']=digest(target);return manifest

def import_bundle(archive,destination,expected_sha256,expected_abi,expected_source_manifest):
    if not all(isinstance(x,str) and HEX.fullmatch(x) for x in (expected_sha256,expected_abi,expected_source_manifest)):
        raise ValueError('external archive/source/ABI identities required')
    archive=ordinary(archive)
    if digest(archive)!=expected_sha256:raise ValueError('runtime archive SHA256 differs')
    target=fresh_destination(destination);work=Path(tempfile.mkdtemp(prefix='.runtime-import-',dir=target.parent))
    try:
        with tarfile.open(archive,'r:gz') as tar:
            members={};total=0
            for m in tar:
                validate_name(m.name)
                if not m.isfile() or m.issym() or m.islnk() or m.name in members or m.size<0:
                    raise ValueError('nonordinary or duplicate runtime member')
                total+=m.size
                if len(members)>=MAX_FILES+1 or total>MAX_TOTAL+MAX_JSON:raise ValueError('runtime archive exceeds bounds')
                members[m.name]=m
            m=members.get('manifest.json')
            if not m or m.size>MAX_JSON:raise ValueError('runtime manifest missing or oversized')
            manifest=json.loads(tar.extractfile(m).read())
            if (manifest.get('schema')!=1 or manifest.get('format')!='monado-authored-runtime' or
                manifest.get('abi_id')!=expected_abi or manifest.get('source_manifest_sha256')!=expected_source_manifest or
                manifest.get('game_code_included') is not False):raise ValueError('runtime manifest identity differs')
            files=manifest.get('files',{})
            if not isinstance(files,dict) or set(files)!=(set(members)-{'manifest.json'}) or not {'xcde-linux','receipt.json'}.issubset(files):
                raise ValueError('runtime manifest file set differs')
            for name,row in files.items():
                validate_name(name);m=members[name]
                if type(row.get('bytes')) is not int or row['bytes']!=m.size or not HEX.fullmatch(row.get('sha256','')):
                    raise ValueError('invalid runtime member identity')
                with tar.extractfile(m) as src,(work/name).open('xb') as dst:shutil.copyfileobj(src,dst,1048576)
                if digest(work/name)!=row['sha256']:raise ValueError('runtime member hash differs: '+name)
                (work/name).chmod(0o755 if name=='xcde-linux' or '.so' in name else 0o644)
            (work/'manifest.json').write_bytes(encoded(manifest))
        receipt=document(work/'receipt.json')
        if inspect_runtime(work/'xcde-linux',receipt)!=expected_abi:raise ValueError('imported runtime ABI differs')
        if digest(archive)!=expected_sha256:raise ValueError('runtime archive changed during import')
        no_replace(work,target);return manifest
    finally:
        if work.exists():shutil.rmtree(work)

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    e=s.add_parser('export');e.add_argument('executable',type=Path);e.add_argument('output',type=Path);e.add_argument('--source-manifest-sha256',required=True);e.add_argument('--all-local-companions',action='store_true')
    i=s.add_parser('import');i.add_argument('archive',type=Path);i.add_argument('output',type=Path);i.add_argument('--sha256',required=True);i.add_argument('--abi',required=True);i.add_argument('--source-manifest-sha256',required=True)
    a=p.parse_args()
    try:
        result=export_bundle(a.executable,a.output,a.source_manifest_sha256,include_resources='all-local' if a.all_local_companions else None) if a.command=='export' else import_bundle(a.archive,a.output,a.sha256,a.abi,a.source_manifest_sha256)
        print(json.dumps(result,indent=2))
    except (OSError,ValueError,tarfile.TarError,subprocess.SubprocessError) as error:p.exit(1,str(error)+'\n')
if __name__=='__main__':main()
