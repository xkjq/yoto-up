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
    from PIL import ImageOps
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


def generate_html_template(title: str, image_url: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: str = "#f1c40f", title_style: str = "classic", image_fit: str = "scale", cover_full_bleed: bool = True, title_shadow: bool = False, title_font: Optional[str] = None, title_shadow_color: str = "#008000", top_blend_color: Optional[str] = None, bottom_blend_color: Optional[str] = None, top_blend_pct: float = 0.12, bottom_blend_pct: float = 0.12, title_color: str = "#111111", footer_style: str = "bar") -> str:
    """Return an HTML string for the requested template.

    image_url can be a file:// URL or a remote URL supported by the renderer.
    """
    # Basic safe escaping (minimal)
    safe_title = (title or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    footer = footer_text if footer_text is not None else Path(image_url).stem

    # Decide object-fit for hero image depending on image_fit / cover_full_bleed
    # If cover_full_bleed is requested we want the hero to cover the whole
    # card by default (background-style). Otherwise it will be contained
    # inside the hero box.
    if cover_full_bleed:
        object_fit = "cover"
    else:
        object_fit = "contain" if image_fit in ("scale", "resize") else "cover"

    # Title style tweaks - provide more visually distinct options
    title_font_size = "8vw"
    title_weight = "700"
    title_transform = "none"
    title_align = "center"
    title_extra_css = ""
    
    if title_style == "large":
        title_font_size = "10vw"
        title_weight = "900"
    elif title_style == "small":
        title_font_size = "6vw"
        title_weight = "600"
    elif title_style == "uppercase":
        title_font_size = "7vw"
        title_weight = "900"
        title_transform = "uppercase"
        title_extra_css = "letter-spacing: 2px;"
    elif title_style == "italic":
        title_font_size = "8.5vw"
        title_weight = "600"
        title_extra_css = "font-style: italic;"
    elif title_style == "bold":
        title_font_size = "9vw"
        title_weight = "900"
    elif title_style == "light":
        title_font_size = "8vw"
        title_weight = "300"
    elif title_style == "outline":
        title_font_size = "9vw"
        title_weight = "900"
        title_extra_css = "-webkit-text-stroke: 2px #000; -webkit-text-fill-color: transparent;"
    elif title_style == "condensed":
        title_font_size = "7vw"
        title_weight = "800"
        title_extra_css = "letter-spacing: -1px; transform: scaleX(0.85);"
    
    # Footer style options
    footer_display_css = ""
    if footer_style == "text":
        # Simple text footer, no bar
        footer_display_css = "background:transparent; height:auto; padding:8px 0;"
    elif footer_style == "badge":
        # Small badge-style footer
        footer_display_css = "background:{accent_color}; border-radius:20px; padding:6px 16px; height:auto; width:auto; margin:0 auto;"
    # Default "bar" style uses the existing styling

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

    # Title font and optional text-shadow
    title_font_css = ""
    if title_font:
        # use specified font name as family, fallback to DejaVuSans
        title_font_css = f"font-family: '{title_font}', 'DejaVuSans', serif;"
    title_shadow_css = ""
    if title_shadow:
        # multi-offset shadow similar to the requested style; allow custom color
        c = title_shadow_color
        # Build the list of offsets per the user's spec
        offsets = [
            "-1px 0",
            "0 1px",
            "1px 0",
            "0 -1px",
            "-8px 8px",
            "-7px 7px",
            "-6px 6px",
            "-5px 5px",
            "-4px 4px",
            "-3px 3px",
            "-2px 2px",
            "-1px 1px",
        ]
        title_shadow_css = "text-shadow: " + ", ".join([f"{off} {c}" for off in offsets]) + ";"

    if template_name == "classic":
        # When cover_full_bleed is True prefer using the image as the
        # card background so it covers the full card area; fall back to
        # the hero box when False.
        bg_css = ""
        if cover_full_bleed:
            bg_css = f"background: url('{image_url}') no-repeat center/cover;"

        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', serif; {bg_css} position:relative; }}
        .title {{ position:absolute; top:6%; left:6%; right:6%; text-align:{title_align}; font-size:{title_font_size}; color:{title_color}; font-weight:{title_weight}; text-transform:{title_transform}; {title_extra_css} {title_font_css} {title_shadow_css} }}
    .hero {{ position:absolute; top:18%; left:6%; right:6%; bottom:18%; display:flex; align-items:center; justify-content:center; }}
                        .hero img {{ width:100%; height:100%; object-fit:{object_fit}; border-radius:8px; }}
            .overlay {{ position:absolute; top:18%; left:6%; right:6%; bottom:18%; border-radius:8px; pointer-events:none; background: {overlay_css} rgba(0,0,0,0); }}
    .footer {{ position:absolute; bottom:4%; left:6%; right:6%; height:10%; background:{accent_color}; display:flex; align-items:center; justify-content:center; font-weight:700; color:#000; border-radius:6px; {footer_display_css} }}
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
                        text-transform:uppercase; letter-spacing:2px; color:#eaf6ff; text-shadow: 0 6px 18px rgba(6,40,80,0.45); {title_font_css} {title_shadow_css} }}
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
    elif template_name == "vintage":
        # Vintage/retro template: ornate border, serif title, aged paper feel
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', serif; position:relative; 
                     background: linear-gradient(135deg, #f5e6d3 0%, #e8d5b7 100%); 
                     border: 12px solid #8b7355; }}
    .title {{ position:absolute; top:8%; left:10%; right:10%; text-align:center; font-size:7vw; font-weight:700; 
                        color:#3a2f23; text-transform:capitalize; letter-spacing:1px; {title_font_css} {title_shadow_css} 
                        border-top: 2px solid #8b7355; border-bottom: 2px solid #8b7355; padding:8px 0; }}
    .hero {{ position:absolute; top:25%; left:10%; right:10%; bottom:25%; display:flex; align-items:center; justify-content:center;
                    border: 4px double #8b7355; background: {overlay_css} #fff; }}
        .hero img {{ width:100%; height:100%; object-fit:{object_fit}; }}
  .footer {{ position:absolute; bottom:6%; left:10%; right:10%; text-align:center; font-weight:600; 
                    color:#3a2f23; font-size:4.5vw; font-style:italic; }}
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
    elif template_name == "minimal":
        # Ultra minimal template: just image with subtle title overlay and thin accent line
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', sans-serif; position:relative; 
                     background: {overlay_css} url('{image_url}'); background-size: cover; background-position: center; }}
    .title {{ position:absolute; bottom:12%; left:6%; right:6%; text-align:left; font-size:7vw; font-weight:300; 
                        color:#ffffff; letter-spacing:2px; {title_font_css} {title_shadow_css} 
                        background: linear-gradient(90deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%);
                        padding: 12px 16px; }}
  .footer {{ position:absolute; bottom:6%; left:6%; right:6%; height:2px; background:{accent_color}; }}
</style>
</head>
<body>
  <div class="card">
    <div class="title">{safe_title}</div>
    <div class="footer"></div>
  </div>
</body>
</html>
"""
    elif template_name == "bold":
        # Bold geometric template: strong colors, geometric shapes, high contrast
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', sans-serif; position:relative; 
                     background: #000; }}
    .title-bar {{ position:absolute; top:0; left:0; right:0; height:18%; background:{accent_color}; 
                            display:flex; align-items:center; justify-content:center; clip-path: polygon(0 0, 100% 0, 100% 80%, 0 100%); }}
    .title {{ font-size:8vw; font-weight:900; color:#000; text-transform:uppercase; letter-spacing:1px; 
                    {title_font_css} {title_shadow_css} }}
    .hero {{ position:absolute; top:20%; left:4%; right:4%; bottom:16%; display:flex; align-items:center; justify-content:center;
                    background: {overlay_css} #fff; border: 4px solid {accent_color}; }}
        .hero img {{ width:100%; height:100%; object-fit:{object_fit}; }}
  .footer {{ position:absolute; bottom:0; left:0; right:0; height:14%; background:{accent_color}; 
                    display:flex; align-items:center; justify-content:center; font-weight:700; color:#000; 
                    font-size:5vw; clip-path: polygon(0 20%, 100% 0, 100% 100%, 0 100%); }}
</style>
</head>
<body>
  <div class="card">
    <div class="title-bar"><div class="title">{safe_title}</div></div>
    <div class="hero"><img src="{image_url}" alt="cover"/></div>
    <div class="footer">{footer}</div>
  </div>
</body>
</html>
"""
    elif template_name == "polaroid":
        # Polaroid/photo frame style: white border, centered image, handwritten-style caption
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', sans-serif; position:relative; 
                     background: {overlay_css} #e8e8e8; padding:6%; }}
    .polaroid {{ width:100%; height:100%; background:#fff; box-shadow: 0 8px 24px rgba(0,0,0,0.15); 
                        position:relative; padding:8% 8% 18% 8%; box-sizing:border-box; }}
    .title {{ position:absolute; top:2%; left:8%; right:8%; text-align:center; font-size:5.5vw; font-weight:400; 
                        color:#333; {title_font_css} {title_shadow_css} }}
    .hero {{ width:100%; height:100%; display:flex; align-items:center; justify-content:center; }}
        .hero img {{ max-width:100%; max-height:100%; object-fit:{object_fit}; }}
  .footer {{ position:absolute; bottom:4%; left:8%; right:8%; text-align:center; font-weight:400; 
                    color:#555; font-size:4.5vw; font-style:italic; }}
</style>
</head>
<body>
  <div class="card">
    <div class="polaroid">
      <div class="title">{safe_title}</div>
      <div class="hero"><img src="{image_url}" alt="cover"/></div>
      <div class="footer">{footer}</div>
    </div>
  </div>
</body>
</html>
"""
    elif template_name == "comic":
        # Comic book style: bold outlines, action lines, vibrant colors
        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @font-face {{ font-family: 'DejaVuSans'; src: local('DejaVu Sans'); }}
  html,body {{ margin:0; padding:0; width:100%; height:100%; }}
    .card {{ box-sizing:border-box; width:100%; height:100%; font-family: 'DejaVuSans', sans-serif; position:relative; 
                     background: radial-gradient(circle at 50% 50%, {accent_color} 0%, #000 100%); 
                     border: 8px solid #000; }}
    .title {{ position:absolute; top:8%; left:8%; right:8%; text-align:center; font-size:9vw; font-weight:900; 
                        color:{accent_color}; text-transform:uppercase; letter-spacing:1px; 
                        text-shadow: 3px 3px 0 #000, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000; 
                        {title_font_css} transform:rotate(-2deg); }}
    .hero {{ position:absolute; top:24%; left:8%; right:8%; bottom:20%; display:flex; align-items:center; justify-content:center;
                    border: 6px solid #000; background: {overlay_css} #fff; transform:rotate(1deg); 
                    box-shadow: 4px 4px 0 rgba(0,0,0,0.3); }}
        .hero img {{ width:100%; height:100%; object-fit:{object_fit}; }}
  .footer {{ position:absolute; bottom:6%; left:8%; right:8%; text-align:center; font-weight:900; 
                    color:#fff; font-size:5vw; text-transform:uppercase; 
                    text-shadow: 2px 2px 0 #000, -1px -1px 0 #000; }}
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
      .title {{ position:absolute; top:6%; left:8%; right:8%; text-align:left; font-size:6.5vw; color:#003366; font-weight:700; {title_font_css} {title_shadow_css} }}
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


def render_template_with_pillow(title: str, image_path: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: Optional[str] = None, title_style: str = "classic", image_fit: str = "scale", crop_position: str = "center", crop_offset_x: float = 0.0, crop_offset_y: float = 0.0, cover_full_bleed: bool = True, title_shadow: bool = False, title_font: Optional[str] = None, title_shadow_color: str = "#008000", top_blend_color: Optional[str] = None, bottom_blend_color: Optional[str] = None, top_blend_pct: float = 0.12, bottom_blend_pct: float = 0.12, title_color: str = "#111111", footer_style: str = "bar"):
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

    # If full-bleed requested, place a resized/cropped hero as the background
    # before any overlays/text so other items render on top.
    if cover_full_bleed:
        try:
            bg = ImageOps.fit(hero, (width_px, height_px), Image.LANCZOS, centering=(0.5, 0.5))
            base.paste(bg.convert("RGB"), (0, 0))
            background_applied = True
        except Exception:
            background_applied = False
    else:
        background_applied = False

    # Fonts - choose title font based on title_font argument when possible
    def _choose_title_font(name: Optional[str], size: int):
        candidates = []
        if name == "DejaVuSans" or name is None:
            candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        elif name == "LiberationSans":
            candidates = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
        elif name == "Arial":
            candidates = ["/usr/share/fonts/truetype/msttcorefonts/Arial.ttf", "/usr/share/fonts/truetype/msttcorefonts/arial.ttf"]
        else:
            candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]

        for fp in candidates:
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    font_title = _choose_title_font(title_font, max(18, width_px // 10))
    try:
        font_footer = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(12, width_px // 20))
    except Exception:
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

        # Draw title; support optional text shadow and title font selection
        w, h = _measure_text(draw, title, font_title)
        try:
            x = int((width_px - w) / 2)
            y = title_y
            if title_shadow:
                # Draw multiple shadow offsets as requested; allow custom color
                def _hex_to_rgba(hx: str, alpha: int = 255):
                    try:
                        a = hx.lstrip('#')
                        r = int(a[0:2], 16)
                        g = int(a[2:4], 16)
                        b = int(a[4:6], 16)
                        return (r, g, b, alpha)
                    except Exception:
                        return (0, 128, 0, alpha)

                shadow_color = _hex_to_rgba(title_shadow_color, 200)
                overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(overlay)
                # Small 1px offsets around to create crisp outline
                small_offsets = [(-1, 0), (0, 1), (1, 0), (0, -1), (-1, 1)]
                for ox, oy in small_offsets:
                    od.text((x + ox, y + oy), title, font=font_title, fill=shadow_color)
                # Larger cascading offsets for depth
                for d in range(8, 0, -1):
                    od.text((x - d, y + d), title, font=font_title, fill=_hex_to_rgba(title_shadow_color, max(40, 220 - d * 20)))
                base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
                # Recreate draw after compositing so further drawing targets the updated image
                draw = ImageDraw.Draw(base)
            draw.text((x, y), title, font=font_title, fill=(10, 10, 10))
        except Exception:
            draw.text(((width_px - w) / 2, title_y), title, font=font_title, fill=(10,10,10))

        # Decide where the hero image should be pasted. If cover_full_bleed is
        # requested, use the entire card as the target; otherwise use the
        # hero_box area inside the card.
        hero_target_box = hero_box
        if cover_full_bleed:
            hero_target_box = (0, 0, width_px, height_px)

        # Paste hero according to image_fit / cover_full_bleed
        hw = hero_target_box[2] - hero_target_box[0]
        hh = hero_target_box[3] - hero_target_box[1]
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

        # If hero_resized is a canvas with RGBA, convert before pasting
        if hero_resized.mode != "RGB":
            paste_img = hero_resized.convert("RGB")
        else:
            paste_img = hero_resized

        # Paste into the determined target box (hero_target_box) unless we
        # already applied the full-bleed background earlier; avoid covering
        # overlays/title/footer.
        if not (cover_full_bleed and background_applied):
            base.paste(paste_img, (hero_target_box[0], hero_target_box[1]))

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
                # Recreate draw after compositing so subsequent drawing (footer) uses the updated image
                draw = ImageDraw.Draw(base)
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
        # Draw title: support optional text-shadow and title font
        try:
            w, h = _measure_text(draw, title, font_title)
            x = int(width_px * 0.08)
            y = title_y
            if title_shadow:
                overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(overlay)
                shadow_off = (2, 2)
                od.text((x + shadow_off[0], y + shadow_off[1]), title, font=font_title, fill=(0, 0, 0, 160))
                base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
                draw = ImageDraw.Draw(base)
            draw.text((x, y), title, font=font_title, fill=(0,51,102))
        except Exception:
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


def render_template(title: str, image_path: str, template_name: str = "classic", width_px: int = 540, height_px: int = 856, footer_text: Optional[str] = None, accent_color: Optional[str] = None, title_style: str = "classic", image_fit: str = "scale", crop_position: str = "center", crop_offset_x: float = 0.0, crop_offset_y: float = 0.0, cover_full_bleed: bool = True, title_shadow: bool = False, title_font: Optional[str] = None, title_shadow_color: str = "#008000", top_blend_color: Optional[str] = None, bottom_blend_color: Optional[str] = None, top_blend_pct: float = 0.12, bottom_blend_pct: float = 0.12, title_color: str = "#111111", footer_style: str = "bar"):
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
        html = generate_html_template(
            title,
            Path(image_path).as_uri(),
            template_name,
            width_px,
            height_px,
            footer_text=footer_text,
            accent_color=(accent_color or "#f1c40f"),
            title_style=title_style,
            image_fit=image_fit,
            cover_full_bleed=cover_full_bleed,
            title_shadow=title_shadow,
            title_font=title_font,
            title_shadow_color=title_shadow_color,
            top_blend_color=top_blend_color,
            bottom_blend_color=bottom_blend_color,
            top_blend_pct=top_blend_pct,
            bottom_blend_pct=bottom_blend_pct,
            title_color=title_color,
            footer_style=footer_style,
        )
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
        return render_template_with_pillow(
            title,
            ip,
            template_name,
            width_px,
            height_px,
            footer_text=footer_text,
            accent_color=accent_color,
            title_style=title_style,
            image_fit=image_fit,
            crop_position=crop_position,
            crop_offset_x=crop_offset_x,
            crop_offset_y=crop_offset_y,
            cover_full_bleed=cover_full_bleed,
            title_shadow=title_shadow,
            title_font=title_font,
            title_shadow_color=title_shadow_color,
            top_blend_color=top_blend_color,
            bottom_blend_color=bottom_blend_color,
            top_blend_pct=top_blend_pct,
            bottom_blend_pct=bottom_blend_pct,
            title_color=title_color,
            footer_style=footer_style,
        )
