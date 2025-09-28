import os
import json
import tempfile
import base64
import io
from collections import Counter

import flet as ft
from loguru import logger
from PIL import Image
import subprocess
import sys
import platform
import io as _io

project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
stamps_dir = os.path.join(project_dir, '.stamps')

IMPORT_DIALOG = None
CROP_SHEET_DIALOG = None


def open_import_dialog(editor, ev):
    """Show the import sprite-sheet dialog. This is extracted from stamp_dialog so it can be used independently.
    This function does NOT attempt to modify stamp_dialog UI elements; it writes imported stamps into
    `.stamps/imported/` and logs the result. The main stamp dialog will pick them up when it rebuilds.
    """
    page_local = ev.page if hasattr(ev, 'page') else None
    sheet_path_field = ft.TextField(label="Sprite sheet path", width=300)
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
    edit_sheet_crop_btn = ft.TextButton("Edit sheet crop", on_click=lambda ev: None)

    def _open_sheet_crop_from_fields(ev):
        try:
            path_now = (sheet_path_field.value or '').strip()
            if not path_now or not os.path.exists(path_now):
                warn_preview.value = "No sheet loaded to edit crop"
                try:
                    warn_preview.update()
                except Exception:
                    pass
                return
            try:
                tw = int((tile_w_field.value or '8').strip())
                th = int((tile_h_field.value or '8').strip())
            except Exception:
                tw = th = 8
            try:
                img_full = Image.open(path_now)
            except Exception:
                # fallback: open full image and use a small placeholder
                try:
                    img_full = Image.open(path_now)
                except Exception:
                    img_full = Image.new('RGBA', (tw, th), (255,255,255,255))
            # pass the full sheet image to the sheet crop dialog so the override is sheet-relative
            open_sheet_crop_dialog(img_full)
        except Exception:
            pass

    try:
        edit_sheet_crop_btn.on_click = _open_sheet_crop_from_fields
    except Exception:
        pass
    tile_w_field = ft.TextField(label="Tile width", value="8", width=140)
    tile_h_field = ft.TextField(label="Tile height", value="8", width=140)
    downscale_field = ft.TextField(label="Downscale (e.g. 1, 0.5)", value="1", width=140)
    prefix_field = ft.TextField(label="Filename prefix", value="sheet", width=260)
    skip_empty_cb = ft.Checkbox(label="Skip empty tiles", value=True)
    crop_tiles_cb = ft.Checkbox(label="Crop tile blank borders", value=True)
    transparent_bg_cb = ft.Checkbox(label="Make background transparent", value=False)
    status_import = ft.Text("")
    status_preview = ft.Text("")
    warn_preview = ft.Text("", color="red")
    # preview_container will hold a Column of Rows (we build a simple grid manually)
    preview_container = ft.Column(spacing=6)
    # single sheet-level manual cropping override: (left, top, right, bottom) or None
    sheet_crop_override = None

    def open_sheet_crop_dialog(sample_image):
        """Show a dialog to edit a sheet-level crop override. sample_image is a Pillow Image (preferably the full sheet) used for preview."""
        try:
            import tempfile as _temp
            _tempf = _temp.NamedTemporaryFile(suffix='.png', delete=False)
            try:
                # save a preview of the provided image (may be large)
                sample_image.save(_tempf.name)
                preview_src = _tempf.name
            except Exception:
                preview_src = None
        except Exception:
            preview_src = None

        left_field = ft.TextField(label='Left (px)', width=120)
        top_field = ft.TextField(label='Top (px)', width=120)
        right_field = ft.TextField(label='Right (px)', width=120)
        bottom_field = ft.TextField(label='Bottom (px)', width=120)
        info_text = ft.Text('Define a sheet-level crop applied to every tile; leave empty to disable')

        if sheet_crop_override:
            try:
                left_field.value = str(sheet_crop_override[0])
                top_field.value = str(sheet_crop_override[1])
                right_field.value = str(sheet_crop_override[2])
                bottom_field.value = str(sheet_crop_override[3])
            except Exception:
                pass

        def do_auto(ev):
            try:
                # try to compute an automatic bbox from the sample tile
                tb = None
                try:
                    # reuse local tile_bbox logic from earlier
                    def _tile_bbox_local(im, tol=16, alpha_thresh=16):
                        w2, h2 = im.size
                        px = im.load()
                        has_alpha = False
                        for yy in range(min(4, h2)):
                            for xx in range(min(4, w2)):
                                try:
                                    v = px[xx, yy]
                                    if isinstance(v, tuple) and len(v) > 3:
                                        has_alpha = True
                                        break
                                except Exception:
                                    pass
                            if has_alpha:
                                break
                        if has_alpha:
                            top = bottom = left = right = None
                            for yy in range(h2):
                                row_has = False
                                for xx in range(w2):
                                    try:
                                        v = px[xx, yy]
                                        if isinstance(v, tuple) and len(v) > 3 and v[3] >= alpha_thresh:
                                            row_has = True
                                            break
                                        elif not isinstance(v, tuple):
                                            row_has = True
                                            break
                                    except Exception:
                                        pass
                                if row_has and top is None:
                                    top = yy
                                if row_has:
                                    bottom = yy
                            for xx in range(w2):
                                col_has = False
                                for yy in range(h2):
                                    try:
                                        v = px[xx, yy]
                                        if isinstance(v, tuple) and len(v) > 3 and v[3] >= alpha_thresh:
                                            col_has = True
                                            break
                                        elif not isinstance(v, tuple):
                                            col_has = True
                                            break
                                    except Exception:
                                        pass
                                if col_has and left is None:
                                    left = xx
                                if col_has:
                                    right = xx
                            if top is None:
                                return None
                            return (left, top, right+1, bottom+1)
                        else:
                            return None
                    tb = _tile_bbox_local(sample_image)
                except Exception:
                    tb = None
                if tb:
                    left_field.value = str(int(tb[0]))
                    top_field.value = str(int(tb[1]))
                    right_field.value = str(int(tb[2]))
                    bottom_field.value = str(int(tb[3]))
                else:
                    left_field.value = ''
                    top_field.value = ''
                    right_field.value = ''
                    bottom_field.value = ''
                try:
                    dlg.update()
                except Exception:
                    pass
            except Exception:
                pass

        def do_save(ev):
            nonlocal sheet_crop_override
            try:
                lf = (left_field.value or '').strip()
                tf = (top_field.value or '').strip()
                rf = (right_field.value or '').strip()
                bf = (bottom_field.value or '').strip()
                if lf == '' and tf == '' and rf == '' and bf == '':
                    sheet_crop_override = None
                else:
                    try:
                        lvi = int(lf) if lf != '' else 0
                        tvi = int(tf) if tf != '' else 0
                        rvi = int(rf) if rf != '' else sample_image.width
                        bvi = int(bf) if bf != '' else sample_image.height
                        # clamp to the provided image
                        lvi = max(0, min(sample_image.width, lvi))
                        tvi = max(0, min(sample_image.height, tvi))
                        rvi = max(0, min(sample_image.width, rvi))
                        bvi = max(0, min(sample_image.height, bvi))
                        if rvi <= lvi or bvi <= tvi:
                            sheet_crop_override = None
                        else:
                            sheet_crop_override = (lvi, tvi, rvi, bvi)
                    except Exception:
                        pass
                try:
                    page_local.open(IMPORT_DIALOG)
                except Exception:
                    pass
                try:
                    update_preview()
                except Exception:
                    pass
            except Exception:
                pass

        def do_reset(ev):
            nonlocal sheet_crop_override
            sheet_crop_override = None
            try:
                page_local.open(IMPORT_DIALOG)
            except Exception:
                pass
            try:
                update_preview()
            except Exception:
                pass

        img_ctrl = ft.Image(src=preview_src, width=300) if preview_src else ft.Text('Preview unavailable')
        dlg = ft.AlertDialog(title=ft.Text('Edit sheet crop override'), content=ft.Column([img_ctrl, info_text, ft.Row([left_field, top_field, right_field, bottom_field], spacing=8)]), actions=[ft.TextButton('Auto', on_click=do_auto), ft.TextButton('Save', on_click=do_save), ft.TextButton('Reset', on_click=do_reset), ft.TextButton('Close', on_click=lambda e: page_local.open(IMPORT_DIALOG))])
        global CROP_SHEET_DIALOG
        CROP_SHEET_DIALOG = dlg
        try:
            page_local.open(dlg)
        except Exception:
            pass

    def update_preview(ev=None):
        try:
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
            # if a sheet-level crop override is set, apply it to the whole sheet
            try:
                if sheet_crop_override:
                    img = img.crop(sheet_crop_override)
            except Exception:
                pass
            sw, sh = img.size
            cols = max(1, sw // tw)
            rows = max(1, sh // th)
            total = cols * rows
            warn_preview.value = f"{cols} cols x {rows} rows => {total} tiles"
            if total > 200:
                warn_preview.value = str(warn_preview.value) + " — large import, preview shows first 100"
            try:
                warn_preview.update()
            except Exception:
                pass
            # show up to 100 thumbnails in the preview (keeps UI responsive but gives a good overview)
            max_preview = min(100, total)
            count = 0
            # grid params
            cols_per_row = 10
            current_row = ft.Row(spacing=6)
            row_count = 0
            import tempfile as _temp
            for r in range(rows):
                for c in range(cols):
                    if count >= max_preview:
                        break
                    box = (c*tw, r*th, c*tw + tw, r*th + th)
                    pil_tile = img.crop(box)
                    try:
                        thumb = pil_tile.resize((32, 32))
                        tmpf = _temp.NamedTemporaryFile(suffix='.png', delete=False)
                        thumb.save(tmpf.name)
                        # append to current row
                        current_row.controls.append(ft.Container(content=ft.Image(src=tmpf.name, width=32, height=32)))
                        if len(current_row.controls) >= cols_per_row:
                            preview_container.controls.append(current_row)
                            current_row = ft.Row(spacing=6)
                    except Exception:
                        pass
                    count += 1
                if count >= max_preview:
                    break
            # flush remaining row
            try:
                if getattr(current_row, 'controls', None):
                    if len(current_row.controls) > 0:
                        preview_container.controls.append(current_row)
            except Exception:
                pass
            try:
                preview_container.update()
            except Exception:
                pass
            # add sheet crop editor button / indicator
            try:
                def _open_sheet_crop(ev):
                    # open dialog using first tile as sample
                    try:
                        # pass the full sheet image to the crop dialog
                        open_sheet_crop_dialog(img)
                    except Exception as ex:
                        logger.exception(f"Failed to open sheet crop dialog: {ex}")
                caption_text = 'Sheet crop: set' if sheet_crop_override else 'Sheet crop: none'
                preview_container.controls.append(ft.Row([ft.Text(caption_text), ft.TextButton('Edit sheet crop', on_click=_open_sheet_crop)]))
                logger.debug("Added sheet crop editor button")
            except Exception as ex:
                logger.exception(f"Failed to add sheet crop editor button: {ex}")
        except Exception as ex:
            logger.exception(f"Failed to process image for preview: {ex}")
            warn_preview.value = "Failed to read image for preview"
            try:
                warn_preview.update()
            except Exception:
                pass

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

    def import_from_clipboard(ev_cb, target=sheet_path_field, status_ctrl=status_import):
        logger.debug("Importing from clipboard")
        if not page_local:
            status_ctrl.value = "No page available for clipboard"
            status_ctrl.update()
            return
        try:
            # prefer any page-supplied clipboard first (web flows)
            cb = None
            try:
                cb = page_local.get_clipboard()
            except Exception:
                try:
                    cb = page_local.clipboard
                except Exception:
                    cb = None

            def _bytes_from_data_uri(s):
                try:
                    if isinstance(s, str) and s.startswith('data:image') and 'base64,' in s:
                        import base64 as _b64
                        return _b64.b64decode(s.split('base64,', 1)[1])
                except Exception:
                    return None
                return None

            def _try_desktop_clipboard():
                """Attempt several desktop clipboard methods and return raw PNG bytes or None.
                Order: Pillow ImageGrab, pyperclip/tkinter text (data-uri), wl-paste/xclip/xsel binaries (raw png).
                """
                # 1) Pillow ImageGrab.grabclipboard()
                try:
                    from PIL import ImageGrab
                    grabbed = ImageGrab.grabclipboard()
                    if grabbed is not None:
                        # grabbed may be an Image.Image or a list of filenames
                        if hasattr(grabbed, 'tobytes') or hasattr(grabbed, 'save'):
                            buf = _io.BytesIO()
                            try:
                                grabbed.save(buf, format='PNG')
                                return buf.getvalue()
                            except Exception as ex:
                                logger.exception(f"Failed to save grabbed image to buffer: {ex}")
                        elif isinstance(grabbed, (list, tuple)) and grabbed:
                            # list of filenames
                            for fn in grabbed:
                                try:
                                    with open(fn, 'rb') as fh:
                                        data = fh.read()
                                        if data:
                                            return data
                                except Exception as ex:
                                    logger.exception(f"Failed to read clipboard image file {fn}: {ex}")
                                    continue
                except Exception as ex:
                    logger.exception(f"Failed to grab clipboard image: {ex}")

                # 2) try pyperclip/tkinter for textual data URIs
                try:
                    import pyperclip
                    txt = pyperclip.paste()
                    if txt:
                        b = _bytes_from_data_uri(txt)
                        if b:
                            return b
                except Exception:
                    pass
                try:
                    import tkinter as _tk
                    root = _tk.Tk()
                    root.withdraw()
                    try:
                        txt = root.clipboard_get()
                        b = _bytes_from_data_uri(txt)
                        if b:
                            return b
                    except Exception:
                        pass
                    try:
                        root.destroy()
                    except Exception:
                        pass
                except Exception:
                    pass

                # 3) platform tools (Linux: wl-paste / xclip / xsel)
                sys_plat = platform.system().lower()
                if sys_plat == 'linux':
                    # try wl-paste
                    try:
                        p = subprocess.run(['wl-paste', '--no-newline', '--type', 'image/png'], capture_output=True)
                        if p.returncode == 0 and p.stdout:
                            return p.stdout
                    except Exception:
                        pass
                    # try xclip
                    try:
                        p = subprocess.run(['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'], capture_output=True)
                        if p.returncode == 0 and p.stdout:
                            return p.stdout
                    except Exception:
                        pass
                    # try xsel
                    try:
                        p = subprocess.run(['xsel', '--clipboard', '--output', '--mime-type', 'image/png'], capture_output=True)
                        if p.returncode == 0 and p.stdout:
                            return p.stdout
                    except Exception:
                        pass

                # 4) give up
                return None

            img_bytes = None
            # first, if page provided something useful
            if cb:
                if isinstance(cb, (bytes, bytearray)):
                    img_bytes = bytes(cb)
                elif isinstance(cb, str):
                    img_bytes = _bytes_from_data_uri(cb)
                elif isinstance(cb, dict):
                    # some filepicker shapes may include 'bytes' or 'data'
                    if 'bytes' in cb and isinstance(cb['bytes'], (bytes, bytearray)):
                        img_bytes = bytes(cb['bytes'])
                    elif 'data' in cb and isinstance(cb['data'], str):
                        img_bytes = _bytes_from_data_uri(cb['data'])
            # if still empty and we're on desktop, try desktop methods
            if img_bytes is None:
                try:
                    desktop_bytes = _try_desktop_clipboard()
                    if desktop_bytes:
                        img_bytes = desktop_bytes
                except Exception:
                    img_bytes = None

            if not img_bytes:
                status_ctrl.value = "Clipboard does not contain image bytes"
                status_ctrl.update()
                return

            img = Image.open(_io.BytesIO(img_bytes)).convert('RGBA')
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
        def starts_from_proj(proj, thresh):
            starts=[]
            in_region=False
            for i,v in enumerate(proj):
                if v>thresh and not in_region:
                    starts.append(i)
                    in_region=True
                elif v<=thresh and in_region:
                    in_region=False
            return starts

        row_starts = starts_from_proj(row_proj, row_thresh)
        col_starts = starts_from_proj(col_proj, col_thresh)
        row_spacings = [j-i for i,j in zip(row_starts, row_starts[1:])] if len(row_starts)>1 else []
        col_spacings = [j-i for i,j in zip(col_starts, col_starts[1:])] if len(col_starts)>1 else []

        def median_or_zero(arr):
            if not arr:
                return 0
            a=sorted(arr)
            return a[len(a)//2]
        candidates = []
        try:
            import math
            if col_spacings:
                g = math.gcd(*col_spacings)
                if g>1:
                    candidates.append(g)
                m = median_or_zero(col_spacings)
                if m>1:
                    candidates.append(m)
            if row_spacings:
                g = math.gcd(*row_spacings)
                if g>1 and g not in candidates:
                    candidates.append(g)
                m = median_or_zero(row_spacings)
                if m>1 and m not in candidates:
                    candidates.append(m)
        except Exception:
            pass

        return {
            'col_starts': col_starts,
            'row_starts': row_starts,
            'candidates': candidates,
            'cols': len(col_starts),
            'rows': len(row_starts),
        }

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
            img = Image.open(path).convert('RGBA')
            best_score = -1
            best_result = None
            best_img = None
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
                    if score > best_score:
                        best_score = score
                        best_result = result
                        best_img = im_test
                except Exception:
                    continue

            if not best_result:
                warn_preview.value = "Failed to detect grid"
                try:
                    warn_preview.update()
                except Exception:
                    pass
                return

            cand_sizes = best_result.get('candidates') or []
            inferred = None
            if cand_sizes:
                inferred = sorted(cand_sizes)[len(cand_sizes)//2]
            else:
                if best_result['cols']>0:
                    inferred = max(1, best_img.width // best_result['cols'])
                elif best_result['rows']>0:
                    inferred = max(1, best_img.height // best_result['rows'])
                else:
                    inferred = 8

            cs = best_result['col_starts']
            rs = best_result['row_starts']
            left = cs[0] if cs else 0
            top = rs[0] if rs else 0
            right = (cs[-1] + inferred) if cs else best_img.width
            bottom = (rs[-1] + inferred) if rs else best_img.height
            left = max(0, left)
            top = max(0, top)
            right = min(best_img.width, right)
            bottom = min(best_img.height, bottom)
            try:
                cropped = best_img.crop((left, top, right, bottom))
            except Exception:
                cropped = best_img

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
        except Exception as ex:
            logger.exception(f"Auto analyze failed: {ex}")
            warn_preview.value = f"Auto analyze failed: {ex}"
            try:
                warn_preview.update()
            except Exception:
                pass

    def perform_import(path, tw, th, pref):
        """Import tiles and write them to .stamps/imported; do not touch stamp dialog UI controls here.
        """
        try:
            img = Image.open(path).convert('RGBA')
            # apply sheet-level crop override to the whole sheet before slicing into tiles
            try:
                if sheet_crop_override:
                    img = img.crop(sheet_crop_override)
            except Exception:
                pass
            sw, sh = img.size
            cols = sw // tw
            rows = sh // th
            base_stamps = stamps_dir if stamps_dir else os.path.join(project_dir, '.stamps')
            ensure_dir = os.path.join(base_stamps, 'imported')
            try:
                os.makedirs(ensure_dir, exist_ok=True)
            except Exception:
                pass
            written = 0
            cropped_tiles = 0
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

                        final_tile = tile
                        try:
                            if crop_tiles_cb.value:
                                def tile_bbox(im, tol=16, alpha_thresh=16):
                                    w2, h2 = im.size
                                    px = im.load()
                                    has_alpha = False
                                    for yy in range(min(4, h2)):
                                        for xx in range(min(4, w2)):
                                            try:
                                                v = px[xx, yy]
                                                if isinstance(v, tuple) and len(v) > 3:
                                                    has_alpha = True
                                                    break
                                            except Exception:
                                                pass
                                        if has_alpha:
                                            break
                                    if has_alpha:
                                        top = bottom = left = right = None
                                        for yy in range(h2):
                                            row_has = False
                                            for xx in range(w2):
                                                try:
                                                    v = px[xx, yy]
                                                    if isinstance(v, tuple) and len(v) > 3 and v[3] >= alpha_thresh:
                                                        row_has = True
                                                        break
                                                    elif not isinstance(v, tuple):
                                                        row_has = True
                                                        break
                                                except Exception:
                                                    pass
                                            if row_has and top is None:
                                                top = yy
                                            if row_has:
                                                bottom = yy
                                        for xx in range(w2):
                                            col_has = False
                                            for yy in range(h2):
                                                try:
                                                    v = px[xx, yy]
                                                    if isinstance(v, tuple) and len(v) > 3 and v[3] >= alpha_thresh:
                                                        col_has = True
                                                        break
                                                    elif not isinstance(v, tuple):
                                                        col_has = True
                                                        break
                                                except Exception:
                                                    pass
                                            if col_has and left is None:
                                                left = xx
                                            if col_has:
                                                right = xx
                                        if top is None:
                                            return None
                                        return (left, top, right+1, bottom+1)
                                    else:
                                        border_samples = []
                                        for xx in range(w2):
                                            try:
                                                v = px[xx, 0]
                                                if isinstance(v, tuple):
                                                    border_samples.append((int(v[0]), int(v[1]), int(v[2])))
                                                else:
                                                    border_samples.append((int(v), int(v), int(v)))
                                            except Exception:
                                                pass
                                            try:
                                                v = px[xx, h2-1]
                                                if isinstance(v, tuple):
                                                    border_samples.append((int(v[0]), int(v[1]), int(v[2])))
                                                else:
                                                    border_samples.append((int(v), int(v), int(v)))
                                            except Exception:
                                                pass
                                        for yy in range(h2):
                                            try:
                                                v = px[0, yy]
                                                if isinstance(v, tuple):
                                                    border_samples.append((int(v[0]), int(v[1]), int(v[2])))
                                                else:
                                                    border_samples.append((int(v), int(v), int(v)))
                                            except Exception:
                                                pass
                                            try:
                                                v = px[w2-1, yy]
                                                if isinstance(v, tuple):
                                                    border_samples.append((int(v[0]), int(v[1]), int(v[2])))
                                                else:
                                                    border_samples.append((int(v), int(v), int(v)))
                                            except Exception:
                                                pass
                                        if border_samples:
                                            bgc = Counter(border_samples).most_common(1)[0][0]
                                        else:
                                            bgc = (255, 255, 255)
                                        def color_diff_sq(a, b):
                                            return (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2
                                        top = bottom = left = right = None
                                        for yy in range(h2):
                                            row_has = False
                                            for xx in range(w2):
                                                try:
                                                    v = px[xx, yy]
                                                    col = (int(v[0]), int(v[1]), int(v[2])) if isinstance(v, tuple) else (int(v), int(v), int(v))
                                                    if color_diff_sq(col, bgc) > (tol * tol):
                                                        row_has = True
                                                        break
                                                except Exception:
                                                    pass
                                            if row_has and top is None:
                                                top = yy
                                            if row_has:
                                                bottom = yy
                                        for xx in range(w2):
                                            col_has = False
                                            for yy in range(h2):
                                                try:
                                                    v = px[xx, yy]
                                                    col = (int(v[0]), int(v[1]), int(v[2])) if isinstance(v, tuple) else (int(v), int(v), int(v))
                                                    if color_diff_sq(col, bgc) > (tol * tol):
                                                        col_has = True
                                                        break
                                                except Exception:
                                                    pass
                                            if col_has and left is None:
                                                left = xx
                                            if col_has:
                                                right = xx
                                        if top is None:
                                            return None
                                        return (left, top, right+1, bottom+1)
                                tb = None
                                try:
                                    # sheet-level override has already been applied to the source image,
                                    # so compute bbox per-tile normally when requested
                                    tb = tile_bbox(tile, tol=20, alpha_thresh=16)
                                except Exception:
                                    tb = None
                                if tb:
                                    try:
                                        logger.debug(f"Import: cropping tile r={r} c={c} box={tb}")
                                    except Exception:
                                        pass
                                    try:
                                        left_px, top_px, right_px, bottom_px = (int(tb[0]), int(tb[1]), int(tb[2]), int(tb[3]))
                                        left_px = max(0, left_px)
                                        top_px = max(0, top_px)
                                        right_px = min(tile.width, right_px)
                                        bottom_px = min(tile.height, bottom_px)
                                        final_tile = tile.crop((left_px, top_px, right_px, bottom_px))
                                        cropped_tiles += 1
                                    except Exception:
                                        final_tile = tile
                                    if transparent_bg_cb.value:
                                        try:
                                            # ensure we have the final tile size
                                            w3, h3 = final_tile.size if hasattr(final_tile, 'size') else (0, 0)
                                            corners = []
                                            if w3 > 0 and h3 > 0:
                                                pts = [(0,0), (w3-1,0), (0,h3-1), (w3-1,h3-1)]
                                            else:
                                                pts = []
                                            for (cx, cy) in pts:
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
                            final_tile = tile
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
            status_import.value = f"Wrote {written} stamps to {ensure_dir} (cropped {cropped_tiles})"
            try:
                status_import.update()
            except Exception:
                pass
            # write a small marker so other parts of the app can detect new imported stamps
            try:
                with open(os.path.join(ensure_dir, '.last_import'), 'w', encoding='utf-8') as mf:
                    mf.write(str(written))
            except Exception:
                pass
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
            perform_import(path, tw, th, pref)
        except Exception as ex:
            logger.exception(f"Error preparing import: {ex}")
            status_import.value = f"Import failed: {ex}"
            status_import.update()

    content = ft.Column([
        ft.Row([sheet_path_field, choose_btn], spacing=8),
    ft.Row([clipboard_btn], spacing=8),
    ft.Row([auto_analyze_btn, edit_sheet_crop_btn], spacing=8),
        ft.Row([tile_w_field, tile_h_field, prefix_field], spacing=8),
        ft.Row([downscale_field, skip_empty_cb, crop_tiles_cb, transparent_bg_cb], spacing=8),
        warn_preview,
        ft.Container(content=ft.Column([preview_container], scroll=ft.ScrollMode.AUTO), width=680, height=360),
        status_import
    ], spacing=8, width=700)
    import_dlg = ft.AlertDialog(title=ft.Text("Import Sprite Sheet"), content=content, actions=[ft.TextButton("Import", on_click=do_import), ft.TextButton("Cancel", on_click=lambda ev: page_local.close(import_dlg))], open=False)
    global IMPORT_DIALOG
    IMPORT_DIALOG = import_dlg
    if page_local:
        page_local.open(import_dlg)
