import asyncio
import os
from pathlib import Path
import sys
import traceback
import json
import threading

import flet as ft
from models import Card

from yoto_api import YotoAPI
from yoto_app import utils as utils_mod
from yoto_app import ui_helpers as ui_helpers
from yoto_app import auth as auth_mod
from yoto_app.api_manager import ensure_api
from yoto_app.playlists import build_playlists_panel
from loguru import logger
from yoto_app.logging_helpers import safe_log
from yoto_app.upload_tasks import start_uploads as upload_start, stop_uploads as upload_stop

print(f"[gui] module loaded, pid={os.getpid()}")

# Supported audio extensions
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"}

logger.remove()  # Remove default handler
logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message}")


# use utils_mod.find_audio_files when needed


class FileRow(ft.Row):
    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        # create a row matching ft_row_for_file shape: name, hidden progress bar, status
        pr = ft.ProgressBar(width=300, visible=False)
        status = ft.Text("Queued")
        self.controls = [ft.Text(filename, width=300), pr, status]
        try:
            setattr(self, 'filename', filename)
        except Exception:
            pass


def main(page):
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
            upload_mode_dropdown.value = state.get("upload_mode", upload_mode_dropdown.value)
            sort_dropdown = playlists_ui['sort_dropdown'] if isinstance(playlists_ui, dict) else None
            if sort_dropdown and state.get("playlist_sort"):
                sort_dropdown.value = state["playlist_sort"]
                # Also update the current_sort key in the playlists module and refresh
                playlists_ui['current_sort']['key'] = sort_dropdown.value
        except Exception as e:
            logger.error(f"load_ui_state: failed to read or parse state file: {e}")

    # ...existing code...
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
        # Switch to Auth tab
        tabs_control.selected_index = 0
        # Update instructions/status
        try:
            auth_instructions.controls.clear()
            auth_instructions.controls.append(ft.Text("Not authenticated", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.RED))
        except Exception:
            pass
        status.value = "Not authenticated"
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
    auth_instructions = ft.Column([ft.Text("Not authenticated")])

    def show_snack(message: str, error: bool = False):
        print(f"[gui] show_snack: {message}")
        bg = ft.Colors.RED if error else None
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=bg)
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
            safe_log('upload_target_change failed', exc)

    upload_target_dropdown.on_change = _on_upload_target_change

    # Action buttons
    start_btn = ft.ElevatedButton('Start Upload')
    stop_btn = ft.ElevatedButton('Stop Upload', disabled=True)
    fetch_btn = ft.ElevatedButton('Fetch Playlists')
    multi_select_btn = ft.ElevatedButton('Select Multiple')
    delete_selected_btn = ft.ElevatedButton('Delete Selected', disabled=True)

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
                    # create a UI row using upload_tasks.ft_row_for_file so the details button is present
                    try:
                        from yoto_app.upload_tasks import ft_row_for_file
                        file_row = ft_row_for_file(f, page, file_rows_column)
                    except Exception:
                        file_row = FileRow(f)
                    file_rows_column.controls.append(file_row)
                    added += 1
            if added == 0 and files:
                print("[populate_file_rows] All files from folder already present in upload list.")
            if not files:
                file_rows_column.controls.append(ft.Text(f"No audio files found in {folder_path}"))
            page.update()
        except Exception as e:
            try:
                print(f"[populate_file_rows] error: {e}")
            except Exception:
                pass

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
                except Exception as exc:
                    safe_log("on_pick_result: populate_file_rows failed", exc)
            else:
                # web mode: save files to temp? For simplicity, just inform user
                folder.value = "(web file picker used - paste local folder path instead)"
        page.update()

    def on_pick_files_result(e: ft.FilePickerResultEvent):
        if e.files:
            for f in e.files:
                # Add each selected file to the file_rows_column if not already present
                path = getattr(f, "path", None)
                if path and not any(getattr(row, "filename", None) == path for row in file_rows_column.controls):
                    try:
                        from yoto_app.upload_tasks import ft_row_for_file
                        file_row = ft_row_for_file(path, page, file_rows_column)
                    except Exception:
                        file_row = FileRow(path)
                    file_rows_column.controls.append(file_row)
            page.update()

    browse.on_result = on_pick_result
    browse_files.on_result = on_pick_files_result

    # When the folder TextField is changed (user pastes or types a path), update the file list immediately
    def _on_folder_change(ev=None):
        try:
            if folder.value:
                populate_file_rows(folder.value)
        except Exception as exc:
            safe_log("_on_folder_change: populate_file_rows failed", exc)

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
    sort_dropdown = playlists_ui['sort_dropdown']
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
        'start_btn': start_btn,
        'stop_btn': stop_btn,
    }

    # Also add the control to the page so user can toggle it
    # We'll insert it near the upload controls later when building the upload panel

    def _start_click(e):
        # update ctx with the current checkbox value
        try:
            ctx['strip_leading_track_numbers'] = bool(strip_leading_checkbox.value)
        except Exception:
            ctx['strip_leading_track_numbers'] = True
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
                print("[gui] auth background thread started")
                start_device_auth(evt, instr)
                print("[gui] auth background thread finished")
            except Exception:
                print("[gui] auth background thread exception:\n", traceback.format_exc())

        threading.Thread(target=lambda: _auth_bg_runner(e, auth_instructions), daemon=True).start()

    auth_btn.on_click = _auth_click

    # Auth page (separate from uploads) — include embedded instructions area
    auth_column = ft.Column([
        ft.Row([auth_btn]),
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
                    hdr[insert_at:insert_at] = [playlist_fetch_btn or fetch_btn, playlist_multi_select_btn or multi_select_btn, playlist_delete_selected_btn or delete_selected_btn]
                    header.controls = hdr
            except Exception as e:
                safe_log("failed to merge header buttons into playlists header", e)
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
            folder, 
            ft.TextButton("Browse Folder...", on_click=lambda e: browse.pick_files(allow_multiple=True)),
            ft.TextButton("Add Files...", on_click=lambda e: browse_files.pick_files(allow_multiple=True)),
            ft.TextButton("Clear Queue", on_click=clear_queue),
            ft.IconButton(
                icon=ft.Icons.HELP_OUTLINE,
                tooltip="Help: Select a folder or specific files to upload.",
                on_click=lambda e: show_snack(
                    "Select the folder containing your audio files, or add specific files. 'Browse Folder...' lets you pick a folder (you may have to select a file within the folder), or paste the path directly. 'Add Files...' lets you pick individual files.\n\nChoose 'Chapters' to upload files as chapters, or 'Tracks' to upload as tracks.",
                    error=False
                )
            )
        ]),
        ft.Row([start_btn, stop_btn]),
        ft.Divider(),
        overall_text,
        overall_bar,
        ft.Divider(),
        ft.Text("Files:"),
        ft.Container(content=file_rows_column, padding=10, bgcolor=ft.Colors.WHITE),
        ft.Divider(),
        ft.Row([status])
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
    tabs_control = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Auth", content=auth_column),
            ft.Tab(text="Playlists", content=playlists_column, visible=False),
            ft.Tab(text="Upload", content=upload_column, visible=False),
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
