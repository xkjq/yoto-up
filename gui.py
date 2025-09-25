import asyncio
import os
import tempfile
# Ensure matplotlib will use a writable config/cache dir when the app is frozen by PyInstaller.
# PyInstaller unpacks the app to a temporary folder which may be read-only for font cache writes.
# Setting MPLCONFIGDIR to a temp directory prevents the "Matplotlib is building the font cache" pause
# and avoids FileNotFoundError when matplotlib tries to access a bundled source file path.
try:
    mpl_cfg = os.path.join(tempfile.gettempdir(), "yoto_up_matplotlib")
    os.environ.setdefault("MPLCONFIGDIR", mpl_cfg)
    os.makedirs(mpl_cfg, exist_ok=True)
except Exception:
    pass
import importlib.util
from typing import cast, Any
import sys as _sys
from pathlib import Path
import sys
import traceback
import json
import threading
# typing imported above

import os

import flet as ft
from yoto_app import utils as utils_mod
from yoto_app import ui_helpers as ui_helpers
from yoto_app import auth as auth_mod
from yoto_app.api_manager import ensure_api
from yoto_app.playlists import build_playlists_panel
from loguru import logger
from yoto_app.upload_tasks import start_uploads as upload_start, stop_uploads as upload_stop, FileUploadRow

from yoto_app.show_waveforms import show_waveforms_popup
from yoto_app.icon_browser import build_icon_browser_panel
from yoto_app.pixel_art_editor import PixelArtEditor
import http.server
import socketserver
import socket
import subprocess
try:
    import simpleaudio as _simpleaudio
    HAS_SIMPLEAUDIO = True
except Exception:
    _simpleaudio = None
    HAS_SIMPLEAUDIO = False

# Simple single-instance HTTP server to serve preview files from .tmp_trim/previews
_preview_server = None
_preview_server_base = None
def start_preview_server_if_needed(directory: str = '.tmp_trim/previews') -> str:
    """Start a local HTTP server serving `directory` and return the base URL.

    The server is started once per application instance and reused.
    """
    global _preview_server, _preview_server_base
    if _preview_server_base:
        return _preview_server_base
    try:
        # Ensure directory exists
        Path(directory).mkdir(parents=True, exist_ok=True)
        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)
            def log_message(self, format, *args):
                # silence logs
                return

        # Pick an available port
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        addr, port = sock.getsockname()
        sock.close()

        httpd = socketserver.TCPServer(('127.0.0.1', port), _Handler)
        httpd.allow_reuse_address = True

        def _serve():
            try:
                httpd.serve_forever()
            except Exception:
                pass

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        _preview_server = httpd
        _preview_server_base = f'http://127.0.0.1:{port}'
        return _preview_server_base
    except Exception:
        return ''



# Prefer a normal import so PyInstaller will detect and include the module.
# Fall back to loading from the source file only when the normal import fails
# (useful in some dev workflows).
try:
    import audio_adjust_utils  # type: ignore
except Exception:
    audio_adjust_utils = cast(Any, None)  # type: ignore
    # fallback: attempt to load from the local source file if present
    audio_adjust_utils_path = os.path.join(os.path.dirname(__file__), "audio_adjust_utils.py")
    if os.path.exists(audio_adjust_utils_path):
        try:
            _spec = importlib.util.spec_from_file_location("audio_adjust_utils", audio_adjust_utils_path)
            if _spec and _spec.loader:
                # mypy/linters can be picky about module typing; ignore here
                audio_adjust_utils = importlib.util.module_from_spec(_spec)  # type: ignore
                _sys.modules["audio_adjust_utils"] = audio_adjust_utils
                _spec.loader.exec_module(audio_adjust_utils)  # type: ignore
        except Exception:
            audio_adjust_utils = cast(Any, None)  # type: ignore

# Supported audio extensions
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"}

logger.remove()  # Remove default handler
logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message}")


AUTHENTICATE_TEXT = """Not authenticated.

To authenticate with your Yoto account:

1. Click the "Authenticate" button.
2. A code and URL will be displayed. Open the URL in your web browser.
3. Enter the code and complete the authentication process.
"""

# use utils_mod.find_audio_files when needed


#class FileRow(ft.Row):
#    def __init__(self, filename: str):
#        super().__init__()
#        self.filename = filename
#        pr = ft.ProgressBar(width=300, visible=False)
#        status = ft.Text("Queued")
#        def on_preview_click(e=None):
#            import webbrowser
#            # Use file:// URI for local files
#            path = os.path.abspath(filename)
#            url = f"file://{path}"
#            try:
#                webbrowser.open(url)
#            except Exception as ex:
#                print(f"[Preview] Failed to open {url}: {ex}")
#        preview_btn = ft.TextButton("Preview", on_click=on_preview_click, tooltip="Play this audio file before upload")
#        self.controls = [ft.Text(filename, width=300), preview_btn, pr, status]
#        try:
#            setattr(self, 'filename', filename)
#        except Exception:
#            pass


def main(page):

    gain_adjusted_files = {}  # {filepath: {'gain': float, 'temp_path': str or None}}
    waveform_cache = {}


    def show_waveforms_popup_wrapper(e=None):
        show_waveforms_popup(
            page=page,
            file_rows_column=file_rows_column,
            show_snack=show_snack,
            gain_adjusted_files=gain_adjusted_files,
            audio_adjust_utils=audio_adjust_utils,
            waveform_cache=waveform_cache
        )
    page.title = "Yoto Up"
    # --- About Dialog ---
    def show_about_dialog(e=None):
        dlg = ft.AlertDialog(
            title=ft.Text("About Yoto Up"),
            content=ft.Column([
            ft.Row(
                [ft.Image(src="art.jpeg", width=120, height=120)],
                alignment=ft.MainAxisAlignment.CENTER
            ),
            ft.Text("Yoto Up", size=20, weight=ft.FontWeight.BOLD),
            ft.Text("A desktop tool for managing Yoto cards and playlists."),
            #ft.Text("Version: 2025.09"),
            ft.Text("Author: xkjq"),
            ft.TextButton(
                "GitHub Repository",
                url="https://github.com/xkjq/yoto-up",
                style=ft.ButtonStyle(color=ft.Colors.BLUE),
            ),
            ft.Text("\nYoto Up is not affiliated with Yoto Ltd.\n"),
            ]),
            actions=[ft.TextButton("Close", on_click=lambda e: page.close(dlg))],
        )
        page.open(dlg)
        page.update()
    # --- UI State Persistence ---
    UI_STATE_FILE = "ui_state.json"
    def save_ui_state():
        sort_dropdown = playlists_ui['sort_dropdown'] if isinstance(playlists_ui, dict) else None
        state = {
            "concurrency": concurrency.value,
            "strip_leading": strip_leading_checkbox.value,
            "normalize": normalize_checkbox.value,
            "intro_outro_side": intro_outro_side.value,
            "intro_outro_seconds": intro_seconds.value,
            "intro_outro_threshold": similarity_threshold.value,
            "upload_mode": upload_mode_dropdown.value,
            "playlist_sort": sort_dropdown.value if sort_dropdown else None,
        }
        try:
            with open(UI_STATE_FILE, "w") as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[ui_state] Failed to save: {e}")

    def load_ui_state(playleists_ui):
        try:
            with open(UI_STATE_FILE, "r") as f:
                state = json.load(f)
            concurrency.value = state.get("concurrency", concurrency.value)
            strip_leading_checkbox.value = state.get("strip_leading", strip_leading_checkbox.value)
            normalize_checkbox.value = state.get("normalize", normalize_checkbox.value)
            intro_outro_side.value = state.get("intro_outro_side", intro_outro_side.value)
            intro_seconds.value = state.get("intro_outro_seconds", intro_seconds.value)
            similarity_threshold.value = state.get("intro_outro_threshold", similarity_threshold.value)
            upload_mode_dropdown.value = state.get("upload_mode", upload_mode_dropdown.value)
            sort_dropdown = playlists_ui['sort_dropdown'] if isinstance(playlists_ui, dict) else None
            if sort_dropdown and state.get("playlist_sort"):
                sort_dropdown.value = state["playlist_sort"]
                # Also update the current_sort key in the playlists module and refresh
                playlists_ui['current_sort']['key'] = sort_dropdown.value
        except Exception as e:
            logger.error(f"load_ui_state: failed to read or parse state file: {e}")

    # Controls must be created before loading state
    def show_dev_warning():
        dlg = ft.AlertDialog(
            title=ft.Text("Yoto Up: In Development"),
            content=ft.Column([
            ft.Text(
                "This app is under active development. Features may be incomplete, unstable, or change at any time.\n\nPlease report bugs and use with caution!"
            ),
            ft.TextButton(
                "View on GitHub",
                url="https://github.com/xkjq/yoto-up",
                style=ft.ButtonStyle(color=ft.Colors.BLUE),
            ),
            ]),
            actions=[ft.TextButton("OK", on_click=lambda e: page.close(dlg))],
        )
        page.open(dlg)
        page.update()
    def invalidate_authentication():
        """Invalidate authentication: clear API, hide tabs, switch to Auth tab, and update UI."""
        # Clear API instance
        api_ref["api"] = None
        # Hide Playlists and Upload tabs
        tabs_control.tabs[1].visible = False
        tabs_control.tabs[2].visible = False
        tabs_control.tabs[3].visible = False  # Icons tab
        tabs_control.tabs[4].visible = False  # Editor tab
        # Switch to Auth tab
        tabs_control.selected_index = 0
        # Update instructions/status
        auth_instructions.controls.clear()
        auth_instructions.controls.append(ft.Text(AUTHENTICATE_TEXT, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.RED))
        page.update()
    def switch_to_auth_tab():
        """Switch to the Auth tab (index 0) and update the page."""
        tabs_control.selected_index = 0
        page.update()
    page.switch_to_auth_tab = switch_to_auth_tab
    page.invalidate_authentication = invalidate_authentication

    # Shared runtime state
    # Counters for overall progress
    total_files = 0
    completed_count = 0
    # Shared API instance (so Fetch Playlists can reuse it)
    api_ref = {"api": None}

    # Basic UI controls that many helper functions expect. These are
    # intentionally minimal so we can restore behavior incrementally.
    #client_id = ft.TextField(label="Client ID", value="RslORm04nKbhf04qb91r2Pxwjsn3Hnd5", width=400, disabled=True)
    auth_btn = ft.ElevatedButton(text="Authenticate")
    status = ft.Text("")
    auth_instructions = ft.Column([ft.Text(AUTHENTICATE_TEXT)])

    def show_snack(message: str, error: bool = False, duration: int | None = None):
        print(f"[gui] show_snack: {message}")
        bg = ft.Colors.RED if error else None
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=bg, duration=duration)
        page.open(page.snack_bar)
        page.update()

    overall_bar = ft.ProgressBar(width=400, visible=False)
    overall_text = ft.Text("")
    file_rows_column = ft.Column()

    # File picker and folder controls
    browse = ft.FilePicker()
    browse_files = ft.FilePicker()
    page.overlay.append(browse)
    page.overlay.append(browse_files)
    # When a folder is chosen we will populate file_rows_column
    folder = ft.TextField(label="Folder", width=400)

    # Upload controls
    concurrency = ft.TextField(label="Concurrency", value="4", width=80, on_change=lambda e: save_ui_state())
    strip_leading_checkbox = ft.Checkbox(
        label='Strip leading track numbers',
        value=True,
        tooltip="Remove common leading track number prefixes from filenames (e.g. '01 - ', '1. ', '01)', '001_')",
        on_change=lambda e: save_ui_state(),
    )
    normalize_checkbox = ft.Checkbox(
        label='Normalize audio (loudness)',
        value=False,
        tooltip="Apply loudness normalization (server-side if supported).",
        on_change=lambda e: save_ui_state(),
    )
    intro_outro_side = ft.Dropdown(
        label='Side',
        value='intro',
        options=[ft.dropdown.Option('intro'), ft.dropdown.Option('outro')],
        width=100,
        on_change=lambda e: save_ui_state(),
    )
    intro_seconds = ft.TextField(label='Segment seconds', value='10.0', width=80, on_change=lambda e: save_ui_state())
    similarity_threshold = ft.TextField(label='Similarity threshold', value='0.75', width=80, on_change=lambda e: save_ui_state())
    upload_target_dropdown = ft.Dropdown(
        label='Upload target',
        value='Create new card',
        options=[ft.dropdown.Option('Create new card'), ft.dropdown.Option('Add to existing card')],
    )
    new_card_title = ft.TextField(label='New card title', width=400)

    # Placeholders that will be populated/overwritten by playlists module
    existing_card_dropdown = ft.Dropdown(label='Existing card', options=[])
    existing_card_map = {}

    # Ensure only the relevant upload target control is visible
    try:
        if upload_target_dropdown.value == 'Create new card':
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
            if upload_target_dropdown.value == 'Create new card':
                new_card_title.visible = True
                existing_card_dropdown.visible = False
            else:
                new_card_title.visible = False
                existing_card_dropdown.visible = True

                if existing_card_dropdown and hasattr(existing_card_dropdown, 'options'):
                    # If switching to existing card, and no options are present, try to fetch playlists
                    if (not existing_card_dropdown.options or len(existing_card_dropdown.options) == 0) and callable(fetch_playlists_sync):
                        print("[_on_upload_target_change] existing_card_dropdown empty, calling fetch_playlists_sync to populate")
                        try:
                            # fetch_playlists_sync may be blocking; run in a thread to avoid blocking the UI
                            threading.Thread(target=lambda: fetch_playlists_sync(None), daemon=True).start()
                        except Exception as fe:
                            print(f"[_on_upload_target_change] fetch_playlists_sync failed: {fe}")
            page.update()
        except Exception as exc:
            logger.error(f"[_on_upload_target_change] failed: {exc}")

    upload_target_dropdown.on_change = _on_upload_target_change


    def remove_uploaded_files(ev=None):
        logger.debug("[remove_uploaded_files] Removing uploaded files from the queue")
        file_rows_column.controls = [c for c in file_rows_column.controls if not (hasattr(c, '_fileuploadrow') and getattr(c._fileuploadrow, 'uploaded', False))]
        page.update()

    start_btn = ft.ElevatedButton('Start Upload')
    stop_btn = ft.ElevatedButton('Stop Upload', disabled=True)
    fetch_btn = ft.ElevatedButton('Fetch Playlists')
    multi_select_btn = ft.ElevatedButton('Select Multiple')
    delete_selected_btn = ft.ElevatedButton('Delete Selected', disabled=True)
    export_selected_btn = ft.ElevatedButton('Export Selected', disabled=True)
    remove_uploaded_btn = ft.ElevatedButton('Remove Uploaded', on_click=remove_uploaded_files)

    ## Add Remove Uploaded button to the UI after the action buttons
    #action_buttons_row = ft.Row([
    #    start_btn, stop_btn, fetch_btn, multi_select_btn, delete_selected_btn, export_selected_btn, remove_uploaded_btn
    #])
    #page.add(action_buttons_row)

    def update_overall():
        # update overall progress bar when a file completes
        nonlocal completed_count
        # compute total dynamically from the UI rows to avoid relying on a separate counter
        try:
            total = len([r for r in getattr(file_rows_column, 'controls', []) if getattr(r, 'filename', None)])
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
            existing = set(getattr(row, "filename", None) for row in file_rows_column.controls)
            added = 0
            from yoto_app.upload_tasks import FileUploadRow
            for f in files:
                if f not in existing:
                    try:
                        file_row = FileUploadRow(f, maybe_page=page, maybe_column=file_rows_column)
                        file_rows_column.controls.append(file_row.row)
                    except Exception as e:
                        raise RuntimeError(f"Failed to create FileUploadRow for {f}: {e}")
                    added += 1
            if added == 0 and files:
                print("[populate_file_rows] All files from folder already present in upload list.")
            if not files:
                file_rows_column.controls.append(ft.Text(f"No audio files found in {folder_path}"))
            page.update()
        except Exception:
            logger.error("[populate_file_rows] error")

    def start_device_auth(e, instr=None):
        # Delegate to auth module which will start its own poll thread
        try:
            auth_mod.start_device_auth(page, instr_container=instr or auth_instructions, api_ref=api_ref, show_snack_fn=show_snack)
        except Exception as ex:
            try:
                print(f"[gui] start_device_auth delegate failed: {ex}")
            except Exception:
                pass

    def get_card_id_local(card):
        """Small helper to extract card id from various shapes (model, dict)."""
        try:
            if hasattr(card, 'cardId') and getattr(card, 'cardId'):
                return getattr(card, 'cardId')
            if hasattr(card, 'id') and getattr(card, 'id'):
                return getattr(card, 'id')
            if hasattr(card, 'contentId') and getattr(card, 'contentId'):
                return getattr(card, 'contentId')
            if isinstance(card, dict):
                return card.get('cardId') or card.get('id') or card.get('contentId')
            if hasattr(card, 'model_dump'):
                try:
                    d = card.model_dump(exclude_none=True)
                    return d.get('cardId') or d.get('id') or d.get('contentId')
                except Exception:
                    pass
        except Exception:
            pass
        return None

    # start_uploads and stop_uploads moved to yoto_app.upload_tasks



    def on_pick_result(e: ft.FilePickerResultEvent):
        if e.files:
            # use the first file's folder as the folder path
            first = e.files[0]
            # In desktop mode, path is available as "path"
            if hasattr(first, "path") and first.path:
                folder.value = str(Path(first.path).parent)
                # populate the file rows immediately when a folder is chosen
                try:
                    if folder.value:
                        populate_file_rows(folder.value)
                except Exception:
                    logger.error("on_pick_result: populate_file_rows failed", None)
            else:
                # web mode: save files to temp? For simplicity, just inform user
                folder.value = "(web file picker used - paste local folder path instead)"
            update_show_waveforms_btn()
        page.update()

    def on_pick_files_result(e: ft.FilePickerResultEvent):
        if e.files:
            for f in e.files:
                # Add each selected file to the file_rows_column if not already present
                path = getattr(f, "path", None)
                if path and not any(getattr(row, "filename", None) == path for row in file_rows_column.controls):
                    try:
                        file_row = FileUploadRow(path, maybe_page=page, maybe_column=file_rows_column)
                        file_rows_column.controls.append(file_row.row)
                    except Exception as _:
                        raise RuntimeError(f"Failed to create FileUploadRow for {path}")
            update_show_waveforms_btn()
            page.update()

    browse.on_result = on_pick_result
    browse_files.on_result = on_pick_files_result

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
    playlists_ui = build_playlists_panel(page, api_ref, show_snack, ensure_api, status, overall_bar, overall_text, file_rows_column)
    # extract controls and helpers
    playlists_column = playlists_ui['playlists_column']
    _ = playlists_ui['playlists_list']
    existing_card_dropdown = playlists_ui['existing_card_dropdown']
    existing_card_map = playlists_ui['existing_card_map']
    _ = playlists_ui['fetch_playlists']
    fetch_playlists_sync = playlists_ui['fetch_playlists_sync']
    playlist_fetch_btn = playlists_ui['fetch_btn']
    playlist_multi_select_btn = playlists_ui['multi_select_btn']
    playlist_delete_selected_btn = playlists_ui['delete_selected_btn']
    playlist_export_selected_btn = playlists_ui['export_selected_btn']
    sort_dropdown = playlists_ui['sort_dropdown']
    show_card_details = playlists_ui['show_card_details']
    # Save playlist sort order on change
    if sort_dropdown:
        def _on_sort_change(ev):
            save_ui_state()
        orig_on_change = getattr(sort_dropdown, 'on_change', None)
        if orig_on_change and orig_on_change != _on_sort_change:
            def chained(ev):
                orig_on_change(ev)
                _on_sort_change(ev)
            sort_dropdown.on_change = chained
        else:
            sort_dropdown.on_change = _on_sort_change

    # Context passed into upload tasks implementation
    ctx = {
        'page': page,
        'folder': folder,
        'utils_mod': utils_mod,
        'ensure_api': ensure_api,
        'api_ref': api_ref,
        'concurrency': concurrency,
        'file_rows_column': file_rows_column,
        'overall_bar': overall_bar,
        'overall_text': overall_text,
        'status': status,
        'show_snack': show_snack,
        'update_overall': update_overall,
        'fetch_playlists_sync': fetch_playlists_sync,
        'upload_target_dropdown': upload_target_dropdown,
        'new_card_title': new_card_title,
        'existing_card_dropdown': existing_card_dropdown,
        'existing_card_map': existing_card_map,
    # store the control so the upload task can read current value at start
    'strip_leading_track_numbers_control': strip_leading_checkbox,
    'normalize_audio_control': normalize_checkbox,
    'intro_outro_side_control': intro_outro_side,
    'intro_outro_seconds_control': intro_seconds,
    'intro_outro_threshold_control': similarity_threshold,
    'gain_adjusted_files': gain_adjusted_files,
        'start_btn': start_btn,
        'stop_btn': stop_btn,
        'remove_uploaded_btn': remove_uploaded_btn,
    }

    # Also add the control to the page so user can toggle it
    # We'll insert it near the upload controls later when building the upload panel

    def _start_click(e):
        # update ctx with the current checkbox value
        try:
            ctx['strip_leading_track_numbers'] = bool(strip_leading_checkbox.value)
        except Exception:
            ctx['strip_leading_track_numbers'] = True
        try:
            ctx['normalize_audio'] = bool(normalize_checkbox.value)
        except Exception:
            ctx['normalize_audio'] = False
        # intro/outro analysis is manual via the Analyze dialog; no automatic flag
        try:
            ctx['intro_outro_side'] = str(intro_outro_side.value or 'intro')
        except Exception:
            ctx['intro_outro_side'] = 'intro'
        try:
            ctx['intro_outro_seconds'] = float(intro_seconds.value or 10.0)
        except Exception:
            ctx['intro_outro_seconds'] = 10.0
        try:
            ctx['intro_outro_threshold'] = float(similarity_threshold.value or 0.75)
        except Exception:
            ctx['intro_outro_threshold'] = 0.75
        run_coro_in_thread(upload_start, e, ctx)

    start_btn.on_click = _start_click
    stop_btn.on_click = lambda e: run_coro_in_thread(upload_stop, e, ctx)
    fetch_btn.on_click = lambda e: threading.Thread(target=lambda: fetch_playlists_sync(e), daemon=True).start()
    # Run the auth starter in a background thread so the UI remains responsive
    def _auth_click(e):
        print("[gui] Authenticate button clicked")
        status.value = "Starting authentication..."
        # show preparing text in the embedded instructions area
        try:
            auth_instructions.controls.clear()
            auth_instructions.controls.append(ft.Text("Preparing authentication..."))
        except Exception:
            pass
        page.update()

        def _auth_bg_runner(evt, instr):
            try:
                logger.debug("[gui] auth background thread started")
                start_device_auth(evt, instr)
                logger.debug("[gui] auth background thread finished")
            except Exception:
                logger.error("[gui] auth background thread exception:\n", traceback.format_exc())

        threading.Thread(target=lambda: _auth_bg_runner(e, auth_instructions), daemon=True).start()

    auth_btn.on_click = _auth_click

    # Auth page (separate from uploads) — include embedded instructions area
    # Add reset auth buttons to allow clearing saved tokens and optionally reauthenticating
    def reset_auth_gui(e, reauth: bool = False):
        """Show confirmation, then perform token reset while disabling the reset buttons.

        Runs the actual work in a background thread so the UI remains responsive.
        """
        # Background worker that performs the reset and optionally reauths


        # Confirmation dialog handlers
        dlg = ft.AlertDialog(
            title=ft.Text("Confirm Reset Authentication"),
            content=ft.Text("This will remove saved authentication tokens (tokens.json) and sign out. Continue?"),
            actions=[],
        )

        def _cancel(ev):
            try:
                page.close(dlg)
            except Exception:
                pass

        def _confirm(ev):
            try:
                page.close(dlg)
            except Exception:
                pass
            # Start background reset so the UI remains responsive
            # threading.Thread(target=_do_reset, daemon=True).start()

        dlg.actions = [
            ft.TextButton("Cancel", on_click=_cancel),
            ft.TextButton("Confirm", on_click=_confirm),
        ]

        page.open(dlg)
        page.update()

    reset_btn = ft.TextButton("Reset Auth", on_click=lambda e: reset_auth_gui(e, reauth=False))
    reset_and_reauth_btn = ft.TextButton("Reset & Reauth", on_click=lambda e: reset_auth_gui(e, reauth=True))

    auth_column = ft.Column([
        ft.Row([auth_btn, reset_btn, reset_and_reauth_btn]),
        ft.Divider(),
        ft.Text("Instructions:"),
        auth_instructions,
    ], scroll=ft.ScrollMode.AUTO, expand=True)


    if upload_target_dropdown.value == 'Create new card':
        new_card_title.visible = True
        existing_card_dropdown.visible = False
    else:
        new_card_title.visible = False
        existing_card_dropdown.visible = True
    page.update()

    # Ensure the original header buttons are present in the playlists header
    try:
        header = playlists_column.controls[0] if playlists_column and len(playlists_column.controls) > 0 else None
        if header and hasattr(header, 'controls'):
            try:
                hdr = list(header.controls)
                existing_texts = [getattr(c, 'text', None) for c in hdr]
                if 'Fetch Playlists' not in existing_texts:
                    insert_at = 1
                    # prefer buttons returned from playlists module
                    hdr[insert_at:insert_at] = [playlist_fetch_btn or fetch_btn, playlist_multi_select_btn or multi_select_btn, playlist_delete_selected_btn or delete_selected_btn, playlist_export_selected_btn or export_selected_btn]
                    header.controls = hdr
            except Exception as e:
                logger.error(f"[_on_playlists_header_merge] failed: {e}")
    except Exception:
        pass

    # Upload page (appears after Playlists)
    # Add a dropdown to select upload mode: Chapters or Tracks
    upload_mode_dropdown = ft.Dropdown(
        label='Upload as',
        value='Chapters',
        options=[
            ft.dropdown.Option('Chapters'),
            ft.dropdown.Option('Tracks')
        ],
        width=150,
        on_change=lambda e: save_ui_state(),
    )

    # Now load state after controls are created
    load_ui_state(playlists_ui)
    ctx['upload_mode_dropdown'] = upload_mode_dropdown  # Add to context for upload tasks

    # Card info/link display (persistent at bottom)
    card_info_display = ft.Column([], visible=False)

    def show_card_popup(card):
        # Show a dialog with full card details
        from flet import AlertDialog, Text, Column, TextButton, Image
        lines = []
        lines.append(Text(f"Title: {getattr(card, 'title', '')}", size=18, weight=ft.FontWeight.BOLD))
        lines.append(Text(f"Card ID: {getattr(card, 'cardId', '')}", size=14))
        if getattr(card, 'metadata', None):
            meta = card.metadata
            if getattr(meta, 'author', None):
                lines.append(Text(f"Author: {meta.author}"))
            if getattr(meta, 'description', None):
                lines.append(Text(f"Description: {meta.description}"))
            if getattr(meta, 'note', None):
                lines.append(Text(f"Note: {meta.note}"))
            if getattr(meta, 'cover', None) and getattr(meta.cover, 'imageL', None):
                lines.append(Image(src=meta.cover.imageL, width=120, height=120))
        if getattr(card, 'content', None) and getattr(card.content, 'chapters', None):
            lines.append(Text("Chapters:", weight=ft.FontWeight.BOLD))
            for ch in card.content.chapters:
                lines.append(Text(f"- {getattr(ch, 'title', '')}"))
        lines.append(TextButton("View card", on_click=lambda e: show_card_details(e, card), style=ft.ButtonStyle(color=ft.Colors.BLUE)))
        dlg = AlertDialog(
            title=Text("Card Details"),
            content=Column(lines, scroll=ft.ScrollMode.AUTO, expand=True),
            actions=[TextButton("Close", on_click=lambda e: page.close(dlg))],
            scrollable=True
        )
        page.open(dlg)
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

        if not card or not getattr(card, 'cardId', None):
            row = ft.Row([
                ft.Text("No card info available", color=ft.Colors.RED),
                ft.TextButton("Dismiss", on_click=lambda e: dismiss_item(row), style=ft.ButtonStyle(color=ft.Colors.RED))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            card_info_display.controls.append(row)
        else:
            summary = ft.Container(
                content=ft.Row([
                    ft.Text(getattr(card, 'title', ''), size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(f"ID: {getattr(card, 'cardId', '')}", size=12, color=ft.Colors.GREY),
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.BLUE),
                    ft.TextButton("Dismiss", on_click=lambda e: dismiss_item(summary), style=ft.ButtonStyle(color=ft.Colors.RED))
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                on_click=lambda e: show_card_popup(card),
                bgcolor=ft.Colors.BLUE_50,
                padding=10,
                border_radius=8,
                ink=True,
                tooltip="Click for card details"
            )
            card_info_display.controls.append(summary)
        card_info_display.visible = True
        page.update()

    # Patch into ctx so upload_tasks can update it
    ctx['show_card_info'] = show_card_info

    show_waveforms_btn = ft.TextButton(
        "Show Waveforms",
        on_click=show_waveforms_popup_wrapper,
        tooltip="Visualize sound levels for all files in the queue",
        disabled=True
    )

    # Analyze/trim button for intro/outro detection
    analyze_intro_btn = ft.ElevatedButton("Analyze intro/outro")

    async def _do_analysis_and_show_dialog(dialog_controls):
        """Perform analysis using settings from dialog_controls and update dialog content.

        dialog_controls should contain:
          - 'intro_outro_side': Dropdown
          - 'intro_seconds': TextField
          - 'similarity_threshold': TextField
          - 'content_column': Column to place results into
        """
        # gather files from the UI queue
        files = [getattr(r, 'filename', None) for r in file_rows_column.controls if getattr(r, 'filename', None)]
        files = [f for f in files if f]
        if not files:
            show_snack('No files in queue to analyze', error=False)
            return

        # import here so missing dependency only affects this feature
        try:
            from yoto_app.intro_outro import per_window_common_prefix, trim_audio_file
        except Exception:
            show_snack('Intro/outro analysis unavailable (missing module)', error=True)
            return

        # read config from dialog controls
        side = dialog_controls['intro_outro_side'].value or 'intro'
        seconds = float(dialog_controls['intro_seconds'].value or 10.0)
        thresh = float(dialog_controls['similarity_threshold'].value or 0.75)
        try:
            padding_seconds = float(dialog_controls.get('padding_seconds').value or 0.25)
        except Exception:
            padding_seconds = 0.25
        padding_ms = int(padding_seconds * 1000)

        # Show spinner in the dialog's content column so the main dialog stays open
        content_col = dialog_controls['content_column']
        content_col.controls.clear()
        content_col.controls.append(ft.Row([ft.ProgressRing(), ft.Text('Analyzing files...')], alignment=ft.MainAxisAlignment.CENTER))
        try:
            page.update()
        except Exception:
            pass

        # run analysis off the UI thread
        try:
            # Use windowed analyzer (configurable window size / sub-second precision)
            try:
                fast_mode_ctrl = dialog_controls.get('fast_mode')
                try:
                    fast_mode = bool(getattr(fast_mode_ctrl, 'value', True))
                except Exception:
                    fast_mode = True
                sr = 11025 if fast_mode else 22050
                n_mfcc = 13
                # read windowed controls
                ws_ctrl = dialog_controls.get('window_seconds')
                mx_ctrl = dialog_controls.get('max_seconds_window')
                sim_ctrl = dialog_controls.get('window_similarity')
                mf_ctrl = dialog_controls.get('window_min_files')
                try:
                    window_seconds = float(getattr(ws_ctrl, 'value', 0.25))
                except Exception:
                    window_seconds = 0.25
                try:
                    max_seconds = float(getattr(mx_ctrl, 'value', seconds))
                except Exception:
                    max_seconds = float(seconds)
                try:
                    similarity_threshold = float(getattr(sim_ctrl, 'value', 0.95))
                except Exception:
                    similarity_threshold = 0.95
                try:
                    min_files_fraction = float(getattr(mf_ctrl, 'value', 0.75))
                except Exception:
                    min_files_fraction = 0.75

                result = await asyncio.to_thread(
                    lambda: per_window_common_prefix(paths=files, side=side, max_seconds=max_seconds, window_seconds=window_seconds, sr=sr, n_mfcc=n_mfcc, similarity_threshold=similarity_threshold, min_files_fraction=min_files_fraction)
                )
            except Exception as e:
                raise
        except Exception as e:
            # analysis failed — update the dialog content column rather than trying
            # to close a previously-used helper dialog (analyzing_dlg no longer exists)
            show_snack(f'Analysis failed: {e}', error=True)
            return

    # populate result content in the same dialog content column
        # The new windowed analyzer returns per-window similarities and a
        # contiguous matched window count. Use that to compute the common
        # removal seconds and per-file match fractions for UI presentation.
        content_col.controls.clear()
        windows_matched = int(result.get('windows_matched', 0))
        seconds_matched = float(result.get('seconds_matched', 0.0))
        per_window_frac = result.get('per_window_frac', [])
        per_file_per_window = result.get('per_file_per_window', {})

        if windows_matched <= 0 or seconds_matched <= 0.0:
            content_col.controls.append(ft.Text('No common intro/outro detected'))
            try:
                page.update()
            except Exception:
                pass
            return

        # Update the computed removal field so the user can tweak it before trimming
        try:
            comp_ctrl = dialog_controls.get('computed_removal')
            if comp_ctrl is not None:
                comp_ctrl.value = f"{seconds_matched:.2f}"
                try:
                    setattr(comp_ctrl, '_computed_by_analysis', True)
                except Exception:
                    pass
                try:
                    page.update()
                except Exception:
                    pass
        except Exception:
            pass

        content_col.controls.append(ft.Text(f"Planned removal: from start up to {seconds_matched:.2f}s (same for all matched files)"))
        # Persist a small debug JSON so the preview/trim actions can be inspected
        try:
            debug_dir = Path('.tmp_trim') / 'previews'
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / ('intro_removal.json')
            try:
                with open(debug_path, 'w') as _df:
                    import json as _json
                    _json.dump({'common_removal_end_sec': seconds_matched, 'per_window_frac': per_window_frac}, _df, indent=2)
            except Exception:
                pass
        except Exception:
            pass

        # build per-file score based on how many of the matched windows each
        # file satisfied (i.e. per-window similarity >= configured threshold)
        checkbox_map = {}
        try:
            sim_thresh = float(dialog_controls.get('window_similarity').value or 0.95)
        except Exception:
            sim_thresh = 0.95
        for p, perw in per_file_per_window.items():
            try:
                # consider only the windows that were accepted
                relevant = perw[:windows_matched]
                matched = sum(1 for v in relevant if v >= sim_thresh)
                score = float(matched) / float(windows_matched) if windows_matched else 0.0
            except Exception:
                score = 0.0
            score_label = f"{score * 100:.2f}%"
            cb = ft.Checkbox(label=f"{p} (score={score_label})", value=(score >= float(dialog_controls.get('window_min_files').value or 0.75)))
            checkbox_map[p] = cb

            # Preview button: extract the matched segment into a temp file and play it
            preview_btn = ft.TextButton('Preview', on_click=None, tooltip='Preview the matched intro/outro segment')

            def make_preview_handler(path, preview_button, seg_seconds, side_label):
                def _on_preview(ev=None):
                    try:
                        preview_button.disabled = True
                        page.update()
                    except Exception:
                        pass

                    # Create a preview dialog so the user sees progress while we extract
                    preview_content = ft.Column([ft.Row([ft.ProgressRing(), ft.Text('Preparing preview...')], alignment=ft.MainAxisAlignment.CENTER)], scroll=ft.ScrollMode.AUTO)
                    preview_dlg = ft.AlertDialog(title=ft.Text('Preview'), content=preview_content, actions=[ft.TextButton('Close', on_click=lambda e: page.close(preview_dlg))], modal=True)
                    try:
                        page.open(preview_dlg)
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

                            if side == 'intro':
                                # preview the start portion that would be removed from all files
                                segment = audio[0:common_ms]
                            else:
                                # preview the tail portion that would be removed from all files
                                if common_ms <= len(audio):
                                    segment = audio[-common_ms:]
                                else:
                                    segment = audio
                            temp_dir = Path('.tmp_trim') / 'previews'
                            temp_dir.mkdir(parents=True, exist_ok=True)
                            preview_path = temp_dir / (Path(src).stem + '.preview' + Path(src).suffix)
                            try:
                                # Best-effort: write original-format preview
                                segment.export(str(preview_path), format=preview_path.suffix.lstrip('.'))
                            except Exception:
                                # non-fatal
                                pass

                            # Ensure we create a WAV preview for reliable playback
                            preview_wav = temp_dir / (Path(src).stem + '.preview.wav')
                            wav_ok = False
                            try:
                                segment.export(str(preview_wav), format='wav')
                                wav_ok = preview_wav.exists()
                            except Exception:
                                wav_ok = False

                            # Fallback: if original-format preview written, try converting that to WAV
                            if not wav_ok and preview_path.exists():
                                try:
                                    tmp_seg = AudioSegment.from_file(str(preview_path))
                                    tmp_seg.export(str(preview_wav), format='wav')
                                    wav_ok = preview_wav.exists()
                                except Exception:
                                    wav_ok = False

                            # Close the preparing dialog
                            try:
                                page.close(preview_dlg)
                            except Exception:
                                pass

                            # Build result dialog with Play (enabled only if WAV exists) and Open buttons
                            def make_result_dialog(wav_available: bool):
                                items = [ft.Text(f'Preview: {Path(src).name}')] 

                                if wav_available or segment is not None:
                                    def _play(e=None, p=preview_wav, seg=segment):
                                        def _play_thread():
                                            # Prefer playing the in-memory pydub segment via simpleaudio so we play exactly the removed segment
                                            if HAS_SIMPLEAUDIO and _simpleaudio is not None and seg is not None:
                                                try:
                                                    sa_mod = _simpleaudio
                                                    # pydub AudioSegment stores raw_data, frame_rate, channels, sample_width
                                                    raw = seg.raw_data
                                                    channels = seg.channels
                                                    sample_width = seg.sample_width
                                                    frame_rate = seg.frame_rate
                                                    wave_obj = sa_mod.WaveObject(raw, channels, sample_width, frame_rate)
                                                    play_obj = wave_obj.play()
                                                    play_obj.wait_done()
                                                    return
                                                except Exception:
                                                    pass
                                            # Fallback to calling an external player on the WAV file we wrote
                                            cmds = [
                                                ['ffplay', '-nodisp', '-autoexit', str(p)],
                                                ['aplay', str(p)],
                                                ['xdg-open', str(p)],
                                            ]
                                            for cmd in cmds:
                                                try:
                                                    subprocess.run(cmd, check=True)
                                                    return
                                                except Exception:
                                                    continue
                                            show_snack('No available player found (ffplay/aplay/xdg-open)', error=True)
                                        threading.Thread(target=_play_thread, daemon=True).start()
                                    items.append(ft.ElevatedButton('Play', on_click=_play))
                                else:
                                    items.append(ft.Text('Preview playback not available (conversion failed)'))

                                def _open_external(e=None):
                                    try:
                                        target = preview_wav if wav_available and preview_wav.exists() else preview_path
                                        webbrowser.open(Path(target).resolve().as_uri())
                                    except Exception as ex:
                                        show_snack(f'Failed to open preview: {ex}', error=True)

                                items.append(ft.TextButton('Open in external player', on_click=_open_external))
                                # Show the absolute path so users can verify which file will be opened/played
                                try:
                                    display_target = preview_wav if wav_available and preview_wav.exists() else preview_path
                                    items.append(ft.Text(str(Path(display_target).resolve()), size=12))
                                except Exception:
                                    pass
                                items.append(ft.TextButton('Close', on_click=lambda e: page.close(result_dlg)))
                                content = ft.Column(items, scroll=ft.ScrollMode.AUTO)
                                return ft.AlertDialog(title=ft.Text('Preview'), content=content, actions=[items[-1]], modal=True)

                            try:
                                result_dlg = make_result_dialog(wav_ok)
                                page.open(result_dlg)
                                page.update()
                            except Exception:
                                try:
                                    # fallback: open any file we have
                                    target = preview_wav if wav_ok and preview_wav.exists() else preview_path
                                    webbrowser.open(Path(target).resolve().as_uri())
                                except Exception:
                                    pass
                        except Exception as ex:
                            show_snack(f'Preview failed: {ex}', error=True)
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
            content_col.controls.append(ft.Row([cb, preview_btn], alignment=ft.MainAxisAlignment.START))

        # trim handler: shows a trimming dialog and runs trimming in background
        def do_trim(ev=None):
            total_to_trim = sum(1 for p, cb in checkbox_map.items() if cb.value)
            if total_to_trim == 0:
                show_snack('No files selected for trimming', error=False)
                return

            # Safety: if the computed removal is non-zero, require explicit confirmation
            try:
                comp_ctrl = dialog_controls.get('computed_removal')
                confirm_ctrl = dialog_controls.get('confirm_removal')
                comp_val = 0.0
                try:
                    comp_val = float(getattr(comp_ctrl, 'value', seconds_matched))
                except Exception:
                    comp_val = float(seconds_matched) if seconds_matched is not None else 0.0
                if comp_val > 0.0 and not (confirm_ctrl and getattr(confirm_ctrl, 'value', False)):
                    show_snack('Computed removal is >0s — check "Confirm removal" to enable trimming.', error=False)
                    return
            except Exception:
                pass
            # Define the trimming worker up-front so it can be started from the
            # confirmation dialog. It will open its own progress dialog.
            def _trim_worker():
                trim_progress = ft.ProgressBar(width=400, value=0.0, visible=True)
                trim_label = ft.Text(f'Trimming 0/{total_to_trim}')
                trim_dlg = ft.AlertDialog(title=ft.Text('Trimming...'), content=ft.Column([trim_label, trim_progress]), actions=[])
                try:
                    page.open(trim_dlg)
                    page.update()
                except Exception:
                    pass

                temp_dir = Path('.tmp_trim')
                temp_dir.mkdir(parents=True, exist_ok=True)
                trimmed_count = 0
                for p, cb in checkbox_map.items():
                    if not cb.value:
                        continue

                    # set row status to trimming
                    for ctrl in list(file_rows_column.controls):
                        fur = getattr(ctrl, '_fileuploadrow', None)
                        try:
                            if fur and (getattr(fur, 'original_filepath', None) == p or getattr(fur, 'filepath', None) == p or getattr(ctrl, 'filename', None) == p):
                                fur.set_status('Trimming...')
                                fur.set_progress(0.0)
                        except Exception:
                            pass

                        try:
                            # Use the analysis-computed common_removal_end_sec by default.
                            # Only honor the user-edited computed_removal field when the
                            # "Confirm removal" checkbox is checked — this prevents accidental
                            # trimming of the full inspected window.
                            remove_t = 0.0
                            try:
                                confirm_ctrl = dialog_controls.get('confirm_removal')
                                comp_ctrl = dialog_controls.get('computed_removal')
                                confirmed = bool(getattr(confirm_ctrl, 'value', False))
                            except Exception:
                                confirmed = False
                                comp_ctrl = None

                            if confirmed and comp_ctrl is not None:
                                # user explicitly confirmed; try to parse their value
                                try:
                                    remove_t = float(getattr(comp_ctrl, 'value', seconds_matched))
                                except Exception:
                                    remove_t = float(seconds_matched) if seconds_matched is not None else 0.0
                            else:
                                # default: use the analysis-computed value (conservative)
                                try:
                                    remove_t = float(seconds_matched)
                                except Exception:
                                    remove_t = 0.0
                            src_path = Path(p)
                            dest = str(temp_dir / (src_path.stem + '.trimmed' + src_path.suffix))
                            # Safety: avoid trimming the full inspected window unless the user confirmed
                            try:
                                confirm_ctrl = dialog_controls.get('confirm_removal')
                                if remove_t >= float(seconds) - 1e-6 and not (confirm_ctrl and getattr(confirm_ctrl, 'value', False)):
                                    try:
                                        show_snack('Attempt to trim full inspected window detected; skipping trim for safety. Check "Confirm removal" to allow removing the full window.', error=False)
                                    except Exception:
                                        pass
                                    # skip trimming for this file
                                    continue
                            except Exception:
                                pass

                            # keep a small left padding (in ms) so we don't cut too aggressively
                            trim_audio_file(
                                p,
                                dest,
                                remove_intro_seconds=remove_t if side == 'intro' else 0.0,
                                remove_outro_seconds=remove_t if side == 'outro' else 0.0,
                                keep_silence_ms=padding_ms,
                            )

                            # update matching rows to point to trimmed file
                            for ctrl in list(file_rows_column.controls):
                                fur = getattr(ctrl, '_fileuploadrow', None)
                                try:
                                    if fur and (getattr(fur, 'original_filepath', None) == p or getattr(fur, 'filepath', None) == p or getattr(ctrl, 'filename', None) == p):
                                        fur.update_file(dest)
                                        fur.set_status('Trimmed intro/outro')
                                        fur.set_progress(1.0)
                                except Exception:
                                    pass
                        except Exception as e:
                            # report error on affected rows
                            for ctrl in list(file_rows_column.controls):
                                fur = getattr(ctrl, '_fileuploadrow', None)
                                try:
                                    if fur and (getattr(fur, 'original_filepath', None) == p or getattr(fur, 'filepath', None) == p or getattr(ctrl, 'filename', None) == p):
                                        fur.set_status(f'Trim error: {e}')
                                except Exception:
                                    pass

                    trimmed_count += 1
                    # update progress UI
                    try:
                        trim_progress.value = (trimmed_count / total_to_trim) if total_to_trim else 1.0
                        trim_label.value = f'Trimming {trimmed_count}/{total_to_trim}'
                        page.update()
                    except Exception:
                        pass

                try:
                    page.close(trim_dlg)
                    page.update()
                except Exception:
                    pass
                show_snack('Trim complete')

            # If computed removal is > 0 (and the earlier checkbox guard passed),
            # show a final confirmation modal summarizing the action. The user
            # must click "Proceed" to actually start the trimming worker.
            try:
                if comp_val > 0.0:
                    confirm_text = ft.Text(f'You are about to trim {comp_val:.2f}s from {total_to_trim} file(s).\n\nThis will modify the selected files. Proceed?')
                    def _on_proceed(e=None):
                        try:
                            page.close(confirm_dlg)
                        except Exception:
                            pass
                        # start the trimming worker after closing the confirm dialog
                        threading.Thread(target=_trim_worker, daemon=True).start()

                    def _on_cancel(e=None):
                        try:
                            page.close(confirm_dlg)
                        except Exception:
                            pass

                    proceed_btn = ft.ElevatedButton('Proceed', on_click=_on_proceed)
                    cancel_btn = ft.TextButton('Cancel', on_click=_on_cancel)
                    confirm_dlg = ft.AlertDialog(title=ft.Text('Confirm trimming'), content=confirm_text, actions=[proceed_btn, cancel_btn])
                    page.open(confirm_dlg)
                    page.update()
                else:
                    # No removal requested (0s) — start trimming immediately
                    threading.Thread(target=_trim_worker, daemon=True).start()
            except Exception:
                # Fallback: start trimming if anything goes wrong showing the modal
                threading.Thread(target=_trim_worker, daemon=True).start()

        # If the opener provided a dialog action button, enable and wire it
        try:
            trim_btn = dialog_controls.get('trim_button')
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
        # Build dialog controls (local to this dialog)
        d_side = ft.Dropdown(label='Side', value='intro', options=[ft.dropdown.Option('intro'), ft.dropdown.Option('outro')], width=120)
        d_seconds = ft.TextField(label='Segment seconds', value='10.0', width=100)
        d_thresh = ft.TextField(label='Similarity threshold', value='0.75', width=100)
        # Small padding to keep at the start when trimming so we don't cut too aggressively
        d_padding = ft.TextField(label='Left padding (s)', value='0.25', width=100)
        d_fast = ft.Checkbox(label='Fast mode (lower quality, faster)', value=True)
        d_refine = ft.Checkbox(label='Refine with DTW (slower, stricter)', value=False)
        d_dtw_thresh = ft.TextField(label='DTW similarity threshold', value='0.5', width=100)
        # New controls: per-frame agreement tuning
        d_frame_agree = ft.TextField(label='Frame agreement fraction', value='0.70', width=120)
        d_min_files_frame = ft.TextField(label='Min files meeting frame agreement', value='0.75', width=120)
        # Windowed analysis controls (sub-second precision)
        d_window_seconds = ft.TextField(label='Window seconds', value='0.25', width=120)
        d_max_seconds = ft.TextField(label='Max inspect seconds', value='10.0', width=120)
        d_window_similarity = ft.TextField(label='Window similarity threshold', value='0.95', width=120)
        d_window_min_files = ft.TextField(label='Min files fraction', value='0.75', width=120)
        # Editable computed removal so user can override before trimming
        d_computed_removal = ft.TextField(label='Computed removal (s)', value='0.00', width=120)
        d_confirm_removal = ft.Checkbox(label='Confirm removal', value=False)
        content_column = ft.Column([], scroll=ft.ScrollMode.AUTO)

        def on_run(ev=None):
            # Kick off analysis inside the dialog — run the coroutine in a thread
            dlg_controls = {
                'intro_outro_side': d_side,
                'intro_seconds': d_seconds,
                'similarity_threshold': d_thresh,
                'padding_seconds': d_padding,
                'fast_mode': d_fast,
                'refine_with_dtw': d_refine,
                'dtw_threshold': d_dtw_thresh,
                'frame_agreement_fraction': d_frame_agree,
                'min_files_frame_fraction': d_min_files_frame,
                'window_seconds': d_window_seconds,
                'max_seconds_window': d_max_seconds,
                'window_similarity': d_window_similarity,
                'window_min_files': d_window_min_files,
                'computed_removal': d_computed_removal,
                'confirm_removal': d_confirm_removal,
                'content_column': content_column,
                'trim_button': trim_btn,
            }

            def _runner():
                try:
                    asyncio.run(_do_analysis_and_show_dialog(dlg_controls))
                except Exception as ex:
                    show_snack(f'Analysis error: {ex}', error=True)

            threading.Thread(target=_runner, daemon=True).start()

        run_btn = ft.ElevatedButton('Run analysis', on_click=on_run)
        # Windowed analysis runner
        def on_run_window(ev=None):
            dlg_controls = {
                'window_seconds': d_window_seconds,
                'max_seconds_window': d_max_seconds,
                'window_similarity': d_window_similarity,
                'window_min_files': d_window_min_files,
                'content_column': content_column,
            }

            def _runner():
                try:
                    # import here to avoid circular top-level imports
                    from yoto_app.intro_outro import per_window_common_prefix
                    # collect paths from current queued files
                    paths = [getattr(row, 'filename', None) or getattr(getattr(row, '_fileuploadrow', None), 'original_filepath', None) for row in file_rows_column.controls]
                    paths = [p for p in paths if p]
                    if not paths:
                        show_snack('No files in queue to analyze', error=False)
                        return
                    try:
                        ws = float(getattr(dlg_controls['window_seconds'], 'value', 0.25))
                    except Exception:
                        ws = 0.25
                    try:
                        mx = float(getattr(dlg_controls['max_seconds_window'], 'value', 10.0))
                    except Exception:
                        mx = 10.0
                    try:
                        sim = float(getattr(dlg_controls['window_similarity'], 'value', 0.95))
                    except Exception:
                        sim = 0.95
                    try:
                        mf = float(getattr(dlg_controls['window_min_files'], 'value', 0.75))
                    except Exception:
                        mf = 0.75

                    content_column.controls.clear()
                    content_column.controls.append(ft.Text('Running windowed analysis...'))
                    page.update()

                    res = per_window_common_prefix(paths=paths, side=getattr(d_side, 'value', 'intro'), max_seconds=mx, window_seconds=ws, sr=11025 if getattr(d_fast, 'value', True) else 22050, n_mfcc=13, similarity_threshold=sim, min_files_fraction=mf)

                    # show summary and add Open Trace button
                    content_column.controls.clear()
                    content_column.controls.append(ft.Text(f"Matched seconds: {res.get('seconds_matched', 0.0):.2f} (windows: {res.get('windows_matched',0)})"))
                    content_column.controls.append(ft.Text(f"Per-window fractions: {res.get('per_window_frac', [])}"))

                    def _open_trace(e=None):
                        try:
                            import webbrowser
                            p = Path('.tmp_trim/previews') / 'per_window_trace.json'
                            if p.exists():
                                webbrowser.open(p.resolve().as_uri())
                            else:
                                show_snack('Trace not found', error=True)
                        except Exception as ex:
                            show_snack(f'Failed to open trace: {ex}', error=True)

                    content_column.controls.append(ft.TextButton('Open trace', on_click=_open_trace))
                    page.update()
                except Exception as ex:
                    show_snack(f'Windowed analysis failed: {ex}', error=True)

            threading.Thread(target=_runner, daemon=True).start()

        run_window_btn = ft.ElevatedButton('Run windowed analysis', on_click=on_run_window)
        # Trim action placed as a dialog action, initially disabled until analysis finds matches
        trim_btn = ft.ElevatedButton('Trim selected', disabled=True)
        close_btn = ft.TextButton('Close', on_click=lambda e: page.close(dlg))

        dlg = ft.AlertDialog(
            title=ft.Text('Analyze intro/outro'),
            content=ft.Column([
                ft.Row([d_side, d_seconds, d_thresh, d_padding, d_fast]),
                ft.Row([d_refine, d_dtw_thresh, d_computed_removal]),
                ft.Row([d_frame_agree, d_min_files_frame]),
                ft.Row([d_window_seconds, d_max_seconds, d_window_similarity, d_window_min_files]),
                ft.Row([d_confirm_removal]),
                ft.Divider(),
                content_column
            ], scroll=ft.ScrollMode.AUTO),
            actions=[run_btn, run_window_btn, trim_btn, close_btn],
        )
        # expose dlg to inner closures
        page.open(dlg)
        page.update()

    analyze_intro_btn.on_click = open_analysis_dialog

    def update_show_waveforms_btn():
        # Enable if there are any files in the upload queue
        has_files = any(getattr(row, 'filename', None) for row in file_rows_column.controls)
        show_waveforms_btn.disabled = not has_files
        page.update()

    upload_column = ft.Column([
        ft.Row([
            upload_target_dropdown, 
            new_card_title, 
            existing_card_dropdown
        ]),
        ft.Row([
            concurrency,
            strip_leading_checkbox,
            normalize_checkbox,
            upload_mode_dropdown  # Add the new dropdown here
        ]),
        ft.Row([
            folder, 
            ft.TextButton("Browse Folder...", on_click=lambda e: browse.pick_files(allow_multiple=True)),
            ft.TextButton("Add Files...", on_click=lambda e: browse_files.pick_files(allow_multiple=True)),
            ft.TextButton("Clear Queue", on_click=clear_queue),
            show_waveforms_btn,
            analyze_intro_btn,
            ft.IconButton(
                icon=ft.Icons.HELP_OUTLINE,
                tooltip="Help: Select a folder or specific files to upload.",
                on_click=lambda e: show_snack(
                    "Select the folder containing your audio files, or add specific files. 'Browse Folder...' lets you pick a folder (you may have to select a file within the folder), or paste the path directly. 'Add Files...' lets you pick individual files.\n\nChoose 'Chapters' to upload files as chapters, or 'Tracks' to upload as tracks. Once uploaded it is possible to convert between Chapters and tracks",
                    error=False,
                    duration=10000

                )
            )
        ]),
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
        card_info_display
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    # Use Tabs so Auth, Playlists and Upload are on separate pages

    # Add About button to the top right
    about_btn = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE,
        tooltip="About Yoto Up",
        on_click=show_about_dialog,
        style=ft.ButtonStyle(color=ft.Colors.BLUE),
    )

    # Create tabs and keep a reference so we can enable/disable them
    # Build icon browser panel and add as a tab
    icon_browser_ui = build_icon_browser_panel(page=page, api_ref=api_ref, ensure_api=ensure_api, show_snack=show_snack)
    icon_panel = icon_browser_ui.get('panel') if isinstance(icon_browser_ui, dict) else None

    # Instantiate PixelArtEditor and expose as a dedicated tab on the main page
    try:
        editor = PixelArtEditor(page=page)
        editor_tab = editor.as_tab("Editor") or editor.as_tab("Icon Editor")
        # keep a reference on the page for external callers if needed
        page.pixel_editor = editor
    except Exception:
        editor = None
        editor_tab = None

    tabs_control = ft.Tabs(
         selected_index=0,
         tabs=[
             ft.Tab(text="Auth", content=auth_column),
             ft.Tab(text="Playlists", content=playlists_column, visible=False),
             ft.Tab(text="Upload", content=upload_column, visible=False),
             ft.Tab(text="Icons", content=icon_panel, visible=False),
             # Editor tab (if created) - inserted before Icons
             editor_tab if editor_tab is not None else ft.Tab(text="Editor", content=ft.Text("Editor unavailable")),
         ],
         expand=True,
     )
    # Place About button above tabs
    page.add(ft.Row([ft.Text("Yoto Up", size=22, weight=ft.FontWeight.BOLD, expand=True), about_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
    page.add(tabs_control)
    show_dev_warning()

    def auth_complete():
        print("Auth complete")
        tabs_control.tabs[1].visible = True
        tabs_control.tabs[2].visible = True
        tabs_control.tabs[3].visible = True  # Icons tab
        tabs_control.tabs[4].visible = True  # Editor tab

        api = api_ref.get("api")
        if api:
            api.get_public_icons(show_in_console=False)
        #api.get_user_icons(show_in_console=False)
        # Always use the local page variable, not the argument
        page.update()
    page.auth_complete = auth_complete

    # Now that the UI controls are added to the page, try to reuse tokens.json (if present)
    try:
        tokens_path = Path("tokens.json")
        if tokens_path.exists():
            def _init_api_from_tokens():
                try:
                    api = ensure_api(api_ref)
                    api_ref["api"] = api
                    show_snack("Authenticated (from tokens.json)")
                    # Replace instructions with a prominent success message
                    auth_instructions.controls.clear()
                    auth_instructions.controls.append(
                        ft.Text("Authenticated (from tokens.json)", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)
                    )
                    auth_complete()
                except Exception as e:
                    status.value = f"Tokens present but API init failed: {e}"
                    show_snack(f"API init from tokens.json failed: {e}", error=True)
                    print("[gui] init_api_from_tokens failed:", e)
                page.update()

            threading.Thread(target=_init_api_from_tokens, daemon=True).start()
    except Exception as e:
        logger.error(f"Failed while attempting to initialize API from tokens.json: {e}")


if __name__ == "__main__":
    ft.app(target=main)
