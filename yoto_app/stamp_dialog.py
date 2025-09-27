import os
import json
from pathlib import Path
import tempfile
import base64
import io
import copy
import flet as ft
from loguru import logger
from PIL import Image

from .icon_import_helpers import get_base64_from_path


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

    # gather file list (include .stamps/imported)
    try:
        if stamps_dir and os.path.isdir(stamps_dir):
            for fn in os.listdir(stamps_dir):
                if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                    files.append(os.path.join('.stamps', fn))
            # include imported subfolder contents (if present)
            try:
                imported_dir = os.path.join(stamps_dir, 'imported')
                if os.path.isdir(imported_dir):
                    for fn in os.listdir(imported_dir):
                        if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                            rel = os.path.join('.stamps', 'imported', fn)
                            if rel not in files:
                                files.append(rel)
            except Exception:
                pass
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

    # build dropdown (labels mark imported vs stamps)
    dropdown_options = []
    option_map = {}
    for f in files:
        fstr = str(f)
        if fstr.startswith(os.path.join('.stamps', 'imported') + os.sep) or fstr.startswith('.stamps/imported'):
            label = f"[imported] {os.path.basename(f)}"
            value = f
        elif fstr.startswith('.stamps' + os.sep) or fstr.startswith('.stamps/'):
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

        

    def build_stamp_grid(filter_by=None):
        try:
            stamp_grid.controls.clear()
        except Exception:
            pass
        import tempfile as _temp
        per_row = 6
        row = []
        for f in files:
            # apply gallery filter if requested
            try:
                if filter_by and filter_by != 'All':
                    fstr = str(f)
                    if filter_by == 'Imported' and not (fstr.startswith(os.path.join('.stamps', 'imported') + os.sep) or fstr.startswith('.stamps/imported')):
                        continue
                    if filter_by == 'Stamps' and (fstr.startswith(os.path.join('.stamps', 'imported') + os.sep) or fstr.startswith('.stamps/imported')):
                        # skip imported when only showing stamps
                        continue
                    if filter_by == 'Saved' and (fstr.startswith('.stamps' + os.sep) or fstr.startswith('.stamps/')):
                        # skip central .stamps when showing saved
                        continue
            except Exception:
                pass
            try:
                if str(f).startswith('.stamps' + os.sep) or str(f).startswith('.stamps/'):
                    p = os.path.join(project_dir, f)
                    # label will show imported when inside imported folder
                    if str(f).startswith(os.path.join('.stamps', 'imported') + os.sep) or str(f).startswith('.stamps/imported'):
                        label = f"[imported] {os.path.basename(f)}"
                    else:
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

                img_widget = ft.Image(src_base64=get_base64_from_path(Path(tmpf.name)), width=48, height=48, fit=ft.ImageFit.CONTAIN)
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
            # filter dropdown for gallery: All / Imported / Stamps / Saved
            filter_dropdown = ft.Dropdown(label="Filter", value='All', width=160, options=[ft.dropdown.Option(o) for o in ['All','Imported','Stamps','Saved']])
            def on_filter_change(ev_filter):
                try:
                    build_stamp_grid(filter_dropdown.value)
                except Exception:
                    pass
            filter_dropdown.on_change = on_filter_change
            # initial build with current filter
            build_stamp_grid(filter_dropdown.value)
            # place the stamp_grid inside a scrollable Column so the gallery can scroll
            grid_container = ft.Column([stamp_grid], scroll=ft.ScrollMode.AUTO, height=480, width=420)
            # ensure grid_container is updated after building
            try:
                grid_container.update()
            except Exception:
                pass
            gallery_content = ft.Column([ft.Row([ft.Text('Filter:'), filter_dropdown]), grid_container], spacing=8, width=420)
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
                base64_out = editor._pixels_to_base64(pixels_scaled)
                #img_out = editor._pixels_to_image(pixels_scaled)
                #with _tmp.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                #    img_out.save(tmp.name)
                #    preview.src = tmp.name
                #    preview.update()
                preview.src_base64 = base64_out
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
    # delegate to the extracted import dialog module which owns its own UI and worker-thread logic
    try:
        from yoto_app import import_dialog
        # pass `editor` by pulling from the enclosing module's expected variable: stamp dialog calls this
        # function from the editor via `open_import_dialog(ev)`; the editor is available on the top-level
        # `open_image_stamp_dialog` scope as `editor` when the wrapper is created. We capture it here via
        # the caller attaching `__editor_for_import` to the page event if present; fallback to None.
        editor_obj = None
        try:
            # some call sites may attach editor as attribute on the event
            editor_obj = ev.editor if hasattr(ev, 'editor') else None
        except Exception:
            editor_obj = None
        import_dialog.open_import_dialog(editor_obj, ev)
    except Exception:
        logger.exception("Failed to open import dialog module")
    