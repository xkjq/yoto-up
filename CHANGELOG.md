# Changelog

## 0.1.0 -- Unreleased

### New Features

- **PySide6 GUI application** with six pages: Dashboard, Card Library, Card Editor, Account, Devices, and Audio Tools
- **Core/GUI split architecture** -- `yoto-up-core` (no GUI deps) and `yoto-up-gui` (PySide6) as separate installable packages
- **OAuth 2.0 device code flow** for secure Yoto account authentication
- **Card Library** with paginated grid, keyboard navigation, and mouse wheel scrolling
- **Card Editor** for creating/editing cards with chapters, tracks, metadata, and icons
- **Card Detail Overlay** with edit and delete actions
- **Device Manager** showing live battery, storage, WiFi, temperature, and firmware status
- **Audio Tools** with tabbed interface for LUFS normalization and silence trimming
- **Async image loader** (`ImageLabel` widget) with background downloads, disk caching, and cooperative cancellation
- **Navigation drawer** with smooth slide animation
- **Cross-platform packaging** configs for PyInstaller, NSIS, MSIX, Flatpak, AppImage, and DMG
- **CI/CD workflows** for automated builds and releases via GitHub Actions
- **87 automated tests** covering storage, API, audio processing, and models

### Bug Fixes (Round 1 -- 20 fixes)

1. `closeEvent` on `MainWindow` to close `YotoClient` on window destroy
2. Thread safety -- background workers create dedicated `httpx.Client` instances
3. Worker lifecycle tracking to prevent premature garbage collection
4. Cooperative cancellation in image loader (replaced dangerous `QThread.terminate`)
5. Guard `_auth_headers()` against `None` token (returns `{}` instead of `"Bearer None"`)
6. Fix API endpoint paths for card operations
7. `APICache.put` no longer mutates the caller's dict
8. `trim_silence` empty-audio guard prevents zero-length output
9. `normalize_audio` type hint uses `Callable` instead of builtin `callable`
10. `QPixmap` thread safety -- use `QImage` on background threads
11. `_CoverLabel` centre-crop `QRect` calculation
12. `delete_tokens` no longer re-raises `OSError`
13. `atomic_write` cleans up orphaned `.tmp` files
14. `IconCache` sanitizes `media_id` with SHA-256 to prevent directory traversal
15. `VersionStore` handles empty/whitespace-only titles (falls back to `"untitled"`)
16. `_fmt_duration` treats 0 as a valid duration
17. Card editor age spin boxes treat 0 correctly
18. `_looks_like_icon_url` handles URLs with query parameters
19. `poll_for_token` handles non-JSON error responses
20. Dashboard spacer item leak fix

### Bug Fixes (Round 2 -- 20 fixes)

1. `_remove_worker` lambda now accepts `*_` to match `Signal(object)`
2. Background workers call `_ensure_valid_token()` before reading tokens
3. `calculate_sha256` streams file in 64KB chunks instead of loading entire file
4. `poll_for_token` guards against non-dict JSON response body
5. Audio tools closures snapshot file lists to avoid race conditions
6. `CardDetailOverlay.parentResizeEvent` updates geometry even when hidden
7. `CardLibraryPage.wheelEvent` calls `event.accept()`
8. `gui/pyproject.toml` build-backend corrected to `setuptools.build_meta`
9. PyInstaller spec removes deprecated `block_cipher`
10. PyInstaller spec adds missing `yoto_up.audio.*` hidden imports
11. `DevicesPage` uses separate `_status_worker` to prevent GC during status fetch
12. Device status lambda uses default arg for correct device capture
13. `main.py` removes `is_file()` check for Traversable robustness in bundled apps
14. Flatpak manifest removes broken `python3-deps` module
15. Account settings merge into existing settings instead of clobbering
16. Public path aliases exported (`CONFIG_DIR`, `DATA_DIR`, `CACHE_DIR`)
17. Waveform truncates to `num_samples` before normalizing
18. `DevicesPage` clamps storage percentage to 0-100
19. `NavigationDrawer` sets `_expanded` before `animation.start()` to fix toggle race
