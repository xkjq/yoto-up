import flet as ft
import os
import math
import colorsys
from PIL import Image
from loguru import logger

class ColourPicker:
    def __init__(self, current_color='#000000', wheel_size=280, saved_dir=None):
        self.current_color = current_color
        self.wheel_size = wheel_size
        self.saved_dir = saved_dir or '.'
        self.color_picker_dialog = None

    def hex_to_rgb(self, h):
        h = h.lstrip('#')
        if len(h) == 3:
            h = ''.join([c*2 for c in h])
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(self, r, g, b):
        return f"#{r:02X}{g:02X}{b:02X}"

    def _make_color_wheel_image(self, val):
        try:
            path = os.path.join(str(self.saved_dir), '__color_wheel.png')
            size = self.wheel_size
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            cx = cy = size / 2.0
            radius = size / 2.0
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
        except Exception as ex:
            logger.error(f"color wheel generation error: {ex}")
            return None
        try:
            with open(path, 'wb') as f:
                img.save(f, format='PNG')
                f.flush()
            logger.debug(f"color wheel PNG save succeeded: {path}")
            return path
        except Exception as ex:
            logger.error(f"color wheel PNG save error: {ex}")
            return None

    def hsv_to_hex(self, h, s, v):
        try:
            r, g, b = colorsys.hsv_to_rgb(h/360.0, float(s), float(v))
            return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
        except Exception:
            return '#000000'

    def build_dialog(self, page=None):
        r, g, b = self.hex_to_rgb(self.current_color)
        r_slider = ft.Slider(min=0, max=255, value=r, label="Red", divisions=255, on_change=None)
        g_slider = ft.Slider(min=0, max=255, value=g, label="Green", divisions=255, on_change=None)
        b_slider = ft.Slider(min=0, max=255, value=b, label="Blue", divisions=255, on_change=None)
        hex_field = ft.TextField(label="Hex", value=self.current_color, width=100)
        preview = ft.Container(width=48, height=48, bgcolor=self.current_color, border_radius=6, border=ft.border.all(1, "#888888"))
        value_slider = ft.Slider(min=0.0, max=1.0, value=1, divisions=100, label="Value (Brightness)", on_change=None)
        wheel_img = ft.Image(width=self.wheel_size, height=self.wheel_size)
        hue_slider = ft.Slider(min=0, max=360, value=0, divisions=360, label="Hue (0-360°)", on_change=None)
        sat_slider = ft.Slider(min=0.0, max=1.0, value=1.0, divisions=100, label="Saturation (0-1)", on_change=None)

        def on_value_change(ev):
            v = float(value_slider.value)
            p = self._make_color_wheel_image(v)
            if p:
                wheel_img.src = p
                wheel_img.update()
            try:
                if self.color_picker_dialog:
                    self.color_picker_dialog.update()
            except Exception:
                logger.debug("color wheel dialog update failed")
            try:
                if page:
                    page.update()
            except Exception:
                logger.debug("page update failed")

        def on_hsv_change(ev=None):
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
            try:
                if page:
                    page.update()
            except Exception:
                pass

        value_slider.on_change = on_value_change
        hue_slider.on_change = on_hsv_change
        sat_slider.on_change = on_hsv_change

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

        r_slider.on_change = on_slider_change
        g_slider.on_change = on_slider_change
        b_slider.on_change = on_slider_change
        hex_field.on_change = on_hex_change

        content = ft.Column([
            ft.Row([preview, hex_field, ft.Column([wheel_img, ft.Row([ft.Text("Value (Brightness)", width=120), value_slider])])]),
            ft.Row([ft.Text("Red", width=120), r_slider]),
            ft.Row([ft.Text("Green", width=120), g_slider]),
            ft.Row([ft.Text("Blue", width=120), b_slider]),
            ft.Row([ft.Text("Hue (0-360°)", width=120), hue_slider]),
            ft.Row([ft.Text("Saturation (0-1)", width=120), sat_slider]),
        ], spacing=10, width=self.wheel_size + 150)
        self.color_picker_dialog = ft.AlertDialog(
            title=ft.Text("Advanced Color Picker"),
            content=content,
            actions=[ft.TextButton("Close", on_click=lambda ev: self.close_dialog(page))],
            open=True
        )
        return self.color_picker_dialog

    def close_dialog(self, page=None):
        if self.color_picker_dialog:
            self.color_picker_dialog.open = False
        if page:
            page.update()
