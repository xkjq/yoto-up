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
