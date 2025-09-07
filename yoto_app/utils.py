from pathlib import Path
import os

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"}


def find_audio_files(folder: str):
    p = Path(folder)
    if not p.exists() or not p.is_dir():
        return []
    files = [str(f) for f in sorted(p.iterdir()) if f.suffix.lower() in AUDIO_EXTS and f.is_file()]
    return files


class FileRow:
    """Lightweight representation of a file row used by the UI.
    This class is intentionally small so callers can construct their own flet controls
    using the filename and status/progress values.
    """
    def __init__(self, filename: str):
        self.filename = filename
        self.basename = os.path.basename(filename)
        self.path = filename
