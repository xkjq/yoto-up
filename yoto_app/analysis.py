"""Audio analysis helpers (moved out of intro_outro to keep concerns separate).

This module exposes per-window (sub-second) and per-second common-prefix
analysis functions plus lower-level MFCC helpers used by the UI.
"""
from typing import List, Tuple, Dict, Union
import numpy as np
import librosa
from librosa.feature import mfcc as _librosa_mfcc
from librosa.feature import delta as _librosa_delta, rms as _librosa_rms, spectral_centroid as _librosa_spectral_centroid
from pathlib import Path
import json


def load_audio_mono(path: str, sr: int = 22050) -> Tuple[np.ndarray, Union[int, float]]:
    y, sr_out = librosa.load(path, sr=sr, mono=True)
    try:
        sr_out = int(sr_out)
    except Exception:
        pass
    return y, sr_out


def mfcc_summary(y: np.ndarray, sr: int, n_mfcc: int = 20) -> np.ndarray:
    if y.size == 0:
        return np.zeros(n_mfcc * 2, dtype=float)
    mf = _librosa_mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    try:
        delta = _librosa_delta(mf)
    except Exception:
        delta = np.zeros_like(mf)
    mf_mean = np.mean(mf, axis=1)
    delta_mean = np.mean(delta, axis=1)
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


def _compute_mfcc_sequence(path: str, side: str, seconds: float, sr: int = 22050, n_mfcc: int = 20, n_fft: int = 2048, hop_length: int = 512) -> np.ndarray:
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
        mf = _librosa_mfcc(y=seg, sr=sr_out, n_mfcc=n_mfcc)
    return mf


def _dtw_prefix_similarity(a_path: str, b_path: str, side: str, max_seconds: float, sr: int = 22050, n_mfcc: int = 20, hop_length: int = 512, step_seconds: float = 0.25, dtw_threshold: float = 0.5) -> tuple:
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

    fps = float(sr) / float(max(1, hop_length))
    best_sim = 0.0
    best_t = 0.0
    t = max(step_seconds, 0.25)
    while t <= max_seconds + 1e-9:
        n_frames = max(1, int(np.round(t * fps)))
        avail = min(mf_a.shape[1], mf_b.shape[1])
        take = min(n_frames, avail)
        if take <= 0:
            break
        A = mf_a[:, :take]
        B = mf_b[:, :take]
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
    results = {
        'seconds_matched': 0.0,
        'windows_matched': 0,
        'per_window_frac': [],
        'per_file_per_window': {},
        'max_seconds': float(max_seconds),
        'window_seconds': float(window_seconds),
    }

    n_windows = max(0, int(np.floor(float(max_seconds) / float(max(1e-6, window_seconds)))))
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

    for w in range(n_windows):
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

    try:
        out_dir = Path('.tmp_trim/previews')
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / 'per_window_trace.json', 'w') as fh:
            json.dump(results, fh, indent=2)
    except Exception:
        pass

    return results


def per_second_common_prefix(
    paths: List[str],
    side: str = 'intro',
    max_seconds: int = 10,
    sr: int = 22050,
    n_mfcc: int = 13,
    similarity_threshold: float = 0.95,
    min_files_fraction: float = 0.75,
) -> Dict[str, object]:
    return per_window_common_prefix(paths=paths, side=side, max_seconds=max_seconds, window_seconds=1.0, sr=sr, n_mfcc=n_mfcc, similarity_threshold=similarity_threshold, min_files_fraction=min_files_fraction)


def common_prefix_duration(*args, **kwargs):
    """Legacy API: keep in analysis for callers that want the heavier frame-based method.

    This was originally in intro_outro; we preserve a thin wrapper here that
    imports the original implementation if available. For now, this is a
    placeholder that raises NotImplementedError to encourage callers to use
    the lighter-weight per-window analyzer.
    """
    raise NotImplementedError("common_prefix_duration moved to a separate implementation; use per_window_common_prefix or re-add the heavier method if needed")
