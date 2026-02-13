# yoto-up-core

Standalone Python library for the Yoto API, audio processing, and local storage. Has **no GUI dependencies** -- used by the GUI application but can also be used directly for scripting or automation.

## API Client (`yoto_up.api`)

`YotoClient` is an authenticated HTTP client that wraps `httpx`. It loads OAuth tokens from disk, refreshes them when they expire, and persists updates automatically.

```python
from yoto_up.api.client import YotoClient
from yoto_up.api.cards import get_cards

client = YotoClient()
# client.is_authenticated will be True if tokens exist on disk
cards = get_cards(client)
client.close()
```

| Module | What it does |
|--------|-------------|
| `client.py` | `YotoClient` -- HTTP client with automatic token refresh against `api.yotoplay.com` |
| `auth.py` | OAuth 2.0 device-code flow: `request_device_code()` + `poll_for_token()` |
| `cards.py` | List, get, create, update, delete cards |
| `devices.py` | List devices, fetch live device status (battery, WiFi, storage, firmware) |
| `icons.py` | Search and download icon/cover art |
| `media.py` | Upload audio files with SHA-256 integrity verification and progress callbacks |

## Audio Processing (`yoto_up.audio`)

| Module | What it does |
|--------|-------------|
| `normalize.py` | LUFS loudness normalization via FFmpeg (`get_audio_loudness`, `normalize_audio`) |
| `trim.py` | Silence detection and trimming via pydub (`detect_silence`, `trim_silence`) |
| `waveform.py` | Extract amplitude data and query duration via soundfile/numpy |

Audio dependencies are optional. Install them with:

```bash
pip install -e "./core[audio]"
```

This pulls in: pydub, pyloudnorm, numpy, scipy, soundfile, librosa. FFmpeg must be installed separately on the system for normalization to work.

## Data Models (`yoto_up.models`)

Pydantic v2 models for all API entities:

| Model | Key fields |
|-------|-----------|
| `Card` | cardId, title, metadata, content (chapters/tracks), status |
| `Device` | deviceId, name, deviceType, deviceFamily, online |
| `DeviceStatus` | battery, storage, WiFi, temperature, firmware, volumes |
| `TokenData` | access_token, refresh_token, id_token |

## Local Storage (`yoto_up.storage`)

All persistent data is stored under platform-appropriate directories via `platformdirs`:

| Module | What it does |
|--------|-------------|
| `paths.py` | Resolves config/data/cache directories per platform |
| `tokens.py` | Save, load, and delete OAuth tokens (JSON on disk) |
| `config.py` | `AppSettings` -- JSON-backed settings with defaults |
| `cache.py` | `APICache` (time-expiring) + `IconCache` (disk-backed, SHA-256 filenames) |
| `versions.py` | `VersionStore` -- timestamped card snapshots for history |

## Dependencies

**Required:** httpx, pydantic (v2), platformdirs, loguru, pillow, rapidfuzz

**Optional (`[audio]`):** pydub, pyloudnorm, numpy, scipy, soundfile, librosa

## Install & Test

```bash
pip install -e ./core           # base
pip install -e "./core[audio]"  # with audio processing

pip install pytest
pytest core/tests/ -v
```
