"""Build an isolated, clean Windows x64 portable distribution."""
from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, sys, zipfile
ROOT = Path(__file__).resolve().parents[2]
APP = 'DesktopPet'
DIST, BUILD, RELEASE = ROOT/'dist', ROOT/'build', ROOT/'release'
PRIVATE = re.compile(r'^(?:ai_config|memories|chat_history|pet_settings|pet_reminders|pet_state|pet_cmd|ai_quota)(?:[._-].*)?\.json$',re.I)
SKIP = {'.git','.venv','__pycache__','_tts_cache','_archive','ai_sessions','audio_peaknorm_backup','audio_v2','.godot','handoff'}
def allowed(path):
    return not (any(p in SKIP for p in path.parts) or (PRIVATE.match(path.name) and path.name!='ai_config.example.json') or path.name.startswith('.env') or path.suffix.lower() in {'.log','.bak','.tmp','.dmp','.pyc'})
def main():
    if os.name!='nt': raise SystemExit('Build this package with Windows Python.')
    for path in (DIST,BUILD,RELEASE):
        if path.exists(): shutil.rmtree(path)
    BUILD.mkdir(parents=True)
    from PIL import Image
    im=Image.open(ROOT/'assets/main.png').convert('RGBA')
    box=im.getbbox()
    if box: im=im.crop(box)
    side=max(im.size); canvas=Image.new('RGBA',(side,side)); canvas.paste(im,((side-im.width)//2,(side-im.height)//2),im)
    icon=BUILD/'pet.ico'; canvas.save(icon,sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name',APP,'--distpath',str(DIST),'--workpath',str(BUILD),'--specpath',str(BUILD),'--icon',str(icon),'--collect-all','google.genai','--collect-submodules','pystray','--collect-submodules','PIL','--hidden-import','pystray._win32','--hidden-import','tkinter','--hidden-import','tkinter.messagebox','--hidden-import','tkinter.simpledialog']
    for module in ('numpy','matplotlib','scipy','pandas','pytest','IPython'): args += ['--exclude-module',module]
    args.append(str(ROOT/'pet.py'))
    subprocess.run(args,cwd=ROOT,check=True)
    out=RELEASE/APP
    shutil.copytree(DIST/APP,out)
    # SDK test fixtures are unnecessary at runtime and may resemble credentials.
    internal=out/'_internal'
    for path in sorted(internal.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if path.is_dir() and path.name in {'tests','test'}:
            shutil.rmtree(path)
    for src in sorted((ROOT/'assets').rglob('*')):
        if src.is_file() and allowed(src.relative_to(ROOT/'assets')):
            dst=out/'assets'/src.relative_to(ROOT/'assets');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    (out/'assets/ai_config.json').write_text(json.dumps({'enabled':False,'api_key':'','model':'gemini-flash-lite-latest','greet_interval_min':30},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'assets/memories.json').write_text('{"facts": []}\n',encoding='utf-8')
    for name in ('zcode_notify.py','ai_lights_core.py','task_directions.py'):
        shutil.copy2(ROOT/name,out/name)
    for name in ('README.md','ASSET_LICENSES.md','LICENSE','DISTRIBUTION.md'):
        shutil.copy2(ROOT/name,out/name)
    shutil.copytree(ROOT/'docs',out/'docs')
    (out/'使用说明.txt').write_text('AI 桌宠 · Windows I-52 + 表情贴纸恢复\n\n完整解压后双击 DesktopPet.exe，无需 Python。首次启动无需密钥。\n右键 → 场景与设置 → 桌宠形象，可选 AI 自动跟随或固定角色。\n拖动移动、滚轮缩放、双击聊天，菜单或托盘退出。\n本机 Codex/Claude Code 观察自动开启；ZCode/WSL/跨机与账户额度需另配来源。\n自由聊天可选，使用自己的服务配置；个人数据保存在本机程序目录。\n更新先退出旧实例，再解压新版；迁移数据前请备份。\n表情贴纸默认开启，可在设置里关闭；旧设置只迁移一次。\n换成自己的角色请先备份，再看 docs/CUSTOMIZE.md。\n详见 README.md、docs/GUIDE.md 与 ASSET_LICENSES.md。\nAI 角色来自 CrossPet，CC BY-NC-SA 4.0；须署名、非商用、同协议共享。\n',encoding='utf-8')
    zpath=RELEASE/'Xiaoqiao-AI-Pet-Windows-x64.zip'
    with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(out.rglob('*')):
            if path.is_file(): z.write(path,path.relative_to(RELEASE))
    print(json.dumps({'zip':str(zpath),'bytes':zpath.stat().st_size,'sha256':hashlib.sha256(zpath.read_bytes()).hexdigest()},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
