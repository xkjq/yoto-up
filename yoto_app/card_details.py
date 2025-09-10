import threading
import asyncio
import json
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import flet as ft
from loguru import logger
from yoto_app.logging_helpers import safe_log


def make_show_card_details(
    page,
    api_ref: Dict[str, Any],
    show_snack,
    ensure_api,
    CLIENT_ID,
    Card,
    fetch_playlists_sync,
    playlists_list,
    make_playlist_row,
    status_ctrl,
    show_edit_card_dialog,
    IconReplaceDialog,
    show_replace_icons_dialog,
):
    """Factory that returns a callable with signature (ev, card).

    The returned `show_card_details(ev, card)` function was extracted from
    `yoto_app.playlists` to keep the playlists module smaller. The factory
    captures the dependencies that were previously closed-over in the
    nested function.
    """

    def show_card_details(e, card):
        def refresh_icon_cache(ev=None):
            api = api_ref.get("api")
            try:
                api.refresh_public_and_user_icons()
            except Exception:
                pass

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

            c = _normalize(card)
            if not isinstance(c, dict):
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

            def clear_chapter_icon(ev, ch_i=None):
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
                            if getattr(ch, 'display', None):
                                try:
                                    setattr(ch.display, 'icon16x16', None)
                                except Exception:
                                    try:
                                        delattr(ch.display, 'icon16x16')
                                    except Exception:
                                        pass
                            else:
                                show_snack('Chapter has no icon to clear', error=True)
                                return
                            api.update_card(full, return_card_model=False)
                            show_snack('Chapter icon cleared')
                            show_card_details(None, full)
                        except Exception as ee:
                            show_snack(f'Failed to clear chapter icon: {ee}', error=True)

                    threading.Thread(target=worker, daemon=True).start()
                except Exception:
                    show_snack('Failed to start clear chapter icon operation', error=True)

            def clear_track_icon(ev, ch_i=None, tr_i=None):
                try:
                    api = ensure_api(api_ref, CLIENT_ID)
                    card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                    if not card_id:
                        show_snack("Unable to determine card id", error=True)
                        return

                    def worker():
                        try:
                            full = api.get_card(card_id)
                            tr = full.content.chapters[ch_i].tracks[tr_i]
                            if getattr(tr, 'display', None):
                                try:
                                    setattr(tr.display, 'icon16x16', None)
                                except Exception:
                                    try:
                                        delattr(tr.display, 'icon16x16')
                                    except Exception:
                                        pass
                            else:
                                show_snack('Track has no icon to clear', error=True)
                                return
                            api.update_card(full, return_card_model=False)
                            show_snack('Track icon cleared')
                            show_card_details(None, full)
                        except Exception as ee:
                            show_snack(f'Failed to clear track icon: {ee}', error=True)

                    threading.Thread(target=worker, daemon=True).start()
                except Exception:
                    show_snack('Failed to start clear track icon operation', error=True)

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
                        tr_key = tr.get("key", "")
                        tr_overlay = tr.get("overlayLabel", "")
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
                                    target=lambda: _on_tap_tr(ev, ci, ti),
                                    daemon=True,
                                ).start(),
                            )

                        tr_col = ft.Column(
                            [
                                ft.Row(
                                    [
                                        tr_img if tr_img else ft.Container(width=20, tooltip="Click to replace icon"),
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
                                ft.Row(
                                    [
                                        ft.Container(width=20),
                                        ft.Text(
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
                            [
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
                    show_snack("Saving order...")
                    page.update()

                    def bg_save():
                        api = api_ref.get("api")
                        card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                        if not card_id:
                            safe_log("save_order: no card id found")
                            return

                        dlg_content = getattr(dialog, "content", None)
                        ui_items = None
                        reconstructed_titles = []
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
                                            if isinstance(ch, dict):
                                                matches += 1
                                        if matches >= max(1, len(children) // 2):
                                            ui_items = children
                                            break
                                    except Exception:
                                        continue
                        except Exception:
                            pass

                        if ui_items is None:
                            ui_items = list(chapter_items)

                        ordered = []
                        for i, it in enumerate(chapter_items):
                            try:
                                ch = getattr(it, "_chapter", None)
                                if ch is None and hasattr(it, "content"):
                                    ch = getattr(it.content, "_chapter", None)
                                if isinstance(ch, dict):
                                    ordered.append(deepcopy(ch))
                            except Exception:
                                continue

                        if ordered:
                            if "content" not in c or not isinstance(c.get("content"), dict):
                                c["content"] = {}
                            c["content"]["chapters"] = ordered

                        card_model = Card.model_validate(c)
                        try:
                            card_model = Card(**c)
                        except Exception as ex:
                            safe_log("save_order: failed to build Card model", ex)
                            show_snack(f"Failed to prepare card for save: {ex}", error=True)
                        try:
                            payload = card_model.model_dump(exclude_none=True)
                        except Exception:
                            payload = c

                        if not getattr(card_model, "cardId", None):
                            if getattr(card_model, "id", None):
                                card_model.cardId = getattr(card_model, "id")
                            else:
                                card_model.cardId = card_id

                        try:
                            payload = card_model.model_dump(exclude_none=True)
                        except Exception:
                            payload = {}
                        try:
                            if (c.get("content") or {}).get("chapters"):
                                payload.setdefault("content", {})
                                payload["content"]["chapters"] = deepcopy((c.get("content") or {}).get("chapters") or [])
                        except Exception:
                            pass

                        try:
                            updated = api.create_or_update_content(Card.model_validate(payload), return_card=True)
                            show_card_details(None, updated)
                            page.update()
                        except Exception as ex:
                            safe_log("save_order: background save failed", ex)

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
                        replace_individual_icon(ev, "chapter", ch_index)

                    try:
                        api = api_ref.get("api")
                        if api and icon_field:
                            p = api.get_icon_cache_path(icon_field)
                            if p and Path(p).exists():
                                img = ft.Image(src=str(p), width=24, height=24)
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
                    if isinstance(ch, dict) and (ch.get("duration") or ch.get("fileSize")):
                        meta_line += f"  • Duration: {fmt_sec(ch.get('duration'))}  FileSize: {ch.get('fileSize', '')}"

                    tracks = ch.get("tracks") if isinstance(ch, dict) else None
                    track_controls = (make_track_items(ch, ch_idx, for_reorder=True) if tracks else [])

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
                                tr_list = c.get("content", {}).get("chapters", [])[ch_index].get("tracks") or []
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

                    tracks_rv = ft.ReorderableListView(track_controls, on_reorder=make_track_on_reorder(ch_idx))
                    chapter_panel_children.append(tracks_rv)

                    col = ft.Column(chapter_panel_children, spacing=6)
                    try:
                        col._chapter = ch
                    except Exception:
                        pass
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
                        try:
                            ch_list = c.get("content", {}).get("chapters", [])
                            before = [ (ch.get("title") if isinstance(ch, dict) else str(ch)) for ch in list(ch_list) ]
                        except Exception:
                            before = []
                        try:
                            item = ch_list.pop(old)
                            ch_list.insert(new, item)
                        except Exception as err:
                            print("[playlists] on_reorder: mutation error", err)
                        try:
                            after = [ (ch.get("title") if isinstance(ch, dict) else str(ch)) for ch in (c.get("content") or {}).get("chapters") or [] ]
                        except Exception:
                            after = []
                        try:
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

                chapters_rv = ft.ReorderableListView(chapter_items, on_reorder=make_chapter_on_reorder)
                try:
                    chapters_rv._is_chapter_rv = True
                    chapters_rv._chapter_items_ref = chapter_items
                except Exception:
                    pass
                controls.append(chapters_rv)

                controls.append(ft.Row([ft.ElevatedButton("Save Order", on_click=save_order_click)]))

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
                                chapter_icon = (getattr(ch.display, "icon16x16", None) if getattr(ch, "display", None) else None)
                                if not chapter_icon:
                                    show_snack("Chapter has no icon to copy", error=True)
                                    return
                                tr = ch.tracks[tr_i]
                                if not getattr(tr, "display", None):
                                    tr.display = (type(tr.display)() if hasattr(tr, "display") else None)
                                tr.display.icon16x16 = chapter_icon
                                api.update_card(full, return_card_model=False)
                                page.open(dialog)
                                page.update()
                                show_snack("Track icon updated to chapter icon")
                            except Exception as ee:
                                show_snack(f"Failed to copy chapter icon: {ee}", error=True)
                                page.update()
                            show_card_details(None, full)

                        threading.Thread(target=worker, daemon=True).start()
                    except Exception:
                        show_snack("Failed to start copy operation", error=True)

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

            json_content = ft.ListView([ft.Text(raw, selectable=True)], padding=10, height=500, width=800)
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
                CLIENT_ID,
            )

        def relabel_keys(ev=None):
            try:
                api = ensure_api(api_ref, CLIENT_ID)
                card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                if not card_id:
                    show_snack("Unable to determine card id", error=True)
                    return

                def worker():
                    try:
                        full = api.get_card(card_id)
                        # rewrite 'key' sequentially across tracks
                        updated = api.rewrite_track_fields(full, field="key", sequential=True)
                        api.update_card(updated, return_card_model=False)
                        show_snack("Track keys relabelled")
                        try:
                            show_card_details(None, updated)
                        except Exception:
                            pass
                    except Exception as ex:
                        show_snack(f"Failed to relabel keys: {ex}", error=True)

                threading.Thread(target=worker, daemon=True).start()
            except Exception:
                show_snack("Failed to start relabel keys operation", error=True)

        def relabel_overlays(ev=None):
            try:
                api = ensure_api(api_ref, CLIENT_ID)
                card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                if not card_id:
                    show_snack("Unable to determine card id", error=True)
                    return

                def worker():
                    try:
                        full = api.get_card(card_id)
                        # rewrite 'overlayLabel' sequentially and reset every chapter
                        updated = api.rewrite_track_fields(full, field="overlayLabel", sequential=True, reset_every_chapter=True)
                        api.update_card(updated, return_card_model=False)
                        show_snack("Overlay labels relabelled")
                        try:
                            show_card_details(None, updated)
                        except Exception:
                            pass
                    except Exception as ex:
                        show_snack(f"Failed to relabel overlays: {ex}", error=True)

                threading.Thread(target=worker, daemon=True).start()
            except Exception:
                show_snack("Failed to start relabel overlays operation", error=True)

        def merge_chapters(ev=None):
            try:
                def do_merge(_e=None):
                    try:
                        confirm_dialog.open = False
                    except Exception:
                        pass
                    try:
                        api = ensure_api(api_ref, CLIENT_ID)
                        card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                        if not card_id:
                            show_snack("Unable to determine card id", error=True)
                            return
                        full = api.get_card(card_id)
                        updated = api.merge_chapters(full, reset_overlay_labels=True, reset_track_keys=True)
                        api.update_card(updated, return_card_model=False)
                        show_snack("Chapters merged")
                        try:
                            show_card_details(None, updated)
                        except Exception:
                            logger.debug("merge_chapters: failed to refresh details view after merge")
                    except Exception as ex:
                        show_snack(f"Failed to merge chapters: {ex}", error=True)

                confirm_dialog = ft.AlertDialog(
                    title=ft.Text("Merge chapters"),
                    content=ft.Text("Merge all chapters into one chapter? This cannot be undone."),
                    actions=[
                        ft.TextButton("Yes", on_click=lambda e: threading.Thread(target=do_merge, daemon=True).start()),
                        ft.TextButton("No", on_click=lambda e: (setattr(confirm_dialog, 'open', False), page.update())),
                    ],
                )
                page.open(confirm_dialog)
            except Exception:
                show_snack("Failed to start merge chapters operation", error=True)

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

        dialog_content = ft.ListView(controls, spacing=6, padding=10, height=dlg_h, width=dlg_w)
        dialog = ft.AlertDialog(
            title=ft.Text("Playlist details"),
            content=dialog_content,
            actions=[
                ft.ElevatedButton("Save Order", on_click=save_order_click),
                ft.TextButton("Raw JSON", on_click=show_json),
                ft.TextButton("Renumber keys", on_click=lambda ev: relabel_keys(ev)),
                ft.TextButton("Renumber overlays", on_click=lambda ev: relabel_overlays(ev)),
                ft.TextButton("Merge chapters", on_click=lambda ev: merge_chapters(ev)),
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
                        ),
                    ),
                ),
                ft.TextButton("Add Cover", on_click=lambda ev: show_add_cover(ev)),
                ft.TextButton("Replace Default Icons", on_click=lambda ev: replace_icons(ev)),
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

    return show_card_details
