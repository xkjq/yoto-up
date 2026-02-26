from nltk.lm.vocabulary import _
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
from yoto_up.yoto_app.playlists import build_playlists_panel, build_playlists_ui
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
ENABLE_ICON_BROWSER = False

# ft.context.disable_auto_update()

AUTHENTICATE_TEXT = """Not authenticated.

To authenticate with your Yoto account:

1. Click the "Authenticate" button.
2. A code and URL will be displayed. Open the URL in your web browser.
3. Enter the code and complete the authentication process.
"""

def main(page: ft.Page):
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message}", enqueue=True, catch=True)
    logger.debug("Starting Yoto Up GUI")
    page.title = "Yoto Up"

    page.cards: list[Card] = []

    def update_local_card_cache(card: Card, refresh_ui: bool = True):
        # Update the local cache of cards on the page object. This is used by various helpers to avoid refetching cards from the API.
        try:
            existing = next((c for c in page.cards if c.id == card.id), None)
            if existing:
                page.cards.remove(existing)
            page.cards.append(card)
            if refresh_ui:
                build_playlists_ui(page)
        except Exception:
            logger.error(f"Failed to update local card cache: {traceback.format_exc()}")

    page.update_local_card_cache = update_local_card_cache  # expose on page for easy access from helpers

    api_ref = {"api": None}

    page.api_ref = api_ref  # expose on page for easy access from helpers   


    def get_api():
        return ensure_api(api_ref)

    page.get_api = get_api


    def update_card(card: Card) -> None:
        """
        Generic helper to perform an API update of a card and refresh the local cache and UI. This is used by various helpers after making changes to a card to persist those changes and update the UI.
        """
        try:
            api = get_api()
            updated = api.update_card(card, return_card_model=True)
            update_local_card_cache(updated)
            build_playlists_ui(page)
        except Exception as ex:
            logger.error(f"Failed to update card: {ex}")
            page.show_snack(f"Failed to update card: {ex}", error=True)
            return None

    page.update_card = update_card  # expose on page for easy access from helpers

    page.fetch_playlists_sync = None  # will be set by playlists builder; exposed here for auth flow to trigger a refresh after login
    page.fetch_playlists = None  # async version; exposed here for auth flow to trigger a refresh after login

    page.selected_playlist_ids = set()  # exposed on page for easy access from playlist row callbacks

    # Basic UI controls that many helper functions expect. These are
    # intentionally minimal so we can restore behavior incrementally.
    # client_id = ft.TextField(label="Client ID", value="RslORm04nKbhf04qb91r2Pxwjsn3Hnd5", width=400, disabled=True)
    auth_btn = ft.TextButton(content=ft.Text(value="Authenticate"))
    status = ft.Text(value="")
    page.status = status  # expose on page for easy access from helpers
    auth_instructions = ft.Column(controls=[ft.Text(value=AUTHENTICATE_TEXT)])

    def show_snack(message: str, error: bool = False, duration: int = 3000):
        # print(f"[gui] show_snack: {message}")  # Commented out for performance
        bg = ft.Colors.RED if error else None
        page.snack_bar = ft.SnackBar(content=ft.Text(value=message), bgcolor=bg, duration=duration)
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


    async def start_device_auth(instr=None):
        logger.debug("[start_device_auth] Starting device auth flow")
        # Prefer using the YotoAPI device auth flow directly (so we reuse
        # YotoAPI.get_device_code() and poll_for_token()). Fall back to the
        # existing auth module on any error.
        api = get_api()
        if api is None:
            logger.error("start_device_auth: API instance not available")
            show_snack("API unavailable; cannot start authentication", error=True)
            return
        device_info = api.get_device_code()

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
                    ft.Text(value=f"Visit: {verification_uri} and enter the code displayed below.", selectable=True)
                )
                container.controls.append(ft.Text(value=f"Code: {user_code}", selectable=True))
                container.controls.append(
                    ft.Row(
                        controls=[
                            ft.Text(value="Alternatively open (click) this direct link: "),
                            ft.TextButton(
                                content=ft.Text(value=verification_uri_complete),
                                on_click=lambda e, url=verification_uri_complete: (
                                    logger.debug(f"Opening browser for URL: {url}"),
                                    __import__("webbrowser").open(url),
                                ),
                            ),
                            ft.TextButton(content=ft.Text(value="Copy Link"), on_click=lambda e, url=verification_uri_complete: (
                                logger.debug(f"Copying URL to clipboard: {url}"),
                                ft.Clipboard().set(url),
                            )),
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
            logger.error(f"Failed to populate auth instructions: {traceback.format_exc()}")

        # Start background poll using YotoAPI.poll_for_token
        def _poll_thread():
            try:
                access, refresh = api.poll_for_token(
                    device_info.get("device_code"),
                    device_info.get("interval", 5),
                    device_info.get("expires_in", 300),
                )
                api.save_tokens(access, refresh)
                api.access_token = access
                api.refresh_token = refresh
                api_ref["api"] = api
                show_snack("Authenticated")
                page.auth_complete()
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
                except Exception:
                    logger.error(f"Failed to update auth instructions after successful auth: {traceback.format_exc()}")
            except Exception as e:
                logger.error(f"start_device_auth: auth failed: {e}")
                show_snack(f"Auth failed: {e}", error=True)
            finally:
                page.update()

        page.run_thread(_poll_thread)  # also run as a task to ensure exceptions are logged   


    page.show_card_details = make_show_card_details(
            page=page,
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

        page.run_task(start_device_auth, auth_instructions)
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
            api = page.get_api()  # ensure api_ref has an API instance
            api.reset_auth()
            invalidate_authentication()
            if reauth:
                # Start re-authentication in a background thread
                async def _start_reauth():
                    try:
                        await start_device_auth(auth_instructions)
                    except Exception as ex:
                        logger.error(f"Failed to start re-authentication: {ex}")
                        show_snack(f"Failed to start re-authentication: {ex}", error=True)
                page.run_task(_start_reauth)

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

    if ENABLE_ICON_BROWSER:
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
    if ENABLE_ICON_BROWSER and hasattr(icon_panel, "visible"):
        icon_panel.visible = True
    #if hasattr(covers_panel, "visible"):
    #    covers_panel.visible = True

    # Create tab labels for TabBar
    auth_tab = ft.Tab(label="Auth")
    playlists_tab = ft.Tab(label="Playlists", disabled=True)
    upload_tab = ft.Tab(label="Upload", disabled=True)
    if ENABLE_ICON_BROWSER:
        icons_tab = ft.Tab(label="Icons", disabled=True)
    #covers_tab = ft.Tab(label="Covers", disabled=True)
    editor_tab = ft.Tab(label="Editor", disabled=True)

    all_tab_labels = [
        auth_tab,
        playlists_tab,
        upload_tab,
        #covers_tab,
        editor_tab,
    ]
    all_tab_content = [
        auth_column,
        playlists_column,
        page.upload_manager.column,
        #covers_panel,
        editor_content,
    ]
    if ENABLE_ICON_BROWSER:
        all_tab_labels.append(icons_tab)
        all_tab_content.append(icon_panel)

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

    def auth_complete():
        logger.debug("Auth complete")
        # Enable all tabs - access TabBar from tabs_control.content.controls[0]
        tab_bar = tabs_control.content.controls[
            0
        ]  # First control in Column is TabBar
        for i in range(1, len(tab_bar.tabs)):
            tab_bar.tabs[i].disabled = False

        api = page.get_api()

        if api:
            # Run icon cache refresh in a background thread so the UI doesn't hang.
            async def _refresh_icons_bg():
                logger.debug("Refreshing icon caches (in background thread)...")
                try:
                    if hasattr(page, "set_icon_refreshing"):
                        page.set_icon_refreshing(True, "Refreshing icon caches...")
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
                    except Exception as e:
                        logger.error("Failed to hide icon refreshing badge: %s", traceback.format_exc())
                # Notify any icon browser listeners that the cache refresh finished
                cbs = getattr(page, "icon_cache_refreshed_callbacks", None)
                if cbs:
                    for cb in list(cbs):
                        try:
                            cb()
                        except Exception as e:
                            logger.error("Icon cache refreshed callback failed: %s", traceback.format_exc())

            page.run_task(_refresh_icons_bg)

    page.auth_complete = auth_complete

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


    # Now that the UI controls are added to the page, try to reuse tokens.json (if present)
    logger.debug("Checking for existing tokens...")
    api = page.get_api()

    logger.debug("Checking for existing tokens...")
    logger.debug(f"api: {api}")

    if api and api.is_authenticated():
        logger.debug("Authenticated (from existing tokens)")
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
                ft.Text(str(api.TOKEN_FILE), size=10),
            ]
        )
        auth_complete()
        page.update()


def start_gui():
    ft.run(main)


if __name__ == "__main__":
    start_gui()
