import os
import json
import tempfile
import base64
import io
import copy
import flet as ft
from loguru import logger
from PIL import Image


STAMP_DIALOG = None

project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
stamps_dir = os.path.join(project_dir, '.stamps')

def open_image_stamp_dialog(editor, e):
    """Open the stamp image dialog using the provided editor instance.

    This function was extracted from PixelArtEditor._open_image_stamp_dialog
    and adapted to operate on the passed `editor` object.
    """
    page = e.page if hasattr(e, 'page') else None
    saved_dir = editor._ensure_saved_dir()

    files = []
    status = ft.Text("")
    preview = ft.Image(width=64, height=64, fit=ft.ImageFit.CONTAIN)
    preview_applied = ft.Image(width=64, height=64, fit=ft.ImageFit.CONTAIN)

    # gather file list
    try:
        if stamps_dir and os.path.isdir(stamps_dir):
            for fn in os.listdir(stamps_dir):
                if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                    files.append(os.path.join('.stamps', fn))
    except Exception:
        pass
    try:
        if saved_dir:
            sd = str(saved_dir) if hasattr(saved_dir, 'as_posix') else saved_dir
            for fn in os.listdir(sd):
                if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                    if fn not in [os.path.basename(f) for f in files]:
                        files.append(fn)
    except Exception:
        logger.exception("Error listing saved icons for stamp dialog")

    if not files:
        status.value = "No saved small icons found in .stamps or saved_icons"
        content = ft.Column([status], spacing=8)
        dlg = ft.AlertDialog(title=ft.Text("Stamp Image"), content=content, actions=[ft.TextButton("OK", on_click=lambda ev: page.close(dlg))], open=False)
        STAMP_DIALOG = dlg
        if page:
            page.open(dlg)
        return

    # build dropdown
    dropdown_options = []
    option_map = {}
    for f in files:
        if str(f).startswith('.stamps' + os.sep) or str(f).startswith('.stamps/'):
            label = f"[stamps] {os.path.basename(f)}"
            value = f
        else:
            label = os.path.basename(f)
            value = f
        option_map[label] = value
        dropdown_options.append(ft.dropdown.Option(label))

    dropdown = ft.Dropdown(label="Image file", options=dropdown_options, width=320)
    stamp_grid = ft.Column(spacing=6)
    gallery_dialog = None

    def select_stamp(label, ev=None):
        logger.debug(f"select_stamp: label={label} ev={ev}")
        try:
            dropdown.value = label
            try:
                dropdown.update()
            except Exception:
                pass
            try:
                on_select(None)
            except Exception:
                pass
        except Exception:
            pass

        page = ev.page if ev and hasattr(ev, 'page') else None
        page.open(STAMP_DIALOG)

        

    def build_stamp_grid():
        try:
            stamp_grid.controls.clear()
        except Exception:
            pass
        import tempfile as _temp
        per_row = 6
        row = []
        for f in files:
            try:
                if str(f).startswith('.stamps' + os.sep) or str(f).startswith('.stamps/'):
                    p = os.path.join(project_dir, f)
                    label = f"[stamps] {os.path.basename(f)}"
                else:
                    label = os.path.basename(f)
                    p = os.path.join(str(saved_dir), f) if saved_dir and not os.path.isabs(f) else f
                if not p or not os.path.exists(p):
                    continue

                thumb_img = None
                try:
                    if p.lower().endswith('.json'):
                        with open(p, 'r', encoding='utf-8') as _fh:
                            _obj = json.load(_fh)
                        if isinstance(_obj, dict) and _obj.get('png_base64'):
                            b = base64.b64decode(_obj['png_base64'])
                            thumb_img = Image.open(io.BytesIO(b)).convert('RGBA')
                        elif isinstance(_obj, dict) and 'pixels' in _obj and isinstance(_obj['pixels'], list):
                            try:
                                thumb_img = editor._pixels_to_image(_obj['pixels']).convert('RGBA')
                            except Exception:
                                thumb_img = None
                        else:
                            thumb_img = None
                    else:
                        thumb_img = Image.open(p).convert('RGBA')
                except Exception:
                    thumb_img = None

                if thumb_img is None:
                    continue

                try:
                    resample = Image.Resampling.LANCZOS
                except Exception:
                    resample = Image.BICUBIC if hasattr(Image, 'BICUBIC') else Image.NEAREST
                thumb = thumb_img.resize((48, 48), resample)
                tmpf = _temp.NamedTemporaryFile(suffix='.png', delete=False)
                thumb.save(tmpf.name)

                img_widget = ft.Image(src=tmpf.name, width=48, height=48, fit=ft.ImageFit.CONTAIN)
                try:
                    img_ctrl = ft.Container(content=img_widget, width=48, height=48, on_click=lambda ev, lbl=label: select_stamp(lbl, ev))
                except Exception:
                    try:
                        img_ctrl = ft.GestureDetector(content=img_widget, on_tap=lambda ev, lbl=label: select_stamp(lbl, ev))
                    except Exception:
                        img_ctrl = img_widget

                col = ft.Column([img_ctrl, ft.Text(label, width=64, max_lines=1)], spacing=2)
                row.append(col)
                if len(row) >= per_row:
                    stamp_grid.controls.append(ft.Row(row, spacing=8))
                    row = []
            except Exception:
                logger.exception(f"Error creating thumbnail for stamp {f}")
        if row:
            stamp_grid.controls.append(ft.Row(row, spacing=8))
        try:
            if getattr(editor, 'page', None) and getattr(editor.page, 'dialog', None):
                try:
                    stamp_grid.update()
                except Exception:
                    pass
        except Exception:
            pass

    try:
        build_stamp_grid()
    except Exception:
        pass

    def open_stamp_gallery(ev):
        try:
            nonlocal gallery_dialog
            page_local = ev.page if hasattr(ev, 'page') else None
            build_stamp_grid()
            gallery_content = ft.Column([stamp_grid], spacing=8, width=420)
            dlg_gallery = ft.AlertDialog(title=ft.Text("Stamp Gallery"), content=gallery_content, actions=[ft.TextButton("Close", on_click=lambda e: page_local.close(dlg_gallery))], open=False)
            try:
                dlg_gallery._origin_page = page_local
            except Exception:
                pass
            try:
                dlg_gallery._parent_dialog = dlg
            except Exception:
                pass
            gallery_dialog = dlg_gallery
            if page_local:
                page_local.open(dlg_gallery)
        except Exception:
            logger.exception("Error opening stamp gallery dialog")

    import_btn = ft.ElevatedButton("Import sprite sheet", on_click=lambda ev: open_import_dialog(ev))
    pos_x = ft.TextField(label="X (left)", value="0", width=80)
    pos_y = ft.TextField(label="Y (top)", value="0", width=80)
    opaque_only = ft.Checkbox(label="Ignore transparent pixels (stamp only opaque)", value=False)
    scale_options_main = ['0.25','0.5','0.75','1','2','3','4']
    scale_dropdown = ft.Dropdown(label="Scale", options=[ft.dropdown.Option(s) for s in scale_options_main], value='1', width=100)
    chroma_checkbox = ft.Checkbox(label="Make chosen color transparent (chroma)", value=False)
    chroma_color_field = ft.TextField(label="Chroma color (hex)", value="#FFFFFF", width=100)

    def open_chroma_picker(ev):
        page_local = ev.page if hasattr(ev, 'page') else None
        def on_chroma_selected(hex_color):
            chroma_color_field.value = hex_color
            chroma_color_field.update()
            try:
                on_select(None)
            except Exception:
                pass
        try:
            from yoto_app.colour_picker import ColourPicker
            picker = ColourPicker(current_color=chroma_color_field.value, saved_dir=editor._ensure_saved_dir(), on_color_selected=on_chroma_selected)
            dialog = picker.build_dialog(page=page_local, caller_page_dialog=page_local.dialog if page_local else None)
            if page_local and dialog:
                page_local.open(dialog)
        except Exception:
            pass

    chroma_picker_btn = ft.TextButton("Pick", on_click=open_chroma_picker)
    chroma_checkbox.on_change = lambda ev: on_select(None)
    chroma_color_field.on_change = lambda ev: on_select(None)

    positions = [
        "Top Left", "Top Center", "Top Right",
        "Middle Left", "Center", "Middle Right",
        "Bottom Left", "Bottom Center", "Bottom Right"
    ]

    def get_stamp_size_from_pixels(pixels):
        h = len(pixels)
        w = max((len(r) for r in pixels), default=0)
        return w, h

    def set_position(pos):
        grid_size = editor.size
        v = dropdown.value
        mapped = option_map.get(v, v) if v else None
        stamp_w = stamp_h = 0
        try:
            if mapped:
                if str(mapped).startswith('.stamps' + os.sep) or str(mapped).startswith('.stamps/'):
                    p = os.path.join(project_dir, mapped)
                else:
                    p = os.path.join(str(saved_dir), mapped) if saved_dir else mapped
                if p and os.path.exists(p):
                    try:
                        sf = float(scale_dropdown.value)
                    except Exception:
                        sf = 1.0
                    pixels_for_size = load_pixels_for_stamp(p, sf)
                    if pixels_for_size:
                        w, h = get_stamp_size_from_pixels(pixels_for_size)
                        stamp_w, stamp_h = w, h
                    else:
                        if p.lower().endswith('.png'):
                            img = Image.open(p).convert('RGBA')
                            w, h = img.size
                            stamp_w, stamp_h = int(round(w * sf)), int(round(h * sf))
                        else:
                            with open(p, 'r', encoding='utf-8') as fh:
                                obj = json.load(fh)
                            if isinstance(obj, dict) and 'pixels' in obj:
                                w, h = get_stamp_size_from_pixels(obj['pixels'])
                                stamp_w, stamp_h = int(round(w * sf)), int(round(h * sf))
        except Exception:
            stamp_w, stamp_h = 0, 0

        if pos == "Top Left":
            x = 0
            y = 0
        elif pos == "Top Center":
            x = max((grid_size - stamp_w)//2, 0)
            y = 0
        elif pos == "Top Right":
            x = max(grid_size - stamp_w, 0)
            y = 0
        elif pos == "Middle Left":
            x = 0
            y = max((grid_size - stamp_h)//2, 0)
        elif pos == "Center":
            x = max((grid_size - stamp_w)//2, 0)
            y = max((grid_size - stamp_h)//2, 0)
        elif pos == "Middle Right":
            x = max(grid_size - stamp_w, 0)
            y = max((grid_size - stamp_h)//2, 0)
        elif pos == "Bottom Left":
            x = 0
            y = max(grid_size - stamp_h, 0)
        elif pos == "Bottom Center":
            x = max((grid_size - stamp_w)//2, 0)
            y = max(grid_size - stamp_h, 0)
        elif pos == "Bottom Right":
            x = max(grid_size - stamp_w, 0)
            y = max(grid_size - stamp_h, 0)
        else:
            x = 0
            y = 0
        pos_x.value = str(x)
        pos_y.value = str(y)
        pos_x.update()
        pos_y.update()
        try:
            on_select(None)
        except Exception:
            pass

    grid_rows = []
    for r in range(3):
        row_buttons = []
        for c in range(3):
            idx = r * 3 + c
            label = positions[idx]
            row_buttons.append(ft.TextButton(label, on_click=lambda ev, label=label: set_position(label)))
        grid_rows.append(ft.Row(row_buttons, spacing=4))
    pos_buttons = ft.Column(grid_rows, spacing=4)

    def scale_pixel_grid(pixels, factor):
        if factor == 1:
            return pixels
        h = len(pixels)
        w = max((len(r) for r in pixels), default=0)
        nh = h * factor
        nw = w * factor
        out = [[None for _ in range(nw)] for _ in range(nh)]
        for y in range(h):
            for x in range(len(pixels[y])):
                v = pixels[y][x]
                if v is None:
                    continue
                for dy in range(factor):
                    for dx in range(factor):
                        out[y*factor + dy][x*factor + dx] = v
        return out

    def load_pixels_for_stamp(path, scale):
        if not path or not os.path.exists(path):
            return None
        try:
            try:
                scale_f = float(scale)
            except Exception:
                scale_f = 1.0
            if path.lower().endswith('.png'):
                img = Image.open(path).convert('RGBA')
                try:
                    resample = Image.Resampling.NEAREST
                except Exception:
                    resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                if abs(scale_f - 1.0) > 1e-6:
                    nw = max(1, int(round(img.width * scale_f)))
                    nh = max(1, int(round(img.height * scale_f)))
                    img = img.resize((nw, nh), resample)
                pixels = editor._image_to_pixels_native(img)
            else:
                with open(path, 'r', encoding='utf-8') as fh:
                    obj = json.load(fh)
                if isinstance(obj, dict) and obj.get('png_base64'):
                    b = base64.b64decode(obj['png_base64'])
                    img = Image.open(io.BytesIO(b)).convert('RGBA')
                    try:
                        resample = Image.Resampling.NEAREST
                    except Exception:
                        resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                    if abs(scale_f - 1.0) > 1e-6:
                        nw = max(1, int(round(img.width * scale_f)))
                        nh = max(1, int(round(img.height * scale_f)))
                        img = img.resize((nw, nh), resample)
                    pixels = editor._image_to_pixels_native(img)
                elif isinstance(obj, dict) and 'pixels' in obj and isinstance(obj['pixels'], list):
                    pixels = obj['pixels']
                    if abs(scale_f - 1.0) > 1e-6:
                        try:
                            img = editor._pixels_to_image(pixels)
                            try:
                                resample = Image.Resampling.NEAREST
                            except Exception:
                                resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                            nw = max(1, int(round(img.width * scale_f)))
                            nh = max(1, int(round(img.height * scale_f)))
                            img = img.resize((nw, nh), resample)
                            pixels = editor._image_to_pixels_native(img)
                        except Exception:
                            try:
                                if int(scale_f) > 1:
                                    pixels = scale_pixel_grid(pixels, int(scale_f))
                            except Exception:
                                pass
            if chroma_checkbox.value:
                try:
                    tr, tg, tb, _ = editor._hex_to_rgba(chroma_color_field.value)
                    for yy in range(len(pixels)):
                        for xx in range(len(pixels[yy])):
                            px = pixels[yy][xx]
                            if px is None:
                                continue
                            pr, pg, pb, _ = editor._hex_to_rgba(px)
                            if pr == tr and pg == tg and pb == tb:
                                pixels[yy][xx] = None
                except Exception:
                    pass
            try:
                if not path.lower().endswith('.png'):
                    sf_int = int(round(float(scale)))
                    if sf_int > 1 and abs(float(scale) - sf_int) < 1e-6:
                        pixels = scale_pixel_grid(pixels, sf_int)
            except Exception:
                pass
            return pixels
        except Exception:
            return None

    def on_select(ev):
        v = dropdown.value
        if not v:
            return
        try:
            mapped = option_map.get(v, v)
        except Exception:
            mapped = v
        if str(mapped).startswith('.stamps' + os.sep) or str(mapped).startswith('.stamps/'):
            p = os.path.join(project_dir, mapped)
        else:
            p = os.path.join(str(saved_dir), mapped) if saved_dir and not os.path.isabs(mapped) else mapped

        logger.debug(f"Stamp dialog on_select: selected value={v} mapped={mapped} resolved_path={p} exists={os.path.exists(p) if p else 'N/A'} scale={scale_dropdown.value}")

        try:
            scale = float(scale_dropdown.value or '1')
        except Exception:
            scale = 1.0

        def apply_chroma(pixels):
            if not chroma_checkbox.value:
                return pixels
            try:
                tr, tg, tb, _ = editor._hex_to_rgba(chroma_color_field.value)
            except Exception:
                return pixels
            h = len(pixels)
            for yy in range(h):
                row = pixels[yy]
                for xx in range(len(row)):
                    px = row[xx]
                    if px is None:
                        continue
                    try:
                        pr, pg, pb, _ = editor._hex_to_rgba(px)
                        if pr == tr and pg == tg and pb == tb:
                            row[xx] = None
                    except Exception:
                        continue
            return pixels

        try:
            pixels_scaled = load_pixels_for_stamp(p, scale)
            if pixels_scaled is not None:
                import tempfile as _tmp
                img_out = editor._pixels_to_image(pixels_scaled)
                with _tmp.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    img_out.save(tmp.name)
                    preview.src = tmp.name
                    preview.update()
                try:
                    applied_pixels = copy.deepcopy(editor.pixels)
                    ox = int((pos_x.value or '0').strip())
                    oy = int((pos_y.value or '0').strip())
                    for y in range(len(pixels_scaled)):
                        for x in range(len(pixels_scaled[0])):
                            vpx = pixels_scaled[y][x]
                            tx = x + ox
                            ty = y + oy
                            if 0 <= tx < editor.size and 0 <= ty < editor.size:
                                if vpx is not None:
                                    applied_pixels[ty][tx] = vpx
                    try:
                        total_ap = sum(len(row) for row in applied_pixels)
                        trans_ap = sum(1 for r in applied_pixels for c in r if c is None)
                        logger.debug(f"applied_preview: after stamping opaque_only={opaque_only.value} ox={ox} oy={oy} applied_transparent={trans_ap}/{total_ap}")
                    except Exception:
                        pass
                    img2 = editor._pixels_to_image(applied_pixels)
                    try:
                        w2, h2 = img2.size
                        sq = max(1, min(w2, h2) // 4)
                        bg = Image.new('RGBA', img2.size, (255, 255, 255, 255))
                        for yy in range(0, h2, sq):
                            for xx in range(0, w2, sq):
                                c = (200, 200, 200, 255) if ((xx//sq)+(yy//sq)) % 2 == 0 else (240, 240, 240, 255)
                                for y2 in range(yy, min(h2, yy+sq)):
                                    for x2 in range(xx, min(w2, xx+sq)):
                                        bg.putpixel((x2, y2), c)
                        composed = Image.alpha_composite(bg, img2.convert('RGBA'))
                    except Exception:
                        composed = img2
                    with _tmp.NamedTemporaryFile(suffix='.png', delete=False) as tmp2:
                        composed.save(tmp2.name)
                        preview_applied.src = tmp2.name
                        preview_applied.update()
                except Exception:
                    preview_applied.src = None
                    preview_applied.update()
                return

            if p and os.path.exists(p) and p.lower().endswith('.json'):
                with open(p, 'r', encoding='utf-8') as fh:
                    obj = json.load(fh)
                if isinstance(obj, dict) and obj.get('png_base64'):
                    b = base64.b64decode(obj['png_base64'])
                    try:
                        img = Image.open(io.BytesIO(b)).convert('RGBA')
                    except Exception:
                        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmpf:
                            tmpf.write(b)
                            preview.src = tmpf.name
                            preview.update()
                            preview_applied.src = tmpf.name
                            preview_applied.update()
                            return
                    try:
                        resample = Image.Resampling.NEAREST
                    except Exception:
                        resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                    if abs(scale - 1.0) > 1e-6:
                        nw = max(1, int(round(img.width * scale)))
                        nh = max(1, int(round(img.height * scale)))
                        img = img.resize((nw, nh), resample)
                    pixels = editor._image_to_pixels_native(img)
                    pixels = apply_chroma(pixels)
                    img_out = editor._pixels_to_image(pixels)
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        img_out.save(tmp.name)
                        preview.src = tmp.name
                        preview.update()
                        try:
                            applied_pixels = copy.deepcopy(editor.pixels)
                            ox = int((pos_x.value or '0').strip())
                            oy = int((pos_y.value or '0').strip())
                            for y in range(len(pixels)):
                                for x in range(len(pixels[0])):
                                    vpx = pixels[y][x]
                                    tx = x + ox
                                    ty = y + oy
                                    if 0 <= tx < editor.size and 0 <= ty < editor.size:
                                        if vpx is not None:
                                            applied_pixels[ty][tx] = vpx
                            try:
                                total_ap = sum(len(row) for row in applied_pixels)
                                trans_ap = sum(1 for r in applied_pixels for c in r if c is None)
                                logger.debug(f"applied_preview(embedded png): opaque_only={opaque_only.value} ox={ox} oy={oy} applied_transparent={trans_ap}/{total_ap}")
                            except Exception:
                                pass
                            img2 = editor._pixels_to_image(applied_pixels)
                            try:
                                w2, h2 = img2.size
                                sq = max(1, min(w2, h2) // 4)
                                bg = Image.new('RGBA', img2.size, (255, 255, 255, 255))
                                for yy in range(0, h2, sq):
                                    for xx in range(0, w2, sq):
                                        c = (200, 200, 200, 255) if ((xx//sq)+(yy//sq)) % 2 == 0 else (240, 240, 240, 255)
                                        for y2 in range(yy, min(h2, yy+sq)):
                                            for x2 in range(xx, min(w2, xx+sq)):
                                                bg.putpixel((x2, y2), c)
                                composed = Image.alpha_composite(bg, img2.convert('RGBA'))
                            except Exception:
                                composed = img2
                            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp2:
                                composed.save(tmp2.name)
                                preview_applied.src = tmp2.name
                                preview_applied.update()
                        except Exception:
                            preview_applied.src = None
                            preview_applied.update()
                        return

                if isinstance(obj, dict) and 'pixels' in obj and isinstance(obj['pixels'], list):
                    pixels = obj['pixels']
                    pixels = apply_chroma(pixels)
                    # support fractional scaling by converting to an image and resizing
                    try:
                        sf = float(scale)
                    except Exception:
                        sf = 1.0
                    if abs(sf - round(sf)) < 1e-6:
                        sf_int = int(round(sf))
                        pixels_scaled = scale_pixel_grid(pixels, sf_int) if sf_int > 1 else pixels
                    else:
                        try:
                            img_tmp = editor._pixels_to_image(pixels)
                            try:
                                resample = Image.Resampling.NEAREST
                            except Exception:
                                resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                            nw = max(1, int(round(img_tmp.width * sf)))
                            nh = max(1, int(round(img_tmp.height * sf)))
                            img_tmp = img_tmp.resize((nw, nh), resample)
                            pixels_scaled = editor._image_to_pixels_native(img_tmp)
                        except Exception:
                            # fallback to integer scaling
                            sf_int = max(1, int(round(sf)))
                            pixels_scaled = scale_pixel_grid(pixels, sf_int)
                    img_out = editor._pixels_to_image(pixels_scaled)
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                        img_out.save(tmp.name)
                        preview.src = tmp.name
                        preview.update()
                    try:
                        applied_pixels = copy.deepcopy(editor.pixels)
                        ox = int((pos_x.value or '0').strip())
                        oy = int((pos_y.value or '0').strip())
                        for y in range(len(pixels_scaled)):
                            for x in range(len(pixels_scaled[0])):
                                vpx = pixels_scaled[y][x]
                                tx = x + ox
                                ty = y + oy
                                if 0 <= tx < editor.size and 0 <= ty < editor.size:
                                    if vpx is not None:
                                        applied_pixels[ty][tx] = vpx
                        try:
                            total_ap = sum(len(row) for row in applied_pixels)
                            trans_ap = sum(1 for r in applied_pixels for c in r if c is None)
                            logger.debug(f"applied_preview(pixels json): opaque_only={opaque_only.value} ox={ox} oy={oy} applied_transparent={trans_ap}/{total_ap}")
                        except Exception:
                            pass
                        img2 = editor._pixels_to_image(applied_pixels)
                        try:
                            w2, h2 = img2.size
                            sq = max(1, min(w2, h2) // 4)
                            bg = Image.new('RGBA', img2.size, (255, 255, 255, 255))
                            for yy in range(0, h2, sq):
                                for xx in range(0, w2, sq):
                                    c = (200, 200, 200, 255) if ((xx//sq)+(yy//sq)) % 2 == 0 else (240, 240, 240, 255)
                                    for y2 in range(yy, min(h2, yy+sq)):
                                        for x2 in range(xx, min(w2, xx+sq)):
                                            bg.putpixel((x2, y2), c)
                            composed = Image.alpha_composite(bg, img2.convert('RGBA'))
                        except Exception:
                            composed = img2
                        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp2:
                            composed.save(tmp2.name)
                            preview_applied.src = tmp2.name
                            preview_applied.update()
                    except Exception:
                        preview_applied.src = None
                        preview_applied.update()
                    return

            preview.src = None
            preview.update()
            preview_applied.src = None
            preview_applied.update()
        except Exception as ex:
            logger.exception(f"Error previewing selected stamp image: {ex}")

    dropdown.on_change = on_select

    def do_stamp(ev):
        fn = dropdown.value
        if not fn:
            status.value = "Select a file"
            status.update()
            return
        mapped = option_map.get(fn, fn)
        if str(mapped).startswith('.stamps' + os.sep) or str(mapped).startswith('.stamps/'):
            p = os.path.join(project_dir, mapped)
        else:
            p = os.path.join(str(saved_dir), mapped) if saved_dir and not os.path.isabs(mapped) else mapped

        try:
            try:
                scale = float(scale_dropdown.value or '1')
            except Exception:
                scale = 1.0
            pixels = load_pixels_for_stamp(p, scale)

            if not pixels:
                status.value = "Failed to load pixels from file"
                status.update()
                return

            ox = int((pos_x.value or '0').strip())
            oy = int((pos_y.value or '0').strip())
            stamp = [[None for _ in range(editor.size)] for _ in range(editor.size)]
            for y in range(min(editor.size, len(pixels))):
                for x in range(min(editor.size, len(pixels[0]))):
                    v = pixels[y][x]
                    tx = x + ox
                    ty = y + oy
                    if 0 <= tx < editor.size and 0 <= ty < editor.size:
                        if opaque_only.value:
                            if v is not None:
                                stamp[ty][tx] = v
                        else:
                            stamp[ty][tx] = v
            editor._stamp_pixels(stamp)
            try:
                page.close(dlg)
            except Exception:
                pass
        except Exception as ex:
            logger.exception(f"Error stamping image: {ex}")
            status.value = f"Error: {ex}"
            status.update()

    pos_x.on_change = lambda ev: on_select(None)
    pos_y.on_change = lambda ev: on_select(None)
    scale_dropdown.on_change = lambda ev: on_select(None)

    logger.debug(f"Stamp dialog initialized: {len(files)} files found, option_map keys: {list(option_map.keys())}")

    content = ft.Column([
        ft.Row([ft.Column([dropdown, ft.TextButton("Open Stamp Gallery", on_click=open_stamp_gallery)]), import_btn], alignment=ft.MainAxisAlignment.START, spacing=8),
        ft.Row([pos_x, pos_y, scale_dropdown, opaque_only], spacing=8),
        ft.Row([chroma_checkbox, chroma_color_field, chroma_picker_btn], spacing=8),
        pos_buttons,
        ft.Row([
            ft.Column([ft.Text("Preview"), preview]),
            ft.Column([ft.Text("Applied Preview"), preview_applied])
        ]),
        status
    ], spacing=8, width=620)

    dlg = ft.AlertDialog(title=ft.Text("Stamp Image"), content=content, actions=[ft.TextButton("Stamp", on_click=do_stamp), ft.TextButton("Cancel", on_click=lambda ev: page.close(dlg))], open=False)
    STAMP_DIALOG = dlg
    if page:
        page.dialog = dlg
        page.open(dlg)
        try:
            if not dropdown.value and dropdown.options:
                dropdown.value = dropdown.options[0].text if hasattr(dropdown.options[0], 'text') else getattr(dropdown.options[0], 'key', None) or getattr(dropdown.options[0], 'value', None)
            on_select(None)
        except Exception:
            pass

# --- Import sprite sheet dialog/handler ---
def open_import_dialog(ev):
    page_local = ev.page if hasattr(ev, 'page') else None
    sheet_path_field = ft.TextField(label="Sprite sheet path", width=300)
    # file picker control (shared pattern used in other parts of the app)
    file_picker = ft.FilePicker()
    if page_local and getattr(page_local, 'overlay', None) is not None:
        try:
            page_local.overlay.append(file_picker)
        except Exception:
            pass
    def on_file_pick(e_pick, target=sheet_path_field):
        try:
            if getattr(e_pick, 'files', None):
                fp = e_pick.files[0].path if hasattr(e_pick.files[0], 'path') else (e_pick.files[0].name if hasattr(e_pick.files[0], 'name') else None)
                if fp:
                    try:
                        target.value = fp
                        target.update()
                        try:
                            update_preview()
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass
    try:
        file_picker.on_result = on_file_pick
    except Exception:
        try:
            file_picker.on_pick = on_file_pick
        except Exception:
            pass
    choose_btn = ft.TextButton("Choose file", on_click=lambda ev2: file_picker.pick_files())
    auto_analyze_btn = ft.TextButton("Auto Analyze", on_click=lambda ev3: auto_analyze())
    tile_w_field = ft.TextField(label="Tile width", value="8", width=140)
    tile_h_field = ft.TextField(label="Tile height", value="8", width=140)
    # add downscale option for import: integer or fractional downscale (e.g., 0.5 to reduce size)
    downscale_field = ft.TextField(label="Downscale (e.g. 1, 0.5)", value="1", width=140)
    prefix_field = ft.TextField(label="Filename prefix", value="sheet", width=260)
    skip_empty_cb = ft.Checkbox(label="Skip empty tiles", value=True)
    crop_tiles_cb = ft.Checkbox(label="Crop tile blank borders", value=True)
    transparent_bg_cb = ft.Checkbox(label="Make background transparent", value=False)
    status_import = ft.Text("")
    status_preview = ft.Text("")
    warn_preview = ft.Text("", color="red")
    # container to hold thumbnail previews of tiles
    preview_container = ft.Row(spacing=8)

    # helper to update preview thumbnails and warning
    def update_preview(ev=None):
        try:
            # clear existing previews
            if getattr(preview_container, 'controls', None) is not None:
                preview_container.controls.clear()
        except Exception:
            pass
        path = (sheet_path_field.value or '').strip()
        try:
            tw = int((tile_w_field.value or '8').strip())
            th = int((tile_h_field.value or '8').strip())
        except Exception:
            warn_preview.value = "Tile width/height must be integers"
            try:
                warn_preview.update()
            except Exception:
                pass
            return
        if not path or not os.path.exists(path):
            warn_preview.value = "No valid sprite sheet selected"
            try:
                warn_preview.update()
            except Exception:
                pass
            return
        try:
            img = Image.open(path)
            sw, sh = img.size
            cols = max(1, sw // tw)
            rows = max(1, sh // th)
            total = cols * rows
            warn_preview.value = f"{cols} cols x {rows} rows => {total} tiles"
            if total > 200:
                warn_preview.value = str(warn_preview.value) + " — large import, preview shows first 12"
            try:
                warn_preview.update()
            except Exception:
                pass
            # show up to 12 thumbnails
            max_preview = 12
            count = 0
            import tempfile
            for r in range(rows):
                for c in range(cols):
                    if count >= max_preview:
                        break
                    box = (c*tw, r*th, c*tw + tw, r*th + th)
                    tile = img.crop(box).resize((32, 32))
                    try:
                        tmpf = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                        tile.save(tmpf.name)
                        preview_container.controls.append(ft.Image(src=tmpf.name, width=32, height=32))
                    except Exception:
                        pass
                    count += 1
                if count >= max_preview:
                    break
            try:
                preview_container.update()
            except Exception:
                pass
        except Exception:
            warn_preview.value = "Failed to read image for preview"
            try:
                warn_preview.update()
            except Exception:
                pass

    # wire preview updates
    try:
        sheet_path_field.on_change = update_preview
    except Exception:
        pass
    try:
        tile_w_field.on_change = update_preview
    except Exception:
        pass
    try:
        tile_h_field.on_change = update_preview
    except Exception:
        pass
    # Clipboard import button: tries to fetch image data from clipboard if available
    def import_from_clipboard(ev_cb, target=sheet_path_field, status_ctrl=status_import):
        if not page_local:
            status_ctrl.value = "No page available for clipboard"
            status_ctrl.update()
            return
        try:
            # Some runtimes expose a page.get_clipboard() returning bytes or text
            cb = None
            try:
                cb = page_local.get_clipboard()
            except Exception:
                # older flet versions may use page.clipboard or not support it
                try:
                    cb = page_local.clipboard
                except Exception:
                    cb = None
            if not cb:
                status_import.value = "Clipboard empty or unsupported"
                status_import.update()
                return
            # If clipboard returns bytes, attempt to read as PNG; if text, ignore
            img_bytes = None
            if isinstance(cb, (bytes, bytearray)):
                img_bytes = bytes(cb)
            elif isinstance(cb, str):
                # maybe a data URL
                if cb.startswith('data:image') and 'base64,' in cb:
                    import base64
                    img_bytes = base64.b64decode(cb.split('base64,', 1)[1])
            if not img_bytes:
                status_ctrl.value = "Clipboard does not contain image bytes"
                status_ctrl.update()
                return
            import io
            img = Image.open(io.BytesIO(img_bytes)).convert('RGBA')
            # save to a temp file and set the sheet path
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmpf:
                img.save(tmpf.name)
                try:
                    target.value = tmpf.name
                    target.update()
                    try:
                        update_preview()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception as ex:
            logger.exception(f"Clipboard import failed: {ex}")
            status_import.value = f"Clipboard import failed: {ex}"
            status_import.update()
    clipboard_btn = ft.TextButton("Import from clipboard", on_click=import_from_clipboard)

    def auto_analyze():
        path = (sheet_path_field.value or '').strip()
        if not path or not os.path.exists(path):
            warn_preview.value = "No file to analyze"
            try:
                warn_preview.update()
            except Exception:
                pass
            return
        try:
            # Use a robust grid detection approach across integer downsample scales
            img = Image.open(path).convert('RGBA')
            from collections import Counter

            # helper to pick a background color from edge samples
            def pick_background(im):
                w, h = im.size
                px = im.load()
                coords = [(0,0),(w-1,0),(0,h-1),(w-1,h-1),(w//2,0),(w//2,h-1),(0,h//2),(w-1,h//2)]
                samples = []
                for (sx, sy) in coords:
                    try:
                        samples.append(tuple(int(v) for v in px[sx, sy]))
                    except Exception:
                        pass
                if not samples:
                    return (255,255,255,255)
                most = Counter(samples).most_common(1)[0][0]
                return most

            def similar_color(a, b, tol=18):
                ar,ag,ab,aa = a
                br,bg,bb,ba = b
                return ((ar-br)**2 + (ag-bg)**2 + (ab-bb)**2) <= (tol*tol)

            def detect_grid(im, bg):
                """Detect content segments per-row and per-column and return their starts and median lengths.
                This measures contiguous non-background runs (segments) instead of relying on spacing gcds,
                which is more robust for sheets with gutters or variable spacing.
                """
                w,h = im.size
                px = im.load()
                row_proj = [0]*h
                col_proj = [0]*w
                for y in range(h):
                    s=0
                    for x in range(w):
                        try:
                            if not similar_color(px[x,y], bg):
                                s += 1
                        except Exception:
                            pass
                    row_proj[y]=s
                for x in range(w):
                    s=0
                    for y in range(h):
                        try:
                            if not similar_color(px[x,y], bg):
                                s += 1
                        except Exception:
                            pass
                    col_proj[x]=s

                row_thresh = max(1, int(w*0.02))
                col_thresh = max(1, int(h*0.02))

                def segments_from_proj(proj, thresh):
                    segs = []
                    in_region = False
                    start = 0
                    for i, v in enumerate(proj):
                        if v > thresh and not in_region:
                            in_region = True
                            start = i
                        elif v <= thresh and in_region:
                            in_region = False
                            segs.append((start, i))
                    # close final region
                    if in_region:
                        segs.append((start, len(proj)))
                    return segs

                row_segs = segments_from_proj(row_proj, row_thresh)
                col_segs = segments_from_proj(col_proj, col_thresh)

                row_starts = [s for s,_ in row_segs]
                col_starts = [s for s,_ in col_segs]

                row_lengths = [e - s for s,e in row_segs]
                col_lengths = [e - s for s,e in col_segs]

                # choose candidates from median segment lengths if available
                candidates = []
                if col_lengths:
                    col_med = sorted(col_lengths)[len(col_lengths)//2]
                    if col_med > 0:
                        candidates.append(col_med)
                if row_lengths:
                    row_med = sorted(row_lengths)[len(row_lengths)//2]
                    if row_med > 0 and row_med not in candidates:
                        candidates.append(row_med)

                return {
                    'col_starts': col_starts,
                    'row_starts': row_starts,
                    'candidates': candidates,
                    'cols': len(col_starts),
                    'rows': len(row_starts),
                }

            # try multiple integer downsample scales and pick the best detection
            best_score = -1
            best_result = None
            best_img = None
            # resampling compatibility
            try:
                resample_filter = Image.Resampling.LANCZOS
            except Exception:
                try:
                    resample_filter = Image.LANCZOS
                except Exception:
                    resample_filter = Image.BICUBIC
            for scale in [1,2,3,4]:
                try:
                    if scale == 1:
                        im_test = img
                    else:
                        new_w = max(1, img.width // scale)
                        new_h = max(1, img.height // scale)
                        im_test = img.resize((new_w, new_h), resample=resample_filter)
                    bg = pick_background(im_test)
                    result = detect_grid(im_test, bg)
                    score = result['cols'] * result['rows']
                    # prefer results with more than 1 col and row
                    if score > best_score:
                        best_score = score
                        best_result = result
                        best_img = im_test
                        best_scale = scale
                except Exception:
                    continue

            if not best_result:
                warn_preview.value = "Failed to detect grid"
                try:
                    warn_preview.update()
                except Exception:
                    pass
                return

            # determine inferred tile size: use median spacing if available
            cand_sizes = best_result.get('candidates') or []
            inferred = None
            if cand_sizes:
                inferred = sorted(cand_sizes)[len(cand_sizes)//2]
            else:
                # fallback to equal division
                if best_result['cols']>0:
                    inferred = max(1, best_img.width // best_result['cols'])
                elif best_result['rows']>0:
                    inferred = max(1, best_img.height // best_result['rows'])
                else:
                    inferred = 8

            # crop best_img to detected start/end boxes
            cs = best_result['col_starts']
            rs = best_result['row_starts']
            left = cs[0] if cs else 0
            top = rs[0] if rs else 0
            right = (cs[-1] + inferred) if cs else best_img.width
            bottom = (rs[-1] + inferred) if rs else best_img.height
            # clamp
            left = max(0, left)
            top = max(0, top)
            right = min(best_img.width, right)
            bottom = min(best_img.height, bottom)
            cropped = best_img.crop((left, top, right, bottom))

            # save cropped/scaled image and set fields
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            try:
                cropped.save(tf.name)
                sheet_path_field.value = tf.name
                try:
                    sheet_path_field.update()
                except Exception:
                    pass
            except Exception:
                pass
            inferred_w = inferred_h = int(inferred)
            tile_w_field.value = str(inferred_w)
            tile_h_field.value = str(inferred_h)
            try:
                tile_w_field.update()
                tile_h_field.update()
            except Exception:
                pass
            try:
                update_preview()
            except Exception:
                pass
            # detection complete; preview already updated
        except Exception as ex:
            logger.exception(f"Auto analyze failed: {ex}")
            warn_preview.value = f"Auto analyze failed: {ex}"
            try:
                warn_preview.update()
            except Exception:
                pass

    def perform_import(path, tw, th, pref):
        try:
            img = Image.open(path).convert('RGBA')
            sw, sh = img.size
            cols = sw // tw
            rows = sh // th
            ensure_dir = stamps_dir if stamps_dir else os.path.join(project_dir, '.stamps')
            try:
                os.makedirs(ensure_dir, exist_ok=True)
            except Exception:
                pass
            written = 0
            # iterate over grid and write out tiles; keep logic explicit to avoid nested-try issues
            for r in range(rows):
                for c in range(cols):
                    try:
                        box = (c*tw, r*th, c*tw + tw, r*th + th)
                        tile = img.crop(box).convert('RGBA')

                        def tile_to_pixels(im):
                            pxs = []
                            for yy in range(im.height):
                                row = []
                                for xx in range(im.width):
                                    try:
                                        pr, pg, pb, pa = im.getpixel((xx, yy))
                                    except Exception:
                                        val = im.getpixel((xx, yy))
                                        if isinstance(val, (int, float)):
                                            pr = pg = pb = int(val)
                                            pa = 255
                                        else:
                                            try:
                                                pr, pg, pb = val[:3]
                                                pa = val[3] if len(val) > 3 else 255
                                            except Exception:
                                                pr = pg = pb = 0
                                                pa = 255
                                    if pa < 128:
                                        row.append(None)
                                    else:
                                        row.append(f"#{pr:02X}{pg:02X}{pb:02X}")
                                pxs.append(row)
                            return pxs

                        # decide final tile image after optional cropping and transparency
                        final_tile = tile
                        try:
                            if crop_tiles_cb.value:
                                tb = tile.getbbox()
                                if tb:
                                    final_tile = tile.crop(tb)
                                    if transparent_bg_cb.value:
                                        try:
                                            from collections import Counter
                                            w2, h2 = final_tile.size
                                            corners = []
                                            for (cx, cy) in [(0,0),(w2-1,0),(0,h2-1),(w2-1,h2-1)]:
                                                try:
                                                    corners.append(tuple(int(v) for v in final_tile.getpixel((cx, cy))))
                                                except Exception:
                                                    pass
                                            bgc = Counter(corners).most_common(1)[0][0] if corners else (255,255,255,255)
                                            def similar_col(a,b,tol=20):
                                                return ((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) <= (tol*tol)
                                            tc = final_tile.copy()
                                            tc_px = tc.load()
                                            for yy in range(tc.height):
                                                for xx in range(tc.width):
                                                    try:
                                                        p = tc_px[xx, yy]
                                                        if similar_col(p, bgc):
                                                            tc_px[xx, yy] = (0,0,0,0)
                                                    except Exception:
                                                        pass
                                            final_tile = tc
                                        except Exception:
                                            final_tile = tile
                        except Exception:
                            # ignore cropping/transparency errors and continue with original tile
                            final_tile = tile

                        # apply downscale if requested (supports fractional factors)
                        try:
                            downscale_f = float(downscale_field.value or '1')
                        except Exception:
                            downscale_f = 1.0
                        if abs(downscale_f - 1.0) > 1e-6:
                            try:
                                resample = Image.Resampling.NEAREST
                            except Exception:
                                resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                            nw = max(1, int(round(final_tile.width * downscale_f)))
                            nh = max(1, int(round(final_tile.height * downscale_f)))
                            try:
                                final_tile = final_tile.resize((nw, nh), resample)
                            except Exception:
                                pass

                        pixels = tile_to_pixels(final_tile)
                        if skip_empty_cb.value and all(all(p is None for p in row) for row in pixels):
                            continue

                        name = f"{pref}_{r}_{c}"
                        outp = os.path.join(ensure_dir, name + '.json')
                        try:
                            with open(outp, 'w', encoding='utf-8') as fh:
                                json.dump({"metadata": {"name": name, "source": os.path.basename(path)}, "pixels": pixels}, fh, indent=2)
                            written += 1
                        except Exception as ex:
                            logger.exception(f"Failed writing stamp file {outp}: {ex}")
                    except Exception:
                        logger.exception("Error processing tile during import")
            status_import.value = f"Wrote {written} stamps to {ensure_dir}"
            status_import.update()
            # refresh main dropdown list: re-scan stamps_dir and saved_dir
            try:
                new_files = []
                if stamps_dir and os.path.isdir(stamps_dir):
                    for fn in os.listdir(stamps_dir):
                        if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                            new_files.append(os.path.join('.stamps', fn))
                if saved_dir:
                    sd = str(saved_dir) if hasattr(saved_dir, 'as_posix') else saved_dir
                    for fn in os.listdir(sd):
                        if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                            if fn not in [os.path.basename(f) for f in new_files]:
                                new_files.append(fn)
                # rebuild mapping
                dropdown.options.clear()
                option_map.clear()
                for f in new_files:
                    if str(f).startswith('.stamps' + os.sep) or str(f).startswith('.stamps/'):
                        label = f"[stamps] {os.path.basename(f)}"
                        value = f
                    else:
                        label = os.path.basename(f)
                        value = f
                    option_map[label] = value
                    dropdown.options.append(ft.dropdown.Option(label))
                try:
                    dropdown.update()
                except Exception:
                    pass
                # pick first option and preview
                try:
                    if dropdown.options:
                        dropdown.value = dropdown.options[0].text if hasattr(dropdown.options[0], 'text') else getattr(dropdown.options[0], 'key', None) or getattr(dropdown.options[0], 'value', None)
                    on_select(None)
                except Exception:
                    pass
                try:
                    # refresh stamp grid thumbnails as well
                    build_stamp_grid()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to refresh stamps after import")
            # close the import dialog after a short delay
            try:
                page_local.close(import_dlg)
            except Exception:
                pass
        except Exception as ex:
            logger.exception(f"Error importing sprite sheet: {ex}")
            status_import.value = f"Import failed: {ex}"
            status_import.update()

    def do_import(ev2):
        path = (sheet_path_field.value or '').strip()
        try:
            tw = int((tile_w_field.value or '8').strip())
            th = int((tile_h_field.value or '8').strip())
        except Exception:
            status_import.value = "Tile width/height must be integers"
            status_import.update()
            return
        pref = (prefix_field.value or 'sheet').strip() or 'sheet'
        if not path or not os.path.exists(path):
            status_import.value = f"File not found: {path}"
            status_import.update()
            return
        try:
            img = Image.open(path)
            sw, sh = img.size
            cols = sw // tw
            rows = sh // th
            total = cols * rows
            WARN_LIMIT = 500
            if total > WARN_LIMIT:
                # ask for confirmation
                def do_confirm(ev3):
                    try:
                        page_local.close(confirm_dlg)
                    except Exception:
                        pass
                    perform_import(path, tw, th, pref)

                def do_cancel(ev3):
                    try:
                        page_local.close(confirm_dlg)
                    except Exception:
                        pass

                confirm_dlg = ft.AlertDialog(title=ft.Text("Large import"), content=ft.Text(f"This will create {total} stamps ({cols}x{rows}). Continue?"), actions=[ft.TextButton("Yes, import", on_click=do_confirm), ft.TextButton("Cancel", on_click=do_cancel)])
                page_local.open(confirm_dlg)
                return
            # otherwise proceed immediately
            perform_import(path, tw, th, pref)
        except Exception as ex:
            logger.exception(f"Error preparing import: {ex}")
            status_import.value = f"Import failed: {ex}"
            status_import.update()

    content = ft.Column([
        ft.Row([sheet_path_field, choose_btn], spacing=8),
        ft.Row([clipboard_btn], spacing=8),
        ft.Row([auto_analyze_btn], spacing=8),
        ft.Row([tile_w_field, tile_h_field, prefix_field], spacing=8),
        ft.Row([downscale_field, skip_empty_cb, crop_tiles_cb, transparent_bg_cb], spacing=8),
        warn_preview,
        ft.Container(content=ft.Row([preview_container], scroll=ft.ScrollMode.AUTO), width=680),
        status_import
    ], spacing=8, width=700)
    import_dlg = ft.AlertDialog(title=ft.Text("Import Sprite Sheet"), content=content, actions=[ft.TextButton("Import", on_click=do_import), ft.TextButton("Cancel", on_click=lambda ev: page_local.close(import_dlg))], open=False)
    if page_local:
        page_local.open(import_dlg)