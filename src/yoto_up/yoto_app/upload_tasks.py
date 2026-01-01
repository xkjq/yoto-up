import asyncio
import os
import traceback
import tempfile
import shutil
from yoto_up.models import Chapter, ChapterDisplay, Card, CardContent, CardMetadata
from yoto_up.yoto_api import YotoAPI
from yoto_up.normalization import AudioNormalizer
from flet import Text, ElevatedButton, AlertDialog, Column
import re
from loguru import logger
import webbrowser
# (Intro/outro analysis is executed from the UI module when requested.)

# module-level reference to the last active page so row buttons can open dialogs
_LAST_PAGE = None

# --- Robust FileUploadRow class ---
class FileUploadRow:
    def __init__(self, filepath, maybe_page=None, maybe_column=None):
        from flet import Row, ProgressBar
        self.filepath = filepath
        self.original_filepath = filepath  # Always keep the original file path
        self.name = os.path.basename(filepath)
        self.status_text = Text('Queued')
        self.progress = ProgressBar(width=300, visible=False)
        self.inner_row = Row([
            Text(self.name, width=300),
            ElevatedButton('Preview', on_click=self.on_preview),
            self.progress,
            self.status_text,
            ElevatedButton('View details', on_click=self.on_view_details),
            ElevatedButton('Remove', on_click=self.on_remove)
        ])
        from flet import Container
        self.row = Container(content=self.inner_row, bgcolor=None, padding=0)
        setattr(self.row, 'filename', filepath)
        setattr(self.row, '_fileuploadrow', self)
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
                print('[FileUploadRow] No page available to show dialog')
                return
            tags = {}
            try:
                from mutagen import File as MutagenFile
                mf = MutagenFile(self.filepath)
                if mf is not None:
                    tag_items = []
                    for k, v in getattr(mf, 'tags', {}).items():
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
                    if hasattr(mf, 'info'):
                        info = mf.info
                        if hasattr(info, 'length'):
                            tags['duration'] = f"{info.length:.2f} sec"
                        if hasattr(info, 'bitrate'):
                            tags['bitrate'] = f"{getattr(info, 'bitrate', 0) // 1000} kbps"
                        if hasattr(info, 'channels'):
                            tags['channels'] = str(getattr(info, 'channels'))
                        if hasattr(info, 'sample_rate'):
                            tags['sample_rate'] = f"{getattr(info, 'sample_rate')} Hz"
            except Exception:
                try:
                    if self.filepath.lower().endswith('.mp3') and os.path.getsize(self.filepath) > 128:
                        with open(self.filepath, 'rb') as fh:
                            fh.seek(-128, os.SEEK_END)
                            tagdata = fh.read(128)
                            if tagdata[:3] == b'TAG':
                                tags['title'] = tagdata[3:33].decode('latin1', errors='ignore').strip('\x00 ').strip()
                                tags['artist'] = tagdata[33:63].decode('latin1', errors='ignore').strip('\x00 ').strip()
                                tags['album'] = tagdata[63:93].decode('latin1', errors='ignore').strip('\x00 ').strip()
                                tags['year'] = tagdata[93:97].decode('latin1', errors='ignore').strip('\x00 ').strip()
                            else:
                                tags['info'] = 'No ID3v1 tags found'
                    else:
                        tags['info'] = 'Unsupported or non-mp3 file for fallback parsing'
                except Exception as fe:
                    tags['error'] = f'Fallback tag read failed: {fe}'
            lines = []
            if not tags:
                lines = [Text('No tags found')]
            else:
                for k, v in tags.items():
                    lines.append(Text(f"{k}: {v}"))
            dlg = AlertDialog(title=Text(f"Media details: {self.name}"), content=Column(lines), actions=[ElevatedButton('OK', on_click=lambda e: page.close(dlg))])
            page.open(dlg)
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
            print('[FileUploadRow] No column available to remove row')
            return
        try:
            col.controls.remove(self)
        except Exception:
            for existing in list(col.controls):
                if getattr(existing, 'filename', None) == self.filepath:
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
        setattr(self.row, 'filename', new_filepath)
        # Update the displayed file name in the UI
        if self.inner_row.controls and isinstance(self.inner_row.controls[0], Text):
            self.inner_row.controls[0].value = self.name
        # Optionally reset status and progress
        self.set_status('Queued')
        self.set_progress(0.0)
        self.uploaded = False
        if self.maybe_page:
            self.maybe_page.update()

# --- End FileUploadRow class ---

@logger.catch
async def start_uploads(event, ctx):
    """Start uploads migrated from gui; ctx is the UI/context dict.

    Expected ctx keys: page, folder, utils_mod, ensure_api, api_ref, concurrency,
    file_rows_column, overall_bar, overall_text, status, show_snack, update_overall,
    upload_target_dropdown, new_card_title, existing_card_dropdown, existing_card_map,
    start_btn, stop_btn
    """
    gain_adjusted_files = ctx.get('gain_adjusted_files', {})
    page = ctx["page"]
    #folder_widget = ctx["folder"]
    #utils_mod = ctx["utils_mod"]
    ensure_api = ctx["ensure_api"]
    api_ref = ctx["api_ref"]
    concurrency_widget = ctx["concurrency"]
    file_rows_column = ctx["file_rows_column"]
    overall_bar = ctx["overall_bar"]
    overall_text = ctx["overall_text"]
    status = ctx["status"]
    show_snack = ctx["show_snack"]
    update_overall = ctx["update_overall"]
    upload_target_dropdown = ctx["upload_target_dropdown"]
    new_card_title = ctx["new_card_title"]
    existing_card_dropdown = ctx["existing_card_dropdown"]
    existing_card_map = ctx["existing_card_map"]
    # optional helper to trigger synchronous playlist fetch if provided
    fetch_playlists_sync = ctx.get('fetch_playlists_sync')

    logger.debug("[start_uploads] Starting upload process")
    status.value = "Starting..."
    page.update()

    # Option: strip leading track numbers from filenames when used as titles
    strip_leading = bool(ctx.get('strip_leading_track_numbers', True))
    # Option: normalize audio loudness prior to upload (maps to API loudnorm flag)
    normalize_audio = bool(ctx.get('normalize_audio', False))

    def clean_title_from_filename(fp: str, strip_leading_nums: bool = True) -> str:
        # Use the filename without extension
        base = os.path.splitext(os.path.basename(fp))[0]
        if strip_leading_nums:
            # remove common leading track number patterns like '01 - ', '1. ', '01) ', '01_', etc.
            cleaned = re.sub(r'^\s*\d{1,3}[\s\-\._:\)\]]*', '', base)
        else:
            cleaned = base
        return cleaned.strip()

    # expose page for row button handlers
    global _LAST_PAGE
    _LAST_PAGE = page

    # Shared helper: build chapters/tracks from transcoded results
    def build_chapters_from_transcodes(transcoded_results, filename_list, title_for_single_chapter, api, single_chapter=False, existing_chapters=0):
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
                td = {'title': filename_list[i]} if filename_list and i < len(filename_list) else None
                track = api.get_track_from_transcoded_audio(tr, track_details=td)
                track.key = f"{i+1:02}"
                track.overlayLabel = str(i+1)
                tracks.append(track)
            chapter = Chapter(
                key=f"{i+1+existing_chapters:02}",
                title=title_for_single_chapter,
                overlayLabel=str(i+1+existing_chapters),
                tracks=tracks,
                display=ChapterDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
            )
            chapters_out = [chapter]
        else:
            for i, tr in enumerate(transcoded_results):
                if not tr:
                    continue
                cd = {'title': filename_list[i]} if filename_list and i < len(filename_list) else None
                new_ch = api.get_chapter_from_transcoded_audio(tr, chapter_details=cd)
                try:
                    new_ch.key = f"{i+1+existing_chapters:02}"
                    new_ch.overlayLabel = str(i+1+existing_chapters)
                    if hasattr(new_ch, 'tracks') and new_ch.tracks:
                        for j, t in enumerate(new_ch.tracks):
                            t.key = f"{j+1:02}"
                            t.overlayLabel = str(j+1)
                except Exception:
                    pass
                chapters_out.append(new_ch)
        return chapters_out

    # Shared progress callback factory used by upload helper
    def make_progress_cb(idx):
        def progress_cb(msg, frac):
            try:
                row = file_rows_column.controls[idx]
                fileuploadrow = getattr(row, '_fileuploadrow', None)
                if fileuploadrow is None:
                    raise RuntimeError(f"Row at idx={idx} is missing _fileuploadrow reference: {type(row)}")
                fileuploadrow.set_status(msg or '')
                if frac is not None:
                    fileuploadrow.set_progress(float(frac))
                page.update()
            except Exception as e:
                logger.debug(f"[progress_cb] failed for idx={idx}: {e}")
        return progress_cb

    async def upload_and_transcode_idx(idx, audio_path, filename_for_api, loudnorm=False, show_progress=True):
        """Upload a file and transcode via API, updating UI row state; returns transcode result or None on failure."""
        fileuploadrow = None
        try:
            row = file_rows_column.controls[idx]
            fileuploadrow = getattr(row, '_fileuploadrow', None)
            if fileuploadrow is None:
                raise RuntimeError(f"Row at idx={idx} is missing _fileuploadrow reference: {type(row)}")
            # Start status
            fileuploadrow.set_status('Uploading...')
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
                    fileuploadrow.set_status('Done (100%)')
                    fileuploadrow.on_upload_complete()
            else:
                if fileuploadrow is not None:
                    fileuploadrow.set_progress(1.0)
                    fileuploadrow.set_status('Skipped (already exists)')
                    fileuploadrow.on_upload_complete()

            return tr
        except Exception as e:
            logger.error(f"upload_and_transcode_idx: error idx={idx}, path={audio_path}: {e}")
            if fileuploadrow is not None:
                try:
                    fileuploadrow.set_status('Error')
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
                tr = await upload_and_transcode_idx(i, audio_path=path, filename_for_api=fname, loudnorm=normalize_audio, show_progress=show_progress)
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
            fname = filename_list_local[i] if filename_list_local and i < len(filename_list_local) else os.path.basename(path)
            tasks_local.append(asyncio.create_task(worker(i, path, fname)))

        if tasks_local:
            await asyncio.gather(*tasks_local)
        return results



    # Gather all unique FileUploadRow objects from file_rows_column.controls
    fileuploadrows = []
    orig_files = []
    files = []
    seen = set()
    for row in getattr(file_rows_column, 'controls', []):
        fileuploadrow = getattr(row, '_fileuploadrow', None)
        path = getattr(row, 'filename', None)
        if fileuploadrow is not None and path and path not in seen:
            fileuploadrows.append(fileuploadrow)
            # Always use the original file for title/track naming
            orig_path = getattr(fileuploadrow, 'original_filepath', path)
            temp_info = gain_adjusted_files.get(orig_path)
            if temp_info and temp_info.get('temp_path'):
                files.append(temp_info['temp_path'])
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
    local_norm_enabled = ctx.get('local_normalization_enabled', False)
    local_norm_target = ctx.get('local_normalization_target', -23.0)
    local_norm_batch = ctx.get('local_normalization_batch', False)
    temp_norm_dir = None

    if local_norm_enabled:
        try:
            status.value = "Normalizing audio..."
            page.update()
            temp_norm_dir = tempfile.mkdtemp(prefix="yoto_norm_")
            logger.info(f"Normalizing {len(files)} files to {temp_norm_dir} (Target: {local_norm_target}LUFS, Batch: {local_norm_batch})")
            
            normalizer = AudioNormalizer(target_level=local_norm_target, batch_mode=local_norm_batch)
            
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
                logger.error("Normalization returned different number of files. Using original files.")
                
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
        api: YotoAPI = ensure_api(api_ref)
        logger.debug("[start_uploads] YotoAPI initialized successfully")
    except Exception as ex:
        status.value = f"API init failed: {ex}"
        show_snack(f"API init failed: {ex}", error=True)
        logger.error(f"[start_uploads] API init failed: {ex}")
        page.update()
        return

    maxc = int(getattr(concurrency_widget, 'value', 2))
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
        logger.debug('[start_uploads] Rows present:')
        for i, r in enumerate(getattr(file_rows_column, 'controls', [])):
            try:
                types = [type(c).__name__ for c in getattr(r, 'controls', [])]
                vis = None
                if len(getattr(r, 'controls', [])) > 1:
                    ctrl = r.controls[1]
                    vis = getattr(ctrl, 'visible', 'no-visible-attr')
                logger.debug(f"  row[{i}] types={types} visible={vis}")
            except Exception as e:
                logger.debug(f"  row[{i}] inspect error: {e}")
    except Exception:
        pass

    # Card info display hook
    show_card_info = ctx.get('show_card_info')

    # Launch workers (branch by upload target)
    tasks = []
    target = getattr(upload_target_dropdown, 'value', 'Create new card')
    filename_list = [clean_title_from_filename(f, strip_leading) for f in orig_files]
    transcoded_results = [None] * len(files)
    gain_notes = {}
    for orig_path, info in gain_adjusted_files.items():
        gain = info.get('gain', 0.0)
        temp_path = info.get('temp_path')
        if temp_path and abs(gain) > 0.01:
            gain_notes[temp_path] = gain
    # Prepare gain adjustment note lines for card metadata
    gain_note_lines = []
    for i, f in enumerate(files):
        gain = gain_notes.get(f)
        if gain is not None:
            gain_note_lines.append(f"Gain adjusted by {gain:+.2f} dB on 2025-09-13 for: {os.path.basename(orig_files[i])}")
    if target == 'Create new card':
        title = (getattr(new_card_title, 'value', '') or '').strip() or 'New Yoto Card'
        # Map from upload file path to gain adjustment (if any)

        # Use shared scheduler to upload all files in parallel (bounded by semaphore)
        transcoded_results = await schedule_uploads(files, filename_list)

        # After all uploads, check for failures before creating the card
        failed_files = [filename_list[i] for i, tr in enumerate(transcoded_results) if tr is None]
        if failed_files:
            status.value = f"Upload failed for: {', '.join(failed_files)}. Card not created."
            show_snack(status.value, error=True)
            logger.error(f"Upload failed for files: {failed_files}. Card not created.")
            page.update()
            return

        try:
            status.value = 'Creating card...'
            page.update()
            upload_mode_dropdown = ctx.get('upload_mode_dropdown')
            single_chapter = False
            if upload_mode_dropdown:
                mode_value = getattr(upload_mode_dropdown, 'value', 'Chapters')
                single_chapter = (mode_value == 'Tracks')

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
                card_metadata = CardMetadata(note='\n'.join(gain_note_lines))
            card = Card(
                title=title,
                content=CardContent(chapters=chapters),
                metadata=card_metadata
            )
            # If there is an existing note, append to it
            if gain_note_lines:
                prev_note = getattr(card.metadata, 'note', '') if card.metadata else ''
                if prev_note and not prev_note.endswith('\n'):
                    prev_note += '\n'
                # Ensure note is always a string
                note_val = (prev_note or '') + '\n'.join(gain_note_lines)
                if card.metadata:
                    card.metadata.note = str(note_val)
            created = api.create_or_update_content(card, return_card=True)
            cid = created.cardId
            status.value = f'Created card: {cid}' if cid else 'Card created'
            show_snack(status.value)
            show_card_info(created)
            fetch_playlists_sync(None)
        except Exception as e:
            logger.error(f"start_uploads: create card error: {e}")
            traceback.print_exc()
        finally:
            page.update()
    else:

        # Early check: ensure an existing card is selected when appending.
        sel = getattr(existing_card_dropdown, 'value', None)
        card_id = existing_card_map.get(sel)
        if not card_id:
            # If the existing card map is empty, try to populate it synchronously
            # via the optional fetch_playlists_sync hook, then re-check selection.
            if (not existing_card_map or len(existing_card_map) == 0) and callable(fetch_playlists_sync):
                try:
                    await asyncio.to_thread(lambda: fetch_playlists_sync(None))
                except Exception:
                    pass
                sel = getattr(existing_card_dropdown, 'value', None)
                card_id = existing_card_map.get(sel)
            if not card_id:
                status.value = 'No target card selected for append'
                show_snack(status.value, error=True)
                page.update()
                return

        # Schedule uploads using shared scheduler
        transcoded_results = await schedule_uploads(files, filename_list, show_progress=False)

        async def append_all_after_uploads(tasks_to_wait):
            print("[start_uploads] Waiting for all uploads to complete before appending")

            # If playlists haven't been fetched yet (map empty), try to fetch synchronously
            if (not existing_card_map or len(existing_card_map) == 0) and callable(fetch_playlists_sync):
                print("[start_uploads] existing_card_map empty, calling fetch_playlists_sync to populate")
                try:
                    # fetch_playlists_sync may be blocking; run in a thread to avoid blocking this async loop
                    await asyncio.to_thread(lambda: fetch_playlists_sync(None))
                except Exception as fe:
                    print(f"[start_uploads] fetch_playlists_sync failed: {fe}")

            sel = getattr(existing_card_dropdown, 'value', None)
            card_id = existing_card_map.get(sel)
            print(f"[start_uploads] Selected existing card: {sel} -> {card_id}")
            if not card_id:
                status.value = 'No target card selected'
                page.update()
                return

            status.value = 'Appending chapters to card...'
            page.update()
            # Card info display hook
            show_card_info = ctx.get('show_card_info')

            def do_append():
                try:
                    print(f"[start_uploads] Fetching card for batch append: {card_id}")
                    card = api.get_card(card_id)


                    upload_mode_dropdown = ctx.get('upload_mode_dropdown')
                    single_chapter = False
                    if upload_mode_dropdown:
                        mode_value = getattr(upload_mode_dropdown, 'value', 'Chapters')
                        single_chapter = (mode_value == 'Tracks')

                    if not getattr(card, 'content', None):
                        card.content = type(card.content)()
                    if not getattr(card.content, 'chapters', None):
                        card.content.chapters = []

                    if single_chapter and len(transcoded_results) > 1:
                        # Build a single chapter containing all tracks and append
                        chapters_to_add = build_chapters_from_transcodes(
                            transcoded_results=transcoded_results,
                            filename_list=filename_list,
                            title_for_single_chapter=f"Chapter {len(card.content.chapters) + 1}",
                            api=api,
                            single_chapter=True,
                            existing_chapters=len(card.content.chapters)
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
                            existing_chapters=len(card.content.chapters)
                        )
                        for ch in chapters_to_add:
                            card.content.chapters.append(ch)

                    # If there is an existing note, append to it
                    if gain_note_lines:
                        prev_note = getattr(card.metadata, 'note', '') if card.metadata else ''
                        if prev_note and not prev_note.endswith('\n'):
                            prev_note += '\n'
                        # Ensure note is always a string
                        note_val = (prev_note or '') + '\n'.join(gain_note_lines)
                        if card.metadata:
                            card.metadata.note = str(note_val)
                        else:
                            card.metadata = CardMetadata(note=str(note_val))

                    created = api.create_or_update_content(card, return_card=True)
                    status.value = 'Chapters appended'
                    show_card_info(created)
                    return True, None
                except Exception as ex:
                    print(f"[start_uploads] Batch append error: {ex}")
                    return False, ex

            ok, err = await asyncio.to_thread(do_append)
            if not ok:
                status.value = f'Append failed: {err}'
                show_snack(status.value, error=True)
                for idx, r in enumerate(file_rows_column.controls):
                    fileuploadrow = getattr(r, '_fileuploadrow', None)
                    if fileuploadrow is None:
                        raise RuntimeError(f"Row is missing _fileuploadrow reference: {type(r)}")
                    if transcoded_results[idx]:
                        fileuploadrow.set_status('Transcoded (not appended)')
                    else:
                        if fileuploadrow.status_text.value != 'Error':
                            fileuploadrow.set_status('Error')
                page.update()
            else:
                status.value = 'All chapters appended'
                show_snack(status.value)
                for r in file_rows_column.controls:
                    fileuploadrow = getattr(r, '_fileuploadrow', None)
                    if fileuploadrow is None:
                        raise RuntimeError(f"Row is missing _fileuploadrow reference: {type(r)}")
                    fileuploadrow.set_status('Done (appended)')
                    fileuploadrow.on_upload_complete()
                page.update()

        # append_all_after_uploads does not need the original upload_tasks variable
        # (results are already awaited); pass an empty list to avoid referencing
        # the undefined local `upload_tasks` variable which caused UnboundLocalError.
        append_task = asyncio.create_task(append_all_after_uploads([]))
        tasks = [append_task]

    status.value = "Uploading..."
    try:
        ctx.get('start_btn').disabled = True
        ctx.get('stop_btn').disabled = False
    except Exception:
        pass
    logger.debug("[start_uploads] Upload tasks started")
    # Make per-file progress bars visible now that uploads have started
    try:
        for r in file_rows_column.controls:
            fileuploadrow = getattr(r, '_fileuploadrow', None)
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
            ctx.get('start_btn').disabled = False
            ctx.get('stop_btn').disabled = True
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

async def stop_uploads(event, ctx):
    status = ctx.get('status')
    page = ctx.get('page')
    if status:
        status.value = "Stopping... (will finish active uploads)"
    if page:
        page.update()
    # No aggressive cancel implemented here; could be added
