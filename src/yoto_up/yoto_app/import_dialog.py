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
from yoto_up.paths import STAMPS_DIR

# Use centralized STAMPS_DIR from paths.py (absolute Path-like)
stamps_dir = str(STAMPS_DIR)

IMPORT_DIALOG = None


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
                            auto_analyze()
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
    sheet_crop_mode_field = ft.Dropdown(label="Sheet crop method", options=[ft.dropdown.Option("None"), ft.dropdown.Option("Snap to tiles"), ft.dropdown.Option("Detect by border color")], value="Snap to tiles", width=220)
    apply_sheet_crop_btn = ft.TextButton("Apply sheet crop", on_click=lambda ev: apply_sheet_crop_method())
    # Edit sheet crop dialog removed; main dialog contains inline edit controls now

    # edit_sheet_crop_btn is unused; main dialog fields replace the separate dialog
    tile_w_field = ft.TextField(label="Tile width", value="8", width=140)
    tile_h_field = ft.TextField(label="Tile height", value="8", width=140)
    downscale_field = ft.TextField(label="Downscale (e.g. 1, 0.5)", value="1", width=140)
    edge_mode_field = ft.Dropdown(label="Edge handling", options=[ft.dropdown.Option("Trim to whole tiles"), ft.dropdown.Option("Pad to whole tiles"), ft.dropdown.Option("Include partial tiles")], value="Trim to whole tiles", width=260)
    prefix_field = ft.TextField(label="Filename prefix", value="sheet", width=260)
    skip_empty_cb = ft.Checkbox(label="Skip empty tiles", value=True)
    crop_tiles_cb = ft.Checkbox(label="Crop tile blank borders", value=True)
    transparent_bg_cb = ft.Checkbox(label="Make background transparent", value=False)
    status_import = ft.Text("")
    warn_preview = ft.Text("", color="red")
    # preview_container will hold a Row with wrap enabled so thumbnails naturally wrap
    preview_container = ft.Row(spacing=6, wrap=True)
    # single sheet-level manual cropping override: (left, top, right, bottom) or None
    sheet_crop_override = None
    # remember the original sheet path chosen by the user (not currently used)

    def _tile_bbox(im, tol=20, alpha_thresh=16):
        """Shared helper: return tight bbox (left,top,right,bottom) for non-empty pixels in image `im`,
        supporting multiple pixel formats and alpha handling. Returns None if tile appears empty.
        """
        try:
            w2, h2 = im.size
            px = im.load()

            def to_rgba(v):
                try:
                    if isinstance(v, tuple):
                        if len(v) >= 4:
                            return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))
                        elif len(v) == 3:
                            return (int(v[0]), int(v[1]), int(v[2]), 255)
                        elif len(v) == 2:
                            return (int(v[0]), int(v[0]), int(v[0]), int(v[1]))
                    elif isinstance(v, (int, float)):
                        iv = int(v)
                        return (iv, iv, iv, 255)
                except Exception:
                    pass
                return (0, 0, 0, 255)

            def to_rgb3(v):
                r, g, b, a = to_rgba(v)
                return (r, g, b)

            # quick alpha detection
            has_alpha = False
            for yy in range(min(4, h2)):
                for xx in range(min(4, w2)):
                    try:
                        if to_rgba(px[xx, yy])[3] < 255:
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
                            r, g, b, a = to_rgba(px[xx, yy])
                            if a >= alpha_thresh:
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
                            r, g, b, a = to_rgba(px[xx, yy])
                            if a >= alpha_thresh:
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
                return (left, top, right + 1, bottom + 1)

            # no alpha path: sample border colour and find differing pixels
            border_samples = []
            for xx in range(w2):
                try:
                    border_samples.append(to_rgb3(px[xx, 0]))
                except Exception:
                    pass
                try:
                    border_samples.append(to_rgb3(px[xx, h2 - 1]))
                except Exception:
                    pass
            for yy in range(h2):
                try:
                    border_samples.append(to_rgb3(px[0, yy]))
                except Exception:
                    pass
                try:
                    border_samples.append(to_rgb3(px[w2 - 1, yy]))
                except Exception:
                    pass
            if border_samples:
                bgc = Counter(border_samples).most_common(1)[0][0]
            else:
                bgc = (255, 255, 255)

            def color_diff_sq(a, b):
                return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2

            top = bottom = left = right = None
            for yy in range(h2):
                row_has = False
                for xx in range(w2):
                    try:
                        col = to_rgb3(px[xx, yy])
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
                        col = to_rgb3(px[xx, yy])
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
            return (left, top, right + 1, bottom + 1)
        except Exception:
            return None

    def _to_rgb3_from_value(v):
        try:
            if isinstance(v, tuple):
                if len(v) >= 3:
                    return (int(v[0]), int(v[1]), int(v[2]))
                elif len(v) == 2:
                    return (int(v[0]), int(v[0]), int(v[0]))
            elif isinstance(v, (int, float)):
                iv = int(v)
                return (iv, iv, iv)
        except Exception:
            pass
        return (255, 255, 255)

    def _make_bg_transparent(im, tol=20):
        """Return a copy of im with pixels similar to the corner/background color set transparent.
        Only pixels connected to the image border that are similar to the detected background
        colour will be made transparent. This prevents internal pixels that happen to match
        the background colour from becoming transparent.
        The function is resilient to pixel formats.
        """
        try:
            if im is None:
                return im
            w3, h3 = im.size

            # collect corner samples then pick the most common as background colour
            pts = [(0, 0), (w3 - 1, 0), (0, h3 - 1), (w3 - 1, h3 - 1)] if w3 > 0 and h3 > 0 else []
            corners = []
            for (cx, cy) in pts:
                try:
                    val = im.getpixel((cx, cy))
                    corners.append(_to_rgb3_from_value(val))
                except Exception:
                    pass
            bgc = Counter(corners).most_common(1)[0][0] if corners else (255, 255, 255)

            def similar_col_rgb(a, b, tol=tol):
                return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) <= (tol * tol)

            # Work on an RGBA copy
            tc = im.convert('RGBA').copy()
            tc_px = tc.load()

            # visited mask for flood-fill (0 = unseen, 1 = background-connected)
            visited = [[0] * w3 for _ in range(h3)]

            # stack for flood-fill; seed with border pixels that match bgc
            stack = []
            for x in range(w3):
                try:
                    col = _to_rgb3_from_value(tc_px[x, 0])
                    if similar_col_rgb(col, bgc):
                        stack.append((x, 0))
                        visited[0][x] = 1
                except Exception:
                    pass
                try:
                    col = _to_rgb3_from_value(tc_px[x, h3 - 1])
                    if similar_col_rgb(col, bgc) and visited[h3 - 1][x] == 0:
                        stack.append((x, h3 - 1))
                        visited[h3 - 1][x] = 1
                except Exception:
                    pass
            for y in range(h3):
                try:
                    col = _to_rgb3_from_value(tc_px[0, y])
                    if similar_col_rgb(col, bgc) and visited[y][0] == 0:
                        stack.append((0, y))
                        visited[y][0] = 1
                except Exception:
                    pass
                try:
                    col = _to_rgb3_from_value(tc_px[w3 - 1, y])
                    if similar_col_rgb(col, bgc) and visited[y][w3 - 1] == 0:
                        stack.append((w3 - 1, y))
                        visited[y][w3 - 1] = 1
                except Exception:
                    pass

            # 4-connected flood-fill
            while stack:
                x, y = stack.pop()
                # examine neighbours
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx = x + dx
                    ny = y + dy
                    if nx < 0 or ny < 0 or nx >= w3 or ny >= h3:
                        continue
                    if visited[ny][nx]:
                        continue
                    try:
                        ncol = _to_rgb3_from_value(tc_px[nx, ny])
                        if similar_col_rgb(ncol, bgc):
                            visited[ny][nx] = 1
                            stack.append((nx, ny))
                    except Exception:
                        pass

            # Set background-connected pixels to transparent only
            for yy in range(h3):
                for xx in range(w3):
                    try:
                        if visited[yy][xx]:
                            # preserve existing alpha if any by writing full transparent pixel
                            tc_px[xx, yy] = (0, 0, 0, 0)
                    except Exception:
                        pass
            return tc
        except Exception:
            return im

    # sheet crop dialog implementation removed — all crop editing is now inline in the main dialog

    def update_preview(ev=None):
        """Build a preview that matches the import pipeline: apply sheet crop, per-tile crop (if enabled), transparency filling and downscale.
        The preview thumbnails show the final tiles as they will be written (but limited to a reasonable display size).
        """
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
            img_full = Image.open(path).convert('RGBA')
            try:
                if sheet_crop_override:
                    img = img_full.crop(sheet_crop_override)
                else:
                    img = img_full
            except Exception:
                img = img_full

            sw, sh = img.size
            # decide how to handle edges when sheet is not an exact multiple of tile size
            try:
                mode = (edge_mode_field.value or '').lower()
            except Exception:
                mode = 'trim to whole tiles'
            import math
            if mode.startswith('trim'):
                cols = max(1, sw // tw)
                rows = max(1, sh // th)
                work_img = img
            elif mode.startswith('pad'):
                cols = max(1, math.ceil(sw / tw))
                rows = max(1, math.ceil(sh / th))
                # create a padded backing image of whole tiles
                try:
                    pad_bg = (0,0,0,0) if transparent_bg_cb.value else (255,255,255,255)
                except Exception:
                    pad_bg = (0,0,0,0)
                work_img = Image.new('RGBA', (cols*tw, rows*th), pad_bg)
                try:
                    work_img.paste(img, (0,0))
                except Exception:
                    pass
            else:
                # include partial tiles: iterate ceil sw/tw and sh/th but use original image (may crop smaller tiles)
                cols = max(1, math.ceil(sw / tw))
                rows = max(1, math.ceil(sh / th))
                work_img = img
            total = cols * rows
            warn_preview.value = f"{cols} cols x {rows} rows => {total} tiles"
            if total > 200:
                warn_preview.value = str(warn_preview.value) + " — large import, preview shows first 100"
            try:
                warn_preview.update()
            except Exception:
                pass

            max_preview = min(100, total)
            count = 0
            # no local tempfile use here

            try:
                downscale_f = float((downscale_field.value or '1').strip())
            except Exception:
                downscale_f = 1.0

            # use shared tile bbox helper for preview and import
            # (defined below as _tile_bbox)

            # build preview using the final tile output as in import
            for r in range(rows):
                for c in range(cols):
                    if count >= max_preview:
                        break
                    box = (c*tw, r*th, c*tw + tw, r*th + th)
                    try:
                        tile = work_img.crop(box).convert('RGBA')
                    except Exception:
                        tile = None
                    final_tile = tile
                    try:
                        if tile is not None and crop_tiles_cb.value:
                            tb = _tile_bbox(tile, tol=20, alpha_thresh=16)
                            if tb:
                                lpx, tpx, rpx, bpx = (int(tb[0]), int(tb[1]), int(tb[2]), int(tb[3]))
                                lpx = max(0, lpx)
                                tpx = max(0, tpx)
                                rpx = min(tile.width, rpx)
                                bpx = min(tile.height, bpx)
                                try:
                                    final_tile = tile.crop((lpx, tpx, rpx, bpx))
                                except Exception:
                                    final_tile = tile
                        # apply transparent background treatment same as import
                        if final_tile is not None and transparent_bg_cb.value:
                            try:
                                final_tile = _make_bg_transparent(final_tile, tol=20)
                            except Exception:
                                final_tile = final_tile

                        # apply downscale exactly as import
                        if final_tile is not None:
                            try:
                                df = float(downscale_field.value or '1')
                            except Exception:
                                df = 1.0
                            if abs(df - 1.0) > 1e-6:
                                try:
                                    resample = Image.Resampling.NEAREST
                                except Exception:
                                    resample = Image.NEAREST if hasattr(Image, 'NEAREST') else 0
                                nw = max(1, int(round(final_tile.width * df)))
                                nh = max(1, int(round(final_tile.height * df)))
                                try:
                                    final_tile = final_tile.resize((nw, nh), resample)
                                except Exception:
                                    pass

                        # optionally skip empty tiles from preview
                        if skip_empty_cb.value:
                            try:
                                tb_check = _tile_bbox(final_tile if final_tile is not None else tile, tol=20, alpha_thresh=16)
                                if tb_check is None:
                                    # don't display empty tiles in preview
                                    continue
                            except Exception:
                                pass

                        # decide display size: show the final tile size 1:1 so preview matches import
                        # do NOT upscale small tiles; only downscale very large tiles for UI
                        if final_tile is None:
                            display_img = None
                        else:
                            disp_w = final_tile.width
                            disp_h = final_tile.height
                            max_display = 64
                            # If the tile is larger than max_display on its largest side, downscale for UI
                            if max(disp_w, disp_h) > max_display:
                                try:
                                    scale = max_display / float(max(disp_w, disp_h))
                                    rdw = max(1, int(round(disp_w * scale)))
                                    rdh = max(1, int(round(disp_h * scale)))
                                    try:
                                        resamp = Image.Resampling.BICUBIC
                                    except Exception:
                                        resamp = Image.BICUBIC if hasattr(Image, 'BICUBIC') else 1
                                    display_img = final_tile.resize((rdw, rdh), resamp)
                                except Exception:
                                    display_img = final_tile
                            else:
                                # show actual final pixels, no upscaling
                                display_img = final_tile

                        if display_img is not None:
                            try:
                                buf = _io.BytesIO()
                                display_img.save(buf, format='PNG')
                                b64 = base64.b64encode(buf.getvalue()).decode('ascii')
                                # append directly to wrap container so items wrap automatically
                                preview_container.controls.append(ft.Container(content=ft.Image(src_base64=b64, width=display_img.width, height=display_img.height)))
                            except Exception:
                                pass
                        else:
                            # placeholder if tile missing
                            try:
                                preview_container.controls.append(ft.Container(content=ft.Text('n/a')))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    count += 1
                if count >= max_preview:
                    break

            # no row flushing needed with Wrap
            try:
                preview_container.update()
            except Exception:
                pass

            try:
                caption_text = 'Sheet crop: set' if sheet_crop_override else 'Sheet crop: none'
                preview_container.controls.append(ft.Row([ft.Text(caption_text)]))
            except Exception as ex:
                logger.exception(f"Failed to add sheet crop status: {ex}")
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
    def _suggest_downscale_to_16():
        try:
            try:
                tw_now = int((tile_w_field.value or '8').strip())
            except Exception:
                tw_now = None
            try:
                th_now = int((tile_h_field.value or '8').strip())
            except Exception:
                th_now = None
            if not tw_now and not th_now:
                return
            max_dim = max(tw_now or 0, th_now or 0) or 1
            suggested = min(1.0, 16.0 / float(max_dim))
            val = f"{suggested:.3f}".rstrip('0').rstrip('.')
            downscale_field.value = val
            try:
                downscale_field.update()
            except Exception:
                pass
        except Exception:
            pass

    def _on_tile_size_change(ev=None):
        try:
            _suggest_downscale_to_16()
        except Exception:
            pass
        try:
            update_preview()
        except Exception:
            pass

    try:
        tile_w_field.on_change = _on_tile_size_change
    except Exception:
        pass
    try:
        tile_h_field.on_change = _on_tile_size_change
    except Exception:
        pass
    try:
        downscale_field.on_change = update_preview
    except Exception:
        pass
    try:
        edge_mode_field.on_change = update_preview
    except Exception:
        pass
    try:
        sheet_crop_mode_field.on_change = lambda ev: apply_sheet_crop_method()
    except Exception:
        pass
    # ensure toggling these options updates the preview immediately
    try:
        crop_tiles_cb.on_change = update_preview
    except Exception:
        pass
    try:
        transparent_bg_cb.on_change = update_preview
    except Exception:
        pass
    try:
        skip_empty_cb.on_change = update_preview
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
                        auto_analyze()
                        auto_analyze()
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

    def show_help(ev=None):
        """Open a small help dialog explaining the import dialog controls."""
        help_lines = [
            "How the Import dialog works:\n",
            "- Choose file: select a sprite sheet image file to import.",
            "- Import from clipboard: paste an image from your clipboard (desktop or web).",
            "- Auto Analyze: heuristic grid detection; suggests tile size and sheet crop.",
            "- Sheet cropping: set a sheet-level crop (applied once before slicing).", 
            "  Modes: None, Snap to tiles (aligns to tile grid), Detect by border color.",
            "- Edge handling: Trim / Pad / Include partial tiles when sheet isn't exact multiple.",
            "- Crop tile blank borders: trims empty pixel borders per tile before saving.",
            "- Make background transparent: clears border-connected background pixels only.",
            "- Skip empty tiles: do not import tiles that contain no non-transparent pixels.",
            "- Downscale: applied to the final tile image (affects preview and output).",
            "- Preview: shows the final tiles as they will be written (wraps and shows first 100).",
        ]
        help_text = "\n".join(help_lines)
        help_dlg = ft.AlertDialog(title=ft.Text("Import dialog help"), content=ft.Text(help_text), actions=[ft.TextButton("Close", on_click=lambda e: page_local.open(IMPORT_DIALOG))])
        if page_local:
            page_local.open(help_dlg)

    help_btn = ft.TextButton("Help", on_click=show_help)

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

    def detect_sheet_border_crop(path, tol=18):
        """Detect a single-colour border around the sprite sheet and return a crop box in original coordinates or None.
        The detection chooses the most common border colour and finds the tight bbox of pixels that differ from it.
        """
        try:
            if not path or not os.path.exists(path):
                return None
            im = Image.open(path).convert('RGBA')
            bg = pick_background(im)
            px = im.load()
            w, h = im.size
            min_x = w
            min_y = h
            max_x = 0
            max_y = 0
            found = False
            for y in range(h):
                for x in range(w):
                    try:
                        p = px[x, y]
                        if not similar_color(p, bg, tol=tol):
                            found = True
                            if x < min_x:
                                min_x = x
                            if y < min_y:
                                min_y = y
                            if x > max_x:
                                max_x = x
                            if y > max_y:
                                max_y = y
                    except Exception:
                        pass
            if not found:
                return None
            # bounding box is inclusive [min_x, max_x], convert to crop box (left, top, right+1, bottom+1)
            return (max(0, min_x), max(0, min_y), min(w, max_x+1), min(h, max_y+1))
        except Exception:
            return None

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
        nonlocal sheet_crop_override
        path = (sheet_path_field.value or '').strip()
        if not path or not os.path.exists(path):
            warn_preview.value = "No file to analyze"
            try:
                warn_preview.update()
            except Exception:
                pass
            return
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
        # map inferred tile size back to original image coordinates
        try:
            scale_w = float(img.width) / float(best_img.width) if best_img.width else 1.0
            scale_h = float(img.height) / float(best_img.height) if best_img.height else 1.0
        except Exception:
            scale_w = scale_h = 1.0
        if cand_sizes:
            # choose median candidate in best_img coords and scale up
            cand = sorted(cand_sizes)[len(cand_sizes)//2]
            inferred = max(1, int(round(cand * scale_w)))
        else:
            if best_result['cols']>0:
                inferred = max(1, int(round(img.width / max(1, best_result['cols']))))
            elif best_result['rows']>0:
                inferred = max(1, int(round(img.height / max(1, best_result['rows']))))
            else:
                inferred = 8

        cs = best_result['col_starts']
        rs = best_result['row_starts']
        left = cs[0] if cs else 0
        # coordinates are currently in best_img (possibly scaled) coords; map back to original image
        left = cs[0] if cs else 0
        top = rs[0] if rs else 0
        right = (cs[-1] + (cand if cand_sizes else inferred)) if cs else best_img.width
        bottom = (rs[-1] + (cand if cand_sizes else inferred)) if rs else best_img.height
        left = max(0, left)
        top = max(0, top)
        right = min(best_img.width, right)
        bottom = min(best_img.height, bottom)
        try:
            # scale coordinates to original image size
            ol = int(round(left * scale_w))
            ot = int(round(top * scale_h))
            orr = int(round(right * scale_w))
            ob = int(round(bottom * scale_h))
            # clamp to original
            ol = max(0, min(img.width, ol))
            ot = max(0, min(img.height, ot))
            orr = max(0, min(img.width, orr))
            ob = max(0, min(img.height, ob))
            try:
                _cropped = img.crop((ol, ot, orr, ob))
            except Exception:
                _cropped = img
        except Exception:
            try:
                _cropped = best_img.crop((left, top, right, bottom))
            except Exception:
                _cropped = best_img

        # store the detected crop as a sheet-level override using original-image coords
        try:
            # snap the detected crop to tile boundaries so defaults align with tile grid
            try:
                # prefer explicit tile fields if valid integers
                tw_try = int((tile_w_field.value or '').strip())
            except Exception:
                tw_try = None
            try:
                th_try = int((tile_h_field.value or '').strip())
            except Exception:
                th_try = None
            tw_use = tw_try if (tw_try and tw_try > 0) else (int(inferred) if inferred else 1)
            th_use = th_try if (th_try and th_try > 0) else (int(inferred) if inferred else 1)

            def _snap_crop_to_tiles(l, t, r, b, tw, th, iw, ih):
                try:
                    if tw <= 0 or th <= 0:
                        return (l, t, r, b)
                    nl = max(0, (l // tw) * tw)
                    nt = max(0, (t // th) * th)
                    # ceil for right/bottom to include full tiles
                    nr = min(iw, ((r + tw - 1) // tw) * tw)
                    nb = min(ih, ((b + th - 1) // th) * th)
                    # ensure we still have a positive area
                    if nr <= nl or nb <= nt:
                        return (l, t, r, b)
                    return (nl, nt, nr, nb)
                except Exception:
                    return (l, t, r, b)

            try:
                ol_snapped, ot_snapped, orr_snapped, ob_snapped = _snap_crop_to_tiles(ol, ot, orr, ob, tw_use, th_use, img.width, img.height)
            except Exception:
                ol_snapped, ot_snapped, orr_snapped, ob_snapped = ol, ot, orr, ob

            sheet_crop_override = (ol_snapped, ot_snapped, orr_snapped, ob_snapped)
            logger.debug(f"Auto analyze detected sheet_crop_override={sheet_crop_override} (snapped by tile {tw_use}x{th_use}) for path={path}")
            try:
                # populate main dialog crop fields so the user sees the detected snapped values
                left_field_main.value = str(ol_snapped)
                top_field_main.value = str(ot_snapped)
                right_field_main.value = str(orr_snapped)
                bottom_field_main.value = str(ob_snapped)
                try:
                    left_field_main.update()
                except Exception:
                    pass
                try:
                    top_field_main.update()
                except Exception:
                    pass
                try:
                    right_field_main.update()
                except Exception:
                    pass
                try:
                    bottom_field_main.update()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                sheet_crop_status.value = 'set' if sheet_crop_override else 'none'
                try:
                    sheet_crop_status.update()
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            sheet_crop_override = None
        tile_w_field.value = str(inferred)
        tile_h_field.value = str(inferred)
        try:
            tile_w_field.update()
            tile_h_field.update()
        except Exception:
            pass
        try:
            # suggest a downscale so the imported tiles aim for 16x16
            try:
                _suggest_downscale_to_16()
            except Exception:
                pass
        except Exception:
            pass
        try:
            update_preview()
        except Exception:
            pass

    def apply_sheet_crop_method():
        """Apply the selected sheet crop method and populate the main crop fields and preview.
        Modes:
         - Snap to tiles: attempt to run auto_analyze (if needed) and snap the detected crop to tile multiples.
         - Detect by border color: detect a single-colour border and set crop to the inner bounds.
        """
        nonlocal sheet_crop_override

        path = (sheet_path_field.value or '').strip()
        if not path or not os.path.exists(path):
            warn_preview.value = "No valid sprite sheet selected"
            try:
                warn_preview.update()
            except Exception:
                pass
            return

        mode = (sheet_crop_mode_field.value or '').strip()
        mode_l = mode.lower()

        try:
            warn_preview.value = f"Sheet crop method: {mode}"
            try:
                warn_preview.update()
            except Exception:
                pass
            logger.debug(f"apply_sheet_crop_method selected mode={mode}")
        except Exception:
            pass

        # explicit 'None' clears the override
        if mode_l == 'none':
            sheet_crop_override = None
            try:
                left_field_main.value = ''
                top_field_main.value = ''
                right_field_main.value = ''
                bottom_field_main.value = ''
                try:
                    left_field_main.update()
                except Exception:
                    pass
                try:
                    top_field_main.update()
                except Exception:
                    pass
                try:
                    right_field_main.update()
                except Exception:
                    pass
                try:
                    bottom_field_main.update()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                sheet_crop_status.value = 'none'
                sheet_crop_status.update()
            except Exception:
                pass
            try:
                update_preview()
            except Exception:
                pass
            return

        # detect by border color
        if mode_l.startswith('detect'):
            crop = detect_sheet_border_crop(path)
            if crop:
                sheet_crop_override = crop
                try:
                    left_field_main.value = str(crop[0])
                    top_field_main.value = str(crop[1])
                    right_field_main.value = str(crop[2])
                    bottom_field_main.value = str(crop[3])
                    try:
                        left_field_main.update()
                    except Exception:
                        pass
                    try:
                        top_field_main.update()
                    except Exception:
                        pass
                    try:
                        right_field_main.update()
                    except Exception:
                        pass
                    try:
                        bottom_field_main.update()
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    sheet_crop_status.value = 'set'
                    sheet_crop_status.update()
                except Exception:
                    pass
                try:
                    update_preview()
                except Exception:
                    pass
                return
            else:
                warn_preview.value = "Border detection failed"
                try:
                    warn_preview.update()
                except Exception:
                    pass
                return

        # default: snap to tiles
        try:
            auto_analyze()
        except Exception:
            pass

        if not sheet_crop_override:
            warn_preview.value = 'No crop available to snap'
            try:
                warn_preview.update()
            except Exception:
                pass
            return

        # prefer explicit tile fields if valid
        try:
            tw_try = int((tile_w_field.value or '').strip())
        except Exception:
            tw_try = None
        try:
            th_try = int((tile_h_field.value or '').strip())
        except Exception:
            th_try = None
        tw_use = tw_try if (tw_try and tw_try > 0) else 1
        th_use = th_try if (th_try and th_try > 0) else 1

        try:
            l, t, r, b = sheet_crop_override
        except Exception:
            warn_preview.value = 'Invalid detected crop'
            try:
                warn_preview.update()
            except Exception:
                pass
            return

        def snap_box(lv, tv, rv, bv, tw, th, iw, ih):
            try:
                nl = max(0, (lv // tw) * tw)
                nt = max(0, (tv // th) * th)
                nr = min(iw, ((rv + tw - 1) // tw) * tw)
                nb = min(ih, ((bv + th - 1) // th) * th)
                if nr <= nl or nb <= nt:
                    return (lv, tv, rv, bv)
                return (nl, nt, nr, nb)
            except Exception:
                return (lv, tv, rv, bv)

        try:
            img = Image.open(path).convert('RGBA')
            iw, ih = img.size
        except Exception:
            iw = ih = None

        if iw and ih:
            try:
                new_box = snap_box(l, t, r, b, tw_use, th_use, iw, ih)
                sheet_crop_override = new_box
                left_field_main.value = str(new_box[0])
                top_field_main.value = str(new_box[1])
                right_field_main.value = str(new_box[2])
                bottom_field_main.value = str(new_box[3])
                try:
                    left_field_main.update()
                except Exception:
                    pass
                try:
                    top_field_main.update()
                except Exception:
                    pass
                try:
                    right_field_main.update()
                except Exception:
                    pass
                try:
                    bottom_field_main.update()
                except Exception:
                    pass
                try:
                    sheet_crop_status.value = 'set'
                    sheet_crop_status.update()
                except Exception:
                    pass
                try:
                    update_preview()
                except Exception:
                    pass
                return
            except Exception:
                pass

        warn_preview.value = 'No crop available to snap'
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
            try:
                mode = (edge_mode_field.value or '').lower()
            except Exception:
                mode = 'trim to whole tiles'
            import math
            if mode.startswith('trim'):
                cols = sw // tw
                rows = sh // th
                work_img = img
            elif mode.startswith('pad'):
                cols = max(1, math.ceil(sw / tw))
                rows = max(1, math.ceil(sh / th))
                try:
                    pad_bg = (0,0,0,0) if transparent_bg_cb.value else (255,255,255,255)
                except Exception:
                    pad_bg = (0,0,0,0)
                work_img = Image.new('RGBA', (cols*tw, rows*th), pad_bg)
                try:
                    work_img.paste(img, (0,0))
                except Exception:
                    pass
            else:
                cols = max(1, math.ceil(sw / tw))
                rows = max(1, math.ceil(sh / th))
                work_img = img
            # write imports into the centralized stamps dir
            base_stamps = stamps_dir
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
                        try:
                            tile = work_img.crop(box).convert('RGBA')
                        except Exception:
                            tile = None

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
                                tb = None
                                try:
                                    # sheet-level override has already been applied to the source image,
                                    # so compute bbox per-tile normally when requested
                                    tb = _tile_bbox(tile, tol=20, alpha_thresh=16)
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
                                            final_tile = _make_bg_transparent(final_tile, tol=20)
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

    # group sheet-cropping controls into an expandable panel
    # a small status control for current override state
    # main dialog crop controls so user can edit values without opening the crop dialog
    left_field_main = ft.TextField(label='Left (px)', width=100)
    top_field_main = ft.TextField(label='Top (px)', width=100)
    right_field_main = ft.TextField(label='Right (px)', width=100)
    bottom_field_main = ft.TextField(label='Bottom (px)', width=100)

    def _update_sheet_override_from_main_fields(ev=None):
        nonlocal sheet_crop_override
        try:
            lf = (left_field_main.value or '').strip()
            tf = (top_field_main.value or '').strip()
            rf = (right_field_main.value or '').strip()
            bf = (bottom_field_main.value or '').strip()
            if lf == '' and tf == '' and rf == '' and bf == '':
                sheet_crop_override = None
            else:
                try:
                    lvi = int(lf) if lf != '' else 0
                    tvi = int(tf) if tf != '' else 0
                    # attempt to clamp to the actual image if available
                    path_now = (sheet_path_field.value or '').strip()
                    if path_now and os.path.exists(path_now):
                        try:
                            im_tmp = Image.open(path_now)
                            iw, ih = im_tmp.size
                        except Exception:
                            iw = ih = None
                    else:
                        iw = ih = None
                    rvi = int(rf) if rf != '' else (iw if iw is not None else 0)
                    bvi = int(bf) if bf != '' else (ih if ih is not None else 0)
                    if iw is not None:
                        lvi = max(0, min(iw, lvi))
                        tvi = max(0, min(ih, tvi))
                        rvi = max(0, min(iw, rvi))
                        bvi = max(0, min(ih, bvi))
                    if rvi <= lvi or bvi <= tvi:
                        sheet_crop_override = None
                    else:
                        sheet_crop_override = (lvi, tvi, rvi, bvi)
                except Exception:
                    sheet_crop_override = None
        except Exception:
            pass
        try:
            sheet_crop_status.value = 'set' if sheet_crop_override else 'none'
            try:
                sheet_crop_status.update()
            except Exception:
                pass
        except Exception:
            pass
        try:
            update_preview()
        except Exception:
            pass

    def _main_reset(ev=None):
        try:
            left_field_main.value = ''
            top_field_main.value = ''
            right_field_main.value = ''
            bottom_field_main.value = ''
            try:
                try:
                    left_field_main.update()
                except Exception:
                    pass
                try:
                    top_field_main.update()
                except Exception:
                    pass
                try:
                    right_field_main.update()
                except Exception:
                    pass
                try:
                    bottom_field_main.update()
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass
        try:
            nonlocal sheet_crop_override
            sheet_crop_override = None
        except Exception:
            pass
        try:
            sheet_crop_status.value = 'set' if sheet_crop_override else 'none'
            try:
                sheet_crop_status.update()
            except Exception:
                pass
        except Exception:
            pass
        try:
            update_preview()
        except Exception:
            pass

    # wire main fields to update the override live
    try:
        left_field_main.on_change = _update_sheet_override_from_main_fields
        top_field_main.on_change = _update_sheet_override_from_main_fields
        right_field_main.on_change = _update_sheet_override_from_main_fields
        bottom_field_main.on_change = _update_sheet_override_from_main_fields
    except Exception:
        pass

    sheet_crop_status = ft.Text('none')
    # Put crop controls and sheet-crop method selector inside the expander
    sheet_crop_expander = ft.ExpansionTile(
            title=ft.Text('Sheet cropping'),
            controls=[
                ft.Container(content=ft.Row([ft.Text('Current override:'), sheet_crop_status], spacing=8), padding=0),
                ft.Container(content=ft.Row([
                    ft.Column([ft.Row([left_field_main, top_field_main], spacing=8), ft.Row([right_field_main, bottom_field_main], spacing=8)]),
                    ft.Column([ft.Row([edge_mode_field], spacing=8)]),
                    ft.Column([ft.ElevatedButton('Apply', on_click=_update_sheet_override_from_main_fields), ft.TextButton('Reset', on_click=_main_reset)]),
                ], spacing=12), padding=0),
                ft.Container(content=ft.Row([sheet_crop_mode_field, apply_sheet_crop_btn], spacing=8), padding=0),
            ],
        )

    content = ft.Column([
        ft.Row([sheet_path_field, choose_btn, auto_analyze_btn, help_btn], spacing=8),
        ft.Row([clipboard_btn], spacing=8),
        sheet_crop_expander,
        ft.Row([tile_w_field, tile_h_field, prefix_field], spacing=8),
        ft.Row([downscale_field, skip_empty_cb, crop_tiles_cb, transparent_bg_cb], spacing=8),
        ft.Container(content=ft.Row([ft.Text('Status:'), warn_preview], spacing=8), padding=0),
        status_import,
        ft.Container(content=ft.Column([preview_container], scroll=ft.ScrollMode.AUTO, height=360), width=680),
    ], spacing=8, width=700, height=600)
    import_dlg = ft.AlertDialog(title=ft.Text("Import Sprite Sheet"), content=content, actions=[ft.TextButton("Import", on_click=do_import), ft.TextButton("Cancel", on_click=lambda ev: page_local.close(import_dlg))], open=False)
    global IMPORT_DIALOG
    IMPORT_DIALOG = import_dlg
    if page_local:
        page_local.open(import_dlg)
