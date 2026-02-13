# Yoto-UP

<img src="art.jpeg" alt="Yoto-UP" style="max-width:100%;height:auto;">

A desktop app for managing your Yoto player cards, devices, and audio content.

Yoto-UP is a standalone application for Windows, macOS, and Linux. Download the latest release, run it, and log in with your Yoto account -- no Python or command-line knowledge required.

## Quickstart

1. **Download** the latest release for your platform from [GitHub Releases](https://github.com/xkjq/yoto-up/releases)

   | Platform | File |
   |----------|------|
   | Windows | `yoto-up.exe` |
   | macOS | `yoto-up` (or `.dmg` installer) |
   | Linux | `yoto-up` (or Flatpak) |

2. **Run** the downloaded file

3. **Log in** -- go to the Account page, click "Login", and follow the device-code instructions on screen. You'll be given a code to enter at Yoto's website in your browser.

4. **Manage your cards** -- your card library loads automatically after login. Browse, edit, create, and delete cards from the GUI.

## What You Can Do

### Card Library
Browse all your Yoto cards in a paginated grid. Search by title, click a card to see its details, or open it in the editor. Keyboard and mouse-wheel navigation supported.

### Card Editor
Create new cards or edit existing ones. Add chapters, reorder tracks, set metadata (title, age range, category), and pick cover art via the built-in icon picker.

### Device Manager
View all your registered Yoto players. See live status for each device: battery level, storage usage, WiFi signal, temperature, and firmware version.

### Audio Tools
Prepare audio files before uploading:
- **Normalize** -- adjust loudness to a target LUFS level so all tracks play at a consistent volume
- **Trim Silence** -- detect and remove silence from the start/end of audio files
- **Waveform Preview** -- visualize audio amplitude before and after processing

### Account & Settings
Manage your Yoto login, configure application settings, and clear cached data (API cache, icon cache).

## Screenshots

The app uses a dark theme (Catppuccin Mocha) with a navigation drawer on the left and a toolbar at the top.

```
+-------+----------------------------------------------+
| Menu  |  Toolbar: [=] Page Title                     |
+-------+----------------------------------------------+
|       |                                              |
| Dash  |  +------+  +------+  +------+  +------+     |
| Cards |  | Card |  | Card |  | Card |  | Card |     |
| Edit  |  | Tile |  | Tile |  | Tile |  | Tile |     |
| Acct  |  +------+  +------+  +------+  +------+     |
| Dev   |                                              |
| Audio |  +------+  +------+  +------+  +------+     |
|       |  | Card |  | Card |  | Card |  | Card |     |
|       |  | Tile |  | Tile |  | Tile |  | Tile |     |
|       |  +------+  +------+  +------+  +------+     |
|       |                                              |
+-------+----------------------------------------------+
|  Status bar: Authenticated                           |
+------------------------------------------------------+
```

## Architecture

Yoto-UP is split into two Python packages that are bundled into a single binary at release time:

```
yoto-up/
  core/                         # yoto-up-core -- standalone library, no GUI deps
    yoto_up/
      api/                      # Yoto API client
      +-- client.py             #   Authenticated HTTP client (httpx) with auto token refresh
      +-- auth.py               #   OAuth 2.0 device-code flow
      +-- cards.py              #   Card CRUD (list, get, create, update, delete)
      +-- devices.py            #   Device listing and live status
      +-- icons.py              #   Icon/cover art search and download
      +-- media.py              #   Audio upload with SHA-256 integrity
      audio/                    # Audio processing
      +-- normalize.py          #   LUFS loudness normalization (via FFmpeg)
      +-- trim.py               #   Silence detection and trimming (via pydub)
      +-- waveform.py           #   Waveform extraction (via soundfile/numpy)
      models/                   # Pydantic data models
      +-- card.py               #   Card, Chapter, Track
      +-- device.py             #   Device, DeviceStatus
      +-- user.py               #   TokenData
      storage/                  # Persistent local storage
      +-- tokens.py             #   OAuth token save/load/delete
      +-- config.py             #   App settings (JSON)
      +-- cache.py              #   API cache (time-based) + icon cache (disk, SHA-256)
      +-- versions.py           #   Card version snapshots
      +-- paths.py              #   Cross-platform dirs via platformdirs
  gui/                          # yoto-up-gui -- PySide6 desktop application
    yoto_up_gui/
      main.py                   # Entry point: QApplication setup, stylesheet loading
      app.py                    # MainWindow: navigation shell, page stack, workers
      pages/
      +-- dashboard.py          #   Welcome banner, stats, quick actions, recent cards
      +-- card_library.py       #   Paginated card grid with search
      +-- card_editor.py        #   Full card editor (chapters, tracks, metadata)
      +-- card_detail.py        #   Slide-in overlay with card details
      +-- account.py            #   Login/logout, settings, cache management
      +-- devices.py            #   Device list with live status panels
      +-- audio_tools.py        #   Tabbed normalize/trim/waveform interface
      widgets/
      +-- nav_drawer.py         #   Animated sidebar navigation
      +-- card_tile.py          #   Card grid tile with cover art
      +-- image_loader.py       #   Async background image loading with disk cache
      +-- icon_picker.py        #   Icon search and selection dialog
      resources/
      +-- style.qss             #   Catppuccin Mocha Qt stylesheet
  packaging/                    # Build configs for standalone binaries
    pyinstaller.spec            #   Single-file executable (all platforms)
    windows/nsis/               #   Windows installer (NSIS)
    windows/msix/               #   Windows Store package
    linux/flatpak/              #   Flatpak manifest
    linux/appimage/             #   AppImage config
    macos/dmg/                  #   macOS disk image script
  .github/workflows/
    build.yml                   #   CI: lint, test, build binaries per platform
    release.yml                 #   CD: build + create GitHub release on tag push
```

### How It Fits Together

```
+--------------------+          +-------------------+
|   yoto-up-gui      |  uses    |   yoto-up-core    |
|   (PySide6 UI)     +--------->|   (pure Python)   |
|                    |          |                   |
|  MainWindow        |          |  YotoClient       |
|   +-- Pages        |          |   +-- auth        |
|   +-- Widgets      |          |   +-- cards API   |
|   +-- Workers      |          |   +-- devices API |
|       (QThread)    |          |   +-- media API   |
|                    |          |                   |
|  Runs on GUI       |          |  Audio processing |
|  thread only       |          |  Local storage    |
+--------+-----------+          +--------+----------+
         |                               |
         | Background workers            | httpx
         | (own httpx.Client)            |
         v                               v
+------------------------------------------------------+
|              Yoto Cloud Services                     |
|  api.yotoplay.com   login.yotoplay.com               |
+------------------------------------------------------+
```

Workers run API calls on background `QThread`s with their own `httpx.Client` instances (the main client is not thread-safe). `QPixmap` operations stay on the GUI thread; background image loading uses `QImage` and converts on delivery.

## Building from Source

This section is for **developers** contributing to Yoto-UP. End users should use the pre-built releases above.

### Prerequisites

- Python 3.11+
- Git
- FFmpeg (optional, for audio normalization features)

### Setup

```bash
git clone https://github.com/xkjq/yoto-up.git
cd yoto-up

python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

pip install -e ./core
pip install -e "./core[audio]"   # optional audio processing deps
pip install -e ./gui
```

### Run

```bash
yoto-up
```

### Test

```bash
pip install pytest
pytest core/tests/ -v
```

### Build a Standalone Binary

```bash
pip install pyinstaller
pyinstaller packaging/pyinstaller.spec --noconfirm
# Output: dist/yoto-up (or dist/yoto-up.exe on Windows)
```

See [`packaging/README.md`](packaging/README.md) for platform-specific installer builds (NSIS, Flatpak, DMG).

## External Services

| Service | URL | Purpose |
|---------|-----|---------|
| Yoto API | `api.yotoplay.com` | Card CRUD, media upload, icons |
| Yoto OAuth | `login.yotoplay.com` | Device-code authentication |

## License

MIT -- see `LICENSE` for details.
