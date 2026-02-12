# Packaging

Build configurations for distributing Yoto-UP as standalone binaries.

## PyInstaller (all platforms)

Single-file executable via `pyinstaller.spec`:

```bash
pip install pyinstaller
pyinstaller packaging/pyinstaller.spec
```

The spec file:
- Bundles both `core/` and `gui/` packages
- Includes all hidden imports (API, storage, audio, models)
- Embeds GUI resources (stylesheets)
- Produces a windowed (no-console) binary

Output: `dist/yoto-up` (or `dist/yoto-up.exe` on Windows).

## Windows

### NSIS Installer

Config in `packaging/windows/nsis/`. Produces a traditional `.exe` installer with Start Menu shortcuts and uninstaller.

### MSIX

Config in `packaging/windows/msix/`. Produces a modern Windows app package for Microsoft Store or sideloading.

## Linux

### Flatpak

Manifest: `packaging/linux/flatpak/com.yotoup.YotoUp.yml`

```bash
flatpak-builder --user --install --force-clean build-dir \
    packaging/linux/flatpak/com.yotoup.YotoUp.yml
```

Uses the `org.freedesktop.Platform` 23.08 runtime. Installs core and GUI via pip.

### AppImage

Config in `packaging/linux/appimage/`. Produces a portable single-file `.AppImage`.

## macOS

### DMG

Config in `packaging/macos/dmg/`. Produces a `.dmg` disk image for drag-and-drop installation.

## CI/CD

GitHub Actions workflows automate builds:

- `.github/workflows/build.yml` -- runs tests and builds on push/PR
- `.github/workflows/release.yml` -- builds platform binaries on tag push and creates GitHub releases
