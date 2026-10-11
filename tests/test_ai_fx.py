"""Bounded vector effects, finite transforms and transparent sprite composition."""
import math
import unittest
from unittest.mock import patch
from PIL import Image, ImageChops
import ai_fx as fx


class MotionTests(unittest.TestCase):
    def test_all_families_are_finite_and_bounded(self):
        for name in ('bob','hop','jump','quick','rock','sway','slow','float','shake',
                     'squish','gift','jolt','dash','leave'):
            for t in (0,.01,.14,.65,1,2.2,10,1e300):
                v=fx.motion(name,t)
                self.assertEqual(len(v),5)
                self.assertTrue(all(math.isfinite(x) for x in v))
                self.assertLessEqual(abs(v[0]),.3);self.assertLessEqual(abs(v[1]),.15)
                self.assertLessEqual(abs(v[2]),4)
                self.assertTrue(.9<=v[3]<=1.1 and .9<=v[4]<=1.1)

    def test_unknown_or_invalid_motion_is_identity(self):
        for name,t in ((None,0),('not-a-motion',10),('bob',True),('bob',-1),
                       ('bob',float('nan')),('bob',float('inf'))):
            self.assertEqual(fx.motion(name,t),fx.IDENTITY)

    def test_periodic_bob_and_one_shot_exit(self):
        self.assertEqual(fx.motion('bob',0),fx.IDENTITY)
        self.assertAlmostEqual(fx.motion('bob',1.6)[1],-.025)
        self.assertEqual(fx.motion('bob',3.2),fx.IDENTITY)
        self.assertEqual(fx.motion('leave',1),fx.motion('leave',100))
        self.assertEqual(fx.motion('dash',0),fx.motion('dash',1))

    def test_translation_preserves_pixels_and_object_identity(self):
        image=Image.new('RGBA',(20,40),(1,2,3,128))
        with patch.object(Image.Image,'transform',side_effect=AssertionError('unexpected resampling')):
            out,at=fx.apply(image,(.1,-.05,0,1,1))
        self.assertIs(out,image);self.assertEqual(at,(4,-2))

    def test_transform_preserves_source_and_foot_anchor(self):
        image=Image.new('RGBA',(50,80))
        for x in range(23,28):
            for y in range(76,80):image.putpixel((x,y),(0,255,0,255))
        before=image.tobytes()
        out,(ox,oy)=fx.apply(image,(0,0,4,.96,1.05))
        self.assertEqual(image.tobytes(),before)
        points=[(x+ox,y+oy) for y in range(out.height) for x in range(out.width)
                if out.getpixel((x,y))[1]>200 and out.getpixel((x,y))[3]>100]
        self.assertTrue(points)
        self.assertLess(abs(sum(x for x,y in points)/len(points)-25),3)
        self.assertLess(abs(sum(y for x,y in points)/len(points)-78),3)
        self.assertEqual(out.mode,'RGBA')

    def test_invalid_transform_is_safe_and_extreme_values_are_clamped(self):
        image=Image.new('RGBA',(40,80),(255,0,0,255))
        for value in (None,(),(0,0,0,True,1),(float('nan'),0,0,1,1)):
            self.assertIs(fx.apply(image,value)[0],image)
        out,at=fx.apply(image,(1e20,-1e20,1e20,1e20,-1e20))
        self.assertLess(out.width*out.height,20000)
        self.assertTrue(all(type(x) is int for x in at))

    def test_crossfade_endpoints_and_premultiplied_transparency(self):
        old=Image.new('RGBA',(10,10),(255,0,0,255))
        new=Image.new('RGBA',(10,10),(0,0,255,0))
        self.assertIs(fx.crossfade(old,new,0),old);self.assertIs(fx.crossfade(old,new,1),new)
        color=fx.crossfade(old,new,.5).getpixel((5,5))
        self.assertEqual(color[:3],(255,0,0));self.assertTrue(126<=color[3]<=128)
        self.assertEqual(old.getpixel((5,5)),(255,0,0,255))

    def test_crossfade_rejects_mismatched_or_unbounded_canvases(self):
        with self.assertRaises(ValueError):fx.crossfade(Image.new('RGBA',(1,1)),Image.new('RGBA',(2,1)),.5)
        with self.assertRaises(ValueError):fx.crossfade(None,None,.5)


class EffectTests(unittest.TestCase):
    def test_every_effect_is_deterministic_nonempty_and_clipped(self):
        for u in (1,1.5):
            for name in fx._EFFECTS:
                a=Image.new('RGBA',(660,441));b=a.copy()
                bounds=(10*u,35*u,164*u,210*u)
                fx.draw(a,name,1.1,bounds,u,'#c3a1ed')
                fx.draw(b,name,1.1,bounds,u,'#c3a1ed')
                self.assertEqual(a.tobytes(),b.tobytes(),name)
                box=a.getchannel('A').getbbox()
                self.assertIsNotNone(box,name)
                self.assertLessEqual(box[2],math.ceil(174*u),name)
                self.assertIsNone(a.crop((math.ceil(174*u),0,660,441)).getchannel('A').getbbox(),name)

    def test_real_pad_and_negative_origin_are_clipped_to_canvas(self):
        image=Image.new('RGBA',(200,250))
        fx.draw(image,'happy',.7,(-20,-12,190,230),1,'#aabbcc')
        self.assertIsNotNone(image.getchannel('A').getbbox())
        self.assertIsNone(image.crop((174,0,200,250)).getchannel('A').getbbox())

    def test_unknown_software_cards_and_malformed_inputs_paint_nothing(self):
        for name,age,bounds,u,color in (('terminal',1,(0,0,100,100),1,'#ffffff'),
              ('not-known',1,(0,0,100,100),1,'#ffffff'),('pat',True,(0,0,100,100),1,'#ffffff'),
              ('pat',-1,(0,0,100,100),1,'#ffffff'),('pat',float('inf'),(0,0,100,100),1,'#ffffff'),
              ('pat',1,(0,0,100,100),True,'#ffffff'),('pat',1,(0,0,100,100),5,'#ffffff'),
              ('pat',1,(100,0,0,100),1,'#ffffff'),('pat',1,(0,0,100,100),1,'bad-color')):
            image=Image.new('RGBA',(250,250))
            fx.draw(image,name,age,bounds,u,color)
            self.assertIsNone(image.getchannel('A').getbbox())

    def test_no_blur_or_full_workspace_allocation(self):
        image=Image.new('RGBA',(660,441))
        original=Image.new;alloc=[]
        def allocated(mode,size,*args,**kw):
            alloc.append(size);return original(mode,size,*args,**kw)
        with patch('ai_fx.Image.new',side_effect=allocated),patch.object(Image.Image,'filter',side_effect=AssertionError('blur')):
            fx.draw(image,'thinking',2,(5,80,170,330),1,'#aabbcc')
        self.assertEqual(len(alloc),1)
        self.assertLessEqual(alloc[0][0],174);self.assertLess(alloc[0][1],441)

    def test_extreme_finite_age_and_external_palette_are_safe(self):
        image=Image.new('RGBA',(260,280))
        fx.draw(image,'thinking',1e300,(0,10,170,220),1,(80,120,160))
        self.assertIsNotNone(image.getchannel('A').getbbox())


    def test_thought_cloud_stays_above_visible_art_at_desktop_scales(self):
        for u in (.76, 1, 1.5, 4):
            for age in (0, .6, 1.2, 1e300):
                image=Image.new('RGBA',(math.ceil(220*u),math.ceil(250*u)))
                head=31*u
                fx.draw(image,'thinking',age,(8*u,head,164*u,220*u),u,'#c3a1ed')
                bounds=image.getchannel('A').getbbox()
                self.assertIsNotNone(bounds,(u,age))
                self.assertGreaterEqual(bounds[0],0)
                self.assertGreaterEqual(bounds[1],0)
                self.assertLessEqual(bounds[2],math.ceil(174*u))
                self.assertLessEqual(bounds[3],math.ceil(head-u))
                self.assertIsNone(image.crop((0,math.ceil(head),image.width,image.height)).getchannel('A').getbbox())

    def test_thought_cloud_has_outlined_white_body_and_two_separate_tail_bubbles(self):
        image=Image.new('RGBA',(200,180))
        fx.draw(image,'thinking',0,(12,55,164,170),1,'#c3a1ed')
        pixels={(x,y) for y in range(55) for x in range(174) if image.getpixel((x,y))[3]}
        components=[]
        while pixels:
            seed=pixels.pop(); todo=[seed]; component={seed}
            while todo:
                x,y=todo.pop()
                for point in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if point in pixels:
                        pixels.remove(point);todo.append(point);component.add(point)
            components.append(component)
        self.assertEqual(len(components),3)
        body=max(components,key=len)
        self.assertGreater(len(body),400)
        white=sum(1 for point in body if min(image.getpixel(point)[:3])>245)
        border=sum(1 for point in body if max(image.getpixel(point)[:3])<105)
        self.assertGreater(white,200)
        self.assertGreater(border,70)
        tails=sorted(len(c) for c in components if c is not body)
        self.assertTrue(5<=tails[0]<tails[1]<=60,tails)

    def test_thought_dots_brighten_in_order_without_transparent_holes(self):
        centers=[]
        for age in (.6,.9,1.2):
            image=Image.new('RGBA',(200,180))
            fx.draw(image,'thinking',age,(12,55,164,170),1,(100,60,160))
            dots=[(x,y,image.getpixel((x,y))) for y in range(55) for x in range(174)
                  if image.getpixel((x,y))[2]-image.getpixel((x,y))[1]>25
                  and image.getpixel((x,y))[2]-image.getpixel((x,y))[0]>15]
            self.assertTrue(dots)
            self.assertTrue(all(p[3]==255 for x,y,p in dots))
            low=min(sum(p[:3]) for x,y,p in dots)
            active=[x for x,y,p in dots if sum(p[:3])==low]
            centers.append(sum(active)/len(active))
        self.assertGreater(centers[1]-centers[0],5)
        self.assertGreater(centers[2]-centers[1],5)

    def test_thought_cloud_floats_as_one_shape_and_preserves_sprite_and_workflow(self):
        source=Image.new('RGBA',(330,280),(31,32,44,255))
        images=[];bounds=[]
        for age in (0,1.2):
            image=source.copy()
            fx.draw(image,'thinking',age,(15,80,230,250),1.5,'#e8a33d')
            diff=ImageChops.difference(image.convert('RGB'),source.convert('RGB'))
            bounds.append(diff.getbbox());images.append(image)
            self.assertIsNone(diff.crop((0,80,330,280)).getbbox())
            self.assertIsNone(diff.crop((261,0,330,280)).getbbox())
        self.assertEqual(bounds[0][0],bounds[1][0])
        self.assertEqual(bounds[0][2],bounds[1][2])
        self.assertTrue(1<=bounds[0][1]-bounds[1][1]<=3,bounds)
        self.assertEqual(bounds[0][3]-bounds[0][1],bounds[1][3]-bounds[1][1])

    def test_thought_cloud_fits_short_headroom_and_omits_impossible_placement(self):
        small=Image.new('RGBA',(85,80))
        fx.draw(small,'thinking',1.2,(0,12,80,75),1,'#aabbcc')
        bounds=small.getchannel('A').getbbox()
        self.assertIsNotNone(bounds)
        self.assertLessEqual(bounds[2],85);self.assertLessEqual(bounds[3],11)
        for head in (-12,0,1):
            image=Image.new('RGBA',(85,80))
            fx.draw(image,'thinking',0,(0,head,80,75),1,'#aabbcc')
            self.assertIsNone(image.getchannel('A').getbbox())



if __name__=='__main__':
    unittest.main()
