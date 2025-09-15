from pathlib import Path
import flet as ft
import sys
import os
from loguru import logger
from PIL import Image
import json
import copy
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
        # Advanced color picker dialog
        self.advanced_picker_btn = ft.ElevatedButton("Advanced Color Picker", on_click=self.open_color_picker)
        self.color_picker_dialog = None
        self.rgb_sliders = None
        self.hex_input = None
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
        # Add image adjustment sliders
        self.brightness_slider = ft.Slider(min=0.2, max=2.0, value=1.0, divisions=18, label="Brightness", on_change=self.on_adjust_image)
        self.contrast_slider = ft.Slider(min=0.2, max=2.0, value=1.0, divisions=18, label="Contrast", on_change=self.on_adjust_image)
        self.saturation_slider = ft.Slider(min=0.2, max=2.0, value=1.0, divisions=18, label="Saturation", on_change=self.on_adjust_image)
        self._original_pixels = None
        self._palette_backup = None

        # Add color set dropdown
        self.color_sets = {
            "Default": [
                '#000000', '#222222', '#444444', '#666666', '#888888', '#AAAAAA', '#CCCCCC', '#FFFFFF',
                '#FF0000', '#CC3333', '#FF6666', '#FF9999', '#FFCCCC',
                '#00FF00', '#33CC33', '#66FF66', '#99FF99', '#CCFFCC',
                '#0000FF', '#3333CC', '#6666FF', '#9999FF', '#CCCCFF',
                '#FFFF00', '#FFCC00', '#FF9900', '#FF6600', '#FFA500',
                '#FF00FF', '#CC33CC', '#FF66FF', '#FF99FF', '#FFCCFF',
                '#00FFFF', '#33CCCC', '#66FFFF', '#99FFFF', '#CCFFFF',
                '#800080', '#A52A2A', '#008000', '#808000', '#008080', '#C0C0C0', '#FFD700', '#B22222', '#228B22', '#4169E1', '#FF69B4', '#00CED1', '#F5DEB3', '#2F4F4F'
            ],
            "Pastel": [
                '#FFD1DC', '#FFB7B2', '#FFDAC1', '#E2F0CB', '#B5EAD7', '#C7CEEA', '#B0E0E6', '#E0BBE4', '#F3E5AB', '#E6E6FA', '#F5DEB3', '#D8BFD8', '#E0FFFF', '#F0FFF0', '#F5F5DC', '#FFE4E1',
                '#F3C6E2', '#F7CAC9', '#B5B9D6', '#C1F0F6', '#F3E5AB', '#E6E6FA', '#F5DEB3', '#D8BFD8', '#E0FFFF', '#F0FFF0', '#F5F5DC', '#FFE4E1', '#F3C6E2', '#F7CAC9', '#B5B9D6', '#C1F0F6',
                '#F8BBD0', '#FADADD', '#E6CFCF', '#F9E3E3', '#F6E3B4', '#FFFACD', '#FFF5E1', '#FDFD96', '#E0F7FA', '#B2EBF2', '#B2DFDB', '#DCEDC8', '#C8E6C9', '#D1F2EB', '#E0F2F1',
                '#D7BDE2', '#A9DFBF', '#F9E79F', '#F7DC6F', '#F5CBA7', '#FAD7A0', '#FDEBD0', '#F6DDCC', '#F9E79F', '#F7DC6F', '#F5CBA7', '#FAD7A0', '#FDEBD0', '#F6DDCC',
                '#E3E4FA', '#D6CADD', '#C3B1E1', '#B39EB5', '#B2A1C7', '#C1B2D7', '#D1CFE2', '#E2D6F7', '#E6E6FA', '#E0BBE4', '#D8BFD8', '#F3E5AB', '#F5F5DC', '#F0FFF0', '#E0FFFF', '#FFE4E1'
            ],
            "Vivid": [
                '#FF0000', '#FF4000', '#FF8000', '#FFBF00', '#FFFF00', '#BFFF00', '#80FF00', '#40FF00', '#00FF00',
                '#00FF40', '#00FF80', '#00FFBF', '#00FFFF', '#00BFFF', '#0080FF', '#0040FF', '#0000FF',
                '#4000FF', '#8000FF', '#BF00FF', '#FF00FF', '#FF00BF', '#FF0080', '#FF0040',
                '#FFA500', '#800080', '#008000', '#808000', '#008080', '#C0C0C0', '#A52A2A', '#FFD700', '#B22222', '#228B22', '#4169E1', '#FF69B4', '#00CED1', '#F5DEB3', '#2F4F4F'
            ],
            "Earth Tones": [
                '#3B2F2F', '#8B5C2A', '#A0522D', '#C19A6B', '#BDB76B', '#DEB887', '#F4A460', '#D2B48C', '#EEDC82', '#C2B280', '#8B7D6B', '#6B4226', '#4E3629', '#7C482B', '#A67B5B', '#B2996E', '#C9AE5D', '#8B8000', '#556B2F', '#228B22', '#2E8B57', '#6B8E23', '#8FBC8F', '#BC8F8F', '#CD853F', '#D2691E', '#8B4513', '#A0522D', '#FFF8DC', '#F5DEB3', '#FFE4C4', '#FFDAB9',
                '#6E260E', '#8B4513', '#A0522D', '#D2691E', '#CD853F', '#F4A460', '#DEB887', '#FFE4C4', '#FFF5EE', '#FAEBD7', '#FFEBCD', '#FFEFD5', '#FFDAB9'
            ],
            "Neon": [
                '#39FF14', '#FF073A', '#FDFD96', '#FF6EC7', '#FFB347', '#FF44CC', '#00FFFF', '#FF00FF', '#FFFF00', '#FF3131', '#FFB3DE', '#B3FFB3', '#B3B3FF', '#FFB3B3', '#B3FFFF', '#FFFFB3', '#B3FFEC', '#FFB3EC', '#ECFFB3', '#B3ECFF', '#ECB3FF', '#FFECB3', '#B3FF39', '#39B3FF', '#FF39B3', '#B339FF', '#39FFB3', '#FF3939', '#39FF39', '#3939FF', '#FF39FF', '#39FFFF', '#FFFF39',
                '#FF1493', '#FF4500', '#FF6347', '#FF69B4', '#FF7F50', '#FF8C00', '#FFA07A', '#FFA500', '#FFB6C1', '#FFC0CB', '#FFD700', '#FFE4B5', '#FFE4E1', '#FFEBCD', '#FFEFD5'
            ],
            "Greyscale": [
                '#000000', '#1A1A1A', '#333333', '#4D4D4D', '#666666', '#808080', '#999999', '#B3B3B3', '#CCCCCC', '#E6E6E6', '#FFFFFF'
            ],
            "Retro": [
                '#000000', '#FFFFFF', '#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF', '#00FFFF',
                '#C0C0C0', '#808080', '#800000', '#808000', '#008000', '#800080', '#008080', '#000080',
                '#FFA500', '#A52A2A', '#F5DEB3', '#B22222', '#228B22', '#4169E1', '#FF69B4', '#FFD700', '#B39EB5', '#F49AC2', '#B2EC5D', '#77DD77', '#CB99C9', '#779ECB'
            ],
        }
        self.color_set_dropdown = ft.Dropdown(
            label="Color Set",
            options=[ft.dropdown.Option(k) for k in self.color_sets.keys()],
            value="Default",
            width=160,
            on_change=self.on_color_set_change
        )

        self.container = ft.Column([
            ft.Row([
                self.color_field,
                self.color_preview,
                self.advanced_picker_btn,
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
            ft.Row([
                self.grid_container,
                ft.Column([
                    self.color_set_dropdown,
                    ft.Text("Adjust Whole Picture:"),
                    self.brightness_slider,
                    self.contrast_slider,
                    self.saturation_slider,
                ], spacing=10)
            ], spacing=30),
        ])
    def on_color_set_change(self, e):
        import copy
        set_name = self.color_set_dropdown.value
        palette = self.color_sets.get(set_name, self.palette_colors)
        # If switching to Default, restore backup
        if set_name == "Default" and self._palette_backup is not None:
            self.pixels = copy.deepcopy(self._palette_backup)
            self.refresh_grid()
            return
        # If switching away from Default, store backup
        if set_name != "Default" and self._palette_backup is None:
            self._palette_backup = copy.deepcopy(self.pixels)
        def closest(hex_color):
            h = hex_color.lstrip('#')
            if len(h) == 3:
                h = ''.join([c*2 for c in h])
            r1, g1, b1 = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            def dist(c2):
                h2 = c2.lstrip('#')
                if len(h2) == 3:
                    h2 = ''.join([c*2 for c in h2])
                r2, g2, b2 = int(h2[0:2], 16), int(h2[2:4], 16), int(h2[4:6], 16)
                return (r1-r2)**2 + (g1-g2)**2 + (b1-b2)**2
            return min(palette, key=dist)
        new_pixels = [[closest(c) for c in row] for row in self.pixels]
        self.pixels = new_pixels
        self.refresh_grid()
    def on_adjust_image(self, e):
        b = self.brightness_slider.value
        c = self.contrast_slider.value
        s = self.saturation_slider.value
        # Store original grid before first adjustment
        if self._original_pixels is None:
            self._original_pixels = copy.deepcopy(self.pixels)
        # If all sliders are at 1.0, restore original
        if b == 1.0 and c == 1.0 and s == 1.0:
            if self._original_pixels is not None:
                self.pixels = copy.deepcopy(self._original_pixels)
                self.refresh_grid()
            return
        # Otherwise, apply adjustments to original
        img = self._pixels_to_image(self._original_pixels)
        from PIL import ImageEnhance
        img = ImageEnhance.Brightness(img).enhance(b)
        img = ImageEnhance.Contrast(img).enhance(c)
        img = ImageEnhance.Color(img).enhance(s)
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def open_color_picker(self, e):
        page = e.page if hasattr(e, 'page') else None
        # Parse current color
        def hex_to_rgb(h):
            h = h.lstrip('#')
            if len(h) == 3:
                h = ''.join([c*2 for c in h])
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        def rgb_to_hex(r, g, b):
            return f"#{r:02X}{g:02X}{b:02X}"
        r, g, b = hex_to_rgb(self.current_color)
        # Sliders
        r_slider = ft.Slider(min=0, max=255, value=r, label="R", divisions=255, on_change=None)
        g_slider = ft.Slider(min=0, max=255, value=g, label="G", divisions=255, on_change=None)
        b_slider = ft.Slider(min=0, max=255, value=b, label="B", divisions=255, on_change=None)
        hex_field = ft.TextField(label="Hex", value=self.current_color, width=100)
        preview = ft.Container(width=48, height=48, bgcolor=self.current_color, border_radius=6, border=ft.border.all(1, "#888888"))

        def update_all(ev=None):
            r_val = int(r_slider.value)
            g_val = int(g_slider.value)
            b_val = int(b_slider.value)
            hex_val = rgb_to_hex(r_val, g_val, b_val)
            hex_field.value = hex_val
            preview.bgcolor = hex_val
            hex_field.update()
            preview.update()
            self.current_color = hex_val
            self.color_field.value = hex_val
            self.color_field.update()
            self.color_preview.bgcolor = hex_val
            self.color_preview.update()
            if page:
                page.update()

        def on_slider_change(ev):
            update_all()

        def on_hex_change(ev):
            val = hex_field.value.strip()
            if val.startswith('#') and (len(val) == 7 or len(val) == 4):
                try:
                    r_val, g_val, b_val = hex_to_rgb(val)
                    r_slider.value = r_val
                    g_slider.value = g_val
                    b_slider.value = b_val
                    r_slider.update()
                    g_slider.update()
                    b_slider.update()
                    update_all()
                except Exception:
                    pass

        r_slider.on_change = on_slider_change
        g_slider.on_change = on_slider_change
        b_slider.on_change = on_slider_change
        hex_field.on_change = on_hex_change

        content = ft.Column([
            ft.Row([preview, hex_field]),
            r_slider,
            g_slider,
            b_slider,
        ], spacing=10)
        self.color_picker_dialog = ft.AlertDialog(
            title=ft.Text("Advanced Color Picker"),
            content=content,
            actions=[ft.TextButton("Close", on_click=lambda ev: self._close_dialog(self.color_picker_dialog, page))],
            open=True
        )
        if page:
            page.open(self.color_picker_dialog)
            page.update()

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
