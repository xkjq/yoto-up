"""Analyze a set of audio files to find common intro/outro segments and
optionally trim them.

Approach (lightweight, no cloud/ASR required):
- Extract short segment from start (intro) and end (outro) of each file
  (configurable seconds).
- Compute MFCC-based summary feature for each segment and compare via
  cosine similarity to find groups of files that share the same intro/outro.
- Provide helpers to locate the best-matching location in a file (sliding
  window on MFCC mean) and to trim audio using pydub.

Notes / limitations:
- This is an approximate, signal-based approach. If you need text-aware
  matching (exact repeated spoken words) use an ASR (OpenAI/whisper/others)
  to transcribe the start/end of each file and compare text — that will be
  more reliable for detecting identical spoken intros/outros.
- The algorithm uses librosa for feature extraction and pydub for writing
  trimmed files. The repository already includes these packages in
  `requirements.txt`.
"""

from typing import List, Tuple, Dict, Union
import os
import numpy as np

from loguru import logger


def sliding_best_match_position(
    path: str,
    template_feat,
    seg_seconds: float = 10.0,
    search_seconds: float = 60.0,
    sr: int = 22050,
    hop_seconds: float = 0.5,
) -> Tuple[float, float]:
    """Search for the best-matching start position of a segment similar to template.

    Returns (best_start_seconds, best_score). For intro searches we typically
    search the first `search_seconds` of the file. For outros, the caller should
    pass an appropriately-positioned slice or reverse logic (we keep it simple
    and search from the file start here but `analyze_files` already looked at the end).
    """
    # Legacy heavy-search routine removed. Use the per-window analyzer or
    # DTW-based helpers in `yoto_app.analysis` directly. Keep a compatibility
    # stub to avoid breaking imports.
    raise NotImplementedError(
        "sliding_best_match_position was removed. Use per_window_common_prefix or analyze_files for common-prefix detection."
    )


def per_second_common_prefix(
    paths: List[str],
    side: str = 'intro',
    max_seconds: int = 10,
    sr: int = 22050,
    n_mfcc: int = 13,
    similarity_threshold: float = 0.95,
    min_files_fraction: float = 0.75,
) -> Dict[str, object]:
    # Lazy import to avoid import-time failures when analysis deps are not present
    try:
        from .analysis import per_second_common_prefix as _analysis_per_second_common_prefix
    except Exception as e:
        # Analysis unavailable; return a conservative no-match result
        return {
            'seconds_matched': 0.0,
            'per_second_sim': [],
            'per_file_per_second': {},
            'max_seconds': int(max_seconds),
        }
    return _analysis_per_second_common_prefix(paths=paths, side=side, max_seconds=max_seconds, sr=sr, n_mfcc=n_mfcc, similarity_threshold=similarity_threshold, min_files_fraction=min_files_fraction)


def per_window_common_prefix(
    paths: List[str],
    side: str = 'intro',
    max_seconds: float = 10.0,
    window_seconds: float = 0.1,
    sr: int = 22050,
    n_mfcc: int = 13,
    similarity_threshold: float = 0.95,
    min_files_fraction: float = 0.75,
) -> Dict[str, object]:
    # Lazy import to avoid import-time failures when analysis deps are not present
    try:
        from .analysis import per_window_common_prefix as _analysis_per_window_common_prefix
    except Exception:
        logger.debug("per_window_common_prefix: analysis helpers unavailable")
        return {
            'seconds_matched': 0.0,
            'windows_matched': 0,
            'per_window_frac': [],
            'per_file_per_window': {},
            'max_seconds': float(max_seconds),
            'window_seconds': float(window_seconds),
        }
    return _analysis_per_window_common_prefix(paths=paths, side=side, max_seconds=max_seconds, window_seconds=window_seconds, sr=sr, n_mfcc=n_mfcc, similarity_threshold=similarity_threshold, min_files_fraction=min_files_fraction)


def _compute_mfcc_sequence(path: str, side: str, seconds: float, sr: int = 22050, n_mfcc: int = 20, n_fft: int = 2048, hop_length: int = 512) -> np.ndarray:
    try:
        from .analysis import _compute_mfcc_sequence as _analysis_compute_mfcc_sequence
    except Exception:
        raise RuntimeError("analysis helpers unavailable")
    return _analysis_compute_mfcc_sequence(path=path, side=side, seconds=seconds, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length)


def _dtw_prefix_similarity(a_path: str, b_path: str, side: str, max_seconds: float, sr: int = 22050, n_mfcc: int = 20, hop_length: int = 512, step_seconds: float = 0.25, dtw_threshold: float = 0.5) -> tuple:
    try:
        from .analysis import _dtw_prefix_similarity as _analysis_dtw_prefix_similarity
    except Exception:
        raise RuntimeError("analysis DTW helper unavailable")
    return _analysis_dtw_prefix_similarity(a_path=a_path, b_path=b_path, side=side, max_seconds=max_seconds, sr=sr, n_mfcc=n_mfcc, hop_length=hop_length, step_seconds=step_seconds, dtw_threshold=dtw_threshold)

def common_prefix_duration(*args, **kwargs):
    """Legacy API: keep in analysis for callers that want the heavier frame-based method.

    This was originally in intro_outro; we preserve a thin wrapper here that
    imports the original implementation if available. For now, this is a
    placeholder that raises NotImplementedError to encourage callers to use
    the lighter-weight per-window analyzer.
    """
    raise NotImplementedError("common_prefix_duration was removed. Use per_window_common_prefix or per_second_common_prefix instead.")



def trim_audio_file(
    src_path: str,
    dest_path: str,
    remove_intro_seconds: float = 0.0,
    remove_outro_seconds: float = 0.0,
    keep_silence_ms: int = 0,
) -> None:
    """Trim `remove_intro_seconds` from start and `remove_outro_seconds` from end.

    Saves trimmed file to `dest_path`. Uses pydub which preserves format if the
    destination extension is set accordingly.
    """
    try:
        from pydub import AudioSegment
    except Exception:
        raise RuntimeError("pydub not available: trimming is unavailable")
    audio = AudioSegment.from_file(src_path)
    start_ms = int(remove_intro_seconds * 1000)
    end_ms = int(remove_outro_seconds * 1000)
    new_start = min(max(0, start_ms - keep_silence_ms), len(audio))
    new_end = max(0, len(audio) - end_ms + keep_silence_ms)
    if new_end <= new_start:
        # If trimming would remove everything, write a tiny silent file instead
        out = AudioSegment.silent(duration=1000)
    else:
        out = audio[new_start:new_end]
    # Ensure parent dir exists
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    out.export(dest_path, format=os.path.splitext(dest_path)[1].lstrip("."))


if __name__ == "__main__":
    # Quick demo when run as a script
    import argparse

    parser = argparse.ArgumentParser(description="Analyze and optionally trim common intros/outros")
    parser.add_argument("files", nargs="+", help="Audio files to analyze")
    parser.add_argument("--side", choices=["intro", "outro"], default="intro")
    parser.add_argument("--seconds", type=float, default=10.0, help="segment seconds to compare")
    parser.add_argument("--threshold", type=float, default=0.75)
    args = parser.parse_args()

    result = analyze_files(args.files, side=args.side, seconds=args.seconds, similarity_threshold=args.threshold)
    print("Template:", result.get("template"))
    print("Matches (path,score):")
    matches = list(result.get("matches") or [])
    for m in matches:
        print(" ", m)
