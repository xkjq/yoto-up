"""Cross-platform path management for yoto-up.

All persistent file and directory locations are defined here so that
every module in the package (and downstream consumers) can import a
single, canonical set of paths.  Directory creation is deferred to
helpers rather than happening at import time, keeping imports
side-effect-free.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

# ---------------------------------------------------------------------------
# Application identifier
# ---------------------------------------------------------------------------

APP_NAME = "yoto-up"

# ---------------------------------------------------------------------------
# Base directories
# ---------------------------------------------------------------------------

_config_dir = Path(user_config_dir(APP_NAME))
_data_dir = Path(user_data_dir(APP_NAME))
_cache_dir = Path(user_cache_dir(APP_NAME))

# Public aliases for downstream consumers (e.g. the GUI package).
CONFIG_DIR: Path = _config_dir
DATA_DIR: Path = _data_dir
CACHE_DIR: Path = _cache_dir

# ---------------------------------------------------------------------------
# Standard file locations
# ---------------------------------------------------------------------------

# Config directory
TOKENS_FILE = _config_dir / "tokens.json"
UI_STATE_FILE = _config_dir / "ui_state.json"
SETTINGS_FILE = _config_dir / "settings.json"

# Data directory
ICON_CACHE_DIR = _data_dir / "icon_cache"
YOTOICONS_CACHE_DIR = _data_dir / "yotoicons_cache"
UPLOAD_ICON_CACHE_FILE = _data_dir / "icon_upload_cache.json"
API_CACHE_FILE = _data_dir / "api_cache.json"
USER_ICONS_DIR = _data_dir / "user_icons"
VERSIONS_DIR = _data_dir / "card_versions"
PLAYLISTS_FILE = _data_dir / "playlists.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ensure_parents(path: Path) -> Path:
    """Create all parent directories for *path* if they do not exist.

    Returns *path* unchanged so the call can be used inline:

        fp = ensure_parents(TOKENS_FILE)
        fp.write_text(data)
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def atomic_write(
    path: Path,
    data: Union[str, bytes],
    text_mode: bool = True,
) -> None:
    """Write *data* to *path* atomically (write-to-tmp then replace).

    When *text_mode* is ``True`` (the default) the file is opened in
    text mode; pass ``False`` for binary payloads.  The function
    transparently encodes/decodes when the type of *data* does not match
    the chosen mode.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    ensure_parents(tmp)

    mode = "w" if text_mode else "wb"
    with tmp.open(mode) as fh:
        if text_mode:
            fh.write(data.decode() if isinstance(data, bytes) else data)
        else:
            fh.write(data.encode() if isinstance(data, str) else data)

    # Prefer os.replace (atomic on POSIX, near-atomic on Windows).
    try:
        os.replace(tmp, path)
    except OSError:
        # Fallback: rename then direct-write as last resort.
        try:
            tmp.rename(path)
        except OSError:
            try:
                if text_mode:
                    path.write_text(
                        data.decode() if isinstance(data, bytes) else data
                    )
                else:
                    path.write_bytes(
                        data.encode() if isinstance(data, str) else data
                    )
            finally:
                # Clean up orphaned tmp file
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
