from nltk.lm.vocabulary import _
from yoto_up.yoto_app.playlists import build_playlists_ui
from fontTools.mtiLib import build
from yoto_up.yoto_app.api_manager import ensure_api
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
):
    """Show the Replace Default Icons confirmation and run the replacement worker.

    Parameters mirror the original usage in playlists module so the implementation
    can refresh UI and call back into the playlists helpers.
    """
    try:
        warn = ft.Text(
            value="""Replacing default icons may take a long time. 
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
                        page.pop_dialog()
                        page.update()

                        prog = ft.ProgressBar(width=400)
                        prog_text = ft.Text(value="Preparing...")
                        prog_col = ft.Column(controls=[prog_text, prog])
                        cancel_event = threading.Event()

                        def do_cancel(_e=None):
                            cancel_event.set()
                            prog_text.value = "Cancelling..."
                            page.update()

                        replace_dialog = ft.AlertDialog(
                            title=ft.Text(value="Replace Default Icons"),
                            content=prog_col,
                            actions=[ft.TextButton(content="Cancel", on_click=do_cancel)],
                        )
                        page.show_dialog(replace_dialog)

                        def work():
                            new_card = None
                            try:
                                prog_text.value = "Fetching card..."
                                prog.value = 0.0
                                page.update()
                                api = ensure_api(api_ref, CLIENT_ID)
                                card_id = c.cardId
                                if not card_id:
                                    raise RuntimeError("Unable to determine card id")
                                full = api.get_card(card_id)
                                prog_text.value = "Analyzing icons..."
                                page.update()

                                def icon_progress(msg, frac):
                                    if msg:
                                        prog_text.value = msg
                                    if frac is not None:
                                        prog.value = frac
                                    page.update()

                                new_card = api.replace_card_default_icons(
                                    full,
                                    progress_callback=icon_progress,
                                    cancel_event=cancel_event,
                                    include_yotoicons=include_yotoicons,
                                    max_searches=max_searches,
                                )
                                prog_text.value = "Saving updated card..."
                                page.update_card(new_card)
                                prog_text.value = "Done"
                                prog.value = 1.0

                                build_playlists_ui(page)
                            except Exception as ex:
                                page.show_snack(
                                        f"Replace icons failed: {ex}", error=True
                                    )
                                logger.exception("replace_icons error")
                            time.sleep(1)
                            page.show_card_details(new_card)

                        page.run_task(work)
                    except Exception as ee:
                        page.show_snack(f"Failed to start replace: {ee}", error=True)

                # If user selected a value larger than 2, show a confirmation before starting
                if max_searches > 2:
                    try:
                        warn_txt = ft.Text(
                            value="You have chosen a max extra searches value > 2. This may significantly increase runtime and API usage. Continue?"
                        )
                        secondary = ft.AlertDialog(
                            title=ft.Text(value="Confirm large search count"),
                            content=warn_txt,
                            actions=[
                                ft.TextButton(
                                    content="Start",
                                    on_click=lambda e: (
                                        (
                                            setattr(secondary, "open", False)
                                            if hasattr(secondary, "open")
                                            else None
                                        ),
                                        page.update(),
                                        threading.Thread(
                                            target=_start_worker, daemon=True
                                        ).start(),
                                    ),
                                ),
                                ft.TextButton(
                                    content="Cancel",
                                    on_click=lambda e: (
                                        page.pop_dialog(),
                                        page.update(),
                                    ),
                                ),
                            ],
                        )
                        page.show_dialog(secondary)
                    except Exception:
                        threading.Thread(target=_start_worker, daemon=True).start()
                else:
                    threading.Thread(target=_start_worker, daemon=True).start()
            except Exception as ee:
                page.show_snack(f"Failed to start replace: {ee}", error=True)

        def cancel_confirm(_e=None):
            page.pop_dialog()
            page.update()

        confirm_dialog = ft.AlertDialog(
            title=ft.Text(value="Confirm replace default icons"),
            content=ft.Column(
                controls=[
                    warn,
                    include_yoto,
                    ft.Row(
                        controls=[

                            max_searches_field,
                            ft.Text(value=" "),
                            ft.Text(value="(larger values = more searches, longer runtime)"),
                        ]
                    ),
                ]
            ),
            actions=[
                ft.TextButton(content="Start", on_click=start_replace),
                ft.TextButton(content="Cancel", on_click=cancel_confirm),
            ],
        )

        try:
            page.show_dialog(confirm_dialog)
        except Exception:
            try:
                page.dialog = confirm_dialog
                page.update()
            except Exception:
                logger.exception("Unable to show confirmation dialog for replace_icons")
    except Exception as e:
        page.show_snack(f"Replace icons failed to start: {e}", error=True)
        logger.exception("replace_icons start error")


def start_replace_icons_background(
    page,
    c,
):
    """Start replace default icons in background and show a persistent badge on the page.

    The badge shows progress and can be clicked to reopen a small status dialog with Cancel.
    """
    logger.debug("Starting background replace icons")
    try:
        # Badge UI
        badge_text = ft.Text(value="Autoselect: 0%")

        # Cancellation event for the worker
        cancel_event = threading.Event()
        # Expose cancel_event on page so UI helpers (badge click) can access it
        try:
            setattr(page, "autoselect_cancel_event", cancel_event)
        except Exception:
            pass

        # Prefer using page helpers if available (added in gui.py)
        async def _set_badge(msg, frac, visible=True):
            await page.set_autoselect_progress(msg, frac, visible=visible)

        def _open_status_dialog(hide_default=False):
            page.open_autoselect_status_dialog(cancel_event, hide_default=hide_default)

        hide_default = getattr(page, "autoselect_hide_dialog_default", False)
        _open_status_dialog(hide_default=hide_default)

        # Show initial badge state
        _set_badge("Starting", 0.0, visible=True)

        # Open the status dialog by default unless the page requests it be hidden

        async def work():
            new_card = None
            try:
                api = ensure_api(page.api_ref)
                card_id = c.cardId
                if not card_id:
                    raise RuntimeError("Unable to determine card id")
                full = api.get_card(card_id)


                new_card = api.replace_card_default_icons(
                    full,
                    progress_callback=_set_badge,
                    cancel_event=cancel_event,
                )

                page.update_card(new_card)
                page.pop_dialog()  # close the status dialog if it's still open
                page.show_card_details(new_card)

            except Exception as ex:
                page.show_snack(f"Replace icons failed: {ex}", error=True)
                logger.exception("replace_icons error")
            finally:
                # remove badge after short delay
                try:
                    time.sleep(1)
                except Exception:
                    pass
                try:
                    if hasattr(page, "set_autoselect_progress"):
                        page.set_autoselect_progress("", 0.0, visible=False)
                except Exception:
                    pass

        page.run_task(work)
    except Exception as e:
        page.show_snack(f"Failed to start background replace: {e}", error=True)
        logger.exception("start_replace_icons_background error")
