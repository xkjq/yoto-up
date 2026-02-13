import os
import threading
import sys
import json
import hashlib
from pathlib import Path
from difflib import SequenceMatcher
from typing import Callable

import flet as ft
from loguru import logger
from PIL import Image as PILImage
from .pixel_art_editor import PixelArtEditor

import base64

from .icon_import_helpers import (
    load_cached_icons,
    YOTO_METADATA_FILE,
    USER_METADATA_FILE,
    YOTOICONS_CACHE_DIR,
    YOTOICONS_METADATA_GLOBAL,
    path_is_official,
    path_is_yotoicons,
    source_label_for_path,
    get_base64_from_path,
)



def build_icon_browser_panel(page: ft.Page, api_ref: dict, ensure_api: Callable, show_snack: Callable):
    """Return a dict with 'panel' key containing a Flet Column for the icon browser.

    Features:
    - shows icons from yoto_icon_cache and yotoicons_cache
    - search box to filter cached icons
    - 'Search YotoIcons' button to trigger online search (uses ensure_api/api_ref)
    """
    # top-level panel: header + row with left (scrollable icons) and right (fixed details)
    panel_header = ft.Row([ft.Text("Icon Browser", size=20, weight=ft.FontWeight.BOLD),
                           ft.Button("Refresh Index", on_click=lambda e: build_index())])

    search_row = ft.Row([], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    search_field = ft.TextField(label="Search cached icons", width=400, on_submit=lambda e: do_filter(), on_change=lambda e: schedule_filter())
    online_search_btn = ft.ElevatedButton("Search YotoIcons online", on_click=lambda e: do_online_search())
    # keep the main search field and the online search button in the top row; the Filter button
    # will be visually grouped with the fuzzy controls below for clarity.
    # Group fuzzy controls + filter button into a bordered container so it's clear they belong together.
    search_btn = ft.TextButton("Filter", on_click=lambda e: do_filter())
    cb_fuzzy = ft.Checkbox(label="Fuzzy match", value=False, on_change=lambda e: do_filter())
    threshold_field = ft.TextField(label="Threshold", value="0.6", width=80, tooltip="Match threshold 0..1 (higher = stricter)")
    fuzzy_group = ft.Container(
        content=ft.Row([cb_fuzzy, threshold_field, search_btn], spacing=8),
        padding=8,
        border=ft.border.all(1, "#E0E0E0"),
        border_radius=6,
    )
    search_row.controls.extend([search_field, fuzzy_group, online_search_btn])

    # Source filter checkboxes + live counts
    cb_official = ft.Checkbox(label="Official", value=True, on_change=lambda e: do_filter())
    cb_yotoicons = ft.Checkbox(label="YotoIcons", value=True, on_change=lambda e: do_filter())
    cb_local = ft.Checkbox(label="Local", value=True, on_change=lambda e: do_filter())
    # small text controls to display counts for each source
    official_count_text = ft.Text("0", size=12, color="#333333")
    yotoicons_count_text = ft.Text("0", size=12, color="#333333")
    local_count_text = ft.Text("0", size=12, color="#333333")
    filter_row = ft.Row([
        ft.Row([cb_official, official_count_text], alignment=ft.MainAxisAlignment.START),
        ft.Row([cb_yotoicons, yotoicons_count_text], alignment=ft.MainAxisAlignment.START),
        ft.Row([cb_local, local_count_text], alignment=ft.MainAxisAlignment.START),
    ], spacing=18)

    icons_container = ft.GridView(expand=True, max_extent=80, child_aspect_ratio=1)

    # Details panel on the right (fixed column)
    details_panel = ft.Column([ft.Text("Select an icon to see details", size=14)], spacing=8)

    # status indicator shown under filters when long operations run
    status_text = ft.Text("", size=12, color="#1E90FF")

    # in-memory caches to avoid expensive repeated JSON reads and metadata parsing
    _meta_map = {}        # path -> metadata dict or None
    _meta_source = {}     # path -> source label string or None
    _candidates = {}      # path -> list of candidate lowercase strings
    _index_built = False

    # faster metadata lookup maps (built once) to avoid rereading JSON files per-icon
    _meta_by_filename = {}   # filename -> meta
    _meta_by_hash = {}       # url-hash -> meta
    _meta_by_filename_source = {}  # filename -> 'Yoto'|'YotoIcons'
    _meta_by_hash_source = {}
    _meta_loaded = False
    _debounce_timer = None

    def load_all_metadata():
        """Load all metadata JSON files once and build quick lookup maps.
        Populates _meta_by_filename and _meta_by_hash. Safe to call repeatedly.
        """
        nonlocal _meta_by_filename, _meta_by_hash, _meta_by_filename_source, _meta_by_hash_source, _meta_loaded
        if _meta_loaded:
            return
        logger.debug("load_all_metadata: loading metadata JSON files into memory")
        _meta_by_filename = {}
        _meta_by_hash = {}
        _meta_by_filename_source = {}
        _meta_by_hash_source = {}
        # official cache files
        try:
            yoto_meta = YOTO_METADATA_FILE
            user_meta = USER_METADATA_FILE
            if yoto_meta.exists():
                try:
                    metas = json.loads(yoto_meta.read_text(encoding='utf-8') or '[]')
                    for m in metas:
                        cp = m.get('cache_path') or m.get('cachePath')
                        if cp:
                            try:
                                _meta_by_filename[Path(cp).name] = m
                                _meta_by_filename_source[Path(cp).name] = 'Official cache'
                            except Exception:
                                pass
                        url = m.get('url') or m.get('img_url') or m.get('imgUrl')
                        if url:
                            try:
                                h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                _meta_by_hash[h] = m
                                _meta_by_hash_source[h] = 'Official cache'
                            except Exception:
                                pass
                except Exception as ex:
                    logger.exception(f"Error loading official metadata: {ex}")
            else:
                logger.debug(f"Official metadata file not found: {yoto_meta}")  
                    
            if user_meta.exists():
                try:
                    metas = json.loads(user_meta.read_text(encoding='utf-8') or '[]')
                    for m in metas:
                        cp = m.get('cache_path') or m.get('cachePath')
                        if cp:
                            try:
                                _meta_by_filename[Path(cp).name] = m
                                _meta_by_filename_source[Path(cp).name] = 'Official cache'
                            except Exception:
                                pass
                        url = m.get('url') or m.get('img_url') or m.get('imgUrl')
                        if url:
                            try:
                                h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                _meta_by_hash[h] = m
                                _meta_by_hash_source[h] = 'Official cache'
                            except Exception:
                                pass
                except Exception as ex:
                    logger.exception(f"Error loading official metadata: {ex}")
            else:
                logger.debug(f"User metadata file not found: {user_meta}")
            # yotoicons cache (use configured path)
            yotoicons_dir = YOTOICONS_CACHE_DIR
            global_meta = yotoicons_dir / 'yotoicons_global_metadata.json'
            if global_meta.exists():
                try:
                    metas = json.loads(global_meta.read_text(encoding='utf-8') or '[]')
                    for m in metas:
                        cp = m.get('cache_path') or m.get('cachePath')
                        if cp:
                            try:
                                _meta_by_filename[Path(cp).name] = m
                                _meta_by_filename_source[Path(cp).name] = 'YotoIcons'
                            except Exception:
                                pass
                        url = m.get('url') or m.get('img_url') or m.get('imgUrl')
                        if url:
                            try:
                                h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                _meta_by_hash[h] = m
                                _meta_by_hash_source[h] = 'YotoIcons'
                            except Exception:
                                pass
                except Exception as ex:
                    logger.exception(f"Error loading YotoIcons metadata: {ex}")
            for mf in yotoicons_dir.glob('*_metadata.json'):
                if mf.name == global_meta.name:
                    continue
                try:
                    metas = json.loads(mf.read_text(encoding='utf-8') or '[]')
                    for m in metas:
                        cp = m.get('cache_path') or m.get('cachePath')
                        if cp:
                            try:
                                _meta_by_filename[Path(cp).name] = m
                                _meta_by_filename_source[Path(cp).name] = 'YotoIcons'
                            except Exception:
                                pass
                        url = m.get('url') or m.get('img_url') or m.get('imgUrl')
                        if url:
                            try:
                                h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                _meta_by_hash[h] = m
                                _meta_by_hash_source[h] = 'YotoIcons'
                            except Exception:
                                pass
                except Exception as ex:
                    logger.exception(f"Error loading YotoIcons metadata: {ex}")
                    continue
            # If some YotoIcons metadata entries don't include an explicit cache_path
            # try to resolve them to actual files under the YOTOICONS cache dir by
            # matching the url hash to filenames. This makes metadata searchable even
            # when cache_path wasn't persisted in the metadata files.
            try:
                yc = yotoicons_dir
                if yc.exists():
                    for h, m in list(_meta_by_hash.items()):
                        try:
                            # look for a file in the yotoicons cache whose stem starts
                            # with the 16-char url hash; if found, register the
                            # filename -> metadata mapping so search/display works.
                            found = None
                            for f in yc.iterdir():
                                if f.is_file() and f.stem.startswith(h):
                                    found = f
                                    break
                            if found:
                                _meta_by_filename[found.name] = m
                                _meta_by_filename_source[found.name] = 'YotoIcons'
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception as ex:
            logger.exception(f"Error loading YotoIcons metadata: {ex}")
        _meta_loaded = True

    def update_filter_counts():
        """Update the numeric counts next to each source filter checkbox."""
        try:
            icons = load_cached_icons()
            off = 0
            yotoi = 0
            loc = 0
            for p in icons:
                try:
                    if path_is_official(p):
                        off += 1
                    elif path_is_yotoicons(p):
                        yotoi += 1
                    else:
                        loc += 1
                except Exception:
                    loc += 1
            official_count_text.value = str(off)
            yotoicons_count_text.value = str(yotoi)
            local_count_text.value = str(loc)
            try:
                page.update()
            except Exception:
                pass
        except Exception:
            pass

    def build_index():
        """Build in-memory index of metadata and candidate strings for each cached icon.
        Call this once on startup and after any online refresh to speed up filtering.
        """
        nonlocal _meta_map, _meta_source, _candidates, _index_built
        logger.debug("build_index: rebuilding metadata/candidate index")
        try:
            status_text.value = "Rebuilding index..."
            page.update()
        except Exception:
            pass

        # ensure metadata maps are loaded once
        load_all_metadata()
        _meta_map = {}
        _meta_source = {}
        _candidates = {}
        icons = load_cached_icons()
        for p in icons:
            try:
                # fast lookup using preloaded maps
                meta = None
                src = None
                try:
                    fname = Path(p).name
                    if fname in _meta_by_filename:
                        meta = _meta_by_filename.get(fname)
                        src = _meta_by_filename_source.get(fname)
                    else:
                        stem = Path(p).stem
                        # check for url-hash prefix matches; stem may start with the 16-char hash
                        maybe_hash = stem[:16]
                        if maybe_hash in _meta_by_hash:
                            meta = _meta_by_hash.get(maybe_hash)
                            src = _meta_by_hash_source.get(maybe_hash)
                except Exception:
                    meta = None
                    src = None
                # if no explicit source from metadata maps, infer from the path
                if not src:
                    src = source_label_for_path(p)
                _meta_map[p] = meta
                _meta_source[p] = src

                name = os.path.basename(str(p)).lower()
                cand = [name]
                if meta:
                    if meta.get('title'):
                        cand.append(str(meta.get('title')).lower())
                    if meta.get('author'):
                        cand.append(str(meta.get('author')).lower())
                    tags = meta.get('publicTags') or meta.get('tags')
                    if tags:
                        if isinstance(tags, list):
                            cand.append(" ".join([str(t).lower() for t in tags if t]))
                        else:
                            cand.append(str(tags).lower())
                    if meta.get('displayIconId'):
                        cand.append(str(meta.get('displayIconId')).lower())
                    if meta.get('id'):
                        cand.append(str(meta.get('id')).lower())
                    if meta.get('category'):
                        cand.append(str(meta.get('category')).lower())
                    if meta.get('url'):
                        cand.append(str(meta.get('url')).lower())
                    if meta.get('img_url'):
                        cand.append(str(meta.get('img_url')).lower())
                # dedupe while preserving order
                seen = set()
                ordered = []
                for s in cand:
                    if not s:
                        continue
                    if s not in seen:
                        seen.add(s)
                        ordered.append(s)
                _candidates[p] = ordered
            except Exception:
                _meta_map[p] = None
                _meta_source[p] = None
                _candidates[p] = [os.path.basename(p).lower()]
        _index_built = True
        try:
            status_text.value = ""
            page.update()
        except Exception:
            pass
        # update filter counts whenever the index is rebuilt
        try:
            update_filter_counts()
        except Exception:
            pass


    def find_metadata_for_path(p: str):
        pth = Path(p)
        # official Yoto icons metadata
        try:
            yoto_meta = YOTO_METADATA_FILE
            user_meta = USER_METADATA_FILE
            metas = []
            if yoto_meta.exists():
                metas += json.loads(yoto_meta.read_text(encoding='utf-8') or '[]')
            if user_meta.exists():
                metas += json.loads(user_meta.read_text(encoding='utf-8') or '[]')
            for m in metas:
                cp = m.get('cache_path') or m.get('cachePath')
                if cp:
                    if Path(cp).name == pth.name:
                        return m, 'Yoto'
                # sometimes metadata may include url; match by hash of url
                url = m.get('url')
                if url:
                    try:
                        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                        if pth.stem.startswith(url_hash):
                            return m, 'Yoto'
                    except Exception:
                        pass
        except Exception:
            pass

        # YotoIcons metadata
        try:
            yotoicons_dir = YOTOICONS_CACHE_DIR
            global_meta = YOTOICONS_METADATA_GLOBAL
            metas = []
            if global_meta.exists():
                metas += json.loads(global_meta.read_text(encoding='utf-8') or '[]')
            # also check any per-tag metadata files
            for mf in yotoicons_dir.glob('*_metadata.json'):
                if mf.name == global_meta.name:
                    continue
                try:
                    metas += json.loads(mf.read_text(encoding='utf-8') or '[]')
                except Exception:
                    continue
            for m in metas:
                cp = m.get('cache_path') or m.get('cachePath')
                if cp:
                    try:
                        if Path(cp).name == pth.name:
                            return m, 'YotoIcons'
                    except Exception:
                        pass
                img_url = m.get('img_url') or m.get('imgUrl')
                if img_url:
                    try:
                        url_hash = hashlib.sha256(img_url.encode()).hexdigest()[:16]
                        if pth.stem.startswith(url_hash):
                            return m, 'YotoIcons'
                    except Exception:
                        pass
        except Exception:
            pass

        return None, None

    def schedule_filter(delay: float = 0.5):
        """Debounce wrapper: schedule do_filter to run after `delay` seconds since the last keystroke."""
        nonlocal _debounce_timer
        try:
            if _debounce_timer is not None:
                try:
                    _debounce_timer.cancel()
                except Exception:
                    pass
            _debounce_timer = threading.Timer(delay, lambda: do_filter())
            _debounce_timer.daemon = True
            _debounce_timer.start()
        except Exception:
            # fallback to immediate
            do_filter()

    def show_icon_details(path: str):
        selected_icon_path[0] = path
        # Build a simple details view for the selected icon
        details_panel.controls.clear()
        logger.debug(f"show_icon_details: {path}")
        try:
            src = path
            name = os.path.basename(str(path))
            src_label = source_label_for_path(path)

            # lookup metadata from in-memory index if available (fast), fallback to file lookup
            meta = _meta_map.get(path)
            meta_source = _meta_source.get(path)
            if meta is None and not _index_built:
                meta, meta_source = find_metadata_for_path(path)

            # show a larger preview above the smaller one for better inspection
            try:
                try:
                    pp = Path(src)
                    abs_path = str(pp) if pp.is_absolute() else str(pp.resolve())
                except Exception:
                    abs_path = src
            except Exception:
                abs_path = src
            # try to scale the large preview while preserving aspect ratio (upscale if small, downscale if huge)
            try:
                max_dim = 160
                if os.path.exists(abs_path):
                    try:
                        with PILImage.open(abs_path) as im:
                            w, h = im.size
                        if w <= 0 or h <= 0:
                            raise Exception("invalid image dimensions")
                        ratio = max_dim / max(w, h)
                        new_w = max(1, int(w * ratio))
                        new_h = max(1, int(h * ratio))
                    except Exception:
                        # Pillow not available or failed -> fallback to a sensible fixed size
                        new_w, new_h = (min(160, 160), min(160, 160))
                else:
                    new_w, new_h = (min(160, 160), min(160, 160))
                large_preview = ft.Image(src_base64=get_base64_from_path(Path(abs_path)), width=new_w, height=new_h, fit=ft.ImageFit.CONTAIN)
            except Exception:
                # final fallback
                large_preview = ft.Image(src_base64=get_base64_from_path(Path(abs_path)), width=160, height=160, fit=ft.ImageFit.CONTAIN)
            small_preview = ft.Image(src_base64=get_base64_from_path(Path(src)), width=16, height=16)
            details_panel.controls.append(large_preview)
            details_panel.controls.append(small_preview)
            # show human-friendly title if available
            if meta and meta.get('title'):
                details_panel.controls.append(ft.Text(f"Title: {meta.get('title')}", weight=ft.FontWeight.BOLD))
            else:
                details_panel.controls.append(ft.Text(f"Name: {name}"))
            # source label: prefer metadata source if present
            final_src_label = meta_source or src_label
            details_panel.controls.append(ft.Text(f"Source: {final_src_label}"))
            # additional metadata fields
            if meta:
                if meta.get('author'):
                    details_panel.controls.append(ft.Text(f"Author: {meta.get('author')}"))
                # some yoto metadata uses 'publicTags' or 'tags'
                tags = meta.get('publicTags') or meta.get('tags')
                if tags:
                    if isinstance(tags, list):
                        tags_str = ", ".join([str(t) for t in tags if t])
                    else:
                        tags_str = str(tags)
                    details_panel.controls.append(ft.Text(f"Tags: {tags_str}"))
                # IDs
                if meta.get('displayIconId'):
                    details_panel.controls.append(ft.Text(f"DisplayIconId: {meta.get('displayIconId')}"))
                if meta.get('id'):
                    details_panel.controls.append(ft.Text(f"ID: {meta.get('id')}"))
                if meta.get('category'):
                    details_panel.controls.append(ft.Text(f"Category: {meta.get('category')}"))
                # short description if present
                desc = meta.get('description') or meta.get('info')
                if desc:
                    details_panel.controls.append(ft.Text(f"{str(desc)[:300]}"))
            # Action buttons
            def set_selected(e, p=path):
                logger.debug(f"set_selected: {p}")
                try:
                    # store selected path on the page so other dialogs (Replace dialog) can access it
                    setattr(page, "replace_icon_path", p)
                except Exception:
                    pass
                show_snack(f"Icon selected: {p}")

            def open_in_explorer(e, p=path):
                try:
                    # best-effort: open containing folder using system default
                    import subprocess
                    folder = os.path.dirname(os.path.abspath(p))
                    if os.name == 'nt':
                        subprocess.Popen(['explorer', folder])
                    elif sys.platform == 'darwin':
                        subprocess.Popen(['open', folder])
                    else:
                        subprocess.Popen(['xdg-open', folder])
                except Exception:
                    show_snack('Unable to open folder', True)

            btn_row = ft.Row([
                ft.ElevatedButton("Use this icon", on_click=set_selected),
                ft.TextButton("Open folder", on_click=open_in_explorer),
                ft.ElevatedButton("Edit Icon", on_click=lambda e: open_icon_editor())
            ])
            details_panel.controls.append(btn_row)
        except Exception:
            logger.error("show_icon_details: failed to load details")
            details_panel.controls.append(ft.Text("Failed to load details"))
        ## also open a dialog with the preview so the user definitely sees details
        #try:
        #    dlg_content = ft.Column([
        #        ft.Image(src=os.path.abspath(path), width=240, height=240),
        #        ft.Text(f"Name: {os.path.basename(path)}"),
        #        ft.Text(f"Source: {'Official cache' if path.startswith('.yoto_icon_cache') else ('YotoIcons' if path.startswith('.yotoicons_cache') else 'Local')}"),
        #    ], scroll=ft.ScrollMode.AUTO)
        #    dlg = ft.AlertDialog(title=ft.Text(os.path.basename(path)), content=dlg_content, actions=[ft.TextButton("Close", on_click=lambda e: page.close(dlg))], scrollable=True)
        #    page.open(dlg)
        #except Exception:
        #    pass
        page.update()

    selected_icon_path = [None]  # mutable container for selected icon path
    def open_icon_editor():
        logger.debug(f"open_icon_editor called, selected_icon_path={selected_icon_path[0]}")
        if not selected_icon_path[0]:
            return
        path = selected_icon_path[0]

        # Resolve metadata early (used for both tab and fallback)
        meta = _meta_map.get(path)
        meta_source = _meta_source.get(path)
        logger.debug(f"open_icon_editor: path={path} meta_source={meta_source}")
        if meta is None and not _index_built:
            try:
                meta, meta_source = find_metadata_for_path(path)
            except Exception:
                meta = None
        logger.debug(f"open_icon_editor: resolved meta_source={meta_source}")

        try:
            # Reuse an editor bound to the page if present; else create and attach one
            editor = getattr(page, "pixel_editor", None)
            if editor is None:
                editor = PixelArtEditor(page=page)
                page.pixel_editor = editor

            # Try to find a Tabs control on the page to host the editor tab
            tabs_control = None
            try:
                for c in getattr(page, "controls", []) or []:
                    if isinstance(c, ft.Tabs):
                        tabs_control = c
                        break
            except Exception:
                tabs_control = None

            if tabs_control:
                # Attach/select editor tab in Tabs
                try:
                    editor.attach_to_tabview(tabs_control, select=True, page=page)
                    page.update()
                    logger.debug("Editor tab attached/selected in Tabs control")
                except Exception:
                    logger.exception("Failed to attach/select editor tab; attempting fallback attach without selection")
                    try:
                        editor.attach_to_tabview(tabs_control, select=False, page=page)
                    except Exception:
                        logger.exception("Failed to attach editor tab")
            else:
                # No Tabs control found — fallback to opening editor in a dialog
                try:
                    dlg = ft.AlertDialog(title=ft.Text("Icon Editor"), content=editor.container, open=True)
                    page.dialog = dlg
                    page.open(dlg)
                    page.update()
                except Exception:
                    logger.exception("Failed to open editor dialog fallback")

            # Load the selected icon into the editor (tab or dialog)
            try:
                load_fn = getattr(editor, "load_icon", None)
                if callable(load_fn):
                    logger.debug(f"Loading icon into editor: {path} with metadata source={meta_source}")
                    load_fn(path, metadata=meta)
                    logger.debug("Icon loaded into editor")
                    page.update()
            except Exception:
                logger.exception("Failed to load icon into editor")
        except Exception:
            logger.exception("open_icon_editor failed")

    def render_icons(icons):
        icons_container.controls.clear()
        for path in icons:
            # Load b64 thumbnail image data for each icon
            try:

                img = ft.Image(src_base64=get_base64_from_path(path), width=64, height=64, tooltip=path.name, border_radius=5)
                # attach on_click in the constructor so Flet will register the handler
                def _on_click(e, p=path):
                    # small debug feedback
                    logger.debug(f"Icon clicked: {p}")
                    show_icon_details(p)
                btn = ft.Container(content=img, border_radius=6, padding=1, ink=True, on_click=_on_click, border=ft.border.all(1, "#ADACAC"))
                icons_container.controls.append(btn)
            except Exception as ex:
                logger.exception(f"Failed to load icon {path}: {ex}")
        page.update()

    def do_filter():
        q = (search_field.value or "").strip().lower()
        # Respect source filters
        include_official = bool(cb_official.value)
        include_yotoicons = bool(cb_yotoicons.value)
        include_local = bool(cb_local.value)
        include_fuzzy = bool(cb_fuzzy.value)
        logger.debug(f"do_filter: q='{q}' official={include_official} yotoicons={include_yotoicons} local={include_local} fuzzy={include_fuzzy}")

        # ensure index built for fast lookups
        if not _index_built:
            build_index()
        icons = load_cached_icons()
        filtered = []
        for p in icons:
            # p is a Path returned by load_cached_icons()
            try:
                name = p.name
            except Exception:
                name = os.path.basename(str(p))
            is_official = path_is_official(p)
            is_yotoicons = path_is_yotoicons(p)
            is_local = not (is_official or is_yotoicons)

            if is_official and not include_official:
                continue
            if is_yotoicons and not include_yotoicons:
                continue
            if is_local and not include_local:
                continue

            if q:
                # get prebuilt candidates (fast)
                candidates = _candidates.get(p, [name])

                if include_fuzzy:
                    try:
                        thresh = float((threshold_field.value or "0.6").strip())
                    except Exception:
                        thresh = 0.6
                    # compute best fuzzy ratio across candidates
                    best = 0.0
                    for c in candidates:
                        try:
                            r = SequenceMatcher(None, q, c).ratio()
                        except Exception:
                            r = 0.0
                        if r > best:
                            best = r
                    # allow substring hits even if ratio below threshold
                    if not any(q in c for c in candidates) and best < thresh:
                        continue
                else:
                    if not any(q in c for c in candidates):
                        continue

            filtered.append(p)

        render_icons(filtered)

    def do_online_search():
        # Run online search in a background thread to keep UI responsive
        def _worker():
            try:
                api = ensure_api(api_ref)
                if not api:
                    show_snack("API not available; authenticate first", error=True)
                    return
                # indicate search started
                try:
                    status_text.value = "Searching YotoIcons... (0 downloaded)"
                    page.update()
                except Exception:
                    pass
                # start a small monitor thread to report progress while the search runs
                monitor_stop = threading.Event()
                def _monitor():
                    prev = 0
                    while not monitor_stop.wait(0.7):
                        try:
                            yc = YOTOICONS_CACHE_DIR
                            cnt = 0
                            if yc.exists():
                                for f in yc.iterdir():
                                    if f.is_file():
                                        cnt += 1
                            if cnt != prev:
                                prev = cnt
                                try:
                                    status_text.value = f"Searching YotoIcons... ({cnt} files)"
                                    page.update()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                monitor_thread = threading.Thread(target=_monitor, daemon=True)
                monitor_thread.start()
                # use api.search_yotoicons to refresh cache and then list cached results
                try:
                    new_icons = api.search_yotoicons(search_field.value or "", show_in_console=False, return_new_only=True)

                    show_snack(f"YotoIcons search found {len(new_icons) if new_icons else 0} new icons")
                except Exception:
                    new_icons = None
                icons = load_cached_icons()
                # integrate returned metadata for newly downloaded icons into in-memory maps
                try:
                    discovered = 0
                    if new_icons:
                        for m in new_icons:
                            try:
                                cp = m.get('cache_path') or m.get('cachePath')
                                url = m.get('img_url') or m.get('imgUrl') or m.get('url')
                                # register in filename/hash maps regardless
                                if cp:
                                    try:
                                        fname = Path(cp).name
                                        _meta_by_filename[fname] = m
                                    except Exception:
                                        pass
                                if url:
                                    try:
                                        h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                        _meta_by_hash[h] = m
                                    except Exception:
                                        pass

                                # try to resolve the actual cached image path
                                pth = None
                                if cp:
                                    cand_path = Path(cp)
                                    if not cand_path.is_absolute():
                                        cand_path = Path('.').joinpath(cp)
                                    # if the path is like '.yotoicons_cache/xxx.png' normalize to local path
                                    try:
                                        if not cand_path.exists():
                                            # try under configured YOTOICONS_CACHE_DIR with just the filename
                                            cand_path2 = YOTOICONS_CACHE_DIR / Path(cp).name
                                            if cand_path2.exists():
                                                cand_path = cand_path2
                                    except Exception:
                                        pass
                                    if cand_path.exists():
                                        pth = cand_path
                                # fallback: if we have a url hash, find any file in .yotoicons_cache starting with that hash
                                if not pth and url:
                                    try:
                                        h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                        yc = YOTOICONS_CACHE_DIR
                                        if yc.exists():
                                            for f in yc.iterdir():
                                                if f.stem.startswith(h):
                                                    pth = f
                                                    break
                                    except Exception:
                                        pass
                                if pth and pth.exists():
                                    discovered += 1
                                    # Normalize to Path object (match load_cached_icons)
                                    ppath = Path(pth)
                                    _meta_map[ppath] = m
                                    # build candidate list similar to build_index()
                                    cand = [ppath.name.lower()]
                                    if m.get('title'):
                                        cand.append(str(m.get('title')).lower())
                                    if m.get('author'):
                                        cand.append(str(m.get('author')).lower())
                                    tags = m.get('publicTags') or m.get('tags')
                                    if tags:
                                        if isinstance(tags, list):
                                            cand.append(" ".join([str(t).lower() for t in tags if t]))
                                        else:
                                            cand.append(str(tags).lower())
                                    if m.get('displayIconId'):
                                        cand.append(str(m.get('displayIconId')).lower())
                                    if m.get('id'):
                                        cand.append(str(m.get('id')).lower())
                                    if m.get('category'):
                                        cand.append(str(m.get('category')).lower())
                                    if m.get('url'):
                                        cand.append(str(m.get('url')).lower())
                                    if m.get('img_url'):
                                        cand.append(str(m.get('img_url')).lower())
                                    # dedupe while preserving order
                                    seen = set()
                                    ordered = []
                                    for s in cand:
                                        if not s:
                                            continue
                                        if s not in seen:
                                            seen.add(s)
                                            ordered.append(s)
                                    _candidates[ppath] = ordered
                            except Exception as e:
                                logger.error(f"do_online_search: failed to integrate metadata for one icon: {e}")
                    # If any new files were discovered on disk, force metadata reload before rebuilding index
                    if discovered:
                        _meta_loaded = False
                except Exception:
                    pass
                # render and notify (best-effort from background thread)
                try:
                    # rebuild index since search may have added new metadata/cache files
                    _index_built = False
                    # ensure metadata maps are reloaded from disk if needed
                    _meta_loaded = False
                    build_index()
                    # apply the current filter so the UI respects the user's active search/settings
                    try:
                        do_filter()
                    except Exception:
                        # fallback: render all cached icons if filtering fails
                        render_icons(icons)
                except Exception:
                    pass
                # stop the monitor thread and clear status
                try:
                    monitor_stop.set()
                except Exception:
                    pass
                try:
                    status_text.value = ""
                    page.update()
                except Exception:
                    pass
            except Exception:
                show_snack("YotoIcons search failed", True)

        threading.Thread(target=_worker, daemon=True).start()

    # build left panel (search + source filters + icons) and make it scrollable independently
    left_panel = ft.Column([search_row, filter_row, status_text, ft.Divider(), icons_container], scroll=ft.ScrollMode.AUTO, expand=True)

    # container for the right details column (fixed width)
    detail_container = ft.Container(content=details_panel, width=320)

    # main row: left is scrollable list, right is fixed details
    main_row = ft.Row([
        ft.Container(content=left_panel, expand=True),
        ft.VerticalDivider(),
        detail_container,
    ], expand=True)

    panel = ft.Column([panel_header, main_row], expand=True)
    # do initial load
    render_icons(load_cached_icons())

    # Register a callback on the page so external refreshers (e.g. GUI auth
    # refresh thread) can notify the icon browser that caches finished
    # refreshing. Callbacks should rebuild the in-memory index and re-run
    # the active filter so the displayed icons reflect updated caches.
    try:
        def _on_cache_refreshed():
            nonlocal _meta_loaded, _index_built
            try:
                _meta_loaded = False
                _index_built = False
                # rebuild index from disk and re-apply current filter
                build_index()
                try:
                    do_filter()
                except Exception:
                    render_icons(load_cached_icons())
            except Exception:
                pass
        # support multiple listeners
        if not hasattr(page, 'icon_cache_refreshed_callbacks'):
            page.icon_cache_refreshed_callbacks = []
        page.icon_cache_refreshed_callbacks.append(_on_cache_refreshed)
    except Exception:
        pass

    return {"panel": panel}