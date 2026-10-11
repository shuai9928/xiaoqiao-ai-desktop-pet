"""Generate deterministic schema 2 manifests from local public CrossPet material."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_crosspet import atomic_bytes, local_id
ROOT = Path(__file__).resolve().parents[1] / 'assets' / 'characters'
SOURCE_REVISION = 'c6a756e81862e45ffe16bfbccaba5fd301fe822f'
PACKS = {'claude': ('Claude','claude'), 'codex': ('Codex','codex'), 'gemini': ('Gemini','gemini'),
         'deepseek': ('DeepSeek','deepseek'), 'glm': ('GLM','glm')}
THEMES = {'xiaoqiao':'魔女紫','claude':'琥珀书页','codex':'银雾龙庭','gemini':'星紫灵感','deepseek':'深海静舱','glm':'墨夜狐影'}
PROVIDERS = {'claude':('claude',['claude.exe']), 'codex':('codex',['ChatGPT.exe','codex.exe']),
             'gemini':('gemini',['antigravity.exe']), 'deepseek':('deepseek',['deepseek.exe','deepseek harness.exe']),
             'glm':('glm',['ZCode.exe'])}
ID = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')

def anchor(path):
    with Image.open(path) as image:
        if not 0 < image.width <= 4096 or not 0 < image.height <= 4096 or image.width*image.height > 1_000_000:
            raise ValueError('Anchor image exceeds pixel budget')
        alpha = image.convert('RGBA').getchannel('A')
    w,h = alpha.size;total = weighted_x = 0
    for i,value in enumerate(alpha.crop((0,0,w,max(1,int(h*.4)))).tobytes()):
        if value > 32:total += value;weighted_x += value*(i%w)
    return [round(weighted_x/total,1) if total else w/2,h]

def picture(path):
    with Image.open(path) as image:
        if (image.mode != 'RGBA' or image.format != 'WEBP' or getattr(image,'n_frames',1) != 1
                or not 0 < image.width <= 4096 or not 0 < image.height <= 4096
                or image.width*image.height > 1_000_000 or not 0 < path.stat().st_size <= 4*1024*1024):
            raise ValueError('Expected single-frame RGBA WebP: '+path.name)
        size = list(image.size)
    return {'file':path.name,'size':size,'foot_anchor':anchor(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def clean_lines(data):
    rows=data.get('lines',{})
    if not isinstance(rows,dict):raise ValueError('Invalid lines')
    return {key:[line.replace('\r',' ').replace('\n',' ')[:40] for line in values[:16]
                 if isinstance(line,str) and line.strip()]
            for key,values in rows.items() if ID.fullmatch(key) and isinstance(values,list)}

def behavior(data):
    return {'accent':data.get('accent'),'greeting':str(data.get('greeting',''))[:40],
            'idle_actions':data.get('idleActions',[]),'poke_pose':data.get('pokePose'),
            'corrected_pose':data.get('correctedPose'),'long_think':data.get('longThink'),
            'fx':data.get('fx',{}),'glyph':data.get('glyph',{})}

def build(root=ROOT):
    root=Path(root);files={};entries=[]
    for ident in list(PACKS)+sorted(p.name for p in root.glob('egg-*') if p.is_dir()):
        folder=root/ident;data=json.loads((folder/'character.json').read_text(encoding='utf-8-sig'))
        is_egg=ident.startswith('egg-');host=local_id(data.get('host','')) if is_egg else ident
        if host not in PACKS:raise ValueError('Unrecognized egg host')
        label,theme=(data.get('name',ident),host) if is_egg else PACKS[ident]
        poses={};widths=[];heights=[]
        for path in sorted(folder.glob('*.webp'),key=lambda p:p.name):
            if path.stem.endswith('-blink'):continue
            pose=path.stem.split('-',1)[0]
            if not ID.fullmatch(pose):raise ValueError('Invalid pose filename: '+path.name)
            spec=picture(path);poses.setdefault(pose,[]).append(spec)
            widths.append(spec['size'][0]);heights.append(spec['size'][1])
        if not poses or (not is_egg and 'idle' not in poses) or (is_egg and set(poses)!={'pop','pretend','caught','bye'}):
            raise ValueError('Invalid pose set: '+ident)
        widths.sort();reference=[widths[max(0,(85*len(widths)+99)//100-1)],640]
        if any(height!=640 for height in heights):raise ValueError('Expected upstream 640px canvas height')
        blink=None;bp=folder/'idle-blink.webp';idle=folder/'idle.webp'
        if not is_egg and ident not in ('glm','gemini') and bp.is_file() and idle.is_file():
            blink=dict(picture(bp),base='idle.webp');blink['foot_anchor']=anchor(idle)
        manifest={'schema_version':2,'id':ident,'renderer':'static','version':2,'label':label,'theme':theme,
                  'reference_size':reference,
                  'source':f'CrossPet 1.2.4 characters/{"gpt" if ident=="codex" else "egg-gpt" if ident=="egg-codex" else ident}',
                  'source_revision':SOURCE_REVISION,'license':'CC BY-NC-SA 4.0, see ../LICENSE.md',
                  'poses':poses,'blink':blink,'lines':clean_lines(data),'behavior':behavior(data)}
        entry={'id':ident,'label':label,'theme':theme,'version':2,'manifest':f'{ident}/manifest.json'}
        if is_egg:
            manifest['egg']={'host':host,'caption':str(data.get('caption',label))[:40],'aura':data.get('aura',data.get('accent'))}
            entry['egg']=manifest['egg']
        files[folder/'manifest.json']=manifest;entries.append(entry)
    files[root/'registry.json']={'schema_version':2,'themes':THEMES,'characters':entries,
        'providers':{key:{'character':role,'theme':role,'windows_apps':apps} for key,(role,apps) in PROVIDERS.items()}}
    return {path:(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8') for path,data in files.items()}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args();stale=[]
    for path,raw in build(args.root).items():
        if not path.exists() or path.read_bytes()!=raw:
            stale.append(path)
            if not args.check:atomic_bytes(path,raw)
    print(f'Manifests: {len(stale)} '+('stale' if args.check else 'updated'))
    return 1 if args.check and stale else 0
if __name__=='__main__':sys.exit(main())
