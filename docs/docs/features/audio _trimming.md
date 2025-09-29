## Intro/outro detection (and removal)

### Non-technical summary

If you have many audio files that all start or end with the same tune, spoken intro,
or outro, this tool helps find that repeated segment and remove it automatically. It
works by comparing short audio fingerprints (no speech recognition required) and can
write trimmed copies of files so you don't upload the repeated material.

### Overview

This project includes a lightweight, signal-based tool for detecting and optionally
trimming common intro or outro segments across a set of audio files. The implementation
lives in `yoto_app/intro_outro.py` and uses a per-window MFCC comparison approach to
find similar start/end segments without requiring transcription or cloud services.

### What this does

- Analyze the first N seconds (intro) or last N seconds (outro) of each file and
  compute short-window MFCC features.
- Compare per-window features across files to identify windows that are similar
  in many files (a candidate shared intro/outro template).
- Report which files match the detected template and provide per-file match scores.
- Provide a helper `trim_audio_file()` that trims a specified number of seconds from
  the start/end of a source file and writes a trimmed output file (uses pydub).

### Why use this

- Useful for podcast batches, lectures, or any collection where many files share the
  same spoken/music intro or outro and you want to remove that repeated material before upload.

### Key functions and CLI

- `analyze_files(paths, side='intro', seconds=10.0, similarity_threshold=0.75, ...)`
  - High-level wrapper that returns a `template` (file path chosen as representative),
    `matches` (per-file fractional match score), and other metadata. Tune
    `seconds` and `similarity_threshold` to be more/less conservative.
- `per_window_common_prefix(...)` and `per_second_common_prefix(...)`
  - Lower-level analyzers that compute per-window or per-second similarity
    matrices and return how many seconds/windows matched across the collection.
- `trim_audio_file(src_path, dest_path, remove_intro_seconds=0.0, remove_outro_seconds=0.0, keep_silence_ms=0)`
  - Trim the desired seconds from the start/end and write a new file. `keep_silence_ms`
    lets you preserve a small silence buffer at the edges.

### Example CLI usage

```bash
# analyze two files for a shared 8s intro and print results
python yoto_app/intro_outro.py file1.mp3 file2.mp3 --side intro --seconds 8 --threshold 0.75
```

### Typical workflow

1. Run the analyzer on a representative set of files to identify whether a common
   intro/outro exists and which files match it.
2. Inspect the `matches` or per-file scores to choose which files you want to trim.
3. Use `trim_audio_file()` (or the provided UI helpers in your app) to write trimmed
   versions to a temp directory and update the upload queue to use the trimmed files.

### Tuning tips

- `seconds`: smaller values make matching more precise to short jingles; larger values
  may be needed for longer spoken intros.
- `similarity_threshold`: values near 1.0 require near-identical audio; lower values
  (0.6–0.8) allow more variance but may produce false matches.
- `min_files_fraction` (where available): set the fraction of files that must share
  the similarity to consider a segment a common intro/outro (default ~0.5–0.75).

### Limitations and caveats

- This is a signal-based approach (MFCC + similarity). It can detect repeated
  jingles and very similar spoken intros but will be less reliable when the
  repeated content is spoken slightly differently or when background noise differs.
- For text-aware detection (exact repeated words), prefer running ASR (e.g. Whisper)
  and comparing transcriptions.
- Always preview and listen to trimmed files before replacing originals — automatic
  trimming may occasionally remove desired audio if thresholds are too aggressive.

### Dependencies

- The analyzer and helpers rely on the standard scientific/audio Python ecosystem
  (numpy, librosa for MFCCs, pyloudnorm for LUFS if used, and pydub for trimming/export).
  The functions are written to degrade gracefully if heavy dependencies are missing,
  but trimming requires pydub.

### Further integration

- The app's Waveforms / Gain UI focuses on loudness/gain adjustments; the intro/outro
  analyzer is a separate tool that can be used programmatically to produce a list of
  candidate trims which can then be applied with `trim_audio_file()` prior to upload.