"""Local appearance resources and selection; no sessions, model or Win32 calls.

Xiaoqiao mode is always the existing 2.5D renderer. AI mode alone follows a
stable foreground provider. Static poses are pictures, not animation clips.
Cached CharacterFrame images are read-only to callers.

Loading validates every manifest, header and SHA256 but decodes no pixels; a
pose is decoded (and reduced to at most NATIVE_MAX_H tall) the first time it is
drawn, so Xiaoqiao mode never pays for the AI packs.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path, PureWindowsPath
import re
import threading
from types import MappingProxyType
import warnings

from PIL import Image


MODES = frozenset(('xiaoqiao', 'ai'))
POSES = frozenset(('idle', 'thinking', 'waiting', 'happy', 'sleep', 'error', 'listening'))
POSE_ALIASES = {'waiting': 'asking', 'error': 'oops', 'sleep': 'sleeping', 'done': 'happy'}
POSE_FALLBACK = {'compact': 'writing', 'reset': 'happy', 'feast': 'eat', 'sorry': 'listening',
                 'asking': 'listening', 'update': 'happy', 'bye': 'happy',
                 'drawing': 'writing', 'deepthink': 'thinking'}
STABLE_SECONDS = .5
MAX_JSON_BYTES = 64 * 1024
MAX_PACKS = 16
MAX_SIDE = 4096
MAX_IMAGE_PIXELS = 1_000_000
MAX_PACK_PIXELS = 24_000_000
MAX_NATIVE_PIXELS = 128_000_000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_NATIVE_CACHE = 64
MAX_SCALED_CACHE = 256    # fits all five packs and cameos at one box (231); MAX_SCALED_PIXELS is the memory bound
MAX_SCALED_PIXELS = 8_000_000    # 32 MB of RGBA: about three packs at u=1.5
NATIVE_MAX_H = 400       # the pet column is at most ~320px tall (u <= 1.5)
_ID = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_COLOR = re.compile(r'#[0-9a-fA-F]{6}\Z')


def _id(value):
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _number(value):
    return (type(value) in (int, float) and math.isfinite(value))


def _size(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(type(n) is not int or not 0 < n <= MAX_SIDE for n in value):
        return None
    return tuple(value) if value[0] * value[1] <= MAX_IMAGE_PIXELS else None


class _Invalid(ValueError):
    def __init__(self, reason):
        self.reason = reason


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Invalid('invalid_config')
        result[key] = value
    return result


def _bad_constant(value):
    raise _Invalid('invalid_config')


def _read_json(path):
    with path.open('rb') as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise _Invalid('invalid_config')
    result = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_object,
                        parse_constant=_bad_constant)
    if not isinstance(result, dict):
        raise _Invalid('invalid_config')
    return result


def _inside(root, filename, suffixes):
    if not isinstance(filename, str) or not filename or len(filename) > 256:
        raise _Invalid('unsafe_path')
    win = PureWindowsPath(filename)
    parts = filename.replace('\\', '/').split('/')
    if (win.drive or win.root or ':' in filename or '..' in parts
            or any(not part for part in parts)):
        raise _Invalid('unsafe_path')
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in suffixes:
        raise _Invalid('unsafe_path')
    return path


def _picture_bytes(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise _Invalid('resource_budget')
    return raw


@dataclass(frozen=True)
class CharacterPack:
    id: str
    label: str
    renderer: str
    theme: str
    version: int = 1
    poses: tuple = ()
    available: bool = True
    fallback_reason: str | None = None
    fingerprint: str = 'builtin-xiaoqiao'
    schema_version: int = 1
    is_egg: bool = False


@dataclass(frozen=True)
class CharacterFrame:
    image: Image.Image
    offset: tuple
    pose: str
    ref: tuple
    index: int = 0
    alpha_box: tuple | None = None   # image's alpha bbox, computed with the cached sprite


@dataclass(frozen=True)
class Selection:
    mode: str
    character: str
    provider: str | None
    renderer: str
    theme: str
    reason: str
    pack_version: tuple

    @property
    def cache_key(self):
        return (self.mode, self.character, self.provider, self.renderer,
                self.theme, self.pack_version)


@dataclass(frozen=True)
class _Pose:
    path: Path
    size: tuple
    sha: str
    anchor: tuple


@dataclass(frozen=True)
class _Native:
    image: Image.Image       # alpha-cropped, reduced by `ds`
    crop: tuple              # alpha bbox in original pixels
    ds: float                # stored pixels per original pixel


def _text(value, limit):
    return (isinstance(value, str) and len(value) <= limit
            and not any(ord(ch) < 32 or ord(ch) == 127 for ch in value))


def _freeze(value):
    if isinstance(value, dict):return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):return tuple(_freeze(v) for v in value)
    return value


class CharacterCatalog:
    """Validated public packs. Stored/cached images are borrowed, read-only values."""
    def __init__(self):
        self._packs = {'xiaoqiao': CharacterPack('xiaoqiao', '小乔', 'legacy', 'xiaoqiao')}
        self._poses, self._reference_sizes, self._providers, self._processes = {}, {}, {}, {}
        self._lines, self._behaviors, self._blinks, self._egg_hosts = {}, {}, {}, {}
        self._themes = frozenset(('xiaoqiao', 'codex', 'claude', 'gemini', 'deepseek', 'glm'))
        self._natives, self._scaled = OrderedDict(), OrderedDict()
        self._scaled_pixels = self._native_pixels = 0
        self._lock = threading.RLock()
        # Decoding serialises on its own lock and resampling holds none, so a
        # cached frame() never waits behind them. Never take it under _lock.
        self._decode_lock = threading.Lock()
        self.fallback_reason = None

    @staticmethod
    def _registry(asset_root):
        assets = Path(asset_root).resolve();folder = (assets / 'characters').resolve()
        if not folder.is_relative_to(assets):raise _Invalid('unsafe_path')
        registry = _read_json(_inside(folder, 'registry.json', {'.json'}))
        if type(registry.get('schema_version')) is not int or registry['schema_version'] not in (1, 2):raise _Invalid('invalid_config')
        entries = registry.get('characters');themes = registry.get('themes', {})
        if (not isinstance(entries, list) or len(entries) > MAX_PACKS
                or not isinstance(themes, dict) or len(themes) > MAX_PACKS
                or any(not _id(key) for key in themes)):
            raise _Invalid('invalid_config')
        seen = {'xiaoqiao'}
        for entry in entries:
            if not isinstance(entry, dict) or not _id(entry.get('id')) or entry['id'] in seen:
                raise _Invalid('invalid_config')
            _inside(folder, entry.get('manifest'), {'.json'})
            seen.add(entry['id'])
        return folder, registry

    @classmethod
    def listing(cls, asset_root):
        """Registry metadata only; discovery does not claim resource validation."""
        try:
            _, registry = cls._registry(asset_root)
            result = []
            for entry in registry['characters']:
                if entry.get('egg') is not None or entry['id'].startswith('egg-'):continue
                label = entry.get('label', entry['id']);theme = entry.get('theme', entry['id'])
                if not _text(label, 32) or not label.strip() or not _id(theme):raise _Invalid('invalid_config')
                result.append(CharacterPack(entry['id'], label, 'static', theme))
            return tuple(result)
        except (OSError, ValueError, TypeError, UnicodeError, _Invalid, RecursionError, OverflowError):
            return ()

    @classmethod
    def load(cls, asset_root):
        result = cls()
        try:
            folder, registry = cls._registry(asset_root)
            result._themes = frozenset(('xiaoqiao', *registry.get('themes', {})))
            for entry in registry['characters']:result._load_pack(folder, entry)
            # A declared egg host must be a main registered pack, never another egg.
            for ident, metadata in tuple(result._egg_hosts.items()):
                host = result.get(metadata['host'])
                if host is None or host.is_egg or host.renderer != 'static':result.disable(ident, 'invalid_config')
            result._load_providers(registry.get('providers', {}))
        except _Invalid as error:return cls._fallback(error.reason)
        except FileNotFoundError:return cls._fallback('config_missing')
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError):return cls._fallback('invalid_config')
        return result

    @classmethod
    def _fallback(cls, reason):
        result = cls();result.fallback_reason = reason
        return result

    @staticmethod
    def _metadata(data):
        lines = data.get('lines', {});behavior = data.get('behavior', {})
        if not isinstance(lines, dict) or len(lines) > 64 or not isinstance(behavior, dict):raise _Invalid('invalid_config')
        for key, values in lines.items():
            if (not _id(key) or not isinstance(values, list) or len(values) > 16
                    or any(not _text(value, 40) for value in values)):
                raise _Invalid('invalid_config')
        accent = behavior.get('accent')
        if accent is not None and (not isinstance(accent, str) or not _COLOR.fullmatch(accent)):raise _Invalid('invalid_config')
        if not _text(behavior.get('greeting', ''), 40):raise _Invalid('invalid_config')
        idle = behavior.get('idle_actions', [])
        if not isinstance(idle, list) or len(idle) > 32 or any(not _id(v) for v in idle):raise _Invalid('invalid_config')
        for key in ('poke_pose', 'corrected_pose'):
            if behavior.get(key) is not None and not _id(behavior[key]):raise _Invalid('invalid_config')
        long_think = behavior.get('long_think')
        if long_think is not None and (not isinstance(long_think, dict)
                or not _number(long_think.get('after')) or not 0 < long_think['after'] <= 86400
                or not _id(long_think.get('pose'))):raise _Invalid('invalid_config')
        fx = behavior.get('fx', {});glyph = behavior.get('glyph', {})
        if (not isinstance(fx, dict) or len(fx) > 64
                or any(not _id(k) or not isinstance(v, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', v) for k,v in fx.items())
                or not isinstance(glyph, dict) or len(glyph) > 4
                or any(k not in ('fill', 'stroke') or not isinstance(v,str) or not _COLOR.fullmatch(v) for k,v in glyph.items())):
            raise _Invalid('invalid_config')
        clean = {key: behavior[key] for key in ('accent','greeting','idle_actions','poke_pose','corrected_pose','long_think','fx','glyph') if key in behavior}
        return _freeze(lines), clean

    def _load_pack(self, folder, entry):
        ident = entry['id'];is_egg = False
        try:
            path = _inside(folder, entry.get('manifest'), {'.json'});data = _read_json(path)
            schema = data.get('schema_version')
            if (type(schema) is not int or schema not in (1,2) or data.get('id') != ident
                    or data.get('renderer') != 'static' or type(data.get('version')) is not int
                    or not 1 <= data['version'] <= 1_000_000):raise _Invalid('invalid_config')
            label, theme = data.get('label'), data.get('theme')
            if not _text(label,32) or not label.strip() or theme not in self._themes:raise _Invalid('invalid_config')
            reference = _size(data.get('reference_size'));poses = data.get('poses');egg = data.get('egg')
            is_egg = egg is not None
            if is_egg and (schema != 2 or not isinstance(egg,dict) or not _id(egg.get('host'))
                    or not _text(egg.get('caption',''),40) or not isinstance(egg.get('aura'),str)
                    or not _COLOR.fullmatch(egg['aura'])):raise _Invalid('invalid_config')
            if entry.get('egg') is not None and entry['egg'] != egg:raise _Invalid('invalid_config')
            if (reference is None or not isinstance(poses,dict) or not 0 < len(poses) <= 64
                    or any(not _id(key) for key in poses)
                    or (not is_egg and 'idle' not in poses)
                    or (is_egg and set(poses) != {'pop','pretend','caught','bye'})
                    or (schema == 1 and set(poses) - POSES)):
                raise _Invalid('invalid_config')
            lines, behavior = self._metadata(data)
            if is_egg:behavior['egg'] = dict(egg)
            digest = hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode('utf-8'))
            checked = {};pixels = file_bytes = total_frames = 0
            def read_spec(spec):
                nonlocal pixels, file_bytes
                if not isinstance(spec,dict):raise _Invalid('invalid_config')
                image_path = _inside(path.parent,spec.get('file'),{'.webp','.png'})
                size = _size(spec.get('size'));anchor = spec.get('foot_anchor');sha = spec.get('sha256')
                if (size is None or (schema == 1 and (size[0] > reference[0] or size[1] > reference[1]))
                        or not isinstance(anchor,list) or len(anchor) != 2 or any(not _number(n) for n in anchor)
                        or not 0 <= anchor[0] <= size[0] or not 0 <= anchor[1] <= size[1]
                        or (sha is not None and (not isinstance(sha,str) or not _HEX.fullmatch(sha)))
                        or (schema == 2 and sha is None)):
                    raise _Invalid('invalid_config')
                if image_path not in checked:
                    count = image_path.stat().st_size;file_bytes += count
                    if not 0 < count <= MAX_IMAGE_BYTES or file_bytes > MAX_TOTAL_BYTES:raise _Invalid('resource_budget')
                    pixels += size[0]*size[1]
                    if pixels > MAX_PACK_PIXELS or self._native_pixels + pixels > MAX_NATIVE_PIXELS:raise _Invalid('resource_budget')
                    raw = _picture_bytes(image_path);actual = hashlib.sha256(raw).hexdigest()
                    with warnings.catch_warnings():
                        warnings.simplefilter('error',Image.DecompressionBombWarning)
                        with Image.open(io.BytesIO(raw)) as im:
                            if (im.size != size or im.format not in ('PNG','WEBP')
                                    or getattr(im,'n_frames',1) != 1 or 'A' not in im.getbands()):raise _Invalid('invalid_image')
                    checked[image_path] = actual;digest.update(bytes.fromhex(actual))
                actual = checked[image_path]
                if sha is not None and sha != actual:raise _Invalid('image_mismatch')
                return _Pose(image_path,size,actual,tuple(anchor))
            images = {}
            for pose, group in poses.items():
                specs = [group] if schema == 1 else group
                if not isinstance(specs,list) or not 1 <= len(specs) <= 64:raise _Invalid('invalid_config')
                total_frames += len(specs)
                if total_frames > 256:raise _Invalid('resource_budget')
                images[pose] = tuple(read_spec(spec) for spec in specs)
            blink = None;blink_data = data.get('blink')
            if blink_data is not None:
                if schema != 2 or is_egg or not isinstance(blink_data,dict):raise _Invalid('invalid_config')
                base = blink_data.get('base')
                matches = [i for i,spec in enumerate(images['idle']) if spec.path.name == base]
                if len(matches) != 1:raise _Invalid('invalid_config')
                spec = read_spec(blink_data);base_spec = images['idle'][matches[0]]
                if spec.size != base_spec.size or spec.anchor != base_spec.anchor:raise _Invalid('invalid_config')
                blink = (matches[0],spec)
            self._native_pixels += pixels;self._poses[ident] = images;self._reference_sizes[ident] = reference
            self._lines[ident] = lines;self._behaviors[ident] = _freeze(behavior);self._blinks[ident] = blink
            if is_egg:self._egg_hosts[ident] = _freeze(egg)
            self._packs[ident] = CharacterPack(ident,label,'static',theme,data['version'],tuple(poses),
                                               fingerprint=digest.hexdigest(),schema_version=schema,is_egg=is_egg)
        except _Invalid as error:reason = error.reason
        except FileNotFoundError:reason = 'image_missing'
        except (OSError,ValueError,TypeError,UnicodeError,RecursionError,OverflowError,
                Image.DecompressionBombError,Image.DecompressionBombWarning):reason = 'invalid_image'
        else:return
        self._packs[ident] = CharacterPack(ident,ident,'static','xiaoqiao',available=False,
                                           fallback_reason=reason,is_egg=is_egg)

    def _load_providers(self, rows):
        if not isinstance(rows,dict) or len(rows)>MAX_PACKS:raise _Invalid('invalid_config')
        assignments = {}
        for provider,row in rows.items():
            if not _id(provider) or not isinstance(row,dict):raise _Invalid('invalid_config')
            character,theme,apps = row.get('character'),row.get('theme'),row.get('windows_apps',[])
            pack = self.get(character)
            if (not _id(character) or pack is None or pack.is_egg or theme not in self._themes
                    or not isinstance(apps,list) or len(apps)>16):raise _Invalid('invalid_config')
            self._providers[provider] = MappingProxyType({'character':character,'theme':theme})
            for app in apps:
                name = self._basename(app)
                if name is None:raise _Invalid('invalid_config')
                assignments.setdefault(name,set()).add(provider)
        self._processes = {name:next(iter(providers)) for name,providers in assignments.items() if len(providers)==1}

    @staticmethod
    def _basename(value):
        if (not isinstance(value,str) or not 1<=len(value)<=128
                or any(c in value for c in '/\\:\0') or not value.lower().endswith('.exe')):return None
        return value.casefold()

    def provider_for_process(self, basename):return self._processes.get(self._basename(basename))
    def provider_for_character(self, character):
        return next((key for key,row in self._providers.items() if row['character']==character),None)
    def ids(self, *, include_unavailable=False, include_eggs=False):
        with self._lock:return tuple(key for key,pack in self._packs.items()
            if (include_unavailable or pack.available) and (include_eggs or not pack.is_egg))
    def get(self, ident):return self._packs.get(ident) if isinstance(ident,str) else None
    def binding(self, provider):return self._providers.get(provider) if isinstance(provider,str) else None
    def has_pose(self, character, pose):
        pack = self.get(character)
        return bool(pack and pack.available and isinstance(pose,str) and pose in self._poses.get(character,{}))
    def resolve(self, character, pose):
        pack = self.get(character)
        if pack is None or not pack.available or pack.renderer!='static':return None
        groups = self._poses[character];pose = pose if isinstance(pose,str) else 'idle'
        if pose in groups:return pose
        if pack.schema_version == 1:
            legacy = {'asking':'waiting','sleeping':'sleep','oops':'error','done':'happy'}
            candidate = legacy.get(pose,pose)
        else:candidate = POSE_ALIASES.get(pose,pose)
        if candidate in groups:return candidate
        candidate = POSE_FALLBACK.get(candidate)
        if candidate in groups:return candidate
        return 'pop' if pack.is_egg else 'idle'
    def frame_count(self, character, pose):
        resolved = self.resolve(character,pose)
        return len(self._poses[character][resolved]) if resolved else 0
    def lines(self, character, key):
        pack = self.get(character)
        return self._lines.get(character,{}).get(key,()) if pack and pack.available and isinstance(key,str) else ()
    def behavior(self, character):
        pack = self.get(character)
        return self._behaviors.get(character,MappingProxyType({})) if pack and pack.available else MappingProxyType({})
    def eggs_for(self, host):
        return tuple(key for key,data in self._egg_hosts.items() if data['host']==host and self.get(key).available)
    def blink_index(self, character):
        pack = self.get(character);blink = self._blinks.get(character)
        return blink[0] if pack and pack.available and blink else None

    def _spec(self, character, pose, index=0, blink=False):
        groups = self._poses[character][pose];index %= len(groups)
        pair = self._blinks.get(character)
        return pair[1] if blink and pose=='idle' and pair and index==pair[0] else groups[index]

    def _cached_native(self, key):
        with self._lock:
            native = self._natives.get(key)
            if native is not None:self._natives.move_to_end(key)
            return native

    @staticmethod
    def _decode(spec):
        try:
            if not 0 < spec.path.stat().st_size <= MAX_IMAGE_BYTES:return None
            raw = _picture_bytes(spec.path)
            if hashlib.sha256(raw).hexdigest()!=spec.sha:return None
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as im:
                    if im.size!=spec.size or getattr(im,'n_frames',1)!=1:return None
                    image = im.convert('RGBA')
        except (OSError,ValueError,_Invalid,Image.DecompressionBombError,Image.DecompressionBombWarning):return None
        box = image.getchannel('A').getbbox()
        if box is None:return None
        image = image.crop(box);ds = min(1.,NATIVE_MAX_H/spec.size[1])
        if ds<1:image = image.resize((max(1,round(image.width*ds)),max(1,round(image.height*ds))),Image.Resampling.LANCZOS)
        return _Native(image,box,ds)

    def _native(self, character, pose, index=0, blink=False):
        with self._lock:
            spec = self._spec(character,pose,index,blink);key = (character,spec.path,spec.sha)
            pack = self.get(character)
        native = self._cached_native(key)
        if native is not None:return native
        with self._decode_lock:
            native = self._cached_native(key)    # decoded while this thread waited
            if native is not None:return native
            native = self._decode(spec)
            with self._lock:
                # disable() is atomic: a pack dropped mid-decode is never re-cached.
                if native is not None and pack.available and self.get(character) is pack:
                    self._natives[key] = native
                    while len(self._natives)>MAX_NATIVE_CACHE:self._natives.popitem(last=False)
        return native

    def prewarm(self, character, poses, box_size=None, scaled=None):
        """Worker API; each resource gets a lock, never the entire package.

        Decodes serialise on their own lock and never hold the cache lock, so a
        cached UI frame or disable() proceeds even mid-decode; a pack disabled
        meanwhile is not re-cached. Metadata is immutable.
        With box_size, each pose is also scaled right after it is decoded, idle
        (every variant and its blink) first, so the frame loop neither decodes
        nor resamples a pose this pack can show. scaled=None scales every pose
        in `poses` plus the host's egg cameos; a tuple limits scaling to those
        poses (no cameos). One call scales at most half of MAX_SCALED_CACHE and
        of MAX_SCALED_PIXELS, so it never evicts what it warmed itself; anything
        past that scales on first use, as before.
        """
        if not isinstance(poses,(list,tuple)) or len(poses)>64:return False
        pack = self.get(character)
        if pack is None or not pack.available or pack.renderer!='static':return False
        size = _size(box_size) if box_size is not None else None
        targets = None if scaled is None else {self.resolve(character,pose) for pose in scaled}
        budget = [MAX_SCALED_CACHE//2,MAX_SCALED_PIXELS//2]

        def warm(pose,index,blink=False):
            current = self.get(character)
            if current is None or not current.available:return False
            if self._native(character,pose,index,blink) is None:
                self.disable(character,'image_missing');return False
            return True

        def scale(ident,pose,index,blink=False):
            # A frame never outgrows its box, so a whole box of headroom keeps the call within half.
            if budget[0]<1 or budget[1]<size[0]*size[1]:return True
            frame = self.frame(ident,pose,size,index,blink)
            if frame is None:return False
            budget[0] -= 1;budget[1] -= frame.image.width*frame.image.height
            return True

        done = set()
        for pose in sorted(poses,key=lambda p:self.resolve(character,p)!='idle'):    # stable: idle first
            resolved = self.resolve(character,pose)
            if resolved is None:return False
            if resolved in done:continue
            done.add(resolved)
            blink = self.blink_index(character) if resolved=='idle' else None
            for index in range(self.frame_count(character,pose)):
                if not warm(resolved,index):return False
            if blink is not None and not warm('idle',blink,True):return False
            if size is None or (targets is not None and resolved not in targets):continue
            for index in range(self.frame_count(character,pose)):
                if not scale(character,resolved,index):return False
            if blink is not None and not scale(character,'idle',blink,True):return False
        if size is not None and scaled is None:
            for egg in self.eggs_for(character):
                # A broken cameo disables only itself (frame() does that), never its host.
                for pose in self.get(egg).poses:
                    if not all(scale(egg,pose,index) for index in range(self.frame_count(egg,pose))):break
        with self._lock:
            return self.get(character).available

    def frame(self, character, pose, box_size, index=0, blink=False):
        with self._lock:
            size = _size(box_size);resolved = self.resolve(character,pose)
            if size is None or resolved is None or type(index) is not int or type(blink) is not bool:return None
            pack = self.get(character);index %= self.frame_count(character,resolved)
            pair = self._blinks.get(character)
            use_blink = bool(blink and resolved=='idle' and pair and index==pair[0])
            key = (character,pack.version,pack.fingerprint,resolved,index,use_blink,*size)
            cached = self._scaled.get(key)
            if cached is not None:self._scaled.move_to_end(key);return cached
            spec = self._spec(character,resolved,index,use_blink);rw,rh = self._reference_sizes[character]
        # Decode/resample unlocked: the frame loop's cached poses never wait behind a worker.
        # Keep the original two-argument seam for legacy host test doubles.
        native = self._native(character,resolved) if index==0 and not use_blink else self._native(character,resolved,index,use_blink)
        if native is None:self.disable(character,'image_missing');return None
        scale = min(size[0]/rw,size[1]/rh)
        if pack.schema_version==2:scale = min(scale,size[0]/spec.size[0],size[1]/spec.size[1])
        crop = native.crop;width = max(1,round((crop[2]-crop[0])*scale));height = max(1,round((crop[3]-crop[1])*scale))
        image = native.image.resize((width,height),Image.Resampling.LANCZOS)
        left = round(size[0]/2-(spec.anchor[0]-crop[0])*scale);top = round(size[1]-(spec.anchor[1]-crop[1])*scale)
        if pack.schema_version==2:
            left = min(max(0,left),size[0]-width)
            # Public foot anchors are the full canvas bottom. Bad vertical anchors cannot crop faces.
            top = min(max(0,top),size[1]-height)
        else:
            right,bottom = min(size[0],left+width),min(size[1],top+height);x0,y0 = max(0,left),max(0,top)
            if right<=x0 or bottom<=y0:return None
            if left<0 or top<0 or right<left+width or bottom<top+height:image = image.crop((x0-left,y0-top,right-left,bottom-top))
            left,top = x0,y0
        with self._lock:
            if self.get(character) is not pack:return None     # disabled while resampling
            cached = self._scaled.get(key)
            if cached is not None:self._scaled.move_to_end(key);return cached
            frame = CharacterFrame(image,(left,top),resolved,key,index,image.getchannel('A').getbbox());self._scaled[key] = frame
            self._scaled_pixels += image.width*image.height
            while len(self._scaled)>MAX_SCALED_CACHE or self._scaled_pixels>MAX_SCALED_PIXELS:
                _,removed = self._scaled.popitem(last=False);self._scaled_pixels -= removed.image.width*removed.image.height
            return frame

    def disable(self, ident, reason):
        with self._lock:
            pack = self.get(ident)
            if pack is None or pack.renderer!='static':return
            self._packs[ident] = CharacterPack(ident,pack.label,'static','xiaoqiao',pack.version,pack.poses,
                available=False,fallback_reason=reason,fingerprint=pack.fingerprint,schema_version=pack.schema_version,is_egg=pack.is_egg)
            for key in [k for k in self._scaled if k[0]==ident]:
                removed = self._scaled.pop(key);self._scaled_pixels -= removed.image.width*removed.image.height
            for key in [k for k in self._natives if k[0]==ident]:del self._natives[key]

    def clear_scaled_cache(self):
        with self._lock:self._scaled.clear();self._scaled_pixels = 0


class AppearanceSelector:
    """Caller supplies monotonic time and a finite foreground provider identity.

    Sleep does not hold a switch back: the pet naps after a minute without
    being touched, which is most of the time someone works in another app.
    Only an active drag defers it, and the latest request wins on release.
    """
    def __init__(self, catalog, settings=None):
        self.catalog = catalog
        settings = settings if isinstance(settings, dict) else {}
        mode = settings.get('appearance_mode')
        pin = settings.get('appearance_pin')
        last = settings.get('appearance_last')
        self._mode = mode if isinstance(mode, str) and mode in MODES else 'xiaoqiao'
        self._pin = pin if isinstance(pin, str) and (pin == 'auto' or pin in catalog.ids()) else 'auto'
        self._last = last if isinstance(last, str) and last in catalog.ids() and last != 'xiaoqiao' else None
        self._candidate = None
        self._candidate_since = None
        self._last_now = None
        self._selection = self._make('xiaoqiao', None, 'xiaoqiao', 'default')
        if self._mode == 'ai':
            self._selection = self._entry(None)

    @property
    def mode(self):
        return self._mode

    @property
    def pin(self):
        return self._pin

    @property
    def selection(self):
        return self._selection

    @property
    def candidate(self):
        """Character of the foreground AI that observe() is timing for a switch, else None.

        It stays set after the switch commits (then it equals the selection) and is
        cleared by anything that clears the pending switch.
        """
        binding = self.catalog.binding(self._candidate) if self._candidate is not None else None
        return binding['character'] if binding else None

    def settings_export(self):
        result = {'appearance_mode': self._mode, 'appearance_pin': self._pin}
        if self._last:
            result['appearance_last'] = self._last
        return result

    def _clear_candidate(self):
        self._candidate, self._candidate_since = None, None

    def _make(self, character, provider, theme, reason):
        pack = self.catalog.get(character)
        if pack is None or not pack.available or pack.is_egg:
            pack = self.catalog.get('xiaoqiao')
            theme, reason = 'xiaoqiao', 'resource_fallback'
        elif pack.id != 'xiaoqiao' and self._mode == 'ai':
            self._last = pack.id
        return Selection(self._mode, pack.id, provider, pack.renderer, theme or pack.theme,
                         reason, (pack.version, pack.fingerprint))

    def _entry(self, initial):
        """AI mode never starts blank: pin, else the caller's hint, else the last one shown."""
        if self._pin != 'auto':
            return self._make(self._pin, None, None, 'pinned')
        for character in (initial, self._last):
            pack = self.catalog.get(character)
            if pack is not None and pack.available and pack.id != 'xiaoqiao' and not pack.is_egg:
                return self._make(pack.id, self.catalog.provider_for_character(pack.id), None, 'entered')
        static = [key for key in self.catalog.ids() if key != 'xiaoqiao']
        if static:
            return self._make(static[0], self.catalog.provider_for_character(static[0]), None, 'entered')
        return self._make('xiaoqiao', None, 'xiaoqiao', 'resource_fallback')

    def revalidate(self):
        """Re-make the current choice after a pack became unavailable (whole fallback)."""
        current = self._selection
        pack = self.catalog.get(current.character)
        if pack is not None and pack.available:
            return current
        self._clear_candidate()
        if self._pin != 'auto' and self._pin == current.character:
            self._pin = 'auto'
        self._selection = self._make(current.character, current.provider, None, current.reason)
        return self._selection

    def set_mode(self, mode, initial=None):
        if not isinstance(mode, str) or mode not in MODES:
            return self._selection
        if mode == self._mode:
            return self._selection
        self._mode = mode
        self._clear_candidate()
        if mode == 'ai':
            self._selection = self._entry(initial)
        else:
            self._selection = self._make('xiaoqiao', None, 'xiaoqiao', 'mode_selected')
        return self._selection

    def set_pin(self, character):
        if (not isinstance(character, str)
                or (character != 'auto' and character not in self.catalog.ids())):
            return self._selection
        if character == self._pin:
            return self._selection
        self._pin = character
        self._clear_candidate()
        if self._mode == 'ai' and character != 'auto':
            self._selection = self._make(character, None, None, 'pinned')
        return self._selection

    def observe(self, provider, now, *, dragging=False):
        if not _number(now):
            self._clear_candidate()
            return self._selection
        if self._last_now is not None and now < self._last_now:
            self._clear_candidate()
        self._last_now = now
        if self._mode == 'xiaoqiao':
            self._clear_candidate()
            return self._selection
        if self._pin != 'auto':
            self._clear_candidate()
            return self._selection
        binding = self.catalog.binding(provider)
        if binding is None:
            # Ordinary apps, browsers and the pet itself keep the current look.
            self._clear_candidate()
            return self._selection
        if self._candidate != provider:
            self._candidate, self._candidate_since = provider, now
        if dragging or now - self._candidate_since < STABLE_SECONDS:
            return self._selection
        candidate = self._make(binding['character'], provider, binding['theme'], 'foreground')
        if candidate.cache_key != self._selection.cache_key:
            self._selection = candidate
        return self._selection
