"""Colour themes for the whole UI: workspace panel, chat, bubbles, menus, card.

'xiaoqiao' repeats today's constants exactly (flat_workspace, apple_ui, the
UI_* menu colours and ui3d's calm material), so Xiaoqiao mode looks the same.
The four AI themes take their base colours from the Mac theme previews
(琥珀书页 / 银雾龙庭 / 星紫灵感 / 深海静舱); everything else is derived.
State colours (running / waiting / error / done) never change with a theme.
"""
from dataclasses import dataclass
from types import MappingProxyType

from apple_ui import Palette
import apple_ui


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(rgb[:3])


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    panel: MappingProxyType      # flat_workspace: BG LINE INK DIM ACCENT RIM SEL
    apple: object                # apple_ui module or Palette (chat, bubbles)
    menu: MappingProxyType       # Tk Menu colour options
    card: MappingProxyType       # InteractionCard colours and ui3d calm tones


XIAOQIAO = Theme(
    'xiaoqiao', '魔女紫',
    MappingProxyType(dict(BG='#1d1e2e', LINE='#363850', INK='#f4f5fc', DIM='#b4b7cc',
                          ACCENT='#baa3ed', RIM='#666b96', SEL='#35343d')),
    apple_ui,
    MappingProxyType(dict(bg='#2F2342', fg='#F5EFE6', activebackground='#3B2E52',
                          activeforeground='#F5EFE6', disabledforeground='#B5A8C7',
                          selectcolor='#342848')),
    MappingProxyType(dict(bg='#251C35', panel='#2F2342', field='#342848', border='#4A3A60',
                          title='#F5EFE6', text='#F5EFE6', dim='#B5A8C7', gold='#DFC598',
                          accent='#7C58B8',
                          calm=((43, 32, 58), (30, 22, 42)), edge=(214, 189, 148),
                          button=((60, 47, 80), (50, 39, 68)),
                          button_accent=((132, 96, 192), (110, 78, 168)),
                          button_off=((44, 36, 56), (38, 31, 48)))),
)


def _derive(key, label, *, bg, ink, dim, accent, rim, mine, edge):
    chat = _mix(bg, accent, .05)
    elev, elev2, elev3 = (_mix(chat, ink, t) for t in (.08, .12, .17))
    palette = Palette(key, BG=chat, ELEV=elev, ELEV2=elev2, ELEV3=elev3, SEP=_mix(chat, rim, .35),
                      TEXT=ink, TEXT2=dim, TEXT3=_mix(dim, chat, .45), BLUE=mine,
                      HAIR=tuple(edge) + (70,))
    menu_bg = _mix(chat, ink, .05)
    return Theme(
        key, label,
        MappingProxyType(dict(BG=_hex(bg), LINE=_hex(_mix(bg, rim, .3)), INK=_hex(ink),
                              DIM=_hex(dim), ACCENT=_hex(accent), RIM=_hex(rim),
                              SEL=_hex(_mix(bg, accent, .14)))),
        palette,
        MappingProxyType(dict(bg=_hex(menu_bg), fg=_hex(ink), activebackground=_hex(elev2),
                              activeforeground=_hex(ink), disabledforeground=_hex(dim),
                              selectcolor=_hex(elev))),
        MappingProxyType(dict(bg=_hex(chat), panel=_hex(menu_bg), field=_hex(elev),
                              border=_hex(_mix(chat, rim, .35)), title=_hex(ink), text=_hex(ink),
                              dim=_hex(dim), gold=_hex(_mix(edge, ink, .35)), accent=_hex(mine),
                              calm=(_mix(chat, ink, .05), _mix(chat, (0, 0, 0), .2)),
                              edge=tuple(edge),
                              button=(_mix(chat, ink, .13), _mix(chat, ink, .09)),
                              button_accent=(_mix(mine, ink, .12), mine),
                              button_off=(_mix(chat, ink, .05), chat))),
    )


THEMES = MappingProxyType({
    'xiaoqiao': XIAOQIAO,
    'claude': _derive('claude', '琥珀书页', bg=(40, 31, 27), ink=(247, 236, 224), dim=(196, 176, 158),
                      accent=(236, 163, 110), rim=(168, 105, 64), mine=(160, 92, 50),
                      edge=(222, 160, 110)),
    'codex': _derive('codex', '银雾龙庭', bg=(33, 39, 56), ink=(238, 241, 250), dim=(170, 178, 200),
                     accent=(184, 172, 240), rim=(128, 124, 176), mine=(102, 98, 166),
                     edge=(200, 196, 236)),
    'gemini': _derive('gemini', '星紫灵感', bg=(28, 27, 54), ink=(242, 239, 252), dim=(178, 172, 212),
                      accent=(182, 154, 246), rim=(122, 96, 214), mine=(118, 84, 206),
                      edge=(190, 166, 246)),
    'deepseek': _derive('deepseek', '深海静舱', bg=(16, 30, 52), ink=(232, 240, 251), dim=(160, 180, 206),
                        accent=(126, 170, 240), rim=(78, 124, 196), mine=(48, 96, 172),
                        edge=(140, 184, 236)),
    'glm': _derive('glm', '墨夜狐影', bg=(22, 27, 40), ink=(235, 239, 248), dim=(166, 176, 199),
                   accent=(151, 169, 212), rim=(84, 105, 148), mine=(78, 101, 158),
                   edge=(160, 178, 213)),
})


def theme(key):
    """Unknown keys fall back to Xiaoqiao's violet, never to a half-applied mix."""
    return THEMES.get(key, XIAOQIAO) if isinstance(key, str) else XIAOQIAO
