#!/usr/bin/env python3
"""Slice a pixel-art sprite sheet into tiles and export each tile as a stamp JSON
compatible with the editor's `.stamps` format using Typer for the CLI.

Requires: Pillow, typer
"""

import json
import os
from PIL import Image
import typer

app = typer.Typer(add_completion=False)


def image_to_pixels(img: Image.Image):
    """Convert an RGBA PIL image to the editor's pixel-grid format.
    Returns list of rows where each item is None or "#RRGGBB".
    """
    img = img.convert("RGBA")
    w, h = img.size
    pixels = []
    data = list(img.getdata())
    for y in range(h):
        row = []
        for x in range(w):
            v = data[y * w + x]
            # ensure we have a 4-tuple (r,g,b,a)
            if isinstance(v, int):
                # defensive fallback: treat as opaque gray
                r = g = b = v
                a = 255
            else:
                try:
                    r, g, b, a = v
                except Exception:
                    # fallback: if length 3, assume full alpha
                    if len(v) == 3:
                        r, g, b = v
                        a = 255
                    else:
                        r = g = b = 0
                        a = 0
            if a < 128:
                row.append(None)
            else:
                row.append(f"#{r:02X}{g:02X}{b:02X}")
        pixels.append(row)
    return pixels


def is_tile_empty(grid):
    for row in grid:
        for p in row:
            if p is not None:
                return False
    return True


def ensure_out_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


@app.command()
def slice(
    input: str = typer.Option(..., "-i", help="Path to sprite sheet image"),
    tile_width: int = typer.Option(..., "-tw", help="Tile width in pixels"),
    tile_height: int = typer.Option(..., "-th", help="Tile height in pixels"),
    out_dir: str = typer.Option(".stamps", "-o", help="Output directory (default: .stamps)"),
    prefix: str = typer.Option("sheet", "-p", help="Filename prefix for output stamps"),
    skip_empty: bool = typer.Option(False, help="Skip tiles that are entirely transparent"),
    start_row: int = typer.Option(0, help="Row index to start from (0-based)"),
    start_col: int = typer.Option(0, help="Column index to start from (0-based)"),
    rows: int = typer.Option(0, help="Number of rows to process (0 = auto)"),
    cols: int = typer.Option(0, help="Number of cols to process (0 = auto)"),
):
    """Slice a sheet into stamps and write JSON files into OUT_DIR."""
    img_path = input
    if not os.path.isfile(img_path):
        typer.echo(f"Input file not found: {img_path}", err=True)
        raise typer.Exit(code=1)

    img = Image.open(img_path).convert("RGBA")
    sheet_w, sheet_h = img.size
    tw = tile_width
    th = tile_height

    cols_total = sheet_w // tw
    rows_total = sheet_h // th

    cols_to_process = cols or (cols_total - start_col)
    rows_to_process = rows or (rows_total - start_row)

    if start_col < 0 or start_row < 0:
        typer.echo("start-row and start-col must be >= 0", err=True)
        raise typer.Exit(code=1)

    ensure_out_dir(out_dir)

    written = 0
    for r in range(start_row, start_row + rows_to_process):
        if r >= rows_total:
            break
        for c in range(start_col, start_col + cols_to_process):
            if c >= cols_total:
                break
            left = c * tw
            top = r * th
            box = (left, top, left + tw, top + th)
            tile = img.crop(box)
            grid = image_to_pixels(tile)
            if skip_empty and is_tile_empty(grid):
                continue
            name = f"{prefix}_{r}_{c}" if prefix else f"tile_{r}_{c}"
            out_path = os.path.join(out_dir, f"{name}.json")
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump({"metadata": {"name": name, "source": os.path.basename(img_path)}, "pixels": grid}, fh, indent=2)
            written += 1
    typer.echo(f"Wrote {written} stamps to {out_dir}")


def main():
    app()


if __name__ == "__main__":
    main()
