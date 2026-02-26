import os
import platform
import sys
import subprocess
from pathlib import Path
import flet as ft
from loguru import logger

from yoto_up.paths import (
    FLET_APP_STORAGE_DATA,
    TOKENS_FILE,
    _BASE_DATA_DIR,
    _BASE_CONFIG_DIR,
)
from yoto_up.yoto_app.ui_state import get_state_path
import yoto_up.paths as paths_mod
from yoto_up.yoto_app.api_manager import ensure_api


def show_about_dialog(page, api_ref, show_snack, clear_all_user_data_gui):
    """Show the About dialog. Parameters are provided by the caller (gui)."""
    version = "dev"
    try:
        import importlib.metadata as _md

        try:
            version = _md.version("yoto-up")
        except Exception:
            version = _md.version("yoto_up") if hasattr(_md, "version") else version
    except Exception:
        pass

    try:
        tokens_path = Path(TOKENS_FILE) if TOKENS_FILE is not None else None
        ui_state_path = get_state_path() if get_state_path() is not None else None
        tokens_exist = tokens_path.exists() if tokens_path is not None else False
        ui_exist = ui_state_path.exists() if ui_state_path is not None else False
    except Exception:
        tokens_path = None
        ui_state_path = None
        tokens_exist = False
        ui_exist = False

    try:
        api_instance = api_ref.get("api") if isinstance(api_ref, dict) else None
        if not api_instance:
            try:
                api_instance = ensure_api(api_ref)
            except Exception:
                api_instance = None

        if api_instance:
            try:
                off_cache = getattr(api_instance, "OFFICIAL_ICON_CACHE_DIR", None)
            except Exception:
                off_cache = None
            try:
                yotoicons_cache = getattr(api_instance, "YOTOICONS_CACHE_DIR", None)
            except Exception:
                yotoicons_cache = None
            try:
                upload_icon_cache = getattr(
                    api_instance, "UPLOAD_ICON_CACHE_FILE", None
                )
            except Exception:
                upload_icon_cache = None
            try:
                api_cache = getattr(api_instance, "CACHE_FILE", None)
            except Exception:
                api_cache = None
        else:
            off_cache = getattr(paths_mod, "OFFICIAL_ICON_CACHE_DIR", None)
            yotoicons_cache = getattr(paths_mod, "YOTOICONS_CACHE_DIR", None)
            upload_icon_cache = getattr(paths_mod, "UPLOAD_ICON_CACHE_FILE", None)
            api_cache = getattr(paths_mod, "API_CACHE_FILE", None)

        try:
            off_cache_exists = (
                Path(off_cache).exists() if off_cache is not None else False
            )
        except Exception:
            off_cache_exists = False
        try:
            yotoicons_cache_exists = (
                Path(yotoicons_cache).exists() if yotoicons_cache is not None else False
            )
        except Exception:
            yotoicons_cache_exists = False
    except Exception:
        off_cache = None
        yotoicons_cache = None
        upload_icon_cache = None
        api_cache = None
        off_cache_exists = False
        yotoicons_cache_exists = False

    flet_storage = (
        FLET_APP_STORAGE_DATA or os.getenv("FLET_APP_STORAGE_DATA") or "(not set)"
    )

    def open_path(path_obj, notify_fn=None):
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
            if sys.platform.startswith("darwin"):
                subprocess.Popen(["open", p])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", p])
            else:
                try:
                    subprocess.Popen(["xdg-open", p])
                except Exception:
                    subprocess.Popen(["xdg-open", os.path.dirname(p) or p])
            if notify_fn:
                notify_fn(f"Opened {p}")
        except Exception as ex:
            if notify_fn:
                notify_fn(f"Failed to open {path_obj}: {ex}", error=True)
            else:
                logger.exception(f"Failed to open path {path_obj}: {ex}")

    content_items = [
        ft.Row(
            controls=[ft.Image(src="art.jpeg", width=120, height=120)],
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        ft.Text(value="Yoto Up", size=20, weight=ft.FontWeight.BOLD),
        ft.Text(value=f"Version: {version}"),
        ft.Text(value=f"Python: {platform.python_version()} ({platform.machine()})"),
        ft.Text(value=f"Flet: {getattr(ft, '__version__', '(unknown)')}"),
        ft.Text(value=f"Platform: {platform.platform()}"),
        ft.Divider(),
        ft.Text(value="Config:", weight=ft.FontWeight.BOLD),
        ft.Text(
            value=f"Flet storage (FLET_APP_STORAGE_DATA): {flet_storage}",
            selectable=True,
            size=12,
        ),
        ft.Text(
            value=f"Tokens file: {str(tokens_path) if tokens_path is not None else '(unknown)'} {'(exists)' if tokens_exist else '(missing)'}",
            selectable=True,
            size=12,
        ),
        ft.Text(
            value=f"UI state file: {str(ui_state_path) if ui_state_path is not None else '(unknown)'} {'(exists)' if ui_exist else '(missing)'}",
            selectable=True,
            size=12,
        ),
        ft.Row(
            controls=[
                ft.TextButton(
                    content="Open config dir",
                    on_click=lambda e, p=_BASE_CONFIG_DIR: open_path(p, show_snack),
                    style=ft.ButtonStyle(color=ft.Colors.BLUE),
                ),
            ]
        ),
        ft.Divider(),
        ft.Text(value="Data locations:", weight=ft.FontWeight.BOLD),
        ft.Text(
            value=f"Official icon cache: {str(off_cache) if off_cache is not None else '(unknown)'} {'(exists)' if off_cache_exists else '(missing)'}",
            selectable=True,
            size=12,
        ),
        ft.Text(
            value=f"YotoIcons cache: {str(yotoicons_cache) if yotoicons_cache is not None else '(unknown)'} {'(exists)' if yotoicons_cache_exists else '(missing)'}",
            selectable=True,
            size=12,
        ),
        ft.Text(
            value=f"Upload icon cache file: {str(upload_icon_cache) if upload_icon_cache is not None else '(unknown)'}",
            selectable=True,
            size=12,
        ),
        ft.Text(
            value=f"API cache file: {str(api_cache) if api_cache is not None else '(unknown)'}",
            selectable=True,
            size=12,
        ),
        ft.Row(
            controls=[
                ft.TextButton(
                    content="Open data/cache dir",
                    on_click=lambda e, p=_BASE_DATA_DIR: open_path(p, show_snack),
                    style=ft.ButtonStyle(color=ft.Colors.BLUE),
                ),
            ]
        ),
        ft.Divider(),
        ft.Text(value="About:", weight=ft.FontWeight.BOLD),
        ft.Text(value="A desktop tool for managing Yoto cards and playlists."),
        ft.Text(value="Author: xkjq"),
        ft.TextButton(
            content="GitHub Repository",
            url="https://github.com/xkjq/yoto-up",
            style=ft.ButtonStyle(color=ft.Colors.BLUE),
        ),
        ft.Text(value="\nYoto Up is not affiliated with Yoto Ltd.\n"),
        ft.Text(value="License: see LICENSE file in the project root."),
        ft.Row(
            controls=[
                ft.TextButton(
                    content="Clear All User Data",
                    on_click=lambda e: clear_all_user_data_gui(e),
                    style=ft.ButtonStyle(color=ft.Colors.RED),
                )
            ]
        ),
    ]

    dlg = ft.AlertDialog(
        title=ft.Text(value="About Yoto Up"),
        content=ft.Column(controls=content_items, scroll=ft.ScrollMode.AUTO, width=520),
        actions=[ft.TextButton(content="Close", on_click=lambda e: page.pop_dialog())],
    )
    page.show_dialog(dlg)
    page.update()
