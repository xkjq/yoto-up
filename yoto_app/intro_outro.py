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
from librosa.feature import delta as _librosa_delta, rms as _librosa_rms, spectral_centroid as _librosa_spectral_centroid
from pydub import AudioSegment
from pathlib import Path
import hashlib
import concurrent.futures

# Simple in-memory cache for computed segment features to avoid recomputing when
# the same file/parameters are analyzed repeatedly during a session.
_FEATURE_CACHE: Dict[Tuple[str, str, float, int, int], np.ndarray] = {}

from loguru import logger


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
    # Use librosa MFCC computation
    mf = _librosa_mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    # delta (first derivative) adds temporal change information
    try:
        delta = _librosa_delta(mf)
    except Exception:
        delta = np.zeros_like(mf)
    mf_mean = np.mean(mf, axis=1)
    delta_mean = np.mean(delta, axis=1)
    # add simple spectral descriptors (rms energy and spectral centroid)
    try:
        rms = _librosa_rms(y=y)
        centroid = _librosa_spectral_centroid(y=y, sr=sr)
        rms_mean = float(np.mean(rms))
        centroid_mean = float(np.mean(centroid))
    except Exception:
        rms_mean = 0.0
        centroid_mean = 0.0
    vec = np.concatenate([mf_mean, delta_mean, np.array([rms_mean, centroid_mean])])
    return vec


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


def segment_feature(path: str, side: str = "intro", seconds: float = 10.0, sr: int = 22050, n_mfcc: int = 20) -> np.ndarray:
    """Compute summary feature for the start (intro) or end (outro) segment.

    side: 'intro' or 'outro'
    seconds: duration of the extracted segment in seconds
    """
    # consult cache first
    key = (path, side, float(seconds), int(sr), int(n_mfcc))
    try:
        if key in _FEATURE_CACHE:
            return _FEATURE_CACHE[key]
    except Exception:
        pass

    y, sr_out = load_audio_mono(path, sr=sr)
    if y.size == 0:
        return np.zeros(n_mfcc * 2, dtype=float)
    n = int(seconds * sr_out)
    if side == "intro":
        seg = y[:n]
    else:
        seg = y[-n:]
    feat = mfcc_summary(seg, int(sr_out), n_mfcc=n_mfcc)
    try:
        _FEATURE_CACHE[key] = feat
    except Exception:
        pass
    return feat


def analyze_files(
    paths: List[str],
    side: str = "intro",
    seconds: float = 10.0,
    sr: int = 22050,
    similarity_threshold: float = 0.75,
    n_mfcc: int = 20,
    refine_with_dtw: bool = False,
    dtw_threshold: float = 0.5,
) -> Dict[str, object]:
    """Lightweight compatibility wrapper for older callers.

    The original heavy-weight analyzer was removed in favor of the
    deterministic per-window analyzer. To preserve backward compatibility
    for callers that expect a mapping with 'template' and 'matches', we
    delegate to per_window_common_prefix and synthesize a minimal result
    describing which files matched the detected prefix.
    """
    # if no paths, return empty structure
    if not paths:
        return {"features": {}, "pairs": [], "template": None, "matches": [], "mean_scores": {}}

    # use a conservative window and thresholds derived from the requested
    try:
        window_seconds = min(0.25, float(seconds))
    except Exception:
        window_seconds = 0.25
    try:
        sim_thresh = float(similarity_threshold or 0.75)
    except Exception:
        sim_thresh = 0.75

    res = per_window_common_prefix(paths=paths, side=side, max_seconds=seconds, window_seconds=window_seconds, sr=sr, n_mfcc=n_mfcc, similarity_threshold=sim_thresh, min_files_fraction=0.5)

    windows_matched = int(res.get('windows_matched', 0))
    per_file = res.get('per_file_per_window', {})

    # compute simple per-file match score as fraction of matched windows
    matches = []
    mean_scores = {}
    for p, perw in per_file.items():
        if windows_matched > 0:
            matched = sum(1 for v in perw[:windows_matched] if v >= sim_thresh)
            score = float(matched) / float(windows_matched)
        else:
            score = 0.0
        matches.append((p, score))
        mean_scores[p] = score

    # choose template as the file with highest score (if any)
    template = max(mean_scores.items(), key=lambda kv: kv[1])[0] if mean_scores else None
    return {
        "features": {},
        "pairs": [],
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


def per_second_common_prefix(
    paths: List[str],
    side: str = 'intro',
    max_seconds: int = 10,
    sr: int = 22050,
    n_mfcc: int = 13,
    similarity_threshold: float = 0.95,
    min_files_fraction: float = 0.75,
) -> Dict[str, object]:
    """Simple per-second common-prefix analyzer.

    For each second i in 0..max_seconds-1, compute an MFCC summary for the
    1s window starting at i (from the start for intro, from the end for outro),
    then compute cosine similarity across files against the per-second template.

    Returns a dict with:
    - 'seconds_matched': integer number of initial contiguous seconds matched
    - 'per_second_sim': list of per-second fraction-of-files >= threshold
    - 'per_file_per_second': mapping path -> list of per-second similarity to template
    - 'max_seconds': configured max_seconds
    """
    results = {
        'seconds_matched': 0,
        'per_second_sim': [],
        'per_file_per_second': {},
        'max_seconds': int(max_seconds),
    }

    # delegate to per_window_common_prefix with 1.0s window (backcompat)
    return per_window_common_prefix(paths=paths, side=side, max_seconds=max_seconds, window_seconds=1.0, sr=sr, n_mfcc=n_mfcc, similarity_threshold=similarity_threshold, min_files_fraction=min_files_fraction)


def per_window_common_prefix(
    paths: List[str],
    side: str = 'intro',
    max_seconds: float = 10.0,
    window_seconds: float = 0.25,
    sr: int = 22050,
    n_mfcc: int = 13,
    similarity_threshold: float = 0.95,
    min_files_fraction: float = 0.75,
) -> Dict[str, object]:
    """Per-window common-prefix analyzer with configurable window size in seconds.

    This computes MFCC mean vectors over consecutive windows of `window_seconds`
    starting at time 0 (for intro) or from the end (for outro), then computes
    per-window template similarity and returns contiguous matching windows from
    the start.
    """
    results = {
        'seconds_matched': 0.0,
        'windows_matched': 0,
        'per_window_frac': [],
        'per_file_per_window': {},
        'max_seconds': float(max_seconds),
        'window_seconds': float(window_seconds),
    }

    # number of windows to check
    n_windows = max(0, int(np.floor(float(max_seconds) / float(max(1e-6, window_seconds)))))

    # precompute per-file per-window MFCC mean vectors
    per_file_vectors = {}
    for p in paths:
        try:
            y, sr_out = load_audio_mono(p, sr=sr)
            if y.size == 0:
                per_file_vectors[p] = [np.zeros(n_mfcc, dtype=float)] * n_windows
                continue
            vecs = []
            for w in range(n_windows):
                if side == 'intro':
                    start = int(w * window_seconds * sr_out)
                    end = int(min((w + 1) * window_seconds * sr_out, len(y)))
                else:
                    # outro windows count from file end
                    end = len(y) - int(w * window_seconds * sr_out)
                    start = max(0, len(y) - int((w + 1) * window_seconds * sr_out))
                if start >= end:
                    seg = np.zeros(1)
                else:
                    seg = y[start:end]
                try:
                    mf = _librosa_mfcc(y=seg, sr=sr_out, n_mfcc=n_mfcc)
                    mv = np.mean(mf, axis=1)
                except Exception:
                    mv = np.zeros(n_mfcc, dtype=float)
                vecs.append(np.asarray(mv, dtype=float))
            per_file_vectors[p] = vecs
        except Exception:
            per_file_vectors[p] = [np.zeros(n_mfcc, dtype=float)] * n_windows

    def _norm(v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=float)
        v = v - np.mean(v)
        n = np.linalg.norm(v)
        if n < 1e-8:
            return v
        return v / n

    # evaluate each window from 0..n_windows-1
    for w in range(n_windows):
        # build template and compute per-file similarities
        vecs = [per_file_vectors[p][w] for p in paths]
        stacked = np.stack(vecs, axis=0) if vecs else np.zeros((0, n_mfcc))
        if stacked.size == 0:
            results['per_window_frac'].append(0.0)
            for p in paths:
                results['per_file_per_window'].setdefault(p, []).append(0.0)
            break
        tmpl = _norm(np.mean(stacked, axis=0))
        sims = []
        for p in paths:
            v = _norm(per_file_vectors[p][w])
            sim = float(np.dot(tmpl, v)) if tmpl.size and v.size else 0.0
            sims.append(sim)
            results['per_file_per_window'].setdefault(p, []).append(sim)
        frac = float(sum(1 for x in sims if x >= float(similarity_threshold))) / float(len(sims)) if sims else 0.0
        results['per_window_frac'].append(float(frac))
        if frac >= float(min_files_fraction):
            results['windows_matched'] += 1
            results['seconds_matched'] = results['windows_matched'] * float(window_seconds)
            continue
        else:
            break

    # persist trace
    try:
        out_dir = Path('.tmp_trim/previews')
        out_dir.mkdir(parents=True, exist_ok=True)
        import json
        with open(out_dir / 'per_window_trace.json', 'w') as fh:
            json.dump(results, fh, indent=2)
    except Exception:
        pass

    return results
    per_file_vectors = {}
    for p in paths:
        try:
            y, sr_out = load_audio_mono(p, sr=sr)
            if y.size == 0:
                per_file_vectors[p] = [np.zeros(n_mfcc)] * max_seconds
                continue
            total_len = len(y) / float(sr_out)
            vecs = []
            for s in range(int(max_seconds)):
                # choose window depending on side
                if side == 'intro':
                    start = int(s * sr_out)
                    end = int(min((s + 1) * sr_out, len(y)))
                else:
                    # outro: count from end
                    end = len(y) - int(s * sr_out)
                    start = max(0, len(y) - int((s + 1) * sr_out))
                if start >= end:
                    seg = np.zeros(1)
                else:
                    seg = y[start:end]
                try:
                    mf = _librosa_mfcc(y=seg, sr=sr_out, n_mfcc=n_mfcc)
                    mv = np.mean(mf, axis=1)
                except Exception:
                    mv = np.zeros(n_mfcc, dtype=float)
                vecs.append(np.asarray(mv, dtype=float))
            per_file_vectors[p] = vecs
        except Exception:
            per_file_vectors[p] = [np.zeros(n_mfcc, dtype=float)] * max_seconds

    # for each second compute template and similarities
    for s in range(int(max_seconds)):
        # gather vectors for this second
        vecs = [per_file_vectors[p][s] for p in paths]
        # template is mean across files
        stacked = np.stack([v for v in vecs], axis=0) if vecs else np.zeros((0, n_mfcc))
        if stacked.size == 0:
            results['per_second_sim'].append(0.0)
            for p in paths:
                results['per_file_per_second'].setdefault(p, []).append(0.0)
            break
        tmpl = np.mean(stacked, axis=0)
        # normalize
        def norm(v):
            v = np.asarray(v, dtype=float)
            v = v - np.mean(v)
            n = np.linalg.norm(v)
            if n < 1e-8:
                return v
            return v / n

        nt = norm(tmpl)
        sims = []
        for p in paths:
            v = norm(per_file_vectors[p][s])
            sim = float(np.dot(nt, v)) if nt.size and v.size else 0.0
            sims.append(sim)
            results['per_file_per_second'].setdefault(p, []).append(sim)
        # fraction of files meeting threshold
        frac = float(sum(1 for x in sims if x >= float(similarity_threshold))) / float(len(sims)) if sims else 0.0
        results['per_second_sim'].append(float(frac))
        # accept this second only if fraction >= min_files_fraction
        if frac >= float(min_files_fraction):
            results['seconds_matched'] += 1
            continue
        else:
            break

    # write a small JSON trace for inspection
    try:
        out_dir = Path('.tmp_trim/previews')
        out_dir.mkdir(parents=True, exist_ok=True)
        import json
        with open(out_dir / 'per_second_trace.json', 'w') as fh:
            json.dump(results, fh, indent=2)
    except Exception:
        pass

    return results


def _compute_mfcc_sequence(path: str, side: str, seconds: float, sr: int = 22050, n_mfcc: int = 20, n_fft: int = 2048, hop_length: int = 512) -> np.ndarray:
    """Compute MFCC matrix for the first/last `seconds` of the file.

    Returns an array shape (n_mfcc, n_frames).
    """
    y, sr_out = load_audio_mono(path, sr=sr)
    if y.size == 0:
        return np.zeros((n_mfcc, 1), dtype=float)
    n_samples = int(seconds * sr_out)
    if side == 'intro':
        seg = y[:n_samples]
    else:
        seg = y[-n_samples:]
    try:
        mf = _librosa_mfcc(y=seg, sr=sr_out, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length)
    except Exception:
        # fallback to default call
        mf = _librosa_mfcc(y=seg, sr=sr_out, n_mfcc=n_mfcc)
    return mf


def _dtw_prefix_similarity(a_path: str, b_path: str, side: str, max_seconds: float, sr: int = 22050, n_mfcc: int = 20, hop_length: int = 512, step_seconds: float = 0.25, dtw_threshold: float = 0.5) -> tuple:
    """Compute DTW similarity for increasing prefix lengths and return the best (sim, seconds).

    This favors detecting an initial matching prefix even when files diverge later.
    Returns (best_sim, best_seconds). If computation fails returns (0.0, 0.0).
    """
    try:
        mf_a = _compute_mfcc_sequence(a_path, side=side, seconds=max_seconds, sr=sr, n_mfcc=n_mfcc)
    except Exception:
        try:
            mf_a = _compute_mfcc_sequence(a_path, side=side, seconds=max_seconds, sr=sr, n_mfcc=n_mfcc)
        except Exception:
            return 0.0, 0.0
    try:
        mf_b = _compute_mfcc_sequence(b_path, side=side, seconds=max_seconds, sr=sr, n_mfcc=n_mfcc)
    except Exception:
        return 0.0, 0.0

    mf_a = np.asarray(mf_a, dtype=float)
    mf_b = np.asarray(mf_b, dtype=float)
    if mf_a.size == 0 or mf_b.size == 0:
        return 0.0, 0.0

    # frames per second for these MFCC matrices
    fps = float(sr) / float(max(1, hop_length))
    best_sim = 0.0
    best_t = 0.0
    # iterate prefixes from small to max_seconds
    t = max(step_seconds, 0.25)
    while t <= max_seconds + 1e-9:
        n_frames = max(1, int(np.round(t * fps)))
        # ensure both have at least n_frames available
        avail = min(mf_a.shape[1], mf_b.shape[1])
        take = min(n_frames, avail)
        if take <= 0:
            break
        A = mf_a[:, :take]
        B = mf_b[:, :take]
        # build cost matrix
        try:
            D = np.linalg.norm(A[:, :, None] - B[:, None, :], axis=0)
            try:
                from librosa.sequence import dtw as _lib_dtw
                wp_cost, wp = _lib_dtw(C=D)
                dtw_cost = float(wp_cost[-1, -1])
            except Exception:
                dtw_cost = float(np.mean(D))
            denom = max(1, take)
            norm_cost = dtw_cost / float(denom)
            dtw_sim = 1.0 / (1.0 + norm_cost)
        except Exception:
            dtw_sim = 0.0

        if dtw_sim >= float(dtw_threshold) and dtw_sim > best_sim:
            best_sim = float(dtw_sim)
            best_t = float(t)

        t += step_seconds

    return float(best_sim), float(best_t)

def common_prefix_duration(
    paths: List[str],
    side: str = 'intro',
    max_seconds: float = 10.0,
    step: float = 0.25,
    threshold: float = 0.75,
    # fraction of file-pairs that must be >= threshold to accept a candidate t
    min_pair_fraction: float = 0.85,
    # require the median pairwise similarity to also be >= threshold
    require_median: bool = True,
    # per-frame agreement: fraction of frames within a file that must meet the
    # similarity threshold when compared to the per-frame template
    frame_agreement_fraction: float = 0.7,
    # fraction of files that must satisfy the per-file frame agreement
    min_files_frame_fraction: float = 0.75,
    sr: int = 22050,
    n_mfcc: int = 20,
    n_fft: int = 2048,
    hop_length: int = 512,
) -> float:
    """Compute the largest t (0 < t <= max_seconds) such that the start/end
    segments of length t across all `paths` are mutually similar.

    The algorithm computes frame-level MFCCs for the full `max_seconds` once
    per file, then for each candidate t aggregates the first/last t seconds
    (by selecting frames) and compares mean feature vectors across files.

    Returns the accepted t in seconds (float). If no t accepted returns 0.0.
    """
    # Precompute MFCC matrices and frame-level RMS for all files
    mfcs = {}
    rms_frames = {}
    frames_per_second = float(sr) / float(max(1, hop_length))
    for p in paths:
        try:
            mf = _compute_mfcc_sequence(p, side=side, seconds=max_seconds, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length)
            mfcs[p] = np.asarray(mf, dtype=float)
        except Exception:
            mfcs[p] = np.zeros((n_mfcc, 1), dtype=float)
        # compute frame-level RMS for energy gating
        try:
            y, sr_out = load_audio_mono(p, sr=sr)
            n_samples = int(max_seconds * sr_out)
            if side == 'intro':
                seg = y[:n_samples]
            else:
                seg = y[-n_samples:]
            # rms shape is (1, n_frames)
            try:
                rms = _librosa_rms(y=seg, frame_length=n_fft, hop_length=hop_length)
                rms = np.asarray(rms).reshape(-1)
            except Exception:
                # fallback: approximate energy from squared signal using hop windowing
                if seg.size == 0:
                    rms = np.array([0.0])
                else:
                    hop = max(1, hop_length)
                    frames = [seg[i : i + n_fft] for i in range(0, max(1, len(seg) - n_fft + 1), hop)]
                    if not frames:
                        rms = np.array([0.0])
                    else:
                        rms = np.array([float(np.sqrt(np.mean(np.square(f)))) for f in frames])
            rms_frames[p] = rms
        except Exception:
            rms_frames[p] = np.array([0.0])

    # iterate t from small to max, keep last accepted
    t = step
    accepted_t = 0.0
    # energy threshold: segments below this mean RMS are treated as silence and
    # will not be accepted as matching (reduces silence-driven false positives)
    min_rms = 1e-4

    while t <= max_seconds + 1e-9:
        n_frames = max(1, int(np.round(t * frames_per_second)))
        feats = []
        failed = False
        frames_list = []
        for p in paths:
            mf = mfcs.get(p)
            if mf is None or mf.size == 0:
                failed = True
                break
            # if we don't have enough frames, take what we have
            take = min(n_frames, mf.shape[1]) if mf.shape[1] > 0 else 1
            seg = mf[:, :take]
            # aggregate by mean over time and include delta if possible
            try:
                delta = _librosa_delta(seg)
            except Exception:
                delta = np.zeros_like(seg)
            mean_vec = np.concatenate([np.mean(seg, axis=1), np.mean(delta, axis=1)])
            # energy gating: skip candidate if this file segment is too quiet
            try:
                rms_seq = rms_frames.get(p, np.array([0.0]))
                # if we don't have as many rms frames as MFCC frames, take what we have
                take_rms = min(take, rms_seq.size) if rms_seq.size > 0 else 0
                mean_rms = float(np.mean(rms_seq[:take_rms])) if take_rms > 0 else 0.0
                if mean_rms < min_rms:
                    failed = True
                    break
            except Exception:
                failed = True
                break
            feats.append(mean_vec)
            # collect per-file frame matrices for per-frame agreement checks
            frames_list.append(seg)
        if failed or not feats:
            break
        # Frame-level contiguous-prefix agreement check: compute per-frame
        # similarities across files and require that the first `n_frames`
        # lie within a contiguous prefix where at least
        # `min_files_frame_fraction` of files have per-frame similarity >= threshold.
        try:
            # determine common frame count across files for this t
            min_frames_avail = min([f.shape[1] for f in frames_list]) if frames_list else 0
            if min_frames_avail <= 0:
                failed = True
            else:
                eps = 1e-8
                # build per-file normalized frame vectors: shape (N_files, n_mfcc, min_frames_avail)
                per_file_normed = []
                for fm in frames_list:
                    fm_trim = fm[:, :min_frames_avail]
                    norms = np.linalg.norm(fm_trim, axis=0)
                    norms = np.where(norms < eps, 1.0, norms)
                    normed = fm_trim / norms
                    per_file_normed.append(normed)
                per_file_normed = np.stack(per_file_normed, axis=0)

                # template per-frame is mean across files, then L2-normalize per-frame
                tmpl = np.mean(per_file_normed, axis=0)
                tmpl_norms = np.linalg.norm(tmpl, axis=0)
                tmpl_norms = np.where(tmpl_norms < eps, 1.0, tmpl_norms)
                tmpl = tmpl / tmpl_norms

                # per-file per-frame similarities: for each file and frame, dot(normed[:,frame], tmpl[:,frame])
                sims = np.einsum('fcm,cm->fm', per_file_normed, tmpl)
                # sims shape: (N_files, min_frames_avail)

                # For each frame compute fraction of files meeting threshold
                frame_file_frac = np.mean(sims >= float(threshold), axis=0)  # shape (min_frames_avail,)

                # Convert required contiguous frames (n_frames) and find the longest
                # contiguous prefix from frame 0 where frame_file_frac >= min_files_frame_fraction
                required_frac = float(min_files_frame_fraction)
                contiguous = 0
                for fr_idx in range(min_frames_avail):
                    if frame_file_frac[fr_idx] >= required_frac:
                        contiguous += 1
                    else:
                        break

                # If the contiguous run covers at least n_frames, accept this t; else fail
                if contiguous < n_frames:
                    failed = True
                else:
                    # write per-frame trace for debugging/visualization
                    try:
                        out_dir = Path('.tmp_trim/previews')
                        out_dir.mkdir(parents=True, exist_ok=True)
                        trace = {
                            'paths': paths,
                            't': float(t),
                            'n_frames': int(n_frames),
                            'min_frames_avail': int(min_frames_avail),
                            'frame_file_frac': [float(x) for x in frame_file_frac.tolist()],
                            'per_file_similarities': {paths[i]: [float(x) for x in sims[i, :min_frames_avail].tolist()] for i in range(sims.shape[0])},
                        }
                        import json
                        with open(out_dir / f'per_frame_trace_t{int(t*1000)}.json', 'w') as fh:
                            json.dump(trace, fh, indent=2)
                    except Exception:
                        pass
        except Exception:
            failed = True

        if failed:
            break

        # make pairwise similarity checks that are more robust than a single
        # template mean: normalize each feature and compute cosine similarities
        try:
            stacked = np.stack(feats, axis=0)  # shape (N_files, dim)
            # normalize each feature vector (zero-mean then L2)
            eps = 1e-8
            normed = []
            for v in stacked:
                v = np.asarray(v, dtype=float)
                v = v - np.mean(v)
                nrm = np.linalg.norm(v)
                if nrm < eps:
                    normed.append(v)
                else:
                    normed.append(v / nrm)
            normed = np.stack(normed, axis=0)
            # pairwise cosine similarities via dot product (since vectors are L2-normalized)
            sim_matrix = np.dot(normed, normed.T)
            # extract upper-triangle (unique pairs)
            idxs = np.triu_indices(sim_matrix.shape[0], k=1)
            pair_vals = sim_matrix[idxs] if idxs[0].size > 0 else np.array([])
            if pair_vals.size == 0:
                # single file or degenerate case: require self-similarity trivially
                median_sim = float(sim_matrix[0, 0]) if sim_matrix.size else 0.0
                frac_above = 1.0
                min_sim = median_sim
            else:
                median_sim = float(np.median(pair_vals))
                min_sim = float(np.min(pair_vals))
                frac_above = float(np.sum(pair_vals >= float(threshold))) / float(pair_vals.size)
        except Exception:
            break

        # Accept t only when both median similarity and fraction of pairs meet
        # the configured criteria. This reduces cases where one outlier drives
        # the mean/template and causes false positives.
        try:
            if (not require_median or median_sim >= float(threshold)) and frac_above >= float(min_pair_fraction) and min_sim >= float(threshold):
                accepted_t = float(t)
                t += step
                continue
            else:
                break
        except Exception:
            break

    return accepted_t



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
