import flet as ft
import threading
from pathlib import Path
import json
from loguru import logger
import os
import tempfile
import base64

from models import TrackDisplay, ChapterDisplay
from yoto_app.pixel_art_editor import PixelArtEditor

class IconReplaceDialog:
    def __init__(self, api, card, page, show_snack, show_card_details, kind='chapter', ch_i=None, tr_i=None):
        self.api = api
        self.card = card
        self.page = page
        self.show_snack = show_snack
        self.show_card_details = show_card_details
        self.kind = kind
        self.ch_i = ch_i
        self.tr_i = tr_i
        self.dialog = None

    def _upload_icon_payload(self, payload):
        """Robust upload helper for various saved-icon payload shapes.
        Accepts payloads containing:
         - 'cache_path' pointing to a PNG on disk
         - 'png_base64' (Base64 PNG data)
         - other shapes accepted by self.api.upload_yotoicons_icon_to_yoto_api
        Returns the uploaded response dict on success, or None on failure.
        """
        try:
            if not payload or not isinstance(payload, dict):
                return None

            # If cache_path exists, try direct upload first
            cp = payload.get('cache_path') or payload.get('cachePath')
            if cp:
                try:
                    if os.path.exists(cp):
                        return self.api.upload_yotoicons_icon_to_yoto_api(payload)
                except Exception:
                    logger.debug(f"upload: direct cache_path upload attempt failed for {cp}", exc_info=True)

            # If png_base64 present, write to temp file and retry with cache_path
            b64 = payload.get('png_base64') or payload.get('pngBase64') or payload.get('pngbase64')
            title = payload.get('title') or (payload.get('metadata') or {}).get('title') if isinstance(payload.get('metadata'), dict) else payload.get('title')
            if b64:
                try:
                    data = base64.b64decode(b64)
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                        tf.write(data)
                        tmp_path = tf.name
                    try:
                        # Prefer passing cache_path as some API helpers expect a file on disk
                        res = self.api.upload_yotoicons_icon_to_yoto_api({'cache_path': tmp_path, 'title': title})
                        return res
                    except Exception:
                        # Last attempt: pass original payload (some implementations accept png_base64 directly)
                        try:
                            return self.api.upload_yotoicons_icon_to_yoto_api(payload)
                        except Exception:
                            logger.exception("upload: failed to upload png_base64 payload")
                            return None
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                except Exception:
                    logger.exception("upload: failed to decode/write png_base64")
                    return None

            # Final attempt: try API with given payload
            try:
                return self.api.upload_yotoicons_icon_to_yoto_api(payload)
            except Exception:
                logger.exception("upload: final upload attempt failed")
                return None
        except Exception:
            logger.exception("Unexpected error in _upload_icon_payload")
            return None

    def open(self):
        default_text = ''
        if self.kind == 'chapter':
            try:
                ch = self.card.get('content', {}).get('chapters', [])[self.ch_i]
                default_text = ch.get('title','') if isinstance(ch, dict) else str(ch)
            except Exception:
                default_text = ''
        else:
            try:
                ch = self.card.get('content', {}).get('chapters', [])[self.ch_i]
                tr = ch.get('tracks', [])[self.tr_i]
                default_text = tr.get('title','') if isinstance(tr, dict) else ''
            except Exception:
                default_text = ''

        search_field = ft.TextField(label='Search text for icons', value=default_text, width=400)
        include_yoto = ft.Checkbox(label='Include YotoIcons', value=True)
        max_searches_field = ft.TextField(label='Max extra searches', value='2', width=120)
        top_n_field = ft.TextField(label='Top N results', value='10', width=120)
        results_list = ft.ListView(expand=True, spacing=6, height=420)
        # Progress indicator and status for searches
        search_progress = ft.ProgressRing(width=24, visible=False)
        search_status = ft.Text('', size=12)

        def do_search(_ev=None):
            def search_worker():
                try:
                    # show progress indicator and status
                    search_progress.visible = True
                    search_status.value = 'Searching...'
                    try:
                        search_btn.disabled = True
                    except Exception:
                        pass
                    self.page.update()

                    q = (search_field.value or '').strip()
                    try:
                        mx = int(max_searches_field.value or '2')
                    except Exception:
                        mx = 3
                    try:
                        topn = int(top_n_field.value or '5')
                    except Exception:
                        topn = 5
                    inc = bool(include_yoto.value)
                    results_list.controls.clear()
                    self.page.update()
                    icons = self.api.find_best_icons_for_text(q or default_text or ' ', include_yotoicons=inc, max_searches=mx, top_n=topn)
                    if not icons:
                        results_list.controls.append(ft.Text('No icons found', selectable=True))
                    else:
                        for icon in icons:
                            img_src = None
                            try:
                                if icon.get('mediaId'):
                                    p = self.api.get_icon_cache_path(f"yoto:#{icon.get('mediaId')}")
                                    if p and Path(p).exists():
                                        img_src = str(p)
                                if not img_src and icon.get('url'):
                                    img_src = icon.get('url')
                                if not img_src and icon.get('img_url'):
                                    img_src = icon.get('img_url')
                                if not img_src and icon.get('cache_path') and Path(icon.get('cache_path')).exists():
                                    img_src = icon.get('cache_path')
                            except Exception:
                                img_src = None

                            def use_icon(ev2, icon=icon):
                                def use_worker():
                                    # Perform upload (if required) using robust helper
                                    full = self.api.get_card(self.card.get('cardId') or self.card.get('id') or self.card.get('contentId'))
                                    media_id = icon.get('mediaId')
                                    if not media_id and 'id' in icon:
                                        uploaded = self._upload_icon_payload(icon)
                                        media_id = (uploaded.get('mediaId') if isinstance(uploaded, dict) else None)
                                    if not media_id:
                                        self.show_snack('Selected icon could not be uploaded or has no media id', error=True)
                                        return
                                    if self.kind == 'chapter':
                                        target_ch = full.content.chapters[self.ch_i]
                                        if not getattr(target_ch, 'display', False):
                                            target_ch.display = ChapterDisplay()
                                        target_ch.display.icon16x16 = f"yoto:#{media_id}"
                                    else:
                                        target_ch = full.content.chapters[self.ch_i]
                                        target_tr = target_ch.tracks[self.tr_i]
                                        if not getattr(target_tr, 'display', False):
                                            target_tr.display = TrackDisplay()
                                        target_tr.display.icon16x16 = f"yoto:#{media_id}"
                                    self.api.update_card(full, return_card_model=False)
                                    self.show_card_details(None, full)
                                threading.Thread(target=use_worker, daemon=True).start()

                            row_children = []
                            if img_src:
                                try:
                                    img = ft.Image(src=img_src, width=48, height=48)
                                    row_children.append(ft.GestureDetector(content=img, on_tap=use_icon))
                                except Exception:
                                    placeholder = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                                    row_children.append(ft.GestureDetector(content=placeholder, on_tap=use_icon, mouse_cursor=ft.MouseCursor.CLICK))
                            else:
                                placeholder = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                                row_children.append(ft.GestureDetector(content=placeholder, on_tap=use_icon, mouse_cursor=ft.MouseCursor.CLICK))
                            title_text = icon.get('title') or icon.get('id') or icon.get('displayIconId') or str(icon)
                            row_children.append(ft.Column([ft.Text(title_text, selectable=True), ft.Text(', '.join(icon.get('tags', [])[:5]) if icon.get('tags') else '')]))
                            row_children.append(ft.ElevatedButton('Use', on_click=use_icon))
                            results_list.controls.append(ft.Row(row_children, alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
                    self.page.update()
                except Exception as e:
                    results_list.controls.append(ft.Text(f'Search failed: {e}'))
                    self.page.update()
                finally:
                    # hide progress indicator and re-enable button regardless of outcome
                    try:
                        search_progress.visible = False
                        search_status.value = ''
                        search_btn.disabled = False
                    except Exception:
                        pass
                    self.page.update()
            threading.Thread(target=search_worker, daemon=True).start()
    # create a button variable so the worker thread can disable/enable it
        search_btn = ft.TextButton('Search', on_click=do_search)

        # --- My Icons (saved by PixelArtEditor) tab content --------------------------------
        saved_icons_list = ft.ListView(expand=True, spacing=6, height=420)

        def refresh_saved_icons():
            """Scan saved_icons folder and populate saved_icons_list with preview + actions."""
            saved_icons_list.controls.clear()
            try:
                saved_dir = Path('saved_icons')
                if not saved_dir.exists():
                    saved_icons_list.controls.append(ft.Text("No saved_icons folder"))
                    return
                files = sorted([p for p in saved_dir.iterdir() if p.suffix.lower() in ('.png', '.json')], key=lambda p: p.name)
                if not files:
                    saved_icons_list.controls.append(ft.Text("No saved icons found"))
                    return
                for p in files:
                    def make_use(pth):
                        def _use(ev):
                            def _worker():
                                try:
                                    # Attempt to construct an uploadable icon dict from saved file
                                    icon_payload = None
                                    if pth.suffix.lower() == '.json':
                                        try:
                                            obj = json.loads(pth.read_text(encoding='utf-8') or '{}')
                                            if isinstance(obj, dict):
                                                # Prefer an embedded png_base64 if present
                                                if obj.get('png_base64'):
                                                    icon_payload = {'png_base64': obj.get('png_base64'), 'title': (obj.get('metadata') or {}).get('title')}
                                                else:
                                                    # try to build payload from embedded pixels if present (fallback)
                                                    if obj.get('pixels'):
                                                        try:
                                                            from PIL import Image as PILImage
                                                            import io, base64 as _b64
                                                            pixels = obj.get('pixels')
                                                            h = len(pixels)
                                                            w = len(pixels[0]) if h else 0
                                                            img = PILImage.new('RGBA', (w, h))
                                                            for yy in range(h):
                                                                for xx in range(w):
                                                                    c = pixels[yy][xx] if xx < len(pixels[yy]) else '#FFFFFF'
                                                                    if isinstance(c, str) and c.startswith('#'):
                                                                        c_hex = c.lstrip('#')
                                                                        if len(c_hex) == 3:
                                                                            c_hex = ''.join([ch*2 for ch in c_hex])
                                                                        r = int(c_hex[0:2], 16); g = int(c_hex[2:4], 16); b = int(c_hex[4:6], 16)
                                                                        img.putpixel((xx, yy), (r, g, b, 255))
                                                                    else:
                                                                        img.putpixel((xx, yy), (255,255,255,255))
                                                            buf = io.BytesIO()
                                                            img.save(buf, format='PNG')
                                                            png_b64 = _b64.b64encode(buf.getvalue()).decode('ascii')
                                                            icon_payload = {'png_base64': png_b64}
                                                        except Exception:
                                                            icon_payload = None
                                        except Exception:
                                            pass
                                    if icon_payload is None and pth.suffix.lower() == '.png':
                                        try:
                                            import base64
                                            b = pth.read_bytes()
                                            icon_payload = {'png_base64': base64.b64encode(b).decode('ascii')}
                                        except Exception:
                                            icon_payload = None

                                    if not icon_payload:
                                        self.show_snack("Cannot upload this saved icon (no image data)", True)
                                        return
                                    # upload via robust helper
                                    uploaded = self._upload_icon_payload(icon_payload)
                                    if not uploaded or not (isinstance(uploaded, dict) and uploaded.get('mediaId')):
                                        self.show_snack("Upload failed or returned no mediaId", True)
                                        return
                                    media_id = uploaded.get('mediaId')
                                    # apply to card (same logic as remote icons)
                                    full = self.api.get_card(self.card.get('cardId') or self.card.get('id') or self.card.get('contentId'))
                                    if self.kind == 'chapter':
                                        target_ch = full.content.chapters[self.ch_i]
                                        if not getattr(target_ch, 'display', False):
                                            target_ch.display = ChapterDisplay()
                                        target_ch.display.icon16x16 = f"yoto:#{media_id}"
                                    else:
                                        target_ch = full.content.chapters[self.ch_i]
                                        target_tr = target_ch.tracks[self.tr_i]
                                        if not getattr(target_tr, 'display', False):
                                            target_tr.display = TrackDisplay()
                                        target_tr.display.icon16x16 = f"yoto:#{media_id}"
                                    self.api.update_card(full, return_card_model=False)
                                    self.show_card_details(None, full)
                                except Exception as ex:
                                    self.show_snack(f"Failed to use saved icon: {ex}", True)
                            threading.Thread(target=_worker, daemon=True).start()
                        return _use

                    def make_edit(pth):
                        def _edit(ev):
                            try:
                                # Ensure a page-bound PixelArtEditor exists and load the saved icon
                                editor = getattr(self.page, 'pixel_editor', None)
                                if editor is None:
                                    editor = PixelArtEditor(page=self.page)
                                    self.page.pixel_editor = editor
                                # Try to attach/select editor tab if page contains Tabs
                                try:
                                    tabs_control = None
                                    for c in getattr(self.page, 'controls', []) or []:
                                        if isinstance(c, ft.Tabs):
                                            tabs_control = c
                                            break
                                    if tabs_control:
                                        editor.attach_to_tabview(tabs_control, select=True, page=self.page)
                                except Exception:
                                    pass
                                # load the icon into the editor
                                try:
                                    editor.load_icon(str(pth))
                                    self.page.update()
                                except Exception:
                                    pass
                            except Exception as ex:
                                self.show_snack(f"Failed to open editor: {ex}", True)
                        return _edit

                    # visual row for this saved icon
                    try:
                        preview = ft.Image(src=str(p.resolve()), width=48, height=48)
                    except Exception:
                        preview = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                    row = ft.Row([
                        ft.Column([preview]),
                        ft.Column([ft.Text(p.name, selectable=True)]),
                        ft.Row([ft.ElevatedButton("Edit", on_click=make_edit(p)), ft.ElevatedButton("Use", on_click=make_use(p))])
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=12)
                    saved_icons_list.controls.append(row)
            except Exception:
                saved_icons_list.controls.append(ft.Text("Failed to read saved icons"))
            self.page.update()
        # --- end saved-icons helpers ----------------------------------------------------

        # Refresh saved icons when dialog opens
        try:
            refresh_saved_icons()
        except Exception:
            pass

        def close_replace(_e=None):
            #self.page.(self.dialog)
            self.show_card_details(None, self.card)
            self.page.update()

        # Build a Tabs control inside the dialog so user can switch between Search and My Icons
        tabs = ft.Tabs(selected_index=0, tabs=[
            ft.Tab(text="Search", content=ft.Column([
                ft.Row([search_field, ft.Row([search_btn, search_progress, search_status])]),
                ft.Row([include_yoto, max_searches_field, top_n_field]),
                results_list
            ], width=900, expand=True)),
            ft.Tab(text="My Icons", content=ft.Column([
                saved_icons_list
            ], width=900, expand=True))
        ], expand=True)

        self.dialog = ft.AlertDialog(
            title=ft.Text('Replace icon'),
            content=ft.Column([tabs], width=920),
            actions=[ft.TextButton('Close', on_click=close_replace)],
        )
        self.page.open(self.dialog)
        # kick off the initial search and refresh saved icons
        do_search(None)
        try:
            refresh_saved_icons()
        except Exception:
            pass
