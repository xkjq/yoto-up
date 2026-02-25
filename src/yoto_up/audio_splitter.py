"""Simple audio splitting utilities using ffmpeg's silencedetect.

Provides `split_audio` which detects silences and splits an input audio
file into multiple tracks aiming for `target_tracks` while respecting a
minimum track length.

This is a pragmatic wrapper around `ffmpeg`; `ffmpeg` must be installed
and on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import re
from pathlib import Path
from typing import List, Tuple, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.align import Align
from rich.text import Text
from datetime import timedelta


def _ensure_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required but was not found on PATH")


def _run_ffmpeg_silencedetect(
    path: Path, silence_thresh_db: int, min_silence_len_s: float
) -> str:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={silence_thresh_db}dB:d={min_silence_len_s}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(
        cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    return proc.stderr


def _parse_silencedetect_output(output: str) -> List[Tuple[float, float]]:
    # returns list of (silence_start, silence_end)
    starts = []
    ends = []
    for line in output.splitlines():
        line = line.strip()
        m1 = re.search(r"silence_start: ([0-9.]+)", line)
        if m1:
            starts.append(float(m1.group(1)))
        m2 = re.search(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", line)
        if m2:
            ends.append(float(m2.group(1)))
    # Pair them: sometimes start/end pairs are produced; try to match order
    ranges: List[Tuple[float, float]] = []
    i = 0
    j = 0
    while i < len(starts) or j < len(ends):
        s = starts[i] if i < len(starts) else None
        e = ends[j] if j < len(ends) else None
        if s is not None and (e is None or s < e):
            # start followed by an end later -> if there's a corresponding end use it
            if j < len(ends) and ends[j] > s:
                ranges.append((s, ends[j]))
                i += 1
                j += 1
            else:
                # unmatched start, break
                break
        elif e is not None:
            # end without a known start: treat silence from 0
            ranges.append((0.0, e))
            j += 1
        else:
            break
    return ranges


def _get_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    out = proc.stdout.strip()
    try:
        return float(out)
    except Exception:
        raise RuntimeError("failed to determine input duration via ffprobe")


def _format_output_name(
    input_path: Path, index: int, total: int, out_dir: Path
) -> Path:
    stem = input_path.stem
    suffix = input_path.suffix or ".mp3"
    return out_dir / f"{stem}_part{index + 1:0{len(str(total))}d}{suffix}"


def split_audio(
    input_path: str | Path,
    target_tracks: int = 10,
    min_track_length_sec: int = 30,
    silence_thresh_db: int = -40,
    min_silence_len_ms: int = 800,
    output_dir: Optional[str | Path] = None,
    show_progress: bool = True,
    console: Optional[Console] = None,
) -> List[Path]:
    """Split `input_path` into up to `target_tracks` pieces.

    - Detects silences with ffmpeg's `silencedetect`.
    - Chooses cut points at the midpoint of silence ranges.
    - Tries to pick up to `target_tracks - 1` cut points while ensuring
      segments are at least `min_track_length_sec` seconds long.
    - If insufficient silence points are found, falls back to even splits.

    Returns list of output file Paths.
    """
    _ensure_ffmpeg()
    p = Path(input_path)
    if output_dir is None:
        out_dir = p.parent
    else:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    total_dur = _get_duration(p)
    min_silence_len_s = max(0.01, min_silence_len_ms / 1000.0)
    console = console or Console()
    if show_progress:
        with console.status("Detecting silences…", spinner="dots"):
            raw = _run_ffmpeg_silencedetect(p, silence_thresh_db, min_silence_len_s)
    else:
        raw = _run_ffmpeg_silencedetect(p, silence_thresh_db, min_silence_len_s)
    silence_ranges = _parse_silencedetect_output(raw)

    candidates = []
    for s, e in silence_ranges:
        midpoint = (s + e) / 2.0
        candidates.append(midpoint)

    if show_progress:
        t = Table(show_header=False, box=None)
        t.add_row("Duration:", f"{total_dur:.1f}s")
        t.add_row("Silence ranges found:", str(len(silence_ranges)))
        t.add_row("Candidate cuts:", str(len(candidates)))
        console.print(t)

    # Filter candidates too close to start/end or violating min track length
    filtered = [
        c
        for c in candidates
        if c > min_track_length_sec and (total_dur - c) > min_track_length_sec
    ]

    desired_cuts = max(0, target_tracks - 1)
    chosen_cuts: List[float] = []
    if len(filtered) >= desired_cuts and desired_cuts > 0:
        # pick cuts closest to ideal even-split positions
        targets = [(i + 1) * total_dur / target_tracks for i in range(desired_cuts)]
        used = set()
        for t in targets:
            # find nearest candidate not yet used
            best = min(filtered, key=lambda c: abs(c - t))
            chosen_cuts.append(best)
            filtered.remove(best)
    elif desired_cuts > 0 and len(filtered) > 0:
        # not enough candidates — use what we have
        chosen_cuts = filtered[:desired_cuts]
    else:
        chosen_cuts = []

    chosen_cuts = sorted(chosen_cuts)

    # If still too few cuts, make even splits as fallback
    if len(chosen_cuts) < desired_cuts and desired_cuts > 0:
        missing = desired_cuts - len(chosen_cuts)
        # generate additional evenly spaced cuts avoiding proximity to existing ones
        for i in range(missing):
            t = (len(chosen_cuts) + i + 1) * total_dur / target_tracks
            chosen_cuts.append(t)
        chosen_cuts = sorted(chosen_cuts)

    # Build segment boundaries
    boundaries = [0.0] + chosen_cuts + [total_dur]
    segments: List[Tuple[float, float]] = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        if (end - start) < min_track_length_sec:
            # If too short, try to expand into next segment (simple merge)
            if i + 2 < len(boundaries):
                # merge with next
                boundaries[i + 1] = boundaries[i + 2]
                # recompute later by restarting algorithm; simple approach: skip adding
                continue
            else:
                # last segment short — extend to end
                end = boundaries[-1]
        segments.append((start, end))

    # If segments count > target_tracks, merge last extras
    while len(segments) > target_tracks:
        a = segments.pop()
        segments[-1] = (segments[-1][0], a[1])

    outputs: List[Path] = []
    total = len(segments)
    if show_progress:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn(), console=console) as progress:
            task = progress.add_task("Extracting segments", total=total)
            for idx, (start, end) in enumerate(segments):
                out_path = _format_output_name(p, idx, total, out_dir)
                progress.update(task, description=f"Segment {idx+1}/{total} — {end-start:.1f}s")
                # use ffmpeg to extract
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(p),
                    "-ss",
                    f"{start}",
                    "-to",
                    f"{end}",
                    "-c",
                    "copy",
                    str(out_path),
                ]
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if proc.returncode != 0:
                    # fallback: re-encode audio to avoid copy-related issues
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(p),
                        "-ss",
                        f"{start}",
                        "-to",
                        f"{end}",
                        "-acodec",
                        "libmp3lame",
                        "-b:a",
                        "128k",
                        str(out_path),
                    ]
                    proc2 = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if proc2.returncode != 0:
                        raise RuntimeError(
                            f"ffmpeg failed to create segment {idx + 1}: {proc2.stderr}\n{proc.stderr}"
                        )
                outputs.append(out_path)
                progress.advance(task)
    else:
        for idx, (start, end) in enumerate(segments):
            out_path = _format_output_name(p, idx, total, out_dir)
            # use ffmpeg to extract
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(p),
                "-ss",
                f"{start}",
                "-to",
                f"{end}",
                "-c",
                "copy",
                str(out_path),
            ]
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if proc.returncode != 0:
                # fallback: re-encode audio to avoid copy-related issues
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(p),
                    "-ss",
                    f"{start}",
                    "-to",
                    f"{end}",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(out_path),
                ]
                proc2 = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                if proc2.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg failed to create segment {idx + 1}: {proc2.stderr}\n{proc.stderr}"
                    )
            outputs.append(out_path)

    if show_progress:
        # Print a summary table of created files
        tbl = Table(title="Created segments", show_lines=False)
        tbl.add_column("#", style="bold cyan", width=4)
        tbl.add_column("File")
        tbl.add_column("Duration", justify="right")
        tbl.add_column("Size", justify="right")

        def _format_bytes(n: int) -> str:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if n < 1024.0:
                    return f"{n:3.1f} {unit}"
                n /= 1024.0
            return f"{n:.1f} PB"

        for idx, out in enumerate(outputs):
            try:
                dur = _get_duration(out)
                dur_text = str(timedelta(seconds=round(dur)))
            except Exception:
                dur_text = "?"
            try:
                size = out.stat().st_size
                size_text = _format_bytes(size)
            except Exception:
                size_text = "?"
            tbl.add_row(str(idx + 1), str(out.name), dur_text, size_text)

        console.print(Align.center(tbl))

    return outputs
