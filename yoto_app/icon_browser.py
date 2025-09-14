import os
import threading
from typing import Callable

import flet as ft

from .icon_import_helpers import list_icon_cache_files


def build_icon_browser_panel(page: ft.Page, api_ref: dict, ensure_api: Callable, show_snack: Callable):
    """Return a dict with 'panel' key containing a Flet Column for the icon browser.

    Features:
    - shows icons from .yoto_icon_cache and .yotoicons_cache
    - search box to filter cached icons
    - 'Search YotoIcons' button to trigger online search (uses ensure_api/api_ref)
    """
    panel = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True)

    search_row = ft.Row([], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    search_field = ft.TextField(label="Search cached icons", width=400)
    search_btn = ft.TextButton("Filter", on_click=lambda e: do_filter())
    online_search_btn = ft.ElevatedButton("Search YotoIcons online", on_click=lambda e: do_online_search())
    search_row.controls.extend([search_field, search_btn, online_search_btn])

    icons_container = ft.GridView(expand=True, max_extent=80, child_aspect_ratio=1)

    def load_cached_icons():
        icons = []
        # official Yoto cached icons
        try:
            for f in list_icon_cache_files(cache_dir=".yoto_icon_cache"):
                icons.append(os.path.join(".yoto_icon_cache", f))
        except Exception:
            pass
        # yotoicons cache
        try:
            for f in list_icon_cache_files(cache_dir=".yotoicons_cache"):
                icons.append(os.path.join(".yotoicons_cache", f))
        except Exception:
            pass
        return icons

    def render_icons(icons):
        icons_container.controls.clear()
        for path in icons:
            try:
                img = ft.Image(src=path, width=64, height=64)
                btn = ft.Container(content=img, border_radius=6, padding=4, ink=True)
                def on_click(e, p=path):
                    show_snack(f"Selected icon: {p}")
                btn.on_click = on_click
                icons_container.controls.append(btn)
            except Exception:
                continue
        page.update()

    def do_filter():
        q = (search_field.value or "").strip().lower()
        icons = load_cached_icons()
        if q:
            icons = [p for p in icons if q in os.path.basename(p).lower()]
        render_icons(icons)

    def do_online_search():
        # Run online search in a background thread to keep UI responsive
        def _worker():
            try:
                api = ensure_api(api_ref)
                if not api:
                    show_snack("API not available; authenticate first", error=True)
                    return
                # use api.search_yotoicons to refresh cache and then list cached results
                api.search_yotoicons(search_field.value or "", show_in_console=False)
                icons = load_cached_icons()
                # render and notify (best-effort from background thread)
                try:
                    render_icons(icons)
                except Exception:
                    pass
                show_snack("YotoIcons search complete")
            except Exception:
                show_snack("YotoIcons search failed", True)

        threading.Thread(target=_worker, daemon=True).start()

    # initial render
    panel.controls.append(ft.Row([ft.Text("Icon Browser", size=20, weight=ft.FontWeight.BOLD)]))
    panel.controls.append(search_row)
    panel.controls.append(ft.Divider())
    panel.controls.append(icons_container)

    # do initial load
    render_icons(load_cached_icons())

    return {"panel": panel}
