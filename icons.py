from PIL import Image

def render_icon(path):
    try:
        img = Image.open(path).convert("RGBA")
        # Always resize to 16x16 before rendering
        if img.size != (16, 16):
            img = img.resize((16, 16), Image.Resampling.NEAREST)
        # Render as block art: use colored blocks for each pixel
        rows = []
        for y in range(img.height):
            row = ""
            for x in range(img.width):
                pixel = img.getpixel((x, y))
                if isinstance(pixel, (tuple, list)) and len(pixel) == 4:
                    r, g, b, a = pixel
                else:
                    # fallback: treat as opaque white
                    r, g, b, a = 255, 255, 255, 255
                if a < 128:
                    row += "  "
                else:
                    row += f"[on #{r:02x}{g:02x}{b:02x}]  [/on #{r:02x}{g:02x}{b:02x}]"
            rows.append(row)
        return "\n".join(rows)
    except Exception as e:
        return f"[red]Error rendering icon: {e}[/red]"