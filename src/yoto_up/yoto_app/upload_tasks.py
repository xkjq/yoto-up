import asyncio
import os
import traceback
import tempfile
import shutil
from yoto_up.models import Chapter, ChapterDisplay, Card, CardContent, CardMetadata
from yoto_up.yoto_api import YotoAPI
from yoto_up.normalization import AudioNormalizer
import re
from loguru import logger
import webbrowser
import flet as ft
import sys
from yoto_up.yoto_app.ui_state import set_state, get_state
import threading
from yoto_up.yoto_app.show_waveforms import show_waveforms_popup
from yoto_up.yoto_app.startup import audio_adjust_utils
from pydub import AudioSegment
import webbrowser

# module-level reference to the last active page so row buttons can open dialogs
_LAST_PAGE = None


# --- Robust FileUploadRow class ---
class FileUploadRow:
    def __init__(self, filepath, maybe_page=None, maybe_column=None):

        # use ft.* controls

        self.filepath = filepath
        self.original_filepath = filepath  # Always keep the original file path
        self.name = os.path.basename(filepath)
        self.status_text = ft.Text("Queued")
        self.progress = ft.ProgressBar(width=300, visible=False)
        self.inner_row = ft.Row(
            [
                ft.Text(self.name, width=300),
                ft.Button("Preview", on_click=self.on_preview),
                self.progress,
                self.status_text,
                ft.Button("View details", on_click=self.on_view_details),
                ft.Button("Remove", on_click=self.on_remove),
            ]
        )
        self.row = ft.Container(content=self.inner_row, bgcolor=None, padding=0)
        setattr(self.row, "filename", filepath)
        setattr(self.row, "_fileuploadrow", self)
        self.maybe_page = maybe_page
        self.maybe_column = maybe_column
        self.uploaded = False  # Track if this file has been uploaded

    def set_status(self, value):
        self.status_text.value = value

    def set_progress(self, frac):
        self.progress.visible = True
        self.progress.value = frac
        if self.maybe_page:
            self.maybe_page.update()

    def on_upload_complete(self):
        logger.debug(f"[FileUploadRow] on_upload_complete called for {self.name}")
        self.uploaded = True
        # Change the row background color for visual indication
        self.row.bgcolor = "#71fb91"  # light green
        # Force UI update by removing and re-adding the row in the parent column
        if self.maybe_column:
            try:
                idx = self.maybe_column.controls.index(self.row)
                self.maybe_column.controls.pop(idx)
                self.maybe_column.controls.insert(idx, self.row)
                self.maybe_column.update()
            except Exception as e:
                logger.error(f"[FileUploadRow] Failed to refresh row color: {e}")
        if self.maybe_page:
            self.maybe_page.update()

    def on_view_details(self, ev=None):
        try:
            page = self.maybe_page
            if not page:
                print("[FileUploadRow] No page available to show dialog")
                return
            tags = {}
            try:
                from mutagen import File as MutagenFile

                mf = MutagenFile(self.filepath)
                if mf is not None:
                    tag_items = []
                    for k, v in getattr(mf, "tags", {}).items():
                        try:
                            if isinstance(v, (list, tuple)):
                                val = ", ".join(str(item) for item in v)
                            else:
                                val = str(v)
                            tag_items.append((str(k), val))
                        except Exception:
                            tag_items.append((str(k), repr(v)))
                    tag_items.sort()
                    for k, v in tag_items:
                        tags[k] = v
                    if hasattr(mf, "info"):
                        info = mf.info
                        if hasattr(info, "length"):
                            tags["duration"] = f"{info.length:.2f} sec"
                        if hasattr(info, "bitrate"):
                            tags["bitrate"] = (
                                f"{getattr(info, 'bitrate', 0) // 1000} kbps"
                            )
                        if hasattr(info, "channels"):
                            tags["channels"] = str(getattr(info, "channels"))
                        if hasattr(info, "sample_rate"):
                            tags["sample_rate"] = f"{getattr(info, 'sample_rate')} Hz"
            except Exception:
                try:
                    if (
                        self.filepath.lower().endswith(".mp3")
                        and os.path.getsize(self.filepath) > 128
                    ):
                        with open(self.filepath, "rb") as fh:
                            fh.seek(-128, os.SEEK_END)
                            tagdata = fh.read(128)
                            if tagdata[:3] == b"TAG":
                                tags["title"] = (
                                    tagdata[3:33]
                                    .decode("latin1", errors="ignore")
                                    .strip("\x00 ")
                                    .strip()
                                )
                                tags["artist"] = (
                                    tagdata[33:63]
                                    .decode("latin1", errors="ignore")
                                    .strip("\x00 ")
                                    .strip()
                                )
                                tags["album"] = (
                                    tagdata[63:93]
                                    .decode("latin1", errors="ignore")
                                    .strip("\x00 ")
                                    .strip()
                                )
                                tags["year"] = (
                                    tagdata[93:97]
                                    .decode("latin1", errors="ignore")
                                    .strip("\x00 ")
                                    .strip()
                                )
                            else:
                                tags["info"] = "No ID3v1 tags found"
                    else:
                        tags["info"] = (
                            "Unsupported or non-mp3 file for fallback parsing"
                        )
                except Exception as fe:
                    tags["error"] = f"Fallback tag read failed: {fe}"
            lines = []
            if not tags:
                lines = [ft.Text("No tags found")]
            else:
                for k, v in tags.items():
                    lines.append(ft.Text(f"{k}: {v}"))
            dlg = ft.AlertDialog(
                title=ft.Text(f"Media details: {self.name}"),
                content=ft.Column(lines),
                actions=[ft.Button("OK", on_click=lambda e: page.pop_dialog())],
            )
            page.show_dialog(dlg)
            page.update()
        except Exception as e:
            print(f"[on_view_details] error: {e}")

    def on_preview(self, ev=None):
        url = f"file://{os.path.abspath(self.filepath)}"
        try:
            webbrowser.open(url)
        except Exception as ex:
            print(f"[Preview] Failed to open {url}: {ex}")

    def on_remove(self, ev=None):
        col = self.maybe_column
        if not col:
            print("[FileUploadRow] No column available to remove row")
            return
        try:
            col.controls.remove(self)
        except Exception:
            for existing in list(col.controls):
                if getattr(existing, "filename", None) == self.filepath:
                    try:
                        col.controls.remove(existing)
                    except Exception:
                        pass
        try:
            page = self.maybe_page
            if page:
                page.update()
        except Exception:
            pass

    def update_file(self, new_filepath):
        """
        Update the row to reference a new file path and update displayed name.
        """
        self.filepath = new_filepath
        # self.name is only for display; keep original for title
        self.name = os.path.basename(new_filepath)
        # Update the filename attribute on the row container
        setattr(self.row, "filename", new_filepath)
        # Update the displayed file name in the UI
        self.inner_row.controls[0].value = self.name
        # Optionally reset status and progress
        self.set_status("Queued")
        self.set_progress(0.0)
        self.uploaded = False
        if self.maybe_page:
            self.maybe_page.update()


# --- End FileUploadRow class ---


class UploadManager:
    """Class to manage upload state and tasks.

    UploadManager accepts the UI components and helpers required to build
    the upload execution context. It constructs the `ctx` mapping lazily
    at start time so the GUI doesn't need to assemble or manipulate that
    mapping itself.
    """

    def __init__(self, page, api_ref: dict, show_snack):
        # store page reference for helper methods
        self.page = page
        ctx = {}
        overall_bar = ft.ProgressBar(width=400, visible=False)
        overall_text = ft.Text("")
        file_rows_column = ft.Column()
        # Counters for overall progress
        total_files = 0
        completed_count = 0

        gain_adjusted_files = {}  # {filepath: {'gain': float, 'temp_path': str or None}}
        waveform_cache = {}

        # File picker and folder controls.
        # On Linux desktop, FilePicker depends on "zenity". If it's missing,
        # Flet may surface a confusing "Unknown control: FilePicker" error.
        _is_linux_desktop = sys.platform.startswith("linux") and not getattr(
            page, "web", False
        )
        try:
            _zenity_missing = _is_linux_desktop and shutil.which("zenity") is None
        except Exception:
            logger.warning(
                "Error checking for zenity; assuming file picker is supported",
                exc_info=True,
            )
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
            label="Concurrency",
            value=get_state("gui", "concurrency", "4"),
            width=80,
            on_change=lambda e: set_state("gui", "concurrency", concurrency.value),
        )
        strip_leading_checkbox = ft.Checkbox(
            label="Strip leading track numbers",
            value=get_state("gui", "strip_leading", True),
            tooltip="Remove common leading track number prefixes from filenames (e.g. '01 - ', '1. ', '01)', '001_')",
            on_change=lambda e: set_state(
                "gui", "strip_leading", strip_leading_checkbox.value
            ),
        )
        intro_outro_side = ft.Dropdown(
            label="Side",
            value=get_state("gui", "intro_outro_side", "intro"),
            options=[ft.dropdown.Option("intro"), ft.dropdown.Option("outro")],
            width=100,
            on_select=lambda e: set_state(
                "gui", "intro_outro_side", intro_outro_side.value
            ),
        )
        intro_seconds = ft.TextField(
            label="Segment seconds",
            value=get_state("gui", "intro_outro_seconds", "10.0"),
            width=80,
            on_change=lambda e: set_state(
                "gui", "intro_outro_seconds", intro_seconds.value
            ),
        )
        similarity_threshold = ft.TextField(
            label="Similarity threshold",
            value=get_state("gui", "intro_outro_threshold", "0.75"),
            width=80,
            on_change=lambda e: set_state(
                "gui", "intro_outro_threshold", similarity_threshold.value
            ),
        )
        upload_target_dropdown = ft.Dropdown(
            label="Upload target",
            value=get_state("gui", "upload_target", "Create new card"),
            options=[
                ft.dropdown.Option("Create new card"),
                ft.dropdown.Option("Add to existing card"),
            ],
        )
        new_card_title = ft.TextField(label="New card title", width=400)

        # Placeholders that will be populated/overwritten by playlists module
        self.existing_card_dropdown = ft.Dropdown(label="Existing card", options=[])
        self.existing_card_map = {}

        # Ensure only the relevant upload target control is visible
        try:
            if upload_target_dropdown.value == "Create new card":
                new_card_title.visible = True
                self.existing_card_dropdown.visible = False
            else:
                new_card_title.visible = False
                self.existing_card_dropdown.visible = True
        except Exception:
            # conservative defaults
            new_card_title.visible = True
            self.existing_card_dropdown.visible = False

        def _on_upload_target_change(ev=None):
            try:
                if upload_target_dropdown.value == "Create new card":
                    new_card_title.visible = True
                    self.existing_card_dropdown.visible = False
                else:
                    new_card_title.visible = False
                    self.existing_card_dropdown.visible = True


                    # Refresh options via UploadManager helper
                    self.refresh_existing_card_options()

                page.update()
            except Exception as exc:
                logger.error(f"[_on_upload_target_change] failed: {exc}")

        upload_target_dropdown.on_select = _on_upload_target_change

        def remove_uploaded_files(ev=None):
            logger.debug(
                "[remove_uploaded_files] Removing uploaded files from the queue"
            )
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
        remove_uploaded_btn = ft.Button(
            "Remove Uploaded", on_click=remove_uploaded_files
        )

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

        # expose commonly-used internals for external helpers/tests
        self.files_row_column = file_rows_column
        self.overall_bar = overall_bar
        self.overall_text = overall_text
        self.show_snack = show_snack
        self.update_overall = update_overall
        self.ctx = ctx
        # page.status is created by gui; expose it if available
        self.status = getattr(page, "status", None)


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
                    raise RuntimeError(
                        f"Failed to create FileUploadRow for {temp_path}"
                    )
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
                from yoto_app.intro_outro import (
                    per_window_common_prefix,
                    trim_audio_file,
                )
            except Exception:
                show_snack(
                    "Intro/outro analysis unavailable (missing module)", error=True
                )
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
                sim_thresh = float(
                    dialog_controls.get("window_similarity").value or 0.95
                )
            except Exception:
                sim_thresh = 0.95
            for p, perw in per_file_per_window.items():
                try:
                    # consider only the windows that were accepted
                    relevant = perw[:windows_matched]
                    matched = sum(1 for v in relevant if v >= sim_thresh)
                    score = (
                        float(matched) / float(windows_matched)
                        if windows_matched
                        else 0.0
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
                                    [
                                        ft.ProgressRing(),
                                        ft.Text("Preparing preview..."),
                                    ],
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
                                    "Close",
                                    on_click=lambda e: open_intro_outro_dialog(e),
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
                                preview_wav = temp_dir / (
                                    Path(src).stem + ".preview.wav"
                                )
                                wav_ok = False
                                try:
                                    segment.export(str(preview_wav), format="wav")
                                    wav_ok = preview_wav.exists()
                                except Exception:
                                    wav_ok = False

                                # Fallback: if original-format preview written, try converting that to WAV
                                if not wav_ok and preview_path.exists():
                                    try:
                                        tmp_seg = AudioSegment.from_file(
                                            str(preview_path)
                                        )
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
                                                if wav_available
                                                and preview_wav.exists()
                                                else preview_path
                                            )
                                            webbrowser.open(
                                                Path(target).resolve().as_uri()
                                            )
                                        except Exception as ex:
                                            show_snack(
                                                f"Failed to open preview: {ex}",
                                                error=True,
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
                                                str(Path(display_target).resolve()),
                                                size=12,
                                            )
                                        )
                                    except Exception:
                                        pass

                                    content = ft.Column(
                                        items, scroll=ft.ScrollMode.AUTO
                                    )
                                    return ft.AlertDialog(
                                        title=ft.Text("Preview"),
                                        content=content,
                                        actions=[
                                            ft.TextButton(
                                                "Close",
                                                on_click=lambda e: (
                                                    open_intro_outro_dialog(e)
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
                preview_btn.on_click = make_preview_handler(
                    p, preview_btn, seconds, side
                )

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
                            float(seconds_matched)
                            if seconds_matched is not None
                            else 0.0
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
                                temp_dir
                                / (src_path.stem + ".trimmed" + src_path.suffix)
                            )

                            trim_audio_file(
                                orig_p,
                                dest,
                                remove_intro_seconds=remove_t
                                if side == "intro"
                                else 0.0,
                                remove_outro_seconds=remove_t
                                if side == "outro"
                                else 0.0,
                                keep_silence_ms=padding_ms,
                            )

                            # update matching rows to point to trimmed file
                            for ctrl in list(file_rows_column.controls):
                                fur = getattr(ctrl, "_fileuploadrow", None)
                                try:
                                    if fur and (
                                        getattr(fur, "original_filepath", None)
                                        == orig_p
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
                                futures.append(
                                    executor.submit(_trim_one, orig_p, norm_p)
                                )

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
                                                or getattr(fur, "filepath", None)
                                                == orig_p
                                                or getattr(ctrl, "filename", None)
                                                == orig_p
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
                                                    getattr(
                                                        fur, "original_filepath", None
                                                    )
                                                    == orig_p
                                                    or getattr(fur, "filepath", None)
                                                    == orig_p
                                                    or getattr(ctrl, "filename", None)
                                                    == orig_p
                                                ):
                                                    fur.update_file(dest)
                                                    fur.set_status(
                                                        "Trimmed intro/outro"
                                                    )
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
            d_window_seconds = ft.TextField(
                label="Window seconds", value="0.1", width=120
            )
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
                        ft.Row(
                            [d_window_seconds, d_window_similarity, d_window_min_files]
                        ),
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

        def run_coro_in_thread(coro, *args, **kwargs):
            """Run an async coroutine in a fresh event loop inside a daemon thread."""

            def _runner():
                try:
                    asyncio.run(coro(*args, **kwargs))
                except Exception as exc:
                    print("Background task error:", exc)

            threading.Thread(target=_runner, daemon=True).start()

        def _start_click(e):
            # update ctx with the current checkbox value
            try:
                ctx["strip_leading_track_numbers"] = bool(strip_leading_checkbox.value)
            except Exception:
                ctx["strip_leading_track_numbers"] = True

            try:
                ctx["local_normalization_enabled"] = bool(local_norm_checkbox.value)
                ctx["local_normalization_target"] = float(
                    local_norm_target.value or -23.0
                )
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

            target = getattr(upload_target_dropdown, "value", "Create new card")

            target_card_sel = getattr(existing_card_dropdown, "value", None)
            card_id = existing_card_map.get(target_card_sel) if target_card_sel else None
            run_coro_in_thread(
                start_uploads,
                e,
                api_ref,
                page,
                gain_adjusted_files,
                concurrency=concurrency.value,
                target=target,
                new_card_title=new_card_title.value,
                existing_card_id=card_id,
                ctx=ctx,
            )

        start_btn.on_click = _start_click
        stop_btn.on_click = lambda e: run_coro_in_thread(stop_uploads, e, page)

        # Upload page (appears after Playlists)
        # Add a dropdown to select upload mode: Chapters or Tracks
        upload_mode_dropdown = ft.Dropdown(
            label="Upload as",
            value=get_state("gui", "upload_mode", "Chapters"),
            options=[ft.dropdown.Option("Chapters"), ft.dropdown.Option("Tracks")],
            width=150,
            on_select=lambda e: set_state(
                "gui", "upload_mode", upload_mode_dropdown.value
            ),
        )

        if upload_target_dropdown.value == "Create new card":
            new_card_title.visible = True
            self.existing_card_dropdown.visible = False
        else:
            new_card_title.visible = False
            self.existing_card_dropdown.visible = True

        # Normalization controls
        local_norm_checkbox = ft.Checkbox(
            label="Normalize audio (local)",
            value=get_state("gui", "local_norm_enabled", False),
            tooltip="Normalize audio loudness before upload using ffmpeg-normalize",
            on_change=lambda e: set_state(
                "gui", "local_norm_enabled", local_norm_checkbox.value
            ),
        )
        local_norm_target = ft.TextField(
            label="Target LUFS",
            value=get_state("gui", "local_norm_target", "-23.0"),
            width=100,
            tooltip="Target integrated loudness in LUFS (default -23.0)",
            on_change=lambda e: set_state(
                "gui", "local_norm_target", local_norm_target.value
            ),
        )
        local_norm_batch = ft.Checkbox(
            label="Batch mode",
            value=get_state("gui", "local_norm_batch", False),
            tooltip="Normalize all files as a batch (Album mode) instead of individually",
            on_change=lambda e: set_state(
                "gui", "local_norm_batch", local_norm_batch.value
            ),
        )

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
                content=ft.Text(
                    "ffmpeg normalisation", size=12, weight=ft.FontWeight.W_400
                )
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
            content=local_norm_expander,
            margin=ft.Margin(top=6, bottom=6, left=0, right=0),
        )
        # Card info/link display (persistent at bottom)
        card_info_display = ft.Column([], visible=False)
        self.card_info_display = card_info_display  # expose to show_card_info

        self.column = ft.Column(
            [
                ft.Row(
                    [upload_target_dropdown, new_card_title, self.existing_card_dropdown]
                ),
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
                ft.Container(
                    content=file_rows_column, padding=10, bgcolor=ft.Colors.WHITE
                ),
                ft.Divider(),
                ft.Row([page.status]),
                ft.Divider(),
                card_info_display,
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        # Register service controls after page has content
        page.services.extend([p for p in (browse, browse_files) if p is not None])
        page.update()

    def refresh_existing_card_options(self):
        """Populate `self.existing_card_dropdown.options` from the current `page.cards` cache.

        This method also updates `self.existing_card_map`.
        """
        try:
            options = []
            self.existing_card_map.clear()
            cards = getattr(self.page, "cards", []) or []
            if not cards:
                self.page.run_task(self.page.fetch_playlists)
                return
            seen_titles = set()
            for c in cards:
                try:
                    # prefer Card model fields for a human-friendly title
                    base_title = (
                        getattr(c, "title", None)
                        or (getattr(c, "metadata", None) and getattr(c.metadata, "title", None))
                        or f"Card {getattr(c, 'cardId', '')}"
                    )
                    cid = getattr(c, "cardId", None)
                    if not cid:
                        continue
                    # If multiple cards share the same title, disambiguate by appending the id
                    if base_title in seen_titles:
                        display = f"{base_title} ({cid})"
                    else:
                        display = base_title
                        seen_titles.add(base_title)
                    options.append(ft.dropdown.Option(display, display))
                    # Map the displayed label back to the cardId for lookups elsewhere
                    self.existing_card_map[display] = cid
                except Exception:
                    continue
            self.existing_card_dropdown.options = options
            self.existing_card_dropdown.value = None
        except Exception:
            logger.exception("refresh_existing_card_options failed")

def show_card_popup(page, card):
    # Show a dialog with full card details
    lines = []
    lines.append(
        ft.Text(
            f"Title: {getattr(card, 'title', '')}",
            size=18,
            weight=ft.FontWeight.BOLD,
        )
    )
    lines.append(ft.Text(f"Card ID: {getattr(card, 'cardId', '')}", size=14))
    if getattr(card, "metadata", None):
        meta = card.metadata
        if getattr(meta, "author", None):
            lines.append(ft.Text(f"Author: {meta.author}"))
        if getattr(meta, "description", None):
            lines.append(ft.Text(f"Description: {meta.description}"))
        if getattr(meta, "note", None):
            lines.append(ft.Text(f"Note: {meta.note}"))
        if getattr(meta, "cover", None) and getattr(meta.cover, "imageL", None):
            lines.append(ft.Image(src=meta.cover.imageL, width=120, height=120))
    if getattr(card, "content", None) and getattr(card.content, "chapters", None):
        lines.append(ft.Text("Chapters:", weight=ft.FontWeight.BOLD))
        for ch in card.content.chapters:
            lines.append(ft.Text(f"- {getattr(ch, 'title', '')}"))
    lines.append(
        ft.TextButton(
            "View card",
            on_click=lambda e: show_card_details(e, card),
            style=ft.ButtonStyle(color=ft.Colors.BLUE),
        )
    )
    dlg = ft.AlertDialog(
        title=ft.Text("Card Details"),
        content=ft.Column(lines, scroll=ft.ScrollMode.AUTO, expand=True),
        actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog())],
        scrollable=True,
    )
    page.show_dialog(dlg)
    page.update()

def show_card_info(page, card):
    # Show a clickable card summary that launches show_card_detail
    card_info_display = page.upload_manager.card_info_display
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
            on_click=lambda e: show_card_popup(page, card),
            bgcolor=ft.Colors.BLUE_50,
            padding=10,
            border_radius=8,
            ink=True,
            tooltip="Click for card details",
        )
        card_info_display.controls.append(summary)
    card_info_display.visible = True
    page.update()


def clean_title_from_filename(fp: str, strip_leading_nums: bool = True) -> str:
    # Use the filename without extension
    base = os.path.splitext(os.path.basename(fp))[0]
    if strip_leading_nums:
        # remove common leading track number patterns like '01 - ', '1. ', '01) ', '01_', etc.
        cleaned = re.sub(r"^\s*\d{1,3}[\s\-\._:\)\]]*", "", base)
    else:
        cleaned = base
    return cleaned.strip()


# Shared helper: build chapters/tracks from transcoded results
def build_chapters_from_transcodes(
    transcoded_results,
    filename_list,
    title_for_single_chapter,
    api,
    single_chapter=False,
    existing_chapters=0,
):
    """
    Build a list of Chapter objects from transcoded results.
    - transcoded_results: list of transcoded audio return values from API
    - filename_list: list of cleaned titles corresponding to original files (used for chapter/track titles)
    - title_for_single_chapter: title to use when creating a single chapter containing all tracks
    - api: YotoAPI instance
    - single_chapter: if True, put all tracks into one Chapter
    - files_list / orig_files_list: used to map gain notes back to original basenames where needed
    Returns: list of Chapter instances
    """
    chapters_out = []
    if single_chapter and len(transcoded_results) > 1:
        tracks = []
        for i, tr in enumerate(transcoded_results):
            td = (
                {"title": filename_list[i]}
                if filename_list and i < len(filename_list)
                else None
            )
            track = api.get_track_from_transcoded_audio(tr, track_details=td)
            track.key = f"{i + 1:02}"
            track.overlayLabel = str(i + 1)
            tracks.append(track)
        chapter = Chapter(
            key=f"{i + 1 + existing_chapters:02}",
            title=title_for_single_chapter,
            overlayLabel=str(i + 1 + existing_chapters),
            tracks=tracks,
            display=ChapterDisplay(
                icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"
            ),
        )
        chapters_out = [chapter]
    else:
        for i, tr in enumerate(transcoded_results):
            if not tr:
                continue
            cd = (
                {"title": filename_list[i]}
                if filename_list and i < len(filename_list)
                else None
            )
            new_ch = api.get_chapter_from_transcoded_audio(tr, chapter_details=cd)
            try:
                new_ch.key = f"{i + 1 + existing_chapters:02}"
                new_ch.overlayLabel = str(i + 1 + existing_chapters)
                if hasattr(new_ch, "tracks") and new_ch.tracks:
                    for j, t in enumerate(new_ch.tracks):
                        t.key = f"{j + 1:02}"
                        t.overlayLabel = str(j + 1)
            except Exception:
                pass
            chapters_out.append(new_ch)
    return chapters_out


@logger.catch
async def start_uploads(
    event,
    api_ref,
    page,
    gain_adjusted_files=None,
    concurrency=4,
    target="Create new card",
    new_card_title=None,
    existing_card_id=None,
    ctx=None,
):
    """Start uploads migrated from gui; ctx is the UI/context dict."""
    if gain_adjusted_files is None:
        gain_adjusted_files = {}
    if ctx is None:
        # try to pull context from the page's upload_manager if available
        ctx = getattr(page, "upload_manager", None)
        try:
            ctx = getattr(page.upload_manager, "ctx", {}) if ctx is not None else {}
        except Exception:
            ctx = {}
    file_rows_column = page.upload_manager.files_row_column
    overall_bar = page.upload_manager.overall_bar
    overall_text = page.upload_manager.overall_text
    status = page.upload_manager.status
    show_snack = page.upload_manager.show_snack
    update_overall = page.upload_manager.update_overall
    fetch_playlists_sync = page.fetch_playlists_sync

    logger.debug("[start_uploads] Starting upload process")
    status.value = "Starting..."
    page.update()

    # Option: strip leading track numbers from filenames when used as titles
    strip_leading = bool(ctx.get("strip_leading_track_numbers", True))
    # Option: normalize audio loudness prior to upload (maps to API loudnorm flag)
    normalize_audio = bool(ctx.get("normalize_audio", False))

    # expose page for row button handlers
    global _LAST_PAGE
    _LAST_PAGE = page

    # Shared progress callback factory used by upload helper
    def make_progress_cb(idx):
        def progress_cb(msg, frac):
            try:
                row = file_rows_column.controls[idx]
                fileuploadrow = getattr(row, "_fileuploadrow", None)
                if fileuploadrow is None:
                    raise RuntimeError(
                        f"Row at idx={idx} is missing _fileuploadrow reference: {type(row)}"
                    )
                fileuploadrow.set_status(msg or "")
                if frac is not None:
                    fileuploadrow.set_progress(float(frac))
                page.update()
            except Exception as e:
                logger.debug(f"[progress_cb] failed for idx={idx}: {e}")

        return progress_cb

    async def upload_and_transcode_idx(
        idx, audio_path, filename_for_api, loudnorm=False, show_progress=True
    ):
        """Upload a file and transcode via API, updating UI row state; returns transcode result or None on failure."""
        fileuploadrow = None
        try:
            row = file_rows_column.controls[idx]
            fileuploadrow = getattr(row, "_fileuploadrow", None)
            if fileuploadrow is None:
                raise RuntimeError(
                    f"Row at idx={idx} is missing _fileuploadrow reference: {type(row)}"
                )
            # Start status
            fileuploadrow.set_status("Uploading...")
            fileuploadrow.set_progress(0.0)
            page.update()

            progress_cb = make_progress_cb(idx) if show_progress else None
            tr = await api.upload_and_transcode_audio_async(
                audio_path=audio_path,
                filename=filename_for_api,
                loudnorm=loudnorm,
                show_progress=bool(show_progress),
                poll_interval=2,
                max_attempts=60,
                progress_callback=progress_cb,
            )

            if tr is not None:
                if fileuploadrow is not None:
                    fileuploadrow.set_progress(1.0)
                    fileuploadrow.set_status("Done (100%)")
                    fileuploadrow.on_upload_complete()
            else:
                if fileuploadrow is not None:
                    fileuploadrow.set_progress(1.0)
                    fileuploadrow.set_status("Skipped (already exists)")
                    fileuploadrow.on_upload_complete()

            return tr
        except Exception as e:
            logger.error(
                f"upload_and_transcode_idx: error idx={idx}, path={audio_path}: {e}"
            )
            if fileuploadrow is not None:
                try:
                    fileuploadrow.set_status("Error")
                    page.update()
                except Exception:
                    pass
            return None

    async def schedule_uploads(file_paths, filename_list_local, show_progress=True):
        """Schedule uploads for file_paths using semaphore and upload helper.
        Returns a list of transcoded results (None for failures).
        """
        results = [None] * len(file_paths)

        async def worker(i, path, fname):
            async with sem:
                tr = await upload_and_transcode_idx(
                    i,
                    audio_path=path,
                    filename_for_api=fname,
                    loudnorm=normalize_audio,
                    show_progress=show_progress,
                )
                results[i] = tr
                # update overall after each completes
                try:
                    update_overall()
                except Exception:
                    pass
                try:
                    page.update()
                except Exception:
                    pass

        tasks_local = []
        for i, path in enumerate(file_paths):
            fname = (
                filename_list_local[i]
                if filename_list_local and i < len(filename_list_local)
                else os.path.basename(path)
            )
            tasks_local.append(asyncio.create_task(worker(i, path, fname)))

        if tasks_local:
            await asyncio.gather(*tasks_local)
        return results

    # Gather all unique FileUploadRow objects from file_rows_column.controls
    fileuploadrows = []
    orig_files = []
    files = []
    seen = set()
    for row in getattr(file_rows_column, "controls", []):
        fileuploadrow = getattr(row, "_fileuploadrow", None)
        path = getattr(row, "filename", None)
        if fileuploadrow is not None and path and path not in seen:
            fileuploadrows.append(fileuploadrow)
            # Always use the original file for title/track naming
            orig_path = getattr(fileuploadrow, "original_filepath", path)
            temp_info = gain_adjusted_files.get(orig_path)
            if temp_info and temp_info.get("temp_path"):
                files.append(temp_info["temp_path"])
                orig_files.append(orig_path)
            else:
                files.append(orig_path)
                orig_files.append(orig_path)
            seen.add(path)
    logger.debug(f"[start_uploads] Files to upload (from UI): {files}")
    if not files:
        status.value = "No files selected for upload."
        show_snack(status.value)
        print("[start_uploads] No files selected for upload.")
        page.update()
        return

    # --- Normalization Start ---
    local_norm_enabled = ctx.get("local_normalization_enabled", False)
    local_norm_target = ctx.get("local_normalization_target", -23.0)
    local_norm_batch = ctx.get("local_normalization_batch", False)
    temp_norm_dir = None

    if local_norm_enabled:
        try:
            status.value = "Normalizing audio..."
            page.update()
            temp_norm_dir = tempfile.mkdtemp(prefix="yoto_norm_")
            logger.info(
                f"Normalizing {len(files)} files to {temp_norm_dir} (Target: {local_norm_target}LUFS, Batch: {local_norm_batch})"
            )

            normalizer = AudioNormalizer(
                target_level=local_norm_target, batch_mode=local_norm_batch
            )

            def norm_progress(msg, val):
                status.value = f"Normalizing: {msg}"
                page.update()

            normalized_files = await asyncio.to_thread(
                normalizer.normalize, files, temp_norm_dir, norm_progress
            )

            if len(normalized_files) == len(files):
                files = normalized_files
                logger.info("Normalization complete. Using normalized files.")
            else:
                logger.error(
                    "Normalization returned different number of files. Using original files."
                )

        except Exception as e:
            logger.error(f"Normalization failed: {e}")
            status.value = f"Normalization failed: {e}"
            page.update()
            # Wait a bit so user sees the error
            await asyncio.sleep(2)
    # --- Normalization End ---

    # Note: intro/outro analysis is intentionally not run automatically during start_uploads.
    # Analysis should be run manually from the UI (Analyze button) prior to starting uploads.

    status.value = "Initializing API..."
    logger.debug("[start_uploads] Initializing YotoAPI")
    page.update()
    try:
        api: YotoAPI = api_ref.api
        logger.debug("[start_uploads] YotoAPI initialized successfully")
    except Exception as ex:
        status.value = f"API init failed: {ex}"
        show_snack(f"API init failed: {ex}", error=True)
        logger.error(f"[start_uploads] API init failed: {ex}")
        page.update()
        return

    maxc = int(getattr(concurrency, "value", 2))
    sem = asyncio.Semaphore(maxc)

    total_files = len(files)
    overall_bar.value = 0
    overall_text.value = f"0/{total_files} completed"
    try:
        overall_bar.visible = True
        overall_text.visible = True
    except Exception as e:
        logger.debug(f"[start_uploads] Failed to show overall progress: {e}")
    logger.debug(f"[start_uploads] Total files to upload: {total_files}")

    # No row creation here! Only use existing FileUploadRow objects.
    page.update()
    try:
        logger.debug("[start_uploads] Rows present:")
        for i, r in enumerate(getattr(file_rows_column, "controls", [])):
            try:
                types = [type(c).__name__ for c in getattr(r, "controls", [])]
                vis = None
                if len(getattr(r, "controls", [])) > 1:
                    ctrl = r.controls[1]
                    vis = getattr(ctrl, "visible", "no-visible-attr")
                logger.debug(f"  row[{i}] types={types} visible={vis}")
            except Exception as e:
                logger.debug(f"  row[{i}] inspect error: {e}")
    except Exception:
        pass

    # Launch workers (branch by upload target)
    tasks = []
    filename_list = [clean_title_from_filename(f, strip_leading) for f in orig_files]
    transcoded_results = [None] * len(files)
    gain_notes = {}
    for orig_path, info in gain_adjusted_files.items():
        gain = info.get("gain", 0.0)
        temp_path = info.get("temp_path")
        if temp_path and abs(gain) > 0.01:
            gain_notes[temp_path] = gain
    # Prepare gain adjustment note lines for card metadata
    gain_note_lines = []
    for i, f in enumerate(files):
        gain = gain_notes.get(f)
        if gain is not None:
            gain_note_lines.append(
                f"Gain adjusted by {gain:+.2f} dB on 2025-09-13 for: {os.path.basename(orig_files[i])}"
            )
    if target == "Create new card":
        title = (getattr(new_card_title, "value", "") or "").strip() or "New Yoto Card"
        # Map from upload file path to gain adjustment (if any)

        # Use shared scheduler to upload all files in parallel (bounded by semaphore)
        transcoded_results = await schedule_uploads(files, filename_list)

        # After all uploads, check for failures before creating the card
        failed_files = [
            filename_list[i] for i, tr in enumerate(transcoded_results) if tr is None
        ]
        if failed_files:
            status.value = (
                f"Upload failed for: {', '.join(failed_files)}. Card not created."
            )
            show_snack(status.value, error=True)
            logger.error(f"Upload failed for files: {failed_files}. Card not created.")
            page.update()
            return

        try:
            status.value = "Creating card..."
            page.update()
            upload_mode_dropdown = ctx.get("upload_mode_dropdown")
            single_chapter = False
            if upload_mode_dropdown:
                mode_value = getattr(upload_mode_dropdown, "value", "Chapters")
                single_chapter = mode_value == "Tracks"

            # Build chapters/tracks for the new card using shared helper
            chapters = build_chapters_from_transcodes(
                transcoded_results=transcoded_results,
                filename_list=filename_list,
                title_for_single_chapter=title,
                api=api,
                single_chapter=single_chapter,
            )
            # Compose card metadata with gain adjustment notes
            card_metadata = None
            if gain_note_lines:
                card_metadata = CardMetadata(note="\n".join(gain_note_lines))
            card = Card(
                title=title,
                content=CardContent(chapters=chapters),
                metadata=card_metadata,
            )
            # If there is an existing note, append to it
            if gain_note_lines:
                prev_note = getattr(card.metadata, "note", "") if card.metadata else ""
                if prev_note and not prev_note.endswith("\n"):
                    prev_note += "\n"
                # Ensure note is always a string
                note_val = (prev_note or "") + "\n".join(gain_note_lines)
                if card.metadata:
                    card.metadata.note = str(note_val)
            created = api.create_or_update_content(card, return_card=True)
            cid = created.cardId
            status.value = f"Created card: {cid}" if cid else "Card created"
            show_snack(status.value)
            show_card_info(page, created)
            fetch_playlists_sync(page)
        except Exception as e:
            logger.error(f"start_uploads: create card error: {e}")
            traceback.print_exc()
        finally:
            page.update()
    else:
        if not existing_card_id:
            status.value = "No target card selected for append"
            show_snack(status.value, error=True)
            page.update()
            return

        # Schedule uploads using shared scheduler
        transcoded_results = await schedule_uploads(
            files, filename_list, show_progress=False
        )

        async def append_all_after_uploads(tasks_to_wait):
            print(
                "[start_uploads] Waiting for all uploads to complete before appending"
            )

            print(f"[start_uploads] Selected existing card: {sel} -> {existing_card_id}")
            if not existing_card_id:
                status.value = "No target card selected"
                page.update()
                return

            status.value = "Appending chapters to card..."
            page.update()
            # Card info display hook

            def do_append():
                try:
                    print(f"[start_uploads] Fetching card for batch append: {existing_card_id}")
                    card = api.get_card(existing_card_id)

                    upload_mode_dropdown = ctx.get("upload_mode_dropdown")
                    single_chapter = False
                    if upload_mode_dropdown:
                        mode_value = getattr(upload_mode_dropdown, "value", "Chapters")
                        single_chapter = mode_value == "Tracks"

                    if not getattr(card, "content", None):
                        card.content = type(card.content)()
                    if not getattr(card.content, "chapters", None):
                        card.content.chapters = []

                    if single_chapter and len(transcoded_results) > 1:
                        # Build a single chapter containing all tracks and append
                        chapters_to_add = build_chapters_from_transcodes(
                            transcoded_results=transcoded_results,
                            filename_list=filename_list,
                            title_for_single_chapter=f"Chapter {len(card.content.chapters) + 1}",
                            api=api,
                            single_chapter=True,
                            existing_chapters=len(card.content.chapters),
                        )
                        for ch in chapters_to_add:
                            card.content.chapters.append(ch)
                    else:
                        # One chapter per file
                        chapters_to_add = build_chapters_from_transcodes(
                            transcoded_results=transcoded_results,
                            filename_list=filename_list,
                            title_for_single_chapter=None,
                            api=api,
                            single_chapter=False,
                            existing_chapters=len(card.content.chapters),
                        )
                        for ch in chapters_to_add:
                            card.content.chapters.append(ch)

                    # If there is an existing note, append to it
                    if gain_note_lines:
                        prev_note = (
                            getattr(card.metadata, "note", "") if card.metadata else ""
                        )
                        if prev_note and not prev_note.endswith("\n"):
                            prev_note += "\n"
                        # Ensure note is always a string
                        note_val = (prev_note or "") + "\n".join(gain_note_lines)
                        if card.metadata:
                            card.metadata.note = str(note_val)
                        else:
                            card.metadata = CardMetadata(note=str(note_val))

                    created = api.create_or_update_content(card, return_card=True)
                    status.value = "Chapters appended"
                    show_card_info(page, created)
                    return True, None
                except Exception as ex:
                    print(f"[start_uploads] Batch append error: {ex}")
                    return False, ex

            ok, err = await asyncio.to_thread(do_append)
            if not ok:
                status.value = f"Append failed: {err}"
                show_snack(status.value, error=True)
                for idx, r in enumerate(file_rows_column.controls):
                    fileuploadrow = getattr(r, "_fileuploadrow", None)
                    if fileuploadrow is None:
                        raise RuntimeError(
                            f"Row is missing _fileuploadrow reference: {type(r)}"
                        )
                    if transcoded_results[idx]:
                        fileuploadrow.set_status("Transcoded (not appended)")
                    else:
                        if fileuploadrow.status_text.value != "Error":
                            fileuploadrow.set_status("Error")
                page.update()
            else:
                status.value = "All chapters appended"
                show_snack(status.value)
                for r in file_rows_column.controls:
                    fileuploadrow = getattr(r, "_fileuploadrow", None)
                    if fileuploadrow is None:
                        raise RuntimeError(
                            f"Row is missing _fileuploadrow reference: {type(r)}"
                        )
                    fileuploadrow.set_status("Done (appended)")
                    fileuploadrow.on_upload_complete()
                page.update()

        # append_all_after_uploads does not need the original upload_tasks variable
        # (results are already awaited); pass an empty list to avoid referencing
        # the undefined local `upload_tasks` variable which caused UnboundLocalError.
        append_task = asyncio.create_task(append_all_after_uploads([]))
        tasks = [append_task]

    status.value = "Uploading..."
    page.upload_manager.start_btn.disabled = True
    page.upload_manager.stop_btn.disabled = False
    logger.debug("[start_uploads] Upload tasks started")
    # Make per-file progress bars visible now that uploads have started
    try:
        for r in file_rows_column.controls:
            fileuploadrow = getattr(r, "_fileuploadrow", None)
            if fileuploadrow is not None:
                fileuploadrow.progress.visible = True
    except Exception:
        pass
    page.update()

    print("[start_uploads] Waiting for all upload tasks to complete")
    try:
        await asyncio.gather(*tasks)
        logger.debug("[start_uploads] All upload tasks completed")
    except Exception as e:
        logger.error(f"[start_uploads] Error occurred while waiting for tasks: {e}")
    finally:
        if temp_norm_dir and os.path.exists(temp_norm_dir):
            try:
                shutil.rmtree(temp_norm_dir)
                logger.debug(f"Cleaned up temp normalization dir: {temp_norm_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp dir {temp_norm_dir}: {e}")

        status.value = "Finished"
        try:
            ctx.get("start_btn").disabled = False
            ctx.get("stop_btn").disabled = True
        except Exception:
            pass
        logger.debug("[start_uploads] Upload process finished")
        try:
            overall_bar.visible = False
            overall_text.visible = False
        except Exception:
            pass
        # clear module page reference
        _LAST_PAGE = None
        page.update()


async def stop_uploads(event, page):
    if page.status:
        page.status.value = "Stopping... (will finish active uploads)"
    if page:
        page.update()
