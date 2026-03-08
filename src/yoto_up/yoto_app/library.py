from yoto_up.yoto_app.api_manager import ensure_api
from yoto_up.yoto_app.ui_state import set_state, get_state
import sys
import threading
import asyncio
import json
import traceback
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING
from dataclasses import dataclass


import flet as ft

try:
    from pynput import keyboard

    _PYNPUT_AVAILABLE = True
except Exception:  # Broad because pyodide etc may raise weird errors
    _PYNPUT_AVAILABLE = False

import httpx
from yoto_up.models import Card, FamilyLibraryCard
from yoto_up.yoto_app.auth import delete_tokens_file, start_device_auth
from loguru import logger
import time
from yoto_up.yoto_api import YotoAPI

# Guard against duplicate/overlapping library fetches (many UI actions
# may trigger a refresh on startup). Use a simple lock + cooldown so that
# rapid repeated calls only perform one actual API request.
_library_fetch_lock = threading.Lock()
_library_last_fetch = 0.0
_library_fetch_cooldown = 2.0  # seconds

if TYPE_CHECKING:
    from yoto_up.gui import Page


@dataclass
class LibraryCheckboxData:
    cid: str
    idx: int | None


def _get_library_checkbox_control(ctrl: object) -> ft.Checkbox | None:
    data = getattr(ctrl, "data", None)
    if isinstance(ctrl, ft.Checkbox) and isinstance(data, LibraryCheckboxData):
        return ctrl
    return None


def card_matches_filters(card_obj: Card, filters: Dict[str, Any]):
    tf = (filters.get("title") or "").strip().lower()
    if tf:
        title = card_obj.title
        if tf not in str(title).lower():
            return False

    cat = (filters.get("category") or "").strip().lower()
    if cat:
        try:
            cval = (card_obj.get_category() or "").strip().lower()
            if cval != cat:
                return False
        except Exception:
            return False

    gf = (filters.get("genre") or "").strip().lower()
    if gf:
        want = {g.strip().lower() for g in gf.split(",") if g.strip()}
        try:
            card_genres = card_obj.get_genres()
            card_genres_set = {g.strip().lower() for g in (card_genres or []) if g}
            if not (want & card_genres_set):
                return False
        except Exception:
            return False

    tg = (filters.get("tags") or "").strip().lower()
    if tg:
        want_tags = {t.strip().lower() for t in tg.split(",") if t.strip()}
        try:
            card_tags = card_obj.get_tags()
            card_tags_set = {t.strip().lower() for t in (card_tags or []) if t}
            if not (want_tags & card_tags_set):
                return False
        except Exception:
            return False

    return True


def _extract_cover_source(card_item: Card, api_instance):
    logger.debug(f"Extracting cover source for card: {card_item.cardId}")
    meta = card_item.metadata
    if meta is None:
        return None
    cover = meta.cover
    if cover is None:
        return None
    v = cover.imageL
    if not v:
        return None
    return v


def make_library_row(page, card_obj: Card, idx=None, library_card: FamilyLibraryCard | None = None):
    logger.trace(f"Building row for card: {card_obj.cardId}")
    try:
        title = card_obj.get_title() or str(card_obj)
    except Exception:
        title = str(card_obj)
    cid = card_obj.cardId
    logger.trace(f"Card ID for row: {cid}")

    img_ctrl = ft.Container(width=64, height=64)
    api: YotoAPI = page.api_ref.get("api")
    try:
        cover_src = _extract_cover_source(card_obj, api_instance=api)
        logger.trace(f"Extracted cover source for card {cid}: {cover_src}")
        if cover_src is not None:
            logger.trace(f"Creating image control for cover {cover_src} of card {cid}")
            try:
                # Prefer cached local path from page helper if available
                cache_fn = getattr(page, "get_cached_cover", None)
                if callable(cache_fn) and str(cover_src).startswith("http"):
                    p = cache_fn(cover_src)
                    if p:
                        img_ctrl = ft.Image(src=str(p), width=64, height=64)
                    else:
                        img_ctrl = ft.Image(src=cover_src, width=64, height=64)
                else:
                    img_ctrl = ft.Image(src=str(cover_src), width=64, height=64)
            except Exception:
                logger.error(
                    f"Error creating image control for cover {cover_src} of card {cid}"
                )
                img_ctrl = ft.Image(src=str(cover_src), width=64, height=64)
        else:
            logger.debug(f"No cover source found for card {cid}")

    except Exception as e:
        logger.error(f"Error extracting cover for card {cid}")
        logger.debug(f"Exception details: {e}")

    logger.trace(
        f"Creating checkbox for card {cid} with multi-select mode {page.library_multi_select_mode}"
    )
    cb = ft.Checkbox(value=False)
    try:
        cb.visible = page.library_multi_select_mode
    except Exception:
        logger.error("Error setting checkbox visibility for multi-select mode")
    cb.data = LibraryCheckboxData(cid=cid or "", idx=idx)

    def _on_checkbox_change(ev):
        try:
            control = getattr(ev, "control", None) or ev
            is_checked = getattr(control, "value", None)
            if is_checked:
                page.selected_library_ids.add(cid)
            else:
                page.selected_library_ids.discard(cid)
            page.library_last_selected_index = idx
            page.update_library_multiselect_buttons()
            page.update()
        except Exception:
            logger.error("Error handling checkbox change event")

    cb.on_change = _on_checkbox_change

    def _on_tile_click(ev, card=card_obj, this_idx=idx):
        page.library_last_selected_index
        shift = page.shift_key_down

        if page.library_multi_select_mode:
            if shift and page.library_last_selected_index is not None and this_idx is not None:
                # Shift-select: select all between last_selected_index and this_idx
                start = min(page.library_last_selected_index, this_idx)
                end = max(page.library_last_selected_index, this_idx)
                for i in range(start, end + 1):
                    try:
                        row_ctrl = page.library_list.controls[i]
                        cb_found: ft.Checkbox | None = None
                        for child in getattr(row_ctrl, "controls", []):
                            checkbox_ctrl = _get_library_checkbox_control(child)
                            if checkbox_ctrl is not None:
                                cb_found = checkbox_ctrl
                                break
                        if cb_found:
                            cb_found.value = True
                            data = getattr(cb_found, "data", None)
                            if isinstance(data, LibraryCheckboxData):
                                page.selected_library_ids.add(data.cid)
                    except Exception:
                        pass
                page.update_library_multiselect_buttons()
                page.update()
                page.library_last_selected_index = this_idx
                return
            # Normal multi-select toggle
            cb_found: ft.Checkbox | None = None
            for child in row.controls:
                checkbox_ctrl = _get_library_checkbox_control(child)
                if checkbox_ctrl is not None:
                    cb_found = checkbox_ctrl
                    break
            if cb_found:
                cb_found.value = not cb_found.value
                if cb_found.value:
                    page.selected_library_ids.add(cid)
                else:
                    page.selected_library_ids.discard(cid)
                page.library_last_selected_index = this_idx
                page.update_library_multiselect_buttons()
                page.update()
            return
        # If not in multi-select, open details as before
        if shift and page.library_last_selected_index is not None and this_idx is not None:
            start = min(page.library_last_selected_index, this_idx)
            end = max(page.library_last_selected_index, this_idx)
            for i in range(start, end + 1):
                try:
                    row_ctrl = page.library_list.controls[i]
                    cb_found: ft.Checkbox | None = None
                    for child in getattr(row_ctrl, "controls", []):
                        checkbox_ctrl = _get_library_checkbox_control(child)
                        if checkbox_ctrl is not None:
                            cb_found = checkbox_ctrl
                            break
                        if hasattr(child, "content") and getattr(child, "content"):
                            for sub in (
                                getattr(child, "content").controls
                                if getattr(child, "content")
                                and hasattr(getattr(child, "content"), "controls")
                                else []
                            ):
                                nested_checkbox = _get_library_checkbox_control(sub)
                                if nested_checkbox is not None:
                                    cb_found = nested_checkbox
                                    break
                        if cb_found:
                            break
                    if cb_found:
                        try:
                            cb_found.value = True
                            data = getattr(cb_found, "data", None)
                            if isinstance(data, LibraryCheckboxData):
                                page.selected_library_ids.add(data.cid)
                        except Exception:
                            pass
                except Exception:
                    pass
            page.update_library_multiselect_buttons()
            page.update()
            page.library_last_selected_index = this_idx
            return
        page.show_card_details(card)

    # Compact preview of first few chapter titles
    preview = ""
    try:
        titles = card_obj.get_preview_titles(3)
        preview = "  •  ".join([t for t in (titles or []) if t])
    except Exception:
        preview = ""

    # Extract metadata fields for display
    try:
        tags = card_obj.get_tags() or []
        genres = card_obj.get_genres() or []
        category = card_obj.get_category() or ""
        author = card_obj.get_author() or ""
    except Exception:
        tags = []
        genres = []
        category = ""
        author = ""

    meta_line = []
    if author:
        meta_line.append(f"Author: {author}")
    if category:
        meta_line.append(f"Category: {category}")
    if genres:
        meta_line.append(f"Genres: {', '.join(genres)}")
    if tags:
        meta_line.append(f"Tags: {', '.join(tags)}")
    
    # Show library-specific info if available
    if library_card:
        if library_card.shareType:
            meta_line.append(f"Share: {library_card.shareType}")
        if library_card.lastPlayedAt:
            meta_line.append(f"Last Played: {library_card.lastPlayedAt[:10]}")  # Just date
    
    meta_text = (
        ft.Text(value=" | ".join(meta_line), size=12)
        if meta_line
        else None
    )

    # Show cardId and a short description (if present) beside it
    def _trunc(s, n=80):
        try:
            if not s:
                return ""
            s = str(s)
            return s if len(s) <= n else s[: n - 1] + "…"
        except Exception:
            return ""

    short_desc = ""
    try:
        short_desc = card_obj.get_short_description(80)
    except Exception:
        short_desc = ""

    # Subtitle contains preview, description and metadata; card id is shown on the row's right
    subtitle_items = []
    if preview:
        subtitle_items.append(ft.Text(value=preview, size=12))

    # Add truncated description as a subtitle line (if present)
    try:
        short_desc = card_obj.get_short_description(80)
    except Exception:
        short_desc = ""
    if short_desc:
        subtitle_items.append(ft.Text(value=short_desc, size=12))
    if meta_text:
        subtitle_items.append(meta_text)
    subtitle = ft.Column(controls=subtitle_items)
    tile = ft.ListTile(title=ft.Text(value=title), subtitle=subtitle, on_click=_on_tile_click)

    # Card ID placed to the right of the row (muted)
    id_text = ft.Text(value=str(cid), size=11)

    row = ft.Row(
        controls=[cb, img_ctrl, ft.Container(content=tile, expand=True), id_text],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    row.data = idx
    return row


def build_library_ui(page: "Page", library_cards=None):
    logger.debug("Building library UI")
    if library_cards is None:
        library_cards = page.library_cards
    logger.trace(page.library_cards)
    page.library_list.controls.clear()

    filters = page.get_library_filters()
    logger.debug(f"Applying filters: {filters} to {len(library_cards) if library_cards else 0} library cards")
    if not library_cards or library_cards is None:
        page.library_list.controls.append(ft.Text(value="No library items found"))
        page.update()
        return

    # Extract Card objects from FamilyLibraryCard wrappers
    cards = []
    library_card_map = {}  # Map card_id to FamilyLibraryCard for metadata
    for flc in library_cards:
        if flc.card:
            cards.append(flc.card)
            if flc.card.cardId:
                library_card_map[flc.card.cardId] = flc

    # Sort the cards
    sort_key = page.current_library_sort or "title_asc"

    def sort_func(c: Card):
        if "title" in sort_key:
            return (c.get_title() or "").strip().lower()
        elif "category" in sort_key:
            return (c.get_category() or "").strip().lower()
        elif "created" in sort_key:
            try:
                return c.createdAt or ""
            except Exception:
                return ""
        elif "updated" in sort_key:
            try:
                return c.updatedAt or ""
            except Exception:
                return ""
        return ""

    reverse = False
    if sort_key.endswith("_desc"):
        reverse = True
    elif sort_key.endswith("_asc"):
        reverse = False
    else:
        reverse = sort_key == "title_desc"
    sorted_cards = sorted(cards, key=sort_func, reverse=reverse)

    # Build rows for each card; only append valid ft.Control objects.
    for idx, c in enumerate(sorted_cards):
        if not card_matches_filters(c, filters):
            continue
        library_card = library_card_map.get(c.cardId)
        row = make_library_row(page, c, idx=idx, library_card=library_card)
        if row is not None and isinstance(row, ft.Control):
            page.library_list.controls.append(row)
        else:
            logger.error(f"make_library_row did not return a valid control for card {c.cardId}")
    page.update()


def fetch_library_sync(page):
    # Avoid overlapping / repeated fetches
    global _library_last_fetch
    now = time.time()
    if _library_fetch_lock.locked():
        logger.debug("fetch_library_sync: fetch already in progress; skipping")
        return
    if now - _library_last_fetch < _library_fetch_cooldown:
        logger.debug("fetch_library_sync: recent fetch within cooldown; skipping")
        return
    acquired = _library_fetch_lock.acquire(blocking=False)
    if not acquired:
        logger.debug("fetch_library_sync: failed to acquire lock; skipping")
        return
    _library_last_fetch = now
    try:
        page.show_snack("Fetching library...")
        page.update()
        api = page.api_ref.get("api")
        library_cards = api.get_family_library()
        page.library_cards = library_cards  # Cache library cards on page
        build_library_ui(page, library_cards=library_cards)
        page.show_snack(f"Fetched {len(library_cards)} library items")
        page.update()
    except httpx.HTTPError as http_ex:
        logger.error(f"HTTP error during fetch_library_sync: {http_ex}")
        logger.error(f"fetch_library_sync error: {http_ex}")
        traceback.print_exc(file=sys.stderr)
        if "401" in str(http_ex) or "403" in str(http_ex):
            page.show_snack("Authentication error. Please log in again.", error=True)
            delete_tokens_file()
            if hasattr(page, "invalidate_authentication"):
                page.invalidate_authentication()
            if hasattr(page, "switch_to_auth_tab"):
                page.switch_to_auth_tab()
            page.update()

    except Exception as ex:
        logger.error(f"fetch_library_sync error: {ex}")
        traceback.print_exc(file=sys.stderr)
        page.show_snack("Unable to fetch library", error=True)
    finally:
        try:
            _library_fetch_lock.release()
        except Exception:
            pass


def build_library_panel(
    page: "Page",
) -> Dict[str, Any]:
    """Build full library UI including rows, selection, dialogs and fetch helpers.

    This function mirrors the playlists panel but for family library content.
    Returns a dictionary of controls and helpers for integration with the main UI.
    """

    # Controls and state
    title_filter = ft.TextField(label="Title contains", width=200)
    genre_filter = ft.TextField(label="Genres (comma separated)", width=200)
    category_filter = ft.Dropdown(
        label="Category",
        width=200,
        value="",
        options=[
            ft.dropdown.Option(""),
            ft.dropdown.Option("none"),
            ft.dropdown.Option("stories"),
            ft.dropdown.Option("music"),
            ft.dropdown.Option("radio"),
            ft.dropdown.Option("podcast"),
            ft.dropdown.Option("sfx"),
            ft.dropdown.Option("activities"),
            ft.dropdown.Option("alarms"),
        ],
    )

    tags_filter = ft.TextField(label="Tags (comma separated)", width=200)
    filter_btn = ft.Button(content=ft.Text(value="Apply Filter"))
    clear_filter_btn = ft.TextButton(content="Clear")

    def _get_library_filters():
        return {
            "title": title_filter.value or "",
            "genre": genre_filter.value or "",
            "category": category_filter.value or "",
            "tags": tags_filter.value or "",
        }

    page.get_library_filters = _get_library_filters

    # Multi-select state for library
    page.library_last_selected_index = None
    page.library_multi_select_mode = False
    export_selected_btn = ft.Button(content=ft.Text(value="Export Selected"), disabled=True)
    export_selected_btn.visible = False

    api = ensure_api(page.api_ref)

    multi_select_btn = ft.Button(content=ft.Text(value="Select Multiple"))

    # Sorting control
    sort_options = [
        ft.dropdown.Option("title_asc", "Title (A-Z)"),
        ft.dropdown.Option("title_desc", "Title (Z-A)"),
        ft.dropdown.Option("category", "Category"),
        ft.dropdown.Option("created_desc", "Created (Newest)"),
        ft.dropdown.Option("created_asc", "Created (Oldest)"),
        ft.dropdown.Option("updated_desc", "Updated (Newest)"),
        ft.dropdown.Option("updated_asc", "Updated (Oldest)"),
    ]
    sort_dropdown = ft.Dropdown(
        label="Sort by",
        width=160,
        value=get_state("library_ui", "sort_order", "title_asc"),
        options=sort_options,
    )
    page.current_library_sort = sort_dropdown.value

    def on_sort_change(ev):
        page.current_library_sort = sort_dropdown.value
        build_library_ui(page)  # Rebuild UI with new sort order
        # save current ui state so it can be restored on restart
        set_state("library_ui", "sort_order", sort_dropdown.value)

    sort_dropdown.on_select = on_sort_change

    def _do_export_selected():
        to_export = list(page.selected_library_ids)
        if not to_export:
            return
        out_dir = Path("library_exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = 0
        for cid in to_export:
            try:
                card = api.get_card(cid)
                try:
                    data = card.model_dump(exclude_none=True)
                except Exception:
                    data = {}
                title = card.get_title()
                import re

                def _safe_filename(s: str) -> str:
                    if not s:
                        return cid
                    s = s.strip()
                    s = re.sub(r"[^0-9A-Za-z._-]+", "_", s)
                    return s[:100]

                name = _safe_filename(title)
                fname = out_dir / f"{name or cid}_{cid}.json"
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                exported += 1
            except Exception as e:
                print(f"[export] Failed to export {cid}: {e}")
        page.selected_library_ids.clear()
        export_selected_btn.disabled = True
        page.library_list.controls.clear()
        fetch_library_sync(page)
        page.show_snack(f"Exported {exported} cards to ./library_exports/")
        page.update()

    def _on_export_selected(ev):
        def confirm_yes(_e=None):
            page.pop_dialog()
            page.update()
            threading.Thread(target=_do_export_selected, daemon=True).start()

        def confirm_no(_e=None):
            page.pop_dialog()
            page.update()

        confirm_dialog = ft.AlertDialog(
            title=ft.Text(value="Export selected library items?"),
            content=ft.Text(value=
                f"Export {len(page.selected_library_ids)} selected library items to ./library_exports/?"
            ),
            actions=[
                ft.TextButton(content="Yes", on_click=confirm_yes),
                ft.TextButton(content="No", on_click=confirm_no),
            ],
        )
        page.show_dialog(confirm_dialog)

    export_selected_btn.on_click = _on_export_selected

    # Track shift key state globally (shared with playlists)
    if not hasattr(page, 'shift_key_down'):
        page.shift_key_down = False

    # For desktop: use pynput to track shift key globally
    def _start_shift_listener():
        if not _PYNPUT_AVAILABLE:
            return

        def on_press(key):
            try:
                if (
                    key == keyboard.Key.shift
                    or key == keyboard.Key.shift_l
                    or key == keyboard.Key.shift_r
                ):
                    page.shift_key_down = True
            except Exception:
                pass

        def on_release(key):
            try:
                if (
                    key == keyboard.Key.shift
                    or key == keyboard.Key.shift_l
                    or key == keyboard.Key.shift_r
                ):
                    page.shift_key_down = False
            except Exception:
                pass

        # Only start listener if not already running
        if not hasattr(page, '_shift_listener_started'):
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.daemon = True
            listener.start()
            page._shift_listener_started = True

    _start_shift_listener()

    library_list = ft.ListView(expand=True, spacing=6)
    page.library_list = library_list  # Expose for cross-module updates

    def _clean_controls():
        """Remove any invalid entries from UI control lists that may cause
        Flet to raise AssertionError when building update commands.

        This is defensive: some code paths previously appended None or
        non-Control objects into lists which breaks the Flet RPC layer.
        """
        try:
            # Keep only real ft.Control instances in library_list
            try:
                cleaned = [
                    c for c in library_list.controls if isinstance(c, ft.Control)
                ]
                if len(cleaned) != len(library_list.controls):
                    library_list.controls[:] = cleaned
            except Exception:
                pass
        except Exception:
            pass

    def _update_multiselect_buttons():
        """Central helper to set disabled state for multiselect action buttons."""
        try:
            disabled = len(page.selected_library_ids) == 0
            try:
                export_selected_btn.disabled = disabled
            except Exception:
                pass
            try:
                export_selected_btn.update()
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    page.update_library_multiselect_buttons = (
        _update_multiselect_buttons  # Expose for callbacks in library rows
    )

    def toggle_multi_select(ev=None):
        multi_select_mode = page.library_multi_select_mode

        multi_select_mode = not multi_select_mode
        multi_select_btn.content = ft.Text(value="Done" if multi_select_mode else "Select")
        export_selected_btn.visible = multi_select_mode
        select_all_btn.visible = multi_select_mode
        if not multi_select_mode:
            try:
                select_all_btn.content = ft.Text(value="Select all")
                select_all_btn.update()
            except Exception:
                pass
        if not multi_select_mode:
            page.selected_library_ids.clear()
            _update_multiselect_buttons()
        for row in library_list.controls:
            try:
                for child in getattr(row, "controls", []):
                    checkbox = _get_library_checkbox_control(child)
                    if checkbox is not None:
                        checkbox.visible = multi_select_mode
                        if not multi_select_mode:
                            try:
                                checkbox.value = False
                            except Exception:
                                pass
            except Exception:
                pass
        page.library_multi_select_mode = multi_select_mode
        page.update()

    multi_select_btn.on_click = toggle_multi_select

    # Select All / Deselect All control (visible only in multi-select mode)
    select_all_btn = ft.Button(content=ft.Text(value="Select all"), visible=False)
    select_all_selected = False

    def _set_all_checkboxes(value: bool):
        """Set all library row checkboxes to value (True=checked, False=unchecked)."""
        for row in library_list.controls:
            for child in getattr(row, "controls", []):
                checkbox = _get_library_checkbox_control(child)
                if checkbox is not None:
                    checkbox.value = value
                    checkbox.update()
                    data = checkbox.data
                    if isinstance(data, LibraryCheckboxData):
                        if value:
                            page.selected_library_ids.add(data.cid)
                        else:
                            page.selected_library_ids.discard(data.cid)

    page.set_all_library_checkboxes = (
        _set_all_checkboxes  # Expose for callbacks in library rows
    )

    def _select_all_toggle(ev=None):
        nonlocal select_all_selected
        try:
            if not select_all_selected:
                _set_all_checkboxes(True)
                select_all_btn.content = ft.Text(value="Deselect all")
                select_all_selected = True
            else:
                _set_all_checkboxes(False)
                select_all_btn.content = ft.Text(value="Select all")
                select_all_selected = False
            _update_multiselect_buttons()
            try:
                select_all_btn.update()
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    select_all_btn.on_click = _select_all_toggle

    async def apply_filters(ev=None):
        build_library_ui(page)

    def clear_filters(ev=None):
        try:
            title_filter.value = ""
            genre_filter.value = ""
            category_filter.value = ""
            tags_filter.value = ""
            page.update()
            page.run_task(apply_filters)
        except Exception:
            pass

    filter_btn.on_click = apply_filters
    clear_filter_btn.on_click = clear_filters

    # Header fetch button wired to the synchronous fetch helper
    fetch_btn = ft.Button(content=ft.Text(value="Fetch Library"), bgcolor="#2196F3", color="white")

    async def fetch_library(e=None):
        logger.debug("fetch_library: invoked")
        # Avoid overlapping / repeated fetches
        global _library_last_fetch
        now = time.time()
        if _library_fetch_lock.locked():
            # another fetch in progress; skip this invocation
            logger.debug("fetch_library: fetch already in progress; skipping")
            return
        if now - _library_last_fetch < _library_fetch_cooldown:
            logger.debug("fetch_library: recent fetch within cooldown; skipping")
            return
        acquired = _library_fetch_lock.acquire(blocking=False)
        if not acquired:
            logger.debug("fetch_library: failed to acquire lock; skipping")
            return
        _library_last_fetch = now
        # Clean any stale/invalid controls before touching the page
        _clean_controls()
        page.update()

        try:
            library_cards = await asyncio.to_thread(api.get_family_library)
            page.library_cards = library_cards  # Cache library cards on page
        except httpx.HTTPError as http_ex:
            logger.error(f"HTTP error during fetch_library: {http_ex}")
            traceback.print_exc(file=sys.stderr)
            if "401" in str(http_ex) or "403" in str(http_ex):
                try:
                    page.show_snack("Authentication error. Please log in again.", error=True)
                except Exception:
                    pass
                delete_tokens_file()
                if hasattr(page, "invalidate_authentication"):
                    page.invalidate_authentication()
                if hasattr(page, "switch_to_auth_tab"):
                    page.switch_to_auth_tab()
                # Kick off device auth flow to guide the user
                try:
                    start_device_auth(
                        page,
                        instr_container=getattr(page, "auth_instructions", None),
                        api_ref=page.api_ref,
                        show_snack_fn=getattr(page, "show_snack", None),
                    )
                except Exception as e:
                    logger.error(f"Failed to start device auth: {e}")
            return
        except Exception:
            logger.exception("fetch_library error")
            try:
                page.show_snack("Unable to fetch library", error=True)
            except Exception:
                pass
            return
        finally:
            try:
                _library_fetch_lock.release()
            except Exception:
                pass

        build_library_ui(page, library_cards)
        page.update()

    page.fetch_library = fetch_library  # Expose async fetch for external callers

    logger.debug("Setting up library UI controls and callbacks")
    fetch_btn.on_click = lambda: page.run_task(fetch_library)
    filter_btn.on_click = lambda: page.run_task(apply_filters)
    clear_filter_btn.on_click = lambda e: (
        setattr(title_filter, "value", ""),
        setattr(genre_filter, "value", ""),
        setattr(category_filter, "value", ""),
        page.run_task(apply_filters),
    )

    # Allow pressing Enter in any filter TextField to apply filters (same as Apply Filter)
    title_filter.on_submit = lambda: page.run_task(apply_filters)
    genre_filter.on_submit = lambda: page.run_task(apply_filters)
    tags_filter.on_submit = lambda: page.run_task(apply_filters)

    # Make filters row expandable using Accordion
    filters_panel = ft.ExpansionTile(
        title=ft.Container(
            content=ft.Text(value="Filters", size=12, weight=ft.FontWeight.W_400),
            padding=0,
            margin=0,
        ),
        controls=[
            ft.Container(
                content=ft.Row(
                    controls=[
                        title_filter,
                        genre_filter,
                        tags_filter,
                        category_filter,
                        filter_btn,
                        clear_filter_btn,
                    ],
                    wrap=True,
                    spacing=4,
                    alignment=ft.MainAxisAlignment.START,
                ),
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
                margin=ft.margin.only(left=4, right=4, bottom=2),
                border_radius=4,
                height=None,
                alignment=ft.Alignment.TOP_LEFT,
            )
        ],
    )

    page.fetch_library_sync = fetch_library_sync

    library_column = ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Text(value="Library"),
                    fetch_btn,
                    multi_select_btn,
                    select_all_btn,
                    export_selected_btn,
                    sort_dropdown,
                ],
                wrap=True,
                spacing=8,
                alignment=ft.MainAxisAlignment.START,
            ),
            filters_panel,
            ft.Divider(),
            library_list,
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    return {
        "library_column": library_column,
        "fetch_library": fetch_library,
        "library_list": library_list,
        "make_library_row": make_library_row,
        "export_selected_btn": export_selected_btn,
        "multi_select_btn": multi_select_btn,
    }
