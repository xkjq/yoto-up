import flet as ft
import os
import math
import colorsys
from PIL import Image
from loguru import logger
import uuid
import threading
from pathlib import Path

from .icon_import_helpers import get_base64_from_path

class ColourPicker:
    def __init__(self, current_color='#000000', wheel_size=280, saved_dir=None, on_color_selected=None, loading_dialog=None):
        self.current_color = current_color
        self.wheel_size = wheel_size
        self.saved_dir = saved_dir or '.'
        self.color_picker_dialog = None
        self.on_color_selected = on_color_selected
        self._temp_wheel_files = set()
        self.loading_dialog = loading_dialog


    def hex_to_rgb(self, h):
        h = h.lstrip('#')
        if len(h) == 3:
            h = ''.join([c*2 for c in h])
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(self, r, g, b):
        return f"#{r:02X}{g:02X}{b:02X}"

    def _make_color_wheel_image(self, val):
        try:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            path = tmp.name
            tmp.close()
            size = self.wheel_size
            cx = cy = size / 2.0
            radius = size / 2.0
            try:
                import numpy as np
                yy, xx = np.mgrid[0:size, 0:size]
                dx = xx - cx
                dy = yy - cy
                r = np.hypot(dx, dy)
                angle = np.arctan2(dy, dx)
                hue = (angle / (2 * np.pi)) % 1.0
                sat = np.clip(r / radius, 0, 1)
                mask = r <= radius
                v = float(val)
                hsv = np.stack([hue, sat, np.full_like(hue, v)], axis=-1)
                rgb = np.zeros_like(hsv)
                for i in range(size):
                    for j in range(size):
                        if mask[i, j]:
                            rgb[i, j, :3] = colorsys.hsv_to_rgb(hsv[i, j, 0], hsv[i, j, 1], hsv[i, j, 2])
                arr = np.zeros((size, size, 4), dtype=np.uint8)
                arr[..., 0] = (rgb[..., 0] * 255).astype(np.uint8)
                arr[..., 1] = (rgb[..., 1] * 255).astype(np.uint8)
                arr[..., 2] = (rgb[..., 2] * 255).astype(np.uint8)
                arr[..., 3] = (mask * 255).astype(np.uint8)
                img = Image.fromarray(arr, 'RGBA')
            except ImportError:
                img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                for y in range(size):
                    for x in range(size):
                        dx = x - cx
                        dy = y - cy
                        r = math.hypot(dx, dy)
                        if r <= radius:
                            angle = math.atan2(dy, dx)
                            hue = (angle / (2 * math.pi)) % 1.0
                            sat = min(1.0, r / radius)
                            rgb = colorsys.hsv_to_rgb(hue, sat, float(val))
                            img.putpixel((x, y), (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255), 255))
                        else:
                            img.putpixel((x, y), (0, 0, 0, 0))
            img.save(path, format='PNG')
            self._temp_wheel_files.add(path)
            return path
        except Exception as ex:
            return None

    def hsv_to_hex(self, h, s, v):
        try:
            r, g, b = colorsys.hsv_to_rgb(h/360.0, float(s), float(v))
            return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
        except Exception:
            return '#000000'

    def build_dialog(self, page=None, caller_page_dialog=None):
        ## remember which page opened the picker so close_dialog can reopen caller dialogs
        self._caller_page = page
        self.caller_page_dialog = caller_page_dialog
        #logger.debug("Building colour picker dialog")
        #logger.debug(f"Caller page: {self._caller_page}")
        #logger.debug(f"Caller page dialog: {self._caller_page_dialog}")
        r, g, b = self.hex_to_rgb(self.current_color)
        r_slider = ft.Slider(min=0, max=255, value=r, label="Red", divisions=255, on_change=None)
        g_slider = ft.Slider(min=0, max=255, value=g, label="Green", divisions=255, on_change=None)
        b_slider = ft.Slider(min=0, max=255, value=b, label="Blue", divisions=255, on_change=None)
        hex_field = ft.TextField(label="Hex", value=self.current_color, width=100)
        preview = ft.Container(width=48, height=48, bgcolor=self.current_color, border_radius=6, border=ft.border.all(1, "#888888"))
        value_slider = ft.Slider(min=0.0, max=1.0, value=1, divisions=100, label="Value (Brightness)", on_change=None)
        # Generate initial wheel image and set src
        initial_wheel_path = self._make_color_wheel_image(value_slider.value)
        wheel_img = ft.Image(src_base64=get_base64_from_path(Path(initial_wheel_path)), width=self.wheel_size, height=self.wheel_size)
        # Debounce timer for HSV changes
        self._debounce_timer = None

        def debounce_value_change(ev=None, delay=0.2):
            if self._debounce_timer:
                self._debounce_timer.cancel()
            def run():
                on_value_change(ev)
            self._debounce_timer = threading.Timer(delay, run)
            self._debounce_timer.start()
        def debounce_wheel_gesture(ev, delay=0.2):

            if self._debounce_timer:
                self._debounce_timer.cancel()
            def run():
                x = getattr(ev, 'local_x', None)
                y = getattr(ev, 'local_y', None)
                logger.debug(f"Wheel gesture at: local_x={x}, local_y={y}")
                if x is None or y is None:
                    return
                size = self.wheel_size
                cx = cy = size / 2.0
                dx = x - cx
                dy = y - cy
                r = math.hypot(dx, dy)
                radius = size / 2.0
                if r > radius:
                    logger.debug("Gesture outside wheel")
                    return
                angle = math.atan2(dy, dx)
                hue = (angle / (2 * math.pi)) % 1.0
                sat = min(1.0, r / radius)
                hue_slider.value = int(hue * 360)
                sat_slider.value = sat
                hue_slider.update()
                sat_slider.update()
                # Only update preview, not wheel image
                h = float(hue_slider.value)
                s = float(sat_slider.value)
                v = float(value_slider.value)
                hexv = self.hsv_to_hex(h, s, v)
                try:
                    r_val, g_val, b_val = self.hex_to_rgb(hexv)
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
                if self.on_color_selected:
                    self.on_color_selected(hexv)
                try:
                    if page:
                        page.update()
                except Exception:
                    logger.error("debounce_wheel_gesture: unexpected error")
                    pass
            self._debounce_timer = threading.Timer(delay, run)
            self._debounce_timer.start()

        wheel_gesture = ft.GestureDetector(
            content=wheel_img,
            on_tap_down=debounce_wheel_gesture,
            on_pan_update=debounce_wheel_gesture
        )
        #wheel_container = ft.Container(content=wheel_img, width=self.wheel_size, height=self.wheel_size, on_tap=on_wheel_tap)

        def on_wheel_click(ev):
            # Get click position relative to wheel center
            if not ev.local_x or not ev.local_y:
                return
            x = ev.local_x
            y = ev.local_y
            size = self.wheel_size
            cx = cy = size / 2.0
            dx = x - cx
            dy = y - cy
            r = math.hypot(dx, dy)
            radius = size / 2.0
            if r > radius:
                return  # Click outside wheel
            angle = math.atan2(dy, dx)
            hue = (angle / (2 * math.pi)) % 1.0
            sat = min(1.0, r / radius)
            v = float(value_slider.value)
            # Update sliders and preview
            hue_slider.value = int(hue * 360)
            sat_slider.value = sat
            hue_slider.update()
            sat_slider.update()
            on_hsv_change()
            if page:
                page.update()

        wheel_img.on_click = on_wheel_click
        hue_slider = ft.Slider(min=0, max=360, value=0, divisions=360, label="Hue (0-360°)", on_change=None)
        sat_slider = ft.Slider(min=0.0, max=1.0, value=1.0, divisions=100, label="Saturation (0-1)", on_change=None)

        # Remove on_value_change, use on_hsv_change for all HSV slider updates

        def on_value_change(ev=None):
            h = float(hue_slider.value)
            s = float(sat_slider.value)
            v = float(value_slider.value)
            hexv = self.hsv_to_hex(h, s, v)
            try:
                r_val, g_val, b_val = self.hex_to_rgb(hexv)
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
            if self.on_color_selected:
                self.on_color_selected(hexv)
            # Regenerate and update wheel image on any HSV change
            p = self._make_color_wheel_image(v)
            if p and os.path.exists(p):
                wheel_img.src = p
                wheel_img.update()
            else:
                wheel_img.src = None
                wheel_img.update()
            try:
                if page:
                    page.update()
            except Exception:
                logger.error("on_hsv_change: unexpected error")
                pass

        value_slider.on_change = debounce_value_change
        hue_slider.on_change = debounce_value_change
        sat_slider.on_change = debounce_value_change

        def update_all(ev=None):
            r_val = int(r_slider.value)
            g_val = int(g_slider.value)
            b_val = int(b_slider.value)
            hex_val = self.rgb_to_hex(r_val, g_val, b_val)
            hex_field.value = hex_val
            preview.bgcolor = hex_val
            hex_field.update()
            preview.update()
            self.current_color = hex_val
            if self.on_color_selected:
                self.on_color_selected(hex_val)
            if page:
                page.update()

        def on_slider_change(ev):
            update_all()

        def on_hex_change(ev):
            val = (hex_field.value or '').strip()
            if val.startswith('#') and (len(val) == 7 or len(val) == 4):
                try:
                    r_val, g_val, b_val = self.hex_to_rgb(val)
                    r_slider.value = r_val
                    g_slider.value = g_val
                    b_slider.value = b_val
                    r_slider.update()
                    g_slider.update()
                    b_slider.update()
                    update_all()
                except Exception:
                    pass
        def choose_action(ev=None):
            if self.on_color_selected:
                self.on_color_selected(self.current_color)
            self.close_dialog(page)

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
        ], spacing=10, width=self.wheel_size + 250)
        self.color_picker_dialog = ft.AlertDialog(
            title=ft.Text("Advanced Color Picker"),
            content=content,
            actions=[ft.TextButton("Close", on_click=lambda ev: self.close_dialog(page)),
                     ft.TextButton("Choose", on_click=choose_action)],
            open=True
        )
        return self.color_picker_dialog

    def close_dialog(self, page=None):
        # Clean up temp wheel images
        logger.debug("Closing picker dialog")
        for f in getattr(self, '_temp_wheel_files', []):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        self._temp_wheel_files.clear()
        

        # Reopen caller dialog (e.g. stamp dialog) if provided and a page is available
        if page and getattr(self, 'caller_page_dialog', None):
            logger.debug("Reopening caller dialog")
            page.dialog = self.caller_page_dialog
            page.open(page.dialog)
            self.caller_page_dialog = None
        else:
            self.color_picker_dialog.open = False
        page.update()
