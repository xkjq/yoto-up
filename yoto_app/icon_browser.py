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
from yoto_app.pixel_art_editor import PixelArtEditor

from .icon_import_helpers import list_icon_cache_files


def build_icon_browser_panel(page: ft.Page, api_ref: dict, ensure_api: Callable, show_snack: Callable):
    """Return a dict with 'panel' key containing a Flet Column for the icon browser.

    Features:
    - shows icons from .yoto_icon_cache and .yotoicons_cache
    - search box to filter cached icons
    - 'Search YotoIcons' button to trigger online search (uses ensure_api/api_ref)
    """
    # top-level panel: header + row with left (scrollable icons) and right (fixed details)
    panel_header = ft.Row([ft.Text("Icon Browser", size=20, weight=ft.FontWeight.BOLD)])

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

    # Source filter checkboxes
    cb_official = ft.Checkbox(label="Official", value=True, on_change=lambda e: do_filter())
    cb_yotoicons = ft.Checkbox(label="YotoIcons", value=True, on_change=lambda e: do_filter())
    cb_local = ft.Checkbox(label="Local", value=True, on_change=lambda e: do_filter())
    filter_row = ft.Row([cb_official, cb_yotoicons, cb_local], spacing=12)

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
            yoto_meta = Path('.yoto_icon_cache') / 'icon_metadata.json'
            user_meta = Path('.yoto_icon_cache') / 'user_icon_metadata.json'
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
                except Exception:
                    pass
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
                except Exception:
                    pass
            # yotoicons cache
            yotoicons_dir = Path('.yotoicons_cache')
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
                except Exception:
                    pass
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
                except Exception:
                    continue
        except Exception:
            pass
        _meta_loaded = True

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
                    if p.startswith('.yoto_icon_cache') or p.startswith('./.yoto_icon_cache'):
                        src = 'Official cache'
                    elif p.startswith('.yotoicons_cache') or p.startswith('./.yotoicons_cache'):
                        src = 'YotoIcons'
                    else:
                        src = 'Local'
                _meta_map[p] = meta
                _meta_source[p] = src

                name = os.path.basename(p).lower()
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

    def load_cached_icons():
        icons = []
        # official Yoto cached icons
        try:
            for f in list_icon_cache_files(cache_dir=".yoto_icon_cache"):
                icons.append(os.path.join(".yoto_icon_cache", f))
        except Exception:
            pass
        # yotoicons cache
        try:
            for f in list_icon_cache_files(cache_dir=".yotoicons_cache"):
                icons.append(os.path.join(".yotoicons_cache", f))
        except Exception:
            pass
        return icons

    def find_metadata_for_path(p: str):
        pth = Path(p)
        # official Yoto icons metadata
        try:
            yoto_meta = Path('.yoto_icon_cache') / 'icon_metadata.json'
            user_meta = Path('.yoto_icon_cache') / 'user_icon_metadata.json'
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
            yotoicons_dir = Path('.yotoicons_cache')
            global_meta = yotoicons_dir / 'yotoicons_global_metadata.json'
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
                if cp and Path(cp).name == pth.name:
                    return m, 'YotoIcons'
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
            name = os.path.basename(path)
            src_label = "Official cache" if path.startswith('.yoto_icon_cache') else ('YotoIcons' if path.startswith('.yotoicons_cache') else 'Local')

            # lookup metadata from in-memory index if available (fast), fallback to file lookup
            meta = _meta_map.get(path)
            meta_source = _meta_source.get(path)
            if meta is None and not _index_built:
                meta, meta_source = find_metadata_for_path(path)

            # show a larger preview above the smaller one for better inspection
            try:
                abs_path = src if os.path.isabs(src) else os.path.abspath(src)
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
                large_preview = ft.Image(src=abs_path, width=new_w, height=new_h, fit=ft.ImageFit.CONTAIN)
            except Exception:
                # final fallback
                large_preview = ft.Image(src=abs_path, width=160, height=160, fit=ft.ImageFit.CONTAIN)
            small_preview = ft.Image(src=src, width=16, height=16)
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
                # short description if present
                desc = meta.get('description') or meta.get('info')
                if desc:
                    details_panel.controls.append(ft.Text(f"{str(desc)[:300]}"))
            # Action buttons
            def set_selected(e, p=path):
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
        # Try to spawn a separate process running the editor so it appears in a new window
        try:
            import subprocess
            cmd = [sys.executable, "-m", "yoto_app.pixel_art_editor", "--load", path]
            kwargs = {"stdout": None, "stderr": None, "stdin": None, "close_fds": True, "start_new_session": True}
            # On Windows, request a new console window for clarity
            if os.name == 'nt':
                try:
                    kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
                except Exception:
                    pass
            subprocess.Popen(cmd, **kwargs)
            show_snack("Opened editor in a new window")
            return
        except Exception as ex_spawn:
            logger.debug(f"Failed to spawn new editor process ({ex_spawn}), falling back to in-app editor", exc_info=True)

        # Fallback: open editor in an in-app dialog (existing behavior)
        try:
            logger.debug("Opening icon editor in-app (fallback)")
            editor = PixelArtEditor()
            dlg = ft.AlertDialog(title=ft.Text("Icon Editor"), content=editor.container, open=True)
            page.dialog = dlg
            page.open(dlg)
            # Try to load metadata from index if available
            meta = _meta_map.get(path)
            meta_source = _meta_source.get(path)
            if meta is None and not _index_built:
                meta, meta_source = find_metadata_for_path(path)
            try:
                load_fn = getattr(editor, "load_icon", None)
                if callable(load_fn):
                    load_fn(path, metadata=meta)
            except Exception:
                logger.exception("Failed to load icon into in-app editor")
            page.update()
        except Exception as ex:
            logger.error(f"Failed to open icon editor: {ex}")

    def render_icons(icons):
        icons_container.controls.clear()
        for path in icons:
            try:
                img = ft.Image(src=path, width=64, height=64)
                # attach on_click in the constructor so Flet will register the handler
                def _on_click(e, p=path):
                    # small debug feedback
                    logger.debug(f"Icon clicked: {p}")
                    show_icon_details(p)
                btn = ft.Container(content=img, border_radius=6, padding=4, ink=True, on_click=_on_click)
                icons_container.controls.append(btn)
            except Exception:
                continue
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
            name = os.path.basename(p).lower()
            is_official = p.startswith('.yoto_icon_cache') or p.startswith('./.yoto_icon_cache')
            is_yotoicons = p.startswith('.yotoicons_cache') or p.startswith('./.yotoicons_cache')
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
                            yc = Path('.yotoicons_cache')
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
                                            # try under .yotoicons_cache with just the filename
                                            cand_path2 = Path('.yotoicons_cache') / Path(cp).name
                                            if cand_path2.exists():
                                                cand_path = cand_path2
                                    except Exception:
                                        pass
                                    if cand_path.exists():
                                        pth = str(cand_path)
                                # fallback: if we have a url hash, find any file in .yotoicons_cache starting with that hash
                                if not pth and url:
                                    try:
                                        h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                        yc = Path('.yotoicons_cache')
                                        if yc.exists():
                                            for f in yc.iterdir():
                                                if f.stem.startswith(h):
                                                    pth = str(f)
                                                    break
                                    except Exception:
                                        pass

                                if pth and os.path.exists(pth):
                                    discovered += 1
                                    _meta_map[pth] = m
                                    # build candidate list similar to build_index()
                                    cand = [Path(pth).name.lower()]
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
                                    _candidates[pth] = ordered
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

    return {"panel": panel}
