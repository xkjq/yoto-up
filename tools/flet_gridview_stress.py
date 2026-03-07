# This is a simple Flet app to stress test GridView performance when adding a large number of controls.
# It highlights the performance differences between 0.23 and 0.80 versions
import time
import flet as ft


# Transparent 1x1 PNG data URI used as lightweight placeholder
TRANSPARENT_1PX = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)

NUM_IMAGES = 4000


def main(page: ft.Page):
    page.title = "GridView Stress Test"
    page.window_width = 1200
    page.window_height = 900

    header = ft.Row(controls=[ft.Text("GridView stress test")])
        # Show Flet version
    flet_version = getattr(ft, "__version__", "unknown")
    version_text = ft.Text(value=f"Flet: {flet_version}")
    status = ft.Text("Idle")
    duration_text = ft.Text("")

    grid = ft.GridView(
        width=1000,
        height=700,
        max_extent=80,
        child_aspect_ratio=1,
        cache_extent=50,
        runs_count=6,
    )

    def do_add(e=None):
        try:
            images_to_add = int(images_field.value or str(NUM_IMAGES))
        except Exception:
            images_to_add = NUM_IMAGES
        start = time.time()
        status.value = "Adding images..."
        page.update()

        # Append all images without updating the page until the end
        for i in range(images_to_add):
            img = ft.Image(src=TRANSPARENT_1PX, width=64, height=64)
            c = ft.Container(content=img, border_radius=6, padding=1, border=ft.border.all(1, "#ADACAC"))
            grid.controls.append(c)

        added = time.time() - start
        duration_text.value = f"Appended {images_to_add} controls in {added:.3f}s"
        status.value = "Done"
        page.update()

    def do_add_no_container(e=None):
        # Add images directly without wrapping in a Container to see if that affects performance
        try:
            images_to_add = int(images_field.value or str(NUM_IMAGES))
        except Exception:
            images_to_add = NUM_IMAGES
        start = time.time()
        status.value = "Adding images without container..."
        page.update()

        for i in range(images_to_add):
            img = ft.Image(src=TRANSPARENT_1PX, width=64, height=64, border_radius=6)
            grid.controls.append(img)

        added = time.time() - start
        duration_text.value = f"Appended {images_to_add} images in {added:.3f}s"
        status.value = "Done"
        page.update()

    def do_clear(e=None):
        grid.controls.clear()
        duration_text.value = ""
        status.value = "Cleared"
        page.update()

    add_btn = ft.ElevatedButton("Add images", on_click=do_add)
    add_no_container_btn = ft.ElevatedButton("Add images without container", on_click=do_add_no_container)
    clear_btn = ft.ElevatedButton("Clear", on_click=do_clear)
    # Controls to measure page.update() latency
    runs_field = ft.TextField(label="Update runs", value="5", width=120)
    images_field = ft.TextField(label="Images to add", value=str(NUM_IMAGES), width=120)
    measure_btn = ft.ElevatedButton("Measure page.update()", on_click=lambda e: do_measure())
    measure_result = ft.Text("")

    page.add(
        ft.Row(controls=[header, version_text]),
        ft.Row(controls=[add_btn, add_no_container_btn, clear_btn, status, duration_text, images_field, runs_field, measure_btn, measure_result]),
        grid,
    )

    def do_measure():
        try:
            runs = int(runs_field.value or "5")
        except Exception:
            runs = 5
        times = []
        # Warm-up
        try:
            page.update()
        except Exception:
            pass
        for i in range(runs):
            t0 = time.time()
            try:
                page.update()
            except Exception:
                pass
            times.append(time.time() - t0)
        total = sum(times)
        avg = total / len(times) if times else 0.0
        measure_result.value = f"update() x{runs}: avg {avg:.4f}s total {total:.4f}s"
        page.update()


if __name__ == "__main__":
    ft.app(target=main)
