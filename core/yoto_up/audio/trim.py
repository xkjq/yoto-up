"""Audio silence detection and trimming."""
from pathlib import Path
from typing import Optional
from loguru import logger


def detect_silence(
    audio_path: str | Path,
    silence_thresh_db: float = -40.0,
    min_silence_ms: int = 500,
) -> list[tuple[float, float]] | None:
    """Detect silent regions in audio file.

    Returns list of (start_seconds, end_seconds) tuples for silent regions.
    Returns None if detection fails.

    Requires pydub (optional dependency).
    """
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_silence as _detect_silence
    except ImportError:
        logger.error("pydub required for silence detection")
        return None

    try:
        audio = AudioSegment.from_file(str(audio_path))
        silent_ranges = _detect_silence(audio, min_silence_len=min_silence_ms, silence_thresh=silence_thresh_db)
        return [(start / 1000.0, end / 1000.0) for start, end in silent_ranges]
    except Exception as e:
        logger.error(f"Silence detection failed: {e}")
        return None


def trim_silence(
    input_path: str | Path,
    output_path: str | Path,
    silence_thresh_db: float = -40.0,
    min_silence_ms: int = 500,
    keep_start_ms: int = 100,
    keep_end_ms: int = 100,
) -> bool:
    """Trim leading and trailing silence from audio file.

    Returns True on success, False on failure.
    """
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_leading_silence
    except ImportError:
        logger.error("pydub required for silence trimming")
        return False

    try:
        audio = AudioSegment.from_file(str(input_path))

        # Trim leading silence
        start_trim = max(0, detect_leading_silence(audio, silence_threshold=silence_thresh_db) - keep_start_ms)

        # Trim trailing silence
        reversed_audio = audio.reverse()
        end_trim = max(0, detect_leading_silence(reversed_audio, silence_threshold=silence_thresh_db) - keep_end_ms)

        end_pos = len(audio) - end_trim
        if end_pos <= start_trim:
            logger.warning("Trimming would produce empty audio; skipping trim")
            return False

        trimmed = audio[start_trim:end_pos]

        # Export
        output_format = Path(output_path).suffix.lstrip(".")
        if output_format == "":
            output_format = "mp3"
        trimmed.export(str(output_path), format=output_format)

        return True
    except Exception as e:
        logger.error(f"Silence trimming failed: {e}")
        return False
