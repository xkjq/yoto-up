import flet as ft
import threading
from pathlib import Path
import json
from loguru import logger
import os
import tempfile
import base64

from yoto_up.models import TrackDisplay, ChapterDisplay
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR, FLET_APP_STORAGE_DATA, USER_ICONS_DIR
from yoto_up.yoto_app.icon_import_helpers import get_base64_from_path
from yoto_up.yoto_app.pixel_art_editor import PixelArtEditor

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
        # Show the "also replace first track icon" option only when replacing a chapter icon
        if self.kind == 'chapter':
            apply_to_first_track = ft.Checkbox(label='Also replace first track icon', value=True)
        else:
            apply_to_first_track = None
        max_searches_field = ft.TextField(label='Max extra searches', value='2', width=120)
        top_n_field = ft.TextField(label='Top N results', value='10', width=120)
        results_list = ft.ListView(expand=True, spacing=6, height=420)
        # Progress indicator and status for searches
        search_progress = ft.ProgressRing(width=24, visible=False)
        search_status = ft.Text('', size=12)

        # Selected-icon preview (hidden when no selection). Will be shown next to the "Selected icon" button.
        preview_label = ft.Text("Selected icon", size=12, weight=ft.FontWeight.BOLD, visible=False)
        preview_image = ft.Image(src='', width=32, height=32, visible=False, fit=ft.ImageFit.CONTAIN)
        preview_name = ft.Text('', size=12, visible=False)
        # pack preview into a small column
        preview_column = ft.Column([preview_label, preview_image, preview_name], alignment=ft.MainAxisAlignment.CENTER, visible=True)

        def _schedule_page_update():
            """Schedule a page update on the Flet event loop (safe from background threads)."""
            try:
                # prefer async update routed through the page event loop
                try:
                    self.page.run_async(self.page.update_async())
                    return
                except Exception:
                    pass
                # last-resort synchronous update (may raise if called from wrong thread)
                try:
                    self.page.update()
                except Exception:
                    pass
            except Exception:
                pass

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
                    _schedule_page_update()

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
                    _schedule_page_update()
                    icons = self.api.find_best_icons_for_text(q or default_text or ' ', include_yotoicons=inc, max_searches=mx, top_n=topn)
                    if not icons:
                        results_list.controls.append(ft.Text('No icons found', selectable=True))
                    else:
                        for icon in icons:
                            img_src = None
                            url_src = None
                            try:
                                if icon.get('mediaId'):
                                    p = self.api.get_icon_cache_path(f"yoto:#{icon.get('mediaId')}")
                                    if p and Path(p).exists():
                                        img_src = p
                                if not img_src and icon.get('cache_path') and Path(icon.get('cache_path')).exists():
                                    img_src = Path(icon.get('cache_path'))
                                if not img_src and icon.get('url'):
                                    url_src = icon.get('url')
                                if not img_src and icon.get('img_url'):
                                    url_src = icon.get('img_url')
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
                                       # Optionally also apply to the first track of this chapter
                                        try:
                                            if apply_to_first_track and apply_to_first_track.value:
                                                if getattr(target_ch, 'tracks', None) and len(target_ch.tracks) > 0:
                                                    first_tr = target_ch.tracks[0]
                                                    if not getattr(first_tr, 'display', False):
                                                        first_tr.display = TrackDisplay()
                                                    first_tr.display.icon16x16 = f"yoto:#{media_id}"
                                        except Exception:
                                            pass
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
                            if url_src is not None:
                                img = ft.Image(src=url_src, width=48, height=48)
                                row_children.append(ft.GestureDetector(content=img, on_tap=use_icon))
                            elif img_src is not None:
                                try:
                                    img = ft.Image(src_base64=get_base64_from_path(img_src), width=48, height=48)
                                    row_children.append(ft.GestureDetector(content=img, on_tap=use_icon))
                                except Exception as ex:
                                    logger.exception(f"Failed to load icon image: {ex}")
                                    placeholder = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                                    row_children.append(ft.GestureDetector(content=placeholder, on_tap=use_icon, mouse_cursor=ft.MouseCursor.CLICK))
                            else:
                                placeholder = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                                row_children.append(ft.GestureDetector(content=placeholder, on_tap=use_icon, mouse_cursor=ft.MouseCursor.CLICK))
                            title_text = icon.get('title') or icon.get('id') or icon.get('displayIconId') or str(icon)
                            row_children.append(ft.Column([ft.Text(title_text, selectable=True), ft.Text(', '.join(icon.get('tags', [])[:5]) if icon.get('tags') else '')]))
                            row_children.append(ft.ElevatedButton('Use', on_click=use_icon))
                            results_list.controls.append(ft.Row(row_children, alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
                    _schedule_page_update()
                except Exception as e:
                    results_list.controls.append(ft.Text(f'Search failed: {e}'))
                    _schedule_page_update()
                finally:
                    # hide progress indicator and re-enable button regardless of outcome
                    try:
                        search_progress.visible = False
                        search_status.value = ''
                        search_btn.disabled = False
                    except Exception:
                        pass
                    _schedule_page_update()
            threading.Thread(target=search_worker, daemon=True).start()
    # create a button variable so the worker thread can disable/enable it
        search_btn = ft.TextButton('Search', on_click=do_search)

        # --- My Icons (saved by PixelArtEditor) tab content --------------------------------
        saved_icons_list = ft.ListView(expand=True, spacing=6, height=420)

        def refresh_saved_icons():
            """Scan saved_icons folder and populate saved_icons_list with preview + actions."""
            saved_icons_list.controls.clear()
            try:
                saved_dir = USER_ICONS_DIR
                if not saved_dir.exists():
                    try:
                        saved_dir.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        logger.exception(f"Failed to create saved_icons directory: {e}")
                        saved_icons_list.controls.append(ft.Text("No saved_icons folder"))
                        return
                # if empty, seed some basic stamps
                try:
                    has_files = any(p.suffix.lower() in ('.png', '.json') for p in saved_dir.iterdir())
                except Exception:
                    has_files = False
                if not has_files:
                    files = []
                else: 
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
                                       # Optionally also apply to the first track of this chapter
                                        try:
                                            if apply_to_first_track and apply_to_first_track.value:
                                                if getattr(target_ch, 'tracks', None) and len(target_ch.tracks) > 0:
                                                    first_tr = target_ch.tracks[0]
                                                    if not getattr(first_tr, 'display', False):
                                                        first_tr.display = TrackDisplay()
                                                    first_tr.display.icon16x16 = f"yoto:#{media_id}"
                                        except Exception:
                                            pass
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
                        preview = ft.Image(src_base64=get_base64_from_path(p), width=48, height=48)
                    except Exception:
                        preview = ft.Container(width=48, height=48, bgcolor=ft.Colors.GREY_200)
                    row = ft.Row([
                        ft.Column([preview]),
                        ft.Column([ft.Text(p.name, selectable=True)]),
                        ft.Row([ft.ElevatedButton("Edit", on_click=make_edit(p)), ft.ElevatedButton("Use", on_click=make_use(p))])
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=12)
                    saved_icons_list.controls.append(row)
            except Exception as e:
                logger.exception(f"Failed to refresh saved icons: {e}")
                saved_icons_list.controls.append(ft.Text(f"Failed to read saved icons: {e}"))
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

        def update_preview(marked_path):
            """Synchronously update preview controls based on marked_path."""
            try:
                if not marked_path:
                    preview_label.visible = False
                    preview_image.visible = False
                    preview_image.src = ''
                    preview_name.visible = False
                    preview_name.value = ''
                    try:
                        self.page.update()
                    except Exception:
                        pass
                    return
                # determine src and visibility
                try:
                    abs_path = marked_path if os.path.isabs(marked_path) else os.path.abspath(marked_path)
                except Exception:
                    abs_path = marked_path
                show_it = False
                try:
                    if abs_path and (str(abs_path).startswith('http://') or str(abs_path).startswith('https://')):
                        preview_image.src = abs_path
                        show_it = True
                    elif abs_path and os.path.exists(abs_path):
                        preview_image.src_base64 = get_base64_from_path(abs_path)
                        show_it = True
                    else:
                        preview_image.src = ''
                        show_it = False
                except Exception:
                    preview_image.src = ''
                    show_it = False

                preview_label.visible = show_it
                preview_image.visible = show_it
                preview_name.value = os.path.basename(marked_path) if marked_path else ''
                preview_name.visible = show_it and bool(preview_name.value)
                try:
                    self.page.update()
                except Exception:
                    pass
            except Exception:
                try:
                    self.page.update()
                except Exception:
                    pass

        def use_selected_icon(ev=None):
            """Apply the icon path set on page.replace_icon_path (if any)."""
            def _worker():
                try:
                    marked = getattr(self.page, "replace_icon_path", None)
                    if not marked:
                        self.show_snack("No icon marked in browser", True)
                        return
                    pth = Path(marked)
                    icon_payload = None
                    # support JSON packages saved by PixelArtEditor
                    if pth.suffix.lower() == '.json':
                        try:
                            obj = json.loads(pth.read_text(encoding='utf-8') or '{}')
                            if isinstance(obj, dict):
                                if obj.get('png_base64'):
                                    icon_payload = {'png_base64': obj.get('png_base64'), 'title': (obj.get('metadata') or {}).get('title')}
                                elif obj.get('pixels'):
                                    # attempt to render pixels into png_base64 (best-effort)
                                    try:
                                        from PIL import Image as PILImage
                                        import io as _io, base64 as _b64
                                        pixels = obj.get('pixels')
                                        h = len(pixels)
                                        w = len(pixels[0]) if h else 0
                                        img = PILImage.new('RGBA', (w, h))
                                        for yy in range(h):
                                            for xx in range(w):
                                                c = pixels[yy][xx] if xx < len(pixels[yy]) else '#FFFFFF'
                                                if isinstance(c, str) and c.startswith('#'):
                                                    ch = c.lstrip('#')
                                                    if len(ch) == 3:
                                                        ch = ''.join([c*2 for c in ch])
                                                    r = int(ch[0:2], 16); g = int(ch[2:4], 16); b = int(ch[4:6], 16)
                                                    img.putpixel((xx, yy), (r, g, b, 255))
                                                else:
                                                    img.putpixel((xx, yy), (255,255,255,255))
                                        buf = _io.BytesIO()
                                        img.save(buf, format='PNG')
                                        icon_payload = {'png_base64': _b64.b64encode(buf.getvalue()).decode('ascii')}
                                    except Exception:
                                        icon_payload = None
                        except Exception:
                            icon_payload = None
                    elif pth.suffix.lower() == '.png':
                        try:
                            import base64
                            b = pth.read_bytes()
                            icon_payload = {'png_base64': base64.b64encode(b).decode('ascii')}
                        except Exception:
                            icon_payload = None
                    else:
                        # unknown file type - try to upload as cache_path if file exists
                        try:
                            if pth.exists():
                                icon_payload = {'cache_path': str(pth)}
                        except Exception:
                            icon_payload = None

                    if not icon_payload:
                        self.show_snack("Marked icon cannot be uploaded (no image data)", True)
                        return

                    uploaded = self._upload_icon_payload(icon_payload)
                    if not uploaded or not (isinstance(uploaded, dict) and uploaded.get('mediaId')):
                        self.show_snack("Upload failed or returned no mediaId", True)
                        return
                    media_id = uploaded.get('mediaId')
                    full = self.api.get_card(self.card.get('cardId') or self.card.get('id') or self.card.get('contentId'))
                    if self.kind == 'chapter':
                        target_ch = full.content.chapters[self.ch_i]
                        if not getattr(target_ch, 'display', False):
                            target_ch.display = ChapterDisplay()
                        target_ch.display.icon16x16 = f"yoto:#{media_id}"
                       # Optionally also apply to the first track of this chapter
                        try:
                            if apply_to_first_track and apply_to_first_track.value:
                                if getattr(target_ch, 'tracks', None) and len(target_ch.tracks) > 0:
                                    first_tr = target_ch.tracks[0]
                                    if not getattr(first_tr, 'display', False):
                                        first_tr.display = TrackDisplay()
                                    first_tr.display.icon16x16 = f"yoto:#{media_id}"
                        except Exception:
                            pass
                    else:
                        target_ch = full.content.chapters[self.ch_i]
                        target_tr = target_ch.tracks[self.tr_i]
                        if not getattr(target_tr, 'display', False):
                            target_tr.display = TrackDisplay()
                        target_tr.display.icon16x16 = f"yoto:#{media_id}"
                    self.api.update_card(full, return_card_model=False)
                    self.show_card_details(None, full)
                    self.show_snack("Applied marked icon")
                except Exception as ex:
                    logger.exception("use_selected_icon failed")
                    self.show_snack(f"Failed to apply marked icon: {ex}", True)
            threading.Thread(target=_worker, daemon=True).start()

        # Build a Tabs control inside the dialog so user can switch between Search and My Icons
        tabs = ft.Tabs(selected_index=0, tabs=[
            ft.Tab(text="Search", content=ft.Column([
                ft.Row([search_field, ft.Row([search_btn, search_progress, search_status])]),
                # build row dynamically so the apply_to_first_track checkbox is only placed when relevant
                (lambda: ft.Row(
                    [c for c in ([include_yoto] + ([apply_to_first_track] if apply_to_first_track else []) + [max_searches_field, top_n_field])]
                ))(),
                 results_list
             ], width=900, expand=True)),
            ft.Tab(text="My Icons", content=ft.Column([
                saved_icons_list
            ], width=900, expand=True))
        ], expand=True)

        # include a "Use marked icon" action so the user can apply the icon selected from the browser
        use_selected_btn = ft.TextButton("Selected icon", on_click=use_selected_icon)
        # include the preview_column above the tabs so it's visible when a selection exists
        # build dialog content without accidentally inserting None controls
        content_children = [tabs]
        if apply_to_first_track:
            # place the checkbox above the tabs (it is also included in the tabs' search row)
            content_children.insert(0, apply_to_first_track)

        self.dialog = ft.AlertDialog(
            title=ft.Text('Replace icon'),
            content=ft.Column(content_children, width=920),
            # place preview next to the selected-icon action so they are adjacent
            actions=[use_selected_btn, preview_column, ft.TextButton('Close', on_click=close_replace)],
        )

        self.page.open(self.dialog)
        # initialize preview to current page.replace_icon_path (if any)
        try:
            marked_now = getattr(self.page, "replace_icon_path", None)
            update_preview(marked_now)
        except Exception:
            pass
        # kick off the initial search and refresh saved icons
        do_search(None)
        refresh_saved_icons()
