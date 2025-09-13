import asyncio
import os
import tempfile
import importlib.util
import sys as _sys
from pathlib import Path
import sys
import traceback
import json
import threading

import os

import flet as ft
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
    # Track per-file gain and temp file for upload
    gain_adjusted_files = {}  # {filepath: {'gain': float, 'temp_path': str or None}}
    # In-memory cache for waveform/loudness data: {filepath: (audio, max_amp, avg_amp, lufs, ext, filepath)}
    waveform_cache = {}
    import matplotlib.pyplot as plt
    import numpy as np
    import io
    import base64
    import contextlib
    import wave
    from waveform_utils import batch_audio_stats

    # Import audio_adjust_utils at module level for reliability
    audio_adjust_utils_path = os.path.join(os.path.dirname(__file__), "audio_adjust_utils.py")
    _spec = importlib.util.spec_from_file_location("audio_adjust_utils", audio_adjust_utils_path)
    if _spec and _spec.loader:
        audio_adjust_utils = importlib.util.module_from_spec(_spec)
        _sys.modules["audio_adjust_utils"] = audio_adjust_utils
        _spec.loader.exec_module(audio_adjust_utils)
    else:
        audio_adjust_utils = None

    def show_waveforms_popup(e=None):
        logger.debug("[show_waveforms_popup] Generating waveforms popup")
        files = [getattr(row, 'filename', None) for row in file_rows_column.controls if getattr(row, 'filename', None)]
        if not files:
            show_snack("No files in upload queue.", error=True)
            return
        images = []
        n_images = 0
        per_track = []  # Store (audio, framerate, ext, filepath, gain_slider, col, gain_val) for each track
        # Use previous gain values if available
        if not hasattr(page, '_track_gains'):
            page._track_gains = {}
        global_gain = {'value': getattr(page, '_global_gain', 0.0)}
        logger.debug(f"[show_waveforms_popup] Found {len(files)} files in upload queue")
        progress_text = ft.Text(f"Calculating waveform data... 0/{len(files)}", size=14)
        progress_bar = ft.ProgressBar(width=300, value=0)
        progress_dlg = ft.AlertDialog(
            title=ft.Text("Generating Waveforms"),
            content=ft.Column([
                progress_text,
                progress_bar
            ], expand=True),
            actions=[],
            modal=True
        )
        page.open(progress_dlg)
        page.update()

        def progress_callback(completed, total):
            progress_text.value = f"Calculating waveform data... {completed}/{total}"
            progress_bar.value = completed / total if total else 0
            page.update()

        stats_results = batch_audio_stats(files, waveform_cache, progress_callback=progress_callback)
        page.update()

        # Collect debug info for skipped files
        skipped_files = []
        for idx, stat in enumerate(stats_results):
            audio, max_amp, avg_amp, lufs, ext, filepath = stat
            if audio is None:
                # Try to explain why
                reason = None
                if ext is None:
                    reason = "Unrecognized or missing file extension."
                elif ext not in ['.wav', '.mp3']:
                    reason = f"Unsupported extension: {ext}"
                elif not os.path.exists(filepath):
                    reason = "File does not exist."
                else:
                    reason = "Could not decode audio or file is empty/corrupt."
                skipped_files.append(f"{os.path.basename(filepath) or filepath}: {reason}")

        def plot_and_stats(audio, framerate, ext, filepath, gain_db=0.0):
            import pyloudnorm as pyln
            # Apply gain in dB
            audio_adj = audio * (10 ** (gain_db / 20.0))
            # Recalculate stats
            max_amp = float(np.max(np.abs(audio_adj)))
            avg_amp = float(np.mean(np.abs(audio_adj)))
            try:
                meter = pyln.Meter(framerate)
                lufs = float(meter.integrated_loudness(audio_adj))
            except Exception:
                lufs = None
            # Downsample for plotting if too long
            max_points = 2000
            n = len(audio_adj)
            if n > max_points:
                idx = np.linspace(0, n - 1, max_points).astype(int)
                audio_plot = audio_adj[idx]
            else:
                audio_plot = audio_adj
            if ext == '.wav':
                with contextlib.closing(wave.open(filepath, 'rb')) as wf:
                    framerate = wf.getframerate()
                    n_frames = wf.getnframes()
                    times = np.linspace(0, n_frames / framerate, num=n)
            else:
                framerate = 44100
                times = np.linspace(0, n / framerate, num=n)
            if n > max_points:
                times = times[idx]
            fig, ax = plt.subplots(figsize=(4, 1.2))
            ax.plot(times, audio_plot, color='blue')
            ax.set_title(os.path.basename(filepath), fontsize=8)
            ax.set_xlabel('Time (s)', fontsize=7)
            ax.set_ylabel('Amplitude', fontsize=7)
            ax.tick_params(axis='both', which='major', labelsize=6)
            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            plt.close(fig)
            buf.seek(0)
            img_b64 = base64.b64encode(buf.read()).decode('utf-8')
            fd, tmp_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            with open(tmp_path, 'wb') as tmpfile:
                tmpfile.write(base64.b64decode(img_b64))
            lufs_str = f"LUFS: {lufs:.2f} dB" if lufs is not None else "LUFS: (unavailable)"
            label = ft.Text(f"Max amplitude: {max_amp:.2f}   Average amplitude: {avg_amp:.2f}   {lufs_str}", size=10, color=ft.Colors.BLUE)
            warning = None
            if lufs is not None:
                if lufs > -9:
                    warning = ft.Text("Warning: LUFS is high! Track may be too loud for streaming (-9 dB or higher)", size=10, color=ft.Colors.RED)
                elif lufs > -16:
                    warning = ft.Text("Warning: LUFS is moderately high (-16 dB to -9 dB)", size=10, color=ft.Colors.YELLOW_900)
            return label, warning, tmp_path

        # Actually process stats_results to build per_track and n_images
        for stat in stats_results:
            audio, max_amp, avg_amp, lufs, ext, filepath = stat
            if audio is not None:
                if ext == '.wav':
                    with contextlib.closing(wave.open(filepath, 'rb')) as wf:
                        framerate = wf.getframerate()
                else:
                    framerate = 44100
                # Use last gain value for this file if available
                last_gain = page._track_gains.get(filepath, 0.0)
                gain_slider = ft.Slider(min=-20, max=20, divisions=40, value=last_gain, label="Gain: {value} dB", width=320)
                label, warning, tmp_path = plot_and_stats(audio, framerate, ext, filepath, gain_db=last_gain)
                img = ft.Image(src=tmp_path, width=320, height=100)
                col = ft.Column([])
                gain_val = {'value': last_gain}
                def on_gain_change(e, audio=audio, framerate=framerate, ext=ext, filepath=filepath, col=col, gain_val=gain_val):
                    logger.debug(f"[on_gain_change] Gain changed for {os.path.basename(filepath)} to {e.control.value} dB")
                    gain_db = e.control.value
                    gain_val['value'] = gain_db
                    page._track_gains[filepath] = gain_db
                    label, warning, tmp_path = plot_and_stats(audio, framerate, ext, filepath, gain_db=gain_db)
                    col.controls.clear()
                    col.controls.append(label)
                    if warning:
                        col.controls.append(warning)
                    col.controls.append(ft.Image(src=tmp_path, width=320, height=100))
                    # Show progress dialog only if saving gain-adjusted file (not for zero gain)
                    show_progress = abs(gain_db) > 0.01
                    progress_dlg = None
                    if show_progress:
                        progress_dlg = ft.AlertDialog(title=ft.Text("Saving gain-adjusted audio..."), content=ft.ProgressBar(width=300), modal=True)
                        page.open(progress_dlg)
                        page.update()
                    try:
                        if abs(gain_db) > 0.01:
                            if audio_adjust_utils is not None:
                                try:
                                    temp_path = getattr(audio_adjust_utils, "save_adjusted_audio")(audio * (10 ** (gain_db / 20.0)), framerate, ext, filepath, gain_db)
                                    gain_adjusted_files[filepath] = {'gain': gain_db, 'temp_path': temp_path}
                                except Exception as ex:
                                    show_snack(f"Failed to save adjusted audio for upload: {ex}", error=True)
                        else:
                            gain_adjusted_files.pop(filepath, None)
                    finally:
                        if progress_dlg:
                            page.close(progress_dlg)
                            page.update()
                    page.update()
                gain_slider.on_change_end = on_gain_change
                def on_save_adjusted_audio_click(e, audio=audio, framerate=framerate, ext=ext, filepath=filepath, gain_val=gain_val):
                    if audio_adjust_utils is None:
                        show_snack("audio_adjust_utils could not be loaded", error=True)
                        return
                    progress_dlg = ft.AlertDialog(title=ft.Text("Saving gain-adjusted audio..."), content=ft.ProgressBar(width=300), modal=True)
                    page.open(progress_dlg)
                    page.update()
                    try:
                        temp_path = getattr(audio_adjust_utils, "save_adjusted_audio")(audio * (10 ** (gain_val['value'] / 20.0)), framerate, ext, filepath, gain_val['value'])
                        show_snack(f"Saved adjusted audio to: {temp_path}")
                        if abs(gain_val['value']) > 0.01:
                            gain_adjusted_files[filepath] = {'gain': gain_val['value'], 'temp_path': temp_path}
                        else:
                            gain_adjusted_files.pop(filepath, None)
                    except Exception as ex:
                        show_snack(f"Failed to save adjusted audio: {ex}", error=True)
                    finally:
                        page.close(progress_dlg)
                        page.update()
                save_btn = ft.TextButton("Save Adjusted Audio", on_click=on_save_adjusted_audio_click, tooltip="Save gain-adjusted audio to a temp file for upload")
                col.controls.append(label)
                if warning:
                    col.controls.append(warning)
                col.controls.append(img)
                col.controls.append(save_btn)
                per_track.append((audio, framerate, ext, filepath, gain_slider, col, gain_val))
                n_images += 1
            else:
                per_track.append((None, None, None, None, None, ft.Text("(No waveform for file)", size=10, color=ft.Colors.RED), None))

        def on_global_gain_change(e):
            logger.debug(f"[on_global_gain_change] Global gain changed to {e.control.value} dB")
            global_gain['value'] = e.control.value
            page._global_gain = e.control.value
            progress_text = ft.Text("Applying global gain to all tracks...", size=14)
            progress_bar = ft.ProgressBar(width=300, value=0)
            progress_dlg = ft.AlertDialog(title=ft.Text("Applying Global Gain..."), content=ft.Column([progress_text, progress_bar]), modal=True)
            page.open(progress_dlg)
            page.update()
            total = len(per_track)
            completed = 0
            for i, (audio, framerate, ext, filepath, gain_slider, col, gain_val) in enumerate(per_track):
                if gain_slider is not None and audio is not None:
                    gain_slider.value = global_gain['value']
                    gain_val['value'] = global_gain['value']
                    page._track_gains[filepath] = global_gain['value']
                    # Save gain-adjusted audio with progress (if needed)
                    if abs(global_gain['value']) > 0.01 and audio_adjust_utils is not None:
                        try:
                            temp_path = getattr(audio_adjust_utils, "save_adjusted_audio")(audio * (10 ** (global_gain['value'] / 20.0)), framerate, ext, filepath, global_gain['value'])
                            gain_adjusted_files[filepath] = {'gain': global_gain['value'], 'temp_path': temp_path}
                        except Exception as ex:
                            show_snack(f"Failed to save adjusted audio for upload: {ex}", error=True)
                    else:
                        gain_adjusted_files.pop(filepath, None)
                completed += 1
                progress_text.value = f"Processed {completed} of {total} tracks"
                progress_bar.value = completed / total
                page.update()
            page.close(progress_dlg)
            page.update()
            # Reopen the waveform popup after applying global gain, so waveforms are regenerated
            show_waveforms_popup()

        global_gain_slider = ft.Slider(min=-20, max=20, divisions=40, value=0.0, label="Global Gain: {value} dB", width=320)
        global_gain_slider.on_change_end = on_global_gain_change

        save_btn = None
        if n_images > 0:
            def on_save_adjusted_audio_all_click(e):
                if audio_adjust_utils is None:
                    show_snack("audio_adjust_utils could not be loaded", error=True)
                    return
                progress_text = ft.Text("Saving gain-adjusted audio for all tracks...", size=14)
                progress_bar = ft.ProgressBar(width=300, value=0)
                progress_dlg = ft.AlertDialog(title=ft.Text("Saving gain-adjusted audio..."), content=ft.Column([progress_text, progress_bar]), modal=True)
                page.open(progress_dlg)
                page.update()
                total = n_images
                completed = 0
                errors = []
                for audio, framerate, ext, filepath, gain_slider, col, gain_val in per_track:
                    try:
                        temp_path = getattr(audio_adjust_utils, "save_adjusted_audio")(audio * (10 ** (gain_val['value'] / 20.0)), framerate, ext, filepath, gain_val['value'])
                        if abs(gain_val['value']) > 0.01:
                            gain_adjusted_files[filepath] = {'gain': gain_val['value'], 'temp_path': temp_path}
                        else:
                            gain_adjusted_files.pop(filepath, None)
                        progress_text.value = f"Saved: {os.path.basename(filepath)}"
                    except Exception as ex:
                        errors.append(f"{os.path.basename(filepath)}: {ex}")
                        progress_text.value = f"Error: {os.path.basename(filepath)}"
                    completed += 1
                    progress_bar.value = completed / total
                    page.update()
                page.close(progress_dlg)
                page.update()
                # Fully refresh the upload queue rows to reflect new temp files and details
                from yoto_app.upload_tasks import FileUploadRow
                new_rows = []
                for row in list(getattr(file_rows_column, 'controls', [])):
                    path = getattr(row, 'filename', None)
                    temp_info = gain_adjusted_files.get(path)
                    new_path = temp_info['temp_path'] if temp_info and temp_info.get('temp_path') else path
                    try:
                        file_row = FileUploadRow(new_path, maybe_page=page, maybe_column=file_rows_column)
                        new_rows.append(file_row.row)
                    except Exception:
                        new_rows.append(ft.Row([ft.Text(os.path.basename(new_path) if new_path else "")]))
                file_rows_column.controls.clear()
                file_rows_column.controls.extend(new_rows)
                page.update()
                if errors:
                    show_snack(f"Some files failed: {'; '.join(errors)}", error=True)
                else:
                    show_snack("All gain-adjusted audio files saved and upload queue updated.")
            save_btn = ft.TextButton("Save Adjusted Audio", on_click=on_save_adjusted_audio_all_click, tooltip="Save gain-adjusted audio for all tracks in the dialog")

        if n_images == 0:
            msg = "No waveforms could be generated for the files in the queue."
            if skipped_files:
                msg += "\n\nDetails:"
                for s in skipped_files:
                    msg += f"\n- {s}"
            images = [ft.Text(msg, color=ft.Colors.RED)]
            dlg_actions = [ft.TextButton("Close", on_click=lambda e: page.close(dlg))]
        else:
            images.append(global_gain_slider)
            images.append(ft.Text("Adjust all tracks at once with the global gain slider above. You can still fine-tune individual tracks below.", size=10, color=ft.Colors.BLUE))
            for audio, framerate, ext, filepath, gain_slider, col, gain_val in per_track:
                if gain_slider is not None and audio is not None:
                    images.append(ft.Column([
                        gain_slider,
                        col
                    ]))
                else:
                    images.append(col)
            images.insert(0, ft.Text(f"Generated {n_images} waveform(s) for {len(files)} file(s).", color=ft.Colors.GREEN))
            dlg_actions = [save_btn, ft.TextButton("Close", on_click=lambda e: page.close(dlg))] if save_btn else [ft.TextButton("Close", on_click=lambda e: page.close(dlg))]

        dlg = ft.AlertDialog(
            title=ft.Text("Waveforms for files to be uploaded"),
            content=ft.Column(images, scroll=ft.ScrollMode.AUTO, expand=True),
            actions=dlg_actions,
            scrollable=True
        )
        page.open(dlg)
        page.update()
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
    export_selected_btn = ft.ElevatedButton('Export Selected', disabled=True)

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
            from yoto_app.upload_tasks import FileUploadRow
            for f in files:
                if f not in existing:
                    try:
                        file_row = FileUploadRow(f, maybe_page=page, maybe_column=file_rows_column)
                        file_rows_column.controls.append(file_row.row)
                    except Exception:
                        file_rows_column.controls.append(ft.Row([ft.Text(os.path.basename(f))]))
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
                        file_row = ft.Row([ft.Text(path)])
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
    playlist_export_selected_btn = playlists_ui['export_selected_btn']
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
    'normalize_audio_control': normalize_checkbox,
    'gain_adjusted_files': gain_adjusted_files,
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
        try:
            ctx['normalize_audio'] = bool(normalize_checkbox.value)
        except Exception:
            ctx['normalize_audio'] = False
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
            normalize_checkbox,
            upload_mode_dropdown  # Add the new dropdown here
        ]),
        ft.Row([
            folder, 
            ft.TextButton("Browse Folder...", on_click=lambda e: browse.pick_files(allow_multiple=True)),
            ft.TextButton("Add Files...", on_click=lambda e: browse_files.pick_files(allow_multiple=True)),
            ft.TextButton("Clear Queue", on_click=clear_queue),
            ft.TextButton("Show Waveforms", on_click=show_waveforms_popup, tooltip="Visualize sound levels for all files in the queue"),
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
