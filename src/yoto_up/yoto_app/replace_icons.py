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
    """Show a simple confirmation dialog to collect options and delegate to
    the single background flow implemented in `start_replace_icons_background`.

    This function intentionally avoids duplicating the replacement logic — it
    only gathers user options and calls `start_replace_icons_background` with
    `confirm=False` so the centralized flow can perform card analysis and any
    further interactive edits.
    """
    try:
        warn = ft.Text(
            value=(
                "Replacing default icons may take a long time.\n"
                "The more icons missing, the longer it takes.\n\n"
                "Continue?"
            )
        )
        include_yoto = ft.Checkbox(label="Include YotoIcons search", value=True)
        max_searches_field = ft.TextField(
            label="Max extra searches (per track/chapter)", value="2", width=120
        )

        def on_start(_e=None):
            try:
                try:
                    max_searches = int(max_searches_field.value or "3")
                except Exception:
                    max_searches = 3
                include_yotoicons = bool(include_yoto.value)

                # Fetch card and build default labels so the dialog can present
                # grouped edit controls if needed. This keeps all interactive
                # UI in this function so `start_replace_icons_background` can
                # remain non-interactive.
                try:
                    api = ensure_api(api_ref, CLIENT_ID)
                except Exception:
                    api = ensure_api(getattr(page, "api_ref", None), CLIENT_ID)

                card_id = c.cardId
                if not card_id:
                    page.show_snack("Unable to determine card id", error=True)
                    return

                full = api.get_card(card_id)

                # Build targets and default labels
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
                    page.show_snack("No default icons to replace")
                    return

                default_labels = []
                need_edit = False
                for kind, ch_idx, tr_idx in targets:
                    label = full.choose_icon_search_label(kind, ch_idx, tr_idx)
                    default_labels.append(label)
                    if not label or label == full.get_title():
                        need_edit = True

                user_labels = list(default_labels)

                if need_edit:
                    # Group targets by identical default label so edits apply to all
                    groups: dict[str, list[tuple[int, str, int | None, int | None]]] = {}
                    for i, (kind, ch_idx, tr_idx) in enumerate(targets):
                        key = default_labels[i] or ""
                        groups.setdefault(key, []).append((i, kind, ch_idx, tr_idx))

                    edit_rows = []
                    for key, members in groups.items():
                        parts = []
                        for (_idx, kind, ch_idx, tr_idx) in members:
                            if kind == 'chapter':
                                parts.append(f"Ch{ch_idx+1}")
                            else:
                                parts.append(f"T{ch_idx+1}.{tr_idx+1}")
                        title = ", ".join(parts)
                        initial = key
                        tf = ft.TextField(label=title, value=initial, width=400)
                        setattr(tf, "_target_indices", [m[0] for m in members])
                        edit_rows.append(tf)

                    edit_col = ft.Column(controls=edit_rows, scroll=ft.ScrollMode.AUTO)

                    def _dlg_start(e=None):
                        # Collect edits, build card_for_replace and start background run
                        try:
                            for ctrl in edit_rows:
                                indices = getattr(ctrl, "_target_indices", None) or []
                                for idx in indices:
                                    user_labels[idx] = ctrl.value or ""

                            card_for_replace = copy.deepcopy(full)
                            for i, (kind, ch_idx, tr_idx) in enumerate(targets):
                                val = user_labels[i] if i < len(user_labels) else default_labels[i]
                                if not val:
                                    continue
                                try:
                                    if kind == 'chapter':
                                        card_for_replace.content.chapters[ch_idx].title = val
                                    else:
                                        card_for_replace.content.chapters[ch_idx].tracks[tr_idx].title = val
                                except Exception:
                                    pass

                            # close dialog and start background work
                            page.pop_dialog()
                            page.update()

                            try:
                                start_replace_icons_background(
                                    page,
                                    c,
                                    confirm=False,
                                    include_yotoicons=include_yotoicons,
                                    max_searches=max_searches,
                                    api_ref=api_ref,
                                    card_for_replace=card_for_replace,
                                )
                            except Exception:
                                try:
                                    threading.Thread(
                                        target=lambda: start_replace_icons_background(
                                            page,
                                            c,
                                            confirm=False,
                                            include_yotoicons=include_yotoicons,
                                            max_searches=max_searches,
                                            api_ref=api_ref,
                                            card_for_replace=card_for_replace,
                                        ),
                                        daemon=True,
                                    ).start()
                                except Exception:
                                    page.show_snack("Failed to start replace", error=True)
                        except Exception as ex:
                            page.show_snack(f"Failed to start replace: {ex}", error=True)

                    def _dlg_cancel(e=None):
                        try:
                            setattr(dlg, "_cancelled", True)
                        except Exception:
                            pass
                        page.pop_dialog()
                        page.update()

                    dlg = ft.AlertDialog(
                        title=ft.Text(value="Edit search terms for icon replacement"),
                        content=ft.Column(controls=[ft.Text(value=f"Preparing to replace {total} icons. Edit grouped search terms below if needed."), edit_col]),
                        actions=[
                            ft.TextButton(content=ft.Text(value="Start"), on_click=_dlg_start),
                            ft.TextButton(content=ft.Text(value="Cancel"), on_click=_dlg_cancel),
                        ],
                        scrollable=True,
                    )
                    dlg._cancelled = False
                    page.show_dialog(dlg)
                    page.update()
                    return

                # Build card_for_replace and delegate to non-interactive starter
                card_for_replace = copy.deepcopy(full)
                for i, (kind, ch_idx, tr_idx) in enumerate(targets):
                    val = user_labels[i] if i < len(user_labels) else default_labels[i]
                    if not val:
                        continue
                    try:
                        if kind == 'chapter':
                            card_for_replace.content.chapters[ch_idx].title = val
                        else:
                            card_for_replace.content.chapters[ch_idx].tracks[tr_idx].title = val
                    except Exception:
                        pass

                try:
                    start_replace_icons_background(
                        page,
                        c,
                        confirm=False,
                        include_yotoicons=include_yotoicons,
                        max_searches=max_searches,
                        api_ref=api_ref,
                        card_for_replace=card_for_replace,
                    )
                except Exception:
                    try:
                        threading.Thread(
                            target=lambda: start_replace_icons_background(
                                page,
                                c,
                                confirm=False,
                                include_yotoicons=include_yotoicons,
                                max_searches=max_searches,
                                api_ref=api_ref,
                                card_for_replace=card_for_replace,
                            ),
                            daemon=True,
                        ).start()
                    except Exception:
                        page.show_snack("Failed to start replace", error=True)
            except Exception as ee:
                page.show_snack(f"Failed to start replace: {ee}", error=True)

        def cancel_confirm(_e=None):
            page.pop_dialog()
            page.update()

        confirm_dialog = ft.AlertDialog(
            title=ft.Text(value="Confirm replace default icons"),
            content=ft.Column(
                controls=[warn, include_yoto, ft.Row(controls=[max_searches_field, ft.Text(value=" "), ft.Text(value="(larger values = more searches, longer runtime)")])]
            ),
            actions=[ft.TextButton(content="Start", on_click=on_start), ft.TextButton(content="Cancel", on_click=cancel_confirm)],
        )

        logger.debug("Showing replace icons confirmation dialog")
        page.show_dialog(confirm_dialog)
    except Exception as e:
        page.show_snack(f"Replace icons failed to start: {e}", error=True)
        logger.exception("replace_icons start error")


def start_replace_icons_background(
    page,
    c,
    confirm: bool = True,
    *,
    include_yotoicons: bool | None = None,
    max_searches: int | None = None,
    api_ref=None,
    card_for_replace=None,
):
    """Start replace default icons in background and show a persistent badge on the page.

    The badge shows progress and can be clicked to reopen a small status dialog with Cancel.
    """
    logger.debug("Starting background replace icons")
    # This function no longer opens the interactive confirmation dialog.
    # Callers that need an interactive flow should call
    # `show_replace_icons_dialog` which gathers options and delegates here.
    try:
        # Badge UI
        badge_text = ft.Text(value="Autoselect: 0%")

        logger.debug("Setting cancel event and exposing on page for badge click")
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
        last_badge_msg = None
        last_badge_frac = None

        logger.debug("Initializing badge update function")
        def _set_badge(msg, frac, visible=True):
            nonlocal last_badge_update, last_badge_msg, last_badge_frac
            # debounce frequent updates to avoid flooding the event loop.
            # Also avoid updating when the visible label and fraction haven't meaningfully changed.
            now = time.time()
            if visible:
                if last_badge_msg == msg and last_badge_frac == frac and (now - last_badge_update) < 0.15:
                    return
                if (now - last_badge_update) < 0.06 and last_badge_msg == msg:
                    return
            last_badge_update = now
            last_badge_msg = msg
            last_badge_frac = frac

            async def _do_update():
                try:
                    await page.set_autoselect_progress(msg, frac, visible=visible)
                except Exception:
                    # If the page/session is gone, swallow exceptions to avoid noisy logs
                    pass

            try:
                page.run_task(_do_update)
            except Exception:
                # Fallback to creating a task directly on the loop if run_task isn't available
                try:
                    asyncio.create_task(page.set_autoselect_progress(msg, frac, visible=visible))
                except Exception:
                    pass

        logger.debug("Defining function to open status dialog on badge click")
        def _open_status_dialog(hide_default=False):
            page.open_autoselect_status_dialog(cancel_event, hide_default=hide_default)

        hide_default = getattr(page, "autoselect_hide_dialog_default", False)
        # Schedule opening the status dialog on the page event loop so it
        # doesn't block if another dialog is currently open.
        async def _open_status_async():
            _open_status_dialog(hide_default=hide_default)

        logger.debug("Scheduled status dialog to open on event loop")
        page.run_task(_open_status_async)

        logger.debug("Set initial badge state")
        # Show initial badge state
        _set_badge("Starting", 0.0, visible=True)

        # Open the status dialog by default unless the page requests it be hidden

        async def work():
            new_card = None
            try:
                logger.debug("replace_icons background work: obtaining api and card id")
                api = ensure_api(api_ref or getattr(page, "api_ref", None))
                card_id = c.cardId
                if not card_id:
                    raise RuntimeError("Unable to determine card id")
                logger.debug(f"About to GET card {card_id}")
                full = api.get_card(card_id)
                logger.debug("GET card returned")

                # If a prepared card_for_replace was passed (from the dialog),
                # use it; otherwise, default to using `full` and let the API
                # decide search labels. Use a local variable to avoid accidentally
                # shadowing the outer-scope parameter inside this nested function
                # (which would make Python treat it as local and cause
                # UnboundLocalError when referenced before assignment).
                card_to_use = card_for_replace if card_for_replace is not None else full

                eff_include = include_yotoicons if include_yotoicons is not None else True
                eff_max_searches = max_searches if max_searches is not None else 3

                logger.debug("Calling replace_card_default_icons in thread")
                new_card = await asyncio.to_thread(
                    api.replace_card_default_icons,
                    card_to_use,
                    progress_callback=_set_badge,
                    cancel_event=cancel_event,
                    include_yotoicons=eff_include,
                    max_searches=eff_max_searches,
                )
                logger.debug("replace_card_default_icons returned")
                page.update_card(new_card)
                page.pop_dialog()
                page.show_card_details(new_card)

            except Exception as ex:
                page.show_snack(f"Replace icons failed: {ex}", error=True)
                logger.exception("replace_icons error")
            finally:
                _set_badge("", 0.0, visible=False)

        logger.debug("Scheduling background replace icons work on event loop")
        page.run_task(work)
    except Exception as e:
        page.show_snack(f"Failed to start background replace: {e}", error=True)
        logger.exception("start_replace_icons_background error")
