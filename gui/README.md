# yoto-up-gui

PySide6 desktop application for managing Yoto player content. Depends on `yoto-up-core` for all API and data operations.

## Pages

| Page | Module | Description |
|------|--------|-------------|
| **Dashboard** | `pages/dashboard.py` | Quick-action cards, recent content overview |
| **Card Library** | `pages/card_library.py` | Paginated grid of cards with search, keyboard nav, and wheel scrolling |
| **Card Editor** | `pages/card_editor.py` | Full card creation/editing with chapters, tracks, metadata, and icon picker |
| **Card Detail** | `pages/card_detail.py` | Overlay panel showing card details with edit/delete actions |
| **Account** | `pages/account.py` | OAuth device-code login, app settings, cache management |
| **Devices** | `pages/devices.py` | Device list with live status (battery, storage, WiFi, firmware) |
| **Audio Tools** | `pages/audio_tools.py` | Tabbed interface for loudness normalization and silence trimming |

## Widgets

| Widget | Module | Description |
|--------|--------|-------------|
| **NavigationDrawer** | `widgets/nav_drawer.py` | Animated slide-in sidebar for page switching |
| **CardTile** | `widgets/card_tile.py` | Card grid tile with cover art and title |
| **ImageLabel** | `widgets/image_loader.py` | QLabel with async background image loading and disk cache |
| **IconPicker** | `widgets/icon_picker.py` | Icon search and selection dialog |

## Application Shell

`app.py` contains `MainWindow` which:

- Creates and distributes a shared `YotoClient` to all pages
- Manages page navigation via the stacked widget
- Runs API operations (card fetch, delete) on background `QThread` workers
- Tracks worker lifecycle to prevent premature garbage collection
- Forwards resize events to the card detail overlay
- Cleans up the HTTP client on window close

## Running

```bash
pip install -e ./core -e ./gui
yoto-up
# or
python -m yoto_up_gui.main
```

## Thread Safety Notes

- `httpx.Client` is **not** thread-safe. Background workers create their own `httpx.Client` instances.
- `QPixmap` must only be used on the GUI thread. The image loader uses `QImage` on background threads and converts on the main thread.
- Worker references are kept in `_active_workers` to prevent GC while running.
- All closures that reference mutable lists snapshot them before passing to workers.
