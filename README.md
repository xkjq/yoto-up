# Yoto-UP

<img src="art.jpeg" alt="Artwork preview" style="max-width:100%;height:auto;">

A desktop application and Python library for managing Yoto player content &mdash; cards, audio, devices, and more.

## Highlights

- **Card Library** &mdash; browse, search, and inspect all your Yoto cards
- **Card Editor** &mdash; create and edit cards with chapters, tracks, and metadata
- **Device Manager** &mdash; view registered Yoto players, battery, storage, and firmware
- **Audio Tools** &mdash; normalize loudness (LUFS), trim silence, and preview waveforms
- **Icon Picker** &mdash; search and select cover art for cards
- **Async Image Loading** &mdash; background image downloads with disk caching
- **OAuth Device Flow** &mdash; secure login via Yoto's device authorization flow
- **Cross-Platform** &mdash; runs on Linux, macOS, and Windows

## Architecture

The project is split into two installable Python packages:

| Package | Path | Description |
|---------|------|-------------|
| **yoto-up-core** | `core/` | API client, models, storage, audio processing (no GUI deps) |
| **yoto-up-gui** | `gui/` | PySide6 desktop application that depends on the core |

```
yoto-up/
  core/           # yoto-up-core Python package
    yoto_up/
      api/        # HTTP client, auth, cards, devices, icons, media upload
      audio/      # normalize, trim silence, waveform extraction
      models/     # Pydantic models (Card, Device, User/TokenData)
      storage/    # tokens, settings, cache, versions, paths
  gui/            # yoto-up-gui Python package
    yoto_up_gui/
      pages/      # Dashboard, Card Library, Card Editor, Account, Devices, Audio Tools
      widgets/    # NavigationDrawer, CardTile, ImageLabel, IconPicker
      resources/  # Stylesheets and assets
  packaging/      # PyInstaller, NSIS, Flatpak, AppImage, DMG configs
  .github/        # CI/CD workflows (build + release)
```

## Installation

### Requirements

- Python 3.11+
- FFmpeg (optional, for audio normalization)

### From Source (recommended for development)

```bash
git clone https://github.com/xkjq/yoto-up.git
cd yoto-up

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install both packages in editable mode
pip install -e ./core
pip install -e "./core[audio]"   # optional audio dependencies
pip install -e ./gui
```

### Running the GUI

```bash
yoto-up
# or
python -m yoto_up_gui.main
```

### Running Tests

```bash
pip install pytest
python -m pytest core/tests/ -v
```

## Usage

### GUI Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Overview with quick actions and recent cards |
| **Card Library** | Paginated grid of all cards with search |
| **Card Editor** | Create/edit cards with chapters, tracks, and metadata |
| **Account** | Login/logout via device code flow, app settings, data management |
| **Devices** | View registered Yoto players with live status (battery, storage, WiFi) |
| **Audio Tools** | Batch normalize loudness, detect and trim silence |

### Core Library (programmatic use)

```python
from yoto_up.api.client import YotoClient
from yoto_up.api.cards import get_cards

client = YotoClient()
# After authenticating:
cards = get_cards(client)
for card in cards:
    print(card.title, card.cardId)
client.close()
```

## Packaging

Pre-built binaries can be produced for all major platforms:

| Platform | Format | Config |
|----------|--------|--------|
| Windows | NSIS installer | `packaging/windows/nsis/` |
| Windows | MSIX | `packaging/windows/msix/` |
| Linux | Flatpak | `packaging/linux/flatpak/` |
| Linux | AppImage | `packaging/linux/appimage/` |
| macOS | DMG | `packaging/macos/dmg/` |
| All | PyInstaller | `packaging/pyinstaller.spec` |

See `packaging/README.md` for build instructions.

## CI/CD

GitHub Actions workflows are in `.github/workflows/`:

- **build.yml** &mdash; lint, test, and build on every push/PR
- **release.yml** &mdash; build platform binaries and create GitHub releases on tags

## License

MIT &mdash; see `LICENSE` for details.
