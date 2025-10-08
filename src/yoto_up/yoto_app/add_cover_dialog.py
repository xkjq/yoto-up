import flet as ft
from loguru import logger
import httpx

from yoto_up.yoto_app.api_manager import ensure_api

def add_cover_dialog(page, api_ref, c, fetch_playlists_sync, Card, CLIENT_ID, on_close=None):

    def do_remove_cover(_e=None):
        try:
            api = ensure_api(api_ref)
            card_id = c.get("cardId") or c.get("id") or c.get("contentId")
            if api and card_id:
                full = api.get_card(card_id)
                if hasattr(full, "model_dump"):
                    cd = full.model_dump(exclude_none=True)
                elif isinstance(full, dict):
                    cd = full
                else:
                    cd = c
            else:
                cd = c
            if "metadata" not in cd or not isinstance(cd.get("metadata"), dict):
                cd["metadata"] = {}
            # Remove the cover art
            if "cover" in cd["metadata"]:
                cd["metadata"]["cover"] = {}
            try:
                card_model = Card.model_validate(cd)
            except Exception:
                logger.error("Card.model_validate failed in remove cover")
                try:
                    card_model = Card(**cd)
                except Exception:
                    logger.error("Card(**cd) failed in remove cover")
                    return
            api.update_card(card_model, return_card_model=False)
            try:
                fetch_playlists_sync(None)
            except Exception:
                logger.error("fetch_playlists_sync failed in remove cover")
            page.update()
        except Exception as e:
            logger.error(f"Remove cover error: {e}")
            page.update()
    url_field = ft.TextField(label="Image URL (leave empty to upload file)")
    picker = ft.FilePicker()
    page.overlay.append(picker)
    file_label = ft.Text("No file chosen")

    # If the card already has a cover, try to locate a suitable image URL/path
    cover_src = None
    try:
        meta = (c.get("metadata") or {})
        cover = meta.get("cover") or {}
        if isinstance(cover, dict):
            for key in ("imageL", "imageM", "imageS", "image"):
                url_or_field = cover.get(key)
                if not url_or_field:
                    continue
                try:
                    if isinstance(url_or_field, str) and (url_or_field.startswith("http") or url_or_field.startswith("//")):
                        cache_fn = getattr(page, "get_cached_cover", None)
                        if callable(cache_fn):
                            p = cache_fn(url_or_field)
                            cover_src = str(p) if p else url_or_field
                        else:
                            cover_src = url_or_field
                        break
                    # if it's already a local path
                    if isinstance(url_or_field, str) and url_or_field and url_or_field.startswith("/"):
                        cover_src = url_or_field
                        break
                    # some implementations may store a dict with mediaUrl
                    if isinstance(url_or_field, dict):
                        media = url_or_field.get("mediaUrl") or url_or_field.get("media_url")
                        if media:
                            cache_fn = getattr(page, "get_cached_cover", None)
                            if callable(cache_fn):
                                p = cache_fn(media)
                                cover_src = str(p) if p else media
                            else:
                                cover_src = media
                            break
                except Exception:
                    continue
    except Exception:
        cover_src = None

    def on_pick_result(e: ft.FilePickerResultEvent):
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

    picker.on_result = on_pick_result


    def do_upload(_e=None):
        img_path = (
            file_label.value
            if file_label.value and file_label.value != "No file chosen"
            else None
        )
        img_url = (url_field.value or "").strip() or None
        if not img_path and not img_url:
            page.update()
            return

        try:
            api = ensure_api(api_ref)

            def progress_cb(msg, frac):
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
            print(f"Uploaded cover response: {res}")
            cover = (
                res.get("coverImage")
                if isinstance(res, dict) and "coverImage" in res
                else res
            )
            mediaUrl = None
            if isinstance(cover, dict):
                mediaUrl = cover.get("mediaUrl") or cover.get("media_url")
            try:
                card_id = (
                    c.get("cardId") or c.get("id") or c.get("contentId")
                )
                if api and card_id:
                    full = api.get_card(card_id)
                    if hasattr(full, "model_dump"):
                        cd = full.model_dump(exclude_none=True)
                    elif isinstance(full, dict):
                        cd = full
                    else:
                        cd = c
                else:
                    cd = c
                if "metadata" not in cd or not isinstance(
                    cd.get("metadata"), dict
                ):
                    cd["metadata"] = {}
                if "cover" not in cd["metadata"] or not isinstance(
                    cd["metadata"].get("cover"), dict
                ):
                    cd["metadata"]["cover"] = {}
                elif mediaUrl:
                    cd["metadata"]["cover"]["imageL"] = mediaUrl
                elif img_url:
                    cd["metadata"]["cover"]["imageL"] = img_url

                try:
                    card_model = Card.model_validate(cd)
                except Exception:
                    logger.error("Card.model_validate failed")
                    try:
                        card_model = Card(**cd)
                    except Exception:
                        logger.error("Card(**cd) failed")
                        try:
                            api.create_or_update_content(
                                Card.model_validate(cd)
                            )
                        except Exception:
                            logger.error("api.create_or_update_content failed")
                        page.update()
                        return

                print(card_model)
                api.update_card(card_model, return_card_model=False)
                ## Refresh the card/playlist object from the server to update local metadata
                #try:
                #    card_id = cd.get("cardId") or cd.get("id") or cd.get("contentId")
                #    if card_id:
                #        refreshed = api.get_card(card_id)
                #        if hasattr(refreshed, "model_dump"):
                #            c.clear()
                #            c.update(refreshed.model_dump(exclude_none=True))
                #        elif isinstance(refreshed, dict):
                #            c.clear()
                #            c.update(refreshed)
                #except Exception:
                #    logger.error("Failed to refresh card after cover upload")
                try:
                    fetch_playlists_sync(None)
                except Exception:
                    logger.error("fetch_playlists_sync failed")
            except Exception as ex:
                logger.error("Upload succeeded but attach failed")
            finally:
                page.update()
        except Exception as e:
            logger.error(f"Top-level upload error: {e}")
            page.update()

        try:
            dialog.open = False
        except Exception:
            logger.error("Failed to close dialog after upload")
        page.update()

    def close_add(_e):
        try:
            dialog.open = False
        except Exception:
            logger.error("Failed to close dialog in close_add")
        page.update()
        # call optional on_close callback (e.g., to reopen parent dialog)
        try:
            if callable(on_close):
                try:
                    on_close()
                except Exception:
                    # allow on_close to accept an event param
                    try:
                        on_close(None)
                    except Exception:
                        logger.exception("on_close callback failed")
        except Exception:
            pass

    def do_search_cover(_e=None):
        try:
            default_query = c.get("title") or c.get("name") or ""
            results_column = ft.Column([])
            # Define do_search_action first so it can be referenced
            def do_search_action(_e2=None):
                query = (search_field.value or "").strip()
                logger.info(f"Searching for cover art with query: {query}")
                results_column.controls.clear()
                try:
                    resp = httpx.get(
                        "https://itunes.apple.com/search",
                        params={"term": query, "media": "music", "entity": "album", "limit": 12},
                        timeout=10
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    albums = data.get("results", [])
                    if not albums:
                        results_column.controls.append(ft.Text("No results found."))
                    else:
                        img_row = []
                        for album in albums:
                            img_url = album.get("artworkUrl100") or album.get("artworkUrl60")
                            if img_url:
                                img_url = img_url.replace("100x100bb.jpg", "600x600bb.jpg")
                                img = ft.Image(src=img_url, width=100, height=100, fit=ft.ImageFit.CONTAIN)
                                btn = ft.GestureDetector(
                                    content=img,
                                    on_tap=lambda e, url=img_url: select_image(url),
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                )
                                img_row.append(btn)
                        if img_row:
                            results_column.controls.append(ft.Row(img_row, wrap=True, scroll="auto"))
                except Exception as ex:
                    logger.error(f"Error searching for cover art: {ex}")
                    results_column.controls.append(ft.Text("Error searching for cover art."))
                page.update()

            search_field = ft.TextField(label="Search for cover art", value=default_query, on_submit=do_search_action)

            def select_image(img_url):
                    def do_confirm_upload(_e=None):
                        try:
                            page.update()
                            api = ensure_api(api_ref)
                            # Download the image to a temporary file
                            import tempfile, httpx, os
                            resp = httpx.get(img_url, timeout=15)
                            resp.raise_for_status()
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmpf:
                                tmpf.write(resp.content)
                                tmp_path = tmpf.name
                            # Upload using the same logic as do_upload, but with the temp file
                            def progress_cb(msg, frac):
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
                            logger.error(f"Uploaded cover response (confirm upload): {res}")
                            cover = (
                                res.get("coverImage")
                                if isinstance(res, dict) and "coverImage" in res
                                else res
                            )
                            mediaUrl = None
                            if isinstance(cover, dict):
                                mediaUrl = cover.get("mediaUrl") or cover.get("media_url")
                            try:
                                card_id = (
                                    c.get("cardId") or c.get("id") or c.get("contentId")
                                )
                                if api and card_id:
                                    full = api.get_card(card_id)
                                    if hasattr(full, "model_dump"):
                                        cd = full.model_dump(exclude_none=True)
                                    elif isinstance(full, dict):
                                        cd = full
                                    else:
                                        cd = c
                                else:
                                    cd = c
                                if "metadata" not in cd or not isinstance(
                                    cd.get("metadata"), dict
                                ):
                                    cd["metadata"] = {}
                                if "cover" not in cd["metadata"] or not isinstance(
                                    cd["metadata"].get("cover"), dict
                                ):
                                    cd["metadata"]["cover"] = {}

                                if mediaUrl:
                                    cd["metadata"]["cover"]["imageL"] = mediaUrl
                                elif img_url:
                                    cd["metadata"]["cover"]["imageL"] = img_url

                                logger.error(f"Card data for update (confirm upload): {cd}")

                                try:
                                    card_model = Card.model_validate(cd)
                                except Exception:
                                    logger.error("Card.model_validate failed (confirm upload)")
                                    try:
                                        card_model = Card(**cd)
                                    except Exception:
                                        logger.error("Card(**cd) failed (confirm upload)")
                                        try:
                                            api.create_or_update_content(
                                                Card.model_validate(cd)
                                            )
                                        except Exception:
                                            logger.error("api.create_or_update_content failed (confirm upload)")
                                        page.update()
                                        return


                                api.update_card(card_model, return_card_model=False)
                                try:
                                    fetch_playlists_sync(None)
                                except Exception:
                                    logger.error("fetch_playlists_sync failed (confirm upload)")
                            except Exception as ex:
                                logger.error("Upload succeeded but attach failed (confirm upload)")
                            finally:
                                page.update()
                            # Clean up temp file
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                            try:
                                confirm_dialog.open = False
                            except Exception:
                                pass
                            page.update()
                        except Exception as e:
                            logger.error(f"Top-level upload error (confirm upload): {e}")
                            page.update()
                    def do_cancel(_e=None):
                        try:
                            confirm_dialog.open = False
                        except Exception:
                            pass
                        page.update()
                    confirm_dialog = ft.AlertDialog(
                        title=ft.Text("Use this cover image?"),
                        content=ft.Image(src=img_url, width=300, height=300, fit=ft.ImageFit.CONTAIN),
                        actions=[
                            ft.TextButton("Use this image", on_click=do_confirm_upload),
                            ft.TextButton("Cancel", on_click=do_cancel),
                        ],
                    )
                    page.open(confirm_dialog)



            search_dialog = ft.AlertDialog(
                title=ft.Text("Search for Cover Art"),
                content=ft.Column([
                    search_field,
                    ft.Text("Click an image to select it as the cover art."),
                    results_column
                ], scroll="auto", height=400, width=500),
                actions=[
                    ft.TextButton("Search", on_click=do_search_action),
                    ft.TextButton("Close", on_click=lambda e: setattr(search_dialog, 'open', False) or page.update()),
                ],
            )
            page.open(search_dialog)
            # Trigger initial search when dialog opens
            do_search_action()
        except Exception:
            logger.error("Error opening search dialog")

    # Build the dialog content, showing current cover (if any) above the controls
    content_children = []
    if cover_src:
        try:
            preview = ft.Image(src=cover_src, width=240, height=240, fit=ft.ImageFit.CONTAIN)
            content_children.append(ft.Column([ft.Text("Current cover"), preview], spacing=6))
        except Exception:
            pass

    content_children.extend([
        url_field,
        ft.Row(
            [
                ft.TextButton(
                    "Pick file...",
                    on_click=lambda e: picker.pick_files(
                        allow_multiple=False
                    ),
                ),
                file_label,
            ]
        ),
        ft.TextButton(
            "Search for cover art",
            on_click=do_search_cover,
        ),
    ])

    add_cover_list = ft.Column(content_children)
    dialog = ft.AlertDialog(
        title=ft.Text("Add Cover Image"),
        content=add_cover_list,
        actions=[
            ft.TextButton("Upload", on_click=do_upload),
            ft.TextButton(
                "Remove cover art",
                on_click=do_remove_cover,
                style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.WHITE),
            ),
            ft.TextButton("Cancel", on_click=close_add),
        ],
    )
    page.open(dialog)
    return dialog
