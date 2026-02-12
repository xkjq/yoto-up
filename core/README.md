# yoto-up-core

Core Python library for managing Yoto player content. This package has **no GUI dependencies** and can be used standalone for scripting, automation, or as a foundation for other interfaces.

## Modules

### `yoto_up.api` -- API Client Layer

| Module | Purpose |
|--------|---------|
| `client.py` | `YotoClient` -- authenticated HTTP client with token management and auto-refresh |
| `auth.py` | OAuth 2.0 device code flow (`request_device_code`, `poll_for_token`) |
| `cards.py` | Card CRUD -- list, get, create, update, delete cards |
| `devices.py` | List registered devices and fetch live device status |
| `icons.py` | Icon/cover art search, download, and upload |
| `media.py` | Audio file upload with SHA-256 integrity and progress callbacks |

### `yoto_up.audio` -- Audio Processing

| Module | Purpose |
|--------|---------|
| `normalize.py` | FFmpeg-based LUFS loudness normalization (`get_audio_loudness`, `normalize_audio`) |
| `trim.py` | Silence detection and trimming via pydub (`detect_silence`, `trim_silence`) |
| `waveform.py` | Waveform amplitude extraction and duration queries via soundfile/numpy |

### `yoto_up.models` -- Pydantic Data Models

| Model | Fields |
|-------|--------|
| `Card` | cardId, title, metadata, content (chapters/tracks), status |
| `Device` | deviceId, name, deviceType, deviceFamily, online |
| `DeviceStatus` | battery, storage, WiFi, temperature, firmware, volumes |
| `TokenData` | access_token, refresh_token, id_token |

### `yoto_up.storage` -- Persistent Storage

| Module | Purpose |
|--------|---------|
| `paths.py` | Cross-platform directory/file paths via `platformdirs` |
| `tokens.py` | Save, load, and delete OAuth tokens |
| `config.py` | `AppSettings` -- load/save JSON settings with defaults |
| `cache.py` | `APICache` (time-based), `IconCache` (disk-based, SHA-256 filenames) |
| `versions.py` | `VersionStore` -- timestamped card version snapshots |

## Installation

```bash
pip install -e ./core               # base
pip install -e "./core[audio]"       # with audio processing deps
```

## Dependencies

**Required:** httpx, pydantic, platformdirs, loguru, pillow, rapidfuzz

**Optional (audio):** pydub, pyloudnorm, numpy, scipy, soundfile, librosa

## Testing

```bash
pip install pytest
python -m pytest core/tests/ -v
```

87 tests covering storage, API client, audio processing, and models.
