from yoto_up.yoto_app.api_manager import ensure_api
import flet as ft
from types import SimpleNamespace
from copy import deepcopy
from loguru import logger
from typing import Literal, cast

from yoto_up.models import Card, CardContent, Chapter, Track

from .icon_import_helpers import get_base64_from_path


_EDIT_DIALOG_STATE = SimpleNamespace(flat_items=None, last_card_id=None)

# This function is designed to be imported and called from playlists.py
# It expects the same arguments as the original show_edit closure.
def show_edit_card_dialog(
    c: Card,
    page,
):
    """
    Show the edit card dialog for a playlist card.
    Args:
        c: The card dict/model to edit (will be mutated in-place)
        page: The Flet page
        ensure_api: Function to get API instance
        CLIENT_ID: Client ID string
        fetch_playlists_sync: Function to refresh playlists
        previous_dialog_ref: Optional dict to store the previous dialog instance for external closing
    """

    api = ensure_api(page.api_ref)
    title_field = ft.TextField(label="Card Title", value=c.title)

    card_pre_edit = deepcopy(c)

    # Persistent state for DnD and field mapping
    state = _EDIT_DIALOG_STATE


    chapter_fields = []
    track_fields = []
    chapters_local = c.get_chapters()
    meta = c.get_metadata()
    category_value = meta.category
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
        value=meta.description or "",
        multiline=True,
        width=760,
    )
    note_field = ft.TextField(
        label="Note (metadata)",
        value=meta.note or "",
        multiline=True,
        min_lines=2,
        max_lines=6,
        width=760,
    )
    genre_field = ft.TextField(
        label="Genres (comma separated)",
        value=(
            ", ".join(meta.genre)
            if isinstance(meta.genre, (list, tuple))
            else (meta.genre or "")
        ),
    )
    languages_field = ft.TextField(
        label="Languages (comma separated)",
        value=(
            ", ".join(meta.languages)
            if isinstance(meta.languages, (list, tuple))
            else (meta.languages or "")
        ),
    )
    tags_field = ft.TextField(
        label="Tags (comma separated)",
        value=(
            ", ".join(meta.tags)
            if isinstance(meta.tags, (list, tuple))
            else (meta.tags or "")
        ),
    )
    # Add authors field for editing
    author_field = ft.TextField(
        label="Author",
        value=meta.author or "",
    )

    edit_controls = [
        title_field,
        ft.Divider(),
        ft.Text(value="Metadata", weight=ft.FontWeight.BOLD),
        category_dropdown,
        description_field,
        note_field,
        genre_field,
        languages_field,
        tags_field,
        author_field,
        ft.Divider(),
        ft.Text(value="Chapters & Tracks", weight=ft.FontWeight.BOLD),
    ]
    # Flatten chapters and tracks into a single list for DnD, using persistent state
    if state.flat_items is None or state.last_card_id != id(c):
        flat_items = []
        chapter_fields.clear()
        track_fields.clear()
        for ci, ch in enumerate(chapters_local):
            ch_title = ch.title
            ch_field = ft.TextField(label=f"Chapter {ci+1} Title", value=ch_title)
            chapter_fields.append(ch_field)
            ch_icon = None
            icon_field = ch.get_icon_field()
            if icon_field:
                try:
                    icon_path = api.get_icon_cache_path(icon_field)
                    if icon_path is not None:
                        if icon_path.exists():
                            ch_icon = ft.Image(src=get_base64_from_path(icon_path), width=24, height=24)
                except Exception:
                    logger.exception(f"Failed to load chapter icon for chapter {ci} with icon field {icon_field}")
            def make_delete_chapter(idx=ci, ch_title=ch_title):
                def delete_chapter(_e):
                    confirm_dialog = ft.AlertDialog(
                        title=ft.Text(value="Delete Chapter"),
                        content=ft.Text(value=f"Delete chapter '{ch_title}' and all its tracks? This cannot be undone."),
                        actions=[
                            ft.TextButton(content="Yes", on_click=lambda e: (setattr(confirm_dialog, 'open', False), chapters_local.pop(idx), show_edit_card_dialog(
                                c,
                                page,
                            ))),
                            ft.TextButton(content="No", on_click=lambda e: (setattr(confirm_dialog, 'open', False), show_edit_card_dialog(
                                c,
                                page,
                            ))),
                        ],
                    )
                    try:
                        page.show_dialog(confirm_dialog)
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
            tracks = ch.get_tracks()
            if tracks:
                for ti, tr in enumerate(tracks):
                    tr_title = tr.get_title()
                    tr_field = ft.TextField(label="", value=tr_title)
                    tr_icon = None
                    icon_field = tr.get_icon_field()
                    if icon_field is not None:
                        try:
                            icon_path = api.get_icon_cache_path(icon_field)
                            if icon_path is not None:
                                if icon_path.exists():
                                    tr_icon = ft.Image(src=get_base64_from_path(icon_path), width=20, height=20)
                        except Exception:
                            logger.exception(f"Failed to load track icon for track {ti} with icon field {icon_field}")
                    def make_delete_track(ci=ci, ti=ti):
                        def delete_track(_e):
                            try:
                                ch_obj = chapters_local[ci]
                                tracks_for_chapter = ch_obj.get_tracks()
                                if 0 <= ti < len(tracks_for_chapter):
                                    del tracks_for_chapter[ti]
                                    show_edit_card_dialog(
                                        c,
                                        page,
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
        new_chapters: list[Chapter] = []
        current_ch: Chapter | None = None
        for entry in flat_items:
            if entry["type"] == "chapter":
                current_ch = deepcopy(cast(Chapter, entry["ch"]))
                current_ch.tracks = []
                new_chapters.append(current_ch)
            elif entry["type"] == "track":
                if current_ch is not None:
                    current_ch.tracks.append(cast(Track, entry["tr"]))
        chapters_local.clear()
        chapters_local.extend(new_chapters)
        # After reorder, rebuild dialog so labels are correct
        #show_edit_card_dialog(
        #    c,
        #    page,
        #    ensure_api,
        #    CLIENT_ID,
        #    fetch_playlists_sync,
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
                    state = _EDIT_DIALOG_STATE
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
                    )
                return _delete
            dnd_controls.append(
                ft.Row(controls=[
                    ft.Container(
                        content=ft.Row(controls=[
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
                    state = _EDIT_DIALOG_STATE
                    items = state.flat_items
                    items.pop(idx)
                    state.flat_items = items
                    show_edit_card_dialog(
                        c,
                        page,
                    )
                return _delete
            dnd_controls.append(
                ft.Row(controls=[
                    ft.Container(
                        content=ft.Row(controls=[
                            entry["tr_icon"] if entry["tr_icon"] else ft.Container(width=20),
                            entry["tr_field"],
                            ft.IconButton(icon=ft.Icons.DELETE, tooltip="Delete track", on_click=delete_track_at()),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=ft.padding.only(left=32),
                    )
                ])
            )

    edit_controls.append(
        ft.ReorderableListView(controls=dnd_controls, on_reorder=on_reorder)
    )

    def do_save(_ev=None):
        # Expect a Card model instance; do not accept legacy dicts anymore.
        if not isinstance(c, Card):
            raise TypeError("show_edit_card_dialog requires a `Card` model instance")
        card_model = c

        # Update title
        new_title = title_field.value
        if new_title is not None:
            card_model.title = new_title

        # Helper to parse comma-separated lists into optional list[str]
        def split_list(s):
            if not s:
                return None
            parts = [p.strip() for p in s.split(",") if p.strip()]
            return parts if parts else None

        # Ensure metadata object exists and update fields
        meta = card_model.get_metadata()
        CategoryType = Literal["", "none", "stories", "music", "radio", "podcast", "sfx", "activities", "alarms"]
        cat_value = category_dropdown.value
        allowed_categories = {"", "none", "stories", "music", "radio", "podcast", "sfx", "activities", "alarms"}
        meta.category = cast(CategoryType, cat_value) if cat_value in allowed_categories else None
        desc = description_field.value or ""
        meta.description = desc if desc else None
        meta.note = note_field.value or None
        meta.genre = split_list(genre_field.value)
        meta.languages = split_list(languages_field.value)
        meta.tags = split_list(tags_field.value)
        meta.author = author_field.value or None
        card_model.metadata = meta

        # Rebuild chapters from flat_items (preserve non-title fields where possible)
        state = _EDIT_DIALOG_STATE
        flat_items = state.flat_items or []
        new_chapters: list[Chapter] = []
        chapter_fields_save: list[ft.TextField | None] = []
        track_fields_save: list[list[ft.TextField | None]] = []
        current_ch: Chapter | None = None

        for entry in flat_items:
            if entry["type"] == "chapter":
                # Start a new chapter copy
                src_ch = cast(Chapter, entry["ch"])
                ch_copy = deepcopy(src_ch)
                ch_copy.tracks = []
                new_chapters.append(ch_copy)
                chapter_fields_save.append(cast(ft.TextField | None, entry.get("ch_field")))
                current_ch = ch_copy
                track_fields_save.append([])
            elif entry["type"] == "track":
                if current_ch is None:
                    continue
                src_tr = cast(Track, entry["tr"])
                # Append a deepcopy of the original track object/dict to preserve metadata
                tr_copy = deepcopy(src_tr)
                current_ch.tracks.append(tr_copy)
                # Track field mapping for title edits
                if track_fields_save:
                    track_fields_save[-1].append(cast(ft.TextField | None, entry.get("tr_field")))

        # Assign chapters into card_model.content
        if card_model.content is None:
            card_model.content = CardContent(chapters=new_chapters)
        else:
            card_model.content.chapters = new_chapters

        # Apply edited titles from input fields back into the model chapters/tracks
        try:
            chapters_for_save = card_model.content.chapters if card_model.content and card_model.content.chapters else []
            if chapters_for_save:
                for idx, ch_model in enumerate(chapters_for_save):
                    if idx < len(chapter_fields_save) and chapter_fields_save[idx] is not None:
                        try:
                            chapter_field = chapter_fields_save[idx]
                            if chapter_field is not None:
                                ch_model.title = chapter_field.value
                        except Exception:
                            pass
                    chapter_tracks = ch_model.get_tracks()
                    for t_idx, tr_model in enumerate(chapter_tracks):
                        if t_idx < len(track_fields_save[idx]) and track_fields_save[idx][t_idx] is not None:
                            try:
                                track_field = track_fields_save[idx][t_idx]
                                if track_field is not None:
                                    tr_model.title = track_field.value
                            except Exception:
                                pass

            async def save_thread():
                try:
                    page.update_card(card_model)
                except Exception as ex:
                    logger.debug(f"Update card failed: {ex}")
                finally:
                    page.pop_dialog()
                    page.show_card_details(card_model)
                    page.update()

            page.run_task(save_thread)
        except Exception as ex:
            logger.debug(f"Failed to prepare update: {ex}")
            page.update()
        page.update()

    def close_edit(_ev):
        page.pop_dialog()
        page.show_card_details(card_pre_edit)
        page.update()

    edit_list = ft.ListView(
        controls=edit_controls, spacing=6, padding=10, height=500, width=800
    )
    edit_dialog = ft.AlertDialog(
        title=ft.Text(value="Edit card"),
        content=edit_list,
        actions=[
            ft.TextButton(content="Save", on_click=do_save),
            ft.TextButton(content="Cancel", on_click=close_edit),
        ],
    )

    page.show_dialog(edit_dialog)
    page.update()
