"""Small, asset-bound clips; no clock, movement state or AI input.

The first bank accepts only a non-looping blink. PNGs are local RGBA overlays
on a fixed source canvas; the host keeps timing, compositing and fallback.
Loading reads and decodes each unique frame once. Returned cached images are
read-only to callers. BodySpriteBank separately accepts only a relief breath
replacement crop; it does not expand the expression or movement protocols.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import warnings

from PIL import Image


MAX_MANIFEST_BYTES = 64 * 1024
MAX_SIDE = 4096
MAX_CANVAS_PIXELS = 4_000_000
MAX_FRAME_PIXELS = 1_000_000
MAX_DECODED_PIXELS = 4_000_000
MAX_FRAMES = 16
MAX_SCALED_CACHE = 8
FALLBACK_REASONS = frozenset((
    'manifest_missing', 'invalid_manifest', 'source_mismatch',
    'eyes_mismatch', 'invalid_frame', 'unsafe_path',
))
BODY_FALLBACK_REASONS = FALLBACK_REASONS | {'geometry_mismatch'}
BODY_MAX_FILE_BYTES = 4 * 1024 * 1024
BODY_MAX_TOTAL_FILE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class FrameRef:
    version: int
    clip: str
    index: int

    @property
    def cache_key(self):
        return self.version, self.clip, self.index


@dataclass(frozen=True)
class _Frame:
    image: Image.Image
    end_ms: float


@dataclass(frozen=True)
class _BodyFrame:
    image: Image.Image
    end_ms: float
    baked_breath: float


class _LoadError(ValueError):
    def __init__(self, reason):
        self.reason = reason


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def _size(value, max_pixels):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    if any(type(v) is not int or not 0 < v <= MAX_SIDE for v in value):
        return None
    width, height = value
    return (width, height) if width * height <= max_pixels else None


def _sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value))


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _LoadError('invalid_manifest')
        result[key] = value
    return result


def _bad_constant(value):
    raise _LoadError('invalid_manifest')


def _inside(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise _LoadError('unsafe_path')
    return resolved


def _frame_path(root, filename):
    if not isinstance(filename, str) or not filename or len(filename) > 512:
        raise _LoadError('unsafe_path')
    windows = PureWindowsPath(filename)
    parts = filename.replace('\\', '/').split('/')
    if (windows.drive or windows.root or filename.startswith('/')
            or ':' in filename or '..' in parts):
        raise _LoadError('unsafe_path')
    path = _inside(root.joinpath(*parts), root)
    if path.suffix.lower() != '.png':
        raise _LoadError('invalid_frame')
    return path


class SpriteBank:
    def __init__(self, *, fallback_reason=None, canvas=None, anchor=None,
                 frames=(), version=1):
        self.fallback_reason = fallback_reason
        self._canvas = canvas
        self._anchor = anchor
        self._frames = tuple(frames)
        self._version = version
        self._scaled = OrderedDict()

    @classmethod
    def load(cls, asset_root, source_image, eyes_config):
        """Read the one public manifest, failing closed to a procedural fallback."""
        try:
            return cls._load(asset_root, source_image, eyes_config)
        except _LoadError as error:
            return cls(fallback_reason=error.reason)
        except FileNotFoundError:
            return cls(fallback_reason='manifest_missing')
        except (OSError, ValueError, TypeError, OverflowError, RuntimeError):
            return cls(fallback_reason='invalid_manifest')

    @classmethod
    def _load(cls, asset_root, source_image, eyes_config):
        assets = Path(asset_root).resolve()
        folder = _inside(assets / 'animations', assets)
        manifest_path = _inside(folder / 'manifest.json', folder)
        with manifest_path.open('rb') as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise _LoadError('invalid_manifest')
        data = json.loads(raw, object_pairs_hook=_json_object,
                          parse_constant=_bad_constant)
        if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
            raise _LoadError('invalid_manifest')
        source = data.get('source')
        if not isinstance(source, dict):
            raise _LoadError('invalid_manifest')
        canvas = _size(source.get('size'), MAX_CANVAS_PIXELS)
        if (canvas is None or not _sha(source.get('rgba_sha256'))
                or not _sha(source.get('eyes_sha256'))):
            raise _LoadError('invalid_manifest')
        if (not isinstance(source_image, Image.Image) or source_image.mode != 'RGBA'
                or source_image.size != canvas):
            raise _LoadError('source_mismatch')
        try:
            source_hash = hashlib.sha256(source_image.tobytes()).hexdigest()
        except (OSError, ValueError):
            raise _LoadError('source_mismatch') from None
        if source_hash != source['rgba_sha256']:
            raise _LoadError('source_mismatch')
        if not isinstance(eyes_config, dict):
            raise _LoadError('eyes_mismatch')
        try:
            eyes = json.dumps(eyes_config, sort_keys=True, ensure_ascii=True,
                              allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, OverflowError):
            raise _LoadError('eyes_mismatch') from None
        if hashlib.sha256(eyes).hexdigest() != source['eyes_sha256']:
            raise _LoadError('eyes_mismatch')
        clips = data.get('clips')
        if not isinstance(clips, dict) or set(clips) != {'blink'}:
            raise _LoadError('invalid_manifest')
        clip = clips['blink']
        if (not isinstance(clip, dict) or clip.get('layer') != 'expression'
                or clip.get('loop') is not False or clip.get('return_to') != 'base'
                or _size(clip.get('canvas'), MAX_CANVAS_PIXELS) != canvas):
            raise _LoadError('invalid_manifest')
        rect, anchor = clip.get('rect'), clip.get('anchor')
        if (not isinstance(rect, list) or len(rect) != 4
                or any(type(v) is not int for v in rect)
                or not isinstance(anchor, list) or len(anchor) != 2
                or any(type(v) is not int for v in anchor)):
            raise _LoadError('invalid_manifest')
        x, y, width, height = rect
        frame_size = _size((width, height), MAX_FRAME_PIXELS)
        if (frame_size is None or x < 0 or y < 0 or x + width > canvas[0]
                or y + height > canvas[1] or anchor != [x, y]):
            raise _LoadError('invalid_manifest')
        entries = clip.get('frames')
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FRAMES:
            raise _LoadError('invalid_manifest')
        validated, durations = [], []
        for entry in entries:
            if not isinstance(entry, dict):
                raise _LoadError('invalid_manifest')
            duration = entry.get('duration_ms')
            if not _finite_number(duration) or not 0 < duration <= 1000:
                raise _LoadError('invalid_manifest')
            durations.append(float(duration))
            validated.append((_frame_path(folder, entry.get('file')), float(duration)))
        if math.fsum(durations) > 2000:
            raise _LoadError('invalid_manifest')
        images, frames, decoded_pixels = {}, [], 0
        elapsed_ms = 0.0
        for path, duration in validated:
            if path not in images:
                if decoded_pixels + width * height > MAX_DECODED_PIXELS:
                    raise _LoadError('invalid_frame')
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', Image.DecompressionBombWarning)
                        with Image.open(path) as image:
                            if (image.format != 'PNG' or image.mode != 'RGBA' or image.size != frame_size
                                    or getattr(image, 'n_frames', 1) != 1):
                                raise _LoadError('invalid_frame')
                            image.load()
                            images[path] = image.copy()
                except (OSError, ValueError, Image.DecompressionBombError,
                        Image.DecompressionBombWarning):
                    raise _LoadError('invalid_frame') from None
                decoded_pixels += width * height
            elapsed_ms = math.fsum((elapsed_ms, duration))
            frames.append(_Frame(images[path], elapsed_ms))
        return cls(canvas=canvas, anchor=(x, y), frames=frames,
                   version=data['version'])

    def duration(self, name):
        if not isinstance(name, str) or name != 'blink' or not self._frames:
            return None
        return self._frames[-1].end_ms / 1000.0

    def sample(self, name, elapsed):
        """Return a frame for supplied time; never advance or retain playback time."""
        if (not isinstance(name, str) or name != 'blink' or not self._frames
                or not _finite_number(elapsed) or elapsed < 0):
            return None
        milliseconds = elapsed * 1000
        for index, frame in enumerate(self._frames):
            if milliseconds < frame.end_ms:
                return FrameRef(self._version, 'blink', index)
        return None

    def overlay(self, ref, target_size):
        """Scale uniformly, or return None for the host's procedural fallback.

        Invalid/oversized target canvases never evict or stretch loaded assets.
        A one-pixel canvas-width rounding difference is permitted.
        """
        if (not isinstance(ref, FrameRef) or type(ref.version) is not int
                or ref.version != self._version or not isinstance(ref.clip, str) or ref.clip != 'blink'
                or type(ref.index) is not int or not 0 <= ref.index < len(self._frames)):
            return None
        size = _size(target_size, MAX_CANVAS_PIXELS)
        if size is None or self._canvas is None:
            return None
        scale = size[1] / self._canvas[1]
        if abs(size[0] - self._canvas[0] * scale) > 1.000001:
            return None
        key = ref.cache_key, size
        if key in self._scaled:
            self._scaled.move_to_end(key)
            return self._scaled[key]
        original = self._frames[ref.index].image
        scaled_size = max(1, round(original.width * scale)), max(1, round(original.height * scale))
        if scaled_size[0] * scaled_size[1] > MAX_CANVAS_PIXELS:
            return None
        image = original.resize(scaled_size, Image.Resampling.LANCZOS)
        offset = tuple(round(v * scale) for v in self._anchor)
        value = image, offset
        self._scaled[key] = value
        if len(self._scaled) > MAX_SCALED_CACHE:
            self._scaled.popitem(last=False)
        return value

    def clear_scaled_cache(self):
        self._scaled.clear()


class BodySpriteBank:
    """Only the relief body's baked breath channel, leaving live pose to the host.

    replacement() returns a crop for RGBA paste WITHOUT a mask, so transparent
    pixels erase the previous silhouette. It is not an alpha-composite overlay.
    The host subtracts baked_breath once from its effective procedural breath.
    One retained source copy is bounded by the 4M canvas pixels (16MB RGBA).
    A cold scale uses temporary native/target canvases, each at most 4M pixels,
    then retains only a crop in the existing eight-entry scaled LRU.
    """

    def __init__(self, *, fallback_reason=None, canvas=None, anchor=None,
                 frames=(), version=1, source=None):
        self.fallback_reason = fallback_reason
        self._canvas = canvas
        self._anchor = anchor
        self._frames = tuple(frames)
        self._version = version
        self._scaled = OrderedDict()
        self._source = source.copy() if source is not None else None

    @classmethod
    def load(cls, asset_root, source_image, geometry_config, expected_duration=2.8):
        """Decode one public, source-bound replacement bank or return empty."""
        try:
            return cls._load(asset_root, source_image, geometry_config, expected_duration)
        except _LoadError as error:
            return cls(fallback_reason=error.reason)
        except FileNotFoundError:
            return cls(fallback_reason='manifest_missing')
        except (OSError, ValueError, TypeError, OverflowError, RuntimeError):
            return cls(fallback_reason='invalid_manifest')

    @classmethod
    def _load(cls, asset_root, source_image, geometry_config, expected_duration):
        if not _finite_number(expected_duration) or not 0 < expected_duration <= 4:
            raise _LoadError('invalid_manifest')
        assets = Path(asset_root).resolve()
        animations = _inside(assets / 'animations', assets)
        folder = _inside(animations / 'relief-body', animations)
        manifest_path = _inside(folder / 'manifest.json', folder)
        with manifest_path.open('rb') as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise _LoadError('invalid_manifest')
        data = json.loads(raw, object_pairs_hook=_json_object,
                          parse_constant=_bad_constant)
        if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
            raise _LoadError('invalid_manifest')
        source = data.get('source')
        if not isinstance(source, dict):
            raise _LoadError('invalid_manifest')
        canvas = _size(source.get('size'), MAX_CANVAS_PIXELS)
        if (canvas is None or not _sha(source.get('rgba_sha256'))
                or not _sha(source.get('geometry_sha256'))):
            raise _LoadError('invalid_manifest')
        if (not isinstance(source_image, Image.Image) or source_image.mode != 'RGBA'
                or source_image.size != canvas):
            raise _LoadError('source_mismatch')
        try:
            source_hash = hashlib.sha256(source_image.tobytes()).hexdigest()
        except (OSError, ValueError):
            raise _LoadError('source_mismatch') from None
        if source_hash != source['rgba_sha256']:
            raise _LoadError('source_mismatch')
        if not isinstance(geometry_config, dict):
            raise _LoadError('geometry_mismatch')
        try:
            geometry = json.dumps(geometry_config, sort_keys=True, ensure_ascii=True,
                                  allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, OverflowError, RuntimeError):
            raise _LoadError('geometry_mismatch') from None
        if hashlib.sha256(geometry).hexdigest() != source['geometry_sha256']:
            raise _LoadError('geometry_mismatch')
        clip = data.get('clip')
        if (not isinstance(clip, dict) or clip.get('action') != 'relief'
                or clip.get('channel') != 'breath' or clip.get('loop') is not False
                or clip.get('return_to') != 'base'
                or _size(clip.get('canvas'), MAX_CANVAS_PIXELS) != canvas):
            raise _LoadError('invalid_manifest')
        rect, anchor = clip.get('rect'), clip.get('anchor')
        if (not isinstance(rect, list) or len(rect) != 4
                or any(type(v) is not int for v in rect)
                or not isinstance(anchor, list) or len(anchor) != 2
                or any(type(v) is not int for v in anchor)):
            raise _LoadError('invalid_manifest')
        x, y, width, height = rect
        frame_size = _size((width, height), MAX_FRAME_PIXELS)
        if (frame_size is None or x < 0 or y < 0 or x + width > canvas[0]
                or y + height > canvas[1] or anchor != [x, y]):
            raise _LoadError('invalid_manifest')
        entries = clip.get('frames')
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FRAMES:
            raise _LoadError('invalid_manifest')
        validated, durations, file_breaths = [], [], {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise _LoadError('invalid_manifest')
            duration, breath = entry.get('duration_ms'), entry.get('baked_breath')
            if (not _finite_number(duration) or not 0 < duration <= 1000
                    or not _finite_number(breath) or not -1.5 <= breath <= 1.5
                    or breath * 4 != round(breath * 4)):
                raise _LoadError('invalid_manifest')
            path = _frame_path(folder, entry.get('file'))
            if path in file_breaths and file_breaths[path] != breath:
                raise _LoadError('invalid_manifest')
            file_breaths[path] = float(breath)
            durations.append(float(duration))
            validated.append((path, float(duration), float(breath)))
        total_ms = math.fsum(durations)
        if total_ms > 4000 or abs(total_ms / 1000 - expected_duration) > 1e-6:
            raise _LoadError('invalid_manifest')
        total_file_bytes = 0
        for path in file_breaths:
            try:
                file_bytes = path.stat().st_size
            except OSError:
                raise _LoadError('invalid_frame') from None
            if not 0 < file_bytes <= BODY_MAX_FILE_BYTES:
                raise _LoadError('invalid_frame')
            total_file_bytes += file_bytes
            if total_file_bytes > BODY_MAX_TOTAL_FILE_BYTES:
                raise _LoadError('invalid_frame')
        images, frames, decoded_pixels = {}, [], 0
        elapsed_ms = 0.0
        for path, duration, breath in validated:
            if path not in images:
                if decoded_pixels + width * height > MAX_DECODED_PIXELS:
                    raise _LoadError('invalid_frame')
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', Image.DecompressionBombWarning)
                        with Image.open(path) as image:
                            if (image.format != 'PNG' or image.mode != 'RGBA' or image.size != frame_size
                                    or getattr(image, 'n_frames', 1) != 1):
                                raise _LoadError('invalid_frame')
                            image.load()
                            images[path] = image.copy()
                except (OSError, ValueError, Image.DecompressionBombError,
                        Image.DecompressionBombWarning):
                    raise _LoadError('invalid_frame') from None
                decoded_pixels += width * height
            elapsed_ms = math.fsum((elapsed_ms, duration))
            frames.append(_BodyFrame(images[path], elapsed_ms, breath))
        return cls(canvas=canvas, anchor=(x, y), frames=frames,
                   version=data['version'], source=source_image)

    def duration(self):
        return self._frames[-1].end_ms / 1000.0 if self._frames else None

    def sample(self, elapsed):
        """Pure elapsed sampling, with no looping, deferred requests or clock."""
        if not self._frames or not _finite_number(elapsed) or elapsed < 0:
            return None
        milliseconds = elapsed * 1000
        for index, frame in enumerate(self._frames):
            if milliseconds < frame.end_ms:
                return FrameRef(self._version, 'relief_body', index)
        return None

    def replacement(self, ref, target_size):
        """Return an immutable-by-convention replacement crop, offset and breath.

        Invalid or oversized target canvases return None for the host fallback.
        The full canvas uses the exact SceneArt.scaled target dimensions and
        LANCZOS sampling phase. Only a one-pixel aspect rounding is permitted;
        the output crop includes a three-target-pixel filter halo.
        """
        if (not isinstance(ref, FrameRef) or type(ref.version) is not int
                or ref.version != self._version or not isinstance(ref.clip, str) or ref.clip != 'relief_body'
                or type(ref.index) is not int or not 0 <= ref.index < len(self._frames)):
            return None
        size = _size(target_size, MAX_CANVAS_PIXELS)
        if size is None or self._canvas is None or self._source is None:
            return None
        scale = size[1] / self._canvas[1]
        if abs(size[0] - self._canvas[0] * scale) > 1.000001:
            return None
        key = ref.cache_key, size
        if key in self._scaled:
            self._scaled.move_to_end(key)
            return self._scaled[key]
        frame = self._frames[ref.index]
        # Resizing a crop independently changes the pixel-center phase and can
        # alter the protected face even when this frame is entirely neutral.
        # Compose in native coordinates, then resize the same complete canvas
        # as SceneArt.scaled; only the resulting replacement ROI is retained.
        native = self._source.copy()
        native.paste(frame.image, self._anchor)
        scaled = native.resize(size, Image.Resampling.LANCZOS)
        sx, sy = size[0] / self._canvas[0], size[1] / self._canvas[1]
        x, y = self._anchor
        left = max(0, math.floor(x * sx) - 3)
        top = max(0, math.floor(y * sy) - 3)
        right = min(size[0], math.ceil((x + frame.image.width) * sx) + 3)
        bottom = min(size[1], math.ceil((y + frame.image.height) * sy) + 3)
        image = scaled.crop((left, top, right, bottom))
        offset = left, top
        replacement = image, offset, frame.baked_breath
        self._scaled[key] = replacement
        if len(self._scaled) > MAX_SCALED_CACHE:
            self._scaled.popitem(last=False)
        return replacement

    def clear_scaled_cache(self):
        self._scaled.clear()
