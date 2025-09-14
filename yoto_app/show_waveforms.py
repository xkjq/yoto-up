import flet as ft
import numpy as np
import matplotlib.pyplot as plt
import io
import base64
import contextlib
import wave
import os
import tempfile

def show_waveforms_popup(page, file_rows_column, show_snack, gain_adjusted_files, audio_adjust_utils, waveform_cache):
    files = [getattr(row, 'filename', None) for row in file_rows_column.controls if getattr(row, 'filename', None)]
    if not files:
        show_snack("No files in upload queue.", error=True)
        return
    if not hasattr(page, '_track_gains'):
        page._track_gains = {}
    progress_text = ft.Text(f"Calculating waveform data... 0/{len(files)}", size=14)
    progress_bar = ft.ProgressBar(width=300, value=0)
    progress_dlg = ft.AlertDialog(
        title=ft.Text("Generating Waveforms"),
        content=ft.Column([
            progress_text,
            progress_bar
        ], expand=True),
        actions=[],
        modal=True
    )
    page.open(progress_dlg)
    page.update()

    def progress_callback(completed, total):
        progress_text.value = f"Calculating waveform data... {completed}/{total}"
        progress_bar.value = completed / total if total else 0
        page.update()

    from waveform_utils import batch_audio_stats
    stats_results = batch_audio_stats(files, waveform_cache, progress_callback=progress_callback)
    page.update()

    skipped_files = []
    for idx, stat in enumerate(stats_results):
        audio, max_amp, avg_amp, lufs, ext, filepath = stat
        if audio is None:
            reason = None
            if ext is None:
                reason = "Unrecognized or missing file extension."
            elif ext not in ['.wav', '.mp3']:
                reason = f"Unsupported extension: {ext}"
            elif not os.path.exists(filepath):
                reason = "File does not exist."
            else:
                reason = "Could not decode audio or file is empty/corrupt."
            skipped_files.append(f"{os.path.basename(filepath) or filepath}: {reason}")

    def plot_and_stats(audio, framerate, ext, filepath, gain_db=0.0):
        import pyloudnorm as pyln
        audio_adj = audio * (10 ** (gain_db / 20.0))
        max_amp = float(np.max(np.abs(audio_adj)))
        avg_amp = float(np.mean(np.abs(audio_adj)))
        try:
            meter = pyln.Meter(framerate)
            lufs = float(meter.integrated_loudness(audio_adj))
        except Exception:
            lufs = None
        max_points = 2000
        n = len(audio_adj)
        if n > max_points:
            idx = np.linspace(0, n - 1, max_points).astype(int)
            audio_plot = audio_adj[idx]
        else:
            audio_plot = audio_adj
        if ext == '.wav':
            with contextlib.closing(wave.open(filepath, 'rb')) as wf:
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                times = np.linspace(0, n_frames / framerate, num=n)
        else:
            framerate = 44100
            times = np.linspace(0, n / framerate, num=n)
        if n > max_points:
            times = times[idx]
        fig, ax = plt.subplots(figsize=(4, 1.2))
        ax.plot(times, audio_plot, color='blue')
        ax.set_title(os.path.basename(filepath), fontsize=8)
        ax.set_xlabel('Time (s)', fontsize=7)
        ax.set_ylabel('Amplitude', fontsize=7)
        ax.tick_params(axis='both', which='major', labelsize=6)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode('utf-8')
        fd, tmp_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        with open(tmp_path, 'wb') as tmpfile:
            tmpfile.write(base64.b64decode(img_b64))
        lufs_str = f"LUFS: {lufs:.2f} dB" if lufs is not None else "LUFS: (unavailable)"
        label = ft.Text(f"Max amplitude: {max_amp:.2f}   Average amplitude: {avg_amp:.2f}   {lufs_str}", size=10, color=ft.Colors.BLUE)
        warning = None
        if lufs is not None:
            if lufs > -9:
                warning = ft.Text("Warning: LUFS is high! Track may be too loud for streaming (-9 dB or higher)", size=10, color=ft.Colors.RED)
            elif lufs > -16:
                warning = ft.Text("Warning: LUFS is moderately high (-16 dB to -9 dB)", size=10, color=ft.Colors.YELLOW_900)
        return label, warning, tmp_path

    # ...existing code for per_track, global gain, dialog, etc. (copy from gui.py as needed)
    # This is a minimal extraction; further refactoring may be needed for full feature parity.
