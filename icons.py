from PIL import Image

# Global default horizontal scale for braille rendering. Change this to tune aspect ratio
# for your terminal. Common sane defaults: 1..4 (2 is a good starting point).
BRAILLE_X_SCALE = 2


def render_icon_braille(path, char_width: int = 8, char_height: int = 8, colored: bool = True, braille_x_scale: int | None = None):
    """
    Render an image as a grid of Unicode Braille characters.

    Each braille glyph encodes a 2x4 pixel block, so the input image is
    resized to (char_width*2*braille_x_scale, char_height*4). The glyph
    color is set to the average color of the opaque pixels in the block
    (if `colored` is True).
    """
    try:
        img = Image.open(path).convert("RGBA")

        # Apply horizontal scaling to correct terminal cell aspect ratio.
        # Each braille column maps to 2 horizontal pixels; braille_x_scale
        # replicates/aggregates extra horizontal pixels so rendered glyphs
        # appear closer to square in most terminals.
        if braille_x_scale is None:
            braille_x_scale = BRAILLE_X_SCALE
        target_w = max(1, char_width * 2 * max(1, braille_x_scale))
        target_h = max(1, char_height * 4)
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.Resampling.NEAREST)

        rows = []
        for cy in range(char_height):
            row = ""
            for cx in range(char_width):
                mask = 0
                colors = []
                # For each logical braille column (0..1) we aggregate
                # braille_x_scale source pixels horizontally to correct aspect.
                for col in range(2):
                    for py in range(4):
                        # Check the horizontal span for this braille column
                        any_opaque = False
                        col_colors = []
                        for sx in range(braille_x_scale):
                            x = cx * 2 * braille_x_scale + col * braille_x_scale + sx
                            y = cy * 4 + py
                            # Guard against bounds just in case
                            if x < img.width and y < img.height:
                                px = img.getpixel((x, y))
                                if isinstance(px, (tuple, list)) and len(px) >= 4:
                                    r, g, b, a = px[:4]
                                else:
                                    r, g, b, a = 255, 255, 255, 255
                                if a >= 128:
                                    any_opaque = True
                                    col_colors.append((r, g, b))
                        if any_opaque:
                            # map (col,py) to braille bit
                            if col == 0 and py == 0:
                                bit = 0x01
                            elif col == 0 and py == 1:
                                bit = 0x02
                            elif col == 0 and py == 2:
                                bit = 0x04
                            elif col == 0 and py == 3:
                                bit = 0x40
                            elif col == 1 and py == 0:
                                bit = 0x08
                            elif col == 1 and py == 1:
                                bit = 0x10
                            elif col == 1 and py == 2:
                                bit = 0x20
                            elif col == 1 and py == 3:
                                bit = 0x80
                            else:
                                bit = 0
                            mask |= bit
                            colors.extend(col_colors)
                if mask == 0:
                    row += " "
                else:
                    braille_char = chr(0x2800 + mask)
                    if colored and colors:
                        avg = tuple(sum(c[i] for c in colors) // len(colors) for i in range(3))
                        hexc = f"#{avg[0]:02x}{avg[1]:02x}{avg[2]:02x}"
                        row += f"[{hexc}]{braille_char}[/{hexc}]"
                    else:
                        row += braille_char
            rows.append(row)
        return "\n".join(rows)
    except Exception as e:
        return f"[red]Error rendering icon: {e}[/red]"


def render_icon(path, size: int = 16, small: bool = False, method: str = "blocks", braille_dims: tuple[int, int] = (8, 8), braille_x_scale: int | None = None):
    """
    Generic icon renderer.

    - method: "blocks" (default) uses colored background blocks.
              "braille" uses Unicode braille glyphs for higher detail.
    - small: when using blocks, renders a compact version (half resolution).
    - braille_dims: (char_width, char_height) for braille rendering.
    """
    if method == "braille":
        cw, ch = braille_dims
        return render_icon_braille(path, char_width=cw, char_height=ch, colored=True, braille_x_scale=braille_x_scale)

    # fallback to block-based rendering for backward compatibility
    try:
        img = Image.open(path).convert("RGBA")
        target = size
        if small:
            target = max(1, size // 2)
        if img.size != (target, target):
            img = img.resize((target, target), Image.Resampling.NEAREST)

        rows = []
        for y in range(img.height):
            row = ""
            for x in range(img.width):
                pixel = img.getpixel((x, y))
                if isinstance(pixel, (tuple, list)) and len(pixel) >= 4:
                    r, g, b, a = pixel[:4]
                else:
                    r, g, b, a = 255, 255, 255, 255
                if a < 128:
                    row += " " if small else "  "
                else:
                    hexc = f"#{r:02x}{g:02x}{b:02x}"
                    if small:
                        row += f"[{hexc}]█[/{hexc}]"
                    else:
                        row += f"[on {hexc}]  [/on {hexc}]"
            rows.append(row)
        return "\n".join(rows)
    except Exception as e:
        return f"[red]Error rendering icon: {e}[/red]"