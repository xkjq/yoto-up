"""
Covers tab module for creating and printing Yoto card covers.

Card dimensions: 54mm x 85.6mm
Features:
- Add multiple images
- Image editing (resize, crop, scale)
- Layout optimization for printing
- Overprint/underprint options
- Cut lines toggle
- Print preview and printing
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

import flet as ft
from loguru import logger

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PIL/Pillow not available for covers functionality")


# Card dimensions in mm
CARD_WIDTH_MM = 54.0
CARD_HEIGHT_MM = 85.6

# Common paper sizes in mm (width x height)
PAPER_SIZES = {
    "A4": (210, 297),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}

# DPI for printing
DEFAULT_DPI = 300


class ImageFitMode(str, Enum):
    """How an image should fit within the card dimensions."""
    RESIZE = "resize"  # Resize to fit exactly (may distort)
    CROP = "crop"      # Crop to fit (maintains aspect ratio)
    SCALE = "scale"    # Scale to fit (maintains aspect ratio, may have borders)


class CropPosition(str, Enum):
    """Position for cropping when image doesn't match card aspect ratio."""
    CENTER = "center"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class PrintMode(str, Enum):
    """Print mode for covers."""
    OVERPRINT = "overprint"   # Print on top of existing card
    UNDERPRINT = "underprint" # Print underneath (mirror image)


class CoverImage:
    """Represents a single cover image with editing options."""
    
    def __init__(self, path: str):
        self.path = path
        self.fit_mode: ImageFitMode = ImageFitMode.SCALE
        self.crop_position: CropPosition = CropPosition.CENTER
        self.name = Path(path).name
        
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "path": self.path,
            "fit_mode": self.fit_mode.value,
            "crop_position": self.crop_position.value,
            "name": self.name,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CoverImage':
        """Deserialize from dictionary."""
        img = cls(data["path"])
        img.fit_mode = ImageFitMode(data.get("fit_mode", ImageFitMode.SCALE.value))
        img.crop_position = CropPosition(data.get("crop_position", CropPosition.CENTER.value))
        img.name = data.get("name", Path(data["path"]).name)
        return img


def mm_to_pixels(mm: float, dpi: int = DEFAULT_DPI) -> int:
    """Convert millimeters to pixels at given DPI."""
    return int((mm / 25.4) * dpi)


def calculate_layout(num_cards: int, paper_size: tuple[float, float], 
                     card_size: tuple[float, float], margin_mm: float = 5.0) -> tuple[int, int]:
    """
    Calculate optimal layout for cards on paper.
    
    Returns: (cols, rows) that maximizes number of cards per sheet
    """
    paper_w, paper_h = paper_size
    card_w, card_h = card_size
    
    # Try different orientations
    best_layout = (0, 0)
    best_count = 0
    
    for card_orientation in [(card_w, card_h), (card_h, card_w)]:
        c_w, c_h = card_orientation
        # Calculate how many fit with margins
        cols = int((paper_w - margin_mm) / (c_w + margin_mm))
        rows = int((paper_h - margin_mm) / (c_h + margin_mm))
        count = cols * rows
        
        if count > best_count:
            best_count = count
            best_layout = (cols, rows)
    
    return best_layout


def process_image(img_path: str, fit_mode: ImageFitMode, crop_position: CropPosition,
                 target_width: int, target_height: int) -> Image.Image:
    """
    Process an image according to fit mode and crop position.
    
    Args:
        img_path: Path to source image
        fit_mode: How to fit the image
        crop_position: Where to crop if needed
        target_width: Target width in pixels
        target_height: Target height in pixels
    
    Returns: Processed PIL Image
    """
    if not HAS_PIL:
        raise RuntimeError("PIL/Pillow required for image processing")
    
    img = Image.open(img_path)
    img = img.convert("RGB")  # Ensure RGB mode
    
    if fit_mode == ImageFitMode.RESIZE:
        # Simple resize (may distort)
        return img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    elif fit_mode == ImageFitMode.SCALE:
        # Scale to fit, maintaining aspect ratio
        img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        # Create new image with target size and paste scaled image
        result = Image.new("RGB", (target_width, target_height), "white")
        paste_x = (target_width - img.width) // 2
        paste_y = (target_height - img.height) // 2
        result.paste(img, (paste_x, paste_y))
        return result
    
    elif fit_mode == ImageFitMode.CROP:
        # Crop to fit, maintaining aspect ratio
        target_ratio = target_width / target_height
        img_ratio = img.width / img.height
        
        if img_ratio > target_ratio:
            # Image is wider than target, crop width
            new_width = int(img.height * target_ratio)
            new_height = img.height
        else:
            # Image is taller than target, crop height
            new_width = img.width
            new_height = int(img.width / target_ratio)
        
        # Calculate crop position
        if crop_position == CropPosition.CENTER:
            left = (img.width - new_width) // 2
            top = (img.height - new_height) // 2
        elif crop_position == CropPosition.TOP:
            left = (img.width - new_width) // 2
            top = 0
        elif crop_position == CropPosition.BOTTOM:
            left = (img.width - new_width) // 2
            top = img.height - new_height
        elif crop_position == CropPosition.LEFT:
            left = 0
            top = (img.height - new_height) // 2
        elif crop_position == CropPosition.RIGHT:
            left = img.width - new_width
            top = (img.height - new_height) // 2
        elif crop_position == CropPosition.TOP_LEFT:
            left = 0
            top = 0
        elif crop_position == CropPosition.TOP_RIGHT:
            left = img.width - new_width
            top = 0
        elif crop_position == CropPosition.BOTTOM_LEFT:
            left = 0
            top = img.height - new_height
        elif crop_position == CropPosition.BOTTOM_RIGHT:
            left = img.width - new_width
            top = img.height - new_height
        else:
            left = (img.width - new_width) // 2
            top = (img.height - new_height) // 2
        
        cropped = img.crop((left, top, left + new_width, top + new_height))
        return cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    return img


def generate_print_layout(cover_images: List[CoverImage], paper_size: str = "A4",
                         print_mode: PrintMode = PrintMode.OVERPRINT,
                         show_cut_lines: bool = True,
                         dpi: int = DEFAULT_DPI,
                         margin_mm: float = 5.0) -> Image.Image:
    """
    Generate a print layout with multiple covers on a single sheet.
    
    Args:
        cover_images: List of CoverImage objects to print
        paper_size: Paper size name (A4, Letter, etc.)
        print_mode: Overprint or underprint
        show_cut_lines: Whether to show cut lines
        dpi: DPI for printing
        margin_mm: Margin around cards in mm
    
    Returns: PIL Image ready for printing
    """
    if not HAS_PIL:
        raise RuntimeError("PIL/Pillow required for print layout generation")
    
    # Get paper dimensions
    paper_w_mm, paper_h_mm = PAPER_SIZES.get(paper_size, PAPER_SIZES["A4"])
    paper_w_px = mm_to_pixels(paper_w_mm, dpi)
    paper_h_px = mm_to_pixels(paper_h_mm, dpi)
    
    # Calculate card dimensions in pixels
    card_w_px = mm_to_pixels(CARD_WIDTH_MM, dpi)
    card_h_px = mm_to_pixels(CARD_HEIGHT_MM, dpi)
    
    # Calculate layout
    cols, rows = calculate_layout(
        len(cover_images),
        (paper_w_mm, paper_h_mm),
        (CARD_WIDTH_MM, CARD_HEIGHT_MM),
        margin_mm
    )
    
    # Create blank page
    page_img = Image.new("RGB", (paper_w_px, paper_h_px), "white")
    draw = ImageDraw.Draw(page_img)
    
    margin_px = mm_to_pixels(margin_mm, dpi)
    
    # Place each cover
    for idx, cover_img in enumerate(cover_images):
        if idx >= cols * rows:
            break  # Can't fit more on this page
        
        row = idx // cols
        col = idx % cols
        
        # Calculate position
        x = margin_px + col * (card_w_px + margin_px)
        y = margin_px + row * (card_h_px + margin_px)
        
        try:
            # Process and place image
            processed = process_image(
                cover_img.path,
                cover_img.fit_mode,
                cover_img.crop_position,
                card_w_px,
                card_h_px
            )
            
            # Mirror for underprint
            if print_mode == PrintMode.UNDERPRINT:
                processed = processed.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            
            page_img.paste(processed, (x, y))
            
            # Draw cut lines
            if show_cut_lines:
                # Draw dotted lines around the card
                line_color = (200, 200, 200)
                line_width = 1
                dash_length = mm_to_pixels(2, dpi)
                
                # Top line
                for dx in range(0, card_w_px, dash_length * 2):
                    draw.line([(x + dx, y), (x + min(dx + dash_length, card_w_px), y)], 
                             fill=line_color, width=line_width)
                # Bottom line
                for dx in range(0, card_w_px, dash_length * 2):
                    draw.line([(x + dx, y + card_h_px), (x + min(dx + dash_length, card_w_px), y + card_h_px)], 
                             fill=line_color, width=line_width)
                # Left line
                for dy in range(0, card_h_px, dash_length * 2):
                    draw.line([(x, y + dy), (x, y + min(dy + dash_length, card_h_px))], 
                             fill=line_color, width=line_width)
                # Right line
                for dy in range(0, card_h_px, dash_length * 2):
                    draw.line([(x + card_w_px, y + dy), (x + card_w_px, y + min(dy + dash_length, card_h_px))], 
                             fill=line_color, width=line_width)
        
        except Exception as e:
            logger.error(f"Error processing cover image {cover_img.name}: {e}")
            # Draw error box
            draw.rectangle([x, y, x + card_w_px, y + card_h_px], outline="red", width=2)
            draw.text((x + 10, y + 10), f"Error: {cover_img.name}", fill="red")
    
    return page_img


def build_covers_panel(page: ft.Page, show_snack) -> Dict[str, Any]:
    """
    Build the Covers tab UI.
    
    Args:
        page: Flet page object
        show_snack: Function to show snackbar messages
    
    Returns: Dictionary with panel control and helpers
    """
    
    # State
    cover_images: List[CoverImage] = []
    selected_image_index: Optional[int] = None
    
    # Preview image storage
    preview_path: Optional[str] = None
    
    # Controls
    paper_size_dropdown = ft.Dropdown(
        label="Paper Size",
        value="A4",
        options=[
            ft.dropdown.Option("A4"),
            ft.dropdown.Option("Letter"),
            ft.dropdown.Option("Legal"),
        ],
        width=150,
    )
    
    print_mode_dropdown = ft.Dropdown(
        label="Print Mode",
        value=PrintMode.OVERPRINT.value,
        options=[
            ft.dropdown.Option(PrintMode.OVERPRINT.value, "Overprint"),
            ft.dropdown.Option(PrintMode.UNDERPRINT.value, "Underprint"),
        ],
        width=150,
    )
    
    cut_lines_checkbox = ft.Checkbox(label="Show cut lines", value=True)
    
    margin_slider = ft.Slider(
        min=0,
        max=20,
        value=5,
        divisions=20,
        label="Margin: {value}mm",
        width=200,
    )
    
    # Image list
    image_list = ft.ListView(expand=True, spacing=5, padding=10)
    
    # Preview
    preview_image = ft.Image(
        src="",
        fit=ft.ImageFit.CONTAIN,
        visible=False,
    )
    
    # Image editing panel (shown when an image is selected)
    fit_mode_dropdown = ft.Dropdown(
        label="Fit Mode",
        value=ImageFitMode.SCALE.value,
        options=[
            ft.dropdown.Option(ImageFitMode.RESIZE.value, "Resize (may distort)"),
            ft.dropdown.Option(ImageFitMode.CROP.value, "Crop (maintain ratio)"),
            ft.dropdown.Option(ImageFitMode.SCALE.value, "Scale (maintain ratio)"),
        ],
        width=250,
    )
    
    crop_position_dropdown = ft.Dropdown(
        label="Crop Position",
        value=CropPosition.CENTER.value,
        options=[
            ft.dropdown.Option(CropPosition.CENTER.value, "Center"),
            ft.dropdown.Option(CropPosition.TOP.value, "Top"),
            ft.dropdown.Option(CropPosition.BOTTOM.value, "Bottom"),
            ft.dropdown.Option(CropPosition.LEFT.value, "Left"),
            ft.dropdown.Option(CropPosition.RIGHT.value, "Right"),
            ft.dropdown.Option(CropPosition.TOP_LEFT.value, "Top Left"),
            ft.dropdown.Option(CropPosition.TOP_RIGHT.value, "Top Right"),
            ft.dropdown.Option(CropPosition.BOTTOM_LEFT.value, "Bottom Left"),
            ft.dropdown.Option(CropPosition.BOTTOM_RIGHT.value, "Bottom Right"),
        ],
        width=200,
        visible=False,
    )
    
    edit_panel = ft.Container(
        content=ft.Column([
            ft.Text("Edit Selected Image", weight=ft.FontWeight.BOLD),
            fit_mode_dropdown,
            crop_position_dropdown,
        ], spacing=10),
        padding=10,
        visible=False,
    )
    
    # Functions
    def update_image_list():
        """Update the image list display."""
        image_list.controls.clear()
        for idx, img in enumerate(cover_images):
            is_selected = idx == selected_image_index
            
            def make_on_click(index):
                def on_click(e):
                    select_image(index)
                page.update()
                return on_click
            
            def make_on_delete(index):
                def on_delete(e):
                    delete_image(index)
                return on_delete
            
            row = ft.Container(
                content=ft.Row([
                    ft.Text(f"{idx + 1}.", width=30),
                    ft.Text(img.name, expand=True),
                    ft.Text(f"({img.fit_mode.value})", size=12, color=ft.Colors.GREY_600),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        icon_color=ft.Colors.RED_400,
                        tooltip="Delete",
                        on_click=make_on_delete(idx),
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                bgcolor=ft.Colors.BLUE_100 if is_selected else None,
                padding=10,
                border_radius=5,
                on_click=make_on_click(idx),
                ink=True,
            )
            image_list.controls.append(row)
        
        page.update()
    
    def select_image(index: int):
        """Select an image for editing."""
        nonlocal selected_image_index
        selected_image_index = index
        
        if 0 <= index < len(cover_images):
            img = cover_images[index]
            fit_mode_dropdown.value = img.fit_mode.value
            crop_position_dropdown.value = img.crop_position.value
            crop_position_dropdown.visible = (img.fit_mode == ImageFitMode.CROP)
            edit_panel.visible = True
        else:
            edit_panel.visible = False
        
        update_image_list()
    
    def delete_image(index: int):
        """Delete an image from the list."""
        nonlocal selected_image_index
        if 0 <= index < len(cover_images):
            cover_images.pop(index)
            if selected_image_index == index:
                selected_image_index = None
                edit_panel.visible = False
            elif selected_image_index is not None and selected_image_index > index:
                selected_image_index -= 1
            update_image_list()
    
    def on_fit_mode_change(e):
        """Handle fit mode change."""
        if selected_image_index is not None and 0 <= selected_image_index < len(cover_images):
            img = cover_images[selected_image_index]
            img.fit_mode = ImageFitMode(fit_mode_dropdown.value)
            crop_position_dropdown.visible = (img.fit_mode == ImageFitMode.CROP)
            update_image_list()
            update_preview()
    
    def on_crop_position_change(e):
        """Handle crop position change."""
        if selected_image_index is not None and 0 <= selected_image_index < len(cover_images):
            img = cover_images[selected_image_index]
            img.crop_position = CropPosition(crop_position_dropdown.value)
            update_preview()
    
    fit_mode_dropdown.on_change = on_fit_mode_change
    crop_position_dropdown.on_change = on_crop_position_change
    
    def update_preview():
        """Generate and display preview."""
        nonlocal preview_path
        
        if not cover_images:
            preview_image.visible = False
            page.update()
            return
        
        if not HAS_PIL:
            show_snack("PIL/Pillow required for preview", error=True)
            return
        
        try:
            # Generate layout
            layout_img = generate_print_layout(
                cover_images,
                paper_size=paper_size_dropdown.value,
                print_mode=PrintMode(print_mode_dropdown.value),
                show_cut_lines=cut_lines_checkbox.value,
                dpi=150,  # Lower DPI for preview
                margin_mm=margin_slider.value,
            )
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                preview_path = tmp.name
                layout_img.save(preview_path, "PNG")
            
            preview_image.src = preview_path
            preview_image.visible = True
            page.update()
            
        except Exception as e:
            logger.error(f"Error generating preview: {e}")
            show_snack(f"Error generating preview: {e}", error=True)
    
    def on_add_images_result(e: ft.FilePickerResultEvent):
        """Handle file picker result."""
        if e.files:
            for file in e.files:
                cover_img = CoverImage(file.path)
                cover_images.append(cover_img)
            update_image_list()
            update_preview()
            show_snack(f"Added {len(e.files)} image(s)")
    
    file_picker = ft.FilePicker(on_result=on_add_images_result)
    page.overlay.append(file_picker)
    
    def on_add_images(e):
        """Open file picker to add images."""
        file_picker.pick_files(
            allowed_extensions=["png", "jpg", "jpeg", "bmp", "gif"],
            allow_multiple=True,
        )
    
    def on_generate_preview(e):
        """Generate preview button handler."""
        update_preview()
    
    def on_print(e):
        """Handle print button click."""
        if not cover_images:
            show_snack("No images to print", error=True)
            return
        
        if not HAS_PIL:
            show_snack("PIL/Pillow required for printing", error=True)
            return
        
        try:
            # Generate high-resolution layout
            layout_img = generate_print_layout(
                cover_images,
                paper_size=paper_size_dropdown.value,
                print_mode=PrintMode(print_mode_dropdown.value),
                show_cut_lines=cut_lines_checkbox.value,
                dpi=DEFAULT_DPI,
                margin_mm=margin_slider.value,
            )
            
            # Save to file
            output_path = Path(tempfile.gettempdir()) / "yoto_covers_print.png"
            layout_img.save(output_path, "PNG", dpi=(DEFAULT_DPI, DEFAULT_DPI))
            
            show_snack(f"Print layout saved to {output_path}")
            logger.info(f"Print layout saved to {output_path}")
            
            # Try to open with system default viewer
            import platform
            import subprocess
            
            system = platform.system()
            if system == "Windows":
                subprocess.run(["start", str(output_path)], shell=True)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(output_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(output_path)])
            
        except Exception as e:
            logger.error(f"Error generating print layout: {e}")
            show_snack(f"Error generating print layout: {e}", error=True)
    
    def on_clear_all(e):
        """Clear all images."""
        nonlocal selected_image_index, preview_path
        cover_images.clear()
        selected_image_index = None
        edit_panel.visible = False
        preview_image.visible = False
        if preview_path:
            try:
                Path(preview_path).unlink(missing_ok=True)
            except Exception:
                pass
            preview_path = None
        update_image_list()
    
    # Layout update triggers
    paper_size_dropdown.on_change = lambda e: update_preview()
    print_mode_dropdown.on_change = lambda e: update_preview()
    cut_lines_checkbox.on_change = lambda e: update_preview()
    margin_slider.on_change = lambda e: update_preview()
    
    # Build UI
    settings_panel = ft.Container(
        content=ft.Column([
            ft.Text("Print Settings", weight=ft.FontWeight.BOLD, size=16),
            ft.Row([paper_size_dropdown, print_mode_dropdown]),
            ft.Row([cut_lines_checkbox]),
            ft.Row([ft.Text("Margin:"), margin_slider]),
        ], spacing=10),
        padding=10,
        border=ft.border.all(1, ft.Colors.GREY_400),
        border_radius=5,
    )
    
    image_management = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Cover Images", weight=ft.FontWeight.BOLD, size=16, expand=True),
                ft.IconButton(
                    icon=ft.Icons.ADD_PHOTO_ALTERNATE,
                    tooltip="Add Images",
                    on_click=on_add_images,
                ),
                ft.IconButton(
                    icon=ft.Icons.CLEAR_ALL,
                    tooltip="Clear All",
                    on_click=on_clear_all,
                ),
            ]),
            ft.Container(
                content=image_list,
                height=300,
                border=ft.border.all(1, ft.Colors.GREY_300),
                border_radius=5,
            ),
        ], spacing=10),
        padding=10,
    )
    
    preview_panel = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("Preview", weight=ft.FontWeight.BOLD, size=16, expand=True),
                ft.ElevatedButton(
                    text="Generate Preview",
                    icon=ft.Icons.REFRESH,
                    on_click=on_generate_preview,
                ),
                ft.ElevatedButton(
                    text="Print",
                    icon=ft.Icons.PRINT,
                    on_click=on_print,
                ),
            ]),
            ft.Container(
                content=preview_image,
                expand=True,
                border=ft.border.all(1, ft.Colors.GREY_300),
                border_radius=5,
            ),
        ], spacing=10, expand=True),
        padding=10,
        expand=True,
    )
    
    left_panel = ft.Column([
        settings_panel,
        image_management,
        edit_panel,
    ], spacing=10, scroll=ft.ScrollMode.AUTO)
    
    main_content = ft.Row([
        ft.Container(content=left_panel, width=400),
        ft.VerticalDivider(width=1),
        preview_panel,
    ], expand=True)
    
    return {
        "panel": main_content,
        "update_preview": update_preview,
    }
