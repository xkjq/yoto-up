# Packaging

Build configs for producing standalone Yoto-UP binaries. End users should not need to build these themselves -- pre-built binaries are published as [GitHub Releases](https://github.com/xkjq/yoto-up/releases) by the CI/CD pipeline.

## PyInstaller (all platforms)

The primary build method. Produces a single-file executable with no external dependencies.

```bash
pip install -e ./core -e ./gui pyinstaller
pyinstaller packaging/pyinstaller.spec --noconfirm
```

Output: `dist/yoto-up` (Linux/macOS) or `dist/yoto-up.exe` (Windows).

The spec file (`pyinstaller.spec`):
- Entry point: `gui/yoto_up_gui/main.py`
- Bundles both `core/` and `gui/` packages
- Includes all hidden imports (API, storage, audio, models, PySide6, httpx, pydantic)
- Embeds `gui/yoto_up_gui/resources/` (stylesheet)
- Produces a windowed (no-console) binary
- UPX compression enabled

## Platform Installers

These wrap the PyInstaller output into platform-native installer formats.

### Windows -- NSIS

`windows/nsis/installer.nsi`

Produces `YotoUP-Setup.exe` -- a traditional Windows installer with:
- Program Files installation
- Start Menu + Desktop shortcuts
- Registry-based uninstaller

Requires [NSIS](https://nsis.sourceforge.io/) on the build machine. Expects PyInstaller output in `dist/yoto-up/`.

### Windows -- MSIX

`windows/msix/`

Placeholder for Windows Store / sideloading package. Not yet populated.

### Linux -- Flatpak

`linux/flatpak/com.yotoup.YotoUp.yml`

Flatpak manifest using `org.freedesktop.Platform` 23.08 runtime. Builds core and GUI via pip inside the Flatpak sandbox.

```bash
flatpak-builder --user --install --force-clean build-dir \
    packaging/linux/flatpak/com.yotoup.YotoUp.yml
```

Permissions: network, X11/Wayland, DRI, home (read-only), notifications.

### Linux -- AppImage

`linux/appimage/`

Placeholder for AppImage config. Not yet populated.

### macOS -- DMG

`macos/dmg/create_dmg.sh`

Shell script that wraps a `.app` bundle into a `.dmg` disk image via `hdiutil`. Expects a `dist/Yoto-UP.app` from PyInstaller.

```bash
bash packaging/macos/dmg/create_dmg.sh
# Output: dist/YotoUP.dmg
```

## CI/CD

GitHub Actions handles all builds automatically:

**`.github/workflows/build.yml`** -- runs on every push/PR to `main`:
1. Lint (ruff) and type-check
2. Unit tests on Python 3.11 + 3.12
3. GUI compile-check (no display server needed)
4. Build binaries via PyInstaller on Windows, macOS, and Linux
5. Upload artifacts

**`.github/workflows/release.yml`** -- runs on tag push (`v*`):
1. Build + test on all three platforms
2. Upload binaries as GitHub Release assets

The release creates downloadable files:
- `yoto-up.exe` (Windows)
- `yoto-up` (macOS)
- `yoto-up` (Linux)
