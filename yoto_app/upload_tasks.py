import asyncio
import os
import traceback
from models import Chapter, ChapterDisplay, Card, CardContent
from yoto_api import YotoAPI
from yoto_app.logging_helpers import safe_log
from flet import Row, Text, ProgressBar, ElevatedButton, AlertDialog, Column
import re
from loguru import logger

# module-level reference to the last active page so row buttons can open dialogs
_LAST_PAGE = None

@logger.catch
async def start_uploads(event, ctx):
    """Start uploads migrated from gui; ctx is the UI/context dict.

    Expected ctx keys: page, folder, utils_mod, ensure_api, api_ref, concurrency,
    file_rows_column, overall_bar, overall_text, status, show_snack, update_overall,
    upload_target_dropdown, new_card_title, existing_card_dropdown, existing_card_map,
    start_btn, stop_btn
    """
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


    # Gather all unique files from file_rows_column (from folder and individual selection)
    files = []
    seen = set()
    for row in getattr(file_rows_column, 'controls', []):
        path = getattr(row, 'filename', None)
        if path and path not in seen:
            files.append(path)
            seen.add(path)
    logger.debug(f"[start_uploads] Files to upload (from UI): {files}")
    if not files:
        status.value = "No files selected for upload."
        show_snack(status.value)
        print("[start_uploads] No files selected for upload.")
        page.update()
        return

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

    # Reset UI columns
    file_rows_column.controls.clear()
    page.update()

    total_files = len(files)
    overall_bar.value = 0
    overall_text.value = f"0/{total_files} completed"
    try:
        overall_bar.visible = True
        overall_text.visible = True
    except Exception as e:
        safe_log("start_uploads: failed to set overall bar visibility", e)
    logger.debug(f"[start_uploads] Total files to upload: {total_files}")

    # Create rows
    for f in files:
        logger.debug(f"[start_uploads] Creating UI row for file: {f}")
        r = ft_row_for_file(f, maybe_page=page, maybe_column=file_rows_column)
        if r:
            file_rows_column.controls.append(r)
    page.update()
    try:
        logger.debug('[start_uploads] Rows after creation:')
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
    except Exception:
        pass

    # Launch workers (branch by upload target)
    tasks = []
    target = getattr(upload_target_dropdown, 'value', 'Create new card')
    if target == 'Create new card':
        title = (getattr(new_card_title, 'value', '') or '').strip() or 'New Yoto Card'
        filename_list = [clean_title_from_filename(f, strip_leading) for f in files]
        transcoded_results = [None] * len(files)
        upload_tasks = []
        def make_progress_cb(idx):
            def progress_cb(msg, frac):
                try:
                    logger.debug(f"[progress_cb] idx={idx}, msg={msg}, frac={frac}")
                    row = file_rows_column.controls[idx]
                    # Only show status message, not fractional progress
                    if msg:
                        row.controls[2].value = msg
                    else:
                        row.controls[2].value = ''
                    row.controls[1].visible = True
                    page.update()
                except Exception as e:
                    logger.error(f"[progress_cb] Exception for idx={idx}: {e}")
            return progress_cb

        for idx, (f, fname) in enumerate(zip(files, filename_list)):
            def make_upload_task(idx, f, fname):
                async def upload_new_card_one():
                    already_updated = False
                    try:
                        tr = await api.upload_and_transcode_audio_async(
                            audio_path=f,
                            filename=fname,
                            loudnorm=normalize_audio,
                            show_progress=True,
                            progress=None,
                            upload_task_id=None,
                            transcode_task_id=None,
                            poll_interval=2,
                            max_attempts=60,
                            progress_callback=make_progress_cb(idx),
                        )
                        # If tr is None, treat as skipped (file exists)
                        if tr is not None:
                            transcoded_results[idx] = tr
                            row = file_rows_column.controls[idx]
                            row.controls[1].value = 1.0
                            row.controls[2].value = 'Done (100%)'
                            already_updated = True
                        else:
                            # Defensive: treat skipped as success, set UI
                            transcoded_results[idx] = True
                            row = file_rows_column.controls[idx]
                            row.controls[1].value = 1.0
                            row.controls[2].value = 'Skipped (already exists)'
                            already_updated = True
                    except Exception as e:
                        row = file_rows_column.controls[idx]
                        row.controls[2].value = f'Error: {e}'
                        already_updated = True
                    finally:
                        if already_updated:
                            update_overall()
                            page.update()
                async def sem_runner_new_card():
                    async with sem:
                        await upload_new_card_one()
                return sem_runner_new_card

            upload_tasks.append(asyncio.create_task(make_upload_task(idx, f, fname)()))

        await asyncio.gather(*upload_tasks)

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

            if single_chapter and len(transcoded_results) > 1:
                tracks = []
                for i, tr in enumerate(transcoded_results):
                    td = {'title': filename_list[i]}
                    track = api.get_track_from_transcoded_audio(tr, track_details=td)
                    try:
                        track.key = f"{i+1:02}"
                    except Exception:
                        pass
                    tracks.append(track)
                chapter = Chapter(
                    key="01",
                    title=title,
                    overlayLabel="1",
                    tracks=tracks,
                    display=ChapterDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
                )
                chapters = [chapter]
            else:
                chapters = []
                for i, tr in enumerate(transcoded_results):
                    cd = {'title': filename_list[i]}
                    ch = api.get_chapter_from_transcoded_audio(tr, chapter_details=cd)
                    try:
                        ch.key = f"{i+1:02}"
                        if hasattr(ch, 'tracks') and ch.tracks:
                            for j, t in enumerate(ch.tracks):
                                t.key = f"{j+1:02}"
                    except Exception:
                        pass
                    chapters.append(ch)
            card = Card(
                title=title,
                content=CardContent(chapters=chapters),
            )
            created = api.create_or_update_content(card)
            cid = None
            try:
                if hasattr(created, 'cardId'):
                    cid = getattr(created, 'cardId')
                elif hasattr(created, 'id'):
                    cid = getattr(created, 'id')
                elif isinstance(created, dict):
                    cid = created.get('cardId') or created.get('id')
            except Exception:
                pass
            status.value = f'Created card: {cid}' if cid else 'Card created'
            show_snack(status.value)
            fetch_playlists_sync(None)
        except Exception as e:
            logger.error(f"start_uploads: create card error: {e}")
            traceback.print_exc()
        finally:
            page.update()
    else:
        # Add to existing card
        transcoded_results = [None] * len(files)
        filename_list = [clean_title_from_filename(f, strip_leading) for f in files]

        async def upload_one(idx, fpath):
            already_updated = False
            try:
                row_widget = file_rows_column.controls[idx]
                try:
                    row_widget.controls[1].visible = True
                    # set initial upload progress to 0%
                    try:
                        row_widget.controls[1].value = 0.0
                    except Exception:
                        pass
                    try:
                        row_widget.controls[2].value = 'Uploading 0%'
                    except Exception:
                        pass
                except Exception:
                    pass
                page.update()

                tr = await api.upload_and_transcode_audio_async(
                    audio_path=fpath,
                    filename=os.path.basename(fpath),
                    loudnorm=normalize_audio,
                    show_progress=False,
                )
                transcoded_results[idx] = tr

                try:
                    # set transcode completion to ~70%
                    try:
                        row_widget.controls[1].visible = True
                    except Exception:
                        pass
                    try:
                        row_widget.controls[1].value = 0.7
                    except Exception:
                        pass
                    try:
                        row_widget.controls[2].value = 'Transcoded 70%'
                    except Exception:
                        pass
                except Exception:
                    pass
                already_updated = True
            except Exception as e:
                try:
                    row_widget.controls[2].value = "Error"
                    already_updated = True
                    page.update()
                except Exception:
                    pass
                print(f"[start_uploads] Error uploading {fpath}: {e}")
            finally:
                if already_updated:
                    update_overall()
                    page.update()

        upload_tasks = []
        for i, fpath in enumerate(files):
            async def sem_runner(i=i, fpath=fpath):
                async with sem:
                    await upload_one(i, fpath)

            upload_tasks.append(asyncio.create_task(sem_runner()))

        async def append_all_after_uploads(tasks_to_wait):
            print("[start_uploads] Waiting for all uploads to complete before appending")
            try:
                await asyncio.gather(*tasks_to_wait)
            except Exception as e:
                print(f"[start_uploads] Error waiting for uploads: {e}")

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
                        tracks = []
                        for i, tr in enumerate(transcoded_results):
                            # prefer filename for track title when available
                            try:
                                td = {'title': filename_list[i]}
                            except Exception:
                                td = None
                            track = api.get_track_from_transcoded_audio(tr, track_details=td)
                            try:
                                track.key = f"{i+1:02}"
                            except Exception:
                                pass
                            tracks.append(track)

                        chapter = Chapter(
                            title=f"Chapter {len(card.content.chapters) + 1}",
                            key=f"{len(card.content.chapters) + 1}",
                            overlayLabel=f"{len(card.content.chapters) + 1}",
                            tracks=tracks,
                        )
                        card.content.chapters.append(chapter)
                    else:
                        # One chapter per file
                        for i, tr in enumerate(transcoded_results):
                            if not tr:
                                continue
                            try:
                                cd = {'title': filename_list[i]}
                            except Exception:
                                cd = None
                            new_ch = api.get_chapter_from_transcoded_audio(tr, chapter_details=cd)
                            card.content.chapters.append(new_ch)
                    api.create_or_update_content(card)
                    return True, None
                except Exception as ex:
                    print(f"[start_uploads] Batch append error: {ex}")
                    return False, ex

            ok, err = await asyncio.to_thread(do_append)
            if not ok:
                status.value = f'Append failed: {err}'
                show_snack(status.value, error=True)
                for idx, r in enumerate(file_rows_column.controls):
                    try:
                        if transcoded_results[idx]:
                            r.controls[2].value = 'Transcoded (not appended)'
                        else:
                            if r.controls[2].value != 'Error':
                                r.controls[2].value = 'Error'
                    except Exception:
                        pass
                page.update()
            else:
                status.value = 'All chapters appended'
                show_snack(status.value)
                for r in file_rows_column.controls:
                    try:
                        r.controls[2].value = 'Done (appended)'
                        try:
                            r.controls[1].visible = True
                        except Exception:
                            pass
                        r.controls[1].value = 1.0
                    except Exception:
                        pass
                page.update()

        append_task = asyncio.create_task(append_all_after_uploads(upload_tasks))
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
            try:
                r.controls[1].visible = True
            except Exception:
                pass
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


def ft_row_for_file(filepath: str, maybe_page=None, maybe_column=None):
    try:
        name = os.path.basename(filepath)

        def on_view_details(ev=None, path=filepath):
            try:
                page = maybe_page or globals().get('_LAST_PAGE')
                if not page:
                    print('[ft_row_for_file] No page available to show dialog')
                    return

                # Try to import mutagen for robust tag parsing
                tags = {}
                # Try to import mutagen for robust tag parsing
                try:
                    from mutagen import File as MutagenFile
                    mf = MutagenFile(path)
                    if mf is not None:
                        # flatten tags, format nicely
                        tag_items = []
                        for k, v in getattr(mf, 'tags', {}).items():
                            try:
                                # Mutagen tags can be lists or bytes
                                if isinstance(v, (list, tuple)):
                                    val = ", ".join(str(item) for item in v)
                                else:
                                    val = str(v)
                                tag_items.append((str(k), val))
                            except Exception:
                                tag_items.append((str(k), repr(v)))
                        # Sort tags for readability
                        tag_items.sort()
                        for k, v in tag_items:
                            tags[k] = v
                        # Add format/length info if available
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
                    # fallback: minimal ID3v1 read for mp3 (title/artist/album/year/comment/genre)
                    try:
                        if path.lower().endswith('.mp3') and os.path.getsize(path) > 128:
                            with open(path, 'rb') as fh:
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

                # Build content
                lines = []
                if not tags:
                    lines = [Text('No tags found')]
                else:
                    for k, v in tags.items():
                        lines.append(Text(f"{k}: {v}"))

                dlg = AlertDialog(title=Text(f"Media details: {name}"), content=Column(lines), actions=[ElevatedButton('OK', on_click=lambda e: page.close(dlg))])
                page.open(dlg)
                page.update()
            except Exception as e:
                print(f"[on_view_details] error: {e}")

        btn = ElevatedButton('View details', on_click=on_view_details)
        def on_remove(ev=None, row_ref=None):
            try:
                col = maybe_column or globals().get('_LAST_COLUMN')
                if not col:
                    print('[ft_row_for_file] No column available to remove row')
                    return
                # find and remove this row
                try:
                    col.controls.remove(r)
                except Exception:
                    # fallback: find by filename
                    for existing in list(col.controls):
                        if getattr(existing, 'filename', None) == filepath:
                            try:
                                col.controls.remove(existing)
                            except Exception:
                                pass
                try:
                    page = maybe_page or globals().get('_LAST_PAGE')
                    if page:
                        page.update()
                except Exception:
                    pass
            except Exception as e:
                print(f"[on_remove] error: {e}")
        remove_btn = ElevatedButton('Remove', on_click=on_remove)
        pr = ProgressBar(width=300, visible=False)
        r = Row(controls=[Text(name, width=300), pr, Text('Queued'), btn, remove_btn])
        try:
            # attach filename for upstream code that reads it
            setattr(r, 'filename', filepath)
        except Exception:
            pass
        return r
    except Exception:
        return None
