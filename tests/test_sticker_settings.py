"""Shipped sticker migration, settings persistence and appearance isolation."""
from collections import OrderedDict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import pet
from test_core_profile import core_pet


class StickerSettingsTests(unittest.TestCase):
    def test_old_retired_false_and_missing_values_enable_once(self):
        for settings in ({}, {'stickers_enabled': False}, {'stickers_enabled': True},
                         {'stickers_rev': None, 'stickers_enabled': False}):
            p = core_pet()
            p.settings = dict(settings)
            p._restore_sticker_settings()
            self.assertTrue(p.stickers_enabled)
            self.assertEqual(p.settings['stickers_rev'], 1)

    def test_current_explicit_false_is_kept_on_every_reload(self):
        p = core_pet()
        p.settings = {'stickers_rev': 1, 'stickers_enabled': False}
        for _ in range(3):
            p._restore_sticker_settings()
            self.assertFalse(p.stickers_enabled)

    def test_toggle_clears_overlay_and_persists_current_value(self):
        p = core_pet()
        p.settings = {'stickers_enabled': False}
        p._restore_sticker_settings()
        for name, value in {
            'x': 123, 'fy': 456, 'first_day': '2020-01-01', 'catch_best': 0,
            'magic_style': 0, 'pomo_done': 0, 'pomo': None, 'rps': [0, 0, 0],
            'water_min': 0, 'fg_watch': False, 'battery_watch': False,
            'tts_volume': 700, 'city': '', 'city_lat': None, 'city_lon': None,
        }.items():
            setattr(p, name, value)
        p.sticker, p._sticker_previous = {'name': 'okay'}, ('old',)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pet_settings.json'
            with patch.object(pet, 'CONFIG_FILE', str(path)):
                p.toggle_stickers()
                saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertFalse(saved['stickers_enabled'])
            self.assertEqual(saved['stickers_rev'], 1)
            p.settings = saved
            p._restore_sticker_settings()
            self.assertFalse(p.stickers_enabled)
        self.assertIsNone(p.sticker)
        self.assertIsNone(p._sticker_previous)

    def test_ai_mode_does_not_start_sticker_or_xiaoqiao_eyelids(self):
        p = core_pet()
        p._flat_panel_style = True
        p._appearance = SimpleNamespace(mode='ai', selection=SimpleNamespace(renderer='static'))
        p.stickers_enabled = True
        p.sticker = p._sticker_previous = None
        self.assertFalse(p.play_emotion('happy'))
        self.assertIsNone(p.sticker)
        self.assertNotIn('_lid_until', p.__dict__)

    def test_workspace_sticker_stays_inside_character_column_all_scales(self):
        p = core_pet()
        p.stickers_enabled = True
        p.load_expr = Mock(return_value=Image.new('RGBA', (160, 240), '#00ffff'))
        p._expr_rs = OrderedDict()
        p._sticker_previous = None
        p.sticker = {'name': 'synthetic', 'born': 100, 'life': 2.0}
        for u in (.8, 1.0, 1.25, 1.5, 2.0):
            canvas = Image.new('RGBA', (round(440*u), round(200*u)))
            p._paint_workspace_sticker(canvas, 100.8, u)
            bb = canvas.getbbox()
            self.assertIsNotNone(bb)
            self.assertLessEqual(bb[2], round(172*u))
            self.assertGreaterEqual(bb[0], round(120*u))

    def test_disabled_and_ai_workspace_overlay_are_empty(self):
        p = core_pet()
        p.sticker = {'name': 'synthetic', 'born': 100, 'life': 2.0}
        p.stickers_enabled = False
        canvas = Image.new('RGBA', (440, 200))
        p._paint_workspace_sticker(canvas, 100.8, 1)
        self.assertIsNone(canvas.getbbox())
        p.stickers_enabled = True
        p._static_active = lambda: True
        p._paint_workspace_sticker(canvas, 100.8, 1)
        self.assertIsNone(canvas.getbbox())

if __name__ == '__main__':
    unittest.main()
