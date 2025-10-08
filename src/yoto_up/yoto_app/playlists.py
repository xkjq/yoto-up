import sys
import threading
from copy import deepcopy
import asyncio
import json
import traceback
from pathlib import Path
from typing import Any, Dict


import flet as ft
from yoto_up.yoto_app.icon_replace_dialog import IconReplaceDialog
from yoto_up.yoto_app.edit_card_dialog import show_edit_card_dialog
from yoto_up.yoto_app.replace_icons import show_replace_icons_dialog
from types import SimpleNamespace
from yoto_up.yoto_app.card_details import make_show_card_details

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
except Exception: # Broad because pyodide etc may raise weird errors
    _PYNPUT_AVAILABLE = False

import httpx
from yoto_up.models import Card, CardMetadata, ChapterDisplay, TrackDisplay
from yoto_up.yoto_app.auth import delete_tokens_file
from yoto_up.yoto_app.config import CLIENT_ID
from loguru import logger
import time
from yoto_up.yoto_api import YotoAPI
from yoto_up.paths import save_playlists, VERSIONS_DIR



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
    restore_versions_btn = ft.ElevatedButton(text="Restore Versions")
    def _open_versions_dialog(_e=None):
        try:
            api = ensure_api(api_ref, CLIENT_ID)
        except Exception:
            try:
                show_snack("API not available for restore", error=True)
            except Exception:
                pass
            return

        versions_root = getattr(api, "VERSIONS_DIR", None)
        # Build a mapping of card_id -> latest version file path. We'll show
        # only entries where the current server does NOT have the card (i.e.
        # deleted) so this dialog functions as "Restore Deleted".
        deleted_entries = []
        try:
            # Candidate roots: prefer API-configured VERSIONS_DIR, then the
            # central paths.VERSIONS_DIR fallback. This covers cases where
            # versions were written by a different API instance or earlier
            # during execution.
            candidate_roots = []
            if versions_root:
                try:
                    candidate_roots.append(Path(versions_root))
                except Exception:
                    pass
            try:
                candidate_roots.append(Path(VERSIONS_DIR))
            except Exception:
                pass

            seen_roots = set()
            for root in candidate_roots:
                try:
                    r = Path(root)
                except Exception:
                    continue
                try:
                    resolved = str(r.resolve())
                except Exception:
                    resolved = str(r)
                if resolved in seen_roots:
                    continue
                seen_roots.add(resolved)
                if not r.exists():
                    continue

                # Support both the per-card subdirectory layout (/<root>/<card_id>/*.json)
                # and a flat layout where json files may live directly under the root.
                for child in sorted(r.iterdir()):
                    try:
                        if child.is_dir():
                            card_dir = child
                            json_files = sorted([p for p in card_dir.iterdir() if p.suffix == ".json"], reverse=True)
                            if not json_files:
                                continue
                            latest = json_files[0]
                            title = None
                            card_id = card_dir.name
                            try:
                                with latest.open('r', encoding='utf-8') as fh:
                                    payload = json.load(fh)
                                    title = payload.get('title') if isinstance(payload, dict) else None
                                    card_id = payload.get('cardId') or payload.get('id') or payload.get('contentId') or card_dir.name
                            except Exception:
                                title = None
                            # Check whether the card currently exists on the server; if it does not,
                            # treat it as deleted and offer restore.
                            try:
                                try:
                                    api.get_card(card_id)
                                    exists = True
                                except Exception:
                                    exists = False
                            except Exception:
                                exists = False
                            if not exists:
                                deleted_entries.append((card_id, title or '', latest))
                        elif child.is_file() and child.suffix == ".json":
                            # Flat file directly under versions root
                            latest = child
                            title = None
                            card_id = latest.stem
                            try:
                                with latest.open('r', encoding='utf-8') as fh:
                                    payload = json.load(fh)
                                    title = payload.get('title') if isinstance(payload, dict) else None
                                    card_id = payload.get('cardId') or payload.get('id') or payload.get('contentId') or latest.stem
                            except Exception:
                                title = None
                            try:
                                try:
                                    api.get_card(card_id)
                                    exists = True
                                except Exception:
                                    exists = False
                            except Exception:
                                exists = False
                            if not exists:
                                deleted_entries.append((card_id, title or '', latest))
                    except Exception:
                        # Ignore child-specific errors; continue scanning other entries
                        pass
        except Exception:
            deleted_entries = []

        # Dedupe by card id, keeping the newest version file (by mtime)
        try:
            dedup = {}
            for cid, title, path in deleted_entries:
                try:
                    mtime = path.stat().st_mtime if path and path.exists() else 0
                except Exception:
                    mtime = 0
                if cid not in dedup:
                    dedup[cid] = (title, path, mtime)
                else:
                    try:
                        _, _, prev_mtime = dedup[cid]
                    except Exception:
                        prev_mtime = 0
                    if mtime > (prev_mtime or 0):
                        dedup[cid] = (title, path, mtime)
            deleted_entries = [(cid, t, p) for cid, (t, p, _) in dedup.items()]
        except Exception:
            pass

        if not deleted_entries:
            try:
                show_snack("No deleted versions available to restore")
            except Exception:
                pass
            return

        lv = ft.ListView(expand=True)
        for card_id, title, path in deleted_entries:
            label = f"{title or '<untitled>'} ({card_id})"
            lv.controls.append(ft.Checkbox(label=label, value=False, data=str(path)))

        def do_restore(_ev=None):
            restored = 0
            for cb in lv.controls:
                try:
                    if getattr(cb, 'value', False):
                        path = getattr(cb, 'data', None)
                        if path:
                            try:
                                api.restore_version(Path(path), return_card=True)
                                restored += 1
                            except Exception:
                                pass
                except Exception:
                    pass
            try:
                show_snack(f"Restored {restored} versions")
            except Exception:
                pass
            dlg.open = False
            page.update()
            threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()

        dlg = ft.AlertDialog(title=ft.Text("Restore deleted cards"), content=lv, actions=[ft.TextButton("Restore Selected", on_click=do_restore), ft.TextButton("Cancel", on_click=lambda e: setattr(dlg, 'open', False))])
        try:
            page.open(dlg)
            page.update()
        except Exception:
            try:
                page.dialog = dlg
                page.update()
            except Exception:
                pass
    restore_versions_btn.on_click = _open_versions_dialog
    multi_select_btn = ft.ElevatedButton(text="Select Multiple")
    add_tags_btn = ft.ElevatedButton(text="Add Tags to Selected", disabled=True)
    add_tags_btn.visible = False
    # Bulk edit category button
    edit_category_btn = ft.ElevatedButton(text="Edit Category for Selected", disabled=True)
    edit_category_btn.visible = False
    # Bulk edit author button
    edit_author_btn = ft.ElevatedButton(text="Edit Author for Selected", disabled=True)
    edit_author_btn.visible = False

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

    def _clean_controls():
        """Remove any invalid entries from UI control lists that may cause
        Flet to raise AssertionError when building update commands.

        This is defensive: some code paths previously appended None or
        non-Control objects into lists which breaks the Flet RPC layer.
        """
        try:
            # Keep only real ft.Control instances in playlists_list
            try:
                cleaned = [c for c in playlists_list.controls if isinstance(c, ft.Control)]
                if len(cleaned) != len(playlists_list.controls):
                    playlists_list.controls[:] = cleaned
            except Exception:
                pass
            # Also defensively clean file_rows_column if it exists and has controls
            try:
                if hasattr(file_rows_column, 'controls'):
                    cleaned_fr = [c for c in file_rows_column.controls if isinstance(c, ft.Control)]
                    if len(cleaned_fr) != len(file_rows_column.controls):
                        file_rows_column.controls[:] = cleaned_fr
            except Exception:
                pass
        except Exception:
            pass

    def _safe_page_update():
        """Call page.update() but recover from AssertionError by cleaning
        invalid controls and retrying once.
        """
        try:
            page.update()
            return
        except AssertionError:
            logger.error("page.update() raised AssertionError - attempting to clean UI controls and retry")
            try:
                _clean_controls()
            except Exception:
                pass
            try:
                page.update()
            except Exception as ex:
                logger.error(f"page.update retry failed: {ex}")
        except Exception as ex:
            # Propagate other exceptions as before
            logger.error(f"page.update failed: {ex}")

    # Expose a page-level cleanup helper so other modules (notably gui.show_snack)
    # can attempt automatic recovery when page.update() raises AssertionError.
    try:
        if not hasattr(page, 'clean_ui'):
            setattr(page, 'clean_ui', _clean_controls)
    except Exception:
        pass

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
                logger.info(f"[delete] Deleted {cid}")
            except Exception as e:
                logger.error(f"[delete] Failed to delete {cid}: {e}")
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
            edit_category_btn.visible = multi_select_mode
            edit_author_btn.visible = multi_select_mode
            select_all_btn.visible = multi_select_mode
            if not multi_select_mode:
                try:
                    select_all_btn.text = "Select all"
                    select_all_btn.update()
                except Exception:
                    pass
            if not multi_select_mode:
                selected_playlist_ids.clear()
                _update_multiselect_buttons()
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

    # Select All / Deselect All control (visible only in multi-select mode)
    select_all_btn = ft.ElevatedButton(text="Select all", visible=False)

    def _update_multiselect_buttons():
        """Central helper to set disabled state for multiselect action buttons."""
        try:
            disabled = len(selected_playlist_ids) == 0
            try:
                delete_selected_btn.disabled = disabled
            except Exception:
                pass
            try:
                export_selected_btn.disabled = disabled
            except Exception:
                pass
            try:
                add_tags_btn.disabled = disabled
            except Exception:
                pass
            try:
                edit_category_btn.disabled = disabled
            except Exception:
                pass
            try:
                edit_author_btn.disabled = disabled
            except Exception:
                pass
            try:
                delete_selected_btn.update()
                export_selected_btn.update()
                add_tags_btn.update()
                edit_category_btn.update()
                try:
                    edit_author_btn.update()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass
        except Exception:
            pass

    def _set_all_checkboxes(value: bool):
        """Set all playlist row checkboxes to value (True=checked, False=unchecked)."""
        try:
            for row in playlists_list.controls:
                for child in getattr(row, "controls", []):
                    if getattr(child, "_is_playlist_checkbox", False):
                        try:
                            child.value = value
                            # ensure UI updated
                            child.update()
                            # update selection set
                            if value:
                                selected_playlist_ids.add(getattr(child, "_cid", None))
                            else:
                                selected_playlist_ids.discard(getattr(child, "_cid", None))
                        except Exception:
                            pass
        except Exception:
            pass

    def select_all_toggle(ev=None):
        try:
            if select_all_btn.text == "Select all":
                _set_all_checkboxes(True)
                select_all_btn.text = "Deselect all"
            else:
                _set_all_checkboxes(False)
                select_all_btn.text = "Select all"
            _update_multiselect_buttons()
            try:
                select_all_btn.update()
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    select_all_btn.on_click = select_all_toggle

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
                    # save a local version snapshot before deleting so it can be restored
                    try:
                        try:
                            payload = card.model_dump(exclude_none=True) if hasattr(card, 'model_dump') else None
                        except Exception:
                            payload = None
                        if isinstance(payload, dict):
                            try:
                                api.save_version(payload)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    api.delete_content(content_id)
                    try:
                        # Only remove if row_container looks like a real control and is present
                        if row_container is not None and isinstance(row_container, ft.Control) and row_container in playlists_list.controls:
                            playlists_list.controls.remove(row_container)
                        else:
                            # defensive fallback: remove any None entries, otherwise clear to avoid invalid payloads
                            try:
                                cleaned = [c for c in playlists_list.controls if c is not None and isinstance(c, ft.Control)]
                                playlists_list.controls[:] = cleaned
                            except Exception:
                                try:
                                    playlists_list.controls.clear()
                                except Exception:
                                    pass
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
                try:
                    # Prefer cached local path from page helper if available
                    cache_fn = getattr(page, 'get_cached_cover', None)
                    if callable(cache_fn) and str(cover_src).startswith("http"):
                        p = cache_fn(cover_src)
                        if p:
                            img_ctrl = ft.Image(src=str(p), width=64, height=64)
                        else:
                            img_ctrl = ft.Image(src=cover_src, width=64, height=64)
                    else:
                        img_ctrl = ft.Image(src=str(cover_src), width=64, height=64)
                except Exception:
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
                _update_multiselect_buttons()
                page.update()
            except Exception:
                pass

        def _on_edit_category_selected(ev):
            if not selected_playlist_ids:
                return
            # Category dropdown similar to category_filter options
            cat_dropdown = ft.Dropdown(
                label="New category",
                width=300,
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
            status_text = ft.Text("")

            def do_set_category(_e=None):
                new_cat = (cat_dropdown.value or "").strip()
                client = CLIENT_ID
                api: YotoAPI = ensure_api(api_ref, client)
                updated = 0
                for cid in list(selected_playlist_ids):
                    try:
                        card = api.get_card(cid)
                        meta = getattr(card, "metadata", CardMetadata())
                        if new_cat == "":
                            # interpret empty as clearing category
                            try:
                                meta.category = ""
                            except Exception:
                                pass
                        else:
                            try:
                                meta.category = new_cat
                            except Exception:
                                pass
                        card.metadata = meta
                        api.update_card(card, return_card_model=False)
                        updated += 1
                    except Exception as ex:
                        logger.error(f"Failed to update category for {cid}: {ex}")
                status_text.value = f"Updated category for {updated} playlists"
                try:
                    show_snack(status_text.value)
                except Exception:
                    pass
                dlg.open = False
                threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                page.update()

            def do_remove_category(_e=None):
                # Explicitly remove/clear category for selected playlists
                client = CLIENT_ID
                api: YotoAPI = ensure_api(api_ref, client)
                removed = 0
                for cid in list(selected_playlist_ids):
                    try:
                        card = api.get_card(cid)
                        meta = getattr(card, "metadata", CardMetadata())
                        try:
                            meta.category = ""
                        except Exception:
                            pass
                        card.metadata = meta
                        api.update_card(card, return_card_model=False)
                        removed += 1
                    except Exception as ex:
                        logger.error(f"Failed to remove category for {cid}: {ex}")
                status_text.value = f"Removed category from {removed} playlists"
                try:
                    show_snack(status_text.value)
                except Exception:
                    pass
                dlg.open = False
                threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                page.update()

            def close_edit(_e=None):
                try:
                    dlg.open = False
                except Exception:
                    pass
                page.update()

            dlg = ft.AlertDialog(
                title=ft.Text("Edit Category for Selected Playlists"),
                content=ft.Column([cat_dropdown, status_text]),
                actions=[
                    ft.TextButton("Set Category", on_click=do_set_category),
                    ft.TextButton("Remove Category", on_click=do_remove_category),
                    ft.TextButton("Cancel", on_click=close_edit),
                ],
            )
            try:
                page.open(dlg)
            except Exception:
                try:
                    page.dialog = dlg
                    page.update()
                except Exception:
                    pass

        edit_category_btn.on_click = _on_edit_category_selected

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

        def _on_edit_author_selected(ev):
            if not selected_playlist_ids:
                return
            author_field = ft.TextField(label="Author (leave blank to clear)", width=400)
            status_text = ft.Text("")

            def do_set_author(_e=None):
                new_author = (author_field.value or "").strip()
                client = CLIENT_ID
                api: YotoAPI = ensure_api(api_ref, client)
                updated = 0
                for cid in list(selected_playlist_ids):
                    try:
                        card = api.get_card(cid)
                        meta = getattr(card, "metadata", CardMetadata())
                        try:
                            meta.author = new_author
                        except Exception:
                            pass
                        card.metadata = meta
                        api.update_card(card, return_card_model=False)
                        updated += 1
                    except Exception as ex:
                        logger.error(f"Failed to update author for {cid}: {ex}")
                status_text.value = f"Updated author for {updated} playlists"
                try:
                    show_snack(status_text.value)
                except Exception:
                    pass
                dlg.open = False
                threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                page.update()

            def do_remove_author(_e=None):
                client = CLIENT_ID
                api: YotoAPI = ensure_api(api_ref, client)
                removed = 0
                for cid in list(selected_playlist_ids):
                    try:
                        card = api.get_card(cid)
                        meta = getattr(card, "metadata", CardMetadata())
                        try:
                            meta.author = ""
                        except Exception:
                            pass
                        card.metadata = meta
                        api.update_card(card, return_card_model=False)
                        removed += 1
                    except Exception as ex:
                        logger.error(f"Failed to remove author for {cid}: {ex}")
                status_text.value = f"Removed author from {removed} playlists"
                try:
                    show_snack(status_text.value)
                except Exception:
                    pass
                dlg.open = False
                threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                page.update()

            def close_author(_e=None):
                try:
                    dlg.open = False
                except Exception:
                    pass
                page.update()

            dlg = ft.AlertDialog(
                title=ft.Text("Edit Author for Selected Playlists"),
                content=ft.Column([author_field, status_text]),
                actions=[
                    ft.TextButton("Set Author", on_click=do_set_author),
                    ft.TextButton("Remove Author", on_click=do_remove_author),
                    ft.TextButton("Cancel", on_click=close_author),
                ],
            )
            try:
                page.open(dlg)
            except Exception:
                try:
                    page.dialog = dlg
                    page.update()
                except Exception:
                    pass

        edit_author_btn.on_click = _on_edit_author_selected

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
                    _update_multiselect_buttons()
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
                    _update_multiselect_buttons()
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
                _update_multiselect_buttons()
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
            # Show author in playlist row if present
            author = meta.get("author") or meta.get("creator") or ""
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
        meta_text = (
            ft.Text(" | ".join(meta_line), size=12, color=ft.Colors.BLACK54)
            if meta_line
            else None
        )

        # Show cardId and a short description (if present) beside it
        def _trunc(s, n=80):
            try:
                if not s:
                    return ''
                s = str(s)
                return s if len(s) <= n else s[: n - 1] + '…'
            except Exception:
                return ''

        short_desc = ''
        try:
            short_desc = _trunc(meta.get('description') or '')
        except Exception:
            short_desc = ''

        # Subtitle contains preview, description and metadata; card id is shown on the row's right
        subtitle_items = []
        if preview:
            subtitle_items.append(ft.Text(preview, size=12, color=ft.Colors.BLACK45))

        # Add truncated description as a subtitle line (if present)
        try:
            short_desc = _trunc(meta.get('description') or '')
        except Exception:
            short_desc = ''
        if short_desc:
            subtitle_items.append(ft.Text(short_desc, size=12, color=ft.Colors.BLACK45))
        if meta_text:
            subtitle_items.append(meta_text)
        subtitle = ft.Column(subtitle_items)
        tile = ft.ListTile(title=ft.Text(title), subtitle=subtitle, on_click=_on_tile_click)

        # Card ID placed to the right of the row (muted)
        id_text = ft.Text(str(cid), size=11, color=ft.Colors.BLACK45)

        row = ft.Row(
            [cb, img_ctrl, ft.Container(content=tile, expand=True), id_text, delete_btn],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
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

    # `show_card_details` implementation was moved to `yoto_app.card_details`.
    # We create a placeholder here and instantiate the real callable later
    # (after `fetch_playlists_sync` is defined) so ordering of helpers doesn't
    # affect callback wiring.
    show_card_details = None

    async def fetch_playlists(e=None):
        print("Fetching playlists...")
        # Clean any stale/invalid controls before touching the page
        _clean_controls()
        try:
            _safe_page_update()
        except Exception:
            pass
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
        # Persist playlists for faster startup and offline view
        try:
            serializable = []
            for c in cards:

                    serializable.append(c.model_dump(exclude_none=True))
            try:
                save_playlists(serializable)
            except Exception:
                pass
        except Exception:
            pass
        try:
            _safe_page_update()
        except Exception:
            pass

    def fetch_playlists_sync(e=None):
        print("Fetching playlists...")
        try:
            # Clean invalid controls before showing snack / updating page
            _clean_controls()
            try:
                show_snack("Fetching playlists...")
            except Exception:
                pass
            try:
                _safe_page_update()
            except Exception:
                pass
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
                except Exception:
                    sorted_cards = cards

                # Build rows for each card; only append valid ft.Control objects.
                for idx, c in enumerate(sorted_cards):
                    try:
                        if not card_matches_filters(c):
                            continue
                        try:
                            row = make_playlist_row(c, idx=idx)
                        except Exception:
                            row = None
                        if row is not None and isinstance(row, ft.Control):
                            playlists_list.controls.append(row)
                        else:
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
                            playlists_list.controls.append(
                                ft.ListTile(
                                    title=ft.Text(title),
                                    subtitle=ft.Text(str(cid)),
                                    on_click=lambda ev, card=c: show_card_details(ev, card),
                                )
                            )
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
                            or getattr(c, "cardId", None)
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
            try:
                show_snack(f"Fetched {len(cards)} playlists")
            except Exception:
                pass
            try:
                _safe_page_update()
            except Exception:
                pass
            # Persist playlists after sync fetch
            try:
                serializable = []
                for c in cards:
                    try:
                        if hasattr(c, 'model_dump'):
                            serializable.append(c.model_dump(exclude_none=True))
                        elif isinstance(c, dict):
                            serializable.append(c)
                        else:
                            serializable.append(str(c))
                    except Exception:
                        try:
                            serializable.append(str(c))
                        except Exception:
                            pass
                try:
                    save_playlists(serializable)
                except Exception:
                    pass
            except Exception:
                pass
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

    # Allow pressing Enter in any filter TextField to apply filters (same as Apply Filter)
    try:
        title_filter.on_submit = lambda e: threading.Thread(
            target=lambda: fetch_playlists_sync(e), daemon=True
        ).start()
    except Exception:
        pass
    try:
        genre_filter.on_submit = lambda e: threading.Thread(
            target=lambda: fetch_playlists_sync(e), daemon=True
        ).start()
    except Exception:
        pass
    try:
        tags_filter.on_submit = lambda e: threading.Thread(
            target=lambda: fetch_playlists_sync(e), daemon=True
        ).start()
    except Exception:
        pass

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
                    select_all_btn,
                    delete_selected_btn,
                    export_selected_btn,
                    import_card_btn,
                    restore_versions_btn,
                    add_tags_btn,
                    edit_category_btn,
                    edit_author_btn,
                    sort_dropdown,
                ],
                wrap=True,
                spacing=8,
                alignment=ft.MainAxisAlignment.START,
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

    # Instantiate the externalized show_card_details implementation.
    try:
        show_card_details = make_show_card_details(
            page=page,
            api_ref=api_ref,
            show_snack=show_snack,
            ensure_api=ensure_api,
            CLIENT_ID=CLIENT_ID,
            Card=Card,
            fetch_playlists_sync=fetch_playlists_sync,
            playlists_list=playlists_list,
            make_playlist_row=make_playlist_row,
            status_ctrl=status_ctrl,
            show_edit_card_dialog=show_edit_card_dialog,
            IconReplaceDialog=IconReplaceDialog,
            show_replace_icons_dialog=show_replace_icons_dialog,
        )
    except Exception:
        show_card_details = None

    return {
        "playlists_column": playlists_column,
        "fetch_playlists": fetch_playlists,
        "fetch_playlists_sync": fetch_playlists_sync,
        "playlists_list": playlists_list,
        "existing_card_dropdown": existing_card_dropdown,
        "existing_card_map": existing_card_map,
        "make_playlist_row": make_playlist_row,
        "show_card_details": show_card_details,
        "delete_selected_btn": delete_selected_btn,
        "multi_select_btn": multi_select_btn,
        "add_tags_btn": add_tags_btn,
        "edit_category_btn": edit_category_btn,
        "export_selected_btn": export_selected_btn,
        "import_card_btn": import_card_btn,
        "fetch_btn": fetch_btn,
        "sort_dropdown": sort_dropdown,
        "current_sort": current_sort,
    }
