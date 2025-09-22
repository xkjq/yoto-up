from pathlib import Path
import flet as ft
import sys
import os
from loguru import logger
from PIL import Image
import json
import re
import hashlib
import copy
try:
    from yoto_app.icon_import_helpers import list_icon_cache_files, load_icon_as_pixels
    from yoto_app.pixel_fonts import _font_3x5, _font_5x7
    from yoto_app.colour_picker import ColourPicker
except ImportError:
    from icon_import_helpers import list_icon_cache_files, load_icon_as_pixels
    from pixel_fonts import _font_3x5, _font_5x7
    from colour_picker import ColourPicker
import colorsys

if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ICON_DIR = "saved_icons"

class PixelArtEditor:
    def __init__(self, size=16, pixel_size=24, page=None, loading_dialog=None  ):
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
        self.page = page
        self.loading_dialog = loading_dialog
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
        # Add a transparent swatch at the end
        try:
            self.palette.controls.append(
                ft.Container(
                    width=24,
                    height=24,
                    content=ft.Text("T", size=10),
                    border_radius=4,
                    border=ft.border.all(1, "#888888"),
                    on_click=self.make_palette_click_handler(None),
                    tooltip="Transparent"
                )
            )
        except Exception:
            pass
        self.clear_btn = ft.ElevatedButton("Clear", on_click=self.on_clear)
        #self.export_btn = ft.ElevatedButton("Export", on_click=self.on_export)
        #self.import_btn = ft.ElevatedButton("Import", on_click=self.on_import)
        self.import_icon_btn = ft.ElevatedButton("Import Icon from Cache", on_click=self.on_import_icon)
        # Save / Load created icons
        self.save_btn = ft.ElevatedButton("Save Icon", on_click=self.on_save_png)
        self.load_btn = ft.ElevatedButton("Load Icon", on_click=self.on_load_png)
        # Text generation (pixel letters/numbers)
        self.text_btn = ft.ElevatedButton("Stamp text", on_click=self._open_text_dialog)
        # Persistent metadata fields (visible/editable while creating icon)
        self.meta_title_field = ft.TextField(label="Title", value="", width=300)
        self.meta_author_field = ft.TextField(label="Author", value="", width=300)
        self.meta_tags_field = ft.TextField(label="Tags (comma separated)", value="", width=300)
        self.meta_description_field = ft.TextField(label="Description", multiline=True, height=80, width=300)
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

        # Undo / Redo buttons
        self.undo_btn = ft.ElevatedButton("Undo", on_click=self.on_undo)
        self.redo_btn = ft.ElevatedButton("Redo", on_click=self.on_redo)

        # include metadata panel on the right so user can view/edit while creating
        meta_panel = ft.Column([
            ft.Text("Icon metadata", size=12, weight=ft.FontWeight.W_600),
            self.meta_title_field,
            self.meta_author_field,
            self.meta_tags_field,
            self.meta_description_field
        ], spacing=6)
        self.right_column = ft.Column([
            ft.Row([self.undo_btn, self.redo_btn], spacing=10),

            self.text_btn,
            meta_panel,
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


        # internal undo/redo stacks
        self._undo_stack = []
        self._redo_stack = []

        # Wire dialog handlers for the buttons
        try:
            self._wire_dialogs()
        except Exception:
            pass

    # ----- dialog management helpers so nested dialogs return to editor dialog -----
    def _open_dialog(self, dlg, page=None):
        """Open dlg, remembering and closing the current parent dialog (if it is the editor dialog).
        When dlg is closed via _close_dialog we'll reopen the parent dialog automatically."""
        page = page or getattr(self, 'page', None)
        try:
            parent = None
            if page and getattr(page, 'dialog', None):
                parent = page.dialog
                # Only consider parent if it contains this editor's container
                try:
                    if getattr(parent, 'content', None) is self.container:
                        dlg._parent_dialog = parent
                        # hide parent while child is active
                        try:
                            parent.open = False
                        except Exception:
                            pass
                    else:
                        dlg._parent_dialog = None
                except Exception:
                    logger.exception("Error checking parent dialog content")
                    dlg._parent_dialog = None
            if page:
                page.open(dlg)
                page.update()
        except Exception:
            logger.exception("Error opening dialog")
            # best-effort fallback
            try:
                if page:
                    page.open(dlg)
                    page.update()
            except Exception:
                pass

    def _close_dialog(self, dlg, page=None):
        """Close dlg and reopen any parent dialog that was hidden by _open_dialog."""
        page = page or getattr(self, 'page', None)
        try:
            try:
                dlg.open = False
            except Exception:
                logger.exception("Error closing dialog")
                # some wrappers store nested dialog under dlg.dialog
                try:
                    getattr(dlg, 'dialog').open = False
                except Exception:
                    logger.exception("Error closing nested dialog")
            if page:
                page.update()
            parent = getattr(dlg, '_parent_dialog', None)
            if not parent and hasattr(dlg, 'dialog'):
                parent = getattr(dlg, 'dialog', None)._parent_dialog if getattr(dlg, 'dialog', None) else None
            if parent and page:
                try:
                    page.open(parent)
                    page.update()
                except Exception:
                    logger.exception("Error reopening parent dialog")
        except Exception:
            logger.exception("Error in _close_dialog")
    # ---------------------------------------------------------------------------

    def load_icon(self, path: str, metadata: dict = None):
        """Load an icon (PNG/JSON) into the editor, populate metadata fields if present."""
        try:
            logger.debug(f"PixelArtEditor.load_icon: Loading icon from {path}")
            logger.debug(f"PixelArtEditor.load_icon: Caller provided metadata: {metadata}")
            pixels = None
            p = str(path)
            if p.lower().endswith('.json'):
                try:
                    with open(p, 'r', encoding='utf-8') as fh:
                        obj = json.load(fh)
                except Exception:
                    obj = None
                if isinstance(obj, dict):
                    # populate persistent metadata fields if present
                    try:
                        meta = obj.get('metadata', {}) or {}
                        if hasattr(self, 'meta_title_field'):
                            self.meta_title_field.value = meta.get('title', '') or ''
                            self.meta_author_field.value = meta.get('author', '') or ''
                            self.meta_tags_field.value = ', '.join(meta.get('tags', [])) if isinstance(meta.get('tags', []), list) else (meta.get('tags') or '')
                            self.meta_description_field.value = meta.get('description', '') or ''
                            self.meta_title_field.update()
                            self.meta_author_field.update()
                            self.meta_tags_field.update()
                            self.meta_description_field.update()
                    except Exception:
                        pass
                    if 'pixels' in obj and isinstance(obj['pixels'], list):
                        pixels = obj['pixels']
                    elif 'png_base64' in obj:
                        try:
                            import base64, io
                            b = base64.b64decode(obj['png_base64'])
                            img = Image.open(io.BytesIO(b))
                            pixels = self._image_to_pixels(img)
                        except Exception:
                            pixels = None
            # fallback to generic loader (supports PNG etc.)
            if pixels is None:
                try:
                    # use helper that handles caches; fall back to PIL
                    pixels = load_icon_as_pixels(path, size=self.size)
                except Exception:
                    try:
                        img = Image.open(path)
                        pixels = self._image_to_pixels(img)
                    except Exception:
                        pixels = None
            if pixels and isinstance(pixels, list):
                self._push_undo()
                self.pixels = pixels
                # if caller provided metadata, populate persistent fields
                try:
                    if metadata and isinstance(metadata, dict) and hasattr(self, 'meta_title_field'):
                        self.meta_title_field.value = metadata.get('title', '') or ''
                        self.meta_author_field.value = metadata.get('author', '') or ''
                        if metadata.get('tags'):
                            self.meta_tags_field.value = ', '.join(metadata.get('tags', [])) if isinstance(metadata.get('tags', []), list) else (metadata.get('tags') or '')
                        elif metadata.get("publicTags"):
                            self.meta_tags_field.value = ', '.join(metadata.get('publicTags', [])) if isinstance(metadata.get('publicTags', []), list) else (metadata.get('publicTags') or '')
                        self.meta_description_field.value = metadata.get('description', '') or ''
                        self.meta_title_field.update()
                        self.meta_author_field.update()
                        self.meta_tags_field.update()
                        self.meta_description_field.update()
                except Exception:
                    pass
                self.refresh_grid()
                return True
        except Exception as ex:
            logger.exception(f"load_icon failed: {ex}")
        return False

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
        def on_color_selected(hex_color):
            self.current_color = hex_color
            # Update active colour display if present
            if hasattr(self, 'color_preview') and self.color_preview:
                self.color_preview.bgcolor = hex_color
                self.color_preview.update()
            # Update hex input box if present
            if hasattr(self, 'hex_input') and self.hex_input:
                self.hex_input.value = hex_color
                self.hex_input.update()
            self.refresh_grid()
        picker = ColourPicker(current_color=self.current_color, saved_dir=self._ensure_saved_dir(), on_color_selected=on_color_selected)
        dialog = picker.build_dialog(page=page)
        # use dialog helper so parent (editor) is restored when picker closes
        self._open_dialog(dialog, page)

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
                pixels = None
                # If the cache file is JSON, try to extract metadata + pixels (or embedded png)
                if path.lower().endswith('.json'):
                    try:
                        with open(path, 'r', encoding='utf-8') as fh:
                            obj = json.load(fh)
                    except Exception:
                        obj = None
                    if isinstance(obj, dict):
                        # populate persistent metadata fields if present
                        try:
                            meta = obj.get('metadata', {}) or {}
                            if hasattr(self, 'meta_title_field'):
                                self.meta_title_field.value = meta.get('title', '') or ''
                                self.meta_author_field.value = meta.get('author', '') or ''
                                self.meta_tags_field.value = ', '.join(meta.get('tags', [])) if isinstance(meta.get('tags', []), list) else (meta.get('tags') or '')
                                self.meta_description_field.value = meta.get('description', '') or ''
                                self.meta_title_field.update()
                                self.meta_author_field.update()
                                self.meta_tags_field.update()
                                self.meta_description_field.update()
                        except Exception:
                            pass
                        if 'pixels' in obj and isinstance(obj['pixels'], list):
                            pixels = obj['pixels']
                        elif 'png_base64' in obj:
                            try:
                                import base64
                                import io
                                b = base64.b64decode(obj['png_base64'])
                                img = Image.open(io.BytesIO(b))
                                pixels = self._image_to_pixels(img)
                            except Exception:
                                pixels = None
                # fallback to generic loader (supports PNG etc.)
                if pixels is None:
                    pixels = load_icon_as_pixels(path, size=self.size)
                if not pixels or not isinstance(pixels, list):
                    raise RuntimeError('Loaded icon returned invalid pixel data')
                self._push_undo()
                self.pixels = pixels
                self.refresh_grid()
                # If there's metadata files in the caches, try to find matching metadata and populate export_text
                try:
                    pth = Path(path)
                    # check official cache metadata files
                    meta_found = None
                    yoto_meta = Path('.yoto_icon_cache') / 'icon_metadata.json'
                    user_meta = Path('.yoto_icon_cache') / 'user_icon_metadata.json'
                    metas = []
                    if yoto_meta.exists():
                        try:
                            metas += json.loads(yoto_meta.read_text(encoding='utf-8') or '[]')
                        except Exception:
                            pass
                    if user_meta.exists():
                        try:
                            metas += json.loads(user_meta.read_text(encoding='utf-8') or '[]')
                        except Exception:
                            pass
                    for m in metas:
                        cp = m.get('cache_path') or m.get('cachePath')
                        if cp and Path(cp).name == pth.name:
                            meta_found = m
                            break
                        url = m.get('url')
                        if url:
                            try:
                                h = hashlib.sha256(str(url).encode()).hexdigest()[:16]
                                if pth.stem.startswith(h):
                                    meta_found = m
                                    break
                            except Exception:
                                pass
                    # check yotoicons metadata files
                    if not meta_found:
                        yotoicons_dir = Path('.yotoicons_cache')
                        global_meta = yotoicons_dir / 'yotoicons_global_metadata.json'
                        metas2 = []
                        if global_meta.exists():
                            try:
                                metas2 += json.loads(global_meta.read_text(encoding='utf-8') or '[]')
                            except Exception:
                                pass
                        try:
                            for mf in yotoicons_dir.glob('*_metadata.json'):
                                if mf.name == global_meta.name:
                                    continue
                                try:
                                    metas2 += json.loads(mf.read_text(encoding='utf-8') or '[]')
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        for m in metas2:
                            cp = m.get('cache_path') or m.get('cachePath')
                            if cp and Path(cp).name == pth.name:
                                meta_found = m
                                break
                            img_url = m.get('img_url') or m.get('imgUrl')
                            if img_url:
                                try:
                                    h = hashlib.sha256(str(img_url).encode()).hexdigest()[:16]
                                    if pth.stem.startswith(h):
                                        meta_found = m
                                        break
                                except Exception:
                                    pass
                    if meta_found:
                        try:
                            meta = meta_found.get('metadata') or meta_found.get('meta') or meta_found or {}
                            if isinstance(meta, dict) and hasattr(self, 'meta_title_field'):
                                self.meta_title_field.value = meta.get('title', '') or ''
                                self.meta_author_field.value = meta.get('author', '') or ''
                                self.meta_tags_field.value = ', '.join(meta.get('tags', [])) if isinstance(meta.get('tags', []), list) else (meta.get('tags') or '')
                                self.meta_description_field.value = meta.get('description', '') or ''
                                self.meta_title_field.update()
                                self.meta_author_field.update()
                                self.meta_tags_field.update()
                                self.meta_description_field.update()
                        except Exception:
                            pass
                except Exception:
                    pass
                # close dialog
                try:
                    dlg.open = False
                except Exception:
                    pass
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
            self._open_dialog(dlg, page)

    def _close_dialog(self, dlg, page=None):
        """Close dlg and reopen any parent dialog that was hidden by _open_dialog."""
        page = page or getattr(self, 'page', None)
        try:
            try:
                dlg.open = False
            except Exception:
                # some wrappers store nested dialog under dlg.dialog
                try:
                    getattr(dlg, 'dialog').open = False
                except Exception:
                    pass
            if page:
                page.update()
            parent = getattr(dlg, '_parent_dialog', None)
            if not parent and hasattr(dlg, 'dialog'):
                parent = getattr(dlg, 'dialog', None)._parent_dialog if getattr(dlg, 'dialog', None) else None
            if parent and page:
                try:
                    page.open(parent)
                    page.update()
                except Exception:
                    pass
        except Exception:
            pass

    def make_pixel(self, x, y):
        def on_click(e):
            self._push_undo()
            self.pixels[y][x] = self.current_color
            # render transparent as no bgcolor (None)
            if self.current_color is None:
                try:
                    e.control.bgcolor = None
                except Exception:
                    # Some flet versions expect a string; fall back to explicit transparent rgba
                    e.control.bgcolor = "#00000000"
                # show checker image if available
                try:
                    chk = str(self._ensure_saved_dir() / '__checker.png')
                    e.control.content = ft.Image(src=chk, width=self.pixel_size - 4, height=self.pixel_size - 4, fit=ft.ImageFit.COVER)
                except Exception:
                    # fallback: no content
                    try:
                        e.control.content = None
                    except Exception:
                        pass
            else:
                e.control.bgcolor = self.current_color
                # remove checker content if present
                try:
                    e.control.content = None
                except Exception:
                    pass
            try:
                e.control.update()
            except Exception:
                pass

        # initialize cell appearance based on current pixels value
        val = self.pixels[y][x]
        cell_content = None
        display_bg = None
        if val is None:
            try:
                chk = str(self._ensure_saved_dir() / '__checker.png')
                cell_content = ft.Image(src=chk, width=self.pixel_size - 4, height=self.pixel_size - 4, fit=ft.ImageFit.COVER)
            except Exception:
                cell_content = None
            display_bg = None
        else:
            # If stored value includes alpha (#RRGGBBAA), composite over white for display
            try:
                r, g, b, a = self._hex_to_rgba(val, alpha=255)
                if a < 255:
                    r2 = int((r * a + 255 * (255 - a)) / 255)
                    g2 = int((g * a + 255 * (255 - a)) / 255)
                    b2 = int((b * a + 255 * (255 - a)) / 255)
                    display_bg = f"#{r2:02X}{g2:02X}{b2:02X}"
                else:
                    display_bg = f"#{r:02X}{g:02X}{b:02X}"
            except Exception:
                display_bg = val
        c = ft.Container(
            width=self.pixel_size,
            height=self.pixel_size,
            content=cell_content,
            bgcolor=display_bg,
            on_click=on_click
        )
        return c

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
        # Also clear persistent metadata fields (if present) and update UI
        try:
            if hasattr(self, 'meta_title_field'):
                self.meta_title_field.value = ""
                self.meta_title_field.update()
            if hasattr(self, 'meta_author_field'):
                self.meta_author_field.value = ""
                self.meta_author_field.update()
            if hasattr(self, 'meta_tags_field'):
                self.meta_tags_field.value = ""
                self.meta_tags_field.update()
            if hasattr(self, 'meta_description_field'):
                self.meta_description_field.value = ""
                self.meta_description_field.update()
        except Exception:
            pass

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
                val = self.pixels[y][x]
                try:
                    if val is None:
                        # transparent: show checker image
                        try:
                            chk = str(self._ensure_saved_dir() / '__checker.png')
                            cell.content = ft.Image(src=chk, width=self.pixel_size - 4, height=self.pixel_size - 4, fit=ft.ImageFit.COVER)
                        except Exception:
                            cell.content = None
                        try:
                            cell.bgcolor = None
                        except Exception:
                            cell.bgcolor = "#FFFFFF"
                    else:
                        # opaque or semi-transparent: remove checker and set bgcolor to composite over white if needed
                        try:
                            cell.content = None
                        except Exception:
                            pass
                        try:
                            r, g, b, a = self._hex_to_rgba(val, alpha=255)
                            if a < 255:
                                r2 = int((r * a + 255 * (255 - a)) / 255)
                                g2 = int((g * a + 255 * (255 - a)) / 255)
                                b2 = int((b * a + 255 * (255 - a)) / 255)
                                cell.bgcolor = f"#{r2:02X}{g2:02X}{b2:02X}"
                            else:
                                cell.bgcolor = f"#{r:02X}{g:02X}{b:02X}"
                        except Exception:
                            cell.bgcolor = val
                    cell.update()
                except Exception:
                    try:
                        cell.bgcolor = (None if self.pixels[y][x] is None else self.pixels[y][x])
                        cell.update()
                    except Exception:
                        pass

    # Helpers for saving/loading
    def _ensure_saved_dir(self):
        d = Path(ICON_DIR)
        d.mkdir(parents=True, exist_ok=True)
        # ensure checker preview exists
        try:
            chk = d / '__checker.png'
            if not chk.exists():
                from PIL import ImageDraw
                sq = 8
                im = Image.new('RGBA', (sq*2, sq*2), (255, 255, 255, 0))
                draw = ImageDraw.Draw(im)
                draw.rectangle([0,0,sq-1,sq-1], fill=(200,200,200,255))
                draw.rectangle([sq,sq,sq*2-1,sq*2-1], fill=(200,200,200,255))
                im.save(str(chk))
        except Exception:
            pass
        return d

    def _pixels_to_image(self, pixels):
        size = self.size
        img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
        for y in range(size):
            for x in range(size):
                hexc = pixels[y][x]
                if hexc is None:
                    # transparent
                    img.putpixel((x, y), (0, 0, 0, 0))
                elif isinstance(hexc, str):
                    # try to parse known formats: #RRGGBB, #RRGGBBAA, rgba(...)
                    try:
                        # use helper to parse many formats
                        r, g, b, a = self._hex_to_rgba(hexc, alpha=255)
                        img.putpixel((x, y), (r, g, b, a))
                    except Exception:
                        img.putpixel((x, y), (0, 0, 0, 0))
                else:
                    # unknown -> transparent
                    img.putpixel((x, y), (0, 0, 0, 0))
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
                if a == 0:
                    pixels[y][x] = None
                elif a == 255:
                    pixels[y][x] = f"#{r:02X}{g:02X}{b:02X}"
                else:
                    # preserve partial alpha as 8-digit hex #RRGGBBAA
                    pixels[y][x] = f"#{r:02X}{g:02X}{b:02X}{a:02X}"
        return pixels


    def _render_text_to_pixels(self, text, color, scale=1, x_offset=0, y_offset=0, font_name="5x7", compact=False):
        """Return a pixel grid (list of rows) with text stamped at given offset. Does not modify self.pixels."""
        # prepare a blank grid
        grid = [[None for _ in range(self.size)] for _ in range(self.size)]
        tx = x_offset
        ty = y_offset
        text = (text or '').upper()
        if font_name == "3x5":
            font = _font_3x5
            width = 3
        else:
            font = _font_5x7
            width = 5
        for ch in text:
            glyph = font.get(ch, font.get(' '))
            for row_idx, bits in enumerate(glyph):
                for bit_idx in range(width):
                    if bits & (1 << (width - 1 - bit_idx)):
                        for sy in range(scale):
                            for sx in range(scale):
                                gx = tx + bit_idx * scale + sx
                                gy = ty + row_idx * scale + sy
                                if 0 <= gx < self.size and 0 <= gy < self.size:
                                    grid[gy][gx] = color
            if compact:
                tx += width * scale
            else:
                tx += (width + 1) * scale  # 1px spacing
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
        # Quick position buttons
        def get_stamp_size():
            txt = (text_field.value or '').strip().upper()
            font_name = font_dropdown.value
            scale = int(scale_dropdown.value)
            compact = compact_checkbox.value
            if font_name == "3x5":
                width = 3
                height = 5
            else:
                width = 5
                height = 7
            n_chars = len(txt)
            if compact:
                stamp_w = n_chars * width * scale if n_chars > 0 else 0
            else:
                stamp_w = n_chars * (width + 1) * scale - scale if n_chars > 0 else 0
            stamp_h = height * scale
            return stamp_w, stamp_h

        def set_position(pos):
            grid_size = self.size
            stamp_w, stamp_h = get_stamp_size()
            if pos == "Top Left":
                x = 0
                y = 0
            elif pos == "Top Center":
                x = max((grid_size - stamp_w)//2, 0)
                y = 0
            elif pos == "Top Right":
                x = max(grid_size - stamp_w, 0)
                y = 0
            elif pos == "Middle Left":
                x = 0
                y = max((grid_size - stamp_h)//2, 0)
            elif pos == "Center":
                x = max((grid_size - stamp_w)//2, 0)
                y = max((grid_size - stamp_h)//2, 0)
            elif pos == "Middle Right":
                x = max(grid_size - stamp_w, 0)
                y = max((grid_size - stamp_h)//2, 0)
            elif pos == "Bottom Left":
                x = 0
                y = max(grid_size - stamp_h, 0)
            elif pos == "Bottom Center":
                x = max((grid_size - stamp_w)//2, 0)
                y = max(grid_size - stamp_h, 0)
            elif pos == "Bottom Right":
                x = max(grid_size - stamp_w, 0)
                y = max(grid_size - stamp_h, 0)
            else:
                x = 0
                y = 0
            pos_x.value = str(x)
            pos_y.value = str(y)
            pos_x.update()
            pos_y.update()
            update_preview()

        positions = [
            "Top Left", "Top Center", "Top Right",
            "Middle Left", "Center", "Middle Right",
            "Bottom Left", "Bottom Center", "Bottom Right"
        ]
        pos_buttons = ft.Row([
            ft.TextButton(label, on_click=lambda ev, label=label: set_position(label))
            for label in positions
        ], wrap=True, spacing=4)
        page = e.page if hasattr(e, 'page') else None
        text_field = ft.TextField(label="Text", value="A", width=200)
        color_field = ft.TextField(label="Color (hex)", value=self.current_color, width=120)
        compact_checkbox = ft.Checkbox(label="Compact", value=False, on_change=lambda ev: update_preview())
        def update_text_preview(ev=None):
            txt = (text_field.value or '').strip()
            col = (color_field.value or '').strip()
            sc = int(scale_dropdown.value)
            font_name = font_dropdown.value
            ox = int((pos_x.value or '0').strip())
            oy = int((pos_y.value or '0').strip())
            compact = compact_checkbox.value
            import tempfile
            # Preview 1: just the stamp
            if not txt:
                if preview_img.page:
                    preview_img.src = None
                    preview_img.update()
                if preview_applied_img.page:
                    preview_applied_img.src = None
                    preview_applied_img.update()
                return
            stamp = None
            try:
                stamp = self._render_text_to_pixels(txt, col, scale=sc, x_offset=ox, y_offset=oy, font_name=font_name, compact=compact)
                img = self._pixels_to_image(stamp)
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    img.save(tmp.name)
                    preview_img.src = tmp.name
                    preview_img.update()
            except Exception as ex:
                if preview_img.page:
                    preview_img.src = None
                    preview_img.update()
                status.value = f"Preview error: {ex}"
                status.update()
            # Preview 2: stamp applied to current image
            if stamp is not None:
                try:
                    import copy
                    applied_pixels = copy.deepcopy(self.pixels)
                    for y in range(self.size):
                        for x in range(self.size):
                            v = stamp[y][x]
                            if v is not None:
                                applied_pixels[y][x] = v
                    img2 = self._pixels_to_image(applied_pixels)
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp2:
                        img2.save(tmp2.name)
                        if preview_applied_img.page:
                            preview_applied_img.src = tmp2.name
                            preview_applied_img.update()
                except Exception as ex2:
                    if preview_applied_img.page:
                        preview_applied_img.src = None
                        preview_applied_img.update()
                    status.value = f"Applied preview error: {ex2}"
                    status.update()
        font_dropdown = ft.Dropdown(label="Font", options=[ft.dropdown.Option("5x7"), ft.dropdown.Option("3x5")], value="5x7", width=100, on_change=lambda ev: update_preview())
        scale_dropdown = ft.Dropdown(label="Scale", options=[ft.dropdown.Option(str(i)) for i in range(1,4)], value='1', width=100)
        pos_x = ft.TextField(label="X Offset", value="0", width=80)
        pos_y = ft.TextField(label="Y Offset", value="0", width=80)
        status = ft.Text("")
        preview_img = ft.Image(width=64, height=64, fit=ft.ImageFit.CONTAIN)
        preview_applied_img = ft.Image(width=64, height=64, fit=ft.ImageFit.CONTAIN)

        def on_color_selected(hex_color):
            color_field.value = hex_color
            color_field.update()
            if hasattr(self, 'color_preview') and self.color_preview:
                self.color_preview.bgcolor = hex_color
                self.color_preview.update()
            update_preview()
            ## Reopen the text dialog (dlg) after the picker finishes
            #if page:
            #    try:
            #        self._open_dialog(dlg, page)
            #    except Exception:
            #        pass

        def update_image_preview(ev=None):
            txt = (text_field.value or '').strip()
            col = (color_field.value or '').strip()
            sc = int(scale_dropdown.value)
            font_name = font_dropdown.value
            ox = int((pos_x.value or '0').strip())
            oy = int((pos_y.value or '0').strip())
            compact = compact_checkbox.value
            import tempfile
            # Preview 1: just the stamp
            if not txt:
                if preview_img.page:
                    preview_img.src = None
                    preview_img.update()
                if preview_applied_img.page:
                    preview_applied_img.src = None
                    preview_applied_img.update()
                return
            stamp = None
            try:
                stamp = self._render_text_to_pixels(txt, col, scale=sc, x_offset=ox, y_offset=oy, font_name=font_name, compact=compact)
                img = self._pixels_to_image(stamp)
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    img.save(tmp.name)
                    preview_img.src = tmp.name
                    preview_img.update()
            except Exception as ex:
                if preview_img.page:
                    preview_img.src = None
                    preview_img.update()
                status.value = f"Preview error: {ex}"
                status.update()
            # Preview 2: stamp applied to current image
            if stamp is not None:
                try:
                    import copy
                    applied_pixels = copy.deepcopy(self.pixels)
                    for y in range(self.size):
                        for x in range(self.size):
                            v = stamp[y][x]
                            if v is not None:
                                applied_pixels[y][x] = v
                    img2 = self._pixels_to_image(applied_pixels)
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp2:
                        img2.save(tmp2.name)
                        if preview_applied_img.page:
                            preview_applied_img.src = tmp2.name
                            preview_applied_img.update()
                except Exception as ex2:
                    if preview_applied_img.page:
                        preview_applied_img.src = None
                        preview_applied_img.update()
                    status.value = f"Applied preview error: {ex2}"
                    status.update()
        # Provide a unified name expected by callbacks
        update_preview = update_text_preview

        # Attach update_preview to all relevant fields
        text_field.on_change = update_preview
        color_field.on_change = update_preview
        scale_dropdown.on_change = update_preview
        pos_x.on_change = update_preview
        pos_y.on_change = update_preview

        def open_picker(ev):
            logger.debug("Opening colour picker from text dialog")
            page = ev.page if hasattr(ev, 'page') else None
            picker = ColourPicker(current_color=color_field.value, saved_dir=self._ensure_saved_dir(), on_color_selected=on_color_selected)
            dialog = picker.build_dialog(page=page, caller_page_dialog=page.dialog if page else None)
            if page:
                # open colour picker as child dialog of the text dialog
                self._open_dialog(dialog, page)
                page.update()

        picker_btn = ft.TextButton("Pick Color", on_click=open_picker)

        def do_stamp(ev):
            try:
                txt = (text_field.value or '').strip()
                col = (color_field.value or '').strip()
                sc = int(scale_dropdown.value)
                font_name = font_dropdown.value
                ox = int((pos_x.value or '0').strip())
                oy = int((pos_y.value or '0').strip())
                compact = compact_checkbox.value
                if not txt:
                    status.value = "Enter text"
                    status.update()
                    return
                # render and stamp
                stamp = self._render_text_to_pixels(txt, col, scale=sc, x_offset=ox, y_offset=oy, font_name=font_name, compact=compact)
                self._stamp_pixels(stamp)
                try:
                    self._close_dialog(dlg, page)
                except Exception:
                    pass
            except Exception as ex:
                status.value = f"Error: {ex}"
                status.update()

        content = ft.Column([
            text_field,
            ft.Row([color_field, picker_btn, font_dropdown, scale_dropdown, pos_x, pos_y], wrap=True),
            compact_checkbox,
            pos_buttons,
            ft.Row([
                ft.Column([ft.Text("Stamp Preview"), preview_img]),
                ft.Column([ft.Text("Applied Preview"), preview_applied_img])
            ]),
            status
        ], spacing=8, width=350)
        dlg = ft.AlertDialog(title=ft.Text("Stamp Text"), content=content, actions=[ft.TextButton("Stamp", on_click=do_stamp), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))], open=False)
        if page:
            page.dialog = dlg  # keep a reference
            logger.debug(f"Opening text dialog, page={page}")
            self._open_dialog(dlg, page)
            update_preview()  # Show previews immediately after dialog is open

    def on_save_png(self, e):
        page = e.page if hasattr(e, 'page') else None
        saved_dir = self._ensure_saved_dir()
        if not saved_dir:
            if page:
                page.snack_bar = ft.SnackBar(ft.Text("Failed to create saved_icons folder"))
                page.snack_bar.open = True
                page.update()
            return

        # Use persistent metadata fields; dialog only asks for filename / png option
        name_field = ft.TextField(label="Filename (no extension)")
        save_png_checkbox = ft.Checkbox(label="Also save PNG file", value=False)
        status = ft.Text("")

        def do_save(ev):
            fn = (name_field.value or '').strip()
            if not fn:
                status.value = "Enter a filename"
                status.update()
                return
            # collect metadata
            # read from persistent metadata fields (visible/editable on main UI)
            meta = {
                "title": (getattr(self, 'meta_title_field', ft.TextField(value='')).value or '').strip(),
                "author": (getattr(self, 'meta_author_field', ft.TextField(value='')).value or '').strip(),
                "tags": [t.strip() for t in ((getattr(self, 'meta_tags_field', ft.TextField(value='')).value or '')).split(',') if t.strip()],
                "description": (getattr(self, 'meta_description_field', ft.TextField(value='')).value or '').strip(),
                "created_by": "yoto-up",
            }

            basename = fn + '.json'
            path = os.path.join(str(saved_dir), basename) if hasattr(saved_dir, 'joinpath') else os.path.join(saved_dir, basename)

            # actual save operation extracted so overwrite confirm can call it
            def _perform_save():
                logger.debug(f"Saving icon to {path}")
                # build image and base64 PNG
                img = self._pixels_to_image(self.pixels)
                import io
                import base64
                import json as _json
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
                    _json.dump(obj, fh, ensure_ascii=False, indent=2)

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
                self._close_dialog(dlg, page)

            # If target exists, ask for overwrite confirmation using a dialog
            if os.path.exists(path):
                def do_overwrite_confirm(ev2):
                    logger.debug("User confirmed overwrite")
                    # user confirmed overwrite: proceed with actual write
                    try:
                        _perform_save()
                        self._close_dialog(overwrite_dlg, page)
                    except Exception as ex:
                        logger.exception(f"Error during save overwrite: {ex}")
                        status.value = f"Save failed: {ex}"
                        status.update()

                def do_cancel_overwrite(ev2):
                    logger.debug("User cancelled overwrite")
                    #overwrite_dlg.open = False
                    self._close_dialog(overwrite_dlg, page)

                overwrite_dlg = ft.AlertDialog(
                    title=ft.Text("File exists"),
                    content=ft.Text(f"'{basename}' already exists. Overwrite?"),
                    actions=[
                        ft.TextButton("Yes, overwrite", on_click=do_overwrite_confirm),
                        ft.TextButton("Cancel", on_click=do_cancel_overwrite),
                    ],
                )
                self._open_dialog(overwrite_dlg, page)
                return

            # If file did not exist, perform save immediately
            try:
                _perform_save()
            except Exception as ex:
                status.value = f"Save failed: {ex}"
                status.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Save Icon (JSON + metadata)"),
            content=ft.Column([name_field, save_png_checkbox, status], spacing=8),
            actions=[ft.TextButton("Save", on_click=do_save), ft.TextButton("Cancel", on_click=lambda ev: self._close_dialog(dlg, page))]
        )
        if page:
            self._open_dialog(dlg, page)

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
                        # populate persistent metadata fields so user can edit metadata immediately
                        try:
                            meta = obj.get('metadata', {}) or {}
                            if hasattr(self, 'meta_title_field'):
                                self.meta_title_field.value = meta.get('title', '') or ''
                                self.meta_author_field.value = meta.get('author', '') or ''
                                self.meta_tags_field.value = ', '.join(meta.get('tags', [])) if isinstance(meta.get('tags', []), list) else (meta.get('tags') or '')
                                self.meta_description_field.value = meta.get('description', '') or ''
                                self.meta_title_field.update()
                                self.meta_author_field.update()
                                self.meta_tags_field.update()
                                self.meta_description_field.update()
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
            self._open_dialog(dlg, page)

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

    # Tab helpers: allow embedding the editor as a normal tab in the app's Tabs view.
    def as_tab(self, title: str = "Icon Editor"):
        """Return an ft.Tab that hosts this editor's container. Call once and reuse the tab."""
        try:
            if getattr(self, "_tab", None):
                return self._tab
            # Wrap editor.container in a Column to ensure it expands properly inside tab content
            content = ft.Column([self.container], scroll=ft.ScrollMode.AUTO, expand=True)
            tab = ft.Tab(text=title, content=content)
            self._tab = tab
            return tab
        except Exception:
            logger.exception("Failed to create editor tab")
            # fallback: return a plain container wrapped as a Tab-like object
            try:
                tab = ft.Tab(text=title, content=self.container)
                self._tab = tab
                return tab
            except Exception:
                return None

    def attach_to_tabview(self, tabview: ft.Tabs, select: bool = True, page: ft.Page = None):
        """Attach the editor as a new tab to an existing ft.Tabs (tabview).
        If select=True the new tab will be selected. Pass page to trigger update.
        Returns the appended ft.Tab or None on failure.
        """
        try:
            if tabview is None:
                return None
            tab = getattr(self, "_tab", None) or self.as_tab()
            if tab is None:
                return None
            # Avoid duplicates: if the same tab already present, just select it
            for idx, t in enumerate(tabview.tabs):
                if t is tab:
                    if select:
                        tabview.selected_index = idx
                    if page:
                        page.update()
                    return tab
            tabview.tabs.append(tab)
            if select:
                tabview.selected_index = len(tabview.tabs) - 1
            # remember the page if provided for later dialog helpers
            if page:
                self.page = page
                try:
                    page.update()
                except Exception:
                    pass
            return tab
        except Exception:
            logger.exception("Failed to attach editor to tabview")
            return None
#
# ...existing code...
    class _SmallDialog:
        def __init__(self, title, content, page=None):
            self.dialog = ft.AlertDialog(title=ft.Text(title), content=content, actions=[], open=False)
            self.page = page
            self._parent_dialog = None
        def open(self):
            if self.page:
                # remember parent and hide it while this dialog is active
                try:
                    parent = getattr(self.page, 'dialog', None)
                    if parent:
                        self._parent_dialog = parent
                        try:
                            parent.open = False
                        except Exception:
                            pass
                except Exception:
                    self._parent_dialog = None
                try:
                    self.page.open(self.dialog)
                    self.page.update()
                except Exception:
                    pass
            else:
                self.dialog.open = True
        def close(self):
            try:
                if self.page:
                    try:
                        self.dialog.open = False
                        self.page.update()
                    except Exception:
                        pass
                else:
                    self.dialog.open = False
                # reopen parent if we hidden one
                if getattr(self, '_parent_dialog', None) and self.page:
                    try:
                        self.page.open(self._parent_dialog)
                        self.page.update()
                    except Exception:
                        pass
            except Exception:
                pass

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
            try:
                dlg.close()
            except Exception:
                pass
        content = ft.Column([target_field, replacement_field, status])
        dlg = self._SmallDialog("Replace Color", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Replace", on_click=do_replace), ft.TextButton("Cancel", on_click=lambda ev: dlg.close())]
        if page:
            dlg.open()

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
            try:
                dlg.close()
            except Exception:
                pass
        content = ft.Column([color_field, status])
        dlg = self._SmallDialog("Gradient Overlay", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: dlg.close())]
        if page:
            dlg.open()

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
            try:
                dlg.close()
            except Exception:
                pass
        content = ft.Column([degrees_field, status])
        dlg = self._SmallDialog("Adjust Hue", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: dlg.close())]
        if page:
            dlg.open()

    def _open_opacity_dialog(self, e):
        page = e.page if hasattr(e, 'page') else None
        opacity_field = ft.TextField(label="Opacity (0.0-1.0)", value="0.5", width=140)
        status = ft.Text("")
        def do_apply(ev):
            try:
                op = float((opacity_field.value or '').strip())
            except Exception:
                status.value = "Enter a float between 0.0 and  1.0"
                status.update()
                return
            if op < 0 or op > 1:
                status.value = "Opacity must be between 0.0 and 1.0"
                status.update()
                return
            self.on_adjust_opacity(ev, op)
            try:
                dlg.close()
            except Exception:
                pass
        content = ft.Column([opacity_field, status])
        dlg = self._SmallDialog("Adjust Opacity", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: dlg.close())]
        if page:
            dlg.open()

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
            try:
                dlg.close()
            except Exception:
                pass
        content = ft.Column([size_field, status])
        dlg = self._SmallDialog("Pixelate", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: dlg.close())]
        if page:
            dlg.open()

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
            try:
                dlg.close()
            except Exception:
                pass
        content = ft.Column([count_field, status])
        dlg = self._SmallDialog("Quantize Colors", content, page=page)
        dlg.dialog.actions = [ft.TextButton("Apply", on_click=do_apply), ft.TextButton("Cancel", on_click=lambda ev: dlg.close())]
        if page:
            dlg.open()

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
