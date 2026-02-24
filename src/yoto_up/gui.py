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
    load_playlists,
    save_playlists,
    _BASE_DATA_DIR,
    _BASE_CONFIG_DIR,
)

from yoto_up.ui_state import set_state, get_state, save_state, remove_state_file, get_state_path

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
    start_uploads as upload_start,
    stop_uploads as upload_stop,
    FileUploadRow,
)
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR
from yoto_up import paths as paths_mod
import hashlib

from yoto_up.yoto_app.show_waveforms import show_waveforms_popup
from yoto_up.yoto_app.icon_browser import build_icon_browser_panel
from yoto_up.yoto_app.pixel_art_editor import PixelArtEditor
from yoto_up.yoto_app.covers import build_covers_panel
from yoto_up.yoto_app.about_dialog import show_about_dialog
import subprocess
import shutil

from yoto_up.startup import HAS_SIMPLEAUDIO

INTRO_OUTRO_DIALOG = None

# ft.context.disable_auto_update()

AUTHENTICATE_TEXT = """Not authenticated.

To authenticate with your Yoto account:

1. Click the "Authenticate" button.
2. A code and URL will be displayed. Open the URL in your web browser.
3. Enter the code and complete the authentication process.
"""

def main(page):
    logger.debug("Starting Yoto Up GUI")
    page.title = "Yoto Up"
    gain_adjusted_files = {}  # {filepath: {'gain': float, 'temp_path': str or None}}
    waveform_cache = {}

    # --- UI State Persistence (via yoto_up.ui_state) ---
    def save_ui_state():
        sort_dropdown = (
            playlists_ui["sort_dropdown"] if isinstance(playlists_ui, dict) else None
        )
        try:
            set_state("gui", "concurrency", concurrency.value)
            set_state("gui", "strip_leading", strip_leading_checkbox.value)
            set_state("gui", "intro_outro_side", intro_outro_side.value)
            set_state("gui", "intro_outro_seconds", intro_seconds.value)
            set_state("gui", "intro_outro_threshold", similarity_threshold.value)
            set_state("gui", "upload_mode", upload_mode_dropdown.value)
            set_state("gui", "local_norm_enabled", local_norm_checkbox.value)
            set_state("gui", "local_norm_target", local_norm_target.value)
            set_state("gui", "local_norm_batch", local_norm_batch.value)
            set_state(
                "gui", "playlist_sort", sort_dropdown.value if sort_dropdown else None
            )
            save_state()
        except Exception as e:
            logger.error("save_ui_state: %s", e)

    def load_ui_state(playlists_ui):
        try:
            concurrency.value = get_state("gui", "concurrency", concurrency.value)
            strip_leading_checkbox.value = get_state(
                "gui", "strip_leading", strip_leading_checkbox.value
            )
            intro_outro_side.value = get_state(
                "gui", "intro_outro_side", intro_outro_side.value
            )
            intro_seconds.value = get_state(
                "gui", "intro_outro_seconds", intro_seconds.value
            )
            similarity_threshold.value = get_state(
                "gui", "intro_outro_threshold", similarity_threshold.value
            )
            upload_mode_dropdown.value = get_state(
                "gui", "upload_mode", upload_mode_dropdown.value
            )
            local_norm_checkbox.value = get_state(
                "gui", "local_norm_enabled", local_norm_checkbox.value
            )
            local_norm_target.value = get_state(
                "gui", "local_norm_target", local_norm_target.value
            )
            local_norm_batch.value = get_state(
                "gui", "local_norm_batch", local_norm_batch.value
            )
            sort_dropdown = (
                playlists_ui["sort_dropdown"]
                if isinstance(playlists_ui, dict)
                else None
            )
            playlist_sort = get_state("gui", "playlist_sort", None)
            if sort_dropdown and playlist_sort:
                sort_dropdown.value = playlist_sort
                # Also update the current_sort key in the playlists module and refresh
                playlists_ui["current_sort"]["key"] = sort_dropdown.value
        except Exception as e:
            logger.error(f"load_ui_state: failed to load state: {e}")


    # Shared runtime state
    # Counters for overall progress
    total_files = 0
    completed_count = 0
    # Shared API instance (so Fetch Playlists can reuse it)
    api_ref = {"api": None}

    # Basic UI controls that many helper functions expect. These are
    # intentionally minimal so we can restore behavior incrementally.
    # client_id = ft.TextField(label="Client ID", value="RslORm04nKbhf04qb91r2Pxwjsn3Hnd5", width=400, disabled=True)
    auth_btn = ft.Button("Authenticate")
    status = ft.Text("")
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

    overall_bar = ft.ProgressBar(width=400, visible=False)
    overall_text = ft.Text("")
    file_rows_column = ft.Column()

    # File picker and folder controls.
    # On Linux desktop, FilePicker depends on "zenity". If it's missing,
    # Flet may surface a confusing "Unknown control: FilePicker" error.
    _is_linux_desktop = sys.platform.startswith("linux") and not getattr(
        page, "web", False
    )
    try:
        _zenity_missing = _is_linux_desktop and shutil.which("zenity") is None
    except Exception:
        logger.warning("Error checking for zenity; assuming file picker is supported", exc_info=True)
        _zenity_missing = False
    _file_picker_supported = not _zenity_missing
    if not _file_picker_supported:
        logger.warning(
            "Zenity not found; disabling FilePicker dialogs on Linux desktop"
        )

    browse = ft.FilePicker() if _file_picker_supported else None
    browse_files = ft.FilePicker() if _file_picker_supported else None
    # When a folder is chosen we will populate file_rows_column
    folder = ft.TextField(label="Folder", width=400)

    # Upload controls
    concurrency = ft.TextField(
        label="Concurrency", value="4", width=80, on_change=lambda e: save_ui_state()
    )
    strip_leading_checkbox = ft.Checkbox(
        label="Strip leading track numbers",
        value=True,
        tooltip="Remove common leading track number prefixes from filenames (e.g. '01 - ', '1. ', '01)', '001_')",
        on_change=lambda e: save_ui_state(),
    )
    intro_outro_side = ft.Dropdown(
        label="Side",
        value="intro",
        options=[ft.dropdown.Option("intro"), ft.dropdown.Option("outro")],
        width=100,
        on_select=lambda e: save_ui_state(),
    )
    intro_seconds = ft.TextField(
        label="Segment seconds",
        value="10.0",
        width=80,
        on_change=lambda e: save_ui_state(),
    )
    similarity_threshold = ft.TextField(
        label="Similarity threshold",
        value="0.75",
        width=80,
        on_change=lambda e: save_ui_state(),
    )
    upload_target_dropdown = ft.Dropdown(
        label="Upload target",
        value="Create new card",
        options=[
            ft.dropdown.Option("Create new card"),
            ft.dropdown.Option("Add to existing card"),
        ],
    )
    new_card_title = ft.TextField(label="New card title", width=400)

    # Placeholders that will be populated/overwritten by playlists module
    existing_card_dropdown = ft.Dropdown(label="Existing card", options=[])
    existing_card_map = {}

    # Ensure only the relevant upload target control is visible
    try:
        if upload_target_dropdown.value == "Create new card":
            new_card_title.visible = True
            existing_card_dropdown.visible = False
        else:
            new_card_title.visible = False
            existing_card_dropdown.visible = True
    except Exception:
        # conservative defaults
        new_card_title.visible = True
        existing_card_dropdown.visible = False

    def _on_upload_target_change(ev=None):
        try:
            if upload_target_dropdown.value == "Create new card":
                new_card_title.visible = True
                existing_card_dropdown.visible = False
            else:
                new_card_title.visible = False
                existing_card_dropdown.visible = True

                if existing_card_dropdown and hasattr(
                    existing_card_dropdown, "options"
                ):
                    # If switching to existing card, and no options are present, try to fetch playlists
                    if (
                        not existing_card_dropdown.options
                        or len(existing_card_dropdown.options) == 0
                    ) and callable(fetch_playlists_sync):
                        print(
                            "[_on_upload_target_change] existing_card_dropdown empty, calling fetch_playlists_sync to populate"
                        )
                        try:
                            # fetch_playlists_sync may be blocking; run in a thread to avoid blocking the UI
                            threading.Thread(
                                target=lambda: fetch_playlists_sync(None), daemon=True
                            ).start()
                        except Exception as fe:
                            print(
                                f"[_on_upload_target_change] fetch_playlists_sync failed: {fe}"
                            )
            page.update()
        except Exception as exc:
            logger.error(f"[_on_upload_target_change] failed: {exc}")

    upload_target_dropdown.on_select = _on_upload_target_change

    def remove_uploaded_files(ev=None):
        logger.debug("[remove_uploaded_files] Removing uploaded files from the queue")
        file_rows_column.controls = [
            c
            for c in file_rows_column.controls
            if not (
                hasattr(c, "_fileuploadrow")
                and getattr(c._fileuploadrow, "uploaded", False)
            )
        ]
        page.update()

    start_btn = ft.Button("Start Upload")
    stop_btn = ft.Button("Stop Upload", disabled=True)
    fetch_btn = ft.Button("Fetch Playlists")
    multi_select_btn = ft.Button("Select Multiple")
    delete_selected_btn = ft.Button("Delete Selected", disabled=True)
    export_selected_btn = ft.Button("Export Selected", disabled=True)
    remove_uploaded_btn = ft.Button("Remove Uploaded", on_click=remove_uploaded_files)

    ## Add Remove Uploaded button to the UI after the action buttons
    # action_buttons_row = ft.Row([
    #    start_btn, stop_btn, fetch_btn, multi_select_btn, delete_selected_btn, export_selected_btn, remove_uploaded_btn
    # ])
    # page.add(action_buttons_row)

    def update_overall():
        # update overall progress bar when a file completes
        nonlocal completed_count
        # compute total dynamically from the UI rows to avoid relying on a separate counter
        try:
            total = len(
                [
                    r
                    for r in getattr(file_rows_column, "controls", [])
                    if getattr(r, "filename", None)
                ]
            )
        except Exception:
            total = 0
        completed_count += 1
        # guard against divide-by-zero
        overall_bar.value = (completed_count / total) if total else 0
        overall_text.value = f"{completed_count}/{total} completed"
        page.update()

    def clear_queue(ev=None):
        """Clear the UI upload queue and reset counters."""
        nonlocal total_files, completed_count
        try:
            file_rows_column.controls.clear()
        except Exception:
            pass
        total_files = 0
        completed_count = 0
        try:
            overall_bar.visible = False
            overall_bar.value = 0
            overall_text.value = ""
        except Exception:
            pass
        show_snack("Upload queue cleared")
        update_show_waveforms_btn()
        page.update()

    def populate_file_rows(folder_path: str):
        try:
            # Find audio files in the folder
            files = utils_mod.find_audio_files(folder_path)
            # Add only files not already present
            existing = set(
                getattr(row, "filename", None) for row in file_rows_column.controls
            )
            added = 0
            for f in files:
                if f not in existing:
                    try:
                        file_row = FileUploadRow(
                            f, maybe_page=page, maybe_column=file_rows_column
                        )
                        file_rows_column.controls.append(file_row.row)
                    except Exception as e:
                        raise RuntimeError(
                            f"Failed to create FileUploadRow for {f}: {e}"
                        )
                    added += 1
            if added == 0 and files:
                print(
                    "[populate_file_rows] All files from folder already present in upload list."
                )
            if not files:
                file_rows_column.controls.append(
                    ft.Text(f"No audio files found in {folder_path}")
                )
            page.update()
        except Exception:
            logger.error("[populate_file_rows] error")

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

    async def _handle_picked_files(files: list[ft.FilePickerFile] | None):
        if not files:
            return

        logger.debug(f"[_handle_picked_files] picked {len(files)} files")
        if getattr(page, "web", False):
            logger.debug("[_handle_picked_files] running in web mode")
            to_upload: list[ft.FilePickerUploadFile] = []
            for f in files:
                if getattr(f, "name", None):
                    upload_url = page.get_upload_url(f"queue/{f.name}", 60)
                    to_upload.append(ft.FilePickerUploadFile(f.name, upload_url))
            if to_upload and browse_files is not None:
                await browse_files.upload(to_upload)
        else:
            for f in files:
                logger.debug(
                    f"[_handle_picked_files] processing {getattr(f, 'name', '')}"
                )
                path = getattr(f, "path", None)
                if path and not any(
                    getattr(row, "filename", None) == path
                    for row in file_rows_column.controls
                ):
                    file_row = FileUploadRow(
                        path, maybe_page=page, maybe_column=file_rows_column
                    )
                    file_rows_column.controls.append(file_row.row)
        update_show_waveforms_btn()
        page.update()

    def on_upload_file_result(e: ft.FilePickerUploadEvent):
        logger.debug(f"[on_upload_file_result] uploaded {e} ")
        logger.debug(e.progress)

        if e.progress == 1:
            temp_path = f"assets/uploads/queue/{e.file_name}"

            try:
                file_row = FileUploadRow(
                    temp_path, maybe_page=page, maybe_column=file_rows_column
                )
                file_rows_column.controls.append(file_row.row)
            except Exception as _:
                raise RuntimeError(f"Failed to create FileUploadRow for {temp_path}")
            update_show_waveforms_btn()
            page.update()

    if browse_files is not None:
        browse_files.on_upload = on_upload_file_result

    def _require_file_picker() -> bool:
        if _file_picker_supported:
            return True
        show_snack(
            "File dialogs are disabled because 'zenity' is not installed. "
            "On Ubuntu/Debian: sudo apt-get install zenity",
            error=True,
            duration=12000,
        )
        return False

    async def _open_folder_picker(_e=None):
        if not _require_file_picker() or browse is None:
            return
        selected_dir = await browse.get_directory_path()
        if selected_dir:
            folder.value = selected_dir
            try:
                populate_file_rows(folder.value)
            except Exception:
                logger.error("_open_folder_picker: populate_file_rows failed", None)
            update_show_waveforms_btn()
            page.update()

    async def _open_files_picker(_e=None):
        if not _require_file_picker() or browse_files is None:
            return
        files = await browse_files.pick_files(allow_multiple=True)
        await _handle_picked_files(files)

    # When the folder TextField is changed (user pastes or types a path), update the file list immediately
    def _on_folder_change(ev=None):
        try:
            if folder.value:
                populate_file_rows(folder.value)
        except Exception as exc:
            logger.error("_on_folder_change: populate_file_rows failed", exc)

    folder.on_change = _on_folder_change

    def run_coro_in_thread(coro, *args):
        """Run an async coroutine in a fresh event loop inside a daemon thread."""

        def _runner():
            try:
                asyncio.run(coro(*args))
            except Exception as exc:
                print("Background task error:", exc)

        threading.Thread(target=_runner, daemon=True).start()

    # Playlists page (moved to yoto_app.playlists)
    playlists_ui = build_playlists_panel(
        page,
        api_ref,
        show_snack,
        ensure_api,
        status,
        file_rows_column,
    )
    # extract controls and helpers
    playlists_column = playlists_ui["playlists_column"]
    _ = playlists_ui["playlists_list"]
    existing_card_dropdown = playlists_ui["existing_card_dropdown"]
    existing_card_map = playlists_ui["existing_card_map"]
    _ = playlists_ui["fetch_playlists"]
    fetch_playlists_sync = playlists_ui["fetch_playlists_sync"]
    playlist_fetch_btn = playlists_ui["fetch_btn"]
    playlist_multi_select_btn = playlists_ui["multi_select_btn"]
    playlist_delete_selected_btn = playlists_ui["delete_selected_btn"]
    playlist_export_selected_btn = playlists_ui["export_selected_btn"]
    sort_dropdown = playlists_ui["sort_dropdown"]
    show_card_details = playlists_ui["show_card_details"]
    # Save playlist sort order on change
    if sort_dropdown:

        def _on_sort_change(ev):
            save_ui_state()

        orig_on_change = getattr(sort_dropdown, "on_change", None)
        if orig_on_change and orig_on_change != _on_sort_change:

            def chained(ev):
                orig_on_change(ev)
                _on_sort_change(ev)

            sort_dropdown.on_select = chained
        else:
            sort_dropdown.on_select = _on_sort_change

    # Context passed into upload tasks implementation
    ctx = {
        "page": page,
        "folder": folder,
        "utils_mod": utils_mod,
        "ensure_api": ensure_api,
        "api_ref": api_ref,
        "concurrency": concurrency,
        "file_rows_column": file_rows_column,
        "overall_bar": overall_bar,
        "overall_text": overall_text,
        "status": status,
        "show_snack": show_snack,
        "update_overall": update_overall,
        "fetch_playlists_sync": fetch_playlists_sync,
        "upload_target_dropdown": upload_target_dropdown,
        "new_card_title": new_card_title,
        "existing_card_dropdown": existing_card_dropdown,
        "existing_card_map": existing_card_map,
        # store the control so the upload task can read current value at start
        "strip_leading_track_numbers_control": strip_leading_checkbox,
        "intro_outro_side_control": intro_outro_side,
        "intro_outro_seconds_control": intro_seconds,
        "intro_outro_threshold_control": similarity_threshold,
        "gain_adjusted_files": gain_adjusted_files,
        "start_btn": start_btn,
        "stop_btn": stop_btn,
        "remove_uploaded_btn": remove_uploaded_btn,
    }

    # Also add the control to the page so user can toggle it
    # We'll insert it near the upload controls later when building the upload panel

    def _start_click(e):
        # update ctx with the current checkbox value
        try:
            ctx["strip_leading_track_numbers"] = bool(strip_leading_checkbox.value)
        except Exception:
            ctx["strip_leading_track_numbers"] = True

        try:
            ctx["local_normalization_enabled"] = bool(local_norm_checkbox.value)
            ctx["local_normalization_target"] = float(local_norm_target.value or -23.0)
            ctx["local_normalization_batch"] = bool(local_norm_batch.value)
        except Exception:
            ctx["local_normalization_enabled"] = False
            ctx["local_normalization_target"] = -23.0
            ctx["local_normalization_batch"] = False

        # intro/outro analysis is manual via the Analyze dialog; no automatic flag
        try:
            ctx["intro_outro_side"] = str(intro_outro_side.value or "intro")
        except Exception:
            ctx["intro_outro_side"] = "intro"
        try:
            ctx["intro_outro_seconds"] = float(intro_seconds.value or 10.0)
        except Exception:
            ctx["intro_outro_seconds"] = 10.0
        try:
            ctx["intro_outro_threshold"] = float(similarity_threshold.value or 0.75)
        except Exception:
            ctx["intro_outro_threshold"] = 0.75
        run_coro_in_thread(upload_start, e, ctx)

    start_btn.on_click = _start_click
    stop_btn.on_click = lambda e: run_coro_in_thread(upload_stop, e, ctx)
    fetch_btn.on_click = lambda e: threading.Thread(
        target=lambda: fetch_playlists_sync(e), daemon=True
    ).start()

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

    if upload_target_dropdown.value == "Create new card":
        new_card_title.visible = True
        existing_card_dropdown.visible = False
    else:
        new_card_title.visible = False
        existing_card_dropdown.visible = True
    page.update()

    # Ensure the original header buttons are present in the playlists header
    try:
        header = (
            playlists_column.controls[0]
            if playlists_column and len(playlists_column.controls) > 0
            else None
        )
        if header and hasattr(header, "controls"):
            try:
                hdr = list(header.controls)
                existing_texts = [getattr(c, "text", None) for c in hdr]
                if "Fetch Playlists" not in existing_texts:
                    insert_at = 1
                    # prefer buttons returned from playlists module
                    hdr[insert_at:insert_at] = [
                        playlist_fetch_btn or fetch_btn,
                        playlist_multi_select_btn or multi_select_btn,
                        playlist_delete_selected_btn or delete_selected_btn,
                        playlist_export_selected_btn or export_selected_btn,
                    ]
                    header.controls = hdr
            except Exception as e:
                logger.error(f"[_on_playlists_header_merge] failed: {e}")
    except Exception:
        pass

    # Upload page (appears after Playlists)
    # Add a dropdown to select upload mode: Chapters or Tracks
    upload_mode_dropdown = ft.Dropdown(
        label="Upload as",
        value="Chapters",
        options=[ft.dropdown.Option("Chapters"), ft.dropdown.Option("Tracks")],
        width=150,
        on_select=lambda e: save_ui_state(),
    )

    # Normalization controls
    local_norm_checkbox = ft.Checkbox(
        label="Normalize audio (local)",
        value=False,
        tooltip="Normalize audio loudness before upload using ffmpeg-normalize",
        on_change=lambda e: save_ui_state(),
    )
    local_norm_target = ft.TextField(
        label="Target LUFS",
        value="-23.0",
        width=100,
        tooltip="Target integrated loudness in LUFS (default -23.0)",
        on_change=lambda e: save_ui_state(),
    )
    local_norm_batch = ft.Checkbox(
        label="Batch mode",
        value=False,
        tooltip="Normalize all files as a batch (Album mode) instead of individually",
        on_change=lambda e: save_ui_state(),
    )

    # Now load state after controls are created
    load_ui_state(playlists_ui)
    # Load persisted playlists (if any) and populate the playlists list view
    try:
        saved = load_playlists()
        if saved and isinstance(saved, list):
            try:
                pl_list = (
                    playlists_ui.get("playlists_list")
                    if isinstance(playlists_ui, dict)
                    else None
                )
                if pl_list and hasattr(pl_list, "controls"):
                    pl_list.controls.clear()
                    # Resolve make_playlist_row once to avoid repeated fallback logs
                    make_row = None
                    try:
                        make_row = (
                            playlists_ui.get("make_playlist_row")
                            if isinstance(playlists_ui, dict)
                            else None
                        )
                    except Exception:
                        make_row = None
                    # If playlists_ui did not provide a row builder, we'll fall back
                    # to a simple ListTile per-item. Do not try to import the nested
                    # `make_playlist_row` from the module (it's local to the builder).
                    if not callable(make_row):
                        make_row = None
                    if not callable(make_row):
                        logger.debug(
                            "No make_playlist_row function available in playlists_ui; using fallback ListTile"
                        )

                    for idx, item in enumerate(saved):
                        try:
                            if callable(make_row):
                                try:
                                    row = make_row(item, idx=idx)
                                except Exception:
                                    row = None
                                # Only append a valid Control; otherwise fall back
                                if row is not None and isinstance(row, ft.Control):
                                    pl_list.controls.append(row)
                                else:
                                    title = (
                                        item.get("title", "")
                                        if isinstance(item, dict)
                                        else str(item)
                                    )
                                    cid = (
                                        item.get("cardId", "")
                                        if isinstance(item, dict)
                                        else ""
                                    )
                                    pl_list.controls.append(
                                        ft.ListTile(
                                            title=ft.Text(title),
                                            subtitle=ft.Text(str(cid)),
                                        )
                                    )
                            else:
                                # fallback: render a simple ListTile
                                title = (
                                    item.get("title", "")
                                    if isinstance(item, dict)
                                    else str(item)
                                )
                                cid = (
                                    item.get("cardId", "")
                                    if isinstance(item, dict)
                                    else ""
                                )
                                pl_list.controls.append(
                                    ft.ListTile(
                                        title=ft.Text(title), subtitle=ft.Text(str(cid))
                                    )
                                )
                        except Exception:
                            try:
                                pl_list.controls.append(
                                    ft.ListTile(title=ft.Text(str(item)))
                                )
                            except Exception:
                                pass
                    page.update()
            except Exception:
                pass
    except Exception:
        pass

    # Expose saver on page so other modules can persist playlists after edits
    def _page_save_playlists(items):
        try:
            save_playlists(items)
        except Exception:
            pass

    page.save_playlists = _page_save_playlists
    ctx["upload_mode_dropdown"] = (
        upload_mode_dropdown  # Add to context for upload tasks
    )

    # Card info/link display (persistent at bottom)
    card_info_display = ft.Column([], visible=False)

    def show_card_popup(card):
        # Show a dialog with full card details
        from flet import AlertDialog, Text, Column, TextButton, Image

        lines = []
        lines.append(
            Text(
                f"Title: {getattr(card, 'title', '')}",
                size=18,
                weight=ft.FontWeight.BOLD,
            )
        )
        lines.append(Text(f"Card ID: {getattr(card, 'cardId', '')}", size=14))
        if getattr(card, "metadata", None):
            meta = card.metadata
            if getattr(meta, "author", None):
                lines.append(Text(f"Author: {meta.author}"))
            if getattr(meta, "description", None):
                lines.append(Text(f"Description: {meta.description}"))
            if getattr(meta, "note", None):
                lines.append(Text(f"Note: {meta.note}"))
            if getattr(meta, "cover", None) and getattr(meta.cover, "imageL", None):
                lines.append(Image(src=meta.cover.imageL, width=120, height=120))
        if getattr(card, "content", None) and getattr(card.content, "chapters", None):
            lines.append(Text("Chapters:", weight=ft.FontWeight.BOLD))
            for ch in card.content.chapters:
                lines.append(Text(f"- {getattr(ch, 'title', '')}"))
        lines.append(
            TextButton(
                "View card",
                on_click=lambda e: show_card_details(e, card),
                style=ft.ButtonStyle(color=ft.Colors.BLUE),
            )
        )
        dlg = AlertDialog(
            title=Text("Card Details"),
            content=Column(lines, scroll=ft.ScrollMode.AUTO, expand=True),
            actions=[TextButton("Close", on_click=lambda e: page.pop_dialog())],
            scrollable=True,
        )
        page.show_dialog(dlg)
        page.update()

    def show_card_info(card):
        # Show a clickable card summary that launches show_card_detail
        card_info_display.controls.clear()

        def dismiss_item(item):
            try:
                card_info_display.controls.remove(item)
                if not card_info_display.controls:
                    card_info_display.visible = False
                page.update()
            except Exception:
                pass

        if not card or not getattr(card, "cardId", None):
            row = ft.Row(
                [
                    ft.Text("No card info available", color=ft.Colors.RED),
                    ft.TextButton(
                        "Dismiss",
                        on_click=lambda e: dismiss_item(row),
                        style=ft.ButtonStyle(color=ft.Colors.RED),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            card_info_display.controls.append(row)
        else:
            summary = ft.Container(
                content=ft.Row(
                    [
                        ft.Text(
                            getattr(card, "title", ""),
                            size=16,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            f"ID: {getattr(card, 'cardId', '')}",
                            size=12,
                            color=ft.Colors.GREY,
                        ),
                        ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.BLUE),
                        ft.TextButton(
                            "Dismiss",
                            on_click=lambda e: dismiss_item(summary),
                            style=ft.ButtonStyle(color=ft.Colors.RED),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                on_click=lambda e: show_card_popup(card),
                bgcolor=ft.Colors.BLUE_50,
                padding=10,
                border_radius=8,
                ink=True,
                tooltip="Click for card details",
            )
            card_info_display.controls.append(summary)
        card_info_display.visible = True
        page.update()

    # Patch into ctx so upload_tasks can update it
    ctx["show_card_info"] = show_card_info

    show_waveforms_btn = ft.TextButton(
        "Show Waveforms",
        on_click=lambda: show_waveforms_popup(
            page=page,
            file_rows_column=file_rows_column,
            show_snack=show_snack,
            gain_adjusted_files=gain_adjusted_files,
            audio_adjust_utils=audio_adjust_utils,
            waveform_cache=waveform_cache,
        ),
        tooltip="Visualize sound levels for all files in the queue",
        disabled=True,
    )

    # Analyze/trim button for intro/outro detection
    analyze_intro_btn = ft.Button("Analyze intro/outro")

    async def _do_analysis_and_show_dialog(dialog_controls):
        """Perform analysis using settings from dialog_controls and update dialog content.

        dialog_controls should contain:
          - 'intro_outro_side': Dropdown
          - 'intro_seconds': TextField
          - 'similarity_threshold': TextField
          - 'content_column': Column to place results into
        """
        # gather files from the UI queue
        files = [
            getattr(r, "filename", None)
            for r in file_rows_column.controls
            if getattr(r, "filename", None)
        ]
        files = [f for f in files if f]
        if not files:
            show_snack("No files in queue to analyze", error=False)
            return

        # import here so missing dependency only affects this feature
        try:
            from yoto_app.intro_outro import per_window_common_prefix, trim_audio_file
        except Exception:
            show_snack("Intro/outro analysis unavailable (missing module)", error=True)
            return

        # read config from dialog controls
        side = dialog_controls["intro_outro_side"].value or "intro"
        seconds = float(dialog_controls["intro_seconds"].value or 10.0)
        thresh = float(dialog_controls["similarity_threshold"].value or 0.75)
        try:
            padding_seconds = float(
                dialog_controls.get("padding_seconds").value or 0.25
            )
        except Exception:
            padding_seconds = 0.25
        padding_ms = int(padding_seconds * 1000)

        # Show spinner in the dialog's content column so the main dialog stays open
        content_col = dialog_controls["content_column"]
        content_col.controls.clear()
        content_col.controls.append(
            ft.Row(
                [ft.ProgressRing(), ft.Text("Analyzing files...")],
                alignment=ft.MainAxisAlignment.CENTER,
            )
        )
        try:
            page.update()
        except Exception:
            pass

        # run analysis off the UI thread
        try:
            # Use windowed analyzer (configurable window size / sub-second precision)
            try:
                fast_mode_ctrl = dialog_controls.get("fast_mode")
                try:
                    fast_mode = bool(getattr(fast_mode_ctrl, "value", True))
                except Exception:
                    fast_mode = True
                sr = 11025 if fast_mode else 22050
                n_mfcc = 13
                # read windowed controls
                ws_ctrl = dialog_controls.get("window_seconds")
                mx_ctrl = dialog_controls.get("max_seconds_window")
                sim_ctrl = dialog_controls.get("window_similarity")
                mf_ctrl = dialog_controls.get("window_min_files")
                try:
                    window_seconds = float(getattr(ws_ctrl, "value", 0.1))
                except Exception:
                    window_seconds = 0.1
                try:
                    max_seconds = float(getattr(mx_ctrl, "value", seconds))
                except Exception:
                    max_seconds = float(seconds)
                try:
                    similarity_threshold = float(getattr(sim_ctrl, "value", 0.98))
                except Exception:
                    similarity_threshold = 0.98
                try:
                    min_files_fraction = float(getattr(mf_ctrl, "value", 0.75))
                except Exception:
                    min_files_fraction = 0.75

                result = await asyncio.to_thread(
                    lambda: per_window_common_prefix(
                        paths=files,
                        side=side,
                        max_seconds=max_seconds,
                        window_seconds=window_seconds,
                        sr=sr,
                        n_mfcc=n_mfcc,
                        similarity_threshold=similarity_threshold,
                        min_files_fraction=min_files_fraction,
                    )
                )
            except Exception as e:
                raise
        except Exception as e:
            # analysis failed — update the dialog content column rather than trying
            # to close a previously-used helper dialog (analyzing_dlg no longer exists)
            show_snack(f"Analysis failed: {e}", error=True)
            return

        # populate result content in the same dialog content column
        # The new windowed analyzer returns per-window similarities and a
        # contiguous matched window count. Use that to compute the common
        # removal seconds and per-file match fractions for UI presentation.
        content_col.controls.clear()
        windows_matched = int(result.get("windows_matched", 0))
        seconds_matched = float(result.get("seconds_matched", 0.0))
        per_window_frac = result.get("per_window_frac", [])
        per_file_per_window = result.get("per_file_per_window", {})

        if windows_matched <= 0 or seconds_matched <= 0.0:
            content_col.controls.append(ft.Text("No common intro/outro detected"))
            try:
                page.update()
            except Exception:
                pass
            return

        # Update the computed removal field so the user can tweak it before trimming
        try:
            comp_ctrl = dialog_controls.get("computed_removal")
            if comp_ctrl is not None:
                comp_ctrl.value = f"{seconds_matched:.2f}"
                try:
                    setattr(comp_ctrl, "_computed_by_analysis", True)
                except Exception:
                    pass
                try:
                    page.update()
                except Exception:
                    pass
        except Exception:
            pass

        content_col.controls.append(
            ft.Text(
                f"Planned removal: from start up to {seconds_matched:.2f}s (same for all matched files)"
            )
        )
        # Persist a small debug JSON so the preview/trim actions can be inspected
        try:
            debug_dir = Path(".tmp_trim") / "previews"
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / ("intro_removal.json")
            try:
                with open(debug_path, "w") as _df:
                    import json as _json

                    _json.dump(
                        {
                            "common_removal_end_sec": seconds_matched,
                            "per_window_frac": per_window_frac,
                        },
                        _df,
                        indent=2,
                    )
            except Exception:
                pass
        except Exception:
            pass

        # build per-file score based on how many of the matched windows each
        # file satisfied (i.e. per-window similarity >= configured threshold)
        checkbox_map = {}
        try:
            sim_thresh = float(dialog_controls.get("window_similarity").value or 0.95)
        except Exception:
            sim_thresh = 0.95
        for p, perw in per_file_per_window.items():
            try:
                # consider only the windows that were accepted
                relevant = perw[:windows_matched]
                matched = sum(1 for v in relevant if v >= sim_thresh)
                score = (
                    float(matched) / float(windows_matched) if windows_matched else 0.0
                )
            except Exception:
                score = 0.0
            score_label = f"{score * 100:.2f}%"
            cb = ft.Checkbox(
                label=f"{p.split('/')[-1]} (score={score_label})",
                value=(
                    score
                    >= float(dialog_controls.get("window_min_files").value or 0.75)
                ),
                tooltip=f"Include this file in trimming: {p}",
            )
            checkbox_map[p] = cb

            # Preview button: extract the matched segment into a temp file and play it
            preview_btn = ft.TextButton(
                "Preview",
                on_click=None,
                tooltip="Preview the matched intro/outro segment",
            )

            def make_preview_handler(path, preview_button, seg_seconds, side_label):
                def _on_preview(ev=None):
                    logger.debug(f"Previewing {side_label} segment for {path}")
                    try:
                        preview_button.disabled = True
                        page.update()
                    except Exception:
                        pass

                    def open_intro_outro_dialog(ev=None):
                        logger.debug(f"TEST")
                        global INTRO_OUTRO_DIALOG
                        logger.debug(
                            f"open_intro_outro_dialog: reopening dialog: {INTRO_OUTRO_DIALOG}"
                        )
                        page.show_dialog(INTRO_OUTRO_DIALOG)

                    # Create a preview dialog so the user sees progress while we extract
                    preview_content = ft.Column(
                        [
                            ft.Row(
                                [ft.ProgressRing(), ft.Text("Preparing preview...")],
                                alignment=ft.MainAxisAlignment.CENTER,
                            )
                        ],
                        scroll=ft.ScrollMode.AUTO,
                    )
                    preview_dlg = ft.AlertDialog(
                        title=ft.Text("Preview"),
                        content=preview_content,
                        actions=[
                            ft.TextButton(
                                "Close", on_click=lambda e: open_intro_outro_dialog(e)
                            )
                        ],
                        modal=True,
                    )
                    try:
                        page.show_dialog(preview_dlg)
                        page.update()
                    except Exception:
                        pass

                    def _worker():
                        try:
                            from pydub import AudioSegment
                            import webbrowser

                            src = str(path)
                            # For a consistent removal across matched files we use the computed common_removal_end_sec.
                            audio = AudioSegment.from_file(src)
                            try:
                                common_ms = int(seconds_matched * 1000)
                            except Exception:
                                try:
                                    common_ms = int(float(seg_seconds) * 1000)
                                except Exception:
                                    common_ms = 0

                            if side == "intro":
                                # preview the start portion that would be removed from all files
                                segment = audio[0:common_ms]
                            else:
                                # preview the tail portion that would be removed from all files
                                if common_ms <= len(audio):
                                    segment = audio[-common_ms:]
                                else:
                                    segment = audio
                            temp_dir = Path(".tmp_trim") / "previews"
                            temp_dir.mkdir(parents=True, exist_ok=True)
                            preview_path = temp_dir / (
                                Path(src).stem + ".preview" + Path(src).suffix
                            )
                            try:
                                # Best-effort: write original-format preview
                                segment.export(
                                    str(preview_path),
                                    format=preview_path.suffix.lstrip("."),
                                )
                            except Exception:
                                # non-fatal
                                pass

                            # Ensure we create a WAV preview for reliable playback
                            preview_wav = temp_dir / (Path(src).stem + ".preview.wav")
                            wav_ok = False
                            try:
                                segment.export(str(preview_wav), format="wav")
                                wav_ok = preview_wav.exists()
                            except Exception:
                                wav_ok = False

                            # Fallback: if original-format preview written, try converting that to WAV
                            if not wav_ok and preview_path.exists():
                                try:
                                    tmp_seg = AudioSegment.from_file(str(preview_path))
                                    tmp_seg.export(str(preview_wav), format="wav")
                                    wav_ok = preview_wav.exists()
                                except Exception:
                                    wav_ok = False

                            # Close the preparing dialog
                            try:
                                page.pop_dialog()
                            except Exception:
                                pass

                            # Build result dialog with Play (enabled only if WAV exists) and Open buttons
                            def make_result_dialog(wav_available: bool):
                                items = [ft.Text(f"Preview: {Path(src).name}")]

                                if wav_available or segment is not None:

                                    def _play(e=None, p=preview_wav, seg=segment):
                                        def _play_thread():
                                            # Prefer playing the in-memory pydub segment via simpleaudio so we play exactly the removed segment
                                            if (
                                                HAS_SIMPLEAUDIO
                                                and _simpleaudio is not None
                                                and seg is not None
                                            ):
                                                try:
                                                    sa_mod = _simpleaudio
                                                    # pydub AudioSegment stores raw_data, frame_rate, channels, sample_width
                                                    raw = seg.raw_data
                                                    channels = seg.channels
                                                    sample_width = seg.sample_width
                                                    frame_rate = seg.frame_rate
                                                    wave_obj = sa_mod.WaveObject(
                                                        raw,
                                                        channels,
                                                        sample_width,
                                                        frame_rate,
                                                    )
                                                    play_obj = wave_obj.play()
                                                    play_obj.wait_done()
                                                    return
                                                except Exception:
                                                    pass
                                            # Fallback to calling an external player on the WAV file we wrote
                                            cmds = [
                                                [
                                                    "ffplay",
                                                    "-nodisp",
                                                    "-autoexit",
                                                    str(p),
                                                ],
                                                ["aplay", str(p)],
                                                ["xdg-open", str(p)],
                                            ]
                                            for cmd in cmds:
                                                try:
                                                    subprocess.run(cmd, check=True)
                                                    return
                                                except Exception:
                                                    continue
                                            show_snack(
                                                "No available player found (ffplay/aplay/xdg-open)",
                                                error=True,
                                            )

                                        threading.Thread(
                                            target=_play_thread, daemon=True
                                        ).start()

                                    items.append(ft.Button("Play", on_click=_play))
                                else:
                                    items.append(
                                        ft.Text(
                                            "Preview playback not available (conversion failed)"
                                        )
                                    )

                                def _open_external(e=None):
                                    try:
                                        target = (
                                            preview_wav
                                            if wav_available and preview_wav.exists()
                                            else preview_path
                                        )
                                        webbrowser.open(Path(target).resolve().as_uri())
                                    except Exception as ex:
                                        show_snack(
                                            f"Failed to open preview: {ex}", error=True
                                        )

                                items.append(
                                    ft.TextButton(
                                        "Open in external player",
                                        on_click=_open_external,
                                    )
                                )
                                # Show the absolute path so users can verify which file will be opened/played
                                try:
                                    display_target = (
                                        preview_wav
                                        if wav_available and preview_wav.exists()
                                        else preview_path
                                    )
                                    items.append(
                                        ft.Text(
                                            str(Path(display_target).resolve()), size=12
                                        )
                                    )
                                except Exception:
                                    pass

                                content = ft.Column(items, scroll=ft.ScrollMode.AUTO)
                                return ft.AlertDialog(
                                    title=ft.Text("Preview"),
                                    content=content,
                                    actions=[
                                        ft.TextButton(
                                            "Close",
                                            on_click=lambda e: open_intro_outro_dialog(
                                                e
                                            ),
                                        )
                                    ],
                                    modal=True,
                                )

                            try:
                                result_dlg = make_result_dialog(wav_ok)
                                page.show_dialog(result_dlg)
                                page.update()
                            except Exception:
                                try:
                                    # fallback: open any file we have
                                    target = (
                                        preview_wav
                                        if wav_ok and preview_wav.exists()
                                        else preview_path
                                    )
                                    webbrowser.open(Path(target).resolve().as_uri())
                                except Exception:
                                    pass
                        except Exception as ex:
                            show_snack(f"Preview failed: {ex}", error=True)
                        finally:
                            try:
                                preview_button.disabled = False
                                page.update()
                            except Exception:
                                pass

                    threading.Thread(target=_worker, daemon=True).start()

                return _on_preview

            # attach handler (capture p and seconds)
            preview_btn.on_click = make_preview_handler(p, preview_btn, seconds, side)

            # Layout: checkbox + preview button on the same row
            content_col.controls.append(
                ft.Row([cb, preview_btn], alignment=ft.MainAxisAlignment.START)
            )

        # trim handler: shows a trimming dialog and runs trimming in background
        def do_trim(ev=None):
            total_to_trim = sum(1 for p, cb in checkbox_map.items() if cb.value)
            if total_to_trim == 0:
                show_snack("No files selected for trimming", error=False)
                return

            # Compute planned removal (use computed_removal field if present,
            # otherwise fall back to analysis result). The final confirmation
            # modal below will ask the user to proceed before any files are
            # modified, so we don't require a separate confirm checkbox here.
            try:
                comp_ctrl = dialog_controls.get("computed_removal")
                try:
                    comp_val = float(getattr(comp_ctrl, "value", seconds_matched))
                except Exception:
                    comp_val = (
                        float(seconds_matched) if seconds_matched is not None else 0.0
                    )
            except Exception:
                comp_val = (
                    float(seconds_matched) if seconds_matched is not None else 0.0
                )

            # Define the trimming worker up-front so it can be started from the
            # confirmation dialog. It will open its own progress dialog.
            def _trim_worker():
                trim_progress = ft.ProgressBar(width=400, value=0.0, visible=True)
                trim_label = ft.Text(f"Trimming 0/{total_to_trim}")
                trim_dlg = ft.AlertDialog(
                    title=ft.Text("Trimming..."),
                    content=ft.Column([trim_label, trim_progress]),
                    actions=[],
                )
                try:
                    page.show_dialog(trim_dlg)
                    page.update()
                except Exception:
                    pass

                temp_dir = Path(".tmp_trim")
                temp_dir.mkdir(parents=True, exist_ok=True)
                # Collect selected, canonicalized source paths and dedupe
                selected_paths = []
                seen = set()
                for p, cb in checkbox_map.items():
                    if not cb.value:
                        continue
                    try:
                        norm = str(Path(p).resolve())
                    except Exception:
                        norm = str(p)
                    if norm in seen:
                        logger.debug(f"Skipping duplicate selection for {norm}")
                        continue
                    seen.add(norm)
                    selected_paths.append((p, norm))

                total_selected = len(selected_paths)
                trimmed_count = 0
                trimmed_paths: set[str] = set()
                lock = threading.Lock()

                # Worker that trims a single file. Returns (orig_path, dest, error_or_none)
                def _trim_one(orig_p, norm_p):
                    try:
                        # compute remove_t
                        try:
                            comp_ctrl = dialog_controls.get("computed_removal")
                            remove_t = float(
                                getattr(comp_ctrl, "value", seconds_matched)
                            )
                        except Exception:
                            remove_t = (
                                float(seconds_matched)
                                if seconds_matched is not None
                                else 0.0
                            )

                        src_path = Path(orig_p)
                        dest = str(
                            temp_dir / (src_path.stem + ".trimmed" + src_path.suffix)
                        )

                        trim_audio_file(
                            orig_p,
                            dest,
                            remove_intro_seconds=remove_t if side == "intro" else 0.0,
                            remove_outro_seconds=remove_t if side == "outro" else 0.0,
                            keep_silence_ms=padding_ms,
                        )

                        # update matching rows to point to trimmed file
                        for ctrl in list(file_rows_column.controls):
                            fur = getattr(ctrl, "_fileuploadrow", None)
                            try:
                                if fur and (
                                    getattr(fur, "original_filepath", None) == orig_p
                                    or getattr(fur, "filepath", None) == orig_p
                                    or getattr(ctrl, "filename", None) == orig_p
                                ):
                                    fur.update_file(dest)
                                    fur.set_status("Trimmed intro/outro")
                                    fur.set_progress(1.0)
                            except Exception:
                                pass

                        return (orig_p, dest, None)
                    except Exception as e:
                        return (orig_p, None, str(e))

                # Run trims in parallel but limit concurrency using ThreadPoolExecutor
                try:
                    import concurrent.futures
                except Exception:
                    concurrent = None
                    concurrent_futures = None

                # Determine max workers from UI control or fallback to 4
                try:
                    max_workers = max(1, int(concurrency.value))
                except Exception:
                    max_workers = 4

                futures = []
                try:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_workers
                    ) as executor:
                        for orig_p, norm_p in selected_paths:
                            futures.append(executor.submit(_trim_one, orig_p, norm_p))

                        # iterate as futures complete and update UI
                        for fut in concurrent.futures.as_completed(futures):
                            orig_p, dest, err = fut.result()
                            with lock:
                                trimmed_count += 1
                                try:
                                    trim_progress.value = (
                                        (trimmed_count / total_selected)
                                        if total_selected
                                        else 1.0
                                    )
                                    trim_label.value = (
                                        f"Trimming {trimmed_count}/{total_selected}"
                                    )
                                except Exception:
                                    pass
                            # update UI rows for this file
                            if err:
                                for ctrl in list(file_rows_column.controls):
                                    fur = getattr(ctrl, "_fileuploadrow", None)
                                    try:
                                        if fur and (
                                            getattr(fur, "original_filepath", None)
                                            == orig_p
                                            or getattr(fur, "filepath", None) == orig_p
                                            or getattr(ctrl, "filename", None) == orig_p
                                        ):
                                            fur.set_status(f"Trim error: {err}")
                                    except Exception:
                                        pass
                            else:
                                try:
                                    for ctrl in list(file_rows_column.controls):
                                        fur = getattr(ctrl, "_fileuploadrow", None)
                                        try:
                                            if fur and (
                                                getattr(fur, "original_filepath", None)
                                                == orig_p
                                                or getattr(fur, "filepath", None)
                                                == orig_p
                                                or getattr(ctrl, "filename", None)
                                                == orig_p
                                            ):
                                                fur.update_file(dest)
                                                fur.set_status("Trimmed intro/outro")
                                                fur.set_progress(1.0)
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            try:
                                page.update()
                            except Exception:
                                pass
                            # record trimmed path
                            try:
                                trimmed_paths.add(orig_p)
                            except Exception:
                                pass
                except Exception as e:
                    # If executor failed for some reason, fall back to sequential loop
                    logger.exception(
                        "Parallel trimming failed, falling back to sequential"
                    )
                    for orig_p, norm_p in selected_paths:
                        _orig, _dest, _err = _trim_one(orig_p, norm_p)
                        with lock:
                            trimmed_count += 1
                            try:
                                trim_progress.value = (
                                    (trimmed_count / total_selected)
                                    if total_selected
                                    else 1.0
                                )
                                trim_label.value = (
                                    f"Trimming {trimmed_count}/{total_selected}"
                                )
                            except Exception:
                                pass
                        try:
                            page.update()
                        except Exception:
                            pass

                try:
                    page.pop_dialog()
                    page.update()
                except Exception:
                    pass
                show_snack("Trim complete")

            # If computed removal is > 0 (and the earlier checkbox guard passed),
            # show a final confirmation modal summarizing the action. The user
            # must click "Proceed" to actually start the trimming worker.
            try:
                if comp_val > 0.0:
                    confirm_text = ft.Text(
                        f"You are about to trim {comp_val:.2f}s from {total_to_trim} file(s).\n\nThis will modify the selected files. Proceed?"
                    )

                    def _on_proceed(e=None):
                        try:
                            page.pop_dialog()
                        except Exception:
                            pass
                        # start the trimming worker after closing the confirm dialog
                        threading.Thread(target=_trim_worker, daemon=True).start()

                    def _on_cancel(e=None):
                        try:
                            page.pop_dialog()
                        except Exception:
                            pass

                    proceed_btn = ft.Button("Proceed", on_click=_on_proceed)
                    cancel_btn = ft.TextButton("Cancel", on_click=_on_cancel)
                    confirm_dlg = ft.AlertDialog(
                        title=ft.Text("Confirm trimming"),
                        content=confirm_text,
                        actions=[proceed_btn, cancel_btn],
                    )
                    page.show_dialog(confirm_dlg)
                    page.update()
                else:
                    # No removal requested (0s) — start trimming immediately
                    threading.Thread(target=_trim_worker, daemon=True).start()
            except Exception:
                # Fallback: start trimming if anything goes wrong showing the modal
                threading.Thread(target=_trim_worker, daemon=True).start()

        # If the opener provided a dialog action button, enable and wire it
        try:
            trim_btn = dialog_controls.get("trim_button")
            if trim_btn is not None:
                trim_btn.disabled = False
                trim_btn.on_click = do_trim
        except Exception:
            pass

        # Trim control will be provided as a dialog action (wired by the opener)
        try:
            page.update()
        except Exception:
            pass

    def open_analysis_dialog(e=None):
        # Build a simplified dialog focused on the new per-window analyzer.
        d_side = ft.Dropdown(
            label="Side",
            value="intro",
            options=[ft.dropdown.Option("intro"), ft.dropdown.Option("outro")],
            width=120,
        )
        d_max_seconds = ft.TextField(
            label="Max inspect seconds", value="10.0", width=120
        )
        d_window_seconds = ft.TextField(label="Window seconds", value="0.1", width=120)
        d_window_similarity = ft.TextField(
            label="Window similarity threshold", value="0.95", width=120
        )
        d_window_min_files = ft.TextField(
            label="Min files fraction", value="1.0", width=120
        )
        d_padding = ft.TextField(label="Left padding (s)", value="0.25", width=100)
        d_fast = ft.Checkbox(label="Fast mode (lower quality, faster)", value=True)
        d_computed_removal = ft.TextField(
            label="Computed removal (s)", value="0.00", width=120
        )
        # confirm removal checkbox removed — rely on final confirmation dialog
        content_column = ft.Column([], scroll=ft.ScrollMode.AUTO)

        def on_run(ev=None):
            dlg_controls = {
                "intro_outro_side": d_side,
                "intro_seconds": d_max_seconds,
                "similarity_threshold": d_window_similarity,
                "padding_seconds": d_padding,
                "fast_mode": d_fast,
                "window_seconds": d_window_seconds,
                "max_seconds_window": d_max_seconds,
                "window_similarity": d_window_similarity,
                "window_min_files": d_window_min_files,
                "computed_removal": d_computed_removal,
                "content_column": content_column,
                "trim_button": trim_btn,
            }

            def _runner():
                try:
                    asyncio.run(_do_analysis_and_show_dialog(dlg_controls))
                except Exception as ex:
                    show_snack(f"Analysis error: {ex}", error=True)

            threading.Thread(target=_runner, daemon=True).start()

        run_btn = ft.Button("Run analysis", on_click=on_run)
        trim_btn = ft.Button("Trim selected", disabled=True)
        close_btn = ft.TextButton("Close", on_click=lambda e: page.pop_dialog())

        dlg = ft.AlertDialog(
            title=ft.Text("Analyze intro/outro"),
            content=ft.Column(
                [
                    ft.Row([d_side, d_max_seconds, d_padding, d_fast]),
                    ft.Row([d_window_seconds, d_window_similarity, d_window_min_files]),
                    ft.Row([d_computed_removal]),
                    ft.Divider(),
                    content_column,
                ],
                scroll=ft.ScrollMode.AUTO,
                width=600,
            ),
            actions=[run_btn, trim_btn, close_btn],
        )
        # expose dlg to inner closures
        global INTRO_OUTRO_DIALOG
        INTRO_OUTRO_DIALOG = dlg
        page.show_dialog(dlg)
        page.update()

    analyze_intro_btn.on_click = open_analysis_dialog

    def update_show_waveforms_btn():
        # Enable if there are any files in the upload queue
        has_files = any(
            getattr(row, "filename", None) for row in file_rows_column.controls
        )
        show_waveforms_btn.disabled = not has_files
        page.update()

    # Collapsible local normalization controls (collapsed by default)
    # Build the inner container and expander before creating the upload column
    _local_norm_inner = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "Normalise audio loudness before upload. Use the target LUFS and choose batch mode for album-style normalization.",
                    size=12,
                    color=ft.Colors.GREY,
                ),
                ft.Row([local_norm_checkbox, local_norm_target, local_norm_batch]),
                ft.Text(
                    "For waveform-based inspection and additional normalisation options, click 'Show Waveforms'.",
                    size=11,
                    italic=True,
                    color=ft.Colors.GREY,
                ),
            ],
            tight=True,
        ),
        padding=10,
    )

    local_norm_expander = ft.ExpansionTile(
        title=ft.Container(
            content=ft.Text("ffmpeg normalisation", size=12, weight=ft.FontWeight.W_400)
        ),
        controls=[_local_norm_inner],
    )
    # Ensure collapsed by default (set attribute after construction to avoid constructor arg mismatch)
    try:
        local_norm_expander.open = False
    except Exception:
        pass

    # Wrap in a container to preserve top/bottom margins
    _local_norm_container = ft.Container(
        content=local_norm_expander, margin=ft.Margin(top=6, bottom=6, left=0, right=0)
    )

    upload_column = ft.Column(
        [
            ft.Row([upload_target_dropdown, new_card_title, existing_card_dropdown]),
            ft.Row(
                [
                    concurrency,
                    strip_leading_checkbox,
                    upload_mode_dropdown,  # Add the new dropdown here
                ]
            ),
            _local_norm_container,
            ft.Row(
                [
                    folder,
                    ft.TextButton("Browse Folder...", on_click=_open_folder_picker),
                    ft.TextButton("Add Files...", on_click=_open_files_picker),
                    ft.TextButton("Clear Queue", on_click=clear_queue),
                    show_waveforms_btn,
                    analyze_intro_btn,
                    ft.IconButton(
                        icon=ft.Icons.HELP_OUTLINE,
                        tooltip="Help: Select a folder or specific files to upload.",
                        on_click=lambda e: show_snack(
                            "Select the folder containing your audio files, or add specific files. 'Browse Folder...' lets you pick a folder (you may have to select a file within the folder), or paste the path directly. 'Add Files...' lets you pick individual files.\n\nChoose 'Chapters' to upload files as chapters, or 'Tracks' to upload as tracks. Once uploaded it is possible to convert between Chapters and tracks",
                            error=False,
                            duration=10000,
                        ),
                    ),
                ]
            ),
            ft.Row([start_btn, stop_btn, remove_uploaded_btn]),
            ft.Divider(),
            overall_text,
            overall_bar,
            ft.Divider(),
            ft.Text("Files:"),
            ft.Container(content=file_rows_column, padding=10, bgcolor=ft.Colors.WHITE),
            ft.Divider(),
            ft.Row([status]),
            ft.Divider(),
            card_info_display,
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
        pass

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

    # Create tabs and keep a reference so we can enable/disable them
    # Build icon browser panel and add as a tab
    icon_browser_ui = build_icon_browser_panel(
        page=page, api_ref=api_ref, ensure_api=ensure_api, show_snack=show_snack
    )
    icon_panel = (
        icon_browser_ui.get("panel") if isinstance(icon_browser_ui, dict) else None
    )

    # Build covers panel
    covers_ui = build_covers_panel(page=page, show_snack=show_snack)
    covers_panel = covers_ui.get("panel") if isinstance(covers_ui, dict) else None

    # Note: removed _ensure_control wrapper per user request. If a panel
    # is incorrectly defined it should be fixed at source rather than
    # automatically replaced at runtime.

    editor = PixelArtEditor(page=page)
    # editor_tab = editor.as_tab("Editor") or editor.as_tab("Icon Editor")
    # keep a reference on the page for external callers if needed
    page.pixel_editor = editor
    editor_content = editor.control()

    # Ensure all content is visible
    auth_column.visible = True
    playlists_column.visible = True
    upload_column.visible = True
    if hasattr(icon_panel, "visible"):
        icon_panel.visible = True
    if hasattr(covers_panel, "visible"):
        covers_panel.visible = True

    # Create tab labels for TabBar
    auth_tab = ft.Tab(label="Auth")
    playlists_tab = ft.Tab(label="Playlists", disabled=True)
    upload_tab = ft.Tab(label="Upload", disabled=True)
    icons_tab = ft.Tab(label="Icons", disabled=True)
    covers_tab = ft.Tab(label="Covers", disabled=True)
    editor_tab = ft.Tab(label="Editor", disabled=True)

    all_tab_labels = [
        auth_tab,
        playlists_tab,
        upload_tab,
        icons_tab,
        covers_tab,
        editor_tab,
    ]
    all_tab_content = [
        auth_column,
        playlists_column,
        upload_column,
        icon_panel,
        covers_panel,
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
    page.add(tabs_control)

    # Register service controls after page has content
    page.services.extend([p for p in (browse, browse_files) if p is not None])
    page.update()

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
