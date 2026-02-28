import os
import tempfile
from pathlib import Path
import sys
import importlib.util
from typing import cast, Any
import shutil
from loguru import logger

from yoto_up.paths import FLET_APP_STORAGE_DATA

# Audio playback availability
try:
    import simpleaudio as _simpleaudio

    HAS_SIMPLEAUDIO = True
except Exception:
    logger.warning("simpleaudio module not available; audio playback disabled")
    _simpleaudio = None
    HAS_SIMPLEAUDIO = False

# Ensure FLET storage env vars are set to a sane default if not provided by the host.
os.environ.setdefault("FLET_SECRET_KEY", os.urandom(12).hex())
if os.getenv("FLET_APP_STORAGE_TEMP") is None:
    os.environ["FLET_APP_STORAGE_TEMP"] = tempfile.mkdtemp()
if os.getenv("FLET_APP_STORAGE_DATA") is None:
    if FLET_APP_STORAGE_DATA:
        os.environ["FLET_APP_STORAGE_DATA"] = str(FLET_APP_STORAGE_DATA)
    else:
        os.environ["FLET_APP_STORAGE_DATA"] = str(Path("storage") / "data")

# Ensure matplotlib will use a writable config/cache dir when the app is frozen by PyInstaller.
try:
    mpl_cfg = os.path.join(os.environ.get("FLET_APP_STORAGE_DATA", tempfile.gettempdir()), "yoto_up_matplotlib")
    os.environ.setdefault("MPLCONFIGDIR", mpl_cfg)
    os.makedirs(mpl_cfg, exist_ok=True)
except Exception:
    logger.warning(
        "Failed to set up matplotlib config dir; font cache issues may occur"
    )

# Prefer a normal import so PyInstaller will detect and include the module.
# Fall back to loading from the source file only when the normal import fails
# (useful in some dev workflows).
try:
    import audio_adjust_utils  # type: ignore
except Exception:
    logger.warning("audio_adjust_utils import failed; attempting fallback load")
    audio_adjust_utils = cast(Any, None)  # type: ignore
    audio_adjust_utils_path = os.path.join(
        os.path.dirname(__file__), "audio_adjust_utils.py"
    )
    if os.path.exists(audio_adjust_utils_path):
        try:
            _spec = importlib.util.spec_from_file_location(
                "audio_adjust_utils", audio_adjust_utils_path
            )
            if _spec and _spec.loader:
                audio_adjust_utils = importlib.util.module_from_spec(_spec)  # type: ignore
                sys.modules["audio_adjust_utils"] = audio_adjust_utils
                _spec.loader.exec_module(audio_adjust_utils)  # type: ignore
        except Exception:
            audio_adjust_utils = cast(Any, None)  # type: ignore


