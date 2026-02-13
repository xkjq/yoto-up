from pathlib import Path
import os
import json
from typing import Any
try:
    from platformdirs import user_config_dir, user_data_dir, user_cache_dir
except Exception:
    # Minimal fallback when platformdirs isn't available (e.g., during early import)
    def user_config_dir(appname: str = "yoto-up") -> str:
        return str(Path.home() / f".{appname}")
    def user_data_dir(appname: str = "yoto-up") -> str:
        return str(Path.home() / f".{appname}" / "data")
    def user_cache_dir(appname: str = "yoto-up") -> str:
        return str(Path.home() / f".{appname}" / "cache")

APP_NAME = "yoto-up"

# Respect FLET_APP_STORAGE_DATA when provided by the hosting environment (Flet).
# If present, use that as the base for data/cache; otherwise prefer platformdirs.
FLET_APP_STORAGE_DATA = os.getenv("FLET_APP_STORAGE_DATA")

_BASE_DATA_DIR = Path(FLET_APP_STORAGE_DATA) if FLET_APP_STORAGE_DATA else Path(user_data_dir(APP_NAME))
_BASE_CONFIG_DIR = Path(user_config_dir(APP_NAME))
_BASE_CACHE_DIR = Path(user_cache_dir(APP_NAME))

# Ensure directories exist
try:
    _BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _BASE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

# Standardized file and directory locations
TOKENS_FILE = _BASE_CONFIG_DIR / "tokens.json"
UI_STATE_FILE = _BASE_CONFIG_DIR / "ui_state.json"

OFFICIAL_ICON_CACHE_DIR = _BASE_DATA_DIR / ".yoto_icon_cache"
YOTOICONS_CACHE_DIR = _BASE_DATA_DIR / ".yotoicons_cache"
UPLOAD_ICON_CACHE_FILE = _BASE_DATA_DIR / ".yoto_icon_upload_cache.json"
API_CACHE_FILE = _BASE_DATA_DIR / ".yoto_api_cache.json"
STAMPS_DIR = _BASE_DATA_DIR / ".stamps"
USER_ICONS_DIR = _BASE_DATA_DIR / ".user_icons"
VERSIONS_DIR = _BASE_DATA_DIR / ".card_versions"
PLAYLISTS_FILE = _BASE_DATA_DIR / "playlists.json"

# Convenience helpers
def ensure_parents(path: Path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path

def atomic_write(path: Path, data: str | bytes, text_mode: bool = True):
    tmp = Path(str(path) + ".tmp")
    ensure_parents(tmp)
    mode = "w" if text_mode else "wb"
    with tmp.open(mode) as f:
        if text_mode:
            if isinstance(data, bytes):
                f.write(data.decode())
            else:
                f.write(data)
        else:
            if isinstance(data, str):
                f.write(data.encode())
            else:
                f.write(data)
    try:
        tmp.replace(path)
    except Exception:
        try:
            tmp.rename(path)
        except Exception:
            if text_mode:
                if isinstance(data, bytes):
                    path.write_text(data.decode())
                else:
                    path.write_text(data)
            else:
                if isinstance(data, str):
                    path.write_bytes(data.encode())
                else:
                    path.write_bytes(data)


# Ensure standard app-specific subdirectories exist under the base data dir so callers
# can depend on them being present without duplicating mkdir logic elsewhere.
try:
    OFFICIAL_ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
try:
    YOTOICONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
try:
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
try:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
try:
    USER_ICONS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass



def load_playlists(default: Any | None = None) -> Any:
    """Load persisted playlists from PLAYLISTS_FILE. Returns default if file missing/invalid."""
    if default is None:
        default = []
    try:
        if not PLAYLISTS_FILE.exists():
            return default
        text = PLAYLISTS_FILE.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return default


def save_playlists(playlists: Any) -> None:
    """Persist playlists (list/dict) to PLAYLISTS_FILE atomically."""
    try:
        data = json.dumps(playlists, ensure_ascii=False, indent=2)
        atomic_write(PLAYLISTS_FILE, data, text_mode=True)
    except Exception:
        # best-effort; don't raise to avoid disrupting the UI
        pass


__all__ = [
    "TOKENS_FILE",
    "UI_STATE_FILE",
    "OFFICIAL_ICON_CACHE_DIR",
    "YOTOICONS_CACHE_DIR",
    "UPLOAD_ICON_CACHE_FILE",
    "API_CACHE_FILE",
    "USER_ICONS_DIR",
    "STAMPS_DIR",
    "VERSIONS_DIR",
    "PLAYLISTS_FILE",
    "FLET_APP_STORAGE_DATA",
    "ensure_parents",
    "atomic_write",
    "load_playlists",
    "save_playlists",
]
