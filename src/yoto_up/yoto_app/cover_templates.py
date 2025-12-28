"""
Template generator for card covers.

Provides:
- generate_html_template(title, image_url, template_name, width_px, height_px) -> str
- render_template(title, image_path, template_name, width_px, height_px) -> PIL.Image

The renderer will try to use WeasyPrint (HTML/CSS -> PNG) when available, otherwise falls back to a simple Pillow-based renderer that approximates layouts.
"""
from typing import Optional
import io
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:
    HAS_PIL = False


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: Optional[ImageFont.FreeTypeFont]):
    """Return (w,h) for rendered text using available measurement APIs."""
    try:
        if font is not None:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        else:
            # Some PILs support textbbox without font
            bbox = draw.textbbox((0, 0), text)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        try:
            if font is not None:
                return font.getsize(text)
        except Exception:
            pass
    return (0, 0)


def generate_html_template(title: str, image_url: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: str = "#f1c40f") -> str:
    """Return an HTML string for the requested template.

    image_url can be a file:// URL or a remote URL supported by the renderer.
    """
    # Basic safe escaping (minimal)
    safe_title = (title or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    footer = footer_text if footer_text is not None else Path(image_url).stem
    if template_name == "classic":
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
  .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', serif; background:white; position:relative; }}
  .title {{ position:absolute; top:6%; left:6%; right:6%; text-align:center; font-size:8vw; color:#111; font-weight:700; }}
  .hero {{ position:absolute; top:18%; left:6%; right:6%; bottom:18%; display:flex; align-items:center; justify-content:center; }}
  .hero img {{ max-width:100%; max-height:100%; object-fit:contain; border-radius:8px; }}
    .footer {{ position:absolute; bottom:4%; left:6%; right:6%; height:10%; background:{accent_color}; display:flex; align-items:center; justify-content:center; font-weight:700; color:#000; border-radius:6px; }}
</style>
</head>
<body>
  <div class="card">
    <div class="title">{safe_title}</div>
    <div class="hero"><img src="{image_url}" alt="cover"/></div>
    <div class="footer">{footer}</div>
  </div>
</body>
</html>
"""
    else:
        # simple modern template
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
  .card {{ width:100%; height:100%; background:linear-gradient(180deg,#ffffff,#e6f2ff); position:relative; font-family: Arial, Helvetica, sans-serif; }}
  .title {{ position:absolute; top:6%; left:8%; right:8%; text-align:left; font-size:6.5vw; color:#003366; font-weight:700; }}
  .hero {{ position:absolute; top:24%; left:8%; right:8%; bottom:20%; display:flex; align-items:center; justify-content:center; }}
  .hero img {{ max-width:100%; max-height:100%; object-fit:cover; border-radius:6px; box-shadow:0 6px 18px rgba(0,0,0,0.15); }}
    .footer {{ position:absolute; bottom:4%; left:8%; right:8%; height:8%; display:flex; align-items:center; justify-content:flex-end; font-weight:600; color:#333; }}
</style>
</head>
<body>
  <div class="card">
    <div class="title">{safe_title}</div>
    <div class="hero"><img src="{image_url}" alt="cover"/></div>
    <div class="footer">{footer}</div>
  </div>
</body>
</html>
"""
    return html


def render_template_with_pillow(title: str, image_path: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856):
    """Fallback renderer using Pillow. Returns PIL.Image (RGB).

    This creates a simple layout approximating the HTML templates.
    """
    if not HAS_PIL:
        raise RuntimeError("Pillow is required for fallback rendering")

    # Open and prepare hero image
    hero = Image.open(image_path).convert("RGBA")

    # Create base
    base = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(base)

    # Fonts
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(18, width_px // 10))
        font_footer = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(12, width_px // 20))
    except Exception:
        font_title = ImageFont.load_default()
        font_footer = ImageFont.load_default()

    # Allow passing footer and accent via image_path tuple hack if caller
    # passes them (backwards-compatible). Prefer explicit args when
    # render_template calls this function.
    footer = None
    accent = "#f1c40f"
    if isinstance(image_path, tuple) and len(image_path) == 3:
        # (image_path, footer_text, accent_color)
        image_path, footer, accent = image_path

    if template_name == "classic":
        # Title at top centered
        title_y = int(height_px * 0.06)
        hero_box = (int(width_px * 0.06), int(height_px * 0.15), int(width_px * 0.94), int(height_px * 0.78))
        footer_box_h = int(height_px * 0.08)
        footer_box = (int(width_px * 0.06), int(height_px * 0.78) + int(height_px * 0.02), int(width_px * 0.94), int(height_px * 0.78) + footer_box_h + int(height_px * 0.02))

        # Draw title
        w, h = _measure_text(draw, title, font_title)
        draw.text(((width_px - w) / 2, title_y), title, font=font_title, fill=(10,10,10))

        # Paste hero scaled to hero_box
        hw = hero_box[2] - hero_box[0]
        hh = hero_box[3] - hero_box[1]
        hero_thumb = hero.copy()
        hero_thumb.thumbnail((hw, hh), Image.LANCZOS)
        paste_x = hero_box[0] + (hw - hero_thumb.width)//2
        paste_y = hero_box[1] + (hh - hero_thumb.height)//2
        base.paste(hero_thumb.convert("RGB"), (paste_x, paste_y))

        # Footer band
        # Use provided footer or default to filename stem
        footer_text = footer if footer is not None else Path(image_path).stem
        # parse accent color hex to rgb
        try:
            a = accent.lstrip('#') if accent else "f1c40f"
            acc_rgb = tuple(int(a[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            acc_rgb = (241, 196, 15)
        draw.rectangle(footer_box, fill=acc_rgb)
        fw, fh = _measure_text(draw, footer_text, font_footer)
        draw.text((footer_box[0] + (footer_box[2]-footer_box[0]-fw)/2, footer_box[1] + (footer_box[3]-footer_box[1]-fh)/2), footer_text, font=font_footer, fill=(0,0,0))

    else:
        # modern template
        title_y = int(height_px * 0.06)
        draw.text((int(width_px * 0.08), title_y), title, font=font_title, fill=(0,51,102))
        hero_box = (int(width_px * 0.08), int(height_px * 0.24), int(width_px * 0.92), int(height_px * 0.80))
        hw = hero_box[2] - hero_box[0]
        hh = hero_box[3] - hero_box[1]
        hero_thumb = hero.copy()
        hero_thumb.thumbnail((hw, hh), Image.LANCZOS)
        paste_x = hero_box[0] + (hw - hero_thumb.width)//2
        paste_y = hero_box[1] + (hh - hero_thumb.height)//2
        base.paste(hero_thumb.convert("RGB"), (paste_x, paste_y))
    footer_text = footer if footer is not None else Path(image_path).stem
    fw, fh = _measure_text(draw, footer_text, font_footer)
    draw.text((int(width_px * 0.92) - fw, int(height_px * 0.92) - fh), footer_text, font=font_footer, fill=(50,50,50))

    return base


def render_template(title: str, image_path: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: Optional[str] = None):
    """Try to render using HTML+WeasyPrint; fall back to Pillow.

    Returns a PIL Image.
    """
    # Attempt to use weasyprint if installed
    try:
        from weasyprint import HTML
        html = generate_html_template(title, Path(image_path).as_uri(), template_name, width_px, height_px, footer_text=footer_text, accent_color=(accent_color or "#f1c40f"))
        # WeasyPrint can write to PNG directly via write_png
        png_bytes = HTML(string=html).write_png(stylesheets=None, presentational_hints=True)
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        return img
    except Exception:
        # Fall back
        if not HAS_PIL:
            raise RuntimeError("Neither WeasyPrint nor Pillow are available for template rendering")
        # Fall back: render_template_with_pillow accepts only positional
        # image_path currently; pass a tuple carrying footer/accent if
        # provided so the small fallback can access them without changing
        # too many call sites.
        ip = image_path
        if footer_text is not None or accent_color is not None:
            ip = (image_path, footer_text, accent_color or "#f1c40f")
        return render_template_with_pillow(title, ip, template_name, width_px, height_px)
