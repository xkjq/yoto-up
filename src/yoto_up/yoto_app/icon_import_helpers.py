
from pathlib import Path
import base64
import hashlib
import json
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR, YOTOICONS_CACHE_DIR
from loguru import logger
from PIL import Image as PILImage
import io

# Directory for generated thumbnails (kept inside the official cache dir)
THUMBNAIL_DIR = OFFICIAL_ICON_CACHE_DIR / "thumbnails"
try:
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

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


def get_thumbnail_path(path: Path, size: int = 64) -> str:
    """Return a filesystem path to a thumbnail PNG for `path`.

    If thumbnail doesn't exist, generate it. Returns a string suitable for
    `ft.Image(src=...)`. On failure returns a data URL containing base64 image
    data as a fallback.
    """
    try:
        p = Path(path)
    except Exception:
        return str(path)

    # create deterministic filename for thumbnail
    try:
        key = hashlib.sha256(str(p).encode()).hexdigest()[:12]
        thumb_name = f"{key}_{size}.png"
        thumb_path = THUMBNAIL_DIR / thumb_name
    except Exception:
        thumb_path = THUMBNAIL_DIR / (p.stem + f"_{size}.png")

    if thumb_path.exists():
        return str(thumb_path.resolve())

    # generate thumbnail
    try:
        if p.suffix.lower() == ".json":
            # try to extract embedded png_base64 or pixels
            try:
                data = json.loads(p.read_text(encoding="utf-8") or "{}")
                b64 = None
                if "png_base64" in data:
                    b64 = data["png_base64"]
                elif "pixels" in data:
                    # pixels -> construct an image
                    # fallback: cannot handle here
                    b64 = None
                if b64:
                    raw = base64.b64decode(b64)
                    img = PILImage.open(io.BytesIO(raw)).convert("RGBA")
                else:
                    # fallback to reading via get_base64_from_path
                    b64str = get_base64_from_path(p)
                    raw = base64.b64decode(b64str)
                    img = PILImage.open(io.BytesIO(raw)).convert("RGBA")
            except Exception:
                # give up
                raise
        else:
            img = PILImage.open(p).convert("RGBA")
            # If the source image is already small enough, just use it directly
            try:
                w, h = img.size
                if max(w, h) <= size:
                    return str(p.resolve())
            except Exception:
                pass

        # resize preserving aspect ratio
        resample = PILImage.Resampling.LANCZOS
        img.thumbnail((size, size), resample)
        img.save(thumb_path, format="PNG")
        return str(thumb_path.resolve())
    except Exception as e:
        logger.debug(f"Failed to create thumbnail for {path}: {e}")
        try:
            b64 = get_base64_from_path(p)
            return f"data:image/png;base64,{b64}"
        except Exception:
            return str(path)

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
    resample = Image.Resampling.NEAREST
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
