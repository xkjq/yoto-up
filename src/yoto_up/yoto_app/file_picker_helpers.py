import sys
import shutil
from typing import Optional, List
from loguru import logger

import flet as ft


def _file_picker_supported(page) -> bool:
    _is_linux_desktop = sys.platform.startswith("linux") and not getattr(page, "web", False)
    try:
        _zenity_missing = _is_linux_desktop and shutil.which("zenity") is None
    except Exception:
        _zenity_missing = False
    return not _zenity_missing


def get_or_create_picker(page) -> Optional[ft.FilePicker]:
    # Prefer an existing picker attached to the page
    picker = getattr(page, "file_picker", None)
    if picker is not None:
        return picker
    if not _file_picker_supported(page):
        return None
    try:
        picker = ft.FilePicker()
        # Register as a page service so Flet can show dialogs
        page.services.append(picker)
        page.file_picker = picker
        return picker
    except Exception:
        return None


async def pick_directory(page) -> Optional[str]:
    """Open a native folder picker and return the selected path or None.

    Returns None if file pickers are unsupported or the user cancelled.
    """
    picker = getattr(page, "download_folder_picker", None) or getattr(page, "file_picker", None)
    if picker is None:
        picker = get_or_create_picker(page)
    if picker is None:
        return None
    try:
        return await picker.get_directory_path()
    except Exception:
        return None


async def pick_files(page, allow_multiple: bool = True) -> Optional[List[ft.FilePickerFile]]:
    logger.debug(f"Attempting to pick files with allow_multiple={allow_multiple}")
    picker = getattr(page, "file_picker_files", None) or getattr(page, "file_picker", None)
    if picker is None:
        picker = get_or_create_picker(page)
    if picker is None:
        return None
    try:
        return await picker.pick_files(allow_multiple=allow_multiple)
    except Exception:
        return None
