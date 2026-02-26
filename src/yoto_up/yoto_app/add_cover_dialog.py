import os
import shutil
import sys
import tempfile

import flet as ft
import httpx
from loguru import logger

from yoto_up.models import Card
from yoto_up.yoto_api import YotoAPI
from yoto_up.yoto_app.api_manager import ensure_api


def add_cover_dialog(page, c: Card, on_close=None):
    api: YotoAPI = ensure_api(page.api_ref)

    def do_remove_cover(c: Card = c):
        try:
            card_model = c.clear_cover()
            page.update_card(card_model)
        except Exception as e:
            logger.error(f"Remove cover error: {e}")
            page.update()

    url_field = ft.TextField(label="Image URL (leave empty to upload file)")
    _is_linux_desktop = sys.platform.startswith("linux") and not getattr(page, "web", False)
    try:
        _zenity_missing = _is_linux_desktop and shutil.which("zenity") is None
    except Exception:
        _zenity_missing = False
    _file_picker_supported = not _zenity_missing

    picker = ft.FilePicker() if _file_picker_supported else None
    if picker is not None:
        try:
            page.services.append(picker)
        except Exception:
            pass
    file_label = ft.Text(value="No file chosen")

    def _warn_missing_file_picker():
        try:
            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    value="File dialogs are unavailable because 'zenity' is not installed. "
                    "On Ubuntu/Debian: sudo apt-get install zenity"
                ),
                bgcolor=ft.Colors.RED,
                duration=12000,
            )
            page.show_dialog(page.snack_bar)
            page.update()
        except Exception:
            pass

    cover_src = None
    try:
        current_cover = c.get_cover_url()
        if isinstance(current_cover, str) and current_cover:
            if current_cover.startswith("http") or current_cover.startswith("//"):
                cache_fn = getattr(page, "get_cached_cover", None)
                if callable(cache_fn):
                    p = cache_fn(current_cover)
                    cover_src = str(p) if p else current_cover
                else:
                    cover_src = current_cover
            elif current_cover.startswith("/"):
                cover_src = current_cover
    except Exception:
        cover_src = None

    def on_pick_result(e):
        try:
            if e.files:
                first = e.files[0]
                if hasattr(first, "path") and first.path:
                    file_label.value = str(first.path)
                else:
                    file_label.value = first.name or "(selected)"
            else:
                file_label.value = "No file chosen"
            page.update()
        except Exception:
            logger.error("Error in on_pick_result")

    async def _pick_cover_file(_e=None):
        if picker is None:
            _warn_missing_file_picker()
            return
        files = await picker.pick_files(allow_multiple=False)
        try:
            class _E:
                files = []

            ev = _E()
            ev.files = files
            on_pick_result(ev)
        except Exception:
            pass

    def do_upload(card: Card):
        img_path = file_label.value if file_label.value and file_label.value != "No file chosen" else None
        img_url = (url_field.value or "").strip() or None
        if not img_path and not img_url:
            page.update()
            return

        try:
            def progress_cb(_msg, _frac):
                try:
                    page.update()
                except Exception:
                    logger.error("Error in progress_cb")

            res = api.upload_cover_image(
                image_path=img_path,
                imageUrl=img_url,
                autoconvert=True,
                coverType=None,
                filename=None,
                progress_callback=progress_cb,
            )
            logger.debug(f"Uploaded cover response: {res}")
            try:
                card_model = card.apply_cover_upload_result(
                    upload_result=res,
                    fallback_url=img_url,
                )
                page.update_card(card_model)
            except Exception as ex:
                logger.error(f"Upload succeeded but attach failed, {ex}")
            finally:
                page.update()
        except Exception as e:
            logger.error(f"Top-level upload error: {e}")
            page.update()

        page.pop_dialog()
        page.update()

    def close_add(_e):
        page.pop_dialog()
        page.update()
        try:
            if callable(on_close):
                try:
                    on_close()
                except Exception:
                    try:
                        on_close(None)
                    except Exception:
                        logger.exception("on_close callback failed")
        except Exception:
            pass

    def do_search_cover(_e=None):
        try:
            default_query = c.title
            results_column = ft.Column(controls=[])

            def do_search_action(_e2=None):
                query = (search_field.value or "").strip()
                logger.info(f"Searching for cover art with query: {query}")
                results_column.controls.clear()
                try:
                    resp = httpx.get(
                        "https://itunes.apple.com/search",
                        params={"term": query, "media": "music", "entity": "album", "limit": 12},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    albums = data.get("results", [])
                    if not albums:
                        results_column.controls.append(ft.Text(value="No results found."))
                    else:
                        img_row = []
                        for album in albums:
                            img_url = album.get("artworkUrl100") or album.get("artworkUrl60")
                            if img_url:
                                img_url = img_url.replace("100x100bb.jpg", "600x600bb.jpg")
                                img = ft.Image(src=img_url, width=100, height=100, fit=ft.BoxFit.CONTAIN)
                                btn = ft.GestureDetector(
                                    content=img,
                                    on_tap=lambda e, url=img_url: select_image(url),
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                )
                                img_row.append(btn)
                        if img_row:
                            results_column.controls.append(ft.Row(controls=img_row, wrap=True))
                except Exception as ex:
                    logger.error(f"Error searching for cover art: {ex}")
                    results_column.controls.append(ft.Text(value="Error searching for cover art."))
                page.update()

            search_field = ft.TextField(label="Search for cover art", value=default_query, on_submit=do_search_action)

            def select_image(img_url):
                def do_confirm_upload(_e=None):
                    try:
                        page.update()
                        resp = httpx.get(img_url, timeout=15)
                        resp.raise_for_status()
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmpf:
                            tmpf.write(resp.content)
                            tmp_path = tmpf.name

                        def progress_cb(_msg, _frac):
                            try:
                                page.update()
                            except Exception:
                                logger.error("Error in progress_cb (confirm upload)")

                        res = api.upload_cover_image(
                            image_path=tmp_path,
                            imageUrl=None,
                            autoconvert=True,
                            coverType=None,
                            filename=None,
                            progress_callback=progress_cb,
                        )
                        logger.debug(f"Uploaded cover response (confirm upload): {res}")
                        try:
                            card_model = _get_latest_card_model().apply_cover_upload_result(
                                upload_result=res,
                                fallback_url=img_url,
                            )
                            page.update_card(card_model)
                        except Exception:
                            logger.error("Upload succeeded but attach failed (confirm upload)")
                        finally:
                            page.update()

                        try:
                            os.remove(tmp_path)
                        except Exception:
                            logger.error(f"Failed to remove temp file {tmp_path}")
                        page.pop_dialog()
                        page.update()
                    except Exception as e:
                        logger.error(f"Top-level upload error (confirm upload): {e}")
                        page.update()

                def do_cancel(_e=None):
                    page.pop_dialog()
                    page.update()

                confirm_dialog = ft.AlertDialog(
                    title=ft.Text(value="Use this cover image?"),
                    content=ft.Image(src=img_url, width=300, height=300, fit=ft.BoxFit.CONTAIN),
                    actions=[
                        ft.TextButton(content="Use this image", on_click=do_confirm_upload),
                        ft.TextButton(content="Cancel", on_click=do_cancel),
                    ],
                )
                page.show_dialog(confirm_dialog)

            search_dialog = ft.AlertDialog(
                title=ft.Text(value="Search for Cover Art"),
                content=ft.Column(
                    controls=[
                        search_field,
                        ft.Text(value="Click an image to select it as the cover art."),
                        results_column,
                    ],
                    height=400,
                    width=500,
                ),
                actions=[
                    ft.TextButton(content="Search", on_click=do_search_action),
                    ft.TextButton(content="Close", on_click=lambda e: page.pop_dialog()),
                ],
            )
            page.show_dialog(search_dialog)
            do_search_action()
        except Exception as ex:
            logger.error(f"Error opening search dialog: {ex}")

    content_children = []
    if cover_src:
        try:
            preview = ft.Image(src=cover_src, width=240, height=240, fit=ft.BoxFit.CONTAIN)
            content_children.append(ft.Column(controls=[ft.Text(value="Current cover"), preview], spacing=6))
        except Exception:
            pass

    content_children.extend(
        [
            url_field,
            ft.Row(
                controls=[
                    ft.TextButton(
                        content="Pick file...",
                        on_click=_pick_cover_file,
                    ),
                    file_label,
                ]
            ),
            ft.TextButton(
                content="Search for cover art",
                on_click=do_search_cover,
            ),
        ]
    )

    add_cover_list = ft.Column(controls=content_children)
    dialog = ft.AlertDialog(
        title=ft.Text(value="Add Cover Image"),
        content=add_cover_list,
        actions=[
            ft.TextButton(content="Upload", on_click=lambda e: do_upload(c)),
            ft.TextButton(
                content="Remove cover art",
                on_click=lambda e: do_remove_cover(c),
                style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.WHITE),
            ),
            ft.TextButton(content="Cancel", on_click=close_add),
        ],
    )
    page.show_dialog(dialog)
    return dialog
