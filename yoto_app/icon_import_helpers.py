
import os

def list_icon_cache_files(cache_dir=".yoto_icon_cache"):
    try:
        files = [f for f in os.listdir(cache_dir) if f.endswith('.png')]
        return sorted(files)
    except Exception:
        return []

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
            if a < 128:
                row.append('#FFFFFF')
            else:
                row.append('#{:02X}{:02X}{:02X}'.format(r, g, b))
        pixels.append(row)
    return pixels
