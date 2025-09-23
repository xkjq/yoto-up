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
import librosa
from librosa.feature import mfcc as _librosa_mfcc
from pydub import AudioSegment


def load_audio_mono(path: str, sr: int = 22050) -> Tuple[np.ndarray, Union[int, float]]:
    """Load audio file and return mono waveform and sample rate.

    Uses librosa.load which can open many formats (via soundfile/audioread).
    """
    y, sr_out = librosa.load(path, sr=sr, mono=True)
    # librosa may return numpy integer types; coerce to Python int for clarity
    try:
        sr_out = int(sr_out)
    except Exception:
        pass
    return y, sr_out


def mfcc_summary(y: np.ndarray, sr: int, n_mfcc: int = 20) -> np.ndarray:
    """Return a fixed-size summary vector for audio `y` using MFCC means.

    We compute MFCCs and return the mean and std across time (concatenated).
    """
    if y.size == 0:
        return np.zeros(n_mfcc * 2, dtype=float)
    mf = _librosa_mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    mean = np.mean(mf, axis=1)
    std = np.std(mf, axis=1)
    return np.concatenate([mean, std])


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return 0.0
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def segment_feature(path: str, side: str = "intro", seconds: float = 10.0, sr: int = 22050) -> np.ndarray:
    """Compute summary feature for the start (intro) or end (outro) segment.

    side: 'intro' or 'outro'
    seconds: duration of the extracted segment in seconds
    """
    y, sr_out = load_audio_mono(path, sr=sr)
    if y.size == 0:
        return np.zeros(40, dtype=float)
    n = int(seconds * sr_out)
    if side == "intro":
        seg = y[:n]
    else:
        seg = y[-n:]
    return mfcc_summary(seg, int(sr_out))


def analyze_files(
    paths: List[str],
    side: str = "intro",
    seconds: float = 10.0,
    sr: int = 22050,
    similarity_threshold: float = 0.75,
) -> Dict[str, object]:
    """Analyze a list of files and return similarity info.

    Returns a dict with:
    - 'features': mapping path -> feature vector
    - 'pairs': list of (path_a, path_b, score) for pairs with score >= threshold
    - 'clusters': simple grouping where each file with average similarity >= threshold
      to a chosen template is considered matching the common intro/outro
    - 'template': path chosen as template (the one with highest mean similarity)
    """
    feats: Dict[str, np.ndarray] = {}
    for p in paths:
        try:
            feats[p] = segment_feature(p, side=side, seconds=seconds, sr=sr)
        except Exception:
            feats[p] = np.zeros(40, dtype=float)

    # pairwise similarities
    pairs = []
    paths_list = list(paths)
    for i in range(len(paths_list)):
        for j in range(i + 1, len(paths_list)):
            a = feats[paths_list[i]]
            b = feats[paths_list[j]]
            score = cosine_similarity(a, b)
            pairs.append((paths_list[i], paths_list[j], score))

    # Choose a template: file with highest mean similarity to others
    mean_scores = {}
    for p in paths_list:
        s = [cosine_similarity(feats[p], feats[q]) for q in paths_list if q != p]
        mean_scores[p] = float(np.mean(s)) if s else 0.0
    template = max(mean_scores.items(), key=lambda kv: kv[1])[0] if mean_scores else None

    # Files matching template above threshold
    matches = []
    if template:
        for p in paths_list:
            score = cosine_similarity(feats[template], feats[p])
            if score >= similarity_threshold:
                matches.append((p, score))

    return {
        "features": feats,
        "pairs": pairs,
        "template": template,
        "matches": matches,
        "mean_scores": mean_scores,
    }


def sliding_best_match_position(
    path: str,
    template_feat: np.ndarray,
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
    y, sr_out = load_audio_mono(path, sr=sr)
    if y.size == 0:
        return 0.0, 0.0
    seg_len = int(seg_seconds * sr_out)
    hop = int(hop_seconds * sr_out)
    max_start = min(int(search_seconds * sr_out), max(0, len(y) - seg_len))
    best_score = -1.0
    best_start = 0
    for start in range(0, max_start + 1, max(1, hop)):
        window = y[start : start + seg_len]
        feat = mfcc_summary(window, int(sr_out))
        score = cosine_similarity(feat, template_feat)
        if score > best_score:
            best_score = score
            best_start = start
    return best_start / float(sr_out), best_score


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
