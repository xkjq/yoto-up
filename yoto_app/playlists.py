import sys
import threading
from copy import deepcopy
import asyncio
import json
import traceback
from pathlib import Path
from typing import Any, Dict


import flet as ft
from yoto_app.icon_replace_dialog import IconReplaceDialog
from yoto_app.edit_card_dialog import show_edit_card_dialog
from yoto_app.replace_icons import show_replace_icons_dialog
from types import SimpleNamespace

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False

import httpx
from models import Card, CardMetadata, ChapterDisplay, TrackDisplay
from yoto_app.auth import delete_tokens_file
from yoto_app.config import CLIENT_ID
from loguru import logger
from yoto_app.logging_helpers import safe_log
import time
from yoto_api import YotoAPI



def build_playlists_panel(
    page: ft.Page,
    api_ref: Dict[str, Any],
    show_snack,
    ensure_api,
    status_ctrl=None,
    overall_bar=None,
    overall_text=None,
    file_rows_column=None,
) -> Dict[str, Any]:
    """Build full playlists UI including rows, selection, dialogs and fetch helpers.

    This function mirrors the original behaviour from `gui.py` but keeps
    all playlist-specific state inside this module. It requires a few injected
    controls (status, overall bar/text, file rows) which are used for cross-tab updates.
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
    filter_btn = ft.ElevatedButton(text="Apply Filter")
    clear_filter_btn = ft.TextButton(text="Clear")

    # Multi-select state for playlists
    selected_playlist_ids = set()
    last_selected_index = None
    multi_select_mode = False
    delete_selected_btn = ft.ElevatedButton(text="Delete Selected", disabled=True)
    delete_selected_btn.visible = False
    export_selected_btn = ft.ElevatedButton(text="Export Selected", disabled=True)
    export_selected_btn.visible = False
    # Import card controls
    import_picker = ft.FilePicker()
    # append picker to page overlay if page supports overlay (gui.py appends similar pickers)
    try:
        page.overlay.append(import_picker)
    except Exception:
        # page may be a SimpleNamespace in some tests; ignore if overlay isn't available
        pass
    import_card_btn = ft.ElevatedButton(text="Import Card(s)")
    multi_select_btn = ft.ElevatedButton(text="Select Multiple")
    add_tags_btn = ft.ElevatedButton(text="Add Tags to Selected", disabled=True)
    add_tags_btn.visible = False

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
        label="Sort by", width=160, value="title_asc", options=sort_options
    )
    current_sort = {"key": "title_asc"}

    def on_sort_change(ev):
        current_sort["key"] = sort_dropdown.value
        fetch_playlists_sync()

    sort_dropdown.on_change = on_sort_change

    # Track shift key state globally
    shift_key_down = {"value": False}

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
                    shift_key_down["value"] = True
            except Exception:
                pass

        def on_release(key):
            try:
                if (
                    key == keyboard.Key.shift
                    or key == keyboard.Key.shift_l
                    or key == keyboard.Key.shift_r
                ):
                    shift_key_down["value"] = False
            except Exception:
                pass

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()

    _start_shift_listener()

    playlists_list = ft.ListView(expand=True, spacing=6)
    existing_card_map = {}
    existing_card_dropdown = ft.Dropdown(label="Existing card", width=400, options=[])

    # Provide safe defaults for optional injected controls so callers that
    # don't pass them (older code paths) still work.
    if status_ctrl is None:
        status_ctrl = SimpleNamespace(value="")
    if overall_bar is None:
        overall_bar = SimpleNamespace(value=0, visible=False)
    if overall_text is None:
        overall_text = SimpleNamespace(value="")
    if file_rows_column is None:
        file_rows_column = SimpleNamespace(controls=[])

    def card_matches_filters(card_obj):
        try:
            if hasattr(card_obj, "model_dump"):
                d = card_obj.model_dump(exclude_none=True)
            elif isinstance(card_obj, dict):
                d = card_obj
            else:
                try:
                    d = json.loads(str(card_obj))
                except Exception:
                    d = {}
        except Exception:
            d = {}

        tf = (title_filter.value or "").strip().lower()
        if tf:
            title = (d.get("title") or "").lower()
            if tf not in title:
                return False

        cat = (category_filter.value or "").strip().lower()
        if cat:
            meta = d.get("metadata") or {}
            cval = (meta.get("category") or "").strip().lower()
            if cval != cat:
                return False

        gf = (genre_filter.value or "").strip().lower()
        if gf:
            want = {g.strip().lower() for g in gf.split(",") if g.strip()}
            meta = d.get("metadata") or {}
            card_genres = meta.get("genre") or meta.get("genres") or []
            if isinstance(card_genres, str):
                card_genres = [g.strip() for g in card_genres.split(",") if g.strip()]
            card_genres_set = {g.strip().lower() for g in card_genres if g}
            if not (want & card_genres_set):
                return False

        tg = (tags_filter.value or "").strip().lower()
        if tg:
            want_tags = {t.strip().lower() for t in tg.split(",") if t.strip()}
            meta = d.get("metadata") or {}
            card_tags = meta.get("tags") or []
            # sometimes tags may be stored in genres or as a comma string
            if not card_tags:
                card_tags = meta.get("genre") or meta.get("genres") or []
            if isinstance(card_tags, str):
                card_tags = [t.strip() for t in card_tags.split(",") if t.strip()]
            card_tags_set = {t.strip().lower() for t in card_tags if t}
            if not (want_tags & card_tags_set):
                return False

        return True

    def get_card_id_local(card):
        if hasattr(card, "cardId") and getattr(card, "cardId"):
            return getattr(card, "cardId")
        if hasattr(card, "id") and getattr(card, "id"):
            return getattr(card, "id")
        if hasattr(card, "contentId") and getattr(card, "contentId"):
            return getattr(card, "contentId")
        if isinstance(card, dict):
            return card.get("cardId") or card.get("id") or card.get("contentId")
        try:
            if hasattr(card, "model_dump"):
                d = card.model_dump(exclude_none=True)
                return d.get("cardId") or d.get("id") or d.get("contentId")
        except Exception:
            pass
        return None

    def _do_delete_selected():
        to_delete = list(selected_playlist_ids)
        if not to_delete:
            return
        client = CLIENT_ID
        api = ensure_api(api_ref, client)
        for cid in to_delete:
            try:
                api.delete_content(cid)
            except Exception as e:
                print(f"[delete] Failed to delete {cid}: {e}")
        selected_playlist_ids.clear()
        delete_selected_btn.disabled = True
        export_selected_btn.disabled = True
        playlists_list.controls.clear()
        fetch_playlists_sync(None)
        page.update()


    def _do_export_selected():
        to_export = list(selected_playlist_ids)
        if not to_export:
            return
        client = CLIENT_ID
        api = ensure_api(api_ref, client)
        out_dir = Path("cards")
        out_dir.mkdir(parents=True, exist_ok=True)
        exported = 0
        for cid in to_export:
            try:
                card = api.get_card(cid)
                try:
                    data = card.model_dump(exclude_none=True) if hasattr(card, 'model_dump') else dict(card)
                except Exception:
                    try:
                        data = dict(card)
                    except Exception:
                        data = str(card)
                title = (data.get('title') or '') if isinstance(data, dict) else ''
                import re
                def _safe_filename(s: str) -> str:
                    if not s:
                        return cid
                    s = s.strip()
                    s = re.sub(r"[^0-9A-Za-z._-]+", "_", s)
                    return s[:100]
                name = _safe_filename(title)
                fname = out_dir / f"{name or cid}_{cid}.json"
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                exported += 1
            except Exception as e:
                print(f"[export] Failed to export {cid}: {e}")
        selected_playlist_ids.clear()
        export_selected_btn.disabled = True
        delete_selected_btn.disabled = True
        playlists_list.controls.clear()
        fetch_playlists_sync(None)
        try:
            show_snack(f"Exported {exported} cards to ./cards/")
        except Exception:
            pass
        page.update()

    def _on_delete_selected(ev):
        def confirm_yes(_e=None):
            try:
                confirm_dialog.open = False
            except Exception:
                pass
            page.update()
            threading.Thread(target=_do_delete_selected, daemon=True).start()

        def confirm_no(_e=None):
            try:
                confirm_dialog.open = False
            except Exception:
                pass
            page.update()

        confirm_dialog = ft.AlertDialog(
            title=ft.Text("Delete selected playlists?"),
            content=ft.Text(
                f"Delete {len(selected_playlist_ids)} selected playlists? This cannot be undone."
            ),
            actions=[
                ft.TextButton("Yes", on_click=confirm_yes),
                ft.TextButton("No", on_click=confirm_no),
            ],
        )
        page.open(confirm_dialog)

    def _on_export_selected(ev):
        def confirm_yes(_e=None):
            try:
                confirm_dialog.open = False
            except Exception:
                pass
            page.update()
            threading.Thread(target=_do_export_selected, daemon=True).start()

        def confirm_no(_e=None):
            try:
                confirm_dialog.open = False
            except Exception:
                pass
            page.update()

        confirm_dialog = ft.AlertDialog(
            title=ft.Text("Export selected playlists?"),
            content=ft.Text(
                f"Export {len(selected_playlist_ids)} selected playlists to ./cards/?"
            ),
            actions=[
                ft.TextButton("Yes", on_click=confirm_yes),
                ft.TextButton("No", on_click=confirm_no),
            ],
        )
        page.open(confirm_dialog)

    delete_selected_btn.on_click = _on_delete_selected
    export_selected_btn.on_click = _on_export_selected

    def toggle_multi_select(ev=None):
        nonlocal multi_select_mode
        try:
            multi_select_mode = not multi_select_mode
            multi_select_btn.text = "Done" if multi_select_mode else "Select"
            delete_selected_btn.visible = multi_select_mode
            export_selected_btn.visible = multi_select_mode
            add_tags_btn.visible = multi_select_mode
            if not multi_select_mode:
                selected_playlist_ids.clear()
                delete_selected_btn.disabled = True
                export_selected_btn.disabled = True
                add_tags_btn.disabled = True
            try:
                for row in playlists_list.controls:
                    try:
                        for child in getattr(row, "controls", []):
                            if getattr(child, "_is_playlist_checkbox", False):
                                child.visible = multi_select_mode
                                if not multi_select_mode:
                                    try:
                                        child.value = False
                                    except Exception:
                                        pass
                    except Exception:
                        pass
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    multi_select_btn.on_click = toggle_multi_select

    def apply_filters(ev=None):
        try:
            threading.Thread(
                target=lambda: fetch_playlists_sync(None), daemon=True
            ).start()
        except Exception:
            try:
                asyncio.run(fetch_playlists(None))
            except Exception:
                pass

    def clear_filters(ev=None):
        try:
            title_filter.value = ""
            genre_filter.value = ""
            category_filter.value = ""
            tags_filter.value = ""
            page.update()
            apply_filters(None)
        except Exception:
            pass

    filter_btn.on_click = apply_filters
    clear_filter_btn.on_click = clear_filters

    # Header fetch button wired to the synchronous fetch helper
    fetch_btn = ft.ElevatedButton(
        text="Fetch Playlists", bgcolor="#2196F3", color="white"
    )
    fetch_btn.on_click = lambda e: threading.Thread(
        target=lambda: fetch_playlists_sync(e), daemon=True
    ).start()

    def make_playlist_row(card_obj, idx=None):
        try:
            title = getattr(card_obj, "title", None) or (
                card_obj.model_dump(exclude_none=True).get("title")
                if hasattr(card_obj, "model_dump")
                else str(card_obj)
            )
        except Exception:
            title = str(card_obj)
        cid = get_card_id_local(card_obj) or ""

        def delete_playlist(ev, card=card_obj, row_container=None):
            def do_delete(_ev=None):
                try:
                    client = CLIENT_ID
                    api = ensure_api(api_ref, client)
                    content_id = get_card_id_local(card)
                    if not content_id:
                        status_ctrl.value = "Unable to determine card id to delete"
                        page.update()
                        return
                    api.delete_content(content_id)
                    try:
                        playlists_list.controls.remove(row_container)
                    except Exception:
                        try:
                            playlists_list.controls.clear()
                        except Exception:
                            pass
                    msg = f"Deleted {content_id}"
                    status_ctrl.value = msg
                    try:
                        show_snack(msg)
                    except Exception:
                        pass
                    page.update()
                except Exception as ex:
                    msg = f"Delete failed: {ex}"
                    status_ctrl.value = msg
                    try:
                        show_snack(msg, error=True)
                    except Exception:
                        pass
                    page.update()

            def confirm_yes(_e):
                try:
                    confirm_dialog.open = False
                except Exception:
                    pass
                page.update()
                threading.Thread(target=do_delete, daemon=True).start()

            def confirm_no(_e):
                try:
                    confirm_dialog.open = False
                except Exception:
                    pass
                page.update()

            confirm_dialog = ft.AlertDialog(
                title=ft.Text("Delete playlist?"),
                content=ft.Text(
                    f"Delete playlist '{title}' (id={cid})? This cannot be undone."
                ),
                actions=[
                    ft.TextButton("Yes", on_click=confirm_yes),
                    ft.TextButton("No", on_click=confirm_no),
                ],
            )
            try:
                page.open(confirm_dialog)
            except Exception:
                try:
                    page.dialog = confirm_dialog
                    page.update()
                except Exception:
                    print("Unable to show confirmation dialog")

        delete_btn = ft.TextButton(
            "Delete",
            on_click=lambda ev, card=card_obj, row_container=None: delete_playlist(
                ev, card, row_container
            ),
        )

        def _extract_cover_source(card_item, api_instance=None):
            try:
                if hasattr(card_item, "model_dump"):
                    d = card_item.model_dump(exclude_none=True)
                elif isinstance(card_item, dict):
                    d = card_item
                else:
                    try:
                        d = json.loads(str(card_item))
                    except Exception:
                        d = {}
                meta = d.get("metadata") or {}
                cover = meta.get("cover") or {}
                for k in ("imageS", "imageM", "imageL", "image"):
                    v = cover.get(k)
                    if not v:
                        continue
                    if isinstance(v, str) and v.startswith("yoto:#") and api_instance:
                        try:
                            p = api_instance.get_icon_cache_path(v)
                            if p and Path(p).exists():
                                return str(p)
                        except Exception:
                            pass
                    if isinstance(v, str) and (
                        v.startswith("http") or v.startswith("//")
                    ):
                        return v
                return None
            except Exception:
                return None

        img_ctrl = ft.Container(width=64, height=64)
        try:
            api = api_ref.get("api")
            cover_src = (
                _extract_cover_source(card_obj, api_instance=api) if api else None
            )
            if cover_src:
                if str(cover_src).startswith("http") or str(cover_src).startswith("//"):
                    img_ctrl = ft.Image(src=cover_src, width=64, height=64)
                else:
                    img_ctrl = ft.Image(src=str(cover_src), width=64, height=64)
            else:
                if not api:

                    def _resolve_in_bg(card=card_obj, ctl=img_ctrl):
                        try:
                            client = CLIENT_ID
                            api = ensure_api(api_ref, client)
                            src = _extract_cover_source(card, api_instance=api)
                            if src:
                                try:
                                    _ = ft.Image(src=src, width=64, height=64)
                                    playlists_list.controls.clear()
                                    try:
                                        threading.Thread(
                                            target=lambda: fetch_playlists_sync(None),
                                            daemon=True,
                                        ).start()
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    threading.Thread(target=_resolve_in_bg, daemon=True).start()
        except Exception:
            pass

        cb = ft.Checkbox(value=False)
        try:
            cb.visible = multi_select_mode
        except Exception:
            pass
        try:
            cb._is_playlist_checkbox = True
            cb._cid = cid
            cb._idx = idx
        except Exception:
            pass

        def _on_checkbox_change(ev):
            try:
                control = getattr(ev, "control", None) or ev
                is_checked = getattr(control, "value", None)
                if is_checked:
                    selected_playlist_ids.add(cid)
                else:
                    selected_playlist_ids.discard(cid)
                nonlocal last_selected_index
                last_selected_index = idx
                delete_selected_btn.disabled = len(selected_playlist_ids) == 0
                export_selected_btn.disabled = len(selected_playlist_ids) == 0
                add_tags_btn.disabled = len(selected_playlist_ids) == 0
                page.update()
            except Exception:
                pass

        def _on_add_tags_selected(ev):
            if not selected_playlist_ids:
                return
            tags_field = ft.TextField(label="Tags to add (comma separated)", width=400)
            status_text = ft.Text("")

            def do_add_tags(_e=None):
                tags_val = tags_field.value or ""
                tags = [t.strip() for t in tags_val.split(",") if t.strip()]
                if not tags:
                    status_text.value = "No tags entered."
                    page.update()
                    return
                client = CLIENT_ID
                api: YotoAPI = ensure_api(api_ref, client)
                updated = 0
                failed = 0
                for cid in list(selected_playlist_ids):
                    logger.error(f"Adding tags {tags} to playlist {cid}")
                    card = api.get_card(cid)
                    meta = getattr(card, "metadata", CardMetadata())
                    print(f"Existing metadata for {cid}: {meta}")
                    card_tags = getattr(meta, "tags", None)
                    if card_tags is None:
                        card_tags = []
                    elif isinstance(card_tags, str):
                        card_tags = [
                            t.strip() for t in card_tags.split(",") if t.strip()
                        ]
                    new_tags = list(set(card_tags) | set(tags))
                    print(f"Updating tags for {cid}: {new_tags}")
                    meta.tags = new_tags
                    card.metadata = meta
                    api.update_card(card, return_card_model=False)
                    updated += 1
                status_text.value = f"Tags added to {updated} playlists. {'Failed: ' + str(failed) if failed else ''}"
                show_snack(status_text.value)
                add_tags_dialog.open = False
                threading.Thread(
                    target=lambda: fetch_playlists_sync(None), daemon=True
                ).start()
                page.update()

            def close_add_tags(_e=None):
                try:
                    add_tags_dialog.open = False
                except Exception:
                    pass
                page.update()

            add_tags_dialog = ft.AlertDialog(
                title=ft.Text("Add Tags to Selected Playlists"),
                content=ft.Column([tags_field, status_text]),
                actions=[
                    ft.TextButton("Add Tags", on_click=do_add_tags),
                    ft.TextButton("Cancel", on_click=close_add_tags),
                ],
            )
            try:
                page.open(add_tags_dialog)
            except Exception:
                try:
                    page.dialog = add_tags_dialog
                    page.update()
                except Exception:
                    pass

        add_tags_btn.on_click = _on_add_tags_selected

        cb.on_change = _on_checkbox_change

        # Use global shift_key_down instead of unreliable _is_shift_event

        def _on_tile_click(ev, card=card_obj, this_idx=idx):
            nonlocal last_selected_index
            shift = shift_key_down["value"]
            print(
                "shift:",
                shift,
                "multi_select_mode:",
                multi_select_mode,
                "this_idx:",
                this_idx,
                "last_selected_index:",
                last_selected_index,
            )
            if multi_select_mode:
                if shift and last_selected_index is not None and this_idx is not None:
                    # Shift-select: select all between last_selected_index and this_idx
                    start = min(last_selected_index, this_idx)
                    end = max(last_selected_index, this_idx)
                    for i in range(start, end + 1):
                        try:
                            row_ctrl = playlists_list.controls[i]
                            cb_found = None
                            for child in getattr(row_ctrl, "controls", []):
                                if getattr(child, "_is_playlist_checkbox", False):
                                    cb_found = child
                                    break
                            if cb_found:
                                cb_found.value = True
                                selected_playlist_ids.add(getattr(cb_found, "_cid", ""))
                        except Exception:
                            pass
                    delete_selected_btn.disabled = len(selected_playlist_ids) == 0
                    export_selected_btn.disabled = len(selected_playlist_ids) == 0
                    add_tags_btn.disabled = len(selected_playlist_ids) == 0
                    page.update()
                    last_selected_index = this_idx
                    return
                # Normal multi-select toggle
                cb_found = None
                for child in row.controls:
                    if getattr(child, "_is_playlist_checkbox", False):
                        cb_found = child
                        break
                if cb_found:
                    cb_found.value = not cb_found.value
                    if cb_found.value:
                        selected_playlist_ids.add(cid)
                    else:
                        selected_playlist_ids.discard(cid)
                    last_selected_index = this_idx
                    delete_selected_btn.disabled = len(selected_playlist_ids) == 0
                    export_selected_btn.disabled = len(selected_playlist_ids) == 0
                    add_tags_btn.disabled = len(selected_playlist_ids) == 0
                    page.update()
                return
            # If not in multi-select, open details as before
            if shift and last_selected_index is not None and this_idx is not None:
                start = min(last_selected_index, this_idx)
                end = max(last_selected_index, this_idx)
                for i in range(start, end + 1):
                    try:
                        row_ctrl = playlists_list.controls[i]
                        cb_found = None
                        for child in getattr(row_ctrl, "controls", []):
                            if getattr(child, "_is_playlist_checkbox", False):
                                cb_found = child
                                break
                            if hasattr(child, "content") and getattr(child, "content"):
                                for sub in (
                                    getattr(child, "content").controls
                                    if getattr(child, "content")
                                    and hasattr(child, "content", "controls")
                                    else []
                                ):
                                    if getattr(sub, "_is_playlist_checkbox", False):
                                        cb_found = sub
                                        break
                            if cb_found:
                                break
                        if cb_found:
                            try:
                                cb_found.value = True
                                selected_playlist_ids.add(getattr(cb_found, "_cid", ""))
                            except Exception:
                                pass
                    except Exception:
                        pass
                delete_selected_btn.disabled = len(selected_playlist_ids) == 0
                export_selected_btn.disabled = len(selected_playlist_ids) == 0
                page.update()
                last_selected_index = this_idx
                return
            show_card_details(ev, card)

        # Build a compact preview of the first few chapters to make the
        # playlist row more informative than a single text line.
        preview = ""
        try:
            if hasattr(card_obj, "model_dump"):
                d_preview = card_obj.model_dump(exclude_none=True)
            elif isinstance(card_obj, dict):
                d_preview = card_obj
            else:
                try:
                    d_preview = json.loads(str(card_obj))
                except Exception:
                    d_preview = {}
            content_preview = (
                d_preview.get("content", {}) if isinstance(d_preview, dict) else {}
            )
            chapters_preview = content_preview.get("chapters") or []
            titles = []
            for ch in chapters_preview[:3]:
                if isinstance(ch, dict):
                    titles.append(ch.get("title", "") or "")
                else:
                    titles.append(str(ch))
            preview = "  •  ".join([t for t in titles if t])
        except Exception:
            preview = ""

        # Extract metadata fields for display
        try:
            if hasattr(card_obj, "model_dump"):
                d_meta = card_obj.model_dump(exclude_none=True)
            elif isinstance(card_obj, dict):
                d_meta = card_obj
            else:
                try:
                    d_meta = json.loads(str(card_obj))
                except Exception:
                    d_meta = {}
            meta = d_meta.get("metadata") or {}
            tags = meta.get("tags")
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not tags:
                tags = []
            genres = meta.get("genre") or meta.get("genres")
            if isinstance(genres, str):
                genres = [g.strip() for g in genres.split(",") if g.strip()]
            if not genres:
                genres = []
            category = meta.get("category") or ""
        except Exception:
            tags = []
            genres = []
            category = ""

        meta_line = []
        if category:
            meta_line.append(f"Category: {category}")
        if genres:
            meta_line.append(f"Genres: {', '.join(genres)}")
        if tags:
            meta_line.append(f"Tags: {', '.join(tags)}")
        meta_text = (
            ft.Text(" | ".join(meta_line), size=12, color=ft.Colors.BLACK54)
            if meta_line
            else None
        )

        subtitle_items = [ft.Text(str(cid))]
        if preview:
            subtitle_items.append(ft.Text(preview, size=12, color=ft.Colors.BLACK45))
        if meta_text:
            subtitle_items.append(meta_text)
        subtitle = ft.Column(subtitle_items)
        tile = ft.ListTile(
            title=ft.Text(title), subtitle=subtitle, on_click=_on_tile_click
        )
        row = ft.Row(
            [cb, img_ctrl, ft.Container(content=tile, expand=True), delete_btn],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        delete_btn.on_click = (
            lambda ev, card=card_obj, row_container=row: delete_playlist(
                ev, card, row_container
            )
        )
        try:
            row._idx = idx
        except Exception:
            pass
        return row

    # show_card_details and its nested helpers
    def show_card_details(e, card):
        def refresh_icon_cache(ev=None):
            api: YotoAPI = api_ref.get("api")
            api.refresh_public_and_user_icons()

        def fmt_sec(s):
            try:
                s = float(s)
                m = int(s // 60)
                sec = int(s % 60)
                return f"{m}:{sec:02d}"
            except Exception:
                return str(s) if s is not None else ""

        try:
            # Normalize incoming card-like objects (pydantic v2 `.model_dump`,
            # pydantic v1 `.dict()`, plain dicts, nested models) into a plain
            # Python dict so the UI can inspect fields consistently.
            def _normalize(obj):
                try:
                    if obj is None:
                        return None
                    # pydantic v2
                    if hasattr(obj, "model_dump"):
                        return obj.model_dump(exclude_none=True)
                    # pydantic v1
                    if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
                        try:
                            return obj.dict()
                        except Exception:
                            pass
                    if isinstance(obj, dict):
                        return {k: _normalize(v) for k, v in obj.items()}
                    if isinstance(obj, (list, tuple)):
                        return [_normalize(v) for v in obj]
                    return obj
                except Exception:
                    return obj

            c = _normalize(card)
            if not isinstance(c, dict):
                # fallback: show a reasonable title field instead of raw model repr
                try:
                    c = {"title": str(card)}
                except Exception:
                    c = {}

            def replace_individual_icon(ev, kind="chapter", ch_i=None, tr_i=None):
                try:
                    api = api_ref.get("api")
                    card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                    if not card_id:
                        show_snack("Unable to determine card id", error=True)
                        return
                    dialog = IconReplaceDialog(
                        api=api,
                        card=c,
                        page=page,
                        show_snack=show_snack,
                        show_card_details=show_card_details,
                        kind=kind,
                        ch_i=ch_i,
                        tr_i=tr_i,
                    )
                    dialog.open()
                except Exception as ex:
                    show_snack(f"Failed to open replace icon dialog: {ex}", error=True)

            # Helper: build track UI items for a chapter. If for_reorder is True
            # return simplified rows suitable for ReorderableListView; otherwise
            # return full controls that include icon, 'Use chapter icon' and URL rows.
            def make_track_items(ch, ch_index, for_reorder=False):
                items = []
                tracks = ch.get("tracks") if isinstance(ch, dict) else None
                if not tracks:
                    return items
                for t_idx, tr in enumerate(tracks, start=1):
                    if isinstance(tr, dict):
                        tr_title = tr.get("title", "")
                        tr_format = tr.get("format", "")
                        tr_duration = fmt_sec(tr.get("duration"))
                        tr_size = tr.get("fileSize", "")
                        tr_url = tr.get("trackUrl", "")
                        display = tr.get("display") or {}
                        tr_icon_field = (
                            display.get("icon16x16")
                            if isinstance(display, dict)
                            else None
                        )
                        tr_img = None


                        def _on_tap_tr(
                            ev, ch_index=ch_index, tr_index=t_idx - 1
                        ):
                            try:
                                replace_individual_icon(
                                    ev, "track", ch_index, tr_index
                                )
                            except Exception:
                                logger.debug(f"Failed to open replace icon dialog, chapter {ch_index} track {tr_index}")
                        try:
                            api = api_ref.get("api")
                            if api and tr_icon_field:
                                tp = api.get_icon_cache_path(tr_icon_field)
                                if tp and Path(tp).exists():


                                    img = ft.Image(src=str(tp), width=20, height=20)
                                    tr_img = ft.GestureDetector(
                                        content=img,
                                        on_tap=lambda ev,
                                        ch_index=ch_index,
                                        tr_index=t_idx - 1: _on_tap_tr(
                                            ev, ch_index, tr_index
                                        ),
                                    )
                                else:
                                    # Placeholder: attempt to fetch cache in bg and refresh UI
                                    def fetch_icon_worker(
                                        icon_field=tr_icon_field,
                                        ch_index=ch_index,
                                        tr_index=t_idx - 1,
                                    ):
                                        try:
                                            api_local = ensure_api(api_ref, CLIENT_ID)
                                            api_local.get_icon_cache_path(icon_field)
                                            try:
                                                loop = asyncio.get_event_loop()
                                                loop.call_soon_threadsafe(
                                                    lambda: (
                                                        page.open(dialog),
                                                        page.update(),
                                                    )
                                                )
                                            except Exception:
                                                try:
                                                    page.open(dialog)
                                                    page.update()
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass

                                    tr_img = ft.IconButton(
                                        icon=ft.Icons.IMAGE,
                                        tooltip="Fetch icon",
                                        on_click=lambda ev,
                                        f=tr_icon_field,
                                        ci=ch_index,
                                        ti=t_idx - 1: threading.Thread(
                                            #target=lambda: fetch_icon_worker(f, ci, ti),
                                            target=lambda: _on_tap_tr(ev, ci, ti),
                                            daemon=True,
                                        ).start(),
                                    )
                            else:
                                tr_img = ft.IconButton(
                                    icon=ft.Icons.IMAGE,
                                    tooltip="Fetch icon",
                                    on_click=lambda ev,
                                    f=tr_icon_field,
                                    ci=ch_index,
                                    ti=t_idx - 1: threading.Thread(
                                        #target=lambda: fetch_icon_worker(f, ci, ti),
                                        target=lambda: _on_tap_tr(ev, ci, ti),
                                        daemon=True,
                                    ).start(),
                                )
                        except Exception:
                            tr_img = ft.IconButton(
                                icon=ft.Icons.IMAGE,
                                tooltip="Fetch icon",
                                on_click=lambda ev,
                                f=tr_icon_field,
                                ci=ch_index,
                                ti=t_idx - 1: threading.Thread(
                                    #target=lambda: fetch_icon_worker(f, ci, ti),
                                    target=lambda: _on_tap_tr(ev, ci, ti),
                                    daemon=True,
                                ).start(),
                            )

                        # tr_label = ft.Row([ft.Container(width=20), ft.Text(f"Track {t_idx}. {tr_title}", size=12)])
                        # items.append(ft.Row([ft.Container(width=20), ft.Column([tr_label, ft.Text(f"{tr_format}  • {tr_duration}  • size={tr_size}", size=11, color=ft.Colors.BLACK45)])]))
                        tr_col = ft.Column(
                            [
                                ft.Row(
                                    [
                                        tr_img if tr_img else ft.Container(width=20),
                                        ft.Text(f"Track {t_idx}. {tr_title}", size=12),
                                    ],
                                    alignment=ft.MainAxisAlignment.START,
                                    spacing=8,
                                ),
                                ft.Row(
                                    [
                                        ft.Container(width=20),
                                        ft.Text(
                                            f"{tr_format}  • {tr_duration}  • size={tr_size}",
                                            size=11,
                                            color=ft.Colors.BLACK45,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.START,
                                ),
                            ],
                            spacing=4,
                        )

                        row = ft.Row(
                            [
                                ft.Container(width=20),
                                tr_col,
                                ft.IconButton(
                                    icon=ft.Icons.IMAGE,
                                    tooltip="Use chapter icon for this track",
                                    opacity=0.1,  # Reduce opacity to 50%
                                    on_click=lambda ev,
                                    ch_i=ch_index,
                                    tr_i=t_idx - 1: use_chapter_icon(ev, ch_i, tr_i),
                                ),
                            ]
                        )
                        if tr_url:
                            row.controls.append(
                                ft.Row(
                                    [
                                        ft.Container(width=20),
                                        ft.Text(
                                            f"URL: {tr_url}", selectable=True, size=11
                                        ),
                                    ]
                                )
                            )

                        items.append(row)
                    else:
                        items.append(ft.Text(f"- {str(tr)}", selectable=True))
                return items

            chapters = (c.get("content") or {}).get("chapters")
            if not chapters:
                try:
                    api = api_ref.get("api")
                    card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                    if api and card_id:
                        full_card = api.get_card(card_id)
                        if hasattr(full_card, "model_dump"):
                            c = full_card.model_dump(exclude_none=True)
                        elif isinstance(full_card, dict):
                            c = full_card
                except Exception as ex:
                    print(f"Failed to fetch full card details: {ex}")

            controls = []
            controls.append(ft.Text(f"Title: {c.get('title', '')}", selectable=True))
            controls.append(ft.Text(f"Card ID: {c.get('cardId', '')}", selectable=True))
            controls.append(
                ft.Text(
                    f"Created by Client ID: {c.get('createdByClientId', '')}",
                    selectable=True,
                )
            )
            controls.append(
                ft.Text(f"Created At: {c.get('createdAt', '')}", selectable=True)
            )
            controls.append(
                ft.Text(
                    f"Hidden: {c.get('hidden', False)}    Deleted: {c.get('deleted', False)}",
                    selectable=True,
                )
            )

            meta = c.get("metadata") or {}
            if meta:
                try:
                    cover = meta.get("cover") or {}
                    if cover:
                        for key in ("imageL", "imageM", "imageS", "image"):
                            url_or_field = cover.get(key)
                            if not url_or_field:
                                continue
                            try:
                                if isinstance(url_or_field, str) and (
                                    url_or_field.startswith("http")
                                    or url_or_field.startswith("//")
                                ):
                                    controls.append(
                                        ft.Image(
                                            src=url_or_field, width=240, height=240
                                        )
                                    )
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
                controls.append(ft.Divider())
                controls.append(ft.Text("Metadata:", weight=ft.FontWeight.BOLD))
                controls.append(
                    ft.Text(f"  Author: {meta.get('author', '')}", selectable=True)
                )
                controls.append(
                    ft.Text(f"  Category: {meta.get('category', '')}", selectable=True)
                )
                tags = meta.get("tags")
                if tags:
                    if isinstance(tags, (list, tuple)):
                        controls.append(
                            ft.Text(f"  Tags: {', '.join(tags)}", selectable=True)
                        )
                    else:
                        controls.append(ft.Text(f"  Tags: {tags}", selectable=True))
                genres = meta.get("genre") or meta.get("genres")
                if genres:
                    if isinstance(genres, (list, tuple)):
                        controls.append(
                            ft.Text(f"  Genres: {', '.join(genres)}", selectable=True)
                        )
                    else:
                        controls.append(ft.Text(f"  Genres: {genres}", selectable=True))
                media = meta.get("media") or {}
                if media:
                    controls.append(
                        ft.Text(
                            f"  Duration: {fmt_sec(media.get('duration'))}    FileSize: {media.get('fileSize', '')}",
                            selectable=True,
                        )
                    )
                if meta.get("previewAudio"):
                    controls.append(
                        ft.Text(
                            f"  Preview Audio: {meta.get('previewAudio')}",
                            selectable=True,
                        )
                    )

            content = c.get("content") or {}
            chapters = content.get("chapters") or []
            if chapters:
                controls.append(ft.Divider())
                controls.append(ft.Text("Chapters:", weight=ft.FontWeight.BOLD))

                def save_order_click(_ev=None):
                    """Start a background save of the current chapter order and refresh playlists.

                    This handler provides immediate UI feedback, ensures the Card model
                    has an identifier, and logs any errors via `safe_log` so failures
                    are visible to the user.
                    """
                    show_snack("Saving order...")
                    page.update()

                    def bg_save():
                        api = api_ref.get("api")

                        # Ensure we have an id so the API updates the right card
                        card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                        if not card_id:
                            safe_log("save_order: no card id found")
                            return

                        dlg_content = getattr(dialog, "content", None)
                        ui_items = None
                        reconstructed_titles = []
                        # Robustly find the child-list that actually contains chapter UI items.
                        # Some Flet environments embed many header Text controls at the
                        # top-level of the dialog; we must *not* treat the entire dialog
                        # controls list as the chapter list. Prefer a container whose
                        # children are annotated with `_chapter` dicts (set when building
                        # the chapter items). If none found, fall back to `chapter_items`.
                        try:
                            if dlg_content is not None and hasattr(
                                dlg_content, "controls"
                            ):
                                for ctl in dlg_content.controls:
                                    try:
                                        children = getattr(ctl, "controls", None)
                                        if not children or not isinstance(
                                            children, (list, tuple)
                                        ):
                                            continue
                                        matches = 0
                                        for child in children:
                                            ch = getattr(child, "_chapter", None)
                                            if ch is None and hasattr(child, "content"):
                                                ch = getattr(
                                                    child.content, "_chapter", None
                                                )
                                            if isinstance(ch, dict):
                                                matches += 1
                                        # accept this container when at least half of its children
                                        # look like chapter items (or at least one match)
                                        if matches >= max(1, len(children) // 2):
                                            ui_items = children
                                            break
                                    except Exception:
                                        continue
                        except Exception:
                            pass

                        if ui_items is None:
                            # fallback to the chapter_items captured during dialog build
                            ui_items = list(chapter_items)

                        # Prefer the `chapter_items` array (kept in sync by the UI
                        # reorder handlers) as the authoritative visual order. Each
                        # entry should have an attached `_chapter` dict.
                        ordered = []
                        print(
                            "[playlists] save_order: diagnostic - chapter_items len ->",
                            len(chapter_items),
                        )
                        for i, it in enumerate(chapter_items):
                            try:
                                ch = getattr(it, "_chapter", None)
                                has_ch = isinstance(ch, dict)
                                print(
                                    f"[playlists] save_order: chapter_items[{i}] type={type(it).__name__} has__chapter={has_ch} title={(ch.get('title') if has_ch else None)}"
                                )
                            except Exception as dd:
                                print(
                                    "[playlists] save_order: chapter_items diagnostic error",
                                    dd,
                                )
                        # Also inspect any ReorderableListView markers in dialog
                        try:
                            if dlg_content is not None and hasattr(
                                dlg_content, "controls"
                            ):
                                for ctl in dlg_content.controls:
                                    try:
                                        if getattr(ctl, "_is_chapter_rv", False):
                                            ref = getattr(
                                                ctl, "_chapter_items_ref", None
                                            )
                                            print(
                                                "[playlists] save_order: found marked ReorderableListView controls len ->",
                                                len(getattr(ctl, "controls", [])),
                                                "ref_len ->",
                                                len(ref)
                                                if isinstance(ref, (list, tuple))
                                                else None,
                                            )
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        if chapter_items:
                            for it in chapter_items:
                                try:
                                    ch = getattr(it, "_chapter", None)
                                    if ch is None and hasattr(it, "content"):
                                        ch = getattr(it.content, "_chapter", None)
                                    if isinstance(ch, dict):
                                        ordered.append(deepcopy(ch))
                                except Exception:
                                    continue

                        if ordered:
                            if "content" not in c or not isinstance(
                                c.get("content"), dict
                            ):
                                c["content"] = {}
                            c["content"]["chapters"] = ordered

                        card_model = Card.model_validate(c)
                        try:
                            card_model = Card(**c)
                        except Exception as ex:
                            safe_log("save_order: failed to build Card model", ex)
                            show_snack(
                                f"Failed to prepare card for save: {ex}", error=True
                            )
                        # Inspect payload before sending
                        try:
                            payload = card_model.model_dump(exclude_none=True)
                        except Exception:
                            payload = c

                        # Ensure the model contains the id we intend to update
                        if not getattr(card_model, "cardId", None):
                            if getattr(card_model, "id", None):
                                card_model.cardId = getattr(card_model, "id")
                            else:
                                card_model.cardId = card_id

                        # Build a payload dict and ensure chapters come from the
                        # current `c` dict so we send exactly what the UI shows.
                        try:
                            payload = card_model.model_dump(exclude_none=True)
                        except Exception:
                            payload = {}
                        try:
                            if (c.get("content") or {}).get("chapters"):
                                payload.setdefault("content", {})
                                # deep copy to avoid mutating runtime objects
                                payload["content"]["chapters"] = deepcopy(
                                    (c.get("content") or {}).get("chapters") or []
                                )
                        except Exception:
                            pass

                        print(
                            "[playlists] save_order: sending payload via create_or_update_content"
                        )
                        updated = api.create_or_update_content(
                            Card.model_validate(payload), return_card=True
                        )
                        show_card_details(None, updated)
                        page.update()

                    threading.Thread(target=bg_save, daemon=True).start()
                    safe_log("save_order: background save started")

                chapter_items = []
                for ch_idx, ch in enumerate(chapters):
                    ch_title = ch.get("title", "") if isinstance(ch, dict) else str(ch)
                    overlay = ch.get("overlayLabel", "") if isinstance(ch, dict) else ""
                    key = ch.get("key", "") if isinstance(ch, dict) else ""

                    icon_field = None
                    if isinstance(ch, dict):
                        display = ch.get("display") or {}
                        icon_field = (
                            display.get("icon16x16")
                            if isinstance(display, dict)
                            else None
                        )

                    img_control = None

                    def _on_tap_ch(ev, ch_index=ch_idx):
                        print(
                            f"Chapter icon tapped: chapter index {ch_index}, title '{ch_title}'"
                        )

                        replace_individual_icon(ev, "chapter", ch_index)

                    try:
                        api: YotoAPI = api_ref.get("api")
                        if api and icon_field:
                            p = api.get_icon_cache_path(icon_field)
                            if p and Path(p).exists():
                                print(
                                    f"Using cached icon path for chapter icon field {icon_field}: {p}"
                                )
                                img = ft.Image(src=str(p), width=24, height=24)
                                img_control = ft.GestureDetector(
                                    content=img, on_tap=_on_tap_ch
                                )
                            else:
                                # Add a blank placeholder that is clickable
                                img_control = ft.IconButton(
                                    icon=ft.Icons.ERROR,
                                    tooltip="Click to refresh icon cache",
                                    on_click=refresh_icon_cache,
                                )
                                logger.debug(f"No cached icon path for chapter icon field {icon_field}")
                        else:
                            # Add a blank placeholder that is clickable
                            img_control = ft.IconButton(
                                icon=ft.Icons.IMAGE,
                                tooltip="Fetch icon",
                                on_click=_on_tap_ch,
                            )
                            print("No API or no icon field")
                    except Exception:
                        # Add a blank placeholder that is clickable
                        img_control = ft.IconButton(
                            icon=ft.Icons.IMAGE,
                            tooltip="Fetch icon",
                            on_click=_on_tap_ch,
                        )

                    meta_line = f"key={key}"
                    if overlay:
                        meta_line += f"  overlay={overlay}"
                    if isinstance(ch, dict) and (
                        ch.get("duration") or ch.get("fileSize")
                    ):
                        meta_line += f"  • Duration: {fmt_sec(ch.get('duration'))}  FileSize: {ch.get('fileSize', '')}"

                    tracks = ch.get("tracks") if isinstance(ch, dict) else None
                    track_controls = (
                        make_track_items(ch, ch_idx, for_reorder=True) if tracks else []
                    )

                    def make_track_on_reorder(ch_index):
                        def _on_reorder(ev):
                            try:
                                # Use first non-None because index 0 is falsy and must be preserved
                                old = getattr(ev, "old_index", None)
                                if old is None:
                                    old = getattr(ev, "from_index", None)
                                if old is None:
                                    old = getattr(ev, "start_index", None)

                                new = getattr(ev, "new_index", None)
                                if new is None:
                                    new = getattr(ev, "to_index", None)
                                if new is None:
                                    new = getattr(ev, "index", None)
                                if old is None or new is None:
                                    return
                                tr_list = (
                                    c.get("content", {})
                                    .get("chapters", [])[ch_index]
                                    .get("tracks")
                                    or []
                                )
                                item = tr_list.pop(old)
                                tr_list.insert(new, item)
                                try:
                                    page.open(dialog)
                                    page.update()
                                except Exception:
                                    page.update()
                            except Exception as ex:
                                print("track reorder failed:", ex)

                        return _on_reorder

                    chapter_panel_children = [
                        ft.Row(
                            [
                                img_control if img_control else ft.Container(width=24),
                                ft.Column(
                                    [
                                        ft.Text(
                                            f"Chapter {ch_idx + 1}. {ch_title}",
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            meta_line, size=12, color=ft.Colors.BLACK45
                                        ),
                                    ]
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            spacing=12,
                        )
                    ]

                    # Allow the parent ListView/dialog to handle scrolling by
                    # avoiding an internal fixed height on the ReorderableListView.
                    # flet.ReorderableListView expects the children as the first
                    # positional argument in some versions; avoid unsupported kwargs.
                    tracks_rv = ft.ReorderableListView(
                        track_controls, on_reorder=make_track_on_reorder(ch_idx)
                    )
                    chapter_panel_children.append(tracks_rv)

                    col = ft.Column(chapter_panel_children, spacing=6)
                    try:
                        col._chapter = ch
                    except Exception:
                        pass
                    chapter_items.append(col)


                def make_chapter_on_reorder(ev):
                    print("make_chapter_on_reorder")
                    print(ev)
                    try:
                        # Use first non-None because index 0 is falsy and must be preserved
                        old = getattr(ev, "old_index", None)
                        if old is None:
                            old = getattr(ev, "from_index", None)
                        if old is None:
                            old = getattr(ev, "start_index", None)

                        new = getattr(ev, "new_index", None)
                        if new is None:
                            new = getattr(ev, "to_index", None)
                        if new is None:
                            new = getattr(ev, "index", None)
                        if old is None or new is None:
                            return
                        try:
                            ch_list = c.get("content", {}).get("chapters", [])
                            before = [
                                (
                                    ch.get("title")
                                    if isinstance(ch, dict)
                                    else str(ch)
                                )
                                for ch in list(ch_list)
                            ]
                        except Exception:
                            before = []
                        try:
                            item = ch_list.pop(old)
                            ch_list.insert(new, item)
                        except Exception as err:
                            print("[playlists] on_reorder: mutation error", err)
                        try:
                            after = [
                                (
                                    ch.get("title")
                                    if isinstance(ch, dict)
                                    else str(ch)
                                )
                                for ch in (c.get("content") or {}).get("chapters")
                                or []
                            ]
                        except Exception:
                            after = []
                        print(
                            f"[playlists] on_reorder chapter old={old} new={new} before={before} after={after}"
                        )
                        try:
                            # keep UI chapter items array in sync with model list
                            ui_item = chapter_items.pop(old)
                            chapter_items.insert(new, ui_item)
                        except Exception:
                            pass
                        try:
                            page.open(dialog)
                            page.update()
                        except Exception:
                            page.update()
                    except Exception as ex:
                        print("chapter reorder failed:", ex)

                # Let the dialog's ListView manage scrolling rather than giving
                # the ReorderableListView its own fixed height (prevents nested scroll).
                chapters_rv = ft.ReorderableListView(
                    chapter_items, on_reorder=make_chapter_on_reorder
                )
                try:
                    # mark for bg_save discovery and keep a reference to the
                    # chapter_items list so we can read the authoritative UI order
                    chapters_rv._is_chapter_rv = True
                    chapters_rv._chapter_items_ref = chapter_items
                except Exception:
                    pass
                controls.append(chapters_rv)

                controls.append(
                    ft.Row([ft.ElevatedButton("Save Order", on_click=save_order_click)])
                )

                def use_chapter_icon(ev, ch_i, tr_i):
                    try:
                        api = ensure_api(api_ref, CLIENT_ID)
                        card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                        if not card_id:
                            show_snack("Unable to determine card id", error=True)
                            return

                        def worker():
                            try:
                                full = api.get_card(card_id)
                                ch = full.content.chapters[ch_i]
                                chapter_icon = (
                                    getattr(ch.display, "icon16x16", None)
                                    if getattr(ch, "display", None)
                                    else None
                                )
                                if not chapter_icon:
                                    show_snack(
                                        "Chapter has no icon to copy", error=True
                                    )
                                    return
                                tr = ch.tracks[tr_i]
                                if not getattr(tr, "display", None):
                                    tr.display = (
                                        type(tr.display)()
                                        if hasattr(tr, "display")
                                        else None
                                    )
                                tr.display.icon16x16 = chapter_icon
                                api.update_card(full, return_card_model=False)
                                page.open(dialog)
                                page.update()
                                show_snack("Track icon updated to chapter icon")
                            except Exception as ee:
                                show_snack(
                                    f"Failed to copy chapter icon: {ee}", error=True
                                )
                                page.update()
                            show_card_details(None, full)

                        threading.Thread(target=worker, daemon=True).start()
                    except Exception:
                        show_snack("Failed to start copy operation", error=True)

                # items = make_track_items(ch, ch_idx, for_reorder=False)
                # if items:
                #    for it in items:
                #        controls.append(it)
                # controls.append(ft.Divider())
            else:
                controls.append(ft.Text("Chapters: None", selectable=True))

            if not controls:
                try:
                    controls = [ft.Text(json.dumps(c, indent=2), selectable=True)]
                except Exception:
                    controls = [ft.Text(str(card), selectable=True)]
        except Exception:
            print("Failed to render card details:", traceback.format_exc())
            controls = [ft.Text(str(card), selectable=True)]

        def close_dialog(ev):
            try:
                dialog.open = False
            except Exception:
                pass
            page.update()

        def show_json(ev):
            try:
                raw = json.dumps(c, indent=2)
            except Exception:
                try:
                    raw = str(c)
                except Exception:
                    raw = "<unable to render JSON>"

            def close_json(ev2):
                try:
                    json_dialog.open = False
                except Exception:
                    pass
                page.update()

            json_content = ft.ListView(
                [ft.Text(raw, selectable=True)], padding=10, height=500, width=800
            )
            json_dialog = ft.AlertDialog(
                title=ft.Text("Raw card JSON"),
                content=json_content,
                actions=[ft.TextButton("Close", on_click=close_json)],
            )
            try:
                page.open(json_dialog)
            except Exception:
                try:
                    page.dialog = json_dialog
                    page.update()
                except Exception:
                    print("Unable to display JSON dialog in this Flet environment")

        def show_add_cover(ev):
            from yoto_app.add_cover_dialog import add_cover_dialog
            add_cover_dialog(
                page,
                api_ref,
                c,
                fetch_playlists_sync,
                Card,
                CLIENT_ID
            )
        def replace_icons(ev):

            show_replace_icons_dialog(
                page,
                api_ref,
                c,
                fetch_playlists_sync,
                ensure_api,
                CLIENT_ID,
                show_snack,
                playlists_list,
                make_playlist_row,
                show_card_details,
            )

        ##def replace_icons(ev):
        #    try:
        #        warn = ft.Text(
        #            """Replacing default icons may take a long time. 
        #    The more icons missing, the longer it takes.

        #    Continue?"""
        #        )
        #        include_yoto = ft.Checkbox(label="Include YotoIcons search", value=True)
        #        max_searches_field = ft.TextField(
        #            label="Max extra searches (per track/chapter)", value="2", width=120
        #        )

        #        def start_replace(_e=None):
        #            try:
        #                try:
        #                    max_searches = int(max_searches_field.value or "3")
        #                except Exception:
        #                    max_searches = 3
        #                include_yotoicons = bool(include_yoto.value)

        #                # Worker containing the original start logic
        #                def _start_worker():
        #                    try:
        #                        # close the confirm dialog and prepare UI
        #                        try:
        #                            confirm_dialog.open = False
        #                            page.update()
        #                        except Exception:
        #                            pass

        #                        prog = ft.ProgressBar(width=400)
        #                        prog_text = ft.Text("Preparing...")
        #                        prog_col = ft.Column([prog_text, prog])
        #                        cancel_event = threading.Event()

        #                        def do_cancel(_e=None):
        #                            try:
        #                                cancel_event.set()
        #                                prog_text.value = "Cancelling..."
        #                                page.update()
        #                            except Exception:
        #                                pass

        #                        replace_dialog = ft.AlertDialog(
        #                            title=ft.Text("Replace Default Icons"),
        #                            content=prog_col,
        #                            actions=[ft.TextButton("Cancel", on_click=do_cancel)],
        #                        )
        #                        page.open(replace_dialog)

        #                        def work():
        #                            try:
        #                                prog_text.value = "Fetching card..."
        #                                prog.value = 0.0
        #                                page.update()
        #                                api = ensure_api(api_ref, CLIENT_ID)
        #                                card_id = (
        #                                    c.get("cardId") or c.get("id") or c.get("contentId")
        #                                )
        #                                if not card_id:
        #                                    raise RuntimeError("Unable to determine card id")
        #                                full = api.get_card(card_id)
        #                                prog_text.value = "Analyzing icons..."
        #                                page.update()

        #                                def icon_progress(msg, frac):
        #                                    try:
        #                                        if msg:
        #                                            prog_text.value = msg
        #                                        if frac is not None:
        #                                            prog.value = frac
        #                                        page.update()
        #                                    except Exception:
        #                                        pass

        #                                new_card = api.replace_card_default_icons(
        #                                    full,
        #                                    progress_callback=icon_progress,
        #                                    cancel_event=cancel_event,
        #                                    include_yotoicons=include_yotoicons,
        #                                    max_searches=max_searches,
        #                                )
        #                                prog_text.value = "Saving updated card..."
        #                                page.update()
        #                                api.update_card(new_card, return_card_model=False)
        #                                prog_text.value = "Done"
        #                                prog.value = 1.0

        #                                # Schedule a UI-thread update to refresh the affected playlist row
        #                                def run_on_ui(fn, *a, **kw):
        #                                    try:
        #                                        loop = asyncio.get_event_loop()
        #                                        loop.call_soon_threadsafe(lambda: fn(*a, **kw))
        #                                    except Exception:
        #                                        try:
        #                                            fn(*a, **kw)
        #                                        except Exception:
        #                                            pass

        #                                def get_card_id(card_obj):
        #                                    try:
        #                                        if isinstance(card_obj, dict):
        #                                            return (
        #                                                card_obj.get("id")
        #                                                or card_obj.get("contentId")
        #                                                or card_obj.get("cardId")
        #                                            )
        #                                        return (
        #                                            getattr(card_obj, "id", None)
        #                                            or getattr(card_obj, "contentId", None)
        #                                            or getattr(card_obj, "cardId", None)
        #                                        )
        #                                    except Exception:
        #                                        return None

        #                                def refresh_ui(card_model):
        #                                    try:
        #                                        updated_id = get_card_id(card_model)
        #                                    except Exception:
        #                                        updated_id = None
        #                                    if not updated_id:
        #                                        try:
        #                                            page.update()
        #                                        except Exception:
        #                                            pass
        #                                        return
        #                                    try:
        #                                        # Try to find the playlist row with a checkbox tagged with _is_playlist_checkbox and matching _cid
        #                                        for i, ctrl in enumerate(
        #                                            list(playlists_list.controls)
        #                                        ):
        #                                            cb = None
        #                                            # controls may be a Row with controls attribute
        #                                            children = (
        #                                                getattr(ctrl, "controls", None)
        #                                                or getattr(
        #                                                    getattr(ctrl, "content", None),
        #                                                    "controls",
        #                                                    None,
        #                                                )
        #                                                or []
        #                                            )
        #                                            for ch in children or []:
        #                                                if getattr(
        #                                                    ch, "_is_playlist_checkbox", False
        #                                                ):
        #                                                    cb = ch
        #                                                    break
        #                                            if not cb:
        #                                                continue
        #                                            if getattr(cb, "_cid", None) == updated_id:
        #                                                try:
        #                                                    playlists_list.controls[i] = (
        #                                                        make_playlist_row(
        #                                                            card_model, idx=i
        #                                                        )
        #                                                    )
        #                                                    page.update()
        #                                                    try:
        #                                                        show_snack(
        #                                                            "Playlist icons updated"
        #                                                        )
        #                                                    except Exception:
        #                                                        pass
        #                                                except Exception:
        #                                                    pass
        #                                                return
        #                                        # if not found, refresh full list
        #                                        threading.Thread(
        #                                            target=lambda: fetch_playlists_sync(None),
        #                                            daemon=True,
        #                                        ).start()
        #                                    except Exception:
        #                                        pass

        #                                # run the UI refresh on the main thread
        #                                run_on_ui(refresh_ui, new_card)
        #                            except Exception as ex:
        #                                try:
        #                                    show_snack(
        #                                        f"Replace icons failed: {ex}", error=True
        #                                    )
        #                                except Exception:
        #                                    pass
        #                                print("replace_icons error:", ex)
        #                            # Schedule show_card_details to run in the main thread after 5 seconds
        #                            time.sleep(1)
        #                            show_card_details(None, new_card)

        #                        threading.Thread(target=work, daemon=True).start()
        #                    except Exception as ee:
        #                        try:
        #                            show_snack(f"Failed to start replace: {ee}", error=True)
        #                        except Exception:
        #                            pass

        #                # If user selected a value larger than 2, show a confirmation before starting
        #                if max_searches > 2:
        #                    try:
        #                        warn_txt = ft.Text(
        #                            "You have chosen a max extra searches value > 2. This may significantly increase runtime and API usage. Continue?"
        #                        )
        #                        secondary = ft.AlertDialog(
        #                            title=ft.Text("Confirm large search count"),
        #                            content=warn_txt,
        #                            actions=[
        #                                ft.TextButton(
        #                                    "Start",
        #                                    on_click=lambda e: (
        #                                        (setattr(secondary, "open", False) if hasattr(secondary, "open") else None),
        #                                        page.update(),
        #                                        threading.Thread(target=_start_worker, daemon=True).start(),
        #                                    ),
        #                                ),
        #                                ft.TextButton("Cancel", on_click=lambda e: (setattr(secondary, "open", False), page.update())),
        #                            ],
        #                        )
        #                        page.open(secondary)
        #                    except Exception:
        #                        # If we can't show a dialog, just start
        #                        threading.Thread(target=_start_worker, daemon=True).start()
        #                else:
        #                    threading.Thread(target=_start_worker, daemon=True).start()
        #            except Exception as ee:
        #                try:
        #                    show_snack(f"Failed to start replace: {ee}", error=True)
        #                except Exception:
        #                    pass

        #        def cancel_confirm(_e=None):
        #            try:
        #                confirm_dialog.open = False
        #            except Exception:
        #                pass
        #            page.update()

        #        confirm_dialog = ft.AlertDialog(
        #            title=ft.Text("Confirm replace default icons"),
        #            content=ft.Column(
        #                [
        #                    warn,
        #                    include_yoto,
        #                    ft.Row(
        #                        [
        #                            max_searches_field,
        #                            ft.Text(" "),
        #                            ft.Text(
        #                                "(larger values = more searches, longer runtime)"
        #                            ),
        #                        ]
        #                    ),
        #                ]
        #            ),
        #            actions=[
        #                ft.TextButton("Start", on_click=start_replace),
        #                ft.TextButton("Cancel", on_click=cancel_confirm),
        #            ],
        #        )

        #        try:
        #            page.open(confirm_dialog)
        #        except Exception:
        #            try:
        #                page.dialog = confirm_dialog
        #                page.update()
        #            except Exception:
        #                print("Unable to show confirmation dialog")
        #    except Exception as e:
        #        try:
        #            show_snack(f"Replace icons failed to start: {e}", error=True)
        #        except Exception:
        #            pass
        #        print("replace_icons start error:", e)

        # Size the details dialog to take advantage of the app window where possible.
        try:
            # Prefer window_height/window_width (if available) then page.height/width.
            win_h = getattr(page, "window_height", None) or getattr(
                page, "height", None
            )
            win_w = getattr(page, "window_width", None) or getattr(page, "width", None)
            if win_h:
                dlg_h = max(300, min(int(win_h * 0.9), 1200))
            else:
                dlg_h = 500
            if win_w:
                dlg_w = max(400, min(int(win_w * 0.9), 1400))
            else:
                dlg_w = 800
        except Exception:
            dlg_h, dlg_w = 500, 800

        dialog_content = ft.ListView(
            controls, spacing=6, padding=10, height=dlg_h, width=dlg_w
        )
        dialog = ft.AlertDialog(
            title=ft.Text("Playlist details"),
            content=dialog_content,
            actions=[
                ft.ElevatedButton("Save Order", on_click=save_order_click),
                ft.TextButton("Raw JSON", on_click=show_json),
                ft.TextButton(
                    "Edit",
                    on_click=lambda ev: (
                        setattr(dialog, 'open', False),
                        page.update(),
                        show_edit_card_dialog(
                            c,
                            page,
                            ensure_api,
                            CLIENT_ID,
                            status_ctrl,
                            fetch_playlists_sync,
                            show_card_details=show_card_details,
                            
                        )
                    ),
                ),
                ft.TextButton("Add Cover", on_click=lambda ev: show_add_cover(ev)),
                ft.TextButton(
                    "Replace Default Icons", on_click=lambda ev: replace_icons(ev)
                ),
                ft.TextButton(
                    "Export",
                    on_click=lambda ev: (
                        threading.Thread(
                            target=lambda: (
                                (lambda:
                                    (lambda data, fname: (
                                        (open(fname, 'w', encoding='utf-8').write(json.dumps(data, indent=2, ensure_ascii=False)))
                                    ))(
                                        (c if isinstance(c, dict) else (c.model_dump(exclude_none=True) if hasattr(c, 'model_dump') else c)),
                                        Path('cards') / f"{( (c.get('title') or '') if isinstance(c, dict) else '' )}_{(c.get('cardId') or c.get('id') or c.get('contentId') or 'card')}.json"
                                    )
                                )()
                            ),
                            daemon=True,
                        ).start(),
                        show_snack("Export started..."),
                    ),
                ),
                ft.TextButton("Close", on_click=close_dialog),
            ],
        )
        try:
            page.open(dialog)
        except Exception:
            try:
                page.dialog = dialog
                page.update()
            except Exception:
                print("Unable to display dialog in this Flet environment")

    async def fetch_playlists(e=None):
        print("Fetching playlists...")
        page.update()
        api = api_ref.get("api")
        try:
            cards = await asyncio.to_thread(api.get_myo_content)
        except Exception as ex:
            print("fetch_playlists error:", ex)
            return

        playlists_list.controls.clear()
        if not cards:
            playlists_list.controls.append(ft.Text("No playlists found"))
        else:
            for idx, c in enumerate(cards):
                try:
                    if not card_matches_filters(c):
                        continue
                    playlists_list.controls.append(make_playlist_row(c, idx=idx))
                except Exception:
                    try:
                        title = getattr(c, "title", None) or (
                            c.model_dump(exclude_none=True).get("title")
                            if hasattr(c, "model_dump")
                            else str(c)
                        )
                    except Exception:
                        title = str(c)
                    cid = getattr(c, "id", None) or getattr(c, "contentId", None) or ""
                    playlists_list.controls.append(
                        ft.ListTile(
                            title=ft.Text(title),
                            subtitle=ft.Text(str(cid)),
                            on_click=lambda ev, card=c: show_card_details(ev, card),
                        )
                    )

        try:
            existing_card_map.clear()
            opts = []
            for c in cards:
                try:
                    title = getattr(c, "title", None) or (
                        c.model_dump(exclude_none=True).get("title")
                        if hasattr(c, "model_dump")
                        else str(c)
                    )
                except Exception:
                    title = str(c)
                cid = (
                    getattr(c, "id", None)
                    or getattr(c, "contentId", None)
                    or getattr(c, "cardId", None)
                    or ""
                )
                display = f"{title} ({cid})"
                existing_card_map[display] = cid
                opts.append(ft.dropdown.Option(display))
            existing_card_dropdown.options = opts
        except Exception:
            pass
        try:
            show_snack(f"Fetched {len(cards)} playlists")
        except Exception:
            pass
        page.update()

    def fetch_playlists_sync(e=None):
        print("Fetching playlists...")
        try:
            show_snack("Fetching playlists...")
            page.update()
            api = api_ref.get("api")
            cards = api.get_myo_content()
            playlists_list.controls.clear()
            if not cards:
                playlists_list.controls.append(ft.Text("No playlists found"))
            else:
                # Sort cards based on dropdown
                sort_key = current_sort["key"]

                def get_meta(card):
                    if hasattr(card, "model_dump"):
                        d = card.model_dump(exclude_none=True)
                    elif isinstance(card, dict):
                        d = card
                    else:
                        try:
                            d = json.loads(str(card))
                        except Exception:
                            d = {}
                    meta = d.get("metadata") or {}
                    return d, meta

                def sort_func(card):
                    d, meta = get_meta(card)
                    if sort_key == "title_asc":
                        return (d.get("title") or "").lower()
                    if sort_key == "title_desc":
                        return (d.get("title") or "").lower()
                    if sort_key == "category":
                        return (meta.get("category") or "").lower()
                    if sort_key in ("created_desc", "created_asc", "updated_desc", "updated_asc"):
                        key_name = "createdAt" if "created" in sort_key else "updatedAt"
                        value = d.get(key_name)
                        ts = 0
                        if value:
                            from datetime import datetime
                            try:
                                v = value.rstrip('Z')
                                try:
                                    dt = datetime.strptime(v, "%Y-%m-%dT%H:%M:%S.%f")
                                except ValueError:
                                    dt = datetime.strptime(v, "%Y-%m-%dT%H:%M:%S")
                                ts = int(dt.timestamp())
                            except Exception as e:
                                print(f"[sort_func] Failed to parse {key_name} '{value}' for card {d.get('title','?')}: {e}")
                        print(f"[sort_func] card: {d.get('title','?')}, {key_name}: {value}, ts: {ts}")
                        return ts
                    return (d.get("title") or "").lower()

                if sort_key.endswith("_desc"):
                    reverse = True
                elif sort_key.endswith("_asc"):
                    reverse = False
                else:
                    reverse = sort_key == "title_desc"
                try:
                    sorted_cards = sorted(cards, key=sort_func, reverse=reverse)
                    if sort_key in ("created_desc", "created_asc"):
                        print(f"[sort] sort_key={sort_key}, reverse={reverse}")
                        for idx, c in enumerate(sorted_cards):
                            d, _ = get_meta(c)
                            print(f"[sorted] idx={idx}, title={d.get('title','?')}, createdAt={d.get('createdAt','?')}")
                except Exception as e:
                    print(f"[sort] Exception during sorting: {e}")
                    sorted_cards = cards

                for idx, c in enumerate(sorted_cards):
                    try:
                        if not card_matches_filters(c):
                            continue
                        playlists_list.controls.append(make_playlist_row(c, idx=idx))
                    except Exception:
                        try:
                            title = getattr(c, "title", None) or (
                                c.model_dump(exclude_none=True).get("title")
                                if hasattr(c, "model_dump")
                                else str(c)
                            )
                        except Exception:
                            title = str(c)
                        cid = (
                            getattr(c, "id", None)
                            or getattr(c, "contentId", None)
                            or ""
                        )
                        playlists_list.controls.append(
                            ft.ListTile(
                                title=ft.Text(title),
                                subtitle=ft.Text(str(cid)),
                                on_click=lambda ev, card=c: show_card_details(ev, card),
                            )
                        )
                try:
                    existing_card_map.clear()
                    opts = []
                    for c in cards:
                        try:
                            title = getattr(c, "title", None) or (
                                c.model_dump(exclude_none=True).get("title")
                                if hasattr(c, "model_dump")
                                else str(c)
                            )
                        except Exception:
                            title = str(c)
                        cid = (
                            getattr(c, "id", None)
                            or getattr(c, "contentId", None)
                            or getattr(c, "cardId", None)
                            or ""
                        )
                        display = f"{title} ({cid})"
                        existing_card_map[display] = cid
                        opts.append(ft.dropdown.Option(display))
                    existing_card_dropdown.options = opts
                except Exception:
                    pass
            show_snack(f"Fetched {len(cards)} playlists")
            page.update()
        except httpx.HTTPError as http_ex:
            logger.error(f"HTTP error during fetch_playlists_sync: {http_ex}")
            logger.error(f"fetch_playlists_sync error: {http_ex}")
            traceback.print_exc(file=sys.stderr)
            if "401" in str(http_ex) or "403" in str(http_ex):
                show_snack("Authentication error. Please log in again.", error=True)
                delete_tokens_file()
                page.invalidate_authentication()
                page.switch_to_auth_tab()
                page.update()

        except Exception as ex:
            logger.error(f"fetch_playlists_sync error: {ex}")
            traceback.print_exc(file=sys.stderr)
            # safe_log("fetch_playlists_sync error", ex)
            show_snack("Unable to fetch playlists", error=True)

    filter_btn.on_click = lambda e: threading.Thread(
        target=lambda: fetch_playlists_sync(e), daemon=True
    ).start()
    clear_filter_btn.on_click = lambda e: (
        setattr(title_filter, "value", ""),
        setattr(genre_filter, "value", ""),
        setattr(category_filter, "value", ""),
        threading.Thread(target=lambda: fetch_playlists_sync(e), daemon=True).start(),
    )

    # Make filters row expandable using Accordion
    filters_panel = ft.ExpansionTile(
        title=ft.Container(
            content=ft.Text("Filters", size=12, weight=ft.FontWeight.W_400),
            padding=0,
            margin=0,
        ),
        controls=[
            ft.Container(
                content=ft.Row(
                    [
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
                bgcolor=ft.Colors.GREY_100,
                border_radius=4,
                height=None,
                alignment=ft.alignment.top_left,
            )
        ],
    )

    playlists_column = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Playlists", style=ft.TextThemeStyle.TITLE_MEDIUM),
                    fetch_btn,
                    multi_select_btn,
                    delete_selected_btn,
                    export_selected_btn,
                    import_card_btn,
                    add_tags_btn,
                    sort_dropdown,
                ]
            ),
            filters_panel,
            ft.Divider(),
            playlists_list,
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # Import picker result handling
    def _on_import_pick_result(e: ft.FilePickerResultEvent):
        try:
            if not e.files:
                show_snack("No file selected for import", error=True)
                return
            # use first selected file
            for f in e.files:
                path = getattr(f, "path", None)
                if not path:
                    show_snack("Selected file has no path (web picker unsupported)", error=True)
                    return
                # Read file and parse JSON
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception as ex:
                    logger.error(f"Failed to read card file {path}: {ex}")
                    show_snack(f"Failed to read card file: {ex}", error=True)
                    continue

                # Validate/construct Card
                try:
                    card_obj = Card.model_validate(data)
                except Exception:
                    # fallback: try to construct from dict
                    try:
                        card_obj = Card(**data)
                    except Exception as ex:
                        logger.error("import_card: failed to validate to Card", ex)
                        show_snack(f"Invalid card format: {ex}", error=True)
                        continue

                # Ensure new card (unset id)
                # Do we want to do this?
                try:
                    if hasattr(card_obj, "cardId"):
                        setattr(card_obj, "cardId", None)
                except Exception:
                    pass

                # Call API to create
                try:
                    api = ensure_api(api_ref, CLIENT_ID)
                    new_card = api.create_or_update_content(card_obj, return_card=True)
                    show_snack(f"Card imported: {getattr(new_card, 'cardId', getattr(new_card, 'id', 'unknown'))}")
                    # refresh playlists list
                    try:
                        threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                    except Exception:
                        pass
                except Exception as ex:
                    logger.error(f"Failed to import card via API: {ex}")
                    show_snack(f"Failed to import card: {ex}", error=True)

        except Exception as exc:
            logger.error(f"_on_import_pick_result unexpected error: {exc}")
            show_snack("Unexpected error during import", error=True)

    import_picker.on_result = _on_import_pick_result

    def _on_import_card_click(e=None):
        try:
            import_picker.pick_files(dialog_title="Select Card JSON file(s) to import", allow_multiple=True)
        except Exception as ex:
            logger.error(f"import_card click failed: {ex}")
            show_snack("Failed to open file picker", error=True)

    import_card_btn.on_click = _on_import_card_click

    return {
        "playlists_column": playlists_column,
        "fetch_playlists": fetch_playlists,
        "fetch_playlists_sync": fetch_playlists_sync,
        "playlists_list": playlists_list,
        "existing_card_dropdown": existing_card_dropdown,
        "existing_card_map": existing_card_map,
        "show_card_details": show_card_details,
        "delete_selected_btn": delete_selected_btn,
        "multi_select_btn": multi_select_btn,
        "add_tags_btn": add_tags_btn,
        "export_selected_btn": export_selected_btn,
    "import_card_btn": import_card_btn,
        "fetch_btn": fetch_btn,
        "sort_dropdown": sort_dropdown,
        "current_sort": current_sort,
    }
