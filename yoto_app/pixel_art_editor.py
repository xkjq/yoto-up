from pathlib import Path
import flet as ft
import sys
import os
from loguru import logger
from PIL import Image
import json
try:
    from yoto_app.icon_import_helpers import list_icon_cache_files, load_icon_as_pixels
except ImportError:
    from icon_import_helpers import list_icon_cache_files, load_icon_as_pixels

if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ICON_DIR = "saved_icons"

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
        # Save / Load created icons
        self.save_btn = ft.ElevatedButton("Save PNG", on_click=self.on_save_png)
        self.load_btn = ft.ElevatedButton("Load PNG", on_click=self.on_load_png)
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
                self.import_icon_btn,
                self.save_btn,
                self.load_btn
            ]),
            self.palette,
            self.export_text,
            ft.Divider(),
            self.grid_container
        ])
    def on_import_icon(self, e):
        print("Importing icon from cache...")
        # look in both caches so users can pick from either
        icon_files = []
        try:
            for f in list_icon_cache_files(cache_dir='.yoto_icon_cache'):
                icon_files.append(os.path.join('.yoto_icon_cache', f))
        except Exception:
            pass
        try:
            for f in list_icon_cache_files(cache_dir='.yotoicons_cache'):
                icon_files.append(os.path.join('.yotoicons_cache', f))
        except Exception:
            pass
        # dedupe while preserving order
        seen = set()
        uniq = []
        for p in icon_files:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        icon_files = uniq
        print(f"Found icon files: {icon_files}")
        page = e.page if hasattr(e, 'page') else None
        if not icon_files:
            dlg = ft.AlertDialog(title=ft.Text("No icons found in .yoto_icon_cache"), actions=[ft.TextButton("OK", on_click=lambda ev: self._close_dialog(dlg, page))])
            if page:
                page.dialog = dlg
                dlg.open = True
                page.update()
            return
        # dropdown values will be full relative paths (e.g. .yoto_icon_cache/abcd.png)
        dropdown = ft.Dropdown(label="Icon file", options=[ft.dropdown.Option(f) for f in icon_files], width=320)
        preview = ft.Image(width=64, height=64)
        status = ft.Text("")
        def on_select(ev):
            sel = dropdown.value
            if not sel:
                return
            try:
                abs_path = os.path.abspath(sel)
                # Flet sometimes needs absolute paths to load local files reliably
                preview.src = abs_path
                preview.update()
                if page:
                    page.update()
            except Exception as ex:
                status.value = f"Preview error: {ex}"
                status.update()
                if page:
                    page.update()
        dropdown.on_change = on_select
        def do_import(ev):
            sel = dropdown.value
            if not sel:
                status.value = "Select an icon file."
                status.update()
                if page:
                    page.update()
                return
            try:
                path = os.path.abspath(sel)
                pixels = load_icon_as_pixels(path, size=self.size)
                if not pixels or not isinstance(pixels, list):
                    raise RuntimeError('Loaded icon returned invalid pixel data')
                self.pixels = pixels
                self.refresh_grid()
                dlg.open = False
                if page:
                    page.update()
            except Exception as ex:
                import traceback
                tb = traceback.format_exc()
                status.value = f"Failed to load: {ex}\n{tb.splitlines()[-1]}"
                status.update()
                if page:
                    page.update()
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

    # Helpers for saving/loading
    def _ensure_saved_dir(self):
        d = Path(ICON_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pixels_to_image(self, pixels):
        size = self.size
        img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
        for y in range(size):
            for x in range(size):
                hexc = pixels[y][x]
                if hexc.startswith('#'):
                    hexc = hexc.lstrip('#')
                    if len(hexc) == 3:
                        hexc = ''.join([c*2 for c in hexc])
                    r = int(hexc[0:2], 16)
                    g = int(hexc[2:4], 16)
                    b = int(hexc[4:6], 16)
                    img.putpixel((x, y), (r, g, b, 255))
        return img

    def _image_to_pixels(self, img):
        # convert a PIL Image (mode RGB/RGBA) to pixels grid, always downsampling to grid size
        img = img.convert('RGBA')
        w, h = img.size
        if w != self.size or h != self.size:
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                if hasattr(Image, 'LANCZOS'):
                    resample = Image.LANCZOS
                elif hasattr(Image, 'Resampling') and hasattr(Image.Resampling, 'BICUBIC'):
                    resample = Image.Resampling.BICUBIC
                else:
                    resample = 3  # 3 is BICUBIC in older PIL
            img = img.resize((self.size, self.size), resample)
        pixels = [["#FFFFFF" for _ in range(self.size)] for _ in range(self.size)]
        for y in range(self.size):
            for x in range(self.size):
                r, g, b, a = img.getpixel((x, y))
                pixels[y][x] = f"#{r:02X}{g:02X}{b:02X}"
        return pixels

    def on_save_png(self, e):
        page = e.page if hasattr(e, 'page') else None
        saved_dir = self._ensure_saved_dir()
        if not saved_dir:
            if page:
                page.snack_bar = ft.SnackBar(ft.Text("Failed to create saved_icons folder"))
                page.snack_bar.open = True
                page.update()
            return

        # simple filename dialog
        name_field = ft.TextField(label="Filename (no extension)")
        status = ft.Text("")

        def do_save(ev):
            fn = (name_field.value or '').strip()
            if not fn:
                status.value = "Enter a filename"
                status.update()
                return
            basename = fn + '.png'
            path = os.path.join(str(saved_dir), basename) if hasattr(saved_dir, 'joinpath') else os.path.join(saved_dir, basename)
            try:
                try:
                    img = self._pixels_to_image(self.pixels)
                    # Save as original 16x16, do not resize
                    img.save(path)
                except Exception:
                    # fallback: save JSON
                    import json
                    with open(path + '.json', 'w', encoding='utf-8') as fh:
                        json.dump(self.pixels, fh)
                if page:
                    status.value = f"Saved: {basename}"
                    status.update()
                    page.update()
            except Exception as ex:
                status.value = f"Save failed: {ex}"
                status.update()

        dlg = ft.AlertDialog(title=ft.Text("Save Icon"), content=ft.Column([name_field, status]), actions=[ft.TextButton("Save", on_click=do_save), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))])
        if page:
            page.open(dlg)
            page.update()

    def on_load_png(self, e):
        page = e.page if hasattr(e, 'page') else None
        saved_dir = self._ensure_saved_dir()
        if not saved_dir:
            if page:
                page.snack_bar = ft.SnackBar(ft.Text("No saved_icons folder"))
                page.snack_bar.open = True
                page.update()
            return
        # list files
        files = []
        try:
            sd = str(saved_dir) if hasattr(saved_dir, 'as_posix') else saved_dir
            for fn in os.listdir(sd):
                if fn.lower().endswith('.png') or fn.lower().endswith('.json'):
                    files.append(fn)
        except Exception:
            logger.exception("Error listing saved icons")
        if not files:
            dlg = ft.AlertDialog(title=ft.Text("No saved icons found"), actions=[ft.TextButton("OK", on_click=lambda ev: self._close_dialog(dlg, page))])
            if page:
                page.open(dlg)
                page.update()
            return

        dropdown = ft.Dropdown(label="Saved file", options=[ft.dropdown.Option(f) for f in files], width=320)
        preview = ft.Image(width=64, height=64)
        status = ft.Text("")

        def on_select(ev):
            v = dropdown.value
            if not v:
                return
            p = os.path.join(sd, v)
            if v.lower().endswith('.png'):
                try:
                    img = Image.open(p)
                    # create a temporary scaled preview
                    img2 = img.resize((64, 64))
                    tmp = os.path.join(sd, '__preview.png')
                    img2.save(tmp)
                    preview.src = tmp
                    preview.update()
                except Exception as ex:
                    logger.exception(f"Error loading image preview: {ex}")
                    preview.src = ''
                    preview.update()
            else:
                preview.src = ''
                preview.update()

        dropdown.on_change = on_select

        def do_load(ev):
            v = dropdown.value
            logger.debug(f"Loading selected icon: {v}")
            if not v:
                status.value = "Select a file"
                status.update()
                return
            p = os.path.join(sd, v)
            logger.debug(f"Full path to load: {p}")
            try:
                if v.lower().endswith('.png'):
                    img = Image.open(p)
                    pixels = self._image_to_pixels(img)
                else:
                    with open(p, 'r', encoding='utf-8') as fh:
                        pixels = json.load(fh)
                if isinstance(pixels, list):
                    logger.debug(f"Loaded pixel data: {pixels}")
                    self.pixels = pixels
                    self.refresh_grid()
                    self._close_dialog(dlg, page)
                else:
                    logger.error("Loaded pixel data is not a list")
            except Exception as ex:
                logger.error(f"Failed to load icon: {ex}")
                status.value = f"Load failed: {ex}"
                status.update()

        dlg = ft.AlertDialog(title=ft.Text("Load Saved Icon"), content=ft.Column([dropdown, preview, status]), actions=[ft.TextButton("Load", on_click=do_load), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))])
        if page:
            page.open(dlg)
            page.update()

    def control(self):
        return self.container

# Standalone demo
if __name__ == "__main__":
    def main(page: ft.Page):
        page.title = "Pixel Art Editor"
        editor = PixelArtEditor()
        page.add(editor.control())
    ft.app(target=main)
