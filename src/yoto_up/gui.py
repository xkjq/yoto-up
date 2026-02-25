from colorlog import log
from yoto_up.models import Card
import asyncio
import os
import tempfile
from pathlib import Path
import platform
import sys

from yoto_up.paths import (
    UI_STATE_FILE as UI_STATE_PATH,
    FLET_APP_STORAGE_DATA,
    TOKENS_FILE,
    atomic_write,
    ensure_parents,
    _BASE_DATA_DIR,
    _BASE_CONFIG_DIR,
)

from yoto_up.yoto_app.ui_state import set_state, get_state,remove_state_file, get_state_path
from yoto_up.yoto_app.card_details import make_show_card_details
from yoto_up.yoto_app.icon_replace_dialog import IconReplaceDialog

import importlib.util
from typing import cast, Any
import traceback
import json
import threading

import flet as ft

# from flet.auth import OAuthProvider
from yoto_up.yoto_app import utils as utils_mod
from yoto_up.yoto_app import ui_helpers as ui_helpers
from yoto_up.yoto_app import auth as auth_mod
from yoto_up.yoto_app import config as yoto_config
from yoto_up.yoto_app.api_manager import ensure_api
from yoto_up.yoto_app.playlists import build_playlists_panel
from loguru import logger
from yoto_up.yoto_app.upload_tasks import (
 UploadManager,
)
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR
from yoto_up import paths as paths_mod
import hashlib

from yoto_up.yoto_app.icon_browser import build_icon_browser_panel
from yoto_up.yoto_app.pixel_art_editor import PixelArtEditor
from yoto_up.yoto_app.covers import build_covers_panel
from yoto_up.yoto_app.about_dialog import show_about_dialog
import subprocess
import shutil

from yoto_up.yoto_app.startup import HAS_SIMPLEAUDIO

INTRO_OUTRO_DIALOG = None

# ft.context.disable_auto_update()

AUTHENTICATE_TEXT = """Not authenticated.

To authenticate with your Yoto account:

1. Click the "Authenticate" button.
2. A code and URL will be displayed. Open the URL in your web browser.
3. Enter the code and complete the authentication process.
"""

def main(page):
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message}", enqueue=True, catch=True)
    logger.debug("Starting Yoto Up GUI")
    page.title = "Yoto Up"

    page.cards: list[Card] = []

    # Shared runtime state
    # Shared API instance (so Fetch Playlists can reuse it)
    api_ref = {"api": None}

    page.api_ref = api_ref  # expose on page for easy access from helpers   
    page.fetch_playlists_sync = None  # will be set by playlists builder; exposed here for auth flow to trigger a refresh after login

    page.selected_playlist_ids = set()  # exposed on page for easy access from playlist row callbacks

    # Basic UI controls that many helper functions expect. These are
    # intentionally minimal so we can restore behavior incrementally.
    # client_id = ft.TextField(label="Client ID", value="RslORm04nKbhf04qb91r2Pxwjsn3Hnd5", width=400, disabled=True)
    auth_btn = ft.Button("Authenticate")
    status = ft.Text("")
    page.status = status  # expose on page for easy access from helpers
    auth_instructions = ft.Column([ft.Text(AUTHENTICATE_TEXT)])

    def show_snack(message: str, error: bool = False, duration: int | None = None):
        # print(f"[gui] show_snack: {message}")  # Commented out for performance
        bg = ft.Colors.RED if error else None
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=bg, duration=duration)
        page.show_dialog(page.snack_bar)
        try:
            page.update()
        except AssertionError:
            logger.error("Failed to update page after showing snack: %s", traceback.format_exc())
            # Flet may raise AssertionError if a control list contains
            # invalid entries (None or non-Control). If the playlists module
            # exposed a cleaner, call it and retry once.
            try:
                cleaner = getattr(page, "clean_ui", None)
                if callable(cleaner):
                    cleaner()
            except Exception:
                logger.error("Failed to clean UI after showing snack: %s", traceback.format_exc())
            try:
                page.update()
            except Exception:
                logger.error("Failed to update page after showing snack: %s", traceback.format_exc())

    page.show_snack = show_snack  # expose on page for easy access from helpers


    def start_device_auth(e, instr=None):
        logger.debug("[start_device_auth] Starting device auth flow")
        # Prefer using the YotoAPI device auth flow directly (so we reuse
        # YotoAPI.get_device_code() and poll_for_token()). Fall back to the
        # existing auth module on any error.
        api = ensure_api(api_ref)
        try:
            device_info = api.get_device_code()
        except Exception as e:
            # If YotoAPI can't get a device code, fallback to auth_mod
            raise

        verification_uri = device_info.get("verification_uri") or ""
        verification_uri_complete = (
            device_info.get("verification_uri_complete") or verification_uri
        )
        user_code = device_info.get("user_code") or ""

        # Populate instructions in the provided container (or page.auth_instructions)
        try:
            container = instr or auth_instructions
            if container is not None:
                container.controls.clear()
                container.controls.append(
                    ft.Text(
                        f"Visit: {verification_uri} and enter the code displayed below.",
                        selectable=True,
                    )
                )
                container.controls.append(
                    ft.Text(f"Code: {user_code}", selectable=True)
                )
                container.controls.append(
                    ft.Row(
                        [
                            ft.Text("Alternatively open (click) this direct link: "),
                            ft.TextButton(
                                verification_uri_complete,
                                on_click=lambda e, url=verification_uri_complete: (
                                    __import__("webbrowser").open(url)
                                ),
                            ),
                        ]
                    )
                )
                container.controls.append(
                    ft.Row(
                        [
                            ft.Text("Doing this links you Yoto account with this app."),
                            ft.Text(""),
                        ]
                    )
                )
                container.controls.append(getattr(page, "auth_status", ft.Text("")))
                page.update()
        except Exception:
            pass

        # Start background poll using YotoAPI.poll_for_token
        def _poll_thread():
            try:
                access, refresh = api.poll_for_token(
                    device_info.get("device_code"),
                    device_info.get("interval", 5),
                    device_info.get("expires_in", 300),
                )
                try:
                    api.save_tokens(access, refresh)
                except Exception:
                    # best-effort save into centralized TOKENS_FILE
                    try:
                        ensure_parents(TOKENS_FILE)
                        atomic_write(
                            TOKENS_FILE,
                            json.dumps(
                                {"access_token": access, "refresh_token": refresh}
                            ),
                            text_mode=True,
                        )
                    except Exception:
                        pass
                api.access_token = access
                api.refresh_token = refresh
                api_ref["api"] = api
                show_snack("Authenticated")
                try:
                    page.auth_complete()
                except Exception:
                    pass
                try:
                    # update instruction UI
                    if instr is not None and hasattr(instr, "controls"):
                        instr.controls.clear()
                        instr.controls.append(
                            ft.Text(
                                "Authentication complete",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREEN,
                            )
                        )
                        page.update()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"start_device_auth: auth failed: {e}")
                show_snack(f"Auth failed: {e}", error=True)

        threading.Thread(target=_poll_thread, daemon=True).start()


    page.show_card_details = make_show_card_details(
            page=page,
            Card=Card,
            IconReplaceDialog=IconReplaceDialog,
        )


    logger.debug("Building playlists panel")
    playlists_ui = build_playlists_panel(
        page,
    )
    # extract controls and helpers
    playlists_column = playlists_ui["playlists_column"]
    logger.debug("Playlists panel built")

    logger.debug("Building upload manager")
    page.upload_manager = UploadManager(page, api_ref, show_snack)
    logger.debug("Upload manager built")

    # Run the auth starter in a background thread so the UI remains responsive
    def _auth_click(e):
        print("[gui] Authenticate button clicked")
        status.value = "Starting authentication..."
        # show preparing text in the embedded instructions area
        auth_instructions.controls.clear()
        auth_instructions.controls.append(ft.Text("Preparing authentication..."))
        page.update()

        # Prefer browser OAuth via Flet when possible (works for web and desktop)

        def on_login(evt):
            logger.debug(
                f"[on_login] evt: {evt}; page.auth: {getattr(page, 'auth', None)}"
            )
            # evt is a LoginEvent
            if getattr(evt, "error", None):
                show_snack(f"Login error: {evt.error}", error=True)
                status.value = f"Login error: {evt.error}"
                page.update()
                return

            token = page.auth.token
            access = getattr(token, "access_token", None)
            refresh = getattr(token, "refresh_token", None)
            if access:
                # Persist tokens.json
                tmp = {"access_token": access, "refresh_token": refresh}
                try:
                    ensure_parents(TOKENS_FILE)
                    atomic_write(TOKENS_FILE, json.dumps(tmp))
                except Exception:
                    pass
                # Initialize API with saved tokens
                try:
                    api = ensure_api(api_ref)
                    api.access_token = access
                    api.refresh_token = refresh
                    api_ref["api"] = api
                    show_snack("Authenticated")
                    page.auth_complete()
                    auth_instructions.controls.clear()
                    auth_instructions.controls.append(
                        ft.Text(
                            "Authentication complete",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREEN,
                        )
                    )
                    page.update()
                except Exception as e:
                    show_snack(f"Failed to initialize API: {e}", error=True)

        threading.Thread(
            target=lambda: start_device_auth(e, auth_instructions), daemon=True
        ).start()
        logger.debug("[on_auth_click] _auth_click done")

    auth_btn.on_click = _auth_click

    def reset_auth_gui(e, reauth: bool = False):
        """Show confirmation, then perform token reset while disabling the reset buttons.

        Runs the actual work in a background thread so the UI remains responsive.
        """
        # Background worker that performs the reset and optionally reauths

        # Confirmation dialog handlers
        dlg = ft.AlertDialog(
            title=ft.Text("Confirm Reset Authentication"),
            content=ft.Text(
                f"This will remove saved authentication tokens ({TOKENS_FILE.name}) and sign out. Continue?"
            ),
            actions=[],
        )

        def _cancel(ev):
            try:
                page.pop_dialog()
            except Exception:
                pass

        def _confirm(ev):
            try:
                page.pop_dialog()
            except Exception:
                pass
            api = ensure_api(api_ref)  # ensure api_ref has an API instance
            api.reset_auth()
            invalidate_authentication()
            if reauth:
                # Start re-authentication in a background thread
                threading.Thread(
                    target=lambda: start_device_auth(None), daemon=True
                ).start()

            # threading.Thread(target=_do_reset, daemon=True).start()

        dlg.actions = [
            ft.TextButton("Cancel", on_click=_cancel),
            ft.TextButton("Confirm", on_click=_confirm),
        ]

        page.show_dialog(dlg)
        page.update()

    reset_btn = ft.TextButton(
        "Reset Auth", on_click=lambda e: reset_auth_gui(e, reauth=False)
    )
    reset_and_reauth_btn = ft.TextButton(
        "Reset & Reauth", on_click=lambda e: reset_auth_gui(e, reauth=True)
    )

    def clear_all_user_data_gui(e=None):
        """Show confirmation and clear local user data (tokens, ui state, caches, icon caches, versions)."""
        try:
            import yoto_up.paths as paths_mod
        except Exception:
            paths_mod = None

        dlg = ft.AlertDialog(
            title=ft.Text("Confirm Clear All User Data"),
            content=ft.Text(
                "This will DELETE local tokens, UI state, caches, icon caches and saved versions. This cannot be undone. Continue?"
            ),
            actions=[],
        )

        def _cancel(ev=None):
            try:
                page.pop_dialog()
            except Exception:
                pass

        def _confirm(ev=None):
            try:
                page.pop_dialog()
            except Exception:
                pass

            def _worker():
                removed = {"files": [], "dirs": [], "errors": []}
                try:
                    # tokens and ui state
                    try:
                        if TOKENS_FILE and Path(TOKENS_FILE).exists():
                            Path(TOKENS_FILE).unlink()
                            removed["files"].append(str(TOKENS_FILE))
                    except Exception as ex:
                        removed["errors"].append(f"tokens: {ex}")
                    try:
                        # Use ui_state helper to remove persisted UI state
                        try:
                            remove_state_file()
                            removed["files"].append(str(get_state_path()))
                        except Exception as ex:
                            removed["errors"].append(f"ui_state: {ex}")
                    except Exception as ex:
                        removed["errors"].append(f"ui_state: {ex}")

                    # other paths from paths_mod if available
                    if paths_mod:
                        for p in (
                            getattr(paths_mod, "UPLOAD_ICON_CACHE_FILE", None),
                            getattr(paths_mod, "API_CACHE_FILE", None),
                        ):
                            try:
                                if p and Path(p).exists():
                                    Path(p).unlink()
                                    removed["files"].append(str(p))
                            except Exception as ex:
                                removed["errors"].append(f"file {p}: {ex}")
                        for d in (
                            getattr(paths_mod, "OFFICIAL_ICON_CACHE_DIR", None),
                            getattr(paths_mod, "YOTOICONS_CACHE_DIR", None),
                            getattr(paths_mod, "VERSIONS_DIR", None),
                        ):
                            try:
                                if d and Path(d).exists():
                                    shutil.rmtree(d)
                                    removed["dirs"].append(str(d))
                            except Exception as ex:
                                removed["errors"].append(f"dir {d}: {ex}")

                except Exception as ex:
                    removed["errors"].append(str(ex))

                # post-delete UI updates
                try:
                    invalidate_authentication()
                except Exception:
                    pass
                try:
                    clear_queue()
                except Exception:
                    pass

                summary = []
                for r in removed["files"]:
                    summary.append(f"file: {r}")
                for r in removed["dirs"]:
                    summary.append(f"dir: {r}")
                for err in removed["errors"]:
                    summary.append(f"ERROR: {err}")
                msg = (
                    "Cleared user data"
                    if not removed["errors"]
                    else "Cleared user data (with errors)"
                )
                try:
                    show_snack(msg)
                except Exception:
                    pass
                # also log/print a short summary
                try:
                    for line in summary[:10]:
                        print(line)
                except Exception:
                    pass

            threading.Thread(target=_worker, daemon=True).start()

        dlg.actions = [
            ft.TextButton("Cancel", on_click=_cancel),
            ft.TextButton("Confirm", on_click=_confirm),
        ]
        page.show_dialog(dlg)
        page.update()

    # clear_data_btn removed; Clear action is available from the About dialog

    auth_column = ft.Column(
        [
            ft.Row([auth_btn, reset_btn, reset_and_reauth_btn]),
            ft.Divider(),
            ft.Text("Instructions:"),
            auth_instructions,
        ],
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


    ## Ensure the original header buttons are present in the playlists header
    #try:
    #    header = (
    #        playlists_column.controls[0]
    #        if playlists_column and len(playlists_column.controls) > 0
    #        else None
    #    )
    #    logger.debug(f"Playlists header: {header}")

    #    if header and hasattr(header, "controls"):
    #        try:
    #            hdr = list(header.controls)
    #            existing_texts = [getattr(c, "text", None) for c in hdr]
    #            if "Fetch Playlists" not in existing_texts:
    #                insert_at = 1
    #                # prefer buttons returned from playlists module
    #                hdr[insert_at:insert_at] = [
    #                    playlist_fetch_btn or fetch_btn,
    #                    playlist_multi_select_btn or multi_select_btn,
    #                    playlist_delete_selected_btn or delete_selected_btn,
    #                    playlist_export_selected_btn or export_selected_btn,
    #                ]
    #                header.controls = hdr
    #                logger.debug("[_on_playlists_header_merge] Merged playlist buttons into header")
    #            else:
    #                logger.debug("[_on_playlists_header_merge] Header already contains playlist buttons; skipping merge")
    #        except Exception as e:
    #            logger.error(f"[_on_playlists_header_merge] failed: {e}")
    #    else:
    #        logger.error("[_on_playlists_header_merge] playlists header not found or has no controls")
    #except Exception:
    #    logger.error("Failed to merge header buttons into playlists panel: %s", traceback.format_exc())



    ## Load persisted playlists (if any) and populate the playlists list view
    #try:
    #    logger.debug("Loading persisted playlists")
    #    saved = load_playlists()
    #    logger.debug(f"Loaded persisted playlists: {saved}")
    #    if saved and isinstance(saved, list):
    #        try:
    #            pl_list = (
    #                playlists_ui.get("playlists_list")
    #                if isinstance(playlists_ui, dict)
    #                else None
    #            )
    #            if pl_list and hasattr(pl_list, "controls"):
    #                pl_list.controls.clear()
    #                # Resolve make_playlist_row once to avoid repeated fallback logs
    #                make_row = None
    #                try:
    #                    make_row = (
    #                        playlists_ui.get("make_playlist_row")
    #                        if isinstance(playlists_ui, dict)
    #                        else None
    #                    )
    #                except Exception:
    #                    make_row = None
    #                # If playlists_ui did not provide a row builder, we'll fall back
    #                # to a simple ListTile per-item. Do not try to import the nested
    #                # `make_playlist_row` from the module (it's local to the builder).
    #                if not callable(make_row):
    #                    make_row = None
    #                if not callable(make_row):
    #                    logger.debug(
    #                        "No make_playlist_row function available in playlists_ui; using fallback ListTile"
    #                    )

    #                for idx, item in enumerate(saved):
    #                    try:
    #                        if callable(make_row):
    #                            try:
    #                                row = make_row(item, idx=idx)
    #                            except Exception:
    #                                row = None
    #                            # Only append a valid Control; otherwise fall back
    #                            if row is not None and isinstance(row, ft.Control):
    #                                pl_list.controls.append(row)
    #                            else:
    #                                title = (
    #                                    item.get("title", "")
    #                                    if isinstance(item, dict)
    #                                    else str(item)
    #                                )
    #                                cid = (
    #                                    item.get("cardId", "")
    #                                    if isinstance(item, dict)
    #                                    else ""
    #                                )
    #                                pl_list.controls.append(
    #                                    ft.ListTile(
    #                                        title=ft.Text(title),
    #                                        subtitle=ft.Text(str(cid)),
    #                                    )
    #                                )
    #                        else:
    #                            # fallback: render a simple ListTile
    #                            title = (
    #                                item.get("title", "")
    #                                if isinstance(item, dict)
    #                                else str(item)
    #                            )
    #                            cid = (
    #                                item.get("cardId", "")
    #                                if isinstance(item, dict)
    #                                else ""
    #                            )
    #                            pl_list.controls.append(
    #                                ft.ListTile(
    #                                    title=ft.Text(title), subtitle=ft.Text(str(cid))
    #                                )
    #                            )
    #                    except Exception:
    #                        try:
    #                            pl_list.controls.append(
    #                                ft.ListTile(title=ft.Text(str(item)))
    #                            )
    #                        except Exception:
    #                            pass
    #                page.update()
    #                logger.debug("Persisted playlists loaded and UI updated")
    #        except Exception:
    #            logger.error(f"Failed to populate playlists list: {traceback.format_exc()}")
    #except Exception:
    #    logger.error(f"Failed to load persisted playlists: {traceback.format_exc()}")

    #logger.debug("Persisted playlists loaded")

    
    # Add About button to the top right
    about_btn = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE,
        tooltip="About Yoto Up",
        on_click=lambda: show_about_dialog(
            page=page,
            api_ref=api_ref,
            show_snack=show_snack,
            clear_all_user_data_gui=clear_all_user_data_gui,
        ),
        style=ft.ButtonStyle(color=ft.Colors.BLUE),
    )

    # Small badge to indicate background icon cache refresh activity.
    icon_refresh_badge_text = ft.Text(
        "Updating icon cache...", size=12, color=ft.Colors.ORANGE
    )
    icon_refresh_badge = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.CACHED, color=ft.Colors.ORANGE), icon_refresh_badge_text],
            spacing=6,
        ),
        padding=6,
        border_radius=6,
        bgcolor=ft.Colors.YELLOW_50,
        visible=False,
    )

    # Small autoselect progress badge (smaller than icon_refresh_badge)
    autoselect_badge_text = ft.Text("", size=11, color=ft.Colors.BLUE)
    autoselect_badge = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.REFRESH, color=ft.Colors.BLUE), autoselect_badge_text],
            spacing=4,
        ),
        padding=4,
        border_radius=6,
        bgcolor=ft.Colors.WHITE,
        visible=False,
    )

    # Default tooltip and click handler: click should reopen the autoselect status dialog
    try:
        autoselect_badge.tooltip = "Selecting icons"
    except Exception:
        logger.error("Failed to set tooltip on autoselect badge: %s", traceback.format_exc())

    def _on_autoselect_click(e=None):
        try:
            cancel = getattr(page, "autoselect_cancel_event", None)
            try:
                page.open_autoselect_status_dialog(cancel)
            except Exception:
                # fallback: call without cancel event
                try:
                    page.open_autoselect_status_dialog(None)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        autoselect_badge.on_click = _on_autoselect_click
    except Exception:
        pass

    # Default: dialog opens when autoselect starts unless this flag is set
    page.autoselect_hide_dialog_default = False

    def set_autoselect_progress(
        msg: str | None, frac: float | None = None, visible: bool = True
    ):
        try:
            if not visible:
                autoselect_badge.visible = False
                page.update()
                return
            autoselect_badge.visible = True
            # Build the visible badge text: always show 'Selecting Icons' and a pct if available
            if frac is not None:
                try:
                    pct = int(frac * 100)
                    label = f"{pct}%"
                except Exception:
                    label = ""
            else:
                label = ""
            if label:
                autoselect_badge_text.value = f"Selecting Icons {label}"
            else:
                autoselect_badge_text.value = "Selecting Icons"

            # Set the tooltip to the more-detailed message (e.g. which icon is being searched)
            try:
                if msg:
                    autoselect_badge.tooltip = msg
                else:
                    autoselect_badge.tooltip = "Selecting icons"
            except Exception:
                pass

            # Also update the status text control and detail control in the dialog if they're open
            try:
                ctrl = getattr(page, "autoselect_status_ctrl", None)
                if ctrl is not None:
                    try:
                        ctrl.value = autoselect_badge_text.value
                    except Exception:
                        pass
                detail = getattr(page, "autoselect_status_detail", None)
                if detail is not None:
                    try:
                        # detail shows the more verbose message about the current icon/search
                        detail.value = msg or ""
                    except Exception:
                        pass
            except Exception:
                pass
            page.update()
        except Exception:
            pass

    def open_autoselect_status_dialog(cancel_event: threading.Event | None = None):
        try:
            hide_checkbox = ft.Checkbox(
                label="Hide this dialog by default",
                value=page.autoselect_hide_dialog_default,
            )

            def on_hide_change(e):
                try:
                    page.autoselect_hide_dialog_default = bool(hide_checkbox.value)
                except Exception:
                    pass

            hide_checkbox.on_select = on_hide_change

            status_txt = ft.Text(autoselect_badge_text.value or "Autoselect running...")
            # Keep a reference on the page so the progress updater can refresh this control
            try:
                page.autoselect_status_ctrl = status_txt
            except Exception:
                pass

            # A secondary detail control shows verbose info about the current icon/search
            detail_txt = ft.Text("", size=12)
            try:
                page.autoselect_status_detail = detail_txt
            except Exception:
                pass

            # Use a fixed width column so the dialog doesn't constantly resize
            content_col = ft.Column(
                [status_txt, detail_txt, hide_checkbox],
                width=480,
                scroll=ft.ScrollMode.AUTO,
            )

            dlg = ft.AlertDialog(
                title=ft.Text("Autoselect status"),
                content=content_col,
                actions=[
                    ft.TextButton(
                        "Cancel",
                        on_click=lambda e: (
                            cancel_event.set() if cancel_event else None,
                            page.pop_dialog(),
                        ),
                    ),
                    ft.TextButton("Close", on_click=lambda e: page.pop_dialog()),
                ],
            )
            page.show_dialog(dlg)
            page.update()
        except Exception:
            pass

    # Expose helpers on page so other modules can control autoselect UI
    page.set_autoselect_progress = set_autoselect_progress
    page.open_autoselect_status_dialog = open_autoselect_status_dialog

    def set_icon_refreshing(flag: bool, message: str | None = None):
        try:
            icon_refresh_badge.visible = bool(flag)
            if message is not None:
                try:
                    icon_refresh_badge_text.value = message
                except Exception:
                    pass
            page.update()
        except Exception:
            pass

    # Expose setter on page so other modules (icon_browser) can toggle the badge
    page.set_icon_refreshing = set_icon_refreshing

    def get_cached_cover(url_or_field: str) -> str | None:
        """
        Given a remote cover URL (http/https) or a local path, ensure it's cached
        under OFFICIAL_ICON_CACHE_DIR / 'covers' and return a path suitable for
        use as an ft.Image.src (a local file path or the original URL if caching
        failed).
        """
        try:
            if not url_or_field:
                return None
            s = str(url_or_field)
            # If it's a local file path, return as-is
            if s.startswith("file://"):
                return s
            if not s.startswith("http://") and not s.startswith("https://"):
                # assume local path
                p = Path(s)
                if p.exists():
                    return str(p)
                return None

            # Remote URL: cache under OFFICIAL_ICON_CACHE_DIR/covers
            try:
                cache_dir = Path(OFFICIAL_ICON_CACHE_DIR) / "covers"
                cache_dir.mkdir(parents=True, exist_ok=True)
                url_hash = hashlib.sha256(s.encode()).hexdigest()
                ext = Path(s).suffix or ".png"
                cache_path = cache_dir / f"{url_hash}{ext}"
                if cache_path.exists():
                    return str(cache_path)
                # Download into a temporary file then move
                import tempfile
                import shutil

                tf = tempfile.NamedTemporaryFile(
                    prefix="yoto_cover_", suffix=ext, delete=False
                )
                try:
                    # Use Python's urllib to avoid adding httpx dependency at import
                    try:
                        import urllib.request

                        urllib.request.urlretrieve(s, tf.name)
                    except Exception:
                        # fallback to requests via httpx if available
                        try:
                            import httpx

                            resp = httpx.get(s)
                            resp.raise_for_status()
                            tf.close()
                            with open(tf.name, "wb") as fh:
                                fh.write(resp.content)
                        except Exception:
                            tf.close()
                            return s
                    tf.close()
                    try:
                        shutil.move(tf.name, cache_path)
                    except Exception:
                        try:
                            shutil.copy(tf.name, cache_path)
                        except Exception:
                            pass
                finally:
                    try:
                        if Path(tf.name).exists():
                            Path(tf.name).unlink()
                    except Exception:
                        pass
                if cache_path.exists():
                    return str(cache_path)
                return s
            except Exception:
                return s
        except Exception:
            return None

    # expose on page for other modules
    page.get_cached_cover = get_cached_cover

    logger.debug("Building icon browser panel")
    # Create tabs and keep a reference so we can enable/disable them
    # Build icon browser panel and add as a tab
    icon_browser_ui = build_icon_browser_panel(
        page=page, api_ref=api_ref, ensure_api=ensure_api, show_snack=show_snack
    )
    icon_panel = (
        icon_browser_ui.get("panel") if isinstance(icon_browser_ui, dict) else None
    )
    logger.debug("Icon browser panel built")

    # Build covers panel
    #logger.debug("Building covers panel")   
    #covers_ui = build_covers_panel(page=page, show_snack=show_snack)
    #covers_panel = covers_ui.get("panel") if isinstance(covers_ui, dict) else None
    #logger.debug("Covers panel built")


    logger.debug("Building pixel editor panel")
    editor = PixelArtEditor(page=page)
    # editor_tab = editor.as_tab("Editor") or editor.as_tab("Icon Editor")
    # keep a reference on the page for external callers if needed
    page.pixel_editor = editor
    editor_content = editor.control()
    logger.debug("Pixel editor panel built")

    # Ensure all content is visible
    auth_column.visible = True
    playlists_column.visible = True
    page.upload_manager.column.visible = True
    if hasattr(icon_panel, "visible"):
        icon_panel.visible = True
    #if hasattr(covers_panel, "visible"):
    #    covers_panel.visible = True

    # Create tab labels for TabBar
    auth_tab = ft.Tab(label="Auth")
    playlists_tab = ft.Tab(label="Playlists", disabled=True)
    upload_tab = ft.Tab(label="Upload", disabled=True)
    icons_tab = ft.Tab(label="Icons", disabled=True)
    #covers_tab = ft.Tab(label="Covers", disabled=True)
    editor_tab = ft.Tab(label="Editor", disabled=True)

    all_tab_labels = [
        auth_tab,
        playlists_tab,
        upload_tab,
        icons_tab,
        #covers_tab,
        editor_tab,
    ]
    all_tab_content = [
        auth_column,
        playlists_column,
        page.upload_manager.column,
        icon_panel,
        #covers_panel,
        editor_content,
    ]

    # Create Tabs control using Flet 0.80+ API:
    # ft.Tabs(content=ft.Column([ft.TabBar(tabs=[...]), ft.TabBarView(controls=[...])]))
    tabs_control = ft.Tabs(
        selected_index=0,
        length=len(all_tab_labels),
        expand=True,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(tabs=all_tab_labels),
                ft.TabBarView(expand=True, controls=all_tab_content),
            ],
        ),
    )

    # Place About button above tabs
    page.add(
        ft.Row(
            [
                ft.Text("Yoto Up", size=22, weight=ft.FontWeight.BOLD, expand=True),
                ft.Row([icon_refresh_badge, autoselect_badge, about_btn]),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
    )
    logger.debug("Tabs control created and header added")
    page.add(tabs_control)
    logger.debug("Tabs control added to page")


    # Define functions that reference tabs_control after it's created
    def invalidate_authentication():
        """Invalidate authentication: clear API, hide tabs, switch to Auth tab, and update UI."""
        # Clear API instance
        api_ref["api"] = None
        # Disable non-auth tabs - access TabBar from tabs_control.content.controls[0]
        try:
            tab_bar = tabs_control.content.controls[
                0
            ]  # First control in Column is TabBar
            for i in range(1, len(tab_bar.tabs)):
                tab_bar.tabs[i].disabled = True
        except Exception:
            pass
        # Switch to Auth tab
        tabs_control.selected_index = 0
        # Update instructions/status
        auth_instructions.controls.clear()
        auth_instructions.controls.append(
            ft.Text(
                AUTHENTICATE_TEXT,
                size=16,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.RED,
            )
        )
        page.update()

    def switch_to_auth_tab():
        """Switch to the Auth tab (index 0) and update the page."""
        tabs_control.selected_index = 0
        page.update()

    # Assign functions to page so they can be called elsewhere
    page.switch_to_auth_tab = switch_to_auth_tab
    page.invalidate_authentication = invalidate_authentication

    def show_dev_warning(page):
        dlg = ft.AlertDialog(
            title=ft.Text("Yoto Up: In Development"),
            content=ft.Column(
                [
                    ft.Text(
                        "This app is under active development. Features may be incomplete, unstable, or change at any time.\n\nPlease report bugs and use with caution!"
                    ),
                    ft.TextButton(
                        "View on GitHub",
                        url="https://github.com/xkjq/yoto-up",
                        style=ft.ButtonStyle(color=ft.Colors.BLUE),
                    ),
                ]
            ),
            actions=[ft.TextButton("OK", on_click=lambda e: page.pop_dialog())],
        )
        page.show_dialog(dlg)
        page.update()

    logger.debug("Showing development warning dialog")
    show_dev_warning(page)

    def auth_complete():
        logger.debug("Auth complete")
        # Enable all tabs - access TabBar from tabs_control.content.controls[0]
        try:
            tab_bar = tabs_control.content.controls[
                0
            ]  # First control in Column is TabBar
            for i in range(1, len(tab_bar.tabs)):
                tab_bar.tabs[i].disabled = False
        except Exception:
            pass

        api = api_ref.get("api")
        if api:
            # Run icon cache refresh in a background thread so the UI doesn't hang.
            def _refresh_icons_bg():
                try:
                    try:
                        if hasattr(page, "set_icon_refreshing"):
                            page.set_icon_refreshing(True, "Refreshing icon caches...")
                    except Exception:
                        pass
                    try:
                        api.get_public_icons(show_in_console=False)
                    except Exception as e:
                        logger.exception(f"get_public_icons failed: {e}")
                    try:
                        api.get_user_icons(show_in_console=False)
                    except Exception as e:
                        logger.exception(f"get_user_icons failed: {e}")
                finally:
                    try:
                        if hasattr(page, "set_icon_refreshing"):
                            page.set_icon_refreshing(False)
                    except Exception:
                        pass
                # Notify any icon browser listeners that the cache refresh finished
                try:
                    cbs = getattr(page, "icon_cache_refreshed_callbacks", None)
                    if cbs:
                        for cb in list(cbs):
                            try:
                                cb()
                            except Exception:
                                pass
                except Exception:
                    pass

            threading.Thread(target=_refresh_icons_bg, daemon=True).start()
        # Always use the local page variable, not the argument
        page.update()

    page.auth_complete = auth_complete

    # Now that the UI controls are added to the page, try to reuse tokens.json (if present)
    try:
        logger.debug("Checking for existing tokens...")
        api = ensure_api(api_ref)

        logger.debug("Checking for existing tokens...")
        logger.debug(f"api: {api}")

        if api and api.is_authenticated():
            show_snack("Authenticated (from existing tokens)", error=False)
            auth_instructions.controls.clear()
            auth_instructions.controls.extend(
                [
                    ft.Text(
                        "Authenticated (from existing tokens)",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREEN,
                    ),
                    ft.Text(api.TOKEN_FILE, size=10),
                ]
            )
            auth_complete()
            page.update()
    except Exception as e:
        logger.error(f"Failed while attempting to initialize API from tokens.json: {e}")


def start_gui():
    ft.run(main)


if __name__ == "__main__":
    start_gui()
