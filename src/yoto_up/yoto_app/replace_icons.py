from nltk.lm.vocabulary import _
from yoto_up.yoto_app.playlists import build_playlists_ui
from fontTools.mtiLib import build
from yoto_up.yoto_app.api_manager import ensure_api
from yoto_up.yoto_app.config import CLIENT_ID
from yoto_up.models import DEFAULT_MEDIA_ID
import threading
import asyncio
import time
import json
import flet as ft
from loguru import logger
import copy


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

                        async def work():
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

                                # Build targets that need replacement and suggested search labels
                                targets = []
                                chapters = full.content.chapters if full.content and full.content.chapters else []
                                for ch_idx, chapter in enumerate(chapters):
                                    icon_field = chapter.get_icon_field()
                                    if icon_field is None or (icon_field and icon_field.endswith(DEFAULT_MEDIA_ID)):
                                        targets.append(("chapter", ch_idx, None))
                                    if hasattr(chapter, "tracks") and chapter.tracks:
                                        for tr_idx, track in enumerate(chapter.tracks):
                                            ticon = track.get_icon_field()
                                            if ticon is None or (ticon and ticon.endswith(DEFAULT_MEDIA_ID)):
                                                targets.append(("track", ch_idx, tr_idx))

                                total = len(targets)
                                if total == 0:
                                    prog_text.value = "No default icons to replace"
                                    page.update()
                                    await asyncio.sleep(1)
                                    return

                                # Prepare default labels using model helper
                                default_labels = []
                                need_edit = False
                                for kind, ch_idx, tr_idx in targets:
                                    label = full.choose_icon_search_label(kind, ch_idx, tr_idx)
                                    default_labels.append(label)
                                    # if label falls back to card title or is blank, offer edit
                                    if not label or label == full.get_title():
                                        need_edit = True

                                # If user wants to edit search terms, show dialog
                                user_labels = list(default_labels)
                                if need_edit:
                                    # Group targets by identical default label so edits apply to all
                                    groups: dict[str, list[tuple[int, str, int | None, int | None]]] = {}
                                    for i, (kind, ch_idx, tr_idx) in enumerate(targets):
                                        key = default_labels[i] or ""
                                        groups.setdefault(key, []).append((i, kind, ch_idx, tr_idx))

                                    edit_rows = []
                                    for key, members in groups.items():
                                        # Build a descriptive label that lists affected targets
                                        parts = []
                                        for (_idx, kind, ch_idx, tr_idx) in members:
                                            if kind == 'chapter':
                                                parts.append(f"Ch{ch_idx+1}")
                                            else:
                                                parts.append(f"T{ch_idx+1}.{tr_idx+1}")
                                        title = ", ".join(parts)
                                        initial = key
                                        tf = ft.TextField(label=title, value=initial, width=400)
                                        # store all target indices this control should update
                                        setattr(tf, "_target_indices", [m[0] for m in members])
                                        edit_rows.append(tf)

                                    edit_col = ft.Column(controls=edit_rows, scroll=ft.ScrollMode.AUTO)
                                    dlg = ft.AlertDialog(
                                        title=ft.Text(value="Edit search terms for icon replacement"),
                                        content=ft.Column(controls=[ft.Text(value=f"Preparing to replace {total} icons. Edit grouped search terms below if needed."), edit_col]),
                                        actions=[
                                            ft.TextButton(content=ft.Text(value="Start"), on_click=lambda e: (setattr(dlg, "open", False) if hasattr(dlg, "open") else None, page.update())),
                                            ft.TextButton(content=ft.Text(value="Cancel"), on_click=lambda e: (setattr(dlg, "open", False) if hasattr(dlg, "open") else None, setattr(dlg, "_cancelled", True) if hasattr(dlg, "_cancelled") else None, page.update())),
                                        ],
                                        scrollable=True,
                                    )
                                    # show dialog and wait until closed by user
                                    dlg._cancelled = False
                                    page.show_dialog(dlg)
                                    page.update()

                                    # Busy-wait for dialog close (runs in the event loop thread)
                                    while getattr(dlg, "open", False):
                                        await asyncio.sleep(0.1)

                                    if getattr(dlg, "_cancelled", False):
                                        prog_text.value = "Cancelled"
                                        page.update()
                                        return

                                    # Collect edited labels and apply to all grouped indices
                                    for ctrl in edit_rows:
                                        indices = getattr(ctrl, "_target_indices", None) or []
                                        for idx in indices:
                                            user_labels[idx] = ctrl.value or ""

                                # Use a deep copy of the card to avoid mutating original
                                card_for_replace = copy.deepcopy(full)
                                for i, (kind, ch_idx, tr_idx) in enumerate(targets):
                                    val = user_labels[i] if i < len(user_labels) else default_labels[i]
                                    if not val:
                                        continue
                                    if kind == 'chapter':
                                        try:
                                            card_for_replace.content.chapters[ch_idx].title = val
                                        except Exception:
                                            pass
                                    else:
                                        try:
                                            card_for_replace.content.chapters[ch_idx].tracks[tr_idx].title = val
                                        except Exception:
                                            pass

                                # Ensure replacement runs off the event loop so UI can update.
                                loop = asyncio.get_running_loop()

                                def _ui_update(msg, frac):
                                    try:
                                        if msg:
                                            prog_text.value = msg
                                        if frac is not None:
                                            prog.value = frac
                                        page.update()
                                    except Exception:
                                        pass

                                def icon_progress(msg, frac):
                                    # This may be called from a worker thread; schedule UI update on loop
                                    try:
                                        loop.call_soon_threadsafe(_ui_update, msg or "", float(frac) if frac is not None else None)
                                    except Exception:
                                        try:
                                            _ui_update(msg, frac)
                                        except Exception:
                                            pass

                                new_card = await asyncio.to_thread(
                                    api.replace_card_default_icons,
                                    card_for_replace,
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
                            #await asyncio.sleep(1)
                            page.pop_dialog()
                            page.update_card(new_card)
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
    confirm: bool = True,
):
    """Start replace default icons in background and show a persistent badge on the page.

    The badge shows progress and can be clicked to reopen a small status dialog with Cancel.
    """
    logger.debug("Starting background replace icons")
    # If caller requests interactive confirmation, delegate to dialog flow
    try:
        if confirm:
            # Reuse interactive dialog which supports editing search terms
            try:
                return show_replace_icons_dialog(page, getattr(page, "api_ref", None), c)
            except Exception:
                # fallback to non-interactive mode
                pass
    except Exception:
        pass
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
        # create a synchronous callback that schedules the async page updater
        last_badge_update = 0.0

        def _set_badge(msg, frac, visible=True):
            nonlocal last_badge_update
            # debounce frequent updates to avoid flooding the event loop
            now = time.time()
            if (now - last_badge_update) < 0.05 and visible:
                return
            last_badge_update = now
            # schedule the async progress updater on the event loop
            asyncio.create_task(page.set_autoselect_progress(msg, frac, visible=visible))

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


                logger.debug("Fetched card, starting icon replacement")
                # Run replacement in a thread so we don't block the event loop
                new_card = await asyncio.to_thread(
                    api.replace_card_default_icons,
                    full,
                    progress_callback=_set_badge,
                    cancel_event=cancel_event,
                )
                logger.debug("Icon replacement complete, updating card")

                # update the card on the page and yield briefly so UI can process
                page.update_card(new_card)
                page.pop_dialog()
                page.show_card_details(new_card)

            except Exception as ex:
                page.show_snack(f"Replace icons failed: {ex}", error=True)
                logger.exception("replace_icons error")
            finally:
                # remove badge after short delay
                #await asyncio.sleep(0.1)
                _set_badge("", 0.0, visible=False)

        page.run_task(work)
    except Exception as e:
        page.show_snack(f"Failed to start background replace: {e}", error=True)
        logger.exception("start_replace_icons_background error")
