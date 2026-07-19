import flet as ft
from loguru import logger
from flet_color_pickers import ColorPicker

class ColourPicker:
    def __init__(
        self,
        current_color='#000000',
        wheel_size=280,
        saved_dir=None,
        on_color_selected=None,
        loading_dialog=None
    ):
        # Ensure the color string starts with '#'
        color_str = current_color or '#000000'
        if not color_str.startswith('#'):
            color_str = f"#{color_str}"
        self.current_color = color_str
        self.wheel_size = wheel_size
        self.saved_dir = saved_dir or '.'
        self.color_picker_dialog = None
        self.on_color_selected = on_color_selected
        self.loading_dialog = loading_dialog
        self._caller_page = None
        self.caller_page_dialog = None

    def build_dialog(self, page=None, caller_page_dialog=None):
        self._caller_page = page
        self.caller_page_dialog = caller_page_dialog

        def handle_color_change(e):
            self.current_color = e.data
            if self.on_color_selected:
                try:
                    self.on_color_selected(self.current_color)
                except Exception as ex:
                    logger.error(f"Error in on_color_selected callback: {ex}")

        picker = ColorPicker(
            color=self.current_color,
            on_color_change=handle_color_change,
            width=280,
        )

        def choose_action(ev=None):
            if self.on_color_selected:
                try:
                    self.on_color_selected(self.current_color)
                except Exception as ex:
                    logger.error(f"Error in on_color_selected callback: {ex}")
            self.close_dialog(page)

        self.color_picker_dialog = ft.AlertDialog(
            title=ft.Text("Choose Color"),
            content=ft.Container(
                content=picker,
                padding=10,
                width=300,
                height=450,
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda ev: self.close_dialog(page)),
                ft.TextButton("Choose", on_click=choose_action)
            ],
            open=True
        )
        return self.color_picker_dialog

    def close_dialog(self, page=None):
        logger.debug("Closing picker dialog")
        if page and getattr(self, 'caller_page_dialog', None):
            logger.debug("Reopening caller dialog")
            page.dialog = self.caller_page_dialog
            page.show_dialog(page.dialog)
            self.caller_page_dialog = None
        else:
            if page:
                page.pop_dialog()
        if page:
            page.update()
