
import os
from pathlib import Path
import base64
import json
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR, YOTOICONS_CACHE_DIR

YOTO_ICON_CACHE_DIR = OFFICIAL_ICON_CACHE_DIR
YOTOICONS_CACHE_DIR = YOTOICONS_CACHE_DIR

YOTO_METADATA_FILE = YOTO_ICON_CACHE_DIR / 'icon_metadata.json'
USER_METADATA_FILE = YOTO_ICON_CACHE_DIR / 'user_icon_metadata.json'

YOTOICONS_METADATA_GLOBAL = YOTOICONS_CACHE_DIR / 'yotoicons_global_metadata.json'

#def list_icon_cache_files(cache_dir=".yoto_icon_cache"):
#    try:
#        files = [f for f in os.listdir(cache_dir) if f.endswith('.png')]
#        return sorted(files)
#    except Exception:
#        return []


def get_base64_from_path(path: Path) -> str:
    # If the path ends in .json we need to extract the image data
    if path.suffix.lower() == '.json':
        with path.open('r') as f:
            data = json.load(f)
            if "png_base64" in data:
                return data["png_base64"]
            elif "pixels" in data:
                img_data = data["pixels"]
                img_data = base64.b64encode(img_data).decode()
                return img_data

    with path.open('rb') as f:
        data = f.read()
        img_data = base64.b64encode(data).decode('utf-8')
    return img_data

def load_cached_icons() -> list[Path]:
    icons = []
    # official Yoto cached icons
    try:
        for f in YOTO_ICON_CACHE_DIR.glob('*.png'):
            icons.append(f)
    except Exception:
        pass
    # yotoicons cache
    try:
        for f in YOTOICONS_CACHE_DIR.glob('*.png'):
            icons.append(f)
    except Exception:
        pass
    return icons

def load_icon_as_pixels(path, size=16):
    from PIL import Image
    img = Image.open(path).convert('RGBA')
    try:
        resample = Image.Resampling.NEAREST
    except AttributeError:
        resample = Image.NEAREST
    img = img.resize((size, size), resample)
    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            px = img.getpixel((x, y))
            if isinstance(px, int):
                # grayscale
                r = g = b = px
                a = 255
            elif isinstance(px, tuple):
                if len(px) == 4:
                    r, g, b, a = px
                elif len(px) == 3:
                    r, g, b = px
                    a = 255
                else:
                    r = g = b = px[0]
                    a = 255
            else:
                r = g = b = 255
                a = 255
            # Preserve alpha: None for fully transparent, #RRGGBB for opaque, #RRGGBBAA for partial alpha
            if a == 0:
                row.append(None)
            elif a == 255:
                row.append('#{:02X}{:02X}{:02X}'.format(r, g, b))
            else:
                row.append('#{:02X}{:02X}{:02X}{:02X}'.format(r, g, b, a))
        pixels.append(row)
    return pixels


def path_is_official(path) -> bool:
    """Return True if the given path (str or Path) points to the official Yoto icon cache.

    Accepts pathlib.Path or str. Handles absolute and relative paths and checks both the
    configured YOTO_ICON_CACHE_DIR and any path parts containing '.yoto_icon_cache'.
    """
    try:
        p = Path(path)
    except Exception:
        return False
    # If configured cache dir is available, check containment
    try:
        if YOTO_ICON_CACHE_DIR and str(p).startswith(str(YOTO_ICON_CACHE_DIR)):
            return True
    except Exception:
        pass
    # Fallback: check for path part name
    try:
        return any(part == '.yoto_icon_cache' for part in p.parts)
    except Exception:
        return False


def path_is_yotoicons(path) -> bool:
    """Return True if the given path (str or Path) points to the YotoIcons cache."""
    try:
        p = Path(path)
    except Exception:
        return False
    try:
        if YOTOICONS_CACHE_DIR and str(p).startswith(str(YOTOICONS_CACHE_DIR)):
            return True
    except Exception:
        pass
    try:
        return any(part == '.yotoicons_cache' for part in p.parts)
    except Exception:
        return False


def source_label_for_path(path) -> str:
    """Return a human-friendly source label for a path: 'Official cache', 'YotoIcons', or 'Local'."""
    try:
        if path_is_official(path):
            return 'Official cache'
        if path_is_yotoicons(path):
            return 'YotoIcons'
    except Exception:
        pass
    return 'Local'
