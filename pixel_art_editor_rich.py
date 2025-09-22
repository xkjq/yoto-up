from textual.app import App, ComposeResult
from textual.widgets import Static, Button, Input
from textual.containers import Grid, Horizontal, Vertical
from textual.reactive import reactive

class Pixel(Static):
    def __init__(self, x: int, y: int, **kwargs):
        super().__init__(**kwargs)
        self.x = x
        self.y = y
        self.color = "#000000"
        # render a single block character; we'll change its foreground color on click
        self.update("█")
        self.styles.color = self.color

    def on_click(self, event) -> None:
        """Handle a click on this pixel only."""
        try:
            event.stop()
        except Exception:
            pass
        self.color = self.app.selected_color
        self.styles.color = self.color
        # Debug print to help confirm only this pixel was clicked
        print(f"Pixel clicked: {self.id} ({self.x},{self.y}) -> {self.app.selected_color}")

class PixelArtEditor(App):
    selected_color = reactive("#000000")

    def compose(self) -> ComposeResult:
        # Quick colors and detailed picker moved to the top
        yield Static("Quick Colors:", id="quick_colors_label")
        yield Horizontal(id="quick_colors_grid")
        yield Button("Expand Picker", id="expand_picker_button")
        yield Static("Detailed Color Picker:", id="detailed_color_label")
        yield Grid(id="detailed_color_picker")

        # Canvas and exit controls
        yield Static("Press 'q' to exit", id="exit_hint")
        yield Vertical(id="pixel_grid")
        yield Button("Exit", id="exit_button")  # Adding an Exit button

    def on_mount(self) -> None:
        container = self.query_one("#pixel_grid", Vertical)
        # Build 16 horizontal rows, each containing 16 pixels
        for y in range(16):
            row = Horizontal()
            # Mount the row before adding child pixels
            container.mount(row)
            for x in range(16):
                p = Pixel(x, y, id=f"pixel_{x}_{y}")
                p.styles.min_width = 1
                p.styles.min_height = 1
                row.mount(p)

        quick_colors_grid = self.query_one("#quick_colors_grid", Horizontal)
        # The quick colors container is now a Horizontal container
        quick_colors_grid.styles.height = "auto"
        quick_colors_grid.styles.width = "100%"
        quick_colors_grid.styles.gap = 1  # Changed from "1" to 1
        quick_colors_grid.styles.padding = 1  # Changed from "1" to 1
        quick_colors_grid.styles.align_self = "end"  # Align the quick color grid to the right side of the screen
        quick_colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF", "#000000", "#FFFFFF"]
        for color in quick_colors:
            sanitized_color = color.replace("#", "hex_")
            button_id = f"quick_color_{sanitized_color}"
            print("Mounting quick color button:", button_id, color)
            quick_colors_grid.mount(Button(id=button_id, label=" "))
            quick_colors_grid.query_one(f"#quick_color_{sanitized_color}").styles.background = color

        detailed_color_picker = self.query_one("#detailed_color_picker", Grid)
        detailed_color_picker.styles.display = "none"  # Initially hidden
        # Add a range of colors to the detailed picker
        for r in range(0, 256, 51):
            for g in range(0, 256, 51):
                for b in range(0, 256, 51):
                    color = f"#{r:02X}{g:02X}{b:02X}"
                    sanitized_color = color.replace("#", "_")  # Replace '#' with '_'
                    detailed_color_picker.mount(Button(id=f"color_{sanitized_color}", label=" "))
                    detailed_color_picker.query_one(f"#color_{sanitized_color}").styles.background = color

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Debug: log which button was pressed
        try:
            print(f"Global handler: button pressed id={event.button.id}")
        except Exception:
            print("Global handler: button pressed (no id)")
        # Non-pixel handlers
        if event.button.id == "set_color":
            color_input = self.query_one("#color_input", Input)
            color = color_input.value.strip()
            if len(color) == 7 and color.startswith("#"):
                self.selected_color = color
            else:
                self.query_one("#color_input", Input).value = "Invalid color! Use #RRGGBB"
            return

        if event.button.id == "exit_button":
            self.exit()
            return

        if event.button.id == "expand_picker_button":
            detailed_color_picker = self.query_one("#detailed_color_picker", Grid)
            if detailed_color_picker.styles.display == "none":
                detailed_color_picker.styles.display = "block"
                event.button.label = "Collapse Picker"
            else:
                detailed_color_picker.styles.display = "none"
                event.button.label = "Expand Picker"
            return

        # Handle quick color buttons
        if event.button.id and event.button.id.startswith("quick_color_"):
            # quick color ids are like quick_color_hex_FF0000
            sanitized_color = event.button.id.replace("quick_color_hex_", "#")
            self.selected_color = sanitized_color
            print(f"Selected color set to {self.selected_color} from quick color")
            try:
                event.stop()
            except Exception:
                pass
            return

        # Handle detailed picker buttons (ids like color__FF0000)
        if event.button.id and event.button.id.startswith("color_"):
            sanitized = event.button.id[len("color_"):]
            color = sanitized.replace("_", "#")
            self.selected_color = color
            print(f"Selected color set to {self.selected_color} from detailed picker")
            try:
                event.stop()
            except Exception:
                pass
            return

    def on_key(self, event) -> None:
        if event.key == "q":
            self.exit()

if __name__ == "__main__":
    PixelArtEditor().run()
