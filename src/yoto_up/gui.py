import asyncio
import os
import tempfile
from pathlib import Path
import platform
import sys
from flet.auth import OAuthProvider

from yoto_up.paths import UI_STATE_FILE as UI_STATE_PATH, FLET_APP_STORAGE_DATA, TOKENS_FILE, atomic_write, ensure_parents, load_playlists, save_playlists, _BASE_DATA_DIR, _BASE_CONFIG_DIR

# Ensure FLET storage env vars are set to a sane default if not provided by the host.
if os.getenv("FLET_APP_STORAGE_TEMP") is None:
    os.environ["FLET_APP_STORAGE_TEMP"] = tempfile.mkdtemp()
if os.getenv("FLET_APP_STORAGE_DATA") is None:
    # If the environment didn't provide a Flet storage path, prefer the
    # platform-specific per-user data directory. UI code historically used
    # storage/data under the project; switch to the centralized value.
    if FLET_APP_STORAGE_DATA:
        os.environ["FLET_APP_STORAGE_DATA"] = str(FLET_APP_STORAGE_DATA)
    else:
        os.environ["FLET_APP_STORAGE_DATA"] = str(Path("storage") / "data")

def _can_start_thread() -> bool:
    if sys.platform == "emscripten":
        return sys._emscripten_info.pthreads
    return platform.machine() not in ("wasm32", "wasm64")

can_start_thread = _can_start_thread()

# Ensure matplotlib will use a writable config/cache dir when the app is frozen by PyInstaller.
# PyInstaller unpacks the app to a temporary folder which may be read-only for font cache writes.
# Setting MPLCONFIGDIR to a temp directory prevents the "Matplotlib is building the font cache" pause
# and avoids FileNotFoundError when matplotlib tries to access a bundled source file path.
try:
    mpl_cfg = os.path.join(os.getenv("FLET_APP_STORAGE_TEMP"), "yoto_up_matplotlib")
    os.environ.setdefault("MPLCONFIGDIR", mpl_cfg)
    os.makedirs(mpl_cfg, exist_ok=True)
except Exception:
    pass
import importlib.util
from typing import cast, Any
import sys as _sys
import sys
import traceback
import json
import threading
# typing imported above

import os

import flet as ft
from yoto_up.yoto_app import utils as utils_mod
from yoto_up.yoto_app import ui_helpers as ui_helpers
from yoto_up.yoto_app import auth as auth_mod
from yoto_up.yoto_app import config as yoto_config
from yoto_up.yoto_app.api_manager import ensure_api
from yoto_up.yoto_app.playlists import build_playlists_panel
from loguru import logger
from yoto_up.yoto_app.upload_tasks import start_uploads as upload_start, stop_uploads as upload_stop, FileUploadRow
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR
import hashlib
from yoto_up import paths as paths_mod

from yoto_up.yoto_app.show_waveforms import show_waveforms_popup
from yoto_up.yoto_app.icon_browser import build_icon_browser_panel
from yoto_up.yoto_app.pixel_art_editor import PixelArtEditor
import http.server
import socketserver
import socket
import subprocess
import shutil
try:
    import simpleaudio as _simpleaudio
    HAS_SIMPLEAUDIO = True
except Exception:
    _simpleaudio = None
    HAS_SIMPLEAUDIO = False

INTRO_OUTRO_DIALOG = None

os.environ["FLET_SECRET_KEY"] = os.urandom(12).hex()

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
        # Collect runtime / storage info to show to the user
        try:
            version = "dev"
            try:
                import importlib.metadata as _md
                try:
                    version = _md.version("yoto-up")
                except Exception:
                    version = _md.version("yoto_up") if hasattr(_md, 'version') else version
            except Exception:
                # importlib.metadata may not be present in older runtimes; ignore
                pass
        except Exception:
            version = "dev"

        try:
            tokens_path = Path(TOKENS_FILE) if TOKENS_FILE is not None else None
            ui_state_path = Path(UI_STATE_PATH) if UI_STATE_PATH is not None else None
            tokens_exist = tokens_path.exists() if tokens_path is not None else False
            ui_exist = ui_state_path.exists() if ui_state_path is not None else False
        except Exception:
            tokens_path = None
            ui_state_path = None
            tokens_exist = False
            ui_exist = False

        # Icon cache locations (show paths and existence)
        try:
            # Prefer the API instance paths if an API has been initialized, so
            # the About dialog reflects the same locations the API will use.
            api_instance = api_ref.get('api') if isinstance(api_ref, dict) else None
            if not api_instance:
                # Try to initialize or retrieve the API without forcing auth
                try:
                    api_instance = ensure_api(api_ref)
                except Exception:
                    api_instance = None

            if api_instance:
                try:
                    off_cache = getattr(api_instance, 'OFFICIAL_ICON_CACHE_DIR', None)
                except Exception:
                    off_cache = None
                try:
                    yotoicons_cache = getattr(api_instance, 'YOTOICONS_CACHE_DIR', None)
                except Exception:
                    yotoicons_cache = None
                try:
                    upload_icon_cache = getattr(api_instance, 'UPLOAD_ICON_CACHE_FILE', None)
                except Exception:
                    upload_icon_cache = None
                try:
                    api_cache = getattr(api_instance, 'CACHE_FILE', None)
                except Exception:
                    api_cache = None
            else:
                off_cache = getattr(paths_mod, 'OFFICIAL_ICON_CACHE_DIR', None)
                yotoicons_cache = getattr(paths_mod, 'YOTOICONS_CACHE_DIR', None)
                upload_icon_cache = getattr(paths_mod, 'UPLOAD_ICON_CACHE_FILE', None)
                api_cache = getattr(paths_mod, 'API_CACHE_FILE', None)

            try:
                off_cache_exists = Path(off_cache).exists() if off_cache is not None else False
            except Exception:
                off_cache_exists = False
            try:
                yotoicons_cache_exists = Path(yotoicons_cache).exists() if yotoicons_cache is not None else False
            except Exception:
                yotoicons_cache_exists = False
        except Exception:
            off_cache = None
            yotoicons_cache = None
            upload_icon_cache = None
            api_cache = None
            off_cache_exists = False
            yotoicons_cache_exists = False

        flet_storage = FLET_APP_STORAGE_DATA or os.getenv("FLET_APP_STORAGE_DATA") or "(not set)"

        def open_path(path_obj, notify_fn=None):
            """Open path_obj in the platform file manager and call notify_fn(message, error=False) on failure/success."""
            try:
                if path_obj is None:
                    if notify_fn:
                        notify_fn("Path is unknown", error=True)
                    return
                p = str(path_obj)
                if not os.path.exists(p):
                    try:
                        os.makedirs(p, exist_ok=True)
                    except Exception:
                        pass
                if sys.platform.startswith('darwin'):
                    subprocess.Popen(['open', p])
                elif sys.platform.startswith('win'):
                    subprocess.Popen(['explorer', p])
                else:
                    # assume linux/xdg-open
                    try:
                        subprocess.Popen(['xdg-open', p])
                    except Exception:
                        # fallback to opening parent
                        subprocess.Popen(['xdg-open', os.path.dirname(p) or p])
                if notify_fn:
                    notify_fn(f"Opened {p}")
            except Exception as ex:
                if notify_fn:
                    notify_fn(f"Failed to open {path_obj}: {ex}", error=True)
                else:
                    logger.exception(f"Failed to open path {path_obj}: {ex}")

        content_items = [
            ft.Row(
                [ft.Image(src="art.jpeg", width=120, height=120)],
                alignment=ft.MainAxisAlignment.CENTER
            ),
            ft.Text("Yoto Up", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(f"Version: {version}"),
            ft.Text(f"Python: {platform.python_version()} ({platform.machine()})"),
            ft.Text(f"Platform: {platform.platform()}"),
            ft.Divider(),
            ft.Text("Config:" , weight=ft.FontWeight.BOLD),
            ft.Text(f"Flet storage (FLET_APP_STORAGE_DATA): {flet_storage}", selectable=True, size=12),
            ft.Text(f"Tokens file: {str(tokens_path) if tokens_path is not None else '(unknown)'} {'(exists)' if tokens_exist else '(missing)'}", selectable=True, size=12),
            ft.Text(f"UI state file: {str(ui_state_path) if ui_state_path is not None else '(unknown)'} {'(exists)' if ui_exist else '(missing)'}", selectable=True, size=12),
            ft.Row([
                ft.TextButton(
                    "Open config dir",
                    on_click=lambda e, p=_BASE_CONFIG_DIR: open_path(p, show_snack),
                    style=ft.ButtonStyle(color=ft.Colors.BLUE),
                ),
            ]),
            ft.Divider(),
            ft.Text("Data locations:", weight=ft.FontWeight.BOLD),
            ft.Text(f"Official icon cache: {str(off_cache) if off_cache is not None else '(unknown)'} {'(exists)' if off_cache_exists else '(missing)'}", selectable=True, size=12),
            ft.Text(f"YotoIcons cache: {str(yotoicons_cache) if yotoicons_cache is not None else '(unknown)'} {'(exists)' if yotoicons_cache_exists else '(missing)'}", selectable=True, size=12),
            ft.Text(f"Upload icon cache file: {str(upload_icon_cache) if upload_icon_cache is not None else '(unknown)'}", selectable=True, size=12),
            ft.Text(f"API cache file: {str(api_cache) if api_cache is not None else '(unknown)'}", selectable=True, size=12),
            ft.Row([
                ft.TextButton(
                    "Open data/cache dir",
                    on_click=lambda e, p=_BASE_DATA_DIR: open_path(p, show_snack),
                    style=ft.ButtonStyle(color=ft.Colors.BLUE),
                ),
            ]),
            ft.Divider(),
            ft.Text("About:", weight=ft.FontWeight.BOLD),
            ft.Text("A desktop tool for managing Yoto cards and playlists."),
            ft.Text("Author: xkjq"),
            ft.TextButton(
                "GitHub Repository",
                url="https://github.com/xkjq/yoto-up",
                style=ft.ButtonStyle(color=ft.Colors.BLUE),
            ),
            ft.Text("\nYoto Up is not affiliated with Yoto Ltd.\n"),
            ft.Text("License: see LICENSE file in the project root."),
            ft.Row([ft.TextButton("Clear All User Data", on_click=lambda e: clear_all_user_data_gui(e), style=ft.ButtonStyle(color=ft.Colors.RED))]),
        ]
        # Remove any None entries (e.g. refresh_notice may be None) so Flet
        # receives a clean sequence of Controls.
        try:
            content_items = [c for c in content_items if c is not None]
        except Exception:
            pass

        try:
            dlg = ft.AlertDialog(
                title=ft.Text("About Yoto Up"),
                content=ft.Column(content_items, scroll=ft.ScrollMode.AUTO, width=520),
                actions=[ft.TextButton("Close", on_click=lambda e: page.close(dlg))],
            )
            page.open(dlg)
            page.update()
        except Exception as ex:
            # If anything goes wrong building the rich About dialog (for
            # example race with background UI updates), fall back to a very
            # small dialog so the About button is still functional.
            try:
                print(f"[gui] show_about_dialog fallback due to: {ex}")
            except Exception:
                pass
            try:
                fallback = ft.AlertDialog(
                    title=ft.Text("About Yoto Up"),
                    content=ft.Text("Unable to build full About dialog at this time."),
                    actions=[ft.TextButton("Close", on_click=lambda e: page.close(fallback))],
                )
                page.open(fallback)
                page.update()
            except Exception:
                pass
    # --- UI State Persistence ---
    # UI_STATE_PATH is a pathlib.Path pointing at the persisted UI state file.
    # save_ui_state/load_ui_state will use it directly.
    def save_ui_state():
        sort_dropdown = playlists_ui['sort_dropdown'] if isinstance(playlists_ui, dict) else None
        state = {
            "concurrency": concurrency.value,
            "strip_leading": strip_leading_checkbox.value,
            "intro_outro_side": intro_outro_side.value,
            "intro_outro_seconds": intro_seconds.value,
            "intro_outro_threshold": similarity_threshold.value,
            "upload_mode": upload_mode_dropdown.value,
            "local_norm_enabled": local_norm_checkbox.value,
            "local_norm_target": local_norm_target.value,
            "local_norm_batch": local_norm_batch.value,
            "playlist_sort": sort_dropdown.value if sort_dropdown else None,
        }
        try:
            try:
                UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            with UI_STATE_PATH.open("w") as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[ui_state] Failed to save: {e}")

    def load_ui_state(playlists_ui):
        try:
            with UI_STATE_PATH.open("r") as f:
                state = json.load(f)
            concurrency.value = state.get("concurrency", concurrency.value)
            strip_leading_checkbox.value = state.get("strip_leading", strip_leading_checkbox.value)
            intro_outro_side.value = state.get("intro_outro_side", intro_outro_side.value)
            intro_seconds.value = state.get("intro_outro_seconds", intro_seconds.value)
            similarity_threshold.value = state.get("intro_outro_threshold", similarity_threshold.value)
            upload_mode_dropdown.value = state.get("upload_mode", upload_mode_dropdown.value)
            local_norm_checkbox.value = state.get("local_norm_enabled", local_norm_checkbox.value)
            local_norm_target.value = state.get("local_norm_target", local_norm_target.value)
            local_norm_batch.value = state.get("local_norm_batch", local_norm_batch.value)
            sort_dropdown = playlists_ui['sort_dropdown'] if isinstance(playlists_ui, dict) else None
            if sort_dropdown and state.get("playlist_sort"):
                sort_dropdown.value = state["playlist_sort"]
                # Also update the current_sort key in the playlists module and refresh
                playlists_ui['current_sort']['key'] = sort_dropdown.value
        except Exception as e:
            logger.error(f"load_ui_state: failed to read or parse state file: {e}")
            # Create a default UI state file so subsequent runs have a persisted
            # baseline. Use current control values when available, otherwise
            # fall back to sensible defaults.
            try:
                default_state = {
                    "concurrency": (concurrency.value if 'concurrency' in locals() else "4"),
                    "strip_leading": (strip_leading_checkbox.value if 'strip_leading_checkbox' in locals() else True),
                    "intro_outro_side": (intro_outro_side.value if 'intro_outro_side' in locals() else 'intro'),
                    "intro_outro_seconds": (intro_seconds.value if 'intro_seconds' in locals() else '10.0'),
                    "intro_outro_threshold": (similarity_threshold.value if 'similarity_threshold' in locals() else '0.75'),
                    "upload_mode": (upload_mode_dropdown.value if 'upload_mode_dropdown' in locals() else 'Create new card'),
                    "playlist_sort": None,
                }
                # Write atomically to UI_STATE_PATH
                try:
                    UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                tmp = UI_STATE_PATH.with_suffix('.tmp')
                with tmp.open('w') as f:
                    json.dump(default_state, f)
                try:
                    tmp.replace(UI_STATE_PATH)
                except Exception:
                    # Fallback if atomic replace not available
                    with UI_STATE_PATH.open('w') as f:
                        json.dump(default_state, f)
                logger.info("Created default UI state file: %s", UI_STATE_PATH)
            except Exception as ex:
                logger.error(f"Failed to create default UI state file: {ex}")

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
        try:
            page.update()
        except AssertionError:
            # Flet may raise AssertionError if a control list contains
            # invalid entries (None or non-Control). If the playlists module
            # exposed a cleaner, call it and retry once.
            try:
                cleaner = getattr(page, 'clean_ui', None)
                if callable(cleaner):
                    cleaner()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                # Give up silently; show_snack should not crash the app
                pass

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
        # Prefer using the YotoAPI device auth flow directly (so we reuse
        # YotoAPI.get_device_code() and poll_for_token()). Fall back to the
        # existing auth module on any error.
        api = ensure_api(api_ref)
        try:
            device_info = api.get_device_code()
        except Exception as e:
            # If YotoAPI can't get a device code, fallback to auth_mod
            raise

        verification_uri = device_info.get('verification_uri') or ''
        verification_uri_complete = device_info.get('verification_uri_complete') or verification_uri
        user_code = device_info.get('user_code') or ''

        # Populate instructions in the provided container (or page.auth_instructions)
        try:
            container = instr or auth_instructions
            if container is not None:
                container.controls.clear()
                container.controls.append(ft.Text(f"Visit: {verification_uri} and enter the code displayed below.", selectable=True))
                container.controls.append(ft.Text(f"Code: {user_code}", selectable=True))
                container.controls.append(ft.Row([ft.Text('Alternatively open (click) this direct link: '), ft.TextButton(text=verification_uri_complete, on_click=lambda e, url=verification_uri_complete: __import__('webbrowser').open(url))]))
                container.controls.append(ft.Row([ft.Text('Doing this links you Yoto account with this app.'), ft.Text('')]))
                container.controls.append(getattr(page, 'auth_status', ft.Text('')))
                page.update()
        except Exception:
            pass

        # Start background poll using YotoAPI.poll_for_token
        def _poll_thread():
            try:
                access, refresh = api.poll_for_token(device_info.get('device_code'), device_info.get('interval', 5), device_info.get('expires_in', 300))
                try:
                    api.save_tokens(access, refresh)
                except Exception:
                    # best-effort save into centralized TOKENS_FILE
                    try:
                        ensure_parents(TOKENS_FILE)
                        atomic_write(TOKENS_FILE, json.dumps({'access_token': access, 'refresh_token': refresh}), text_mode=True)
                    except Exception:
                        pass
                api.access_token = access
                api.refresh_token = refresh
                api_ref['api'] = api
                show_snack('Authenticated')
                try:
                    page.auth_complete()
                except Exception:
                    pass
                try:
                    # update instruction UI
                    if instr is not None and hasattr(instr, 'controls'):
                        instr.controls.clear()
                        instr.controls.append(ft.Text('Authentication complete', size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN))
                        page.update()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"start_device_auth: auth failed: {e}")
                show_snack(f'Auth failed: {e}', error=True)

        threading.Thread(target=_poll_thread, daemon=True).start()
        #except Exception as ex:
        #    logger.debug(f"[gui] start_device_auth: failed, falling back to auth_mod: {ex}")
        #    # If anything goes wrong, delegate to the existing auth module
        #    try:
        #        auth_mod.start_device_auth(page, instr_container=instr or auth_instructions, api_ref=api_ref, show_snack_fn=show_snack)
        #    except Exception:
        #        try:
        #            print(f"[gui] start_device_auth delegate failed: {ex}")
        #        except Exception:
        #            pass

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
        logger.debug("[on_pick_result] picked folder")
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
        logger.debug("[on_pick_files_result] picked files")

        logger.debug(f"[on_pick_files_result] platform: {e.page.platform}")
        logger.debug(f"[on_pick_files_result] web: {e.page.web}")

        if e.files:
            logger.debug(f"[on_pick_result] picked {len(e.files)} files")
            if e.page.web:
                logger.debug("[on_pick_files_result] running in web mode")
                # In web mode, we need to save the files to a temp directory
                temp_dir = os.path.join(tempfile.gettempdir(), "yoto_up_uploads")
                os.makedirs(temp_dir, exist_ok=True)
                to_upload = []
                for f in e.files:
                    if hasattr(f, "name") and f.name:
                        upload_url = page.get_upload_url(f"queue/{f.name}", 60)
                        to_upload.append(ft.FilePickerUploadFile(f.name, upload_url))
                
                browse_files.upload(to_upload)
            else:
                for f in e.files:
                    # Add each selected file to the file_rows_column if not already present
                    logger.debug(f"[on_pick_files_result] processing {f.name}")
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

    def on_upload_file_result(e: ft.FilePickerUploadEvent):
        logger.debug(f"[on_upload_file_result] uploaded {e} ")
        logger.debug(e.progress)
        
        if e.progress == 1:
            temp_path = f"assets/uploads/queue/{e.file_name}"

            try:
                file_row = FileUploadRow(temp_path, maybe_page=page, maybe_column=file_rows_column)
                file_rows_column.controls.append(file_row.row)
            except Exception as _:
                raise RuntimeError(f"Failed to create FileUploadRow for {temp_path}")
            update_show_waveforms_btn()
            page.update()

    browse_files.on_upload = on_upload_file_result

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
            ctx['local_normalization_enabled'] = bool(local_norm_checkbox.value)
            ctx['local_normalization_target'] = float(local_norm_target.value or -23.0)
            ctx['local_normalization_batch'] = bool(local_norm_batch.value)
        except Exception:
            ctx['local_normalization_enabled'] = False
            ctx['local_normalization_target'] = -23.0
            ctx['local_normalization_batch'] = False

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
        auth_instructions.controls.clear()
        auth_instructions.controls.append(ft.Text("Preparing authentication..."))
        page.update()

        # Prefer browser OAuth via Flet when possible (works for web and desktop)

        def on_login(evt):
            logger.debug(f"[on_login] evt: {evt}; page.auth: {getattr(page, 'auth', None)}")
            # evt is a LoginEvent
            if getattr(evt, 'error', None):
                show_snack(f"Login error: {evt.error}", error=True)
                status.value = f"Login error: {evt.error}"
                page.update()
                return

            token = page.auth.token
            access = getattr(token, 'access_token', None)
            refresh = getattr(token, 'refresh_token', None)
            if access:
                # Persist tokens.json
                tmp = {'access_token': access, 'refresh_token': refresh}
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
                    api_ref['api'] = api
                    show_snack('Authenticated')
                    page.auth_complete()
                    auth_instructions.controls.clear()
                    auth_instructions.controls.append(ft.Text('Authentication complete', size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN))
                    page.update()
                except Exception as e:
                    show_snack(f'Failed to initialize API: {e}', error=True)

        # Build a generic OAuth provider using Yoto endpoints
        provider = OAuthProvider(
            client_id="RslORm04nKbhf04qb91r2Pxwjsn3Hnd5",
            client_secret=os.getenv('YOTO_CLIENT_SECRET', ''),
            authorization_endpoint='https://login.yotoplay.com/authorize',
            token_endpoint='https://login.yotoplay.com/oauth/token',
            user_endpoint='https://api.yotoplay.com/user',
            user_scopes=['profile'],
            user_id_fn=lambda u: u.get('sub') or u.get('id') or u.get('email'),
            redirect_url="http://localhost:8550/oauth_callback",
        )

        logger.debug(f"[on_auth_click] using OAuthProvider: {provider}")

        page.on_login = on_login
        try:
            # open login; fetch_user=False because we only need tokens
            page.login(provider, fetch_user=False)
        except Exception as ex:
            # fallback to device auth if browser flow fails
            logger.debug(f"Browser OAuth failed, falling back to device flow: {ex}")
            if not can_start_thread:
                start_device_auth(e, auth_instructions)
            else:
                threading.Thread(target=lambda: start_device_auth(e, auth_instructions), daemon=True).start()
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
            content=ft.Text(f"This will remove saved authentication tokens ({TOKENS_FILE.name}) and sign out. Continue?"),
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
            api = ensure_api(api_ref)  # ensure api_ref has an API instance
            api.reset_auth()
            invalidate_authentication()
            if reauth:
                # Start re-authentication in a background thread
                threading.Thread(target=lambda: start_device_auth(None), daemon=True).start()



            #threading.Thread(target=_do_reset, daemon=True).start()

        dlg.actions = [
            ft.TextButton("Cancel", on_click=_cancel),
            ft.TextButton("Confirm", on_click=_confirm),
        ]

        page.open(dlg)
        page.update()

    reset_btn = ft.TextButton("Reset Auth", on_click=lambda e: reset_auth_gui(e, reauth=False))
    reset_and_reauth_btn = ft.TextButton("Reset & Reauth", on_click=lambda e: reset_auth_gui(e, reauth=True))

    def clear_all_user_data_gui(e=None):
        """Show confirmation and clear local user data (tokens, ui state, caches, icon caches, versions)."""
        try:
            import yoto_up.paths as paths_mod
        except Exception:
            paths_mod = None

        dlg = ft.AlertDialog(
            title=ft.Text("Confirm Clear All User Data"),
            content=ft.Text("This will DELETE local tokens, UI state, caches, icon caches and saved versions. This cannot be undone. Continue?"),
            actions=[],
        )

        def _cancel(ev=None):
            try:
                page.close(dlg)
            except Exception:
                pass

        def _confirm(ev=None):
            try:
                page.close(dlg)
            except Exception:
                pass

            def _worker():
                removed = {'files': [], 'dirs': [], 'errors': []}
                try:
                    # tokens and ui state
                    try:
                        if TOKENS_FILE and Path(TOKENS_FILE).exists():
                            Path(TOKENS_FILE).unlink()
                            removed['files'].append(str(TOKENS_FILE))
                    except Exception as ex:
                        removed['errors'].append(f"tokens: {ex}")
                    try:
                        if UI_STATE_PATH and Path(UI_STATE_PATH).exists():
                            Path(UI_STATE_PATH).unlink()
                            removed['files'].append(str(UI_STATE_PATH))
                    except Exception as ex:
                        removed['errors'].append(f"ui_state: {ex}")

                    # other paths from paths_mod if available
                    if paths_mod:
                        for p in (getattr(paths_mod, 'UPLOAD_ICON_CACHE_FILE', None), getattr(paths_mod, 'API_CACHE_FILE', None)):
                            try:
                                if p and Path(p).exists():
                                    Path(p).unlink()
                                    removed['files'].append(str(p))
                            except Exception as ex:
                                removed['errors'].append(f"file {p}: {ex}")
                        for d in (getattr(paths_mod, 'OFFICIAL_ICON_CACHE_DIR', None), getattr(paths_mod, 'YOTOICONS_CACHE_DIR', None), getattr(paths_mod, 'VERSIONS_DIR', None)):
                            try:
                                if d and Path(d).exists():
                                    shutil.rmtree(d)
                                    removed['dirs'].append(str(d))
                            except Exception as ex:
                                removed['errors'].append(f"dir {d}: {ex}")

                except Exception as ex:
                    removed['errors'].append(str(ex))

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
                for r in removed['files']:
                    summary.append(f"file: {r}")
                for r in removed['dirs']:
                    summary.append(f"dir: {r}")
                for err in removed['errors']:
                    summary.append(f"ERROR: {err}")
                msg = "Cleared user data" if not removed['errors'] else "Cleared user data (with errors)"
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
        page.open(dlg)
        page.update()

    # clear_data_btn removed; Clear action is available from the About dialog

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

    # Normalization controls
    local_norm_checkbox = ft.Checkbox(
        label='Normalize audio (local)',
        value=False,
        tooltip="Normalize audio loudness before upload using ffmpeg-normalize",
        on_change=lambda e: save_ui_state(),
    )
    local_norm_target = ft.TextField(
        label='Target LUFS',
        value='-23.0',
        width=100,
        tooltip="Target integrated loudness in LUFS (default -23.0)",
        on_change=lambda e: save_ui_state(),
    )
    local_norm_batch = ft.Checkbox(
        label='Batch mode',
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
                pl_list = playlists_ui.get('playlists_list') if isinstance(playlists_ui, dict) else None
                if pl_list and hasattr(pl_list, 'controls'):
                    pl_list.controls.clear()
                    # Resolve make_playlist_row once to avoid repeated fallback logs
                    make_row = None
                    try:
                        make_row = playlists_ui.get('make_playlist_row') if isinstance(playlists_ui, dict) else None
                    except Exception:
                        make_row = None
                    # If playlists_ui did not provide a row builder, we'll fall back
                    # to a simple ListTile per-item. Do not try to import the nested
                    # `make_playlist_row` from the module (it's local to the builder).
                    if not callable(make_row):
                        make_row = None
                    if not callable(make_row):
                        logger.debug("No make_playlist_row function available in playlists_ui; using fallback ListTile")

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
                                    title = item.get('title', '') if isinstance(item, dict) else str(item)
                                    cid = item.get('cardId', '') if isinstance(item, dict) else ''
                                    pl_list.controls.append(ft.ListTile(title=ft.Text(title), subtitle=ft.Text(str(cid))))
                            else:
                                # fallback: render a simple ListTile
                                title = item.get('title', '') if isinstance(item, dict) else str(item)
                                cid = item.get('cardId', '') if isinstance(item, dict) else ''
                                pl_list.controls.append(ft.ListTile(title=ft.Text(title), subtitle=ft.Text(str(cid))))
                        except Exception:
                            try:
                                pl_list.controls.append(ft.ListTile(title=ft.Text(str(item))))
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
                    window_seconds = float(getattr(ws_ctrl, 'value', 0.1))
                except Exception:
                    window_seconds = 0.1
                try:
                    max_seconds = float(getattr(mx_ctrl, 'value', seconds))
                except Exception:
                    max_seconds = float(seconds)
                try:
                    similarity_threshold = float(getattr(sim_ctrl, 'value', 0.98))
                except Exception:
                    similarity_threshold = 0.98
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
            cb = ft.Checkbox(label=f"{p.split('/')[-1]} (score={score_label})", value=(score >= float(dialog_controls.get('window_min_files').value or 0.75)), tooltip=f"Include this file in trimming: {p}")
            checkbox_map[p] = cb

            # Preview button: extract the matched segment into a temp file and play it
            preview_btn = ft.TextButton('Preview', on_click=None, tooltip='Preview the matched intro/outro segment')

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
                        logger.debug(f"open_intro_outro_dialog: reopening dialog: {INTRO_OUTRO_DIALOG}")
                        page.open(INTRO_OUTRO_DIALOG)

                    # Create a preview dialog so the user sees progress while we extract
                    preview_content = ft.Column([ft.Row([ft.ProgressRing(), ft.Text('Preparing preview...')], alignment=ft.MainAxisAlignment.CENTER)], scroll=ft.ScrollMode.AUTO)
                    preview_dlg = ft.AlertDialog(title=ft.Text('Preview'), content=preview_content, actions=[ft.TextButton('Close', on_click=lambda e: open_intro_outro_dialog(e))], modal=True)
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
                               
                                content = ft.Column(items, scroll=ft.ScrollMode.AUTO)
                                return ft.AlertDialog(title=ft.Text('Preview'), content=content, actions=[ ft.TextButton('Close', on_click=lambda e: open_intro_outro_dialog(e))], modal=True)

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

            # Compute planned removal (use computed_removal field if present,
            # otherwise fall back to analysis result). The final confirmation
            # modal below will ask the user to proceed before any files are
            # modified, so we don't require a separate confirm checkbox here.
            try:
                comp_ctrl = dialog_controls.get('computed_removal')
                try:
                    comp_val = float(getattr(comp_ctrl, 'value', seconds_matched))
                except Exception:
                    comp_val = float(seconds_matched) if seconds_matched is not None else 0.0
            except Exception:
                comp_val = float(seconds_matched) if seconds_matched is not None else 0.0
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
                            comp_ctrl = dialog_controls.get('computed_removal')
                            remove_t = float(getattr(comp_ctrl, 'value', seconds_matched))
                        except Exception:
                            remove_t = float(seconds_matched) if seconds_matched is not None else 0.0

                        src_path = Path(orig_p)
                        dest = str(temp_dir / (src_path.stem + '.trimmed' + src_path.suffix))

                        trim_audio_file(
                            orig_p,
                            dest,
                            remove_intro_seconds=remove_t if side == 'intro' else 0.0,
                            remove_outro_seconds=remove_t if side == 'outro' else 0.0,
                            keep_silence_ms=padding_ms,
                        )

                        # update matching rows to point to trimmed file
                        for ctrl in list(file_rows_column.controls):
                            fur = getattr(ctrl, '_fileuploadrow', None)
                            try:
                                if fur and (getattr(fur, 'original_filepath', None) == orig_p or getattr(fur, 'filepath', None) == orig_p or getattr(ctrl, 'filename', None) == orig_p):
                                    fur.update_file(dest)
                                    fur.set_status('Trimmed intro/outro')
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
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        for orig_p, norm_p in selected_paths:
                            futures.append(executor.submit(_trim_one, orig_p, norm_p))

                        # iterate as futures complete and update UI
                        for fut in concurrent.futures.as_completed(futures):
                            orig_p, dest, err = fut.result()
                            with lock:
                                trimmed_count += 1
                                try:
                                    trim_progress.value = (trimmed_count / total_selected) if total_selected else 1.0
                                    trim_label.value = f'Trimming {trimmed_count}/{total_selected}'
                                except Exception:
                                    pass
                            # update UI rows for this file
                            if err:
                                for ctrl in list(file_rows_column.controls):
                                    fur = getattr(ctrl, '_fileuploadrow', None)
                                    try:
                                        if fur and (getattr(fur, 'original_filepath', None) == orig_p or getattr(fur, 'filepath', None) == orig_p or getattr(ctrl, 'filename', None) == orig_p):
                                            fur.set_status(f'Trim error: {err}')
                                    except Exception:
                                        pass
                            else:
                                try:
                                    for ctrl in list(file_rows_column.controls):
                                        fur = getattr(ctrl, '_fileuploadrow', None)
                                        try:
                                            if fur and (getattr(fur, 'original_filepath', None) == orig_p or getattr(fur, 'filepath', None) == orig_p or getattr(ctrl, 'filename', None) == orig_p):
                                                fur.update_file(dest)
                                                fur.set_status('Trimmed intro/outro')
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
                    logger.exception('Parallel trimming failed, falling back to sequential')
                    for orig_p, norm_p in selected_paths:
                        _orig, _dest, _err = _trim_one(orig_p, norm_p)
                        with lock:
                            trimmed_count += 1
                            try:
                                trim_progress.value = (trimmed_count / total_selected) if total_selected else 1.0
                                trim_label.value = f'Trimming {trimmed_count}/{total_selected}'
                            except Exception:
                                pass
                        try:
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
        # Build a simplified dialog focused on the new per-window analyzer.
        d_side = ft.Dropdown(label='Side', value='intro', options=[ft.dropdown.Option('intro'), ft.dropdown.Option('outro')], width=120)
        d_max_seconds = ft.TextField(label='Max inspect seconds', value='10.0', width=120)
        d_window_seconds = ft.TextField(label='Window seconds', value='0.1', width=120)
        d_window_similarity = ft.TextField(label='Window similarity threshold', value='0.95', width=120)
        d_window_min_files = ft.TextField(label='Min files fraction', value='1.0', width=120)
        d_padding = ft.TextField(label='Left padding (s)', value='0.25', width=100)
        d_fast = ft.Checkbox(label='Fast mode (lower quality, faster)', value=True)
        d_computed_removal = ft.TextField(label='Computed removal (s)', value='0.00', width=120)
    # confirm removal checkbox removed — rely on final confirmation dialog
        content_column = ft.Column([], scroll=ft.ScrollMode.AUTO)

        def on_run(ev=None):
            dlg_controls = {
                'intro_outro_side': d_side,
                'intro_seconds': d_max_seconds,
                'similarity_threshold': d_window_similarity,
                'padding_seconds': d_padding,
                'fast_mode': d_fast,
                'window_seconds': d_window_seconds,
                'max_seconds_window': d_max_seconds,
                'window_similarity': d_window_similarity,
                'window_min_files': d_window_min_files,
                'computed_removal': d_computed_removal,
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
        trim_btn = ft.ElevatedButton('Trim selected', disabled=True)
        close_btn = ft.TextButton('Close', on_click=lambda e: page.close(dlg))

        dlg = ft.AlertDialog(
            title=ft.Text('Analyze intro/outro'),
            content=ft.Column([
                ft.Row([d_side, d_max_seconds, d_padding, d_fast]),
                ft.Row([d_window_seconds, d_window_similarity, d_window_min_files]),
                ft.Row([d_computed_removal]),
                ft.Divider(),
                content_column
            ], scroll=ft.ScrollMode.AUTO, width=600),
            actions=[run_btn, trim_btn, close_btn],
        )
        # expose dlg to inner closures
        global INTRO_OUTRO_DIALOG
        INTRO_OUTRO_DIALOG = dlg
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
            upload_mode_dropdown  # Add the new dropdown here
        ]),
        ft.Row([
            local_norm_checkbox,
            local_norm_target,
            local_norm_batch
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

    # Small badge to indicate background icon cache refresh activity.
    icon_refresh_badge_text = ft.Text("Updating icon cache...", size=12, color=ft.Colors.ORANGE)
    icon_refresh_badge = ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.CACHED, color=ft.Colors.ORANGE), icon_refresh_badge_text], spacing=6),
        padding=6,
        border_radius=6,
        bgcolor=ft.Colors.YELLOW_50,
        visible=False,
    )

    # Small autoselect progress badge (smaller than icon_refresh_badge)
    autoselect_badge_text = ft.Text("", size=11, color=ft.Colors.BLUE)
    autoselect_badge = ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.REFRESH, color=ft.Colors.BLUE), autoselect_badge_text], spacing=4),
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
            cancel = getattr(page, 'autoselect_cancel_event', None)
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

    def set_autoselect_progress(msg: str | None, frac: float | None = None, visible: bool = True):
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
                ctrl = getattr(page, 'autoselect_status_ctrl', None)
                if ctrl is not None:
                    try:
                        ctrl.value = autoselect_badge_text.value
                    except Exception:
                        pass
                detail = getattr(page, 'autoselect_status_detail', None)
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
            hide_checkbox = ft.Checkbox(label="Hide this dialog by default", value=page.autoselect_hide_dialog_default)

            def on_hide_change(e):
                try:
                    page.autoselect_hide_dialog_default = bool(hide_checkbox.value)
                except Exception:
                    pass

            hide_checkbox.on_change = on_hide_change

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
            content_col = ft.Column([status_txt, detail_txt, hide_checkbox], width=480, scroll=ft.ScrollMode.AUTO)

            dlg = ft.AlertDialog(
                title=ft.Text("Autoselect status"),
                content=content_col,
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: (cancel_event.set() if cancel_event else None, page.close(dlg))),
                    ft.TextButton("Close", on_click=lambda e: page.close(dlg)),
                ],
            )
            page.open(dlg)
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
                tf = tempfile.NamedTemporaryFile(prefix="yoto_cover_", suffix=ext, delete=False)
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
                            with open(tf.name, 'wb') as fh:
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
    page.add(ft.Row([ft.Text("Yoto Up", size=22, weight=ft.FontWeight.BOLD, expand=True), ft.Row([icon_refresh_badge, autoselect_badge, about_btn])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
    page.add(tabs_control)
    show_dev_warning()

    def auth_complete():
        logger.debug("Auth complete")
        tabs_control.tabs[1].visible = True
        tabs_control.tabs[2].visible = True
        tabs_control.tabs[3].visible = True  # Icons tab
        tabs_control.tabs[4].visible = True  # Editor tab

        api = api_ref.get("api")
        if api:
            # Run icon cache refresh in a background thread so the UI doesn't hang.
            def _refresh_icons_bg():
                try:
                    try:
                        if hasattr(page, 'set_icon_refreshing'):
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
                        if hasattr(page, 'set_icon_refreshing'):
                            page.set_icon_refreshing(False)
                    except Exception:
                        pass
                # Notify any icon browser listeners that the cache refresh finished
                try:
                    cbs = getattr(page, 'icon_cache_refreshed_callbacks', None)
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
            auth_instructions.controls.extend([
                ft.Text("Authenticated (from existing tokens)", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN, ),
                ft.Text(api.TOKEN_FILE, size=10)
            ]
            )
            auth_complete()
            page.update()
        #tokens_path = Path("tokens.json")
        #logger.debug(f"Checking for existing tokens.json at {tokens_path.resolve()}")
        #if tokens_path.exists():
        #    def _init_api_from_tokens():
        #        try:
        #            api = ensure_api(api_ref)
        #            api_ref["api"] = api
        #            show_snack("Authenticated (from tokens.json)")
        #            # Replace instructions with a prominent success message
        #            auth_instructions.controls.clear()
        #            auth_instructions.controls.extend([
        #                ft.Text("Authenticated (from tokens.json)", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN, ),
        #                ft.Text(api.TOKEN_FILE, size=10)
        #            ]
        #            )
        #            auth_complete()
        #        except Exception as e:
        #            status.value = f"Tokens present but API init failed: {e}"
        #            show_snack(f"API init from tokens.json failed: {e}", error=True)
        #            print("[gui] init_api_from_tokens failed:", e)
        #        page.update()

        #    threading.Thread(target=_init_api_from_tokens, daemon=True).start()
    except Exception as e:
        logger.error(f"Failed while attempting to initialize API from tokens.json: {e}")

def start_gui():
    ft.app(target=main, assets_dir="assets", upload_dir="assets/uploads")

if __name__ == "__main__":
    start_gui()
