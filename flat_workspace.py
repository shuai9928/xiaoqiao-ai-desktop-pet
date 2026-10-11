"""Half-height workspace beside her: one two-line group per AI agent, then AIQuota (I-51 refined rows).

One colour per meaning (COLORS, never themed): lavender running, orange waiting / quota burning fast, red error / quota
>=90 %, green a recent finish (glyph only); everything calm is neutral and anything unknown or stale is DIM and says so.
Chips, chevrons, tracks and row tints are mixed from the theme's own BG/INK/DIM, never from its ACCENT."""
import functools, json, math, os, time
from datetime import date
from pathlib import Path
from PIL import Image,ImageColor,ImageDraw
from apple_ui import font
from ai_quota import quota_view, _number, _used, _timestamp
from moon_board import workflow,_fit
from workflow_stages import stages,display_title,detail_steps

BG='#1d1e2e';SURFACE='#2b2c32';LINE='#363850';INK='#f4f5fc';DIM='#b4b7cc';ACCENT='#baa3ed';RIM='#666b96'
COLORS={'running':ACCENT,'waiting':'#efba70','error':'#f39292','done':'#83caa2','idle':DIM,'recorded':DIM}
PY=14;PH=260   # PY: headroom above the panel (her hat rises into it); PH: expanded panel height
W,H=440,PH+PY
SOURCE_REVISION='9ed04b7fcdeeec332b102e361d3fb11414cd4893'
PANEL_REST=232;PANEL_ACTIVE=248   # per-pixel alpha of the panel fill (not blur); rim, glyphs and text stay opaque
SHAPES={'running':'star','waiting':'ring','error':'tri','done':'dot','idle':'dot','recorded':'dot'}
SB_X=428   # scrollbar x (panel units); its click column is SB_X-4 .. SB_X+7
LIST=(180,38+PY,SB_X+7-180,110)   # list well (x, y, w, h) in window units: rows from x=180 (clear of her art), wheel and well reach the scrollbar column
PET_M=1.4;PET_BOX=(142*PET_M,140*PET_M);PET_CX=80;PET_TOP=15   # native artwork needs 5 more units to keep the hat inside the window
ART_OLD=(38.7,9.0,139.8,140.0)   # swing.png content (left, hat tip, right, soles) in the OLD layout's units; fitted to the maintainer's screenshot
SHOW_STAND=False   # the grey A-frame is no longer drawn: the swing hangs free and the studio bounds only set the scale
ROW=22;TROW=36   # list pitch: steps rows are one line, tasks rows are two-line groups like the live view
MIN_HIT=8   # a scrolled-in row needs this many visible units before it takes clicks (no hit on an invisible sliver)


def row_pitch(mode):return TROW if mode=='tasks' else ROW
AGENT_ORDER=('Codex','Claude','ZCode')
LIVE_H=184;LIVE_ROWS=3;LIVE=('running','waiting','error');DEFAULT_MODE='live'
# Theme-able surface colours (ui_themes.Theme.panel). State colours in COLORS/SHAPES never follow a theme.
PALETTE={'BG':BG,'LINE':LINE,'INK':INK,'DIM':DIM,'ACCENT':ACCENT,'RIM':RIM,'SEL':'#35343d'}
STATIC_BOX=(2,-12,174,LIVE_H-2)   # AI pet mode: the static character's box (x, y, right, bottom) in panel units; y<0 reaches into the headroom
_MISSING=object()   # frame.alpha_box absent (older frame producers): measure the sprite's alpha instead
# Hit kinds that do something when clicked; the host shows the hand cursor over them ('swallow' only blocks dragging).
CLICKABLE=frozenset(('flat_task','flat_mode','flat_back','flat_agent','flat_page','flat_thumb','house_chat','detail'))


def agent_name(raw):
    """Map session source keys (including Mac/WSL variants) to a visible agent."""
    value=str(raw or 'AI').lower()
    if value.startswith('mac-claude') or 'claude' in value:return 'Claude'
    if value.startswith('mac-codex') or 'codex' in value:return 'Codex'
    if 'zcode' in value:return 'ZCode'
    if value.startswith('mac'):return 'Mac'
    return 'AI'


def selected_agent(ui):
    """The strip selection drives the workflow list; default to the app selection."""
    raw=ui.get('flat_agent') or (ui.get('sel_session') or {}).get('agent') or ui.get('sel_key')
    return agent_name(raw) if raw else 'ZCode'


def sessions_for(ui,name=None):
    name=name or selected_agent(ui)
    return [s for s in ui.get('sessions') or [] if agent_name(s.get('agent'))==name]


def _stale(ui,s):
    """workflow(...)['stale'] without parsing the action history: the rank sort and the agent strip ask this for every
    session on every panel rebuild (43 real sessions: ~5 ms of trace_rows per rebuild, enough to drop a 60 fps frame)."""
    from pet import ai_session_stale
    return bool(s.get('stale') or (s and ai_session_stale(s,ui.get('now') or time.time())))


def _rank_key(ui,s):
    """Sort key for a provider's sessions: live and fresh first, then by state, then newest."""
    state=s.get('state','idle')
    priority={'running':0,'waiting':1,'error':2,'done':3,'idle':4}
    return (0 if not _stale(ui,s) and state in LIVE else 1,priority.get(state,4),-(_number(s.get('updated')) or 0))


def session_for(ui,name=None,prefer_current=True):
    """Pick a provider's freshest live session, falling back to its latest record."""
    rows=sessions_for(ui,name)
    current=ui.get('sel_session') or {}
    if prefer_current and current and agent_name(current.get('agent'))== (name or selected_agent(ui)):
        return current
    return min(rows,key=lambda s:_rank_key(ui,s)) if rows else None


def _mode(owner):return getattr(owner,'_flat_mode',DEFAULT_MODE)


def _swing_sessions(owner):
    sw=getattr(owner,'_swing',None);ui=sw.get('ui') if isinstance(sw,dict) else None
    rows=ui.get('sessions') if isinstance(ui,dict) else None
    return rows if isinstance(rows,list) else []


def pet_content():
    """Visible swing + girl box (left, top, right, bottom) in window units under the current PET_* constants."""
    l,t,r,b=ART_OLD;return (PET_CX+(l-82)*PET_M,PET_TOP+(t-15)*PET_M,PET_CX+(r-82)*PET_M,PET_TOP+(b-15)*PET_M)


def geometry(owner, geo):
    from pet import ChatBox
    u=ChatBox._layout(owner.sw,owner.sh)[0]
    sa=owner._scene_art;stand=owner._studio();bx,by,ex,ey=stand.bounds()
    scene_scale=geo.get('ss',1)
    k=min(PET_BOX[0]*u/(ex-bx),PET_BOX[1]*u/(ey-by))*scene_scale
    from hat_fx import HEADROOM
    # Headroom follows the hat layer's availability, not AI pet mode, so switching looks never resizes the window.
    pad=round(HEADROOM*u) if getattr(owner,'_hat_fx_layout_on',getattr(owner,'_hat_fx_enabled_now',lambda:False))() else 0
    gb=sa.girl_bbox;sprh=owner._spr_disp_h();ss=k*(gb[3]-gb[1])/sprh
    cx=PET_CX*u;top=PET_TOP*u+pad
    O=((bx+ex)*k/2-cx,by*k-top)
    geo.update(k=k,ss=ss,O=O,size=(round(W*u),round(H*u)+pad),flat=True,u=u,hat_fx_pad=pad,
               gtl=(gb[0]*k,gb[1]*k),anchor=((gb[0]+gb[2])/2*k,(gb[1]+(gb[3]-gb[1])*.45)*k))
    geo.pop('studio',None);geo.pop('house_layout',None);geo.pop('moon_house',None)
    return geo


ROW_CACHE=128   # session_row results kept (oldest dropped first)
_ROWS={}


def session_row(ui,s):
    """One session as a list row (its latest observed stage), or None when it has no steps yet. A stale session reports
    state 'idle' with stale=True: it never claims to be running, and the row says how old it is instead.
    The row depends only on the session's content and its stale verdict, so it is memoised on exactly those: a panel
    rebuild after a scan re-parses only the sessions that changed (the tasks list parsed ~20 every rebuild, ~11 ms)."""
    key=(_stale(ui,s),repr(s));row=_ROWS.get(key,_MISSING)
    if row is _MISSING:
        row=_session_row(ui,s)
        while len(_ROWS)>=ROW_CACHE:del _ROWS[next(iter(_ROWS))]
        _ROWS[key]=row
    return dict(row) if row else None


def _session_row(ui,s):
    f=stages(dict(ui,sel_session=s));steps=f['steps']
    if not steps:return None
    step=steps[-1]
    return dict(id=s.get('id'),agent=agent_name(s.get('agent')),state='idle' if f['stale'] else s.get('state','idle'),
                title=step.get('title') or '暂无步骤记录',summary=display_title(step),result=step.get('result',''),
                index=step.get('index'),updated=_number(s.get('updated')) or 0,since=turn_start(s),stale=f['stale'])


def rows_for(ui,mode):
    """The rows a view lists, in display order. 'steps': the selected session's stages, newest first (done steps stay
    green only while the session is fresh and recent). 'tasks' / 'live': sessions of the selected agent / of all agents,
    by displayed state, then newest first. Scrolling and the thumb count these same rows."""
    if mode=='steps':
        session=session_for(ui)
        if session is None:return []
        f=stages(dict(ui,sel_session=session));now=ui.get('now') or time.time()
        updated=_number(f['session'].get('updated')) or 0
        recent=not f['stale'] and bool(updated) and now-updated<DONE_RECENT
        return [dict(s,id=f['session'].get('id'),state=s['status'],summary=display_title(s),recent=recent) for s in reversed(detail_steps(f))]
    rows=[r for r in (session_row(ui,s) for s in (ui.get('sessions') or [] if mode=='live' else sessions_for(ui))) if r]
    priority={'running':0,'waiting':1,'error':2,'done':3,'idle':4}
    return sorted(rows,key=lambda r:(priority.get(r['state'],4),-r['updated']))


def agent_lights(ui):
    groups={name:'idle' for name in AGENT_ORDER}
    # This strip answers whether ANY agent is still running, independently
    # of errors or completion in another session from the same provider.
    priority={'running':0,'error':1,'waiting':2,'idle':3}
    for s in ui.get('sessions') or []:
        name=agent_name(s.get('agent'))
        state=s.get('state','idle')
        state=state if not _stale(ui,s) and state in ('running','waiting','error') else 'idle'
        if name not in groups or priority[state]<priority[groups[name]]:groups[name]=state
    return [(name,groups[name]) for name in (*AGENT_ORDER,'Mac','AI') if name in groups]


def widget_rows(raw,now):
    """Whitelist display-only values from AIQuota; never read credentials/config."""
    if not isinstance(raw,dict) or raw.get('schemaVersion')!=1:return []
    providers=raw.get('providers')
    if not isinstance(providers,list):return []
    result=[]
    for p in providers[:12]:
        if not isinstance(p,dict):continue
        name=p.get('name')
        if name not in ('Claude','Codex','Codex WSL'):continue
        stamp=_timestamp(p.get('updated'));ttl=_number(p.get('staleAfter'))
        stale=bool(p.get('stale') or p.get('error') or stamp is None or stamp>now or now-stamp>(ttl if ttl and ttl>0 else 300))
        windows=p.get('windows');cycles=[]
        for c in (windows if isinstance(windows,list) else [])[:2]:
            if not isinstance(c,dict):continue
            reset=_timestamp(c.get('resetUnix'))
            cycles.append({'label':str(c.get('short') or '?')[:4],'used':_used(c.get('used')),
                           'reset':reset,'stale':stale or (reset is not None and reset<=now)})
        result.append({'name':name,'cycles':cycles,'stale':stale,'t':stamp})
    return result


def live_ui(owner,ui):
    if ui.get('mock'):return ui
    now=time.time()
    if now-getattr(owner,'_flat_quota_read',0)>=5:
        owner._flat_quota_read=now
        try:
            path=Path(os.environ.get('LOCALAPPDATA',''))/'AIQuota'/'usage.json'
            if path.stat().st_size>65536:raise ValueError('oversize')
            raw=json.loads(path.read_text(encoding='utf-8-sig'))
            if not widget_rows(raw,now):raise ValueError('invalid')
            owner._flat_quota_raw=raw;owner._flat_quota_error=False
        except (OSError,ValueError,TypeError,RecursionError):
            owner._flat_quota_error=True
    rows=widget_rows(getattr(owner,'_flat_quota_raw',None),now)
    if getattr(owner,'_flat_quota_error',False):
        for row in rows:
            row['stale']=True
            for c in row['cycles']:c['stale']=True
    return dict(ui,quota_widget=rows)


def quota_rows(ui):
    if 'quota_widget' in ui:
        return ui['quota_widget'] or [{'name':n,'cycles':[],'stale':True} for n in ('Claude','Codex')]
    return [{'name':name,'stale':q['stale'],'cycles':[dict(c,label=label) for c,label in zip(q['cycles'],('5h','周'))]}
            for provider,name in (('claude','Claude'),('codex','Codex')) for q in [quota_view(ui,provider)]]


def scroll(owner,delta):
    if _mode(owner)=='live':return
    sw=owner._swing;rows=rows_for(owner_ui(owner,sw.get('ui') or {}),_mode(owner))
    limit=max(0,len(rows)*row_pitch(_mode(owner))-LIST[3])
    owner._flat_scroll=min(limit,max(0,getattr(owner,'_flat_scroll',0)-delta/120*row_pitch(_mode(owner))))
    owner._flat_cache=None


def scrollbar(n,pitch,offset):
    """(thumb top in window units, thumb height, scroll limit) for n rows of `pitch`, or None when they all fit."""
    total=n*pitch
    if total<=LIST[3]:return None
    thumb=max(20,LIST[3]**2/total);limit=total-LIST[3]
    return LIST[1]+max(0,min(limit,offset))/limit*(LIST[3]-thumb),thumb,limit


def bar_input(owner,e,phase):
    """Scrollbar column of the expanded list: press on the thumb drags it, press on the track above / below pages by
    one window of whole rows (no drag starts). Returns True when it consumed the event."""
    sw=getattr(owner,'_swing',None) or {};g=sw.get('geo') or {}
    if not g.get('flat'):return False
    if phase=='release':
        active=getattr(owner,'_flat_bar_drag',None) is not None
        owner._flat_bar_drag=None;return active
    mode=_mode(owner)
    if mode=='live':return False
    u=g['u'];ey=e.y-g.get('hat_fx_pad',0);n=len(rows_for(owner_ui(owner,sw.get('ui') or {}),mode))
    bar=scrollbar(n,row_pitch(mode),getattr(owner,'_flat_scroll',0))
    if bar is None:return False
    ty,thumb,limit=bar
    if phase=='press':
        if not ((SB_X-4)*u<=e.x<=(SB_X+7)*u and LIST[1]*u<=ey<=(LIST[1]+LIST[3])*u):return False
        owner.last_interact=time.time()
        if not ty<=ey/u<=ty+thumb:return action(owner,'flat_page',-1 if ey/u<ty else 1)
        owner._flat_bar_drag=ey/u-ty
    grab=getattr(owner,'_flat_bar_drag',None)
    if grab is None:return False
    owner._flat_scroll=max(0,min(limit,(ey/u-LIST[1]-grab)/(LIST[3]-thumb)*limit))
    owner.last_interact=time.time();owner._flat_cache=None;return True


def action(owner,kind,payload):
    if kind=='flat_mode':owner._flat_mode=payload;owner._flat_scroll=0
    elif kind=='flat_back':
        # 返回 from the steps view: back to the view the user opened it from, at the same scroll position.
        mode,offset=getattr(owner,'_flat_back',None) or ('tasks',0)
        owner._flat_mode=mode;owner._flat_scroll=offset
    elif kind=='flat_task':
        if _mode(owner)!='steps':owner._flat_back=(_mode(owner),getattr(owner,'_flat_scroll',0))
        owner._book_sel=('sid',payload);owner._flat_mode='steps';owner._flat_scroll=0
        s=next((x for x in _swing_sessions(owner) if isinstance(x,dict) and str(x.get('id'))==str(payload)),None)
        if s:owner._flat_agent=agent_name(s.get('agent'))
    elif kind=='flat_agent':
        name=str(payload or '')
        if name not in AGENT_ORDER:return False
        owner._flat_agent=name;owner._flat_mode='tasks';owner._flat_scroll=0
        ui=((getattr(owner,'_swing',None) or {}).get('ui') or {})
        session=session_for(ui,name,prefer_current=False)
        if session:owner._book_sel=('agent',session.get('agent'))
    elif kind=='flat_page':scroll(owner,-payload*120*(LIST[3]//row_pitch(_mode(owner))))
    elif kind=='flat_thumb':return True   # the thumb is dragged through bar_input; a plain click on it does nothing
    elif kind=='flat_top':owner._flat_scroll=0
    else:return False
    owner._flat_cache=None;return True


def _pal(ui):
    return ui.get('palette') or PALETTE


def _px(size,u):
    """Font pixels for a logical size, rounding halves up: 11 at u=1.5 is 17 px (11.3 logical), never 16 (10.7)."""
    return int(size*u+.5)


def _pen(u,pal=PALETTE):
    im=Image.new('RGBA',(round(W*u),round(H*u)));d=ImageDraw.Draw(im);hits=[]
    def box(rect,color,r=0,outline=None):
        x,y,a,b=rect;y+=PY;d.rounded_rectangle(tuple(round(v*u) for v in (x,y,x+a,y+b)),radius=round(r*u),fill=color,outline=outline,width=1)
    def txt(x,y,s,size=13,color=pal['INK'],width=None,weight=450,anchor='la'):
        f=font(_px(size,u),weight);d.text((round(x*u),round((y+PY)*u)),_fit(s,f,width*u) if width else str(s),font=f,fill=color,anchor=anchor)
    def hit(rect,kind,payload=None):
        # Round the edges, not the size, so boxes that touch in panel units still touch (never overlap) in pixels.
        x,y,a,b=rect;l,t,r,bt=(round(v*u) for v in (x,y+PY,x+a,y+PY+b))
        hits.append((l,t,r-l,bt-t,kind,payload))
    return im,d,hits,box,txt,hit


GLYPH_CACHE=(64,1<<18)   # finished glyph tiles kept (LRU): at most this many, and this many pixels in total
_GLYPHS={}


def glyph(im,cx,cy,r,color,shape,u,glow=False):
    """Status glyph centred at (cx,cy) in panel units, drawn 8x supersampled. Shape carries the state as well as colour:
    star = running, ring = waiting, tri = error, dot = done/idle (so error vs done survives red-green colour blindness).
    The tile depends only on (r, colour, shape, u, glow), so a panel rebuild reuses it instead of paying ~0.5 ms of
    supersampling per glyph again; the pixels are the same."""
    key=(r,color,shape,u,bool(glow));t=_GLYPHS.pop(key,None)
    if t is None:
        t=_glyph_tile(*key)
        while _GLYPHS and (len(_GLYPHS)>=GLYPH_CACHE[0] or sum(v.width*v.height for v in _GLYPHS.values())+t.width*t.height>GLYPH_CACHE[1]):
            del _GLYPHS[next(iter(_GLYPHS))]
    _GLYPHS[key]=t
    im.alpha_composite(t,(round(cx*u-t.width/2),round(cy*u-t.height/2)))


def _glyph_tile(r,color,shape,u,glow):
    k=8;g=int((r+5)*2*u*k)+2;t=Image.new('RGBA',(g,g));td=ImageDraw.Draw(t);c=g/2;s=r*u*k;col=ImageColor.getrgb(color)
    if glow:e=(r+2.6)*u*k;td.ellipse((c-e,c-e,c+e,c+e),fill=col+(90,))
    if shape=='star':
        R=1.34*s;td.polygon([(c+(R if i%2==0 else R*.46)*math.cos(math.radians(-90+45*i)),c+(R if i%2==0 else R*.46)*math.sin(math.radians(-90+45*i))) for i in range(8)],fill=col)
    elif shape=='ring':
        td.ellipse((c-1.12*s,c-1.12*s,c+1.12*s,c+1.12*s),fill=col);td.ellipse((c-.52*s,c-.52*s,c+.52*s,c+.52*s),fill=(0,0,0,0))
    elif shape=='tri':
        td.polygon([(c,c-1.22*s),(c+1.12*s,c+.82*s),(c-1.12*s,c+.82*s)],fill=col)
    else:td.ellipse((c-s,c-s,c+s,c+s),fill=col)
    return t.resize((max(1,round(g/k)),max(1,round(g/k))),Image.LANCZOS)


def panel_fill(ui):
    """BG as #rrggbbaa. ImageDraw writes this alpha into an RGBA image as-is (no blending)."""
    return _pal(ui)['BG']+'%02x'%max(0,min(255,int(ui.get('panel_alpha',PANEL_REST))))


def panel_alpha(owner,ui,mode):
    """Calm at rest; more opaque when expanded, hovered (owner._flat_hover, set by the host) or something needs attention."""
    attention=any(isinstance(s,dict) and s.get('state') in ('waiting','error') for s in ui.get('sessions') or [])
    return PANEL_ACTIVE if mode!='live' or attention or getattr(owner,'_flat_hover',False) else PANEL_REST


# ---------------------------------------------------------------------------
# I-51 精修行列 (refined rows): one two-line group per agent on one grid, a compact quota table, neutral chips and
# chevrons on everything clickable. Grid in panel units: glyph column centred on GX, text column at TX, section edge
# QX (row tints and hit boxes bleed 5 units, QX-5 .. XR+5), right edge XR; the status and line 2 stop at XS so the
# chevron keeps its own lane.
# ---------------------------------------------------------------------------
GX=186;TX=196;QX=181;XR=423;XS=410          # glyph centre, text left, section left, right edge, status right edge
LB0=22;LP=38;L2=15                          # live: first line-1 baseline, group pitch, line-1 -> line-2 baseline
QH=130.5;QB0=154;QP=18;CHAT_H=15           # live: quota header centre, first quota baseline, quota row pitch, 聊聊 chip height
QPCT=306;QBAR=(314,356);QBAR_H=6            # quota columns: % right edge, bar left/right, bar height
HDR=20;STRIP=156;SEG_H=20;SQH=188;SQB0=211  # expanded view: header centre, agent switcher top/height, quota header centre / first baseline
TINT=.12                                    # a waiting / error group sits on the panel BG mixed this far toward its state colour
DONE_RECENT=1800                            # a finished session stays green for this long, then DIM
PERIOD={'5h':5*3600,'周':7*86400}           # window lengths for the pace check (月 has no fixed length)
WEEK='一二三四五六日'


def _rgb(c):return ImageColor.getrgb(c)[:3]


def mix(a,b,t):
    """Hex colour t of the way from a to b (both hex)."""
    a,b=_rgb(a),_rgb(b);return '#%02x%02x%02x'%tuple(round(x+(y-x)*t) for x,y in zip(a,b))


def _lum(c):
    def ch(v):v/=255;return v/12.92 if v<=.03928 else ((v+.055)/1.055)**2.4
    r,g,b=_rgb(c);return .2126*ch(r)+.7152*ch(g)+.0722*ch(b)


def contrast(a,b):
    x,y=sorted((_lum(a),_lum(b)),reverse=True);return (x+.05)/(y+.05)


def track_colour(P,ratio=3.0):
    """Bar track: the least DIM-ward mix of BG that still reaches `ratio`:1 against BG."""
    return _track(P['BG'],P['DIM'],ratio)


@functools.lru_cache(maxsize=32)
def _track(bg,dim,ratio):
    for i in range(101):
        c=mix(bg,dim,i/100)
        if contrast(c,bg)>=ratio:return c
    return dim


def _alpha(ui):return '%02x'%max(0,min(255,int(ui.get('panel_alpha',PANEL_REST))))


def tint(ui,colour,t):
    """Panel BG tinted t toward colour, at the panel's own per-pixel alpha (fills replace pixels, they don't blend)."""
    return mix(_pal(ui)['BG'],colour,t)+_alpha(ui)


def dur(sec):
    sec=max(0,int(sec))
    if sec<60:return f'{sec}秒'
    if sec<3600:return f'{sec//60}分钟'
    if sec<86400:return f'{sec//3600}小时'
    return f'{sec//86400}天'


def ago(sec):return '刚刚' if sec<60 else dur(sec)+'前'


def turn_start(session):
    """Earliest action time of the current turn (actions are newest first); None when unknown."""
    first=None
    for a in (session or {}).get('actions') or []:
        if not isinstance(a,dict):continue
        if a.get('turn'):break
        t=_number(a.get('t'))
        if t:first=t
    return first


def status_of(row,now,dim=DIM):
    """(text, colour) for a row's trailing status: how long it has been waiting / failing / running, or how old it is.
    Never '已结束' and never an invented next step; a stale row says when it was last updated."""
    st=row['state'];upd=row.get('updated') or 0
    if row.get('stale'):return ('更新于'+ago(now-upd) if upd else '久未更新'),dim
    if st in LIVE:
        label={'running':'运行中','waiting':'等你确认','error':'出错'}[st]
        start=(row.get('since') or upd) if st=='running' else upd
        return (label+' '+dur(now-start) if start else label),(dim if st=='running' else COLORS[st])
    if upd:return ago(now-upd),dim
    return '–',dim


def glyph_of(row,now,dim=DIM):
    """(colour, shape, radius) for a row's state glyph: green only for a recent finish."""
    st=row['state']
    if row.get('stale'):return dim,'dot',2.6
    if st=='done':
        recent=row.get('updated') and now-row['updated']<DONE_RECENT
        return (COLORS['done'] if recent else dim),'dot',3.0
    if st in LIVE:return COLORS[st],SHAPES[st],3.5
    return dim,'dot',2.6


def reset_note(reset,now):
    """When a quota window resets, in local time: '18:40重置' within 20 h (or later today), '周二重置' within the coming
    week (never today's weekday), else '1/27重置'. None when unknown or already past."""
    if not reset or reset<=now:return None
    t=time.localtime(reset);n=time.localtime(now)
    days=date(t.tm_year,t.tm_mon,t.tm_mday).toordinal()-date(n.tm_year,n.tm_mon,n.tm_mday).toordinal()
    if reset-now<20*3600 or days==0:return f'{t.tm_hour}:{t.tm_min:02d}重置'
    if days<7:return f'周{WEEK[t.tm_wday]}重置'
    return f'{t.tm_mon}/{t.tm_mday}重置'


def quota_pick(row):
    """The window that limits you: the first (5h) normally; a longer one when it is >=80% and worse."""
    cycles=row.get('cycles') or []
    if not cycles:return None
    pick=cycles[0]
    for c in cycles[1:]:
        v=c.get('used')
        if v is not None and v>=80 and (pick.get('used') is None or v>pick['used']):pick=c
    return pick


def _fast(c,now):
    """Used faster than the window elapses: at this pace it runs out before the reset (needs a known reset)."""
    v=c.get('used');period=PERIOD.get(c.get('label'));reset=c.get('reset')
    if v is None or not period or not reset or reset<=now:return False
    elapsed=period-(reset-now)
    return elapsed>.15*period and v>=40 and v*period/elapsed>=100


def quota_colour(c,now,P):
    """(% colour, bar colour): neutral when calm, orange at >=70 % or burning fast, red at >=90 %.
    Stale or unknown: DIM text and no bar (the row says why in words)."""
    v=c.get('used') if c else None
    if c is None or v is None or c.get('stale'):return P['DIM'],None
    if v>=90:return COLORS['error'],COLORS['error']
    if v>=70 or _fast(c,now):return COLORS['waiting'],COLORS['waiting']
    return P['INK'],mix(P['DIM'],P['INK'],.35)


def quota_note(row,c,now):
    """The quota row's right-hand note (DIM): the reset time when fresh, its age when stale, '暂无数据' when unknown."""
    v=c.get('used') if c else None
    stale=row.get('stale') or (c is not None and c.get('stale'))
    if v is None and not (stale and row.get('t')):return '暂无数据'
    if stale:return ('更新于'+ago(now-row['t'])) if row.get('t') else '久未更新'
    return reset_note(c.get('reset'),now) or ''


def chevron(d,x,cy,u,colour,h=7.0):
    """Drill-down chevron with its tip at (x, cy) in the drawing's own units (pass panel y + PY on the window image)."""
    w=h*.5;pts=[(x-w,cy-h/2),(x,cy),(x-w,cy+h/2)]
    d.line([(round(px*u),round(py*u)) for px,py in pts],fill=colour,width=max(1,round(1.5*u)),joint='curve')


def chip(box,txt,hit,ui,u,right,cy,label,kind,payload=None,size=12,h=17,pad=8):
    """Neutral pill button whose right edge is `right` and centre is cy; returns its left edge.
    Its click box is 3 units larger on every side."""
    P=_pal(ui);f=font(_px(size,u),500)
    w=f.getlength(label)/u+2*pad;x=right-w
    box((x,cy-h/2,w,h),tint(ui,P['INK'],.13),h/2)
    txt(x+w/2,cy+size*.38,label,size,P['INK'],weight=500,anchor='ms')
    hit((x-3,cy-h/2-3,w+6,h+6),kind,payload)
    return x


def quota_table(box,txt,ui,u,y_head,y0,pitch,limit,hit=None):
    """Header '已用额度' (+ ' · 模拟' for mock data; with `hit`, the 聊聊 chip at its right), then one row per provider:
    name + window | % (13/600, right-aligned) | 6 px bar on a >=3:1 track | reset note / freshness (DIM).
    Returns the chip's left edge, or None without a chip."""
    P=_pal(ui);now=ui.get('now') or time.time();track=track_colour(P);dim=P['DIM']
    txt(QX,y_head+4,'已用额度'+(' · 模拟' if ui.get('mock') else ''),11,dim,anchor='ls')
    chat=chip(box,txt,hit,ui,u,XR,y_head,'聊聊','house_chat',size=11,h=CHAT_H,pad=7) if hit else None
    f12=font(_px(12,u),450)
    for i,row in enumerate(quota_rows(ui)[:limit]):
        y=y0+i*pitch;c=quota_pick(row);name=row['name']
        txt(QX,y,name,12,P['INK'],anchor='ls')
        if c is not None:txt(QX+f12.getlength(name)/u+4,y,c.get('label',''),11,dim,anchor='ls')
        text_col,bar_col=quota_colour(c,now,P);v=c.get('used') if c else None
        txt(QPCT,y,'–' if v is None else f'{v:.0f}%',13,text_col,weight=600,anchor='rs')
        if bar_col:   # a gauge only for a fresh, known value; stale/unknown rows say so in words instead
            bx0,bx1=QBAR;by=y-4.5-QBAR_H/2
            box((bx0,by,bx1-bx0,QBAR_H),track,QBAR_H/2)
            if v>0:box((bx0,by,max(QBAR_H,(bx1-bx0)*min(100,v)/100),QBAR_H),bar_col,QBAR_H/2)
        note=quota_note(row,c,now)
        if note:txt(XR,y,note,12,dim,anchor='rs')
    return chat



def agent_rows(ui):
    """One row per agent in a stable order: its freshest live session, else its latest record (nothing is invented). At most LIVE_ROWS rows."""
    rows=[];sessions=[s for s in ui.get('sessions') or [] if isinstance(s,dict)]
    for name in (*AGENT_ORDER,'Mac','AI'):
        for s in sorted((x for x in sessions if agent_name(x.get('agent'))==name),key=lambda x:_rank_key(ui,x)):
            row=session_row(ui,s)
            if row:rows.append(row);break          # a session without steps yet: try the agent's next one
    return rows[:LIVE_ROWS]


def step_flow(row):
    """Line 2 of a group: the observed 'stage · direction' only. A next step is never shown or invented."""
    return str(row.get('summary') or row['title'])


def render_live(ui,u=1):
    """Compact view: one two-line group per agent (glyph, name, trailing status / stage · direction), then the quota table.
    The panel is drawn at y=PY..PY+LIVE_H of the same window; the headroom above (her hat) and the rest below stay transparent."""
    P=_pal(ui);INK,DIM_=P['INK'],P['DIM']
    im,d,hits,box,txt,hit=_pen(u,P)
    now=ui.get('now') or time.time();rows=agent_rows(ui)
    box((0,0,W-1,LIVE_H-1),panel_fill(ui),16,P['RIM'])
    f13=font(_px(13,u),600);chev=mix(P['BG'],DIM_,.62)
    first=LB0-11.3-(LP-L2-12.6)/2   # top of group 0's click box: the boxes tile at pitch LP with each group's ink centred
    for i,row in enumerate(rows):
        b1=LB0+i*LP;b2=b1+L2;top,bot=b1-11.3,b2+1.3   # the group's ink: cap top of line 1 .. descent of line 2
        if not row.get('stale') and row['state'] in ('waiting','error'):
            box((QX-5,top-3.5,XR-QX+10,bot-top+7),tint(ui,COLORS[row['state']],TINT),7)
        col,shape,r=glyph_of(row,now,DIM_)
        glyph(im,GX,b1-4.5+PY,r,col,shape,u)
        txt(TX,b1,row['agent'],13,INK,weight=600,anchor='ls')
        status,scol=status_of(row,now,DIM_)
        txt(XS,b1,status,12,scol,width=XS-TX-f13.getlength(row['agent'])/u-10,anchor='rs')
        live=row['state'] in LIVE and not row.get('stale')
        txt(TX,b2,step_flow(row),12,INK if live else DIM_,width=XS-TX,anchor='ls')
        chevron(d,XR,(top+bot)/2+PY,u,chev)
        hit((QX-5,first+i*LP,XR-QX+10,LP),'flat_task',row['id'])   # one destination per group; groups tile with no dead strip
    if not rows:
        txt(TX,LB0,'暂无 AI 会话',13,DIM_,weight=600,anchor='ls')
        txt(TX,LB0+L2,'开始工作后会显示在这里',12,DIM_,width=XS-TX,anchor='ls')
    chat=quota_table(box,txt,ui,u,QH,QB0,QP,2,hit=hit)
    # Empty group slots and the quota block take no clicks (a click there must not count as touching her):
    # the slots under the last group, the header strip left of the chip, then the quota rows.
    head,foot=QH-CHAT_H/2-3,QH+CHAT_H/2+3;rest=first+len(rows)*LP
    hit((QX-5,rest,XR-QX+10,head-rest),'swallow')
    hit((QX-5,head,chat-3-(QX-5),foot-head),'swallow')
    hit((QX-5,foot,XR-QX+10,LIVE_H-4-foot),'swallow')
    return im,[q for q in hits if q[2]>0 and q[3]>0],0


def render(ui,u=1,mode='tasks',offset=0):
    """Expanded view (PH tall): header chips, the scrollable list well, the agent switcher and the quota table.
    'tasks' lists the selected agent's sessions as two-line groups; 'steps' lists the selected session's stages."""
    if mode=='live':return render_live(ui,u)
    P=_pal(ui);INK,DIM_,LINE=P['INK'],P['DIM'],P['LINE']
    im,_,hits,box,txt,hit=_pen(u,P);now=ui.get('now') or time.time()
    box((0,0,W-1,PH-1),panel_fill(ui),16,P['RIM'])
    agent=selected_agent(ui);chev=mix(P['BG'],DIM_,.62)
    # header: title on the section edge, chips at the right edge (返回 goes back to where the steps were opened from)
    x=chip(box,txt,hit,ui,u,XR,HDR,'收起','flat_mode','live')
    if mode=='steps':x2=chip(box,txt,hit,ui,u,x-6,HDR,'返回','flat_back')
    else:x2=chip(box,txt,hit,ui,u,x-6,HDR,'聊聊','house_chat')
    txt(QX,HDR+5,f'{agent} · 阶段概览' if mode=='steps' else f'{agent} · 当前阶段',13,INK,weight=600,width=x2-QX-8,anchor='ls')
    hit((QX-5,HDR-17/2-3,x2-3-(QX-5),17+6),'swallow')   # the title strip, level with the chips' click boxes
    # list well: rows take clicks up to the scrollbar column; a row needs MIN_HIT visible units to take any
    rows=rows_for(ui,mode);n=len(rows)
    LX,LY,LW,LHt=LIST[0],LIST[1]-PY,LIST[2],LIST[3];RH=row_pitch(mode);RW=SB_X-4-LX
    offset=max(0,min(float(offset),max(0,n*RH-LHt)))
    crop=Image.new('RGBA',(round(LW*u),round(LHt*u)));f12=font(_px(12,u),450);f13=font(_px(13,u),600)
    spans=[]
    for i,row in enumerate(rows):
        yy=i*RH-offset
        if yy+RH<=0 or yy>=LHt:continue
        tile=Image.new('RGBA',(round(LW*u),round(RH*u)));td=ImageDraw.Draw(tile)
        if mode=='steps':
            # one line: glyph, stage · direction, then the live state in words; done steps are green only while recent
            st=row['state'];base=RH/2+4.5    # text baseline; the glyph centre sits 4.5 above it, as in the live view
            col=(COLORS['done'] if row.get('recent') else DIM_) if st=='done' else COLORS[st] if st in LIVE else DIM_
            glyph(tile,GX-LX,RH/2,3.5 if st in LIVE else 2.8,col,SHAPES.get(st,'dot'),u)
            label={'running':('运行中',DIM_),'waiting':('等你确认',COLORS['waiting']),'error':('出错',COLORS['error'])}.get(st);sw=0
            if label:td.text(((XS-LX)*u,base*u),label[0],font=f12,fill=label[1],anchor='rs');sw=f12.getlength(label[0])/u+10
            td.text(((TX-LX)*u,base*u),_fit(step_flow(row),f12,(XS-TX-sw)*u),font=f12,fill=INK,anchor='ls')
            chevron(td,XR-LX,RH/2,u,chev,6.0)
            kind,payload='detail',(row['id'],row['index'],step_flow(row),row.get('result',''))
        else:
            # two-line group in the live rhythm: stage · direction (13/600), then the status line (12)
            col,shape,r=glyph_of(row,now,DIM_);status=status_of(row,now,DIM_);b1=RH/2-2.5
            live=row['state'] in LIVE and not row.get('stale')
            glyph(tile,GX-LX,b1-4.5,r,col,shape,u)
            td.text(((TX-LX)*u,b1*u),_fit(step_flow(row),f13,(XS-TX)*u),font=f13,fill=INK if live else DIM_,anchor='ls')
            td.text(((TX-LX)*u,(b1+L2)*u),_fit(status[0],f12,(XS-TX)*u),font=f12,fill=status[1],anchor='ls')
            chevron(td,XR-LX,RH/2,u,chev)
            kind,payload='flat_task',row['id']
        if i<n-1:td.line((round((TX-LX)*u),round(RH*u)-1,round((XR-LX)*u),round(RH*u)-1),fill=mix(P['BG'],LINE,.9),width=1)
        src=max(0,round(-yy*u));dst=max(0,round(yy*u));height=min(tile.height-src,crop.height-dst)
        if height>0:crop.alpha_composite(tile.crop((0,src,tile.width,src+height)),(0,dst))
        top,bottom=max(0,yy),min(LHt,yy+RH)
        if bottom-top>=MIN_HIT:hit((LX,LY+top,RW,bottom-top),kind,payload);spans.append((top,bottom))
    im.alpha_composite(crop,(round(LX*u),round(LIST[1]*u)))
    if not rows:txt(TX,LY+RH/2+4.5,'暂无步骤记录' if mode=='steps' else '暂无会话记录',12,DIM_,anchor='ls')
    # what the rows leave of the well (empty list, slivers) still takes no clicks
    first,last=(spans[0][0],spans[-1][1]) if spans else (LHt,LHt)
    hit((LX,LY,RW,first),'swallow');hit((LX,LY+last,RW,LHt-last),'swallow')
    bar=scrollbar(n,RH,offset)
    if bar:
        ty,thumb,_=bar;ty-=PY
        box((SB_X,LY,3,LHt),track_colour(P,1.6),1.5);box((SB_X,ty,3,thumb),mix(P['BG'],DIM_,.75),1.5)
        hit((SB_X-4,LY,11,ty-LY),'flat_page',-1)              # bar_input handles presses here first: thumb drags, track pages
        hit((SB_X-4,ty,11,thumb),'flat_thumb')
        hit((SB_X-4,ty+thumb,11,LY+LHt-ty-thumb),'flat_page',1)
    # agent switcher: one segmented control; the open agent gets a neutral fill (never ACCENT), running stays lavender
    lamps=[(nm,st) for nm,st in agent_lights(ui) if nm in AGENT_ORDER]
    seg=(XR-QX+6)/len(lamps);cell=(XR-QX+10)/len(lamps)
    box((QX-5,STRIP-2,XR-QX+10,SEG_H+4),tint(ui,INK,.055),SEG_H/2+2)
    for i,(name,st) in enumerate(lamps):
        x=QX-3+i*seg;cy=STRIP+SEG_H/2
        if name==agent:box((x,STRIP,seg-2,SEG_H),tint(ui,INK,.16),SEG_H/2)
        col=COLORS[st] if st in LIVE else mix(P['BG'],DIM_,.7)
        f=font(_px(12,u),500 if name==agent else 450);gx=x+(seg-2)/2-(f.getlength(name)/u+12)/2
        glyph(im,gx+3.5,cy+PY,3.2 if st in LIVE else 2.6,col,SHAPES.get(st,'dot'),u)
        txt(gx+12,cy+4.3,name,12,INK if name==agent or st!='idle' else DIM_,weight=500 if name==agent else 450,anchor='ls')
        hit((QX-5+i*cell,STRIP-2,cell,SEG_H+4),'flat_agent',name)   # the cells tile the whole strip
    quota_table(box,txt,ui,u,SQH,SQB0,QP,3)
    hit((QX-5,STRIP+SEG_H+2,XR-QX+10,PH-8-(STRIP+SEG_H+2)),'swallow')
    return im,[q for q in hits if q[2]>0 and q[3]>0],offset


def push(owner,small):
    from pet import push_layered
    sw=owner._swing;g=sw['geo'];u=g['u'];ui=live_ui(owner,sw.get('ui') or {});mode=_mode(owner)
    ui=dict(ui,flat_agent=getattr(owner,'_flat_agent',None) or selected_agent(ui))
    ui=dict(ui,panel_alpha=panel_alpha(owner,ui,mode))
    # Resolve the picture before the palette: missing material can synchronously
    # fall back to Xiaoqiao, including her theme, on this very frame.
    look=getattr(owner,'_static_look',None)
    ax,ay,art_size=static_layout(u,g.get('hat_fx_pad',0))
    static=look(art_size) if look else None
    theme=getattr(owner,'_ui_theme',None)
    if theme is not None:ui=dict(ui,palette=theme.panel)
    pad=g.get('hat_fx_pad',0)
    key=(panel_data_key(owner,ui),int((ui.get('now') or time.time())/15),u,mode,getattr(owner,'_flat_scroll',0),pad,theme.key if theme else None)
    cache=getattr(owner,'_flat_cache',None)
    # AI mode: when the session scan (~6 ms) ran in this very tick, a data-only panel change waits one frame, so the
    # scan and the 5-10 ms panel rebuild never share a frame. Base and hits stay the old, consistent pair until then.
    gen=getattr(owner,'_ai_scan_gen',0);scanned=gen!=getattr(owner,'_flat_scan_gen',gen);owner._flat_scan_gen=gen
    if cache is None or cache[0]!=key and not (static is not None and scanned and cache[0][2:]==key[2:]):
        base,hits,off=render(ui,u,mode,getattr(owner,'_flat_scroll',0));owner._flat_scroll=off
        if pad:
            padded=Image.new('RGBA',g['size']);padded.alpha_composite(base,(0,pad));base=padded
            hits=[(x,y+pad,w,h,kind,payload) for x,y,w,h,kind,payload in hits]
        owner._flat_cache=(key,base,hits)
    else:_,base,hits=cache
    # AI pet mode: a static character pose replaces her swing art, hat dust
    # and head-anchored marks; the panel, bubbles and click mapping stay.
    if static is not None:
        canvas,dirty=static_frame(owner,sw,base,static,ax,ay,u,pad,theme)
        sw['scene_canvas']=canvas;sw['ui_hits']=hits
        ok=push_layered(owner.hwnd,canvas,sw['scene_l'],sw['scene_t'],255,dirty=dirty)
        if ok==0:
            import ctypes
            # Tk re-created the toplevel (ERROR_INVALID_WINDOW_HANDLE): re-acquire and push the whole frame, as Pet._push does.
            if ctypes.get_last_error()==1400 and getattr(owner,'_acquire_hwnd',lambda:0)():
                push_layered(owner.hwnd,canvas,sw['scene_l'],sw['scene_t'],255)
        return
    owner._flat_live=None
    canvas=base.copy()
    paint_xiaoqiao(owner,canvas,sw,g)
    # Preserve the host's bubbles and effects; geometry also drives click mapping.
    if isinstance(small,Image.Image):
        ox,oy,ss=owner._art_small_map(sw)
        if small.mode!='RGBA':small=small.convert('RGBA')
        if abs(ss-1)>1e-3:
            small=small.resize((max(1,round(small.width*ss)),max(1,round(small.height*ss))),Image.Resampling.BILINEAR)
        owner._ac(canvas,small,ox,oy)
    from agent_companion import paint_effect
    paint_effect(owner,canvas,u,time.time())
    sw['scene_canvas']=canvas;sw['ui_hits']=hits
    push_layered(owner.hwnd,canvas,sw['scene_l'],sw['scene_t'],255)


def _bounds(rects,w,h):
    """Union bbox of (l,t,r,b) rects in whole pixels, clamped to a w x h canvas."""
    l=max(0,math.floor(min(q[0] for q in rects)));t=max(0,math.floor(min(q[1] for q in rects)))
    r=min(w,math.ceil(max(q[2] for q in rects)));b=min(h,math.ceil(max(q[3] for q in rects)))
    return (l,t,max(l,r),max(t,b))


def static_frame(owner,sw,base,static,ax,ay,u,pad,theme):
    """One AI frame on a persistent canvas; returns (canvas, dirty), dirty=None meaning push the whole window.

    Invariant: outside the region drawn last frame the canvas equals the panel base, so only that region is
    restored before drawing; the result is byte-identical to compositing onto a fresh base.copy(). The drawn
    region is the whole AI column at full height (ai_fx.draw and ai_bubble.placement both clip to LEFT_WIDTH;
    ai_fx's band reaches 34u above the head and 12u below the feet, speech sits above the head) plus the
    sprite's own rectangle in case it overhangs, plus the preview label. Rebuilt from base.copy() when the
    base, swing dict, geometry or canvas object changed (a new panel, layout, or another path took the canvas)."""
    from ai_bubble import LEFT_WIDTH as speech_w
    from ai_fx import LEFT_WIDTH as fx_w
    live=getattr(owner,'_flat_live',None);canvas=sw.get('scene_canvas');g=sw.get('geo')
    if (live is None or canvas is None or live[0] is not sw or live[1] is not g or live[2] is not base
            or live[3] is not canvas or canvas.size!=base.size):
        canvas=base.copy();prev=None
    else:
        prev=live[4]
        if prev[2]>prev[0] and prev[3]>prev[1]:canvas.paste(base.crop(prev),prev[:2])
    cw,ch=canvas.size
    rects=[(0,0,math.ceil(max(STATIC_BOX[2],speech_w,fx_w)*u)+2,ch)]
    frame,dy=static
    owner._last_body_frame=None
    x=ax+frame.offset[0]
    y=ay+frame.offset[1]+dy
    owner._ac(canvas,frame.image,x,y)
    ix,iy=int(round(x)),int(round(y))   # where _ac put it
    rects.append((ix,iy,ix+frame.image.width,iy+frame.image.height))
    alpha_box=getattr(frame,'alpha_box',_MISSING)
    if alpha_box is _MISSING:alpha_box=frame.image.getchannel('A').getbbox()
    head_box=(x+alpha_box[0],y+alpha_box[1],x+alpha_box[2],y+alpha_box[3]) if alpha_box else None
    paint=getattr(owner,'_static_effects',None)
    if paint and head_box:paint(canvas,head_box,u)
    speech=getattr(owner,'_static_speech',None)
    if speech and head_box:speech(canvas,head_box,u)
    if time.time()<getattr(owner,'_ai_pose_demo_until',0):
        pen=ImageDraw.Draw(canvas);at=(round(6*u),round((LIVE_H+PY-15)*u)+pad);f=font(_px(11,u),420)   # no CJK below 11 logical px
        pen.text(at,'动作预览',font=f,fill=(getattr(theme,'panel',{}).get('DIM',DIM)))
        rects.append(pen.textbbox(at,'动作预览',font=f))
    drawn=_bounds(rects,cw,ch)
    owner._flat_live=(sw,g,base,canvas,drawn)
    return canvas,None if prev is None else _bounds((prev,drawn),cw,ch)


PANEL_DATA=('sessions','sel_session','quota','codex_quota','codex_quota_error','mock','quota_widget','flat_agent','panel_alpha')
PANEL_RECHECK=1.0   # seconds between full comparisons when every input object is unchanged


def panel_data_key(owner,ui):
    """The panel cache key's data part, without repr()-ing every session each frame.

    The scan replaces the session list and quota samples wholesale every 2 s, so
    unchanged object identities mean unchanged data. A new list that holds the very
    same session dicts reprs the same, so it inherits the data string. The objects
    stay referenced (no id reuse), and a full repr still runs at least every
    PANEL_RECHECK seconds in case something ever edits them in place.
    """
    values=tuple(ui.get(n) for n in PANEL_DATA)
    sessions=values[0]
    fast=(tuple(id(v) for v in values[:4]),len(sessions) if isinstance(sessions,list) else -1,
          values[4],values[5],repr(values[6]),values[7],values[8])
    now=time.monotonic();memo=getattr(owner,'_flat_key_memo',None)
    if memo is not None and 0<=now-memo[2]<PANEL_RECHECK:
        if memo[0]==fast:return memo[1]
        old=memo[3][0]   # same length, every element the same object: adopt the list, keep the recheck clock
        if (fast[0][1:],fast[1:])==(memo[0][0][1:],memo[0][1:]) and type(sessions) is list and type(old) is list and all(a is b for a,b in zip(sessions,old)):
            owner._flat_key_memo=(fast,memo[1],memo[2],values[:4])
            return memo[1]
    data=repr(values)
    owner._flat_key_memo=(fast,data,now,values[:4])
    return data


def static_layout(u,pad=0):
    from ai_bubble import HEADROOM
    top=max(round(HEADROOM*u),round((STATIC_BOX[1]+PY)*u)+pad)
    bottom=round((STATIC_BOX[3]+PY)*u)+pad
    return round(STATIC_BOX[0]*u),top,(round((STATIC_BOX[2]-STATIC_BOX[0])*u),max(1,bottom-top))


def static_box_size(u):
    """Pixel size of STATIC_BOX at window scale u."""
    return (round((STATIC_BOX[2]-STATIC_BOX[0])*u),round((STATIC_BOX[3]-STATIC_BOX[1])*u))


def paint_xiaoqiao(owner,canvas,sw,g):
    """Her swing art onto the workspace canvas: hat dust behind, then the keystoned swing layer."""
    from pet import SWING_PERSP
    sa=owner._scene_art;k=g['k'];O=g['O'];layers=sa.scaled(k)
    back=getattr(owner,'_art_small_back',None)
    if back is not None and getattr(owner,'_hat_fx_enabled_now',lambda:False)():
        bx,by,bs=owner._art_small_map(sw)
        # Only the sparse hat region is needed; don't resample a mostly empty
        # full portrait frame merely to display a few pre-baked dust sprites.
        at=getattr(owner,'_art_small_back_at',None)
        if at is not None:
            # render() already cut this region out of the supersampled layer before reducing it
            bx+=at[0]*bs;by+=at[1]*bs
        else:
            box=getattr(owner,'_hat_fx_back_box',None)
            if box is not None:
                back=back.crop(box);bx+=box[0]*bs;by+=box[1]*bs
        if abs(bs-1)>1e-3:back=back.resize((max(1,round(back.width*bs)),max(1,round(back.height*bs))),Image.Resampling.BILINEAR)
        owner._ac(canvas,back.convert('RGBA'),bx,by)
    if SHOW_STAND:stand,at=owner._studio().render(k);owner._ac(canvas,stand,at[0]-O[0],at[1]-O[1])
    phase=round(sw.get('theta',0)/.008)*.008;pose=owner._art_pose(phase);face=owner._last_face_key
    ck=('flat',round(k,4),phase,face,pose['q'] if pose else None)
    cached=owner._ks_cache.get(ck)
    if cached is None:
        img,at=layers.get('swing_studio',layers['swing'])
        source_hook=getattr(owner,'_art_body_sprite_source',None)
        img,render_pose=source_hook(img,pose) if source_hook else (img,pose)
        ov=owner._art_face_overlay(face,k)
        if ov:
            img=img.copy();owner._ac(img,ov[0],ov[1][0]-at[0],ov[1][1]-at[1])
        cached=sa.pose_keystone(img,at,k,phase,SWING_PERSP,render_pose) if render_pose else sa.keystone(img,at,k,phase,SWING_PERSP)
        body=pose.get('body_sprite') if pose else None
        applied=body['ref'] if body and render_pose.get('body_sprite_applied') else None
        cached=(cached[0],cached[1],applied)
        owner._ks_cache.put(ck,cached)
    # Cache hits report what was actually painted, including a failed replacement.
    owner._last_body_frame=cached[2] if len(cached)>2 else None
    owner._ac(canvas,cached[0],cached[1][0]-O[0],cached[1][1]-O[1])


def owner_ui(owner,ui):
    """Use the same agent filter for painting, wheel scrolling and thumb dragging."""
    return dict(ui,flat_agent=getattr(owner,'_flat_agent',None) or selected_agent(ui))


def runtime_state(owner):
    sw=getattr(owner,'_swing',None) or {}
    ui=owner_ui(owner,sw.get('ui') or {})
    root=getattr(owner,'root',None)
    return dict(cloud_commit=SOURCE_REVISION,view=_mode(owner),
                selected_agent=selected_agent(ui),logical_size=[W,H],
                window_size=[sw.get('scene_w'),sw.get('scene_h')],
                window_position=[sw.get('scene_l'),sw.get('scene_t')],
                visible=bool(root is not None and root.state()!='withdrawn'),
                agent_lights=dict(agent_lights(ui)),
                companion_level=getattr(getattr(owner,'_agent_companion',None),'level',None),
                appearance=getattr(owner,'_appearance_state',lambda:None)())
