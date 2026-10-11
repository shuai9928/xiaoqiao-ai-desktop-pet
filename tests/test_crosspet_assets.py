"""Public fixtures only. Import/check/render tests run inside the isolated stage."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
import appearance as ap

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
sys.path.insert(0, str(ROOT / 'tools'))
import import_crosspet as imp
import build_character_manifests as build


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def fixture(root, *, schema=2, wide=False):
    folder = root / 'characters' / 'demo';folder.mkdir(parents=True)
    Image.new('RGBA', (100, 100), (100, 120, 140, 255)).save(folder / 'idle.png')
    spec = {'file':'idle.png', 'size':[100,100], 'foot_anchor':[50,100],
            'sha256':hashlib.sha256((folder/'idle.png').read_bytes()).hexdigest()}
    poses = {'idle':spec, 'sleep':spec, 'waiting':spec, 'error':spec} if schema == 1 else {'idle':[spec], 'thinking':[spec], 'sleeping':[spec]}
    if wide:
        Image.new('RGBA', (200,100), (180,160,140,255)).save(folder/'wide.png')
        poses['running'] = [dict(spec,file='wide.png',size=[200,100],foot_anchor=[10,100],
            sha256=hashlib.sha256((folder/'wide.png').read_bytes()).hexdigest())]
    data = {'schema_version':schema, 'id':'demo', 'renderer':'static', 'version':1,
            'label':'Demo','theme':'claude','reference_size':[100,100],'poses':poses}
    write_json(folder/'manifest.json',data)
    write_json(root/'characters'/'registry.json',{'schema_version':schema,'themes':{'claude':'Claude'},
        'characters':[{'id':'demo','label':'Demo','theme':'claude','manifest':'demo/manifest.json'}],
        'providers':{'demo':{'character':'demo','theme':'claude','windows_apps':['Demo.exe']}}})
    return folder, data


class CatalogProtocolTests(unittest.TestCase):
    def test_schema1_keeps_original_keys_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root,schema=1);c=ap.CharacterCatalog.load(root)
            self.assertTrue(c.get('demo').available)
            for query,expected in [('waiting','waiting'),('asking','waiting'),('sleeping','sleep'),('oops','error')]:
                self.assertEqual(c.frame('demo',query,(80,100)).pose,expected)
            self.assertEqual(c.frame('demo','running',(80,100)).pose,'idle')
            self.assertEqual(c.frame_count('demo','idle'),1)

    def test_schema2_alias_fallback_and_real_running_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root,wide=True);c=ap.CharacterCatalog.load(root)
            self.assertEqual(c.resolve('demo','running'),'running')
            self.assertEqual(c.resolve('demo','sleep'),'sleeping')
            self.assertEqual(c.resolve('demo','deepthink'),'thinking')
            self.assertFalse(c.has_pose('demo','deepthink'))
            self.assertTrue(c.has_pose('demo','running'))
            self.assertEqual(c.frame_count('demo','deepthink'),1)
            self.assertEqual(c.resolve('nobody','idle'),None)

    def test_wide_picture_shrinks_and_clamps_without_cutting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root,wide=True);c=ap.CharacterCatalog.load(root)
            f=c.frame('demo','running',(80,100))
            self.assertEqual(f.image.size,(80,40))
            self.assertEqual(f.offset,(0,60))
            self.assertEqual(f.image.getchannel('A').getextrema(),(255,255))

    def test_listing_reads_registry_without_resource_io(self):
        with patch.object(ap,'_read_json',wraps=ap._read_json) as reader,patch.object(Image,'open',side_effect=AssertionError('decode/header not allowed')):
            rows=ap.CharacterCatalog.listing(ASSETS)
        self.assertEqual(tuple(p.id for p in rows),('claude','codex','gemini','deepseek','glm'))
        self.assertEqual(reader.call_count,1)

    def test_declared_damaged_variant_disables_whole_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_=fixture(root);c=ap.CharacterCatalog.load(root)
            (folder/'idle.png').unlink()
            self.assertIsNone(c.frame('demo','sleep',(80,100)))
            self.assertFalse(c.get('demo').available)
            self.assertEqual(c.ids(),('xiaoqiao',))

    def test_unconfigured_pose_can_fallback_but_does_not_hide_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,data=fixture(root)
            self.assertEqual(ap.CharacterCatalog.load(root).frame('demo','missing',(80,100)).pose,'idle')
            data['poses']['sleeping'][0]=dict(data['poses']['sleeping'][0],file='missing.png')
            write_json(folder/'manifest.json',data)
            c=ap.CharacterCatalog.load(root)
            self.assertFalse(c.get('demo').available)

    def test_paths_duplicate_keys_nan_animation_and_bad_hash_are_rejected(self):
        for mutation,expected in [
            (lambda d:d['poses']['idle'][0].update(file='../oops.png'),'unsafe_path'),
            (lambda d:d['poses']['idle'][0].update(sha256='0'*64),'image_mismatch'),
            (lambda d:d['poses']['idle'][0].update(foot_anchor=[float('nan'),100]),'invalid_config'),
            (lambda d:d.update(lines={'idle':['bad\nline']}),'invalid_config'),
            (lambda d:d.update(lines={'idle':['x'*41]}),'invalid_config'),
            (lambda d:d.update(behavior={'long_think':{'after':float('inf'),'pose':'thinking'}}),'invalid_config')]:
            with self.subTest(expected=expected),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);folder,data=fixture(root);mutation(data);write_json(folder/'manifest.json',data)
                self.assertFalse(ap.CharacterCatalog.load(root).get('demo').available)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,data=fixture(root)
            Image.new('RGBA',(100,100),'red').save(folder/'animated.png',save_all=True,
                append_images=[Image.new('RGBA',(100,100),'blue')],duration=50,loop=0)
            data['poses']['idle'][0].update(file='animated.png',sha256=hashlib.sha256((folder/'animated.png').read_bytes()).hexdigest())
            write_json(folder/'manifest.json',data)
            self.assertEqual(ap.CharacterCatalog.load(root).get('demo').fallback_reason,'invalid_image')
            (root/'characters'/'registry.json').write_text('{"schema_version":2,"schema_version":2}',encoding='utf-8')
            self.assertEqual(ap.CharacterCatalog.load(root).fallback_reason,'invalid_config')

    def test_package_and_catalog_budgets_reject_before_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            for limit in ('MAX_PACK_PIXELS','MAX_NATIVE_PIXELS','MAX_TOTAL_BYTES','MAX_IMAGE_BYTES'):
                with self.subTest(limit=limit),patch.object(ap,limit,1):
                    self.assertEqual(ap.CharacterCatalog.load(root).get('demo').fallback_reason,'resource_budget')

    def test_metadata_is_recursive_readonly(self):
        c=ap.CharacterCatalog.load(ASSETS)
        self.assertIsInstance(c.lines('claude','idle'),tuple)
        with self.assertRaises(TypeError):c.behavior('claude')['accent']='wrong'
        with self.assertRaises(TypeError):c.behavior('claude')['fx']['proud']='wrong'
        self.assertEqual(c.behavior('egg-codex')['egg']['host'],'codex')
        with self.assertRaises(TypeError):c.behavior('egg-codex')['egg']['host']='claude'

    def test_eggs_are_not_selectable_or_foreground_providers(self):
        c=ap.CharacterCatalog.load(ASSETS);s=ap.AppearanceSelector(c,{})
        self.assertNotIn('egg-codex',c.ids())
        self.assertEqual(c.eggs_for('codex'),('egg-codex',))
        self.assertTrue(c.get('egg-codex').is_egg)
        self.assertEqual(s.set_mode('ai',initial='egg-codex').character,'claude')
        self.assertEqual(s.set_pin('egg-codex').character,'claude')
        self.assertIsNone(c.provider_for_character('egg-codex'))
        self.assertIsNotNone(c.frame('egg-codex','pop',(164,194)))

    def test_invalid_frame_arguments_do_not_damage_pack(self):
        c=ap.CharacterCatalog.load(ASSETS)
        for size,index,blink in [((0,20),0,False),((100,100),True,False),((100,100),0,1),((4096,4096),0,False)]:
            self.assertIsNone(c.frame('claude','idle',size,index,blink))
        self.assertTrue(c.get('claude').available)


class PublicMaterialTests(unittest.TestCase):
    def setUp(self):self.c=ap.CharacterCatalog.load(ASSETS)

    def test_all_main_and_egg_poses_fit_two_actual_sizes(self):
        c=self.c;observed=0
        for role in c.ids(include_eggs=True):
            if role=='xiaoqiao':continue
            for pose in c.get(role).poses:
                for index in range(c.frame_count(role,pose)):
                    for size in ((172,194),(131,147)):
                        with self.subTest(role=role,pose=pose,index=index,size=size):
                            f=c.frame(role,pose,size,index)
                            self.assertIsNotNone(f);x,y=f.offset
                            self.assertTrue(0<=x and x+f.image.width<=size[0])
                            self.assertTrue(0<=y and y+f.image.height<=size[1])
                            self.assertIsNotNone(f.image.getchannel('A').getbbox())
                            observed+=1
        self.assertGreater(observed,400)
        self.assertLessEqual(len(c._natives),ap.MAX_NATIVE_CACHE)
        self.assertLessEqual(len(c._scaled),ap.MAX_SCALED_CACHE)
        self.assertLessEqual(c._scaled_pixels,ap.MAX_SCALED_PIXELS)
        self.assertTrue(all(n.image.height<=400 for n in c._natives.values()))

    def test_variant_order_modulo_and_blink_base_identity(self):
        c=self.c
        for role in ('claude','codex','deepseek'):
            pair=c.blink_index(role)
            self.assertIsNotNone(pair)
            f=c.frame(role,'idle',(172,194),pair)
            self.assertEqual(c._spec(role,'idle',pair).path.name,'idle.webp')
            blink=c.frame(role,'idle',(172,194),pair,True)
            self.assertNotEqual(f.ref,blink.ref)
            self.assertNotEqual(f.image.tobytes(),blink.image.tobytes())
            nonbase=(pair+1)%c.frame_count(role,'idle')
            self.assertIs(c.frame(role,'idle',(172,194),nonbase,True),c.frame(role,'idle',(172,194),nonbase))
            self.assertIs(c.frame(role,'idle',(172,194),pair+c.frame_count(role,'idle')),f)
        for role in ('gemini','glm'):self.assertIsNone(c.blink_index(role))
        self.assertEqual(c._spec('claude','idle',0).path.name,'idle-2.webp')

    def test_prewarm_and_render_are_threadsafe_and_leave_borrowed_images_unchanged(self):
        c=self.c
        with ThreadPoolExecutor(max_workers=4) as workers:
            jobs=[workers.submit(c.prewarm,'claude',['idle','thinking','running']) for _ in range(4)]
            jobs.extend(workers.submit(c.frame,'claude','idle',(172,194),i,True) for i in range(16))
            results=[job.result(timeout=30) for job in jobs]
        self.assertTrue(all(results[:4]))
        f=c.frame('claude','idle',(172,194));original=f.image.tobytes()
        self.assertIs(c.frame('claude','idle',(172,194)),f)
        self.assertEqual(f.image.tobytes(),original)
        self.assertLessEqual(len(c._natives),64)
        c.clear_scaled_cache();self.assertEqual(len(c._scaled),0);self.assertEqual(c._scaled_pixels,0)

    def test_prewarm_bad_resource_disables_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_=fixture(root);c=ap.CharacterCatalog.load(root);(folder/'idle.png').unlink()
            self.assertFalse(c.prewarm('demo',['idle']))
            self.assertFalse(c.get('demo').available)
        self.assertFalse(self.c.prewarm('nobody',['idle']))

    def test_cached_render_is_not_blocked_between_prewarmed_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root);c=ap.CharacterCatalog.load(root)
            cached=c.frame('demo','idle',(80,100))
            between,resume=threading.Event(),threading.Event();results=[]
            original=c.frame_count
            def pause_between(character,pose):
                if threading.current_thread().name=='prewarm-probe' and pose=='thinking':
                    between.set()
                    if not resume.wait(5):raise AssertionError('worker coordination timeout')
                return original(character,pose)
            worker=threading.Thread(target=lambda:results.append(c.prewarm('demo',['idle','thinking'])),name='prewarm-probe')
            with patch.object(c,'frame_count',side_effect=pause_between),ThreadPoolExecutor(max_workers=1) as reader:
                worker.start()
                try:
                    self.assertTrue(between.wait(5),'prewarm did not reach second pose')
                    job=reader.submit(c.frame,'demo','idle',(80,100))
                    self.assertIs(job.result(timeout=2),cached)
                finally:
                    resume.set();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertEqual(results,[True])

    def test_disable_between_resources_stops_prewarm_and_drops_cached_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root);c=ap.CharacterCatalog.load(root)
            c.frame('demo','idle',(80,100))
            between,resume=threading.Event(),threading.Event();results=[]
            original=c.frame_count
            def pause_between(character,pose):
                if threading.current_thread().name=='prewarm-disable' and pose=='thinking':
                    between.set()
                    if not resume.wait(5):raise AssertionError('worker coordination timeout')
                return original(character,pose)
            worker=threading.Thread(target=lambda:results.append(c.prewarm('demo',['idle','thinking'])),name='prewarm-disable')
            with patch.object(c,'frame_count',side_effect=pause_between):
                worker.start()
                try:
                    self.assertTrue(between.wait(5))
                    c.disable('demo','image_missing')
                finally:
                    resume.set();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertEqual(results,[False])
            self.assertFalse(c.get('demo').available)
            self.assertIsNone(c.frame('demo','idle',(80,100)))
            self.assertFalse(any(k[0]=='demo' for k in c._natives))
            self.assertFalse(any(k[0]=='demo' for k in c._scaled))

    def test_concurrent_cold_render_and_prewarm_decode_same_resource_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root);c=ap.CharacterCatalog.load(root)
            start=threading.Barrier(4)
            def warm():
                start.wait(5);return c.prewarm('demo',['idle','thinking','sleeping'])
            def render():
                start.wait(5);return c.frame('demo','idle',(80,100))
            with patch.object(ap,'_picture_bytes',wraps=ap._picture_bytes) as reads,ThreadPoolExecutor(max_workers=4) as jobs:
                futures=[jobs.submit(warm),jobs.submit(render),jobs.submit(warm),jobs.submit(render)]
                results=[job.result(timeout=10) for job in futures]
            self.assertTrue(results[0]);self.assertTrue(results[2])
            self.assertIs(results[1],results[3]);self.assertEqual(reads.call_count,1)

    def test_late_prewarm_failure_disables_all_already_cached_poses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,_=fixture(root,wide=True);c=ap.CharacterCatalog.load(root)
            self.assertIsNotNone(c.frame('demo','idle',(80,100)))
            (folder/'wide.png').unlink()
            self.assertFalse(c.prewarm('demo',['idle','running']))
            self.assertFalse(c.get('demo').available)
            self.assertIsNone(c.frame('demo','idle',(80,100)))
            self.assertFalse(c._scaled);self.assertFalse(c._natives)

    def test_native_lru_reuses_touched_entries_and_evicts_oldest(self):
        c=self.c
        c.prewarm('claude',list(c.get('claude').poses))
        c.prewarm('codex',list(c.get('codex').poses))
        self.assertEqual(len(c._natives),64)
        oldest=next(iter(c._natives))
        # Requesting a resource currently in the cache moves it to the newest end.
        char,path,sha=oldest
        location=next((pose,index) for pose in c.get(char).poses for index in range(c.frame_count(char,pose))
                      if c._spec(char,pose,index).path==path)
        image=c._natives[oldest]
        self.assertIs(c._native(char,*location),image)
        self.assertEqual(next(reversed(c._natives)),oldest)
        c.prewarm('gemini',['idle','thinking'])
        self.assertIn(oldest,c._natives)
        self.assertLessEqual(len(c._natives),64)

    def test_scaled_pixel_budget_evicts_even_below_entry_limit(self):
        c=self.c
        with patch.object(ap,'MAX_SCALED_PIXELS',150_000):
            for h in range(300,315):c.frame('claude','idle',(300,h))
            self.assertLessEqual(c._scaled_pixels,150_000)
            self.assertLess(len(c._scaled),15)

    def test_glm_and_native_process_bindings(self):
        self.assertEqual(self.c.provider_for_process('ZCODE.EXE'),'glm')
        self.assertEqual(self.c.provider_for_process('deepseek harness.exe'),'deepseek')
        for role in ('claude','codex','gemini','deepseek','glm'):
            for pose in self.c.get(role).poses:
                for line in self.c.lines(role,pose):
                    self.assertLessEqual(len(line),40);self.assertNotIn('\n',line)


class ImportGeneratorTests(unittest.TestCase):
    def source(self, root):
        for name in imp.ROLES:
            folder=root/'characters'/name;folder.mkdir(parents=True)
            Image.new('RGBA',(80,640),(20,40,60,128)).save(folder/'idle.webp',lossless=True)
            write_json(folder/'character.json',{'name':name,'accent':'#abcdef','lines':{'idle':['Hello']}})
            (folder/'DO_NOT_RUN.py').write_text('raise RuntimeError("executed")',encoding='utf-8')
        (root/'characters'/'LICENSE.md').write_text('Synthetic fixture license',encoding='utf-8')

    def test_import_is_byte_exact_idempotent_and_does_not_copy_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';dest=root/'assets'/'characters';self.source(source)
            first=imp.import_assets(source,dest)
            self.assertEqual(first['images'],5)
            self.assertEqual((dest/'codex'/'character.json').read_bytes(),(source/'characters'/'gpt'/'character.json').read_bytes())
            mtimes={p:p.stat().st_mtime_ns for p in dest.rglob('*') if p.is_file()}
            second=imp.import_assets(source,dest)
            self.assertFalse(second['changed']);self.assertEqual(first['digest'],second['digest'])
            self.assertEqual(mtimes,{p:p.stat().st_mtime_ns for p in mtimes})
            self.assertFalse(list(dest.rglob('*.py')))

    def test_import_validates_everything_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';dest=root/'assets'/'characters';self.source(source)
            (source/'characters'/'glm'/'idle.webp').write_bytes(b'not an image')
            with self.assertRaises((ValueError,OSError)):imp.import_assets(source,dest)
            self.assertFalse(dest.exists())

    def test_import_check_is_readonly_and_rejects_source_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';dest=root/'assets'/'characters';self.source(source)
            self.assertTrue(imp.import_assets(source,dest,check=True)['changed'])
            self.assertFalse(dest.exists())
            with self.assertRaises(ValueError):imp.import_assets(source,source/'characters')

    def test_generator_matches_public_manifests_without_mutating(self):
        expected=build.build(ASSETS/'characters')
        for path,raw in expected.items():self.assertEqual(path.read_bytes(),raw,path.name)
        self.assertEqual(len(expected),11)
