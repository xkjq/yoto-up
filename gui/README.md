# yoto-up-gui

PySide6 desktop application for managing Yoto player content. Built on top of `yoto-up-core` for all API, storage, and audio operations.

## Running

From a development install:

```bash
pip install -e ./core -e ./gui
yoto-up                          # console entry point
# or
yoto-up-gui                      # gui entry point (no console window)
# or
python -m yoto_up_gui.main
```

End users run the pre-built binary from [GitHub Releases](https://github.com/xkjq/yoto-up/releases) -- no Python needed.

## Application Structure

### Entry Point (`main.py`)

Creates a `QApplication`, loads the Catppuccin Mocha stylesheet from `resources/style.qss`, and shows the `MainWindow`.

### Main Window (`app.py`)

The application shell:

- **Toolbar** -- hamburger menu button + current page title
- **Navigation drawer** -- animated sidebar for switching between pages
- **Stacked widget** -- holds all six pages, only the active one is visible
- **Card detail overlay** -- slides in over the current page when a card is clicked
- **Status bar** -- shows authentication state and transient messages
- **Worker management** -- tracks background `QThread` workers to prevent GC; cleans up the `YotoClient` on close

A shared `YotoClient` is created once and distributed to all pages via `set_client()`. Background workers that need API access create their own `httpx.Client` instances (the main client is not thread-safe).

### Pages

| Page | File | What it does |
|------|------|-------------|
| Dashboard | `pages/dashboard.py` | Welcome banner, library stats, quick-action buttons, grid of recent cards |
| Card Library | `pages/card_library.py` | Paginated grid of all cards with search bar, keyboard nav, mouse-wheel scrolling |
| Card Editor | `pages/card_editor.py` | Create/edit cards: chapters, tracks, metadata (title, age range), icon picker |
| Card Detail | `pages/card_detail.py` | Read-only overlay showing card details with edit/delete actions |
| Account | `pages/account.py` | OAuth device-code login/logout, app settings (LUFS target, trim thresholds), cache clearing |
| Devices | `pages/devices.py` | Device list with live status panels (battery, storage, WiFi, temperature, firmware) |
| Audio Tools | `pages/audio_tools.py` | Tabbed interface: normalize loudness, trim silence, preview waveforms |

### Widgets

| Widget | File | What it does |
|--------|------|-------------|
| NavigationDrawer | `widgets/nav_drawer.py` | Animated slide-in/out sidebar with page buttons; emits `page_selected` signal |
| CardTile | `widgets/card_tile.py` | Grid tile showing cover art + title; emits `clicked` signal |
| ImageLabel | `widgets/image_loader.py` | `QLabel` that loads images asynchronously on a background thread with disk caching |
| IconPicker | `widgets/icon_picker.py` | Dialog for searching and selecting card cover art |

### Resources

| File | Purpose |
|------|---------|
| `resources/style.qss` | Catppuccin Mocha theme -- dark background (`#1e1e2e`), blue accent (`#89b4fa`), rounded corners |

## Threading Model

```
GUI Thread                      Background QThreads
+-----------+                   +------------------+
| MainWindow|                   | _CardFetchWorker |  own httpx.Client
| Pages     | <-- signals ---   | _CardDeleteWorker|  own httpx.Client
| Widgets   |                   | _Worker (generic)|  own httpx.Client
| QPixmap   |                   | ImageLoader      |  uses QImage (not QPixmap)
+-----------+                   +------------------+
```

Rules:
- `QPixmap` must only be created/used on the GUI thread
- Background image loading uses `QImage`, converted to `QPixmap` on the GUI thread upon delivery
- Each background worker creates its own `httpx.Client` (the main `YotoClient._http` is not thread-safe)
- Workers are tracked in `MainWindow._active_workers` to prevent garbage collection while running
- Closures that reference mutable lists snapshot them via default args before passing to workers

## Signals & Navigation

- `NavigationDrawer.page_selected(str)` -> `MainWindow._switch_page`
- `DashboardPage.navigate_to(str)` -> `MainWindow._on_dashboard_navigate`
- `DashboardPage.card_selected(str)` / `CardLibraryPage.card_selected(str)` -> `MainWindow._on_card_selected` -> fetch -> overlay
- `CardDetailOverlay.edit_requested(str)` -> open card in editor
- `CardDetailOverlay.delete_requested(str)` -> delete via API -> refresh library
- `CardEditorPage.card_saved(str)` -> switch to library and refresh
- `AccountPage.auth_changed(bool)` -> re-distribute client, refresh data pages
