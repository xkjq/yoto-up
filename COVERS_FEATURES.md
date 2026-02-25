# Covers Tab Features

The Covers tab allows you to create and print covers for Yoto cards (54mm × 85.6mm).

## Features

### 1. Image Management
- Add multiple images at once
- View and manage an image list (select, edit, delete)

### 2. Image Editing
When you select an image from the list, you can edit:

- Fit Mode:
  - Resize: Stretch to exactly fit (may distort)
  - Crop: Crop to fit while maintaining aspect ratio
  - Scale: Scale to fit with borders (maintains aspect ratio)

- Crop Position (when using Crop mode):
  - Preset positions: Center, Top, Bottom, Left, Right, corners
  - Custom Offsets: Sliders to fine-tune horizontal and vertical crop position (-1.0..1.0)

### 3. Text Overlays
Add text with full control per overlay:

- Text content
- Font size: adjustable from 8 up to 300 points
- Font selection: choose from several fonts (DejaVu Sans, Liberation Sans, Arial, Default). If a scalable TrueType font is available, the slider affects rendered size.
- Color: hex color entry and picker dialog
- Position: X and Y as percentages (0.0..1.0)
- Multiple overlays per image; edit or delete overlays from a list

### 4. Print Settings
- Paper Size: A4, Letter, Legal
- Print Mode:
  - Overprint: Render slightly larger than card (default ~2% bleed)
  - Underprint: Render slightly smaller than card (default ~2% inset). Underprint is NOT mirrored.
  - Exact: Render exactly the card dimensions (no bleed/inset)
- Cut lines: Toggle dotted cut lines around each cover
- Margin: Adjust margins between covers (0–20 mm)

### 5. Preview
- Automatic layout: optimises number of covers per sheet
- Interactive zoom & pan (including Ctrl+scroll)
- Zoom controls (in/out/reset) and zoom-level display
- Preview regenerates at appropriate resolution for zoom level
- Cut guides are drawn for every possible card slot on the sheet (cols × rows), even when slots are empty

### 6. Printing
- Generates high-resolution print-ready images (300 DPI recommended)
- Saves to a temp file and attempts to open the system viewer for printing

## Workflow

1. Add images
2. Select an image and configure fit/crop and any text overlays
3. Configure paper size, margins and print mode (Overprint / Underprint / Exact)
4. Use preview and zoom to verify layout
5. Print to generate a high-resolution layout file

## Notes & Tips
- Overprint/Underprint are implemented by scaling the rendered image slightly relative to the card size; you can request different bleed/inset amounts if desired.
- If the system lacks scalable TrueType fonts, the renderer may fall back to a fixed-size font that will not reflect slider changes; bundling a TTF in the repo is recommended for consistent results across environments.

## Requirements
- PIL/Pillow for image processing
- Flet for the UI
- Images in common formats: PNG, JPG, JPEG, BMP, GIF

# Covers Tab Features

The Covers tab allows you to create and print covers for Yoto cards (54mm x 85.6mm).

## Features

### 1. Image Management
- **Add Multiple Images**: Use the add button to select one or more images
- **Image List**: Shows all added images with their fit mode
- **Delete Images**: Remove individual images or clear all

### 2. Image Editing
When you select an image from the list, you can edit:

- **Fit Mode**:
  - **Resize**: Stretches image to fit (may distort)
  - **Crop**: Crops image to fit while maintaining aspect ratio
  - **Scale**: Scales image to fit with borders (maintains aspect ratio)

- **Crop Position** (when using Crop mode):
  - Preset positions: Center, Top, Bottom, Left, Right, corners
  - **Custom Offsets**: Use sliders to fine-tune horizontal and vertical crop position
    - Horizontal Offset: -1.0 (left) to 1.0 (right)
    - Vertical Offset: -1.0 (top) to 1.0 (bottom)

### 3. Text Overlays
Add text to your covers with full control:

- **Text Content**: Enter any text you want to display
- **Font Size**: Adjustable from 8 to 72 points
- **Color**: Hex color picker (e.g., #000000 for black, #FF0000 for red)
- **Position**: 
  - X position: 0.0 (left) to 1.0 (right)
  - Y position: 0.0 (top) to 1.0 (bottom)
- **Multiple Overlays**: Add as many text overlays as needed
- **Edit/Delete**: Select from the list to edit or delete

### 4. Print Settings
- **Paper Size**: Choose from A4, Letter, or Legal
- **Print Mode**:
  - **Overprint**: Normal printing on top of card
  - **Underprint**: Mirrored for printing underneath
- **Cut Lines**: Toggle dotted cut lines around each cover
- **Margin**: Adjust margins (0-20mm) between covers

### 5. Preview
- **Automatic Layout**: Optimizes number of covers per sheet
- **Zoom Controls**:
  - Zoom In: Increase preview zoom
  - Zoom Out: Decrease preview zoom
  - Reset Zoom: Return to 100%
  - Current zoom level displayed
- **Refresh**: Regenerate preview after changes
- **Visual Feedback**: See exactly how covers will print

### 6. Printing
- **High Resolution**: Generates print-ready files at 300 DPI
- **Auto-Open**: Saves to temp file and opens with system viewer
- **Location**: Files saved to system temp directory as `yoto_covers_print.png`

## Workflow

1. **Add Images**: Click the add button and select images
2. **Edit Each Image**: 
   - Click an image in the list to select it
   - Choose fit mode and adjust crop position if needed
   - Add text overlays as desired
3. **Configure Print Settings**: Set paper size, margins, and print mode
4. **Preview**: Click refresh to see the layout
5. **Zoom**: Use zoom controls to inspect details
6. **Print**: Click print to generate and open the final file

## Tips

- **Crop Positioning**: Use the offset sliders to fine-tune exactly what part of the image is shown when cropping
- **Text Positioning**: Position values are percentages (0.5, 0.5 is center)
- **Multiple Text Layers**: Add multiple text overlays to create complex designs
- **Color Selection**: Use standard hex color codes (#RRGGBB format)
- **Layout Optimization**: The system automatically chooses portrait/landscape orientation for maximum covers per sheet

## Requirements

- PIL/Pillow library must be installed for image processing
- Images should be in common formats: PNG, JPG, JPEG, BMP, GIF
