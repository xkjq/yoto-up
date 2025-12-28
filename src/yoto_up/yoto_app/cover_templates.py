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


def generate_html_template(title: str, image_url: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: str = "#f1c40f", title_style: str = "classic", image_fit: str = "scale", cover_full_bleed: bool = True, title_edge_stretch: bool = False, top_blend_color: Optional[str] = None, bottom_blend_color: Optional[str] = None, top_blend_pct: float = 0.12, bottom_blend_pct: float = 0.12) -> str:
    """Return an HTML string for the requested template.

    image_url can be a file:// URL or a remote URL supported by the renderer.
    """
    # Basic safe escaping (minimal)
    safe_title = (title or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    footer = footer_text if footer_text is not None else Path(image_url).stem

    # Decide object-fit for hero image depending on image_fit / cover_full_bleed
    if cover_full_bleed:
        object_fit = "cover"
    else:
        object_fit = "contain" if image_fit in ("scale", "resize") else "cover"

    # Title style tweaks
    title_font_size = "8vw"
    title_color = "#111"
    if title_style == "large":
        title_font_size = "10vw"
    elif title_style == "small":
        title_font_size = "6vw"

    # Build optional overlay (top/bottom blend) CSS if requested
    overlay_css = ""
    try:
        if top_blend_color or bottom_blend_color:
            top_c = top_blend_color or "transparent"
            bottom_c = bottom_blend_color or "transparent"
            # ensure percentages are reasonable
            tp = max(0.0, min(1.0, float(top_blend_pct))) * 100
            bp = max(0.0, min(1.0, float(bottom_blend_pct))) * 100
            # Create a gradient that blends to transparent in the middle
            overlay_css = f"linear-gradient(to bottom, {top_c} {tp}%, rgba(0,0,0,0) {tp + 0.5}%, rgba(0,0,0,0) {100 - bp - 0.5}%, {bottom_c} 100%), "
    except Exception:
        overlay_css = ""

    # Title transform for edge-stretch effect
    title_transform_css = ""
    if title_edge_stretch:
        title_transform_css = "transform: scaleY(1.35);"

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
    .title {{ position:absolute; top:6%; left:6%; right:6%; text-align:center; font-size:{title_font_size}; color:{title_color}; font-weight:700; }}
  .hero {{ position:absolute; top:18%; left:6%; right:6%; bottom:18%; display:flex; align-items:center; justify-content:center; }}
            .hero img {{ max-width:100%; max-height:100%; object-fit:{object_fit}; border-radius:8px; }}
            .overlay {{ position:absolute; top:18%; left:6%; right:6%; bottom:18%; border-radius:8px; pointer-events:none; background: {overlay_css} rgba(0,0,0,0); }}
    .footer {{ position:absolute; bottom:4%; left:6%; right:6%; height:10%; background:{accent_color}; display:flex; align-items:center; justify-content:center; font-weight:700; color:#000; border-radius:6px; }}
</style>
</head>
<body>
  <div class="card">
    <div class="title">{safe_title}</div>
    <div class="hero"><img src="{image_url}" alt="cover"/></div>
        <div class="overlay"></div>
    <div class="footer">{footer}</div>
  </div>
</body>
</html>
"""
    elif template_name == "frozen":
        # Frozen-like icy template: large uppercase title with subtle shadow,
        # icy gradient background, large hero area and small footer.
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', serif; position:relative; 
                     background: {overlay_css} url('{image_url}'); background-size: cover; background-position: center; color: #eaf6ff; }}
    .title {{ position:absolute; top:4%; left:6%; right:6%; text-align:center; font-size:10vw; font-weight:900; 
                        text-transform:uppercase; letter-spacing:2px; color:#eaf6ff; text-shadow: 0 6px 18px rgba(6,40,80,0.45); {title_transform_css} }}
    .hero {{ position:absolute; top:18%; left:6%; right:6%; bottom:18%; display:flex; align-items:center; justify-content:center; }}
        .hero img {{ width:100%; height:100%; object-fit:{object_fit}; border-radius:10px; box-shadow: 0 18px 48px rgba(6,40,80,0.28); opacity:0.98; }}
  .footer {{ position:absolute; bottom:4%; left:6%; right:6%; height:8%; display:flex; align-items:center; justify-content:center; font-weight:700; color:#08384a; background: rgba(255,255,255,0.6); border-radius:6px; }}
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
        .hero img {{ max-width:100%; max-height:100%; object-fit:{object_fit}; border-radius:6px; box-shadow:0 6px 18px rgba(0,0,0,0.15); }}
        .overlay {{ position:absolute; top:24%; left:8%; right:8%; bottom:20%; border-radius:6px; pointer-events:none; background: {overlay_css} rgba(0,0,0,0); }}
    .footer {{ position:absolute; bottom:4%; left:8%; right:8%; height:8%; display:flex; align-items:center; justify-content:flex-end; font-weight:600; color:#333; }}
</style>
</head>
<body>
  <div class="card">
    <div class="title">{safe_title}</div>
    <div class="hero"><img src="{image_url}" alt="cover"/></div>
        <div class="overlay"></div>
    <div class="footer">{footer}</div>
  </div>
</body>
</html>
"""
    return html


def render_template_with_pillow(title: str, image_path: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: Optional[str] = None, title_style: str = "classic", image_fit: str = "scale", crop_position: str = "center", crop_offset_x: float = 0.0, crop_offset_y: float = 0.0, cover_full_bleed: bool = True, title_edge_stretch: bool = False, top_blend_color: Optional[str] = None, bottom_blend_color: Optional[str] = None, top_blend_pct: float = 0.12, bottom_blend_pct: float = 0.12):
    """Fallback renderer using Pillow. Returns PIL.Image (RGB).

    This creates a simple layout approximating the HTML templates.
    """
    if not HAS_PIL:
        raise RuntimeError("Pillow is required for fallback rendering")

    # Determine footer and accent defaults (allow override via kwargs)
    footer = footer_text
    accent = accent_color or "#f1c40f"

    # Backwards-compatible tuple hack: callers may pass (image_path, footer, accent)
    if isinstance(image_path, tuple) and len(image_path) >= 1:
        try:
            # Unpack tuple; prefer explicit kwargs if provided
            ipath = image_path[0]
            t_footer = image_path[1] if len(image_path) > 1 else None
            t_accent = image_path[2] if len(image_path) > 2 else None
            image_path = ipath
            if footer is None and t_footer is not None:
                footer = t_footer
            if (accent_color is None or accent_color == "") and t_accent is not None:
                accent = t_accent
        except Exception:
            # defensive: fall back to first element
            image_path = image_path[0]

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

    # footer and accent were already determined above (either from kwargs
    # or from a tuple passed as image_path). Ensure we have sensible defaults
    # for later drawing.
    if footer is None:
        footer = Path(image_path).stem
    if not accent:
        accent = "#f1c40f"

    # Title styling
    title_font_size = max(18, width_px // 10)
    if title_style == "large":
        title_font_size = max(title_font_size, width_px // 8)
    elif title_style == "small":
        title_font_size = max(12, width_px // 12)

    if template_name == "classic":
        # Title at top centered
        title_y = int(height_px * 0.06)
        hero_box = (int(width_px * 0.06), int(height_px * 0.15), int(width_px * 0.94), int(height_px * 0.78))
        footer_box_h = int(height_px * 0.08)
        footer_box = (int(width_px * 0.06), int(height_px * 0.78) + int(height_px * 0.02), int(width_px * 0.94), int(height_px * 0.78) + footer_box_h + int(height_px * 0.02))

        # Draw title
        w, h = _measure_text(draw, title, font_title)
        draw.text(((width_px - w) / 2, title_y), title, font=font_title, fill=(10,10,10))

        # Paste hero according to image_fit / cover_full_bleed
        hw = hero_box[2] - hero_box[0]
        hh = hero_box[3] - hero_box[1]
        hero_thumb = hero.copy()

        # Decide behaviour: resize (stretch), scale (contain) or crop (cover)
        fit = image_fit or "scale"
        if cover_full_bleed:
            fit = "crop"

        if fit == "resize":
            hero_resized = hero_thumb.resize((hw, hh), Image.LANCZOS)
        elif fit == "scale":
            # contain
            hero_resized = hero_thumb.copy()
            hero_resized.thumbnail((hw, hh), Image.LANCZOS)
            # create canvas same size and paste centered
            canvas = Image.new("RGBA", (hw, hh), (255,255,255,0))
            paste_x = (hw - hero_resized.width)//2
            paste_y = (hh - hero_resized.height)//2
            canvas.paste(hero_resized, (paste_x, paste_y))
            hero_resized = canvas
        else:
            # crop / cover behaviour
            target_ratio = hw / hh if hh > 0 else 1.0
            img_ratio = hero_thumb.width / hero_thumb.height if hero_thumb.height > 0 else 1.0

            if img_ratio > target_ratio:
                # Image wider than target: crop width
                new_height = hero_thumb.height
                new_width = int(new_height * target_ratio)
            else:
                new_width = hero_thumb.width
                new_height = int(new_width / target_ratio)

            # Determine crop origin using crop_position and offsets
            # crop_position can be 'center','top','bottom','left','right', etc.
            cp = (crop_position or "center")
            if cp == "center":
                left = (hero_thumb.width - new_width)//2
                top = (hero_thumb.height - new_height)//2
            elif cp == "top":
                left = (hero_thumb.width - new_width)//2
                top = 0
            elif cp == "bottom":
                left = (hero_thumb.width - new_width)//2
                top = hero_thumb.height - new_height
            elif cp == "left":
                left = 0
                top = (hero_thumb.height - new_height)//2
            elif cp == "right":
                left = hero_thumb.width - new_width
                top = (hero_thumb.height - new_height)//2
            elif cp == "top_left":
                left = 0
                top = 0
            elif cp == "top_right":
                left = hero_thumb.width - new_width
                top = 0
            elif cp == "bottom_left":
                left = 0
                top = hero_thumb.height - new_height
            elif cp == "bottom_right":
                left = hero_thumb.width - new_width
                top = hero_thumb.height - new_height
            else:
                left = (hero_thumb.width - new_width)//2
                top = (hero_thumb.height - new_height)//2

            # Apply offsets (-1..1) relative to available movement
            max_offset_x = max(0, (hero_thumb.width - new_width)//2)
            max_offset_y = max(0, (hero_thumb.height - new_height)//2)
            try:
                left += int(crop_offset_x * max_offset_x)
                top += int(crop_offset_y * max_offset_y)
            except Exception:
                pass

            left = max(0, min(left, hero_thumb.width - new_width))
            top = max(0, min(top, hero_thumb.height - new_height))

            cropped = hero_thumb.crop((left, top, left + new_width, top + new_height))
            hero_resized = cropped.resize((hw, hh), Image.LANCZOS)

        # If hero_resized is a canvas with RGBA, paste it centered into base at hero_box
        if hero_resized.mode != "RGB":
            paste_img = hero_resized.convert("RGB")
        else:
            paste_img = hero_resized

        # For scale mode where hero_resized is exactly hw x hh we paste at hero_box origin
        base.paste(paste_img, (hero_box[0], hero_box[1]))

        # Apply optional top/bottom blend overlays (fade image into a solid colour)
        def _hex_to_rgb(hx: Optional[str], fallback=(255,255,255)):
            try:
                if not hx:
                    return fallback
                a = hx.lstrip('#')
                return tuple(int(a[i:i+2], 16) for i in (0, 2, 4))
            except Exception:
                return fallback

        try:
            tb_rgb = _hex_to_rgb(top_blend_color)
            bb_rgb = _hex_to_rgb(bottom_blend_color)
            # Only draw if colours were provided
            if top_blend_color or bottom_blend_color:
                overlay = Image.new('RGBA', (width_px, height_px), (0,0,0,0))
                o_draw = ImageDraw.Draw(overlay)
                # Top gradient
                h_top = int(height_px * max(0.0, min(1.0, float(top_blend_pct))))
                for i in range(h_top):
                    alpha = int(255 * (1.0 - (i / max(1, h_top))))
                    col = (tb_rgb[0], tb_rgb[1], tb_rgb[2], alpha)
                    o_draw.line([(0, i), (width_px, i)], fill=col)
                # Bottom gradient
                h_bot = int(height_px * max(0.0, min(1.0, float(bottom_blend_pct))))
                for j in range(h_bot):
                    y = height_px - 1 - j
                    alpha = int(255 * (1.0 - (j / max(1, h_bot))))
                    col = (bb_rgb[0], bb_rgb[1], bb_rgb[2], alpha)
                    o_draw.line([(0, y), (width_px, y)], fill=col)
                base = Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')
        except Exception:
            pass

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
        fit = image_fit or "scale"
        if cover_full_bleed:
            fit = "crop"
        if fit == "resize":
            hero_resized = hero_thumb.resize((hw, hh), Image.LANCZOS)
        elif fit == "scale":
            hero_resized = hero_thumb.copy()
            hero_resized.thumbnail((hw, hh), Image.LANCZOS)
            canvas = Image.new("RGBA", (hw, hh), (255,255,255,0))
            canvas.paste(hero_resized, ((hw - hero_resized.width)//2, (hh - hero_resized.height)//2))
            hero_resized = canvas
        else:
            # crop
            target_ratio = hw / hh if hh > 0 else 1.0
            img_ratio = hero_thumb.width / hero_thumb.height if hero_thumb.height > 0 else 1.0
            if img_ratio > target_ratio:
                new_height = hero_thumb.height
                new_width = int(new_height * target_ratio)
            else:
                new_width = hero_thumb.width
                new_height = int(new_width / target_ratio)
            left = (hero_thumb.width - new_width)//2
            top = (hero_thumb.height - new_height)//2
            cropped = hero_thumb.crop((left, top, left + new_width, top + new_height))
            hero_resized = cropped.resize((hw, hh), Image.LANCZOS)
        base.paste(hero_resized.convert("RGB"), (hero_box[0], hero_box[1]))
    footer_text = footer if footer is not None else Path(image_path).stem
    fw, fh = _measure_text(draw, footer_text, font_footer)
    draw.text((int(width_px * 0.92) - fw, int(height_px * 0.92) - fh), footer_text, font=font_footer, fill=(50,50,50))

    return base


def render_template(title: str, image_path: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: Optional[str] = None, title_style: str = "classic", image_fit: str = "scale", crop_position: str = "center", crop_offset_x: float = 0.0, crop_offset_y: float = 0.0, cover_full_bleed: bool = True):
    """Try to render using HTML+WeasyPrint; fall back to Pillow.

    Returns a PIL Image.
    """
    # Allow callers to pass a tuple (image_path, footer, accent) and honour it
    if isinstance(image_path, tuple) and len(image_path) >= 1:
        try:
            # unpack but don't override explicit kwargs unless not set
            ipath, ip_footer, ip_accent = image_path
            image_path = ipath
            if footer_text is None:
                footer_text = ip_footer
            if accent_color is None:
                accent_color = ip_accent
        except Exception:
            # keep image_path as-is if unpack fails
            pass

    # Attempt to use weasyprint if installed
    try:
        from weasyprint import HTML
        html = generate_html_template(title, Path(image_path).as_uri(), template_name, width_px, height_px, footer_text=footer_text, accent_color=(accent_color or "#f1c40f"), title_style=title_style, image_fit=image_fit, cover_full_bleed=cover_full_bleed)
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
        return render_template_with_pillow(title, ip, template_name, width_px, height_px, footer_text=footer_text, accent_color=accent_color, title_style=title_style, image_fit=image_fit, crop_position=crop_position, crop_offset_x=crop_offset_x, crop_offset_y=crop_offset_y, cover_full_bleed=cover_full_bleed)
