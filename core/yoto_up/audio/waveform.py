"""Waveform analysis and visualization data generation."""
from pathlib import Path
from typing import Optional
from loguru import logger


def get_waveform_data(
    audio_path: str | Path,
    num_samples: int = 200,
) -> list[float] | None:
    """Extract waveform amplitude data from audio file.

    Returns list of normalized amplitude values (0.0 to 1.0) sampled
    evenly across the file duration. Returns None if analysis fails.

    Requires numpy and soundfile (optional dependencies).
    """
    try:
        import numpy as np
        import soundfile as sf
    except ImportError:
        logger.error("numpy and soundfile required for waveform analysis")
        return None

    try:
        data, samplerate = sf.read(str(audio_path))

        # Convert to mono if stereo
        if data.ndim > 1:
            data = data.mean(axis=1)

        # Resample to num_samples points
        chunk_size = max(1, len(data) // num_samples)
        samples = []
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            samples.append(float(np.abs(chunk).max()))

        # Truncate to requested number of samples BEFORE normalizing
        samples = samples[:num_samples]

        # Normalize to 0-1
        peak = max(samples) if samples else 1.0
        if peak > 0:
            samples = [s / peak for s in samples]

        return samples

    except Exception as e:
        logger.error(f"Waveform extraction failed: {e}")
        return None


def get_audio_duration(audio_path: str | Path) -> float | None:
    """Get audio file duration in seconds using soundfile or ffprobe."""
    try:
        import soundfile as sf
        info = sf.info(str(audio_path))
        return info.duration
    except Exception:
        pass

    # Fallback to ffprobe
    try:
        import subprocess
        import shutil
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(audio_path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
    except Exception:
        pass

    return None
