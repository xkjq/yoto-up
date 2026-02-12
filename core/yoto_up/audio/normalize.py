"""Audio normalization using FFmpeg and loudness analysis."""
import json
import subprocess
import shutil
from pathlib import Path
from typing import Callable, Optional
from loguru import logger


def find_ffmpeg() -> str | None:
    """Find ffmpeg binary on PATH."""
    return shutil.which("ffmpeg")


def get_audio_loudness(audio_path: str | Path) -> dict | None:
    """Analyze audio loudness using ffmpeg loudnorm filter.

    Returns dict with keys: input_i (integrated LUFS), input_tp (true peak dB),
    input_lra (loudness range), input_thresh (threshold).
    Returns None if analysis fails.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.error("ffmpeg not found on PATH")
        return None

    try:
        cmd = [
            ffmpeg, "-i", str(audio_path), "-af",
            "loudnorm=print_format=json", "-f", "null", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # Parse the JSON output from stderr
        output = result.stderr
        # Find the last JSON block in the output
        json_start = output.rfind("{")
        json_end = output.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(output[json_start:json_end])
    except Exception as e:
        logger.error(f"Loudness analysis failed: {e}")
    return None


def normalize_audio(
    input_path: str | Path,
    output_path: str | Path,
    target_lufs: float = -16.0,
    target_tp: float = -1.0,
    target_lra: float = 11.0,
    on_progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """Normalize audio file to target loudness using two-pass loudnorm.

    Returns True on success, False on failure.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.error("ffmpeg not found on PATH")
        return False

    try:
        # First pass: analyze
        if on_progress:
            on_progress("Analyzing loudness...")

        analysis = get_audio_loudness(input_path)
        if not analysis:
            return False

        # Second pass: normalize
        if on_progress:
            on_progress("Normalizing audio...")

        measured_i = analysis.get("input_i", "-24.0")
        measured_tp = analysis.get("input_tp", "-2.0")
        measured_lra = analysis.get("input_lra", "7.0")
        measured_thresh = analysis.get("input_thresh", "-34.0")

        af_filter = (
            f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}"
            f":measured_I={measured_i}:measured_TP={measured_tp}"
            f":measured_LRA={measured_lra}:measured_thresh={measured_thresh}"
            f":linear=true:print_format=summary"
        )

        cmd = [
            ffmpeg, "-y", "-i", str(input_path),
            "-af", af_filter,
            "-ar", "44100", "-ac", "2",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            if on_progress:
                on_progress("Normalization complete")
            return True
        else:
            logger.error(f"Normalization failed: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Normalization error: {e}")
        return False
