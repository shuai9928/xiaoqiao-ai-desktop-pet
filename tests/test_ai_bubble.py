"""AI speech fits real alpha bounds and bypasses the hidden Xiaoqiao rig."""
import os
import random
import time
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageChops
import ai_bubble as b
import apple_ui
import appearance
import ai_fx
import flat_workspace as f
import pet
import ui_themes
from test_appearance import shell, flat_snapshot
from test_ai_pet import Catalog, Rng
from ai_pet import AiPetDirector


class SpeechTests(unittest.TestCase):
    def test_duration_is_readable_and_bounded(self):
        self.assertEqual(b.duration('我想想'), 6)
        self.assertEqual(b.duration('长'*100000), 10)

    def test_real_character_bounds_fit_without_covering_art_or_workflow(self):
        catalog = appearance.CharacterCatalog.load(pet.ASSETS)
        for u in (.76, 1, 1.5):
            for pad in (0, round(20*u), round(38*u)):
                x, y, size = f.static_layout(u, pad)
                for c in ('claude','codex','gemini','deepseek','glm'):
                    for pose in ('idle', 'thinking', 'writing', 'pat', 'sleeping'):
                        frame = catalog.frame(c, pose, size)
                        bb = frame.image.getchannel('A').getbbox()
                        head = (x+frame.offset[0]+bb[0], y+frame.offset[1]+bb[1],
                                x+frame.offset[0]+bb[2], y+frame.offset[1]+bb[3])
                        for line in ('我在想～', '这是一段需要截断而不能越过角色左栏的很长台词'*20):
                            art = b.sprite(line, apple_ui.font(round(13*u), 480), u, head[1]-4*u, (128, 96, 164))
                            self.assertIsNotNone(art, (u,pad,c,pose))
                            at = b.placement(art, head, (round(440*u),round(274*u)+pad),u)
                            self.assertGreaterEqual(at[0], 0)
                            self.assertGreaterEqual(at[1], 0)
                            self.assertLessEqual(at[0]+art.width, round(174*u))
                            self.assertLessEqual(at[1]+art.height, head[1], (u,pad,c,pose))

    def test_invalid_scale_and_no_space_do_not_allocate(self):
        font = apple_ui.font(13,480)
        for u in (True,0,5,float('inf'),float('nan')):
            self.assertIsNone(b.sprite('hi',font,u,30,(128,96,164)))
        self.assertIsNone(b.sprite('hi',font,1,2,(128,96,164)))
        self.assertIsNone(b.sprite('',font,1,30,(128,96,164)))

    def test_motion_and_crossfade_envelope_always_leave_a_readable_line(self):
        catalog=appearance.CharacterCatalog.load(pet.ASSETS)
        for u in (.76,1,1.5):
            for pad in (0,round(20*u)):
                x,y,size=f.static_layout(u,pad)
                for c in ('claude','codex','gemini','deepseek','glm'):
                    for pose,motion in (('listening','hop'),('happy','jump'),('yawn','squish'),('thinking','rock'),('idle','bob')):
                        frame=catalog.frame(c,pose,size)
                        for age in (.2,.35,.4,.6,1.1,1.6):
                            img,delta=ai_fx.apply(frame.image,ai_fx.motion(motion,age))
                            bb=img.getchannel('A').getbbox()
                            head=(x+frame.offset[0]+delta[0]+bb[0],y+frame.offset[1]+delta[1]+bb[1],
                                  x+frame.offset[0]+delta[0]+bb[2],y+frame.offset[1]+delta[1]+bb[3])
                            art=b.sprite('我在想～',apple_ui.font(round(13*u),480),u,head[1]-4*u,(128,96,164))
                            self.assertIsNotNone(art,(u,pad,c,pose,age))
                            at=b.placement(art,head,(round(440*u),round(274*u)+pad),u)
                            self.assertLessEqual(at[1]+art.height,head[1],(u,pad,c,pose,age))
                    a=Image.new('RGBA',size);a.alpha_composite(frame.image,frame.offset)
                    mixed=ai_fx.crossfade(a,a,.5)
                    self.assertEqual(mixed.getchannel('A').getbbox(),a.getchannel('A').getbbox())

    def test_two_lines_and_no_runtime_blur(self):
        font = apple_ui.font(13,480)
        with patch.object(Image.Image,'filter',side_effect=AssertionError('unexpected blur')):
            one=b.sprite('国'*200,font,1,30,(128,96,164))
            two=b.sprite('国'*200,font,1,55,(128,96,164))
        self.assertGreater(two.height,one.height)
        self.assertLessEqual(two.width,166)
        self.assertLessEqual(two.height,55)


class HostSpeechTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('XIAOQIAO_CHECKS_ISOLATED')!='1':
            raise RuntimeError('Use the isolated checks runner')
        self.clock=1700000000.0
        self.p=shell(bubble=None, ai_announce=True, hwnd=1)
        self.p._fg_probe=Mock()
        self.p._fg_probe.current.return_value=None
        self.p.say=MethodType(pet.Pet.say,self.p)
        self.p.focus_mode=Mock(return_value=True)
        self.tp=patch('pet.time.time',side_effect=lambda:self.clock)
        self.tp.start();self.addCleanup(self.tp.stop)
        with patch('pet.threading.Thread.start'):
            self.p.set_appearance_mode('ai',pin='codex')
        self.p._ai_pet.set_eggs_enabled(False)
        self.p._ai_pet.rng=random.Random(123)

    def test_same_frame_speech_persists_once_and_bypasses_focus_shortening(self):
        self.p._static_click()
        self.p._static_look((172,165))
        self.assertIsNotNone(self.p.bubble)
        before=self.p.bubble
        self.assertGreaterEqual(before[1]-self.clock,6)
        self.clock+=2.5
        self.p._ai_view(self.clock)
        self.assertEqual(self.p.bubble,before)
        self.clock+=2
        self.p._ai_view(self.clock)  # pat ends at 4 s; the readable line remains
        self.assertEqual(self.p.bubble,before)
        self.p.set_appearance_pin('claude')
        self.assertIsNone(self.p.bubble)

    def test_new_work_pose_removes_previous_phase_line_without_repeating_poll(self):
        d=self.p._ai_pet
        self.clock+=3;d.on_work('reading',(),self.clock)
        self.p._ai_view(self.clock)
        self.assertIsNotNone(self.p.bubble)
        self.clock+=3;d.on_work('writing',(),self.clock)
        self.p._ai_view(self.clock)
        self.assertIsNone(self.p.bubble)

    def test_muted_automatic_lines_preserve_active_interaction(self):
        self.p.ai_announce=False
        self.clock+=3;self.p._ai_pet.on_work('reading',(),self.clock)
        self.p._ai_view(self.clock);self.assertIsNone(self.p.bubble)
        self.p._static_click();self.p._ai_view(self.clock)
        self.assertIsNotNone(self.p.bubble)

    def test_text_survives_reduced_motion_drag_and_cache_is_one_sprite(self):
        self.p._static_click();self.p._ai_view(self.clock)
        self.clock+=.25
        head=(2,35,166,225)
        a=Image.new('RGBA',(440,274))
        self.p.drag={'synthetic':True}
        self.p._static_speech(a,head,1)
        self.assertIsNotNone(a.getchannel('A').getbbox())
        self.assertIsNone(a.crop((174,0,440,274)).getchannel('A').getbbox())
        art=self.p._ai_speech_art[1]
        self.p._static_speech(a,head,1)
        self.assertIs(self.p._ai_speech_art[1],art)

    def test_flat_paints_speech_after_consuming_view_without_legacy_mapping(self):
        p=self.p
        p._swing=dict(geo=dict(u=1,k=.2,O=(0,0),flat=True),ui=flat_snapshot(),scene_l=0,scene_t=0,theta=0)
        p._ac=pet.Pet._ac
        p._art_small_map=Mock(side_effect=AssertionError('hidden rig mapping'))
        p._static_effects=Mock()
        p._static_click();self.clock+=.2
        with patch('pet.push_layered'):
            f.push(p,Image.new('RGBA',(200,200),(255,0,0,255)))
        # say was consumed by the same composition; its first instant is alpha 0.
        self.assertIsNotNone(p.bubble)
        self.clock+=.2
        with patch('pet.push_layered'):
            f.push(p,None)
        self.assertIsNotNone(p._ai_speech_art[1])
        p._art_small_map.assert_not_called()

    def test_cloud_yields_to_speech_then_returns(self):
        self.p.ui_reduced_anim=False
        self.clock+=3;self.p._ai_pet.on_work('thinking',(),self.clock)
        self.p._ai_view(self.clock)
        with patch('ai_fx.draw') as draw:
            self.p._static_effects(Image.new('RGBA',(440,274)),(5,40,165,225),1)
            draw.assert_not_called()
            self.clock+=6.1
            self.p._ai_view(self.clock)
            self.p._static_effects(Image.new('RGBA',(440,274)),(5,40,165,225),1)
            draw.assert_called_once()


class WorkLineBoundaryTests(unittest.TestCase):
    def test_new_eight_second_line_gap_boundary(self):
        d=AiPetDirector(Catalog(),rng=Rng(.99),memory={})
        d.set_character('claude',1000,'entered');d.tick(1000)
        d.on_work('reading',(),1003);d.tick(1003)
        d.on_work('writing',(),1006);self.assertEqual(d.tick(1006).say,'')
        d.on_work('running',(),1011);self.assertEqual(d.tick(1011).say,'running台词')


if __name__=='__main__':
    unittest.main()
