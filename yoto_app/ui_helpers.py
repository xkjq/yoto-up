import flet as ft
from pathlib import Path
from loguru import logger


def append_debug(page, debug_list: ft.ListView, msg: str):
    try:
        ts = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{ts}] {msg}"
        print(line)
        debug_list.controls.append(ft.Text(line))
        if len(debug_list.controls) > 200:
            debug_list.controls.pop(0)
        page.update()
    except Exception:
        try:
            logger.error("append_debug: failed to append debug message")
        except Exception:
            try:
                print('[debug]', msg)
            except Exception:
                pass


def show_snack(page, message: str, error: bool = False):
    try:
        sb = ft.SnackBar(ft.Text(message), bgcolor=ft.Colors.RED if error else ft.Colors.GREEN)
        page.snack_bar = sb
        page.open(sb)
    except Exception:
        try:
            logger.error("show_snack: failed to show snackbar")
        except Exception:
            try:
                # best-effort fallback: update a status control if present on the page
                if hasattr(page, 'status'):
                    try:
                        page.status.value = message
                        page.update()
                    except Exception:
                        pass
            except Exception:
                pass


def populate_file_rows(page, file_rows_column: ft.Column, folder_path: str, utils_module=None):
    try:
        utils = utils_module or __import__('yoto_app.utils', fromlist=['find_audio_files'])
        fp = (folder_path or '').strip()
        if not fp:
            return
        files = utils.find_audio_files(fp)
        file_rows_column.controls.clear()
        if not files:
            file_rows_column.controls.append(ft.Text(f"No audio files found in {fp}"))
        else:
            for f in files:
                try:
                    from yoto_app.upload_tasks import ft_row_for_file
                    r = ft_row_for_file(f, page, file_rows_column)
                    if r is None:
                        raise Exception('ft_row_for_file returned None')
                except Exception:
                    p = ft.ProgressBar(width=300, visible=False)
                    r = ft.Row(controls=[ft.Text(Path(f).name, width=300), p, ft.Text("Queued")])
                file_rows_column.controls.append(r)
        page.update()
    except Exception as e:
        try:
            logger.error(f"populate_file_rows error: {e}")
        except Exception:
            try:
                print(f"[populate_file_rows] error: {e}")
            except Exception:
                pass


def enable_authenticated_tabs(page):
    try:
        for ctl in page.controls:
            try:
                if isinstance(ctl, ft.Tabs):
                    try:
                        ctl.tabs[1].disabled = False
                        ctl.tabs[2].disabled = False
                    except Exception:
                        pass
                    page.update()
                    return
            except Exception:
                continue
    except Exception:
        try:
            logger.error("enable_authenticated_tabs: unexpected error")
        except Exception:
            pass
