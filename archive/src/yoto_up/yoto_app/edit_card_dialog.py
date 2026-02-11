import flet as ft
import threading
from types import SimpleNamespace
from copy import deepcopy
from loguru import logger

from yoto_up.yoto_api import YotoAPI
from yoto_up.models import Card

from .icon_import_helpers import get_base64_from_path

# This function is designed to be imported and called from playlists.py
# It expects the same arguments as the original show_edit closure.
def show_edit_card_dialog(
    c,
    page,
    ensure_api,
    CLIENT_ID,
    status_ctrl,
    fetch_playlists_sync,
    show_card_details,
):
    """
    Show the edit card dialog for a playlist card.
    Args:
        c: The card dict/model to edit (will be mutated in-place)
        page: The Flet page
        ensure_api: Function to get API instance
        CLIENT_ID: Client ID string
        status_ctrl: Status control (SimpleNamespace or Flet control)
        fetch_playlists_sync: Function to refresh playlists
        previous_dialog_ref: Optional dict to store the previous dialog instance for external closing
    """

    try:
        title_field = ft.TextField(label="Card Title", value=c.get("title", ""))
    except Exception:
        title_field = ft.TextField(label="Card Title", value="")

    card_pre_edit = deepcopy(c)

    # Persistent state for DnD and field mapping
    if not hasattr(show_edit_card_dialog, "_state") or not isinstance(getattr(show_edit_card_dialog, "_state", None), SimpleNamespace):
        show_edit_card_dialog._state = SimpleNamespace(flat_items=None, last_card_id=None)
    state = show_edit_card_dialog._state


    chapter_fields = []
    track_fields = []
    chapters_local = c.get("content", {}).get("chapters") or []
    meta = c.get("metadata") or {}
    category_value = meta.get("category") or ""
    category_dropdown = ft.Dropdown(
        label="Category",
        width=300,
        value=category_value,
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
    description_field = ft.TextField(
        label="Description",
        value=meta.get("description") or "",
        multiline=True,
        width=760,
    )
    note_field = ft.TextField(
        label="Note (metadata)",
        value=meta.get("note") or "",
        multiline=True,
        min_lines=2,
        max_lines=6,
        width=760,
    )
    genre_field = ft.TextField(
        label="Genres (comma separated)",
        value=(
            ", ".join(meta.get("genre"))
            if isinstance(meta.get("genre"), (list, tuple))
            else (meta.get("genre") or "")
        ),
    )
    languages_field = ft.TextField(
        label="Languages (comma separated)",
        value=(
            ", ".join(meta.get("languages"))
            if isinstance(meta.get("languages"), (list, tuple))
            else (meta.get("languages") or "")
        ),
    )
    tags_field = ft.TextField(
        label="Tags (comma separated)",
        value=(
            ", ".join(meta.get("tags"))
            if isinstance(meta.get("tags"), (list, tuple))
            else (meta.get("tags") or "")
        ),
    )
    # Add authors field for editing
    author_field = ft.TextField(
        label="Author",
        value=meta.get("author") or "",
    )

    edit_controls = [
        title_field,
        ft.Divider(),
        ft.Text("Metadata", weight=ft.FontWeight.BOLD),
        category_dropdown,
        description_field,
        note_field,
        genre_field,
        languages_field,
        tags_field,
        author_field,
        ft.Divider(),
        ft.Text("Chapters & Tracks", weight=ft.FontWeight.BOLD),
    ]
    # Flatten chapters and tracks into a single list for DnD, using persistent state
    if state.flat_items is None or state.last_card_id != id(c):
        flat_items = []
        chapter_fields.clear()
        track_fields.clear()
        for ci, ch in enumerate(chapters_local):
            ch_title = ch.get("title", "") if isinstance(ch, dict) else str(ch)
            ch_field = ft.TextField(label=f"Chapter {ci+1} Title", value=ch_title)
            chapter_fields.append(ch_field)
            ch_icon = None
            if isinstance(ch, dict):
                display = ch.get("display") or {}
                icon_field = display.get("icon16x16") if isinstance(display, dict) else None
                if icon_field:
                    api = ensure_api(api_ref=None, client=CLIENT_ID)
                    try:
                        icon_path = api.get_icon_cache_path(icon_field)
                        if icon_path is not None:
                            if icon_path.exists():
                                ch_icon = ft.Image(src_base64=get_base64_from_path(icon_path), width=24, height=24)
                    except Exception:
                        pass
            def make_delete_chapter(idx=ci, ch_title=ch_title):
                def delete_chapter(_e):
                    confirm_dialog = ft.AlertDialog(
                        title=ft.Text("Delete Chapter"),
                        content=ft.Text(f"Delete chapter '{ch_title}' and all its tracks? This cannot be undone."),
                        actions=[
                            ft.TextButton("Yes", on_click=lambda e: (setattr(confirm_dialog, 'open', False), chapters_local.pop(idx), show_edit_card_dialog(
                                c,
                                page,
                                ensure_api,
                                CLIENT_ID,
                                status_ctrl,
                                fetch_playlists_sync,
                                show_card_details=show_card_details,
                            ))),
                            ft.TextButton("No", on_click=lambda e: (setattr(confirm_dialog, 'open', False), show_edit_card_dialog(
                                c,
                                page,
                                ensure_api,
                                CLIENT_ID,
                                status_ctrl,
                                fetch_playlists_sync,
                                show_card_details=show_card_details,
                            ))),
                        ],
                    )
                    try:
                        page.open(confirm_dialog)
                    except Exception:
                        try:
                            page.dialog = confirm_dialog
                            page.update()
                        except Exception:
                            pass
                return delete_chapter
            flat_items.append({
                "type": "chapter",
                "ch": ch,
                "ch_field": ch_field,
                "ch_icon": ch_icon,
                "delete": make_delete_chapter(ci, ch_title)
            })
            t_fields_for_ch = []
            tracks = ch.get("tracks") if isinstance(ch, dict) else None
            if tracks:
                for ti, tr in enumerate(tracks):
                    tr_title = tr.get("title", "") if isinstance(tr, dict) else str(tr)
                    tr_field = ft.TextField(label="", value=tr_title)
                    tr_icon = None
                    if isinstance(tr, dict):
                        display = tr.get("display") or {}
                        icon_field = display.get("icon16x16") if isinstance(display, dict) else None
                        if icon_field:
                            api: YotoAPI = ensure_api(api_ref=None, client=CLIENT_ID)
                            try:
                                icon_path = api.get_icon_cache_path(icon_field)
                                if icon_path is not None:
                                    if icon_path.exists():
                                        tr_icon = ft.Image(src_base64=get_base64_from_path(icon_path), width=20, height=20)
                            except Exception:
                                pass
                    def make_delete_track(ci=ci, ti=ti):
                        def delete_track(_e):
                            try:
                                ch_obj = chapters_local[ci]
                                if isinstance(ch_obj, dict) and "tracks" in ch_obj:
                                    if 0 <= ti < len(ch_obj["tracks"]):
                                        del ch_obj["tracks"][ti]
                                        show_edit_card_dialog(
                                            c,
                                            page,
                                            ensure_api,
                                            CLIENT_ID,
                                            status_ctrl,
                                            fetch_playlists_sync,
                                            show_card_details=show_card_details,
                                        )
                            except Exception as ex:
                                logger.error(f"Failed to delete track: {ex}")
                        return delete_track
                    flat_items.append({
                        "type": "track",
                        "tr": tr,
                        "tr_field": tr_field,
                        "tr_icon": tr_icon,
                        "delete": make_delete_track(ci, ti),
                        "ch_idx": ci
                    })
                    t_fields_for_ch.append(tr_field)
            track_fields.append(t_fields_for_ch)
        state.flat_items = flat_items
        state.last_card_id = id(c)
    else:
        flat_items = state.flat_items
        # Rebuild chapter_fields and track_fields from flat_items for correct mapping
        chapter_fields.clear()
        track_fields.clear()
        t_fields_for_ch = []
        for entry in flat_items:
            if entry["type"] == "chapter":
                if t_fields_for_ch:
                    track_fields.append(t_fields_for_ch)
                chapter_fields.append(entry["ch_field"])
                t_fields_for_ch = []
            elif entry["type"] == "track":
                t_fields_for_ch.append(entry["tr_field"])
        if t_fields_for_ch:
            track_fields.append(t_fields_for_ch)

    # Render flat list with DnD
    def on_reorder(ev):
        old = ev.old_index
        new = ev.new_index
        if old is None or new is None or old == new:
            return
        item = flat_items.pop(old)
        flat_items.insert(new, item)
        # Rebuild chapters_local from flat_items
        new_chapters = []
        current_ch = None
        for entry in flat_items:
            if entry["type"] == "chapter":
                current_ch = deepcopy(entry["ch"])
                current_ch["tracks"] = []
                new_chapters.append(current_ch)
            elif entry["type"] == "track":
                if current_ch is not None:
                    current_ch["tracks"].append(entry["tr"])
        chapters_local.clear()
        chapters_local.extend(new_chapters)
        # After reorder, rebuild dialog so labels are correct
        #show_edit_card_dialog(
        #    c,
        #    page,
        #    ensure_api,
        #    CLIENT_ID,
        #    status_ctrl,
        #    fetch_playlists_sync,
        #    show_card_details=show_card_details,
        #)

    dnd_controls = []
    chapter_counter = 0
    track_counter = 0
    for idx, entry in enumerate(flat_items):
        if entry["type"] == "chapter":
            chapter_counter += 1
            entry["ch_field"].label = f"Chapter {chapter_counter} Title"
            def delete_chapter_at(idx=idx):
                def _delete(_e):
                    # Remove chapter and any following tracks until next chapter or end
                    state = show_edit_card_dialog._state
                    items = state.flat_items
                    # Remove the chapter
                    items.pop(idx)
                    # Remove all tracks after this chapter until next chapter or end
                    while idx < len(items) and items[idx]["type"] == "track":
                        items.pop(idx)
                    state.flat_items = items
                    show_edit_card_dialog(
                        c,
                        page,
                        ensure_api,
                        CLIENT_ID,
                        status_ctrl,
                        fetch_playlists_sync,
                        show_card_details=show_card_details,
                    )
                return _delete
            dnd_controls.append(
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            entry["ch_icon"] if entry["ch_icon"] else ft.Container(width=24),
                            entry["ch_field"],
                            ft.IconButton(icon=ft.Icons.DELETE, tooltip="Delete chapter", on_click=delete_chapter_at()),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=ft.padding.only(left=8),
                    )
                ])
            )
            track_counter = 0
        elif entry["type"] == "track":
            track_counter += 1
            entry["tr_field"].label = f"Track {track_counter} Title"
            def delete_track_at(idx=idx):
                def _delete(_e):
                    state = show_edit_card_dialog._state
                    items = state.flat_items
                    items.pop(idx)
                    state.flat_items = items
                    show_edit_card_dialog(
                        c,
                        page,
                        ensure_api,
                        CLIENT_ID,
                        status_ctrl,
                        fetch_playlists_sync,
                        show_card_details=show_card_details,
                    )
                return _delete
            dnd_controls.append(
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            entry["tr_icon"] if entry["tr_icon"] else ft.Container(width=20),
                            entry["tr_field"],
                            ft.IconButton(icon=ft.Icons.DELETE, tooltip="Delete track", on_click=delete_track_at()),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=ft.padding.only(left=32),
                    )
                ])
            )

    edit_controls.append(
        ft.ReorderableListView(dnd_controls, on_reorder=on_reorder)
    )

    def do_save(_ev=None):
        new_title = title_field.value
        if "metadata" not in c or not isinstance(
            c.get("metadata"), dict
        ):
            c["metadata"] = {}
        c["metadata"]["category"] = category_dropdown.value or None
        desc = description_field.value or ""
        c["metadata"]["description"] = desc if desc else None
        c["metadata"]["note"] = note_field.value or None

        def split_list(s):
            if not s:
                return None
            parts = [p.strip() for p in s.split(",") if p.strip()]
            return parts if parts else None

        c["metadata"]["genre"] = split_list(genre_field.value)
        c["metadata"]["languages"] = split_list(languages_field.value)
        c["metadata"]["tags"] = split_list(tags_field.value)
        c["metadata"]["author"] = author_field.value or None

        # Rebuild chapters_local from flat_items before saving
        state = show_edit_card_dialog._state
        flat_items = state.flat_items
        new_chapters = []
        current_ch = None
        chapter_fields_save = []
        track_fields_save = []
        t_fields_for_ch = []
        for entry in flat_items:
            if entry["type"] == "chapter":
                if current_ch is not None:
                    track_fields_save.append(t_fields_for_ch)
                current_ch = deepcopy(entry["ch"])
                current_ch["tracks"] = []
                new_chapters.append(current_ch)
                chapter_fields_save.append(entry["ch_field"])
                t_fields_for_ch = []
            elif entry["type"] == "track":
                if current_ch is not None:
                    current_ch["tracks"].append(entry["tr"])
                    t_fields_for_ch.append(entry["tr_field"])
        if current_ch is not None:
            track_fields_save.append(t_fields_for_ch)
        chapters_local.clear()
        chapters_local.extend(new_chapters)

        card_model = Card.model_validate(c)
        if new_title is not None:
            card_model.title = new_title
        try:
            if card_model.content and getattr(
                card_model.content, "chapters", None
            ):
                for idx, ch_model in enumerate(card_model.content.chapters):
                    if idx < len(chapter_fields_save):
                        ch_model.title = chapter_fields_save[idx].value
                    if hasattr(ch_model, "tracks") and ch_model.tracks:
                        for t_idx, tr_model in enumerate(ch_model.tracks):
                            if t_idx < len(track_fields_save[idx]):
                                tr_model.title = track_fields_save[idx][
                                    t_idx
                                ].value

            def save_thread():
                try:
                    api = ensure_api(api_ref=None, client=CLIENT_ID)
                    api.update_card(card_model, return_card_model=False)
                    status_ctrl.value = "Card updated"
                    fetch_playlists_sync(None)
                except Exception as ex:
                    logger.debug(f"Update card failed: {ex}")
                    msg = f"Update failed: {ex}"
                    status_ctrl.value = msg
                finally:
                    show_card_details(None, card_model)
                    page.update()

            threading.Thread(target=save_thread, daemon=True).start()
        except Exception as ex:
            logger.debug(f"Failed to prepare update: {ex}")
            msg = f"Failed to prepare update: {ex}"
            status_ctrl.value = msg
            page.update()
        page.update()

    def close_edit(_ev):
        show_card_details(None, card_pre_edit)
        page.update()

    edit_list = ft.ListView(
        edit_controls, spacing=6, padding=10, height=500, width=800
    )
    edit_dialog = ft.AlertDialog(
        title=ft.Text("Edit card"),
        content=edit_list,
        actions=[
            ft.TextButton("Save", on_click=do_save),
            ft.TextButton("Cancel", on_click=close_edit),
        ],
    )

    page.open(edit_dialog)
    page.update()
