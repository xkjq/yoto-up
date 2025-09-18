from pathlib import Path
import flet as ft
import sys
import os
from loguru import logger
from PIL import Image
import json
import copy
import re
try:
    from yoto_app.icon_import_helpers import list_icon_cache_files, load_icon_as_pixels
except ImportError:
    from icon_import_helpers import list_icon_cache_files, load_icon_as_pixels
import math
import colorsys

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
        #self.export_btn = None
        #self.import_btn = None
        #self.export_text = None
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
        #self.export_btn = ft.ElevatedButton("Export", on_click=self.on_export)
        #self.import_btn = ft.ElevatedButton("Import", on_click=self.on_import)
        self.import_icon_btn = ft.ElevatedButton("Import Icon from Cache", on_click=self.on_import_icon)
        # Save / Load created icons
        self.save_btn = ft.ElevatedButton("Save PNG", on_click=self.on_save_png)
        self.load_btn = ft.ElevatedButton("Load PNG", on_click=self.on_load_png)
        # Text generation (pixel letters/numbers)
        self.text_btn = ft.ElevatedButton("Text", on_click=self._open_text_dialog)
        #self.export_text = ft.TextField(label="Export/Import JSON", multiline=True, width=400, height=80)
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

        # Make the main container scrollable so controls remain accessible on small windows
        # right-side controls column (fixed width so its internal rows can wrap)
        # Put the three adjustment sliders into an expandable block
        image_adjustments_tile = ft.ExpansionTile(
            title=ft.Text("Colour manipulations", size=12, weight=ft.FontWeight.W_400),
            controls=[
                self.color_set_dropdown,
                ft.Row([ft.Text("Brightness", width=120), self.brightness_slider], alignment=ft.MainAxisAlignment.START, spacing=8),
                ft.Row([ft.Text("Contrast", width=120), self.contrast_slider], alignment=ft.MainAxisAlignment.START, spacing=8),
                ft.Row([ft.Text("Saturation", width=120), self.saturation_slider], alignment=ft.MainAxisAlignment.START, spacing=8),
            ],
        )

        self.right_column = ft.Column([
            image_adjustments_tile,
        ], spacing=10, width=600, scroll=ft.ScrollMode.AUTO)

        # main container is scrollable and expands to available space
        self.container = ft.Column([
            ft.Row([
                self.color_field,
                self.color_preview,
                self.advanced_picker_btn,
                self.clear_btn,
                #self.export_btn,
                #self.import_btn,
                self.import_icon_btn,
                self.text_btn,
                self.save_btn,
                self.load_btn
            ], wrap=True),
            self.palette,
            #self.export_text,
            ft.Divider(),
            ft.Row([
                self.grid_container,
                # place the right-side column next to the grid; this column can grow a scrollable actions area
                self.right_column
            ], spacing=30),
        ], scroll=ft.ScrollMode.AUTO, expand=True)
        # Add flip and rotate buttons
        self.flip_horizontal_btn = ft.ElevatedButton("Flip Horizontal", on_click=lambda e: self.on_flip_image(e, 'horizontal'))
        self.flip_vertical_btn = ft.ElevatedButton("Flip Vertical", on_click=lambda e: self.on_flip_image(e, 'vertical'))
        self.rotate_left_btn = ft.ElevatedButton("Rotate Left", on_click=lambda e: self.on_rotate_image(e, -90))
        self.rotate_right_btn = ft.ElevatedButton("Rotate Right", on_click=lambda e: self.on_rotate_image(e, 90))

        # Add filter buttons
        self.blur_filter_btn = ft.ElevatedButton("Apply Blur", on_click=lambda e: self.on_apply_filter(e, 'BLUR'))
        self.sharpen_filter_btn = ft.ElevatedButton("Apply Sharpen", on_click=lambda e: self.on_apply_filter(e, 'SHARPEN'))

        # Add these buttons to the right-side column (scrollable) and allow wrapping
        self.right_column.controls.append(ft.Row([
            self.flip_horizontal_btn,
            self.flip_vertical_btn,
            self.rotate_left_btn,
            self.rotate_right_btn,
            self.blur_filter_btn,
            self.sharpen_filter_btn,
        ], spacing=10, wrap=True))

        # Add buttons for new color manipulation features
        self.invert_colors_btn = ft.ElevatedButton("Invert Colors", on_click=self.on_invert_colors)
        self.grayscale_btn = ft.ElevatedButton("Convert to Grayscale", on_click=self.on_convert_to_grayscale)
        self.hue_adjust_btn = ft.ElevatedButton("Adjust Hue", on_click=lambda e: self.on_adjust_hue(e, 30))
        self.color_replace_btn = ft.ElevatedButton("Replace Color", on_click=lambda e: self.on_replace_color(e, '#FF0000', '#00FF00'))
        self.gradient_overlay_btn = ft.ElevatedButton("Apply Gradient Overlay", on_click=lambda e: self.on_apply_gradient_overlay(e, '#FF0000'))
        self.opacity_adjust_btn = ft.ElevatedButton("Adjust Opacity", on_click=lambda e: self.on_adjust_opacity(e, 0.5))
        self.sepia_tone_btn = ft.ElevatedButton("Apply Sepia Tone", on_click=self.on_apply_sepia_tone)
        self.pixelate_btn = ft.ElevatedButton("Pixelate", on_click=lambda e: self.on_pixelate(e, 5))
        self.quantize_colors_btn = ft.ElevatedButton("Quantize Colors", on_click=lambda e: self.on_quantize_colors(e, 16))
        self.brightness_contrast_region_btn = ft.ElevatedButton("Adjust Brightness/Contrast (Region)", on_click=lambda e: self.on_adjust_brightness_contrast_region(e, (0, 0, 8, 8), 1.5, 1.2))

        # Group advanced controls into an ExpansionTile so they can be collapsed
        self.advanced_controls_row = ft.Row([
            self.invert_colors_btn,
            self.grayscale_btn,
            self.hue_adjust_btn,
            self.color_replace_btn,
            self.gradient_overlay_btn,
            self.opacity_adjust_btn,
            self.sepia_tone_btn,
            self.pixelate_btn,
            self.quantize_colors_btn,
            self.brightness_contrast_region_btn
        ], spacing=10, wrap=True)

        # Use ExpansionTile (used elsewhere in the codebase) to create a collapsible tile
        self.advanced_expander = ft.ExpansionTile(
            title=ft.Container(content=ft.Text("Advanced Manipulations", size=12, weight=ft.FontWeight.W_400)),
            controls=[self.advanced_controls_row],
        )
        self.right_column.controls.append(self.advanced_expander)

        # Give buttons a fixed width so wrapping behaves predictably in narrow viewports
        btns = [
            self.flip_horizontal_btn, self.flip_vertical_btn, self.rotate_left_btn, self.rotate_right_btn,
            self.blur_filter_btn, self.sharpen_filter_btn,
            self.invert_colors_btn, self.grayscale_btn, self.hue_adjust_btn, self.color_replace_btn,
            self.gradient_overlay_btn, self.opacity_adjust_btn, self.sepia_tone_btn, self.pixelate_btn,
            self.quantize_colors_btn, self.brightness_contrast_region_btn,
            self.text_btn,
        ]
        for b in btns:
            try:
                b.width = 140
            except Exception:
                pass

        # Undo / Redo buttons
        self.undo_btn = ft.ElevatedButton("Undo", on_click=self.on_undo)
        self.redo_btn = ft.ElevatedButton("Redo", on_click=self.on_redo)
        # Append to top controls row
        self.container.controls[0].controls.append(self.undo_btn)
        self.container.controls[0].controls.append(self.redo_btn)

        # internal undo/redo stacks
        self._undo_stack = []
        self._redo_stack = []

        # Wire dialog handlers for the buttons
        try:
            self._wire_dialogs()
        except Exception:
            pass

    def on_color_set_change(self, e):
        import copy
        set_name = self.color_set_dropdown.value
        palette = self.color_sets.get(set_name, self.palette_colors)
        # If switching to Default, restore backup
        if set_name == "Default" and self._palette_backup is not None:
            self._push_undo()
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
        self._push_undo()
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
                # restoring original does not need to push undo
                self.pixels = copy.deepcopy(self._original_pixels)
                self.refresh_grid()
            return
        # Otherwise, apply adjustments to original
        self._push_undo()
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
        r_slider = ft.Slider(min=0, max=255, value=r, label="Red", divisions=255, on_change=None)
        g_slider = ft.Slider(min=0, max=255, value=g, label="Green", divisions=255, on_change=None)
        b_slider = ft.Slider(min=0, max=255, value=b, label="Blue", divisions=255, on_change=None)
        hex_field = ft.TextField(label="Hex", value=self.current_color, width=100)
        preview = ft.Container(width=48, height=48, bgcolor=self.current_color, border_radius=6, border=ft.border.all(1, "#888888"))

        # color wheel parameters
        wheel_size = 280
        value_slider = ft.Slider(min=0.0, max=1.0, value=1, divisions=100, label="Value (Brightness)", on_change=None)
        wheel_img = ft.Image(width=wheel_size, height=wheel_size)
        # HSV fallback sliders
        hue_slider = ft.Slider(min=0, max=360, value=0, divisions=360, label="Hue (0-360°)", on_change=None)
        sat_slider = ft.Slider(min=0.0, max=1.0, value=1.0, divisions=100, label="Saturation (0-1)", on_change=None)

        def _make_color_wheel_image(val):
            # create a color wheel image and save to saved_icons/__color_wheel.png
            saved_dir = self._ensure_saved_dir()
            path = os.path.join(str(saved_dir), '__color_wheel.png')
            size = wheel_size
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            cx = cy = size / 2.0
            radius = size / 2.0
            for y in range(size):
                for x in range(size):
                    dx = x - cx
                    dy = y - cy
                    r = math.hypot(dx, dy)
                    if r <= radius:
                        # angle to hue
                        angle = math.atan2(dy, dx)
                        hue = (angle / (2 * math.pi)) % 1.0
                        sat = min(1.0, r / radius)
                        rgb = colorsys.hsv_to_rgb(hue, sat, float(val))
                        img.putpixel((x, y), (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255), 255))
                    else:
                        img.putpixel((x, y), (0, 0, 0, 0))

            # Save and flush the PNG to disk, then confirm file exists
            try:
                with open(path, 'wb') as f:
                    img.save(f, format='PNG')
                    f.flush()
                return path
            except Exception as ex:
                logger.error(f"color wheel PNG save error: {ex}")
                return path

        def on_wheel_click(ev):
            logger.debug(f"color wheel tap event: {ev!r}")
            # dump event attributes for debugging
            try:
                ev_attrs = [n for n in dir(ev) if not n.startswith('_')]
                logger.debug(f"color wheel event dir: {ev_attrs}")
            except Exception:
                pass
            try:
                logger.debug(f"color wheel ev.__dict__: {getattr(ev, '__dict__', None)!r}")
            except Exception:
                pass
            try:
                ctrl = getattr(ev, 'control', None)
                logger.debug(f"color wheel control: {ctrl!r}")
                logger.debug(f"color wheel control __dict__: {getattr(ctrl, '__dict__', None)!r}")
            except Exception:
                pass
            try:
                logger.debug(f"color wheel ev.data: {getattr(ev, 'data', None)!r}")
            except Exception:
                pass
            # Probe event for possible coordinate attributes
            lx = getattr(ev, 'local_x', None)
            ly = getattr(ev, 'local_y', None)
            if lx is None or ly is None:
                lx = getattr(ev, 'x', None)
                ly = getattr(ev, 'y', None)
            if lx is None or ly is None:
                # try other likely attribute names
                poss = ['local_position', 'position', 'offset', 'local_offset', 'clientX', 'clientY']
                for name in poss:
                    v = getattr(ev, name, None)
                    if v is None:
                        continue
                    # v might be a tuple-like (x,y) or an object with x/y
                    try:
                        if isinstance(v, (tuple, list)) and len(v) >= 2:
                            lx, ly = v[0], v[1]
                            break
                        if hasattr(v, 'x') and hasattr(v, 'y'):
                            lx, ly = getattr(v, 'x'), getattr(v, 'y')
                            break
                    except Exception:
                        continue
            if lx is None or ly is None:
                # log attributes for debugging and return
                try:
                    attrs = ','.join(sorted(name for name in dir(ev) if not name.startswith('_')))
                except Exception:
                    attrs = str(dir(ev))
                logger.debug(f"color wheel event has no coords; available attrs: {attrs}")
                return
            # scale to image pixels
            try:
                logger.debug(f"color wheel tap raw: lx={lx!r} ly={ly!r}")
                img_path = os.path.join(str(self._ensure_saved_dir()), '__color_wheel.png')
                if not os.path.exists(img_path):
                    return
                # compute relative position inside image
                iw = wheel_size
                ih = wheel_size
                # lx/ly may be normalized (0..1) or pixel coordinates; handle both
                if isinstance(lx, (int, float)) and isinstance(ly, (int, float)):
                    if 0.0 <= lx <= 1.0 and 0.0 <= ly <= 1.0:
                        px = int(lx * (iw - 1))
                        py = int(ly * (ih - 1))
                    else:
                        # assume pixel coords
                        px = int(lx)
                        py = int(ly)
                else:
                    px = int(lx)
                    py = int(ly)
                # fallback: clamp
                px = max(0, min(iw-1, px))
                py = max(0, min(ih-1, py))
                im = Image.open(img_path).convert('RGBA')
                val = im.getpixel((px, py))
                logger.debug(f"color wheel mapped to px={px} py={py} pixel={val!r}")
                if isinstance(val, int):
                    r = g = b = int(val)
                    a = 255
                elif isinstance(val, (tuple, list)):
                    if len(val) >= 3:
                        r, g, b = int(val[0]), int(val[1]), int(val[2])
                        a = int(val[3]) if len(val) > 3 else 255
                    else:
                        return
                else:
                    return
                if a == 0:
                    return
                hexv = f"#{r:02X}{g:02X}{b:02X}"
                hex_field.value = hexv
                hex_field.update()
                preview.bgcolor = hexv
                preview.update()
                self.current_color = hexv
                try:
                    self.color_field.value = hexv
                    self.color_field.update()
                except Exception:
                    pass
                try:
                    if getattr(self, 'page', None):
                        self.page.update()
                except Exception:
                    pass
            except Exception as ex:
                logger.exception(f"color wheel click error: {ex}")
                return

        def on_value_change(ev):
            v = float(value_slider.value)
            p = _make_color_wheel_image(v)
            if p:
                wheel_img.src = p
                wheel_img.update()
            if page:
                page.update()

        def hsv_to_hex(h, s, v):
            try:
                import colorsys
                r, g, b = colorsys.hsv_to_rgb(h/360.0, float(s), float(v))
                return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
            except Exception:
                return '#000000'

        def on_hsv_change(ev=None):
            h = float(hue_slider.value)
            s = float(sat_slider.value)
            v = float(value_slider.value)
            hexv = hsv_to_hex(h, s, v)
            # update rgb sliders
            try:
                r_val, g_val, b_val = hex_to_rgb(hexv)
                r_slider.value = r_val
                g_slider.value = g_val
                b_slider.value = b_val
                r_slider.update()
                g_slider.update()
                b_slider.update()
            except Exception:
                pass
            hex_field.value = hexv
            hex_field.update()
            preview.bgcolor = hexv
            preview.update()
            self.current_color = hexv
            try:
                self.color_field.value = hexv
                self.color_field.update()
            except Exception:
                pass
            if page:
                page.update()

        value_slider.on_change = on_value_change
        hue_slider.on_change = on_hsv_change
        sat_slider.on_change = on_hsv_change
        # wrap wheel_img in a GestureDetector so clicks/pans are delivered (attach several handlers)
        wheel_gesture = ft.GestureDetector(content=wheel_img, on_tap=on_wheel_click, on_tap_down=on_wheel_click, on_pan_update=on_wheel_click)

        # generate initial wheel and force the Image control to refresh so clicks work
        try:
            pth = _make_color_wheel_image(value_slider.value)
            if pth:
                wheel_img.src = pth
                wheel_img.update()
                if page:
                    page.update()
        except Exception:
            logger.debug("color wheel initial generation failed")
            pass

        # initialize HSV sliders from current color so UI is in-sync
        r0, g0, b0 = hex_to_rgb(self.current_color)
        rf, gf, bf = r0/255.0, g0/255.0, b0/255.0
        h0, s0, v0 = colorsys.rgb_to_hsv(rf, gf, bf)
        hue_slider.value = h0 * 360.0
        sat_slider.value = s0
        value_slider.value = v0
        # NOTE: Do NOT call .update() on Slider controls here because
        # Flet requires controls to be added to the page before update()
        # is used. We'll perform the initial sync after the dialog is
        # opened below.

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
            val = (hex_field.value or '').strip()
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
            ft.Row([preview, hex_field, ft.Column([wheel_gesture, ft.Row([ft.Text("Value (Brightness)", width=120), value_slider])])]),
            ft.Row([ft.Text("Red", width=120), r_slider]),
            ft.Row([ft.Text("Green", width=120), g_slider]),
            ft.Row([ft.Text("Blue", width=120), b_slider]),
            ft.Row([ft.Text("Hue (0-360°)", width=120), hue_slider]),
            ft.Row([ft.Text("Saturation (0-1)", width=120), sat_slider]),
        ], spacing=10, width=wheel_size + 150)
        self.color_picker_dialog = ft.AlertDialog(
            title=ft.Text("Advanced Color Picker"),
            content=content,
            actions=[ft.TextButton("Close", on_click=lambda ev: self._close_dialog(self.color_picker_dialog, page))],
            open=True
        )
        if page:
            page.open(self.color_picker_dialog)
            page.update()
            # Now that the dialog and its controls are attached to the page,
            # it's safe to run the initial sync handlers which may call
            # .update() on controls.
            on_value_change(None)
            on_hsv_change(None)

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
                self._push_undo()
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
            self._push_undo()
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
        self._push_undo()
        self.pixels = [["#FFFFFF" for _ in range(self.size)] for _ in range(self.size)]
        self.refresh_grid()

    #def on_export(self, e):
    #    import json
    #    self.export_text.value = json.dumps(self.pixels)
    #    self.export_text.update()

    #def on_import(self, e):
    #    import json
    #    try:
    #        data = json.loads(self.export_text.value)
    #        if isinstance(data, list) and len(data) == self.size and all(len(row) == self.size for row in data):
    #            self._push_undo()
    #            self.pixels = data
    #            self.refresh_grid()
    #    except Exception:
    #        self.export_text.value = "Invalid JSON!"
    #        self.export_text.update()

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

    # 5x7 pixel font for A-Z and 0-9 (each entry is a list of 7 integers, 5 bits each)
    _font_5x7 = {
        'A': [0b01110,0b10001,0b10001,0b11111,0b10001,0b10001,0b10001],
        'B': [0b11110,0b10001,0b10001,0b11110,0b10001,0b10001,0b11110],
        'C': [0b01110,0b10001,0b10000,0b10000,0b10000,0b10001,0b01110],
        'D': [0b11110,0b10001,0b10001,0b10001,0b10001,0b10001,0b11110],
        'E': [0b11111,0b10000,0b10000,0b11110,0b10000,0b10000,0b11111],
        'F': [0b11111,0b10000,0b10000,0b11110,0b10000,0b10000,0b10000],
        'G': [0b01110,0b10001,0b10000,0b10111,0b10001,0b10001,0b01110],
        'H': [0b10001,0b10001,0b10001,0b11111,0b10001,0b10001,0b10001],
        'I': [0b01110,0b00100,0b00100,0b00100,0b00100,0b00100,0b01110],
        'J': [0b00111,0b00010,0b00010,0b00010,0b10010,0b10010,0b01100],
        'K': [0b10001,0b10010,0b10100,0b11000,0b10100,0b10010,0b10001],
        'L': [0b10000,0b10000,0b10000,0b10000,0b10000,0b10000,0b11111],
        'M': [0b10001,0b11011,0b10101,0b10101,0b10001,0b10001,0b10001],
        'N': [0b10001,0b10001,0b11001,0b10101,0b10011,0b10001,0b10001],
        'O': [0b01110,0b10001,0b10001,0b10001,0b10001,0b10001,0b01110],
        'P': [0b11110,0b10001,0b10001,0b11110,0b10000,0b10000,0b10000],
        'Q': [0b01110,0b10001,0b10001,0b10001,0b10101,0b10010,0b01101],
        'R': [0b11110,0b10001,0b10001,0b11110,0b10100,0b10010,0b10001],
        'S': [0b01111,0b10000,0b10000,0b01110,0b00001,0b00001,0b11110],
        'T': [0b11111,0b00100,0b00100,0b00100,0b00100,0b00100,0b00100],
        'U': [0b10001,0b10001,0b10001,0b10001,0b10001,0b10001,0b01110],
        'V': [0b10001,0b10001,0b10001,0b10001,0b10001,0b01010,0b00100],
        'W': [0b10001,0b10001,0b10001,0b10101,0b10101,0b11011,0b10001],
        'X': [0b10001,0b10001,0b01010,0b00100,0b01010,0b10001,0b10001],
        'Y': [0b10001,0b10001,0b01010,0b00100,0b00100,0b00100,0b00100],
        'Z': [0b11111,0b00001,0b00010,0b00100,0b01000,0b10000,0b11111],
        '0': [0b01110,0b10001,0b10011,0b10101,0b11001,0b10001,0b01110],
        '1': [0b00100,0b01100,0b00100,0b00100,0b00100,0b00100,0b01110],
        '2': [0b01110,0b10001,0b00001,0b00010,0b00100,0b01000,0b11111],
        '3': [0b01110,0b10001,0b00001,0b00110,0b00001,0b10001,0b01110],
        '4': [0b00010,0b00110,0b01010,0b10010,0b11111,0b00010,0b00010],
        '5': [0b11111,0b10000,0b11110,0b00001,0b00001,0b10001,0b01110],
        '6': [0b00110,0b01000,0b10000,0b11110,0b10001,0b10001,0b01110],
        '7': [0b11111,0b00001,0b00010,0b00100,0b01000,0b01000,0b01000],
        '8': [0b01110,0b10001,0b10001,0b01110,0b10001,0b10001,0b01110],
        '9': [0b01110,0b10001,0b10001,0b01111,0b00001,0b00010,0b01100],
        ' ': [0,0,0,0,0,0,0]
    }

    def _render_text_to_pixels(self, text, color, scale=1, x_offset=0, y_offset=0):
        """Return a pixel grid (list of rows) with text stamped at given offset. Does not modify self.pixels."""
        # prepare a blank grid
        grid = [[None for _ in range(self.size)] for _ in range(self.size)]
        tx = x_offset
        ty = y_offset
        text = (text or '').upper()
        for ch in text:
            glyph = self._font_5x7.get(ch, self._font_5x7.get(' '))
            for row_idx, bits in enumerate(glyph):
                for bit_idx in range(5):
                    if bits & (1 << (4 - bit_idx)):
                        # apply scale
                        for sy in range(scale):
                            for sx in range(scale):
                                gx = tx + bit_idx * scale + sx
                                gy = ty + row_idx * scale + sy
                                if 0 <= gx < self.size and 0 <= gy < self.size:
                                    grid[gy][gx] = color
            tx += (5 + 1) * scale  # 1px spacing
        return grid

    def _stamp_pixels(self, stamp_grid):
        """Stamp a grid of pixel colors (None means skip) onto self.pixels, pushing undo."""
        self._push_undo()
        for y in range(self.size):
            for x in range(self.size):
                v = stamp_grid[y][x]
                if v is not None:
                    self.pixels[y][x] = v
        self.refresh_grid()

    def _open_text_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        text_field = ft.TextField(label="Text", value="A", width=200)
        color_field = ft.TextField(label="Color (hex)", value=self.current_color, width=120)
        scale_dropdown = ft.Dropdown(label="Scale", options=[ft.dropdown.Option(str(i)) for i in range(1,4)], value='1', width=100)
        pos_x = ft.TextField(label="X Offset", value="0", width=80)
        pos_y = ft.TextField(label="Y Offset", value="0", width=80)
        status = ft.Text("")

        def do_stamp(ev):
            try:
                txt = (text_field.value or '').strip()
                col = (color_field.value or '').strip()
                sc = int(scale_dropdown.value)
                ox = int((pos_x.value or '0').strip())
                oy = int((pos_y.value or '0').strip())
                if not txt:
                    status.value = "Enter text"
                    status.update()
                    return
                # render and stamp
                stamp = self._render_text_to_pixels(txt, col, scale=sc, x_offset=ox, y_offset=oy)
                self._stamp_pixels(stamp)
                dlg.open = False
                if page:
                    page.update()
            except Exception as ex:
                status.value = f"Error: {ex}"
                status.update()

        content = ft.Column([text_field, ft.Row([color_field, scale_dropdown, pos_x, pos_y], wrap=True), status], spacing=8, width=350)
        dlg = ft.AlertDialog(title=ft.Text("Stamp Text"), content=content, actions=[ft.TextButton("Stamp", on_click=do_stamp), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))], open=False)
        if page:
            logger.debug(f"Opening text dialog, page={page}")
            page.open(dlg)
            page.update()

    def on_save_png(self, e):
        page = e.page if hasattr(e, 'page') else None
        saved_dir = self._ensure_saved_dir()
        if not saved_dir:
            if page:
                page.snack_bar = ft.SnackBar(ft.Text("Failed to create saved_icons folder"))
                page.snack_bar.open = True
                page.update()
            return

        # Show metadata dialog and save JSON file containing metadata + pixels + PNG (base64)
        name_field = ft.TextField(label="Filename (no extension)")
        title_field = ft.TextField(label="Title", value="")
        author_field = ft.TextField(label="Author", value="")
        tags_field = ft.TextField(label="Tags (comma separated)")
        desc_field = ft.TextField(label="Description", multiline=True, height=80)
        save_png_checkbox = ft.Checkbox(label="Also save PNG file", value=True)
        status = ft.Text("")

        def do_save(ev):
            fn = (name_field.value or '').strip()
            if not fn:
                status.value = "Enter a filename"
                status.update()
                return
            # collect metadata
            meta = {
                "title": (title_field.value or '').strip(),
                "author": (author_field.value or '').strip(),
                "tags": [t.strip() for t in (tags_field.value or '').split(',') if t.strip()],
                "description": (desc_field.value or '').strip(),
                "created_by": "yoto-up",
            }

            basename = fn + '.json'
            path = os.path.join(str(saved_dir), basename) if hasattr(saved_dir, 'joinpath') else os.path.join(saved_dir, basename)

            try:
                # build image and base64 PNG
                img = self._pixels_to_image(self.pixels)
                import io
                import base64
                import json
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                png_bytes = buf.getvalue()
                png_b64 = base64.b64encode(png_bytes).decode('ascii')

                # payload
                obj = {
                    "metadata": meta,
                    "pixels": self.pixels,
                    "png_base64": png_b64,
                }

                # write JSON file
                with open(path, 'w', encoding='utf-8') as fh:
                    json.dump(obj, fh, ensure_ascii=False, indent=2)

                # optionally write PNG file as well
                if save_png_checkbox.value:
                    png_path = os.path.join(str(saved_dir), fn + '.png')
                    try:
                        with open(png_path, 'wb') as pf:
                            pf.write(png_bytes)
                    except Exception:
                        # ignore PNG write errors but report status
                        status.value = "Saved JSON but failed to write PNG"
                        status.update()

                if page:
                    status.value = f"Saved: {basename}"
                    status.update()
                    page.update()
                # close dialog
                try:
                    dlg.open = False
                    if page:
                        page.update()
                except Exception:
                    pass

            except Exception as ex:
                status.value = f"Save failed: {ex}"
                status.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Save Icon (JSON + metadata)"),
            content=ft.Column([name_field, title_field, author_field, tags_field, desc_field, save_png_checkbox, status], spacing=8),
            actions=[ft.TextButton("Save", on_click=do_save), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))]
        )
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
            try:
                if v.lower().endswith('.png'):
                    img = Image.open(p)
                    img2 = img.resize((64, 64))
                    tmp = os.path.join(sd, '__preview.png')
                    img2.save(tmp)
                    preview.src = tmp
                elif v.lower().endswith('.json'):
                    # parse json package
                    with open(p, 'r', encoding='utf-8') as fh:
                        obj = json.load(fh)
                    # if embedded png exists, write a preview file
                    if isinstance(obj, dict) and obj.get('png_base64'):
                        try:
                            import base64
                            b = base64.b64decode(obj['png_base64'])
                            tmp_path = os.path.join(sd, '__preview.png')
                            with open(tmp_path, 'wb') as pf:
                                pf.write(b)
                            preview.src = tmp_path
                        except Exception:
                            preview.src = ''
                    else:
                        # no embedded PNG; render pixels to a small preview if possible
                        preview.src = ''
                else:
                    preview.src = ''
            except Exception as ex:
                logger.exception(f"Error loading file preview: {ex}")
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
                elif v.lower().endswith('.json'):
                    with open(p, 'r', encoding='utf-8') as fh:
                        obj = json.load(fh)
                    # restore pixels from known shapes
                    if isinstance(obj, dict):
                        # write metadata to export_text for user to see/edit
                        try:
                            meta = obj.get('metadata', {})
                            if hasattr(self, 'export_text') and self.export_text is not None:
                                self.export_text.value = json.dumps(meta, ensure_ascii=False, indent=2)
                                self.export_text.update()
                        except Exception:
                            pass
                        if 'pixels' in obj and isinstance(obj['pixels'], list):
                            pixels = obj['pixels']
                        elif 'png_base64' in obj:
                            # decode embedded PNG and convert to pixels
                            try:
                                import base64
                                import io
                                b = base64.b64decode(obj['png_base64'])
                                img = Image.open(io.BytesIO(b))
                                pixels = self._image_to_pixels(img)
                            except Exception:
                                pixels = None
                        else:
                            pixels = None
                    else:
                        pixels = None
                else:
                    pixels = None

                if isinstance(pixels, list):
                    logger.debug(f"Loaded pixel data: (list with {len(pixels)} rows)")
                    self.pixels = pixels
                    self.refresh_grid()
                    self._close_dialog(dlg, page)
                else:
                    logger.error("Loaded pixel data is not a list or could not be decoded")
                    status.value = "Selected file contains no pixel data"
                    status.update()
            except Exception as ex:
                logger.error(f"Failed to load icon: {ex}")
                status.value = f"Load failed: {ex}"
                status.update()

        dlg = ft.AlertDialog(title=ft.Text("Load Saved Icon"), content=ft.Column([dropdown, preview, status]), actions=[ft.TextButton("Load", on_click=do_load), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))])
        if page:
            page.open(dlg)
            page.update()

    def flip_image(self, image, direction):
        """Flip the image either horizontally or vertically."""
        if direction == 'horizontal':
            return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        elif direction == 'vertical':
            return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        else:
            raise ValueError("Invalid direction. Use 'horizontal' or 'vertical'.")

    def rotate_image(self, image, angle):
        """Rotate the image by a given angle."""
        return image.rotate(angle, expand=True)

    def crop_image(self, image, box):
        """Crop the image to the given box (left, upper, right, lower)."""
        return image.crop(box)

    def apply_filter(self, image, filter_type):
        """Apply a filter to the image."""
        if filter_type == 'BLUR':
            from PIL import ImageFilter
            return image.filter(ImageFilter.BLUR)
        elif filter_type == 'SHARPEN':
            from PIL import ImageFilter
            return image.filter(ImageFilter.SHARPEN)
        else:
            raise ValueError("Unsupported filter type. Use 'BLUR' or 'SHARPEN'.")

    def on_apply_filter(self, e, filter_type):
        """Handle applying a filter to the image."""
        img = self._pixels_to_image(self.pixels)
        filtered_img = self.apply_filter(img, filter_type)
        self._push_undo()
        self.pixels = self._image_to_pixels(filtered_img)
        self.refresh_grid()

    def on_flip_image(self, e, direction):
        """Handle flipping the image."""
        img = self._pixels_to_image(self.pixels)
        flipped_img = self.flip_image(img, direction)
        self._push_undo()
        self.pixels = self._image_to_pixels(flipped_img)
        self.refresh_grid()

    def on_rotate_image(self, e, angle):
        """Handle rotating the image."""
        img = self._pixels_to_image(self.pixels)
        rotated_img = self.rotate_image(img, angle)
        self._push_undo()
        self.pixels = self._image_to_pixels(rotated_img)
        self.refresh_grid()

    def invert_colors(self, image):
        """Invert the colors of the image."""
        return image.point(lambda p: 255 - p)

    def convert_to_grayscale(self, image):
        """Convert the image to grayscale."""
        return image.convert('L').convert('RGBA')

    def adjust_hue(self, image, degrees):
        """Adjust the hue of the image by a specified degree."""
        import colorsys
        def shift_hue(r, g, b, degrees):
            h, lightness, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            h = (h + degrees / 360) % 1
            r2, g2, b2 = colorsys.hls_to_rgb(h, lightness, s)
            return int(r2 * 255), int(g2 * 255), int(b2 * 255)
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b, a = pixels[x, y]
                pixels[x, y] = (*shift_hue(r, g, b, degrees), a)
        return image

    def replace_color(self, image, target_color, replacement_color):
        """Replace all instances of a specific color with another color."""
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                if pixels[x, y][:3] == target_color[:3]:
                    pixels[x, y] = replacement_color
        return image

    def _hex_to_rgba(self, hex_color, alpha=255):
        """Convert a hex color (or simple rgba string) to an (R,G,B,A) tuple of ints 0-255.

        Supported inputs:
        - "#RGB" or "#RRGGBB" or "#RRGGBBAA"
        - "rgba(r,g,b,a)" where a may be 0-1 or 0-255
        - plain hex-like strings without '#'
        Falls back to opaque black on parse error.
        """
        if not hex_color:
            return (0, 0, 0, alpha)
        s = str(hex_color).strip()
        # rgba(...) format
        if s.lower().startswith('rgba'):
            try:
                nums = re.findall(r"[0-9]*\.?[0-9]+", s)
                if len(nums) >= 3:
                    r = int(float(nums[0]))
                    g = int(float(nums[1]))
                    b = int(float(nums[2]))
                    a = int(float(nums[3]) * 255) if len(nums) > 3 and float(nums[3]) <= 1 else (int(float(nums[3])) if len(nums) > 3 else alpha)
                    return (r, g, b, a)
            except Exception:
                return (0, 0, 0, alpha)

        # strip leading '#'
        if s.startswith('#'):
            s = s[1:]

        try:
            if len(s) == 3:
                r = int(s[0] * 2, 16)
                g = int(s[1] * 2, 16)
                b = int(s[2] * 2, 16)
                return (r, g, b, alpha)
            if len(s) == 4:  # rgba in hex short form
                r = int(s[0] * 2, 16)
                g = int(s[1] * 2, 16)
                b = int(s[2] * 2, 16)
                a = int(s[3] * 2, 16)
                return (r, g, b, a)
            if len(s) == 6:
                r = int(s[0:2], 16)
                g = int(s[2:4], 16)
                b = int(s[4:6], 16)
                return (r, g, b, alpha)
            if len(s) == 8:
                r = int(s[0:2], 16)
                g = int(s[2:4], 16)
                b = int(s[4:6], 16)
                a = int(s[6:8], 16)
                return (r, g, b, a)
            # try comma/space separated numbers
            parts = [p for p in re.split(r'[,\s]+', s) if p]
            if len(parts) >= 3:
                r = int(float(parts[0]))
                g = int(float(parts[1]))
                b = int(float(parts[2]))
                a = int(float(parts[3])) if len(parts) > 3 else alpha
                return (r, g, b, a)
        except Exception:
            return (0, 0, 0, alpha)

        return (0, 0, 0, alpha)

    def apply_gradient_overlay(self, image, gradient):
        """Apply a gradient overlay to the image."""
        overlay = Image.new('RGBA', image.size, gradient)
        return Image.alpha_composite(image, overlay)

    def adjust_opacity(self, image, opacity):
        """Adjust the opacity of the image."""
        alpha = image.split()[-1]
        alpha = alpha.point(lambda p: int(p * opacity))
        image.putalpha(alpha)
        return image

    def apply_sepia_tone(self, image):
        """Apply a sepia tone to the image."""
        sepia = [(r * 0.393 + g * 0.769 + b * 0.189,
                  r * 0.349 + g * 0.686 + b * 0.168,
                  r * 0.272 + g * 0.534 + b * 0.131)
                 for r, g, b in image.getdata()]
        image.putdata([tuple(map(int, p)) for p in sepia])
        return image

    def pixelate(self, image, pixel_size):
        """Pixelate the image by enlarging each pixel."""
        small = image.resize((image.width // pixel_size, image.height // pixel_size), Image.Resampling.NEAREST)
        return small.resize(image.size, Image.Resampling.NEAREST)

    def quantize_colors(self, image, num_colors):
        """Reduce the number of colors in the image."""
        return image.quantize(colors=num_colors)

    def adjust_brightness_contrast_region(self, image, region, brightness, contrast):
        """Adjust brightness and contrast for a specific region."""
        from PIL import ImageEnhance
        cropped = image.crop(region)
        cropped = ImageEnhance.Brightness(cropped).enhance(brightness)
        cropped = ImageEnhance.Contrast(cropped).enhance(contrast)
        image.paste(cropped, region)
        return image

    # UI handlers for the color manipulation buttons (ensure these are present)
    def on_invert_colors(self, e):
        img = self._pixels_to_image(self.pixels)
        img = self.invert_colors(img)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_convert_to_grayscale(self, e):
        img = self._pixels_to_image(self.pixels)
        img = self.convert_to_grayscale(img)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_adjust_hue(self, e, degrees):
        img = self._pixels_to_image(self.pixels)
        img = self.adjust_hue(img, degrees)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_replace_color(self, e, target_color, replacement_color):
        img = self._pixels_to_image(self.pixels)
        img = self.replace_color(img, self._hex_to_rgba(target_color), self._hex_to_rgba(replacement_color))
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_apply_gradient_overlay(self, e, gradient_color):
        img = self._pixels_to_image(self.pixels)
        img = self.apply_gradient_overlay(img, self._hex_to_rgba(gradient_color))
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_adjust_opacity(self, e, opacity):
        img = self._pixels_to_image(self.pixels)
        img = self.adjust_opacity(img, opacity)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_apply_sepia_tone(self, e):
        img = self._pixels_to_image(self.pixels)
        img = self.apply_sepia_tone(img)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_pixelate(self, e, pixel_size):
        img = self._pixels_to_image(self.pixels)
        img = self.pixelate(img, pixel_size)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_quantize_colors(self, e, num_colors):
        img = self._pixels_to_image(self.pixels)
        img = self.quantize_colors(img, num_colors)
        if hasattr(img, 'convert'):
            img = img.convert('RGBA')
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def on_adjust_brightness_contrast_region(self, e, region, brightness, contrast):
        img = self._pixels_to_image(self.pixels)
        img = self.adjust_brightness_contrast_region(img, region, brightness, contrast)
        self._push_undo()
        self.pixels = self._image_to_pixels(img)
        self.refresh_grid()

    def control(self):
        return self.container

    class _SmallDialog:
        def __init__(self, title, content, page=None):
            self.dialog = ft.AlertDialog(title=ft.Text(title), content=content, actions=[], open=False)
            self.page = page
        def open(self):
            if self.page:
                self.page.open(self.dialog)
                self.page.update()
            else:
                self.dialog.open = True
        def close(self):
            if self.page:
                self.page.update()
            self.dialog.open = False

    def _open_replace_color_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        target_field = ft.TextField(label="Target Color (hex)", value="#FF0000", width=140)
        replacement_field = ft.TextField(label="Replacement Color (hex)", value="#00FF00", width=140)
        status = ft.Text("")
        def do_replace(ev):
            t = (target_field.value or '').strip()
            r = (replacement_field.value or '').strip()
            if not t.startswith('#') or not r.startswith('#'):
                status.value = "Enter valid hex colors like #FF0000"
                status.update()
                return
            self.on_replace_color(ev, t, r)
            dlg.dialog.open = False
            if page:
                page.update()
        content = ft.Column([target_field, replacement_field, status])
        dlg = self._SmallDialog("Replace Color", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Replace", on_click=do_replace), ft.TextButton("Cancel", on_click=lambda ev: (setattr(dlg.dialog, 'open', False), page.update() if page else None))]
        if page:
            page.open(dlg.dialog)
            page.update()

    def _open_gradient_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        color_field = ft.TextField(label="Gradient Color (hex)", value="#FF0000", width=140)
        status = ft.Text("")
        def do_apply(ev):
            c = (color_field.value or '').strip()
            if not c.startswith('#'):
                status.value = "Enter a valid hex color like #FF0000"
                status.update()
                return
            self.on_apply_gradient_overlay(ev, c)
            dlg.dialog.open = False
            if page:
                page.update()
        content = ft.Column([color_field, status])
        dlg = self._SmallDialog("Gradient Overlay", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: (setattr(dlg.dialog, 'open', False), page.update() if page else None))]
        if page:
            page.open(dlg.dialog)
            page.update()

    def _open_hue_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        degrees_field = ft.TextField(label="Degrees (e.g. 30 or -30)", value="30", width=140)
        status = ft.Text("")
        def do_apply(ev):
            try:
                deg = int((degrees_field.value or '').strip())
            except Exception:
                status.value = "Enter an integer degree value"
                status.update()
                return
            self.on_adjust_hue(ev, deg)
            dlg.dialog.open = False
            if page:
                page.update()
        content = ft.Column([degrees_field, status])
        dlg = self._SmallDialog("Adjust Hue", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: (setattr(dlg.dialog, 'open', False), page.update() if page else None))]
        if page:
            page.open(dlg.dialog)
            page.update()

    def _open_opacity_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        opacity_field = ft.TextField(label="Opacity (0.0-1.0)", value="0.5", width=140)
        status = ft.Text("")
        def do_apply(ev):
            try:
                op = float((opacity_field.value or '').strip())
            except Exception:
                status.value = "Enter a float between 0.0 and 1.0"
                status.update()
                return
            if op < 0 or op > 1:
                status.value = "Opacity must be between 0.0 and 1.0"
                status.update()
                return
            self.on_adjust_opacity(ev, op)
            dlg.dialog.open = False
            if page:
                page.update()
        content = ft.Column([opacity_field, status])
        dlg = self._SmallDialog("Adjust Opacity", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: (setattr(dlg.dialog, 'open', False), page.update() if page else None))]
        if page:
            page.open(dlg.dialog)
            page.update()

    def _open_pixelate_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        size_field = ft.TextField(label="Pixel size (integer)", value="5", width=140)
        status = ft.Text("")
        def do_apply(ev):
            try:
                sz = int((size_field.value or '').strip())
            except Exception:
                status.value = "Enter an integer pixel size"
                status.update()
                return
            if sz <= 0:
                status.value = "Pixel size must be > 0"
                status.update()
                return
            self.on_pixelate(ev, sz)
            dlg.dialog.open = False
            if page:
                page.update()
        content = ft.Column([size_field, status])
        dlg = self._SmallDialog("Pixelate", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: (setattr(dlg.dialog, 'open', False), page.update() if page else None))]
        if page:
            page.open(dlg.dialog)
            page.update()

    def _open_quantize_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        count_field = ft.TextField(label="Color count (integer)", value="16", width=140)
        status = ft.Text("")
        def do_apply(ev):
            try:
                cnt = int((count_field.value or '').strip())
            except Exception:
                status.value = "Enter an integer color count"
                status.update()
                return
            if cnt <= 0:
                status.value = "Color count must be > 0"
                status.update()
                return
            self.on_quantize_colors(ev, cnt)
            dlg.dialog.open = False
            if page:
                page.update()
        content = ft.Column([count_field, status])
        dlg = self._SmallDialog("Quantize Colors", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: (setattr(dlg.dialog, 'open', False), page.update() if page else None))]
        if page:
            page.open(dlg.dialog)
            page.update()

    # Rewire the buttons to open dialogs instead of hardcoded calls
    def _wire_dialogs(self):
        try:
            self.invert_colors_btn.on_click = self.on_invert_colors
            self.grayscale_btn.on_click = self.on_convert_to_grayscale
            self.hue_adjust_btn.on_click = self._open_hue_dialog
            self.color_replace_btn.on_click = self._open_replace_color_dialog
            self.gradient_overlay_btn.on_click = self._open_gradient_dialog
            self.opacity_adjust_btn.on_click = self._open_opacity_dialog
            self.sepia_tone_btn.on_click = self.on_apply_sepia_tone
            self.pixelate_btn.on_click = self._open_pixelate_dialog
            self.quantize_colors_btn.on_click = self._open_quantize_dialog
            self.brightness_contrast_region_btn.on_click = lambda e: self.on_adjust_brightness_contrast_region(e, (0, 0, 8, 8), 1.5, 1.2)
        except Exception:
            pass

    # wiring is invoked from _build via self._wire_dialogs()


    # Undo / Redo logic
    def _push_undo(self):
        # push a deep copy of pixels
        self._undo_stack.append(copy.deepcopy(self.pixels))
        # limit stack size
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        # clear redo when new action performed
        self._redo_stack.clear()

    def _can_undo(self):
        return len(self._undo_stack) > 0

    def _can_redo(self):
        return len(self._redo_stack) > 0

    def on_undo(self, e):
        if not self._can_undo():
            return
        self._redo_stack.append(copy.deepcopy(self.pixels))
        self.pixels = self._undo_stack.pop()
        self.refresh_grid()

    def on_redo(self, e):
        if not self._can_redo():
            return
        self._undo_stack.append(copy.deepcopy(self.pixels))
        self.pixels = self._redo_stack.pop()
        self.refresh_grid()

    # wrap mutating operations to push undo state
    def _mutate_start(self):
        self._push_undo()

    def _mutate_end(self):
        # placeholder for future hooks
        pass

    # patch all places where pixels are changed to call _mutate_start()


# Standalone demo
if __name__ == "__main__":
    def main(page: ft.Page):
        page.title = "Pixel Art Editor"
        editor = PixelArtEditor()
        page.add(editor.control())
    ft.app(target=main)
