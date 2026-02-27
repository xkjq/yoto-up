from yoto_up.yoto_api import YotoAPI
from yoto_up.yoto_app.edit_card_dialog import show_edit_card_dialog
from yoto_up.yoto_app.add_cover_dialog import add_cover_dialog
from yoto_up.models import Card
import threading
import json
import traceback
from copy import deepcopy
from pathlib import Path

import flet as ft
import re
from loguru import logger
from datetime import datetime, timezone


def make_show_card_details(
    page,
    IconReplaceDialog,
):
    """Factory that returns a callable with signature (card).

    The returned `show_card_details(card)` function was extracted from
    `yoto_app.playlists` to keep the playlists module smaller. The factory
    captures the dependencies that were previously closed-over in the
    nested function.
    """

    def show_card_details(card: Card, preview_path: Path | None = None, close_other_dialogs: bool = True):
        logger.debug(f"Showing details for card id {card.cardId} with title '{card.title}'")

        assert isinstance(card, Card), f"Expected card to be a Card model instance, got {type(card)}"

        if close_other_dialogs:
            # There must be a better way to do this, but for now we'll just pop dialogs until there are none left
            page.pop_dialog()
            page.pop_dialog()
            page.pop_dialog()

        api: YotoAPI = page.api_ref.get("api")

        def save_order_click(_ev=None):
            page.show_snack("Saving order...")
            page.update()

            async def bg_save():
                # Build a payload from the current Card model and the reordered chapters
                card_id = c.cardId
                if not card_id:
                    logger.error("save_order: no card id found")
                    return

                dlg_content = getattr(dialog, "content", None)
                ui_items = None
                try:
                    if dlg_content is not None and hasattr(dlg_content, "controls"):
                        for ctl in dlg_content.controls:
                            try:
                                children = getattr(ctl, "controls", None)
                                if not children or not isinstance(children, (list, tuple)):
                                    continue
                                matches = 0
                                for child in children:
                                    ch = getattr(child, "_chapter", None)
                                    if ch is None and hasattr(child, "content"):
                                        ch = getattr(child.content, "_chapter", None)
                                    if ch is not None:
                                        matches += 1
                                if matches >= max(1, len(children) // 2):
                                    ui_items = children
                                    break
                            except Exception:
                                logger.debug("Failed to process child controls for save order")
                except Exception:
                    logger.debug("Failed to extract chapter UI items for save order")

                if ui_items is None:
                    ui_items = list(chapter_items)

                ordered = []
                for it in chapter_items:
                    try:
                        ch = getattr(it, "_chapter", None)
                        if ch is None and hasattr(it, "content"):
                            ch = getattr(it.content, "_chapter", None)
                        if ch is not None:
                            ordered.append(deepcopy(ch))
                    except Exception:
                        continue

                if ordered:
                    # Start from current card model payload
                    try:
                        payload = c.model_dump(exclude_none=True)
                    except Exception:
                        payload = {}
                    payload.setdefault("content", {})
                    payload["content"]["chapters"] = ordered

                    card_model = Card.model_validate(payload)

                    if not getattr(card_model, "cardId", None):
                        card_model.cardId = card_id

                    try:
                        updated = api.create_or_update_content(card_model, return_card=True)
                        page.update_local_card_cache(updated)
                        page.pop_dialog()
                        page.pop_dialog()
                        show_card_details(updated)
                        page.update()
                    except Exception as ex:
                        logger.error(f"save_order: background save failed: {ex}")

            page.run_task(bg_save)
            logger.info("save_order: background save started")


        def refresh_icon_cache(ev=None):
            try:
                api.refresh_public_and_user_icons()
            except Exception as ex:
                logger.debug(f"Failed to refresh icon cache: {ex}")

        def fmt_sec(s):
            try:
                s = float(s)
                m = int(s // 60)
                sec = int(s % 60)
                return f"{m}:{sec:02d}"
            except Exception:
                return str(s) if s is not None else ""

        try:
            def _normalize(obj):
                try:
                    if obj is None:
                        return None
                    if hasattr(obj, "model_dump"):
                        return obj.model_dump(exclude_none=True)
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

            # We need to update c to work with the Card model directly
            c = card

            def replace_individual_icon(ev, kind="chapter", ch_i=None, tr_i=None):
                try:
                    card_id = c.cardId
                    if not card_id:
                        page.show_snack("Unable to determine card id", error=True)
                        return
                    dialog = IconReplaceDialog(
                        api=api,
                        card=c,
                        page=page,
                        kind=kind,
                        ch_i=ch_i,
                        tr_i=tr_i,
                    )
                    dialog.open()
                except Exception as ex:
                    page.show_snack(f"Failed to open replace icon dialog: {ex}", error=True)

            def clear_chapter_icon(ev, ch_i=None):
                try:
                    card_id = c.cardId
                    if not card_id:
                        page.show_snack("Unable to determine card id", error=True)
                        return

                    def worker():
                        try:
                            full = api.get_card(card_id)
                            ch = full.content.chapters[ch_i]
                            if ch.get_icon_field() is None:
                                page.show_snack('Chapter has no icon to clear', error=True)
                                return
                            ch.set_icon_field(None)

                            page.update_card(full)
                            page.show_snack('Chapter icon cleared')
                            show_card_details(full)
                        except Exception as ee:
                            page.show_snack(f'Failed to clear chapter icon: {ee}', error=True)

                    threading.Thread(target=worker, daemon=True).start()
                except Exception:
                    page.show_snack('Failed to start clear chapter icon operation', error=True)

            def clear_track_icon(ev, ch_i=None, tr_i=None):
                try:
                    card_id = c.cardId
                    if not card_id:
                        page.show_snack("Unable to determine card id", error=True)
                        return

                    def worker():
                        try:
                            full = api.get_card(card_id)
                            tr = full.content.chapters[ch_i].tracks[tr_i]
                            if tr.get_icon_field() is None:
                                page.show_snack('Track has no icon to clear', error=True)
                                return
                            tr.set_icon_field(None)
                            page.update_card(full)
                            show_card_details(full)
                        except Exception as ee:
                            page.show_snack(f'Failed to clear track icon: {ee}', error=True)

                    threading.Thread(target=worker, daemon=True).start()
                except Exception:
                    page.show_snack('Failed to start clear track icon operation', error=True)

            def make_track_items(ch, ch_index, for_reorder=False):
                items = []
                tracks = getattr(ch, "tracks", None)
                if not tracks:
                    return items
                for t_idx, tr in enumerate(tracks, start=1):
                    # Expect `tr` to be a Track model
                    tr_title = getattr(tr, "title", "")
                    tr_format = getattr(tr, "format", "")
                    tr_duration = fmt_sec(getattr(tr, "duration", None))
                    tr_size = getattr(tr, "fileSize", "")
                    tr_url = getattr(tr, "trackUrl", "")
                    tr_key = getattr(tr, "key", "")
                    tr_overlay = getattr(tr, "overlayLabel", "")
                    tr_icon_field = tr.get_icon_field()
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

                    def _on_download_click(ev=None, url=tr_url, title=tr_title):
                        import httpx
                        from pathlib import Path
                        try:
                            resolved_url = None
                            if url and url.startswith("http"):
                                resolved_url = url
                            if not resolved_url or not resolved_url.startswith("http"):
                                page.show_snack("No valid URL for this track", error=True)
                                return
                            downloads_dir = Path("downloads")
                            downloads_dir.mkdir(exist_ok=True)
                            # Use title or fallback to last part of URL
                            filename = title or resolved_url.split("/")[-1]
                            # Ensure safe filename
                            filename = "_".join(filename.split())
                            if not filename.lower().endswith(f".{tr_format}"):
                                filename += f".{tr_format}"
                            dest = downloads_dir / filename
                            with httpx.stream("GET", resolved_url, timeout=60.0) as r:
                                r.raise_for_status()
                                with open(dest, "wb") as f:
                                    for chunk in r.iter_bytes():
                                        f.write(chunk)
                            page.show_snack(f"Downloaded to {dest}")
                        except Exception as ex:
                            page.show_snack(f"Download failed: {ex}", error=True)
                    tr_img = None
                    try:
                        if api and tr_icon_field:
                            #tp = api.get_icon_cache_path(tr_icon_field)
                            based_image = api.get_icon_b64_data(tr_icon_field)
                            if based_image is not None:
                                img = ft.Image(src=based_image, width=20, height=20, tooltip="Click to replace icon")
                                tr_img = ft.GestureDetector(
                                    content=img,
                                    on_tap=lambda ev,
                                    ch_index=ch_index,
                                    tr_index=t_idx - 1: _on_tap_tr(
                                        ev, ch_index, tr_index
                                    ),
                                    width=20, height=20
                                )
                            else:
                                pass
                        else:
                            pass
                    except Exception as ex:
                        logger.exception(f"Error fetching track icon: {ex}")
                    
                    if tr_img is None:
                        tr_img = ft.IconButton(
                            icon=ft.Icons.IMAGE,
                            tooltip="Fetch icon",
                            on_click=lambda ev,
                            f=tr_icon_field,
                            ci=ch_index,
                            ti=t_idx - 1: threading.Thread(
                                target=lambda: _on_tap_tr(ev, ci, ti),
                                daemon=True,
                            ).start(),
                        )

                    tr_col = ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    tr_img if tr_img else ft.Container(width=20, tooltip="Click to replace icon"),
                                    ft.Text(value=f"Track {t_idx}. {tr_title}", size=12),
                                ],
                                alignment=ft.MainAxisAlignment.START,
                                spacing=8,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Container(width=20),
                                    ft.Text(
                                        value=
                                        f"{tr_format}  • {tr_duration}  • size={tr_size}",
                                        size=11,
                                        color=ft.Colors.BLACK45,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.START,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Container(width=20),
                                    ft.Text(
                                        value=
                                        f"key={tr_key}  overlay={tr_overlay}",
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
                        controls=[
                            ft.Container(width=20),
                            tr_col,
                            ft.IconButton(
                                icon=ft.Icons.IMAGE,
                                tooltip="Use chapter icon for this track",
                                opacity=0.1,
                                icon_size=16,
                                on_click=lambda ev,
                                ch_i=ch_index,
                                tr_i=t_idx - 1: use_chapter_icon(ev, ch_i, tr_i),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                tooltip="Clear track icon",
                                opacity=0.1,
                                icon_size=16,
                                on_click=lambda ev,
                                ch_i=ch_index,
                                tr_i=t_idx - 1: clear_track_icon(ev, ch_i, tr_i),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DOWNLOAD,
                                tooltip="Download this track" if tr_url.startswith("http") else "Unable to download this track (yoto:# ids cannot be downloaded)",
                                icon_size=18,
                                on_click=lambda ev, url=tr_url, title=tr_title: _on_download_click(ev, url, title),
                                disabled=not tr_url or not tr_url.startswith("http"),
                            ),
                        ]
                    )
                    if tr_url:
                        row.controls.append(
                            ft.Row(
                                controls=[
                                    ft.Container(width=20),
                                    ft.Text(
                                        value=f"URL: {tr_url}", selectable=True, size=11
                                    ),
                                ]
                            )
                        )

                    items.append(row)
                return items

            chapters = c.get_chapters()
            if not chapters:
                try:
                    card_id = c.cardId
                    if api and card_id:
                        full_card = api.get_card(card_id)
                        # Expect api.get_card to return a Card model
                        if isinstance(full_card, Card):
                            c = full_card
                except Exception as ex:
                    print(f"Failed to fetch full card details: {ex}")

            controls = []
            # capture cover source found in metadata and defer building the Image
            cover_src = None
            controls.append(ft.Text(value=f"Title: {c.title}", selectable=True))
            controls.append(ft.Text(value=f"Card ID: {c.cardId}", selectable=True))
            controls.append(
                ft.Text(
                    value=
                    f"Created by Client ID: {c.createdByClientId}",
                    selectable=True,
                )
            )
            controls.append(
                ft.Text(value=f"Created At: {c.createdAt}", selectable=True)
            )
            controls.append(
                ft.Text(
                    value=
                    f"Deleted: {c.deleted}",
                    selectable=True,
                )
            )

            meta = c.metadata
            if meta:
                cover_src = c.get_cover_url()
                controls.append(ft.Divider())
                controls.append(ft.Text(value="Metadata:", weight=ft.FontWeight.BOLD))
                controls.append(
                    ft.Text(value=f"  Author: {meta.author}", selectable=True)
                )
                controls.append(
                    ft.Text(value=f"  Category: {meta.category}", selectable=True)
                )
                controls.append(
                    ft.Text(value=f"  Description: {meta.description}", selectable=True)
                )
                controls.append(
                    ft.Text(value=f"  Note: {meta.note}", selectable=True)
                )
                tags = meta.tags
                if tags:
                    if isinstance(tags, (list, tuple)):
                        controls.append(
                            ft.Text(value=f"  Tags: {', '.join(tags)}", selectable=True)
                        )
                    else:
                        controls.append(ft.Text(value=f"  Tags: {tags}", selectable=True))
                genres = meta.genre
                if genres:
                    if isinstance(genres, (list, tuple)):
                        controls.append(
                            ft.Text(value=f"  Genres: {', '.join(genres)}", selectable=True)
                        )
                    else:
                        controls.append(ft.Text(value=f"  Genres: {genres}", selectable=True))
                media = meta.media
                if media:
                    controls.append(
                        ft.Text(
                            value=
                            f"  Duration: {fmt_sec(media.duration)}    FileSize: {media.fileSize}",
                            selectable=True,
                        )
                    )
                if meta.previewAudio:
                    controls.append(
                        ft.Text(
                            value=
                            f"  Preview Audio: {meta.previewAudio}",
                            selectable=True,
                        )
                    )

            content = c.content
            chapters = content.chapters if content and content.chapters else []
            # capture header controls (everything up to the chapters section)
            header_controls = list(controls)
            chapters_view = None
            if chapters:
                controls.append(ft.Divider())
                controls.append(ft.Text(value="Chapters:", weight=ft.FontWeight.BOLD))


                chapter_items = []
                for ch_idx, ch in enumerate(chapters):
                    # Expect `ch` to be a Chapter model
                    ch_title = ch.get_title()
                    overlay = getattr(ch, "overlayLabel", "")
                    key = getattr(ch, "key", "")

                    icon_field = ch.get_icon_field()

                    img_control = None

                    def _on_tap_ch(ev, ch_index=ch_idx):
                        replace_individual_icon(ev, "chapter", ch_index)

                    try:
                        if api and icon_field:
                            icon_base64 = api.get_icon_b64_data(icon_field)
                            if icon_base64 is not None:
                                img = ft.Image(src=icon_base64, width=24, height=24)
                                img_control = ft.GestureDetector(content=img, on_tap=_on_tap_ch)
                            else:
                                img_control = ft.IconButton(icon=ft.Icons.ERROR, tooltip="Click to refresh icon cache", on_click=refresh_icon_cache)
                                logger.debug(f"No cached icon path for chapter icon field {icon_field}")
                        else:
                            img_control = ft.IconButton(icon=ft.Icons.IMAGE, tooltip="Fetch icon", on_click=_on_tap_ch)
                    except Exception:
                        img_control = ft.IconButton(icon=ft.Icons.IMAGE, tooltip="Fetch icon", on_click=_on_tap_ch)

                    meta_line = f"key={key}"
                    if overlay:
                        meta_line += f"  overlay={overlay}"
                    if getattr(ch, "duration", None) or getattr(ch, "fileSize", None):
                        meta_line += f"  • Duration: {fmt_sec(getattr(ch, 'duration', None))}  FileSize: {getattr(ch, 'fileSize', '')}"

                    track_controls = make_track_items(ch, ch_idx, for_reorder=True)

                    def make_track_on_reorder(ch_index):
                        def _on_reorder(ev):
                            try:
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
                                tr_list = c.get_track_list()
                                item = tr_list.pop(old)
                                tr_list.insert(new, item)
                                try:
                                    page.show_dialog(dialog)
                                    page.update()
                                except Exception:
                                    page.update()
                            except Exception as ex:
                                print("track reorder failed:", ex)

                        return _on_reorder

                    chapter_panel_children = [
                        ft.Row(
                            controls=[
                                img_control if img_control else ft.Container(width=24),
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            value=
                                            f"Chapter {ch_idx + 1}. {ch_title}",
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            value=meta_line, size=12, color=ft.Colors.BLACK45
                                        ),
                                    ]
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    opacity=0.2,
                                    hover_color=ft.Colors.RED_ACCENT_100,
                                    tooltip="Clear chapter icon",
                                    on_click=lambda ev, ci=ch_idx: clear_chapter_icon(ev, ci),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            spacing=12,
                        )
                    ]

                    tracks_rv = ft.ReorderableListView(controls=track_controls, on_reorder=make_track_on_reorder(ch_idx))
                    chapter_panel_children.append(tracks_rv)

                    col = ft.Column(controls=chapter_panel_children, spacing=6)
                    chapter_items.append(col)

                def make_chapter_on_reorder(ev):
                    try:
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
                        ch_list = c.get_chapters()
                        item = ch_list.pop(old)
                        ch_list.insert(new, item)
                        ui_item = chapter_items.pop(old)
                        chapter_items.insert(new, ui_item)
                        page.show_dialog(dialog)
                        page.update()
                    except Exception as ex:
                        print("chapter reorder failed:", ex)

                chapters_rv = ft.ReorderableListView(controls=chapter_items, on_reorder=make_chapter_on_reorder)
                controls.append(chapters_rv)

                # Buttons at the bottom of the dialog content
                controls.append(ft.Row(controls=[ft.TextButton(content="Save Order", on_click=save_order_click)]))
                
                # Buttons to remove icons from all chapters/tracks
                def _clear_all_track_icons(ev=None):
                    logger.error("Clearing all track icons for card id {c.cardId}")
                    # clear track icons using model helper on Track
                    for ch in card.get_chapters():
                        ch.clear_all_track_icons()
                    new_card = page.update_card(card)
                    logger.debug(new_card)
                    logger.error("All track icons cleared, refreshing details view")
                    show_card_details(new_card)
                    page.show_snack("Cleared all track icons")

                def _clear_all_chapter_icons(ev=None):
                    # clear chapter icons using model helper on Chapter
                    for ch in card.get_chapters():
                        ch.clear_icon_field()
                    new_card = page.update_card(card)
                    show_card_details(new_card)
                    page.show_snack("Cleared all chapter icons")

                def _clear_all_icons(ev=None):
                    # Use Card helper to clear all icons
                    card.clear_all_icons()
                    new_card = page.update_card(card)
                    show_card_details(new_card)
                    page.show_snack("Cleared all icons (chapters + tracks)")

                controls.append(
                    ft.Row(
                        controls=[
                            ft.TextButton(content="Clear all track icons", on_click=_clear_all_track_icons),
                            ft.TextButton(content="Clear all chapter icons", on_click=_clear_all_chapter_icons),
                            ft.TextButton(content="Clear all icons", on_click=_clear_all_icons),
                        ],
                        spacing=8,
                    )
                )


                # Build a chapters_view from the controls appended after the header
                try:
                    chapters_portion = controls[len(header_controls):]
                    chapters_view = ft.Column(controls=chapters_portion, spacing=6)
                except Exception:
                    chapters_view = None

                def use_chapter_icon(ev, ch_i, tr_i):
                    try:
                        card_id = c.cardId
                        if not card_id:
                            page.show_snack("Unable to determine card id", error=True)
                            return

                        def worker():
                            try:
                                full = api.get_card(card_id)
                                ch = full.content.chapters[ch_i]
                                chapter_icon = ch.get_icon_field()
                                if not chapter_icon:
                                    page.show_snack("Chapter has no icon to copy", error=True)
                                    return
                                tr = ch.tracks[tr_i]
                                tr.set_icon_field(chapter_icon)
                                page.update_card(full)
                                page.show_dialog(dialog)
                                page.update()
                                page.show_snack("Track icon updated to chapter icon")
                            except Exception as ee:
                                page.show_snack(f"Failed to copy chapter icon: {ee}", error=True)
                                page.update()
                            show_card_details(full)

                        threading.Thread(target=worker, daemon=True).start()
                    except Exception:
                        page.show_snack("Failed to start copy operation", error=True)

            else:
                controls.append(ft.Text(value="Chapters: None", selectable=True))

            if not controls:
                try:
                    controls = [ft.Text(value=json.dumps(c, indent=2), selectable=True)]
                except Exception:
                    controls = [ft.Text(value=str(c), selectable=True)]
        except Exception:
            print("Failed to render card details:", traceback.format_exc())
            controls = [ft.Text(value=str(c), selectable=True)]

        def close_dialog(ev):
            logger.debug("Closing card details dialog")
            page.pop_dialog()
            page.update()

        def show_json(ev):
            logger.debug("Preparing raw JSON view")
            raw = json.dumps(c.model_dump(), indent=2)

            def close_json(ev2):
                page.pop_dialog()
                page.update()

            # Render JSON line-by-line into monospace ft.Text controls with
            # simple per-token colouring (keys, strings, numbers, booleans/null).
            lines = raw.splitlines()
            json_lines = []
            key_value_re = re.compile(r'^(\s*)"(?P<key>(?:\\.|[^"])+)"\s*:\s*(?P<val>.*?)(,?)\s*$')
            number_re = re.compile(r'^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$')
            for line in lines:
                m = key_value_re.match(line)
                if m:
                    indent = m.group(1)
                    key = m.group('key')
                    val = m.group('val')
                    trailing_comma = ',' if line.rstrip().endswith(',') else ''
                    # Determine value type for colouring
                    v = val.strip()
                    if v.startswith('"') and v.endswith('"'):
                        val_color = ft.Colors.GREEN
                    elif v in ('true', 'false', 'null'):
                        val_color = ft.Colors.ORANGE
                    elif number_re.match(v):
                        val_color = ft.Colors.PURPLE
                    else:
                        val_color = ft.Colors.BLACK

                    # spacer for indentation (approx char width)
                    space_width = 8
                    spacer = ft.Container(width=len(indent) * space_width)
                    key_text = ft.Text(value=f'"{key}"', style=ft.TextStyle(color=ft.Colors.BLUE, font_family='monospace'))
                    colon_text = ft.Text(value=': ', style=ft.TextStyle(font_family='monospace'))
                    val_text = ft.Text(value=f'{val}{trailing_comma}', style=ft.TextStyle(color=val_color, font_family='monospace'), selectable=True)
                    row = ft.Row(controls=[spacer, key_text, colon_text, val_text], spacing=0, vertical_alignment=ft.CrossAxisAlignment.START)
                    json_lines.append(row)
                else:
                    # Braces, brackets, or other lines — preserve leading indentation
                    stripped = line.strip()
                    # compute leading space count
                    leading = len(line) - len(line.lstrip(' '))
                    space_width = 8
                    spacer = ft.Container(width=leading * space_width)
                    if stripped in ('{', '}', '[', ']', '},', '],'):
                        text = ft.Text(value=stripped, style=ft.TextStyle(color=ft.Colors.BLACK, font_family='monospace'), selectable=True)
                        row = ft.Row(controls=[spacer, text], spacing=0, vertical_alignment=ft.CrossAxisAlignment.START)
                        json_lines.append(row)
                    else:
                        # keep the original line but apply monospace
                        text = ft.Text(value=line, style=ft.TextStyle(font_family='monospace'), selectable=True)
                        row = ft.Row(controls=[spacer, text], spacing=0, vertical_alignment=ft.CrossAxisAlignment.START)
                        json_lines.append(row)

            json_content = ft.ListView(controls=json_lines, padding=10, height=500, width=800)

            def do_copy(_e=None):
                try:
                    # copy raw JSON to clipboard
                    ft.Clipboard().set(raw)
                    page.show_snack("JSON copied to clipboard")
                except Exception as ex:
                    page.show_snack(f"Clipboard error: {ex}", error=True)

            json_dialog = ft.AlertDialog(
                title=ft.Text(value="Raw card JSON"),
                content=json_content,
                actions=[
                    ft.TextButton(content="Copy JSON", on_click=do_copy),
                    ft.TextButton(content="Close", on_click=close_json),
                ],
            )
            page.show_dialog(json_dialog)

        def show_versions(ev=None):
            try:
                card_id = c.cardId
                if not card_id:
                    page.show_snack("Unable to determine card id", error=True)
                    return
                files = api.list_versions(card_id)
                if not files:
                    page.show_snack("No saved versions found for this card")
                    return

                rows = []
                for p in files:
                    try:
                        # Build a human-readable label: timestamp, title, card id, size
                        label = p.name
                        try:
                            readable_parts = []
                            # Try parse timestamp from filename stem (YYYYmmddTHHMMSSZ)
                            ts = None
                            try:
                                ts = datetime.strptime(p.stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                            except Exception:
                                try:
                                    ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                                except Exception:
                                    ts = None
                            if ts:
                                readable_parts.append(ts.strftime("%Y-%m-%d %H:%M:%S UTC"))

                            # Try to read minimal payload metadata (title, card id)
                            title = None
                            cardid = None
                            try:
                                card_model = api.load_version(p, as_model=True)
                                title = card_model.get_title()
                                cardid = card_model.cardId
                            except Exception:
                                title = None
                                cardid = None
                            if title:
                                readable_parts.append(f"'{title}'")
                            if cardid:
                                readable_parts.append(f"({cardid})")

                            # File size human readable
                            try:
                                size = p.stat().st_size
                                def _hr(n: int) -> str:
                                    value = float(n)
                                    for u in ['B', 'KB', 'MB', 'GB']:
                                        if value < 1024:
                                            return f"{value:.0f}{u}" if u == 'B' else f"{value/1024:.1f}{u}"
                                        value = value / 1024
                                    return f"{value:.1f}TB"
                                readable_parts.append(_hr(size))
                            except Exception:
                                logger.error(f"Failed to get file size for version file {p}")

                            if readable_parts:
                                label = " — ".join(readable_parts)
                        except Exception:
                            logger.error(f"Failed to build label for version file {p}")
                            label = p.name
                        def make_preview(pp=p):
                            def _preview(ev2=None):
                                try:
                                    card = api.load_version(pp, as_model=True)
                                    # show the full card details for the saved version
                                    show_card_details(card, preview_path=pp)
                                except Exception as ex:
                                    logger.error(f"Failed to load version for preview: {ex}")
                                    page.show_snack(f"Failed to load version: {ex}", error=True)
                            return _preview

                        def make_restore(pp=p):
                            def _restore(ev2=None):
                                try:
                                    # ask for confirmation
                                    def do_confirm_yes(_e=None):
                                        page.pop_dialog()
                                        page.update()
                                        async def worker():
                                            try:
                                                updated = api.restore_version(pp, return_card=True)
                                                page.show_snack("Version restored")
                                                show_card_details(updated)
                                                page.update()
                                            except Exception as ex:
                                                page.show_snack(f"Failed to restore version: {ex}", error=True)
                                        page.run_task(worker)

                                    confirm_dialog = ft.AlertDialog(
                                        title=ft.Text(value="Restore version"),
                                        content=ft.Text(value=f"Restore version {pp.name}? This will post the saved card to the server and cannot be undone."),
                                        actions=[
                                            ft.TextButton(content="Yes", on_click=do_confirm_yes),
                                            ft.TextButton(content="No", on_click=lambda e: (setattr(confirm_dialog, 'open', False), page.update())),
                                        ],
                                    )
                                    page.show_dialog(confirm_dialog)
                                    page.update()
                                except Exception:
                                    page.show_snack("Failed to show restore confirmation", error=True)
                            return _restore

                        def make_delete(pp=p):
                            def _delete(ev2=None):
                                try:
                                    # ask for confirmation
                                    def do_yes(_e=None):
                                        try:
                                            confirm_del.open = False
                                        except Exception:
                                            pass
                                        page.update()
                                        async def worker_del():
                                            try:
                                                pp.unlink()
                                                page.show_snack(f"Deleted version {pp.name}")
                                                page.pop_dialog()
                                                page.update()
                                                show_versions(None)
                                            except Exception as ex:
                                                page.show_snack(f"Failed to delete version: {ex}", error=True)
                                                logger.debug(f"delete version error: {ex}")
                                        page.run_task(worker_del)

                                    confirm_del = ft.AlertDialog(
                                        title=ft.Text(value="Delete version"),
                                        content=ft.Text(value=f"Delete version {pp.name}? This cannot be undone."),
                                        actions=[
                                            ft.TextButton(content="Yes", on_click=do_yes),
                                            ft.TextButton(content="No", on_click=lambda e: (setattr(confirm_del, 'open', False), page.update())),
                                        ],
                                    )
                                    page.show_dialog(confirm_del)
                                    page.update()
                                except Exception:
                                    page.show_snack("Failed to show delete confirmation", error=True)
                            return _delete

                        rows.append(
                            ft.Row(
                                controls=[
                                    ft.Text(value=label, selectable=True),
                                    ft.TextButton(content="Preview", on_click=make_preview(p)),
                                    ft.TextButton(content="Restore", on_click=make_restore(p)),
                                    ft.TextButton(content="Delete", on_click=make_delete(p)),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            )
                        )
                    except Exception:
                        continue

                versions_list = ft.ListView(controls=rows, spacing=6, padding=6, height=350, width=700)

                def make_delete_all(dir_path=(files[0].parent if files else None)):
                    def _delete_all(ev=None):
                        try:
                            if dir_path is None:
                                page.show_snack("No versions directory found", error=True)
                                return

                            def do_yes(_e=None):
                                try:
                                    confirm_all.open = False
                                except Exception:
                                    pass
                                page.update()

                                def worker_all():
                                    try:
                                        for fpath in list(dir_path.iterdir()):
                                            try:
                                                if fpath.is_file():
                                                    fpath.unlink()
                                            except Exception as ex:
                                                logger.debug(f"Failed to delete version file {fpath}: {ex}")
                                        dir_path.rmdir()
                                        page.show_snack("All versions deleted")
                                        page.pop_dialog()
                                        page.update()
                                        show_versions(None)
                                    except Exception as ex:
                                        page.show_snack(f"Failed to delete all versions: {ex}", error=True)

                                threading.Thread(target=worker_all, daemon=True).start()

                            confirm_all = ft.AlertDialog(
                                title=ft.Text(value="Delete all versions"),
                                content=ft.Text(value="Delete ALL saved versions for this card? This cannot be undone."),
                                actions=[
                                    ft.TextButton(content="Yes", on_click=do_yes),
                                    ft.TextButton(content="No", on_click=lambda e: (setattr(confirm_all, 'open', False), page.update())),
                                ],
                            )
                            page.show_dialog(confirm_all)
                            page.update()
                        except Exception:
                            page.show_snack("Failed to show delete-all confirmation", error=True)

                    return _delete_all

                versions_dialog = ft.AlertDialog(
                    title=ft.Text(value="Saved Versions"),
                    content=versions_list,
                    actions=[
                        ft.TextButton(content="Delete all", on_click=make_delete_all()),
                        ft.TextButton(content="Close", on_click=lambda e: (setattr(versions_dialog, 'open', False), page.update())),
                    ],
                )
                try:
                    page.show_dialog(versions_dialog)
                    page.update()
                except Exception:
                    try:
                        page.dialog = versions_dialog
                        page.update()
                    except Exception:
                        pass
            except Exception as ex:
                page.show_snack(f"Failed to list versions: {ex}", error=True)

        def show_add_cover(ev):
            """Show the add cover dialog."""
            add_cover_dialog(
                page,
                c,
            )

        def relabel_keys(ev=None):
            try:
                card_id = c.cardId
                if not card_id:
                    page.show_snack("Unable to determine card id", error=True)
                    return

                def worker():
                    try:
                        full = api.get_card(card_id)
                        # rewrite 'key' sequentially across tracks
                        updated = api.rewrite_track_fields(full, field="key", sequential=True)
                        page.update_card(updated)
                        page.show_snack("Track keys relabelled")
                        try:
                            show_card_details(updated)
                        except Exception:
                            pass
                    except Exception as ex:
                        page.show_snack(f"Failed to relabel keys: {ex}", error=True)

                threading.Thread(target=worker, daemon=True).start()
            except Exception:
                page.show_snack("Failed to start relabel keys operation", error=True)

        def relabel_overlays(ev=None):
            try:
                card_id = c.cardId
                if not card_id:
                    page.show_snack("Unable to determine card id", error=True)
                    return

                def worker():
                    try:
                        full = api.get_card(card_id)
                        # rewrite 'overlayLabel' sequentially
                        updated = api.rewrite_track_fields(full, field="overlayLabel", sequential=True)
                        updated = api.rewrite_chapter_fields(updated, field="overlayLabel", sequential=True)
                        page.update_card(updated)
                        page.show_snack("Overlay labels relabelled")
                        try:
                            show_card_details(updated)
                        except Exception:
                            pass
                    except Exception as ex:
                        page.show_snack(f"Failed to relabel overlays: {ex}", error=True)

                threading.Thread(target=worker, daemon=True).start()
            except Exception:
                page.show_snack("Failed to start relabel overlays operation", error=True)

        def merge_chapters(ev=None):
            try:
                def do_merge(_e=None):
                    page.pop_dialog()
                    try:
                        card_id = c.cardId
                        if not card_id:
                            page.show_snack("Unable to determine card id", error=True)
                            return
                        full = api.get_card(card_id)
                        updated = api.merge_chapters(full, reset_overlay_labels=True, reset_track_keys=True)
                        page.update_card(updated)
                        page.show_snack("Chapters merged")
                        try:
                            show_card_details(updated)
                        except Exception:
                            logger.debug("merge_chapters: failed to refresh details view after merge")
                    except Exception as ex:
                        page.show_snack(f"Failed to merge chapters: {ex}", error=True)

                confirm_dialog = ft.AlertDialog(
                    title=ft.Text(value="Merge chapters"),
                    content=ft.Text(value="""Merge all chapters into one chapter? 

This will concatenate all tracks into a single chapter and
relabel all overlayLabels and keys sequentially.                                    

For example, if you have 3 chapters with 2 tracks each, such as:
    Chapter 1: Track 1, Track 2
    Chapter 2: Track 3, Track 4
    Chapter 3: Track 5, Track 6
                                    
Merging will result in:
    Chapter 1: Track 1, Track 2, Track 3, Track 4, Track 5, Track 6
"""),
                    actions=[
                        ft.TextButton(content="Yes", on_click=lambda e: threading.Thread(target=do_merge, daemon=True).start()),
                        ft.TextButton(content="No", on_click=lambda e: (setattr(confirm_dialog, 'open', False), page.update())),
                    ],
                )
                page.show_dialog(confirm_dialog)
            except Exception:
                page.show_snack("Failed to start merge chapters operation", error=True)

        def expand_all_tracks(ev=None):
            try:
                def do_expand(_e=None):
                    page.pop_dialog()
                    page.update()

                    def worker():
                        try:
                            card_id = c.cardId
                            if not card_id:
                                page.show_snack("Unable to determine card id", error=True)
                                return
                            full = api.get_card(card_id)
                            updated = api.expand_all_tracks_into_chapters(full, reset_overlay_labels=True, reset_track_keys=True)
                            page.update_card(updated)
                            try:
                                page.show_snack("Expanded all tracks into individual chapters")
                            except Exception:
                                pass
                            try:
                                show_card_details(updated)
                            except Exception:
                                pass
                            page.update()
                        except Exception as ex:
                            try:
                                page.show_snack(f"Failed to expand tracks: {ex}", error=True)
                            except Exception:
                                pass

                    threading.Thread(target=worker, daemon=True).start()

                confirm_expand = ft.AlertDialog(
                    title=ft.Text(value="Expand all tracks"),
                    content=ft.Text(value="Expand every track into its own chapter? This will create one chapter per track and relabel overlays/keys."),
                    actions=[
                        ft.TextButton(content="Yes", on_click=do_expand),
                        ft.TextButton(content="No", on_click=lambda e: (setattr(confirm_expand, 'open', False), page.update())),
                    ],
                )
                page.show_dialog(confirm_expand)
                page.update()
            except Exception:
                page.show_snack("Failed to start expand operation", error=True)

        def replace_icons(ev):
            # Start background replace with persistent badge
            from yoto_up.yoto_app.replace_icons import start_replace_icons_background
            start_replace_icons_background(
                page,
                c,
            )

        # popup dialog for track-related actions (shows title + cover image)
        tracks_dialog = None

        def show_tracks_popup(_ev=None):
            nonlocal tracks_dialog
            try:
                title_text = c.get_title()
                cover_img = c.get_cover_url()

                body = []
                if cover_img is not None:
                    body.append(
                        ft.Row(
                            controls=[
                                ft.Image(src=cover_img, width=72, height=72, fit=ft.BoxFit.CONTAIN),
                                ft.Column(controls=[ft.Text(value=title_text, weight=ft.FontWeight.BOLD)]),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            spacing=12,
                        )
                    )
                else:
                    body.append(ft.Text(value=title_text, weight=ft.FontWeight.BOLD))

                body.append(ft.Divider())

                # Add description about the buttons
                body.append(
                    ft.Text(
                        value=
                        """Below you can renumber all overlayLabels or keys for tracks in this card.
Renumbering overlayLabels will assign sequential overlay labels to tracks.
Renumbering keys will assign sequential keys to all tracks.
                        """,
                        size=12,
                        color=ft.Colors.BLACK54,
                        italic=True,
                    )
                )

                # build chapters + tracks view (showing track title, key and overlayLabel)
                try:
                    chapters = getattr(getattr(c, 'content', None), 'chapters', []) or []
                    chapter_rows = []
                    for ch_idx, ch in enumerate(chapters):
                        ch_title = getattr(ch, 'title', '')
                        header = ft.Text(value=f"Chapter {ch_idx + 1}. {ch_title}", weight=ft.FontWeight.BOLD)
                        track_items = []
                        tracks = getattr(ch, 'tracks', None) or []
                        if tracks:
                            for t_idx, t in enumerate(tracks, 1):
                                t_title = getattr(t, 'title', '')
                                t_key = getattr(t, 'key', '')
                                t_overlay = getattr(t, 'overlayLabel', '')
                                track_items.append(ft.Text(value=f"Track {t_idx}: {t_title}    key={t_key}    overlay={t_overlay}", size=12))
                        else:
                            track_items.append(ft.Text(value="(no tracks)", size=12))

                        chapter_rows.append(ft.Column(controls=[header, ft.Column(controls=track_items, spacing=4)], spacing=6))

                    if chapter_rows:
                        chapters_view = ft.ListView(controls=chapter_rows, spacing=6, padding=6, height=300)
                        body.append(chapters_view)
                    else:
                        body.append(ft.Text(value="No chapters available", size=12))
                except Exception:
                    body.append(ft.Text(value="Unable to render chapters", size=12))

                body.append(ft.Divider())

                tracks_dialog = ft.AlertDialog(
                    title=ft.Text(value="Track actions"),
                    content=ft.Column(controls=body, spacing=8),
                    actions=[
                        ft.TextButton(
                            content="Renumber overlayLabels",
                            on_click=lambda ev: (
                                relabel_overlays(ev),
                            ),
                        ),
                        ft.TextButton(
                            content="Renumber keys",
                            on_click=lambda ev: (
                                relabel_keys(ev),
                            ),
                        ),
                        ft.TextButton(content="Merge chapters", on_click=lambda ev: merge_chapters(ev)),
                        ft.TextButton(content="Expand tracks → chapters", on_click=lambda ev: expand_all_tracks(ev)),
                        ft.TextButton(content="Close", on_click=lambda e: (setattr(tracks_dialog, 'open', False), page.update()))
                    ],
                )
                page.show_dialog(tracks_dialog)
                page.update()
            except Exception:
                logger.exception("Failed to show tracks popup")

        try:
            win_h = getattr(page, "window_height", None) or getattr(page, "height", None)
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

        # Build dialog content. If we found a cover, place it in a right-hand column
        if cover_src:
            # thumbnail sizing: keep it reasonably sized relative to dialog
            thumb_w = min(320, max(120, int(dlg_w * 0.28)))
            thumb_h = max(64, min(320, dlg_h - 120))

            try:
                # clicking the cover should open the Add Cover dialog
                img_w = ft.Image(src=cover_src, width=thumb_w, height=thumb_h)
                try:
                    cover_widget = ft.GestureDetector(content=img_w, on_tap=lambda ev: show_add_cover(ev))
                except Exception:
                    cover_widget = ft.GestureDetector(content=img_w, on_tap=show_add_cover)
            except Exception:
                # fallback: non-interactive image
                cover_widget = ft.Image(src=cover_src)

            # left pane should contain header/metadata controls (use Column so it sizes to content)
            left_col = ft.Column(controls=header_controls, spacing=6)
            right_col = ft.Container(content=ft.Column(controls=[cover_widget], tight=False), padding=6, width=thumb_w + 24)

            header_row = ft.Row(controls=[
                ft.Container(content=left_col, expand=True),
                ft.Container(width=12),
                right_col,
            ], alignment=ft.MainAxisAlignment.START)

            # Build a single scrolling ListView for the dialog content so header + chapters scroll together
            parts = [header_row]
            if chapters_view:
                parts.append(ft.Divider())
                parts.append(chapters_view)

            dialog_content = ft.ListView(controls=parts, spacing=8, padding=6, height=dlg_h, width=dlg_w)
        else:
            dialog_content = ft.ListView(controls=controls, spacing=6, padding=10, height=dlg_h, width=dlg_w)
        def export_card(_ev=None):
            try:
                def worker():
                    try:
                        Path("cards").mkdir(exist_ok=True)
                        try:
                            data = c.model_dump(exclude_none=True)
                        except Exception:
                            data = {}
                        title_part = getattr(c, 'title', '') or ''
                        id_part = getattr(c, 'cardId', 'card') or 'card'
                        safe_title = re.sub(r"[^0-9A-Za-z._-]", "-", str(title_part))[:80]
                        fname = Path('cards') / f"{safe_title}_{id_part}.json"
                        with fname.open('w', encoding='utf-8') as f:
                            f.write(json.dumps(data, indent=2, ensure_ascii=False))
                    except Exception as e:
                        try:
                            page.show_snack(f"Export failed: {e}", error=True)
                        except Exception:
                            pass
                threading.Thread(target=worker, daemon=True).start()
                page.show_snack("Export started...")
            except Exception:
                logger.exception("Failed to start export")
                page.show_snack("Failed to start export", error=True)

        # If preview_path is provided, we're showing a saved version preview and
        # expose a Restore button in the dialog actions.
        # Place the JSON and Versions buttons in the dialog title (top-right)
        dialog_actions = [
            ft.TextButton(content="Save Order", on_click=save_order_click),
            ft.TextButton(content="Tracks/Chapter Management", on_click=lambda ev: show_tracks_popup(ev)),
        ]

        # Title row with buttons on the top-right
        title_row = ft.Row(
            controls=[
                ft.Text(value="Playlist details"),
                ft.Row(
                    controls=[
                        ft.TextButton(content="JSON", on_click=show_json),
                        ft.TextButton(content="Versions", on_click=lambda ev: show_versions(ev)),
                    ],
                    spacing=6,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Add Edit/Add/Replace/Export/Close actions later; include restore if preview
        if preview_path is not None:
            def make_restore_from_preview(ppath=preview_path):
                def _restore(ev2=None):
                    try:
                        # close this dialog
                        page.pop_dialog()
                        page.update()

                        async def worker():
                            try:
                                updated = api.restore_version(ppath, return_card=True)
                                page.show_snack("Version restored")
                                show_card_details(updated)
                                page.update()
                            except Exception as ex:
                                page.show_snack(f"Failed to restore version: {ex}", error=True)

                        page.run_task(worker)
                    except Exception:
                        page.show_snack("Failed to start restore", error=True)

                return _restore

            dialog_actions.append(ft.TextButton(content="Restore this version", on_click=make_restore_from_preview()))

        dialog = ft.AlertDialog(
            title=title_row,
            content=dialog_content,
            actions=dialog_actions + [
                ft.TextButton(
                    content="Edit",
                    on_click=lambda ev: (
                        page.pop_dialog(),
                        page.update(),
                        show_edit_card_dialog(
                            c,
                            page,
                        ),
                    ),
                ),
                ft.TextButton(content="Cover", on_click=lambda ev: show_add_cover(ev)),
                ft.TextButton(content="Replace Default Icons", on_click=lambda ev: replace_icons(ev)),
                ft.TextButton(content="Export", on_click=export_card),
                ft.TextButton(content="Close", on_click=close_dialog),
            ],
        )
        page.show_dialog(dialog)
        page.update()

    return show_card_details
