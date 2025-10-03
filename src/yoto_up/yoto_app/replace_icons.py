import threading
import asyncio
import time
import json
import flet as ft
from loguru import logger


def show_replace_icons_dialog(
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
):
    """Show the Replace Default Icons confirmation and run the replacement worker.

    Parameters mirror the original usage in playlists module so the implementation
    can refresh UI and call back into the playlists helpers.
    """
    try:
        warn = ft.Text(
            """Replacing default icons may take a long time. 
The more icons missing, the longer it takes.

Continue?"""
        )
        include_yoto = ft.Checkbox(label="Include YotoIcons search", value=True)
        max_searches_field = ft.TextField(
            label="Max extra searches (per track/chapter)", value="2", width=120
        )

        def start_replace(_e=None):
            try:
                try:
                    max_searches = int(max_searches_field.value or "3")
                except Exception:
                    max_searches = 3
                include_yotoicons = bool(include_yoto.value)

                def _start_worker():
                    try:
                        try:
                            confirm_dialog.open = False
                            page.update()
                        except Exception:
                            pass

                        prog = ft.ProgressBar(width=400)
                        prog_text = ft.Text("Preparing...")
                        prog_col = ft.Column([prog_text, prog])
                        cancel_event = threading.Event()

                        def do_cancel(_e=None):
                            try:
                                cancel_event.set()
                                prog_text.value = "Cancelling..."
                                page.update()
                            except Exception:
                                pass

                        replace_dialog = ft.AlertDialog(
                            title=ft.Text("Replace Default Icons"),
                            content=prog_col,
                            actions=[ft.TextButton("Cancel", on_click=do_cancel)],
                        )
                        page.open(replace_dialog)

                        def work():
                            new_card = None
                            try:
                                prog_text.value = "Fetching card..."
                                prog.value = 0.0
                                page.update()
                                api = ensure_api(api_ref, CLIENT_ID)
                                card_id = (
                                    c.get("cardId") or c.get("id") or c.get("contentId")
                                )
                                if not card_id:
                                    raise RuntimeError("Unable to determine card id")
                                full = api.get_card(card_id)
                                prog_text.value = "Analyzing icons..."
                                page.update()

                                def icon_progress(msg, frac):
                                    try:
                                        if msg:
                                            prog_text.value = msg
                                        if frac is not None:
                                            prog.value = frac
                                        page.update()
                                    except Exception:
                                        pass

                                new_card = api.replace_card_default_icons(
                                    full,
                                    progress_callback=icon_progress,
                                    cancel_event=cancel_event,
                                    include_yotoicons=include_yotoicons,
                                    max_searches=max_searches,
                                )
                                prog_text.value = "Saving updated card..."
                                page.update()
                                api.update_card(new_card, return_card_model=False)
                                prog_text.value = "Done"
                                prog.value = 1.0

                                def run_on_ui(fn, *a, **kw):
                                    try:
                                        loop = asyncio.get_event_loop()
                                        loop.call_soon_threadsafe(lambda: fn(*a, **kw))
                                    except Exception:
                                        try:
                                            fn(*a, **kw)
                                        except Exception:
                                            pass

                                def get_card_id(card_obj):
                                    try:
                                        if isinstance(card_obj, dict):
                                            return (
                                                card_obj.get("id")
                                                or card_obj.get("contentId")
                                                or card_obj.get("cardId")
                                            )
                                        return (
                                            getattr(card_obj, "id", None)
                                            or getattr(card_obj, "contentId", None)
                                            or getattr(card_obj, "cardId", None)
                                        )
                                    except Exception:
                                        return None

                                def refresh_ui(card_model):
                                    try:
                                        updated_id = get_card_id(card_model)
                                    except Exception:
                                        updated_id = None
                                    if not updated_id:
                                        try:
                                            page.update()
                                        except Exception:
                                            pass
                                        return
                                    try:
                                        for i, ctrl in enumerate(list(playlists_list.controls)):
                                            cb = None
                                            children = (
                                                getattr(ctrl, "controls", None)
                                                or getattr(
                                                    getattr(ctrl, "content", None),
                                                    "controls",
                                                    None,
                                                )
                                                or []
                                            )
                                            for ch in children or []:
                                                if getattr(ch, "_is_playlist_checkbox", False):
                                                    cb = ch
                                                    break
                                            if not cb:
                                                continue
                                            if getattr(cb, "_cid", None) == updated_id:
                                                try:
                                                    playlists_list.controls[i] = (
                                                        make_playlist_row(card_model, idx=i)
                                                    )
                                                    page.update()
                                                    try:
                                                        show_snack("Playlist icons updated")
                                                    except Exception:
                                                        pass
                                                except Exception:
                                                    pass
                                                return
                                        threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                                    except Exception:
                                        pass

                                run_on_ui(refresh_ui, new_card)
                            except Exception as ex:
                                try:
                                    show_snack(f"Replace icons failed: {ex}", error=True)
                                except Exception:
                                    pass
                                logger.exception("replace_icons error")
                            time.sleep(1)
                            try:
                                show_card_details(None, new_card)
                            except Exception:
                                pass

                        threading.Thread(target=work, daemon=True).start()
                    except Exception as ee:
                        try:
                            show_snack(f"Failed to start replace: {ee}", error=True)
                        except Exception:
                            pass

                # If user selected a value larger than 2, show a confirmation before starting
                if max_searches > 2:
                    try:
                        warn_txt = ft.Text(
                            "You have chosen a max extra searches value > 2. This may significantly increase runtime and API usage. Continue?"
                        )
                        secondary = ft.AlertDialog(
                            title=ft.Text("Confirm large search count"),
                            content=warn_txt,
                            actions=[
                                ft.TextButton(
                                    "Start",
                                    on_click=lambda e: (
                                        (setattr(secondary, "open", False) if hasattr(secondary, "open") else None),
                                        page.update(),
                                        threading.Thread(target=_start_worker, daemon=True).start(),
                                    ),
                                ),
                                ft.TextButton("Cancel", on_click=lambda e: (setattr(secondary, "open", False), page.update())),
                            ],
                        )
                        page.open(secondary)
                    except Exception:
                        threading.Thread(target=_start_worker, daemon=True).start()
                else:
                    threading.Thread(target=_start_worker, daemon=True).start()
            except Exception as ee:
                try:
                    show_snack(f"Failed to start replace: {ee}", error=True)
                except Exception:
                    pass

        def cancel_confirm(_e=None):
            try:
                confirm_dialog.open = False
            except Exception:
                pass
            page.update()

        confirm_dialog = ft.AlertDialog(
            title=ft.Text("Confirm replace default icons"),
            content=ft.Column(
                [
                    warn,
                    include_yoto,
                    ft.Row(
                        [
                            max_searches_field,
                            ft.Text(" "),
                            ft.Text("(larger values = more searches, longer runtime)"),
                        ]
                    ),
                ]
            ),
            actions=[
                ft.TextButton("Start", on_click=start_replace),
                ft.TextButton("Cancel", on_click=cancel_confirm),
            ],
        )

        try:
            page.open(confirm_dialog)
        except Exception:
            try:
                page.dialog = confirm_dialog
                page.update()
            except Exception:
                logger.exception("Unable to show confirmation dialog for replace_icons")
    except Exception as e:
        try:
            show_snack(f"Replace icons failed to start: {e}", error=True)
        except Exception:
            pass
        logger.exception("replace_icons start error")


def start_replace_icons_background(
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
):
    """Start replace default icons in background and show a persistent badge on the page.

    The badge shows progress and can be clicked to reopen a small status dialog with Cancel.
    """
    try:
        # Badge UI
        badge_text = ft.Text("Autoselect: 0%")

        # Cancellation event for the worker
        cancel_event = threading.Event()
        # Expose cancel_event on page so UI helpers (badge click) can access it
        try:
            setattr(page, 'autoselect_cancel_event', cancel_event)
        except Exception:
            pass

        # Prefer using page helpers if available (added in gui.py)
        def _set_badge(msg, frac, visible=True):
            try:
                if hasattr(page, 'set_autoselect_progress'):
                    page.set_autoselect_progress(msg, frac, visible=visible)
                else:
                    # fallback: update simple text
                    try:
                        badge_text.value = f"{int((frac or 0.0)*100)}% - {msg}" if msg else f"{int((frac or 0.0)*100)}%"
                        page.update()
                    except Exception:
                        pass
            except Exception:
                pass

        def _open_status_dialog():
            try:
                if hasattr(page, 'open_autoselect_status_dialog'):
                    page.open_autoselect_status_dialog(cancel_event)
                else:
                    # fallback simple dialog
                    try:
                        dlg = ft.AlertDialog(
                            title=ft.Text("Autoselect status"),
                            content=ft.Text(badge_text.value),
                            actions=[
                                ft.TextButton("Cancel", on_click=lambda e: (cancel_event.set(), page.close(dlg))),
                                ft.TextButton("Close", on_click=lambda e: page.close(dlg)),
                            ],
                        )
                        page.open(dlg)
                        page.update()
                    except Exception:
                        pass
            except Exception:
                pass

        # Show initial badge state
        _set_badge("Starting", 0.0, visible=True)

        # Open the status dialog by default unless the page requests it be hidden
        try:
            hide_default = getattr(page, 'autoselect_hide_dialog_default', False)
        except Exception:
            hide_default = False
        if not hide_default:
            try:
                _open_status_dialog()
            except Exception:
                pass

        def work():
            new_card = None
            try:
                api = ensure_api(api_ref, CLIENT_ID)
                card_id = c.get("cardId") or c.get("id") or c.get("contentId")
                if not card_id:
                    raise RuntimeError("Unable to determine card id")
                full = api.get_card(card_id)

                def icon_progress(msg, frac):
                    try:
                        _set_badge(msg, frac)
                    except Exception:
                        pass

                new_card = api.replace_card_default_icons(
                    full,
                    progress_callback=icon_progress,
                    cancel_event=cancel_event,
                )

                try:
                    api.update_card(new_card, return_card_model=False)
                except Exception:
                    pass

                # Refresh playlists UI on completion
                try:
                    updated_id = None
                    if isinstance(new_card, dict):
                        updated_id = new_card.get("id") or new_card.get("cardId") or new_card.get("contentId")
                    else:
                        updated_id = getattr(new_card, "id", None) or getattr(new_card, "cardId", None) or getattr(new_card, "contentId", None)

                    if updated_id:
                        for i, ctrl in enumerate(list(playlists_list.controls)):
                            cb = None
                            children = (
                                getattr(ctrl, "controls", None)
                                or getattr(getattr(ctrl, "content", None), "controls", None)
                                or []
                            )
                            for ch in children or []:
                                if getattr(ch, "_is_playlist_checkbox", False):
                                    cb = ch
                                    break
                            if not cb:
                                continue
                            if getattr(cb, "_cid", None) == updated_id:
                                try:
                                    playlists_list.controls[i] = make_playlist_row(new_card, idx=i)
                                    page.update()
                                    try:
                                        show_snack("Playlist icons updated")
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                                break
                        else:
                            # not found, refresh list
                            threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                except Exception:
                    pass

            except Exception as ex:
                try:
                    show_snack(f"Replace icons failed: {ex}", error=True)
                except Exception:
                    pass
                logger.exception("replace_icons error")
            finally:
                # remove badge after short delay
                try:
                    time.sleep(1)
                except Exception:
                    pass
                try:
                    if hasattr(page, 'set_autoselect_progress'):
                        page.set_autoselect_progress('', 0.0, visible=False)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()
    except Exception as e:
        try:
            show_snack(f"Failed to start background replace: {e}", error=True)
        except Exception:
            pass
        logger.exception("start_replace_icons_background error")
