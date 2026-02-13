# Changelog

## 0.1.0 -- Unreleased

Complete rewrite of Yoto-UP: new PySide6 desktop GUI, core/gui package split, standalone binary distribution via PyInstaller, and CI/CD pipelines for automated cross-platform releases.

### What's New

- **Standalone desktop app** -- download a single binary for Windows, macOS, or Linux. No Python required.
- **PySide6 GUI** replacing the previous Flet-based interface, with Catppuccin Mocha dark theme
- **Core/GUI package split** -- `yoto-up-core` (API, models, storage, audio) works independently of the GUI
- **Dashboard** -- welcome banner, library stats, quick actions, recent cards grid
- **Card Library** -- paginated card grid with search, keyboard navigation, mouse-wheel scrolling
- **Card Editor** -- create/edit cards with chapters, tracks, metadata, icon picker
- **Card Detail Overlay** -- slide-in panel with card info, edit and delete actions
- **Device Manager** -- live status per device: battery, storage, WiFi, temperature, firmware
- **Audio Tools** -- tabbed interface for LUFS normalization, silence trimming, waveform preview
- **Account page** -- OAuth 2.0 device-code login, app settings, cache management
- **Async image loading** -- background downloads with disk caching and cooperative cancellation
- **Animated navigation drawer** -- smooth slide-in/out sidebar
- **Cross-platform packaging** -- PyInstaller spec, NSIS installer, Flatpak manifest, DMG script
- **CI/CD** -- GitHub Actions for lint, test, build (Windows/macOS/Linux), and automated releases on tag push
- **87 automated tests** covering storage, API client, audio processing, and models

### Bug Fixes (Round 1 -- 20 fixes)

1. `MainWindow.closeEvent` closes `YotoClient` on window destroy
2. Background workers create dedicated `httpx.Client` instances (thread safety)
3. Worker lifecycle tracking prevents premature garbage collection
4. Cooperative cancellation in image loader (replaced `QThread.terminate`)
5. `_auth_headers()` guards against `None` token
6. Corrected API endpoint paths for card operations
7. `APICache.put` no longer mutates the caller's dict
8. `trim_silence` guards against empty audio producing zero-length output
9. `normalize_audio` type hint uses `Callable` instead of builtin `callable`
10. `QPixmap` thread safety -- `QImage` used on background threads
11. `_CoverLabel` centre-crop `QRect` calculation corrected
12. `delete_tokens` no longer re-raises `OSError`
13. `atomic_write` cleans up orphaned `.tmp` files
14. `IconCache` sanitizes `media_id` with SHA-256 (prevents directory traversal)
15. `VersionStore` handles empty/whitespace titles (falls back to `"untitled"`)
16. `_fmt_duration` treats 0 as a valid duration
17. Card editor age spin boxes treat 0 correctly
18. `_looks_like_icon_url` handles URLs with query parameters
19. `poll_for_token` handles non-JSON error responses
20. Dashboard spacer item leak fix

### Bug Fixes (Round 2 -- 19 fixes)

1. `_remove_worker` lambda accepts `*_` to match `Signal(object)`
2. Background workers call `_ensure_valid_token()` before reading tokens
3. `calculate_sha256` streams in 64KB chunks instead of loading entire file
4. `poll_for_token` guards against non-dict JSON response body
5. Audio tools closures snapshot file lists to avoid race conditions
6. `CardDetailOverlay.parentResizeEvent` updates geometry even when hidden
7. `CardLibraryPage.wheelEvent` calls `event.accept()`
8. `gui/pyproject.toml` build-backend corrected to `setuptools.build_meta`
9. PyInstaller spec removes deprecated `block_cipher`
10. PyInstaller spec adds missing `yoto_up.audio.*` hidden imports
11. `DevicesPage` uses separate `_status_worker` to prevent GC during status fetch
12. Device status lambda uses default arg for correct device capture
13. `main.py` removes `is_file()` check for `Traversable` robustness in bundled apps
14. Flatpak manifest removes broken `python3-deps` module
15. Account settings merge into existing settings instead of clobbering
16. Public path aliases exported (`CONFIG_DIR`, `DATA_DIR`, `CACHE_DIR`)
17. Waveform truncates to `num_samples` before normalizing
18. `DevicesPage` clamps storage percentage to 0-100
19. `NavigationDrawer` sets `_expanded` before `animation.start()` to fix toggle race
