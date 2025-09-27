
import os
from pathlib import Path

YOTO_ICON_CACHE_DIR = Path(os.getenv("FLET_APP_STORAGE_DATA"))/Path(".yoto_icon_cache")
YOTOICONS_CACHE_DIR = Path(os.getenv("FLET_APP_STORAGE_DATA"))/Path(".yotoicons_cache")

YOTO_METADATA_FILE = YOTO_ICON_CACHE_DIR / 'icon_metadata.json'
USER_METADATA_FILE = YOTO_ICON_CACHE_DIR / 'user_icon_metadata.json'

YOTOICONS_METADATA_GLOBAL = YOTOICONS_CACHE_DIR / 'yotoicons_global_metadata.json'

#def list_icon_cache_files(cache_dir=".yoto_icon_cache"):
#    try:
#        files = [f for f in os.listdir(cache_dir) if f.endswith('.png')]
#        return sorted(files)
#    except Exception:
#        return []
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
