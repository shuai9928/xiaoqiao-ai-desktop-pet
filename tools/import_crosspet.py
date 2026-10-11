"""Copy bounded public art/config bytes only; never execute upstream code."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import warnings
from PIL import Image

DEST = Path(__file__).resolve().parents[1] / 'assets' / 'characters'
ROLES = ('claude', 'gpt', 'gemini', 'deepseek', 'glm')


def local_id(name):
    return 'codex' if name == 'gpt' else 'egg-codex' if name == 'egg-gpt' else name


def atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == raw:
        return False
    before = path.stat().st_mtime_ns if path.exists() else None
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:stream.write(raw)
        current = path.stat().st_mtime_ns if path.exists() else None
        if current != before:raise RuntimeError('Destination changed during import: ' + path.name)
        os.replace(name, path)
    finally:Path(name).unlink(missing_ok=True)
    return True


def import_assets(source, destination=DEST, *, check=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    root = (source / 'characters').resolve()
    if not root.is_relative_to(source) or not root.is_dir():raise ValueError('Missing or unsafe characters directory')
    if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError('Source and destination must not overlap')
    folders = list(ROLES) + sorted(p.name for p in root.glob('egg-*') if p.is_dir())
    files, total_pixels = [], 0
    for name in folders:
        if name not in ROLES and name not in ('egg-' + r for r in ROLES):raise ValueError('Unknown egg package')
        folder = (root / name).resolve()
        if not folder.is_relative_to(root) or not folder.is_dir():raise ValueError('Missing or unsafe package: ' + name)
        images = sorted(folder.glob('*.webp'))
        if not images or len(images) > 128:raise ValueError('Invalid image count')
        pixels = byte_count = 0
        for path in images:
            if not path.resolve().is_relative_to(folder):raise ValueError('Image escapes package')
            if not 0 < path.stat().st_size <= 4 * 1024 * 1024:raise ValueError('Image byte budget exceeded')
            with path.open('rb') as stream:raw = stream.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:raise ValueError('Image changed beyond byte budget')
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if (image.format != 'WEBP' or image.mode != 'RGBA' or getattr(image, 'n_frames', 1) != 1
                            or not 0 < image.width <= 4096 or not 0 < image.height <= 4096
                            or image.width * image.height > 1_000_000):
                        raise ValueError('Expected bounded single-frame RGBA WebP')
                    pixels += image.width * image.height
            byte_count += len(raw)
            files.append((destination / local_id(name) / path.name, raw))
        if pixels > 24_000_000 or byte_count > 32 * 1024 * 1024:raise ValueError('Package budget exceeded')
        total_pixels += pixels
        config = (folder / 'character.json').resolve()
        if not config.is_relative_to(folder) or not config.is_file() or config.stat().st_size > 65536:
            raise ValueError('Missing, oversized or unsafe character.json')
        raw = config.read_bytes()
        if not isinstance(json.loads(raw.decode('utf-8-sig')), dict):raise ValueError('Invalid character object')
        files.append((destination / local_id(name) / 'character.json', raw))
    if total_pixels > 128_000_000:raise ValueError('Catalog pixel budget exceeded')
    license_path = (root / 'LICENSE.md').resolve()
    if not license_path.is_relative_to(root) or not license_path.is_file() or license_path.stat().st_size > 65536:
        raise ValueError('Missing or unsafe art license')
    files.append((destination / 'LICENSE.md', license_path.read_bytes()))
    # Validate all source and destination paths before any mutation.
    for path, _ in files:
        if not path.resolve().is_relative_to(destination):raise ValueError('Destination escapes root')
    changed = []
    for path, raw in files:
        if not path.exists() or path.read_bytes() != raw:
            changed.append(path)
            if not check:atomic_bytes(path, raw)
    return {'files': len(files), 'images': len(files)-len(folders)-1, 'pixels': total_pixels,
            'changed': tuple(changed),
            'digest': hashlib.sha256(b''.join(hashlib.sha256(raw).digest() for _, raw in files)).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', type=Path, default=DEST)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args();result = import_assets(args.source, args.destination, check=args.check)
    print(f"Public art: {result['images']} images, {result['files']} files, {result['pixels']} source pixels, {len(result['changed'])} changed")
    return 1 if args.check and result['changed'] else 0


if __name__ == '__main__':raise SystemExit(main())
