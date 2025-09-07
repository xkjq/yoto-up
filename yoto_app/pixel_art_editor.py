

import flet as ft
import sys
import os
if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

class PixelArtEditor:
    def __init__(self, size=16, pixel_size=24):
        self.size = size
        self.pixel_size = pixel_size
        self.current_color = '#000000'
        self.colors = [
            '#000000', '#FFFFFF', '#FF0000', '#00FF00', '#0000FF',
            '#FFFF00', '#FF00FF', '#00FFFF', '#888888', '#FFA500',
            '#800080', '#008000', '#808000', '#008080', '#C0C0C0', '#A52A2A'
        ]
        self.pixels = [["#FFFFFF" for _ in range(size)] for _ in range(size)]
        self.grid = None
        self.color_dropdown = None
        self.clear_btn = None
        self.export_btn = None
        self.import_btn = None
        self.export_text = None
        self.container = None
        self._build()

    def _build(self):
        self.color_field = ft.TextField(
            label="Color (hex)",
            width=120,
            value=self.current_color,
            on_change=self.on_color_change
        )
        self.color_preview = ft.Container(
            width=32,
            height=32,
            bgcolor=self.current_color,
            border_radius=4,
            border=ft.border.all(1, "#888888"),
        )
        self.palette_colors = [
            '#000000', '#FFFFFF', '#FF0000', '#00FF00', '#0000FF',
            '#FFFF00', '#FF00FF', '#00FFFF', '#888888', '#FFA500',
            '#800080', '#008000', '#808000', '#008080', '#C0C0C0', '#A52A2A',
            '#FFD700', '#B22222', '#228B22', '#4169E1', '#FF69B4', '#00CED1', '#F5DEB3', '#2F4F4F'
        ]
        self.palette = ft.Row([
            ft.Container(
                width=24,
                height=24,
                bgcolor=c,
                border_radius=4,
                border=ft.border.all(1, "#888888"),
                on_click=self.make_palette_click_handler(c),
                tooltip=c
            ) for c in self.palette_colors
        ], spacing=4)
        self.clear_btn = ft.ElevatedButton("Clear", on_click=self.on_clear)
        self.export_btn = ft.ElevatedButton("Export", on_click=self.on_export)
        self.import_btn = ft.ElevatedButton("Import", on_click=self.on_import)
        self.import_icon_btn = ft.ElevatedButton("Import Icon from Cache", on_click=self.on_import_icon)
        self.export_text = ft.TextField(label="Export/Import JSON", multiline=True, width=400, height=80)
        self.grid = ft.Column([
            ft.Row([
                self.make_pixel(x, y) for x in range(self.size)
            ], spacing=0) for y in range(self.size)
        ], spacing=0)
        grid_width = self.size * self.pixel_size
        grid_height = self.size * self.pixel_size
        self.grid_container = ft.Container(
            content=self.grid,
            border_radius=4,
            border=ft.border.all(2, "#888888"),
            padding=2,
            width=grid_width,
            height=grid_height,
        )
        self.container = ft.Column([
            ft.Row([
                self.color_field,
                self.color_preview,
                self.clear_btn,
                self.export_btn,
                self.import_btn,
                self.import_icon_btn
            ]),
            self.palette,
            self.export_text,
            ft.Divider(),
            self.grid_container
        ])
    def on_import_icon(self, e):
        import os
        from yoto_app.icon_import_helpers import list_icon_cache_files, load_icon_as_pixels
        print("Importing icon from cache...")
        icon_files = list_icon_cache_files()
        print(f"Found icon files: {icon_files}")
        page = e.page if hasattr(e, 'page') else None
        if not icon_files:
            dlg = ft.AlertDialog(title=ft.Text("No icons found in .yoto_icon_cache"), actions=[ft.TextButton("OK", on_click=lambda ev: self._close_dialog(dlg, page))])
            if page:
                page.dialog = dlg
                dlg.open = True
                page.update()
            return
        dropdown = ft.Dropdown(label="Icon file", options=[ft.dropdown.Option(f) for f in icon_files], width=320)
        preview = ft.Image(width=64, height=64)
        status = ft.Text("")
        def on_select(ev):
            fname = dropdown.value
            if fname:
                preview.src = os.path.join(".yoto_icon_cache", fname)
                preview.update()
        dropdown.on_change = on_select
        def do_import(ev):
            fname = dropdown.value
            if not fname:
                status.value = "Select an icon file."
                status.update()
                return
            try:
                pixels = load_icon_as_pixels(os.path.join(".yoto_icon_cache", fname), size=self.size)
                self.pixels = pixels
                self.refresh_grid()
                dlg.open = False
                if page:
                    page.update()
            except Exception as ex:
                status.value = f"Failed to load: {ex}"
                status.update()
        dlg = ft.AlertDialog(
            title=ft.Text("Import Icon from Cache"),
            content=ft.Column([
                dropdown,
                preview,
                status
            ], width=350),
            actions=[
                ft.TextButton("Import", on_click=do_import),
                ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))
            ]
        )
        if page:
            page.open(dlg)
            page.update()

    def _close_dialog(self, dlg, page=None):
        dlg.open = False
        if page:
            page.update()

    def make_pixel(self, x, y):
        def on_click(e):
            self.pixels[y][x] = self.current_color
            e.control.bgcolor = self.current_color
            e.control.update()
        return ft.Container(
            width=self.pixel_size,
            height=self.pixel_size,
            bgcolor=self.pixels[y][x],
            on_click=on_click
        )

    def on_color_change(self, e):
        val = e.control.value.strip()
        if val.startswith('#') and (len(val) == 7 or len(val) == 4):
            self.current_color = val
            self.color_preview.bgcolor = val
            self.color_preview.update()
            self.color_picker.value = val
            self.color_picker.update()

    def make_palette_click_handler(self, color):
        def handler(e):
            self.current_color = color
            self.color_field.value = color
            self.color_field.update()
            self.color_preview.bgcolor = color
            self.color_preview.update()
        return handler

    def on_clear(self, e):
        self.pixels = [["#FFFFFF" for _ in range(self.size)] for _ in range(self.size)]
        self.refresh_grid()

    def on_export(self, e):
        import json
        self.export_text.value = json.dumps(self.pixels)
        self.export_text.update()

    def on_import(self, e):
        import json
        try:
            data = json.loads(self.export_text.value)
            if isinstance(data, list) and len(data) == self.size and all(len(row) == self.size for row in data):
                self.pixels = data
                self.refresh_grid()
        except Exception:
            self.export_text.value = "Invalid JSON!"
            self.export_text.update()

    def refresh_grid(self):
        for y, row in enumerate(self.grid.controls):
            for x, cell in enumerate(row.controls):
                cell.bgcolor = self.pixels[y][x]
                cell.update()

    def control(self):
        return self.container

# Standalone demo
if __name__ == "__main__":
    def main(page: ft.Page):
        page.title = "Pixel Art Editor"
        editor = PixelArtEditor()
        page.add(editor.control())
    ft.app(target=main)
