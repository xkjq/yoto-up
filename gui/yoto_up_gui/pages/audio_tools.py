"""Audio Tools page — normalize, trim silence, and view waveforms."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QFileDialog, QProgressBar, QListWidget,
    QListWidgetItem, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QThread


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
class _Worker(QThread):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str, float)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Waveform display widget
# ---------------------------------------------------------------------------
class WaveformWidget(QWidget):
    """Custom widget that paints amplitude bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[float] = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: list[float]):
        self._data = data or []
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bg = QColor("#1e1e2e")
        bar_color = QColor("#89b4fa")
        painter.fillRect(self.rect(), bg)

        if not self._data:
            painter.setPen(QColor("#6c7086"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No waveform data")
            painter.end()
            return

        n = len(self._data)
        w = self.width()
        h = self.height()
        bar_w = max(1, w / n)
        mid = h / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(bar_color)

        for i, amp in enumerate(self._data):
            bar_h = max(1, amp * mid * 0.9)
            x = int(i * bar_w)
            painter.drawRect(x, int(mid - bar_h), max(1, int(bar_w) - 1), int(bar_h * 2))

        painter.end()


# ---------------------------------------------------------------------------
# Normalize tab
# ---------------------------------------------------------------------------
class _NormalizeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _Worker | None = None
        self._files: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Controls row
        ctrl = QHBoxLayout()
        self._btn_add = QPushButton("Add Files")
        self._btn_add.clicked.connect(self._add_files)
        ctrl.addWidget(self._btn_add)

        self._btn_folder = QPushButton("Add Folder")
        self._btn_folder.clicked.connect(self._add_folder)
        ctrl.addWidget(self._btn_folder)

        ctrl.addWidget(QLabel("Target LUFS:"))
        self._lufs = QDoubleSpinBox()
        self._lufs.setRange(-60.0, 0.0)
        self._lufs.setValue(-16.0)
        self._lufs.setSingleStep(0.5)
        ctrl.addWidget(self._lufs)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # File list
        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        # Actions row
        actions = QHBoxLayout()
        self._btn_analyze = QPushButton("Analyze")
        self._btn_analyze.clicked.connect(self._analyze)
        actions.addWidget(self._btn_analyze)

        self._btn_normalize = QPushButton("Normalize All")
        self._btn_normalize.clicked.connect(self._normalize_all)
        actions.addWidget(self._btn_normalize)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setStyleSheet("background-color:#45475a;")
        self._btn_clear.clicked.connect(self._clear)
        actions.addWidget(self._btn_clear)

        actions.addStretch()
        layout.addLayout(actions)

        # Progress
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#6c7086;")
        layout.addWidget(self._status)

    # -- helpers --
    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Audio Files", "",
            "Audio (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;All (*)"
        )
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self._list.addItem(p)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if not folder:
            return
        from pathlib import Path

        exts = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
        for f in sorted(Path(folder).iterdir()):
            if f.suffix.lower() in exts and str(f) not in self._files:
                self._files.append(str(f))
                self._list.addItem(str(f))

    def _clear(self):
        self._files.clear()
        self._list.clear()
        self._status.setText("")
        self._progress.setVisible(False)

    def _analyze(self):
        if not self._files:
            self._status.setText("No files to analyze.")
            return
        self._status.setText("Analyzing...")
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._files))
        self._progress.setValue(0)

        def _run():
            from yoto_up.audio.normalize import get_audio_loudness

            results = []
            for i, fp in enumerate(self._files):
                info = get_audio_loudness(fp)
                lufs = info.get("input_i", "?") if info else "error"
                results.append((fp, lufs))
            return results

        self._worker = _Worker(_run)
        self._worker.finished.connect(self._on_analyze_done)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    def _on_analyze_done(self, results):
        self._list.clear()
        for fp, lufs in results:
            self._list.addItem(f"{fp}  [LUFS: {lufs}]")
        self._progress.setValue(len(results))
        self._status.setText(f"Analysis complete — {len(results)} files.")

    def _normalize_all(self):
        if not self._files:
            self._status.setText("No files to normalize.")
            return
        target = self._lufs.value()
        self._status.setText("Normalizing...")
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._files))
        self._progress.setValue(0)

        def _run():
            from pathlib import Path
            from yoto_up.audio.normalize import normalize_audio

            ok = 0
            for fp in self._files:
                p = Path(fp)
                out = p.parent / f"{p.stem}_norm{p.suffix}"
                if normalize_audio(fp, out, target_lufs=target):
                    ok += 1
            return ok

        self._worker = _Worker(_run)
        self._worker.finished.connect(
            lambda n: self._status.setText(f"Normalized {n}/{len(self._files)} files.")
        )
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()


# ---------------------------------------------------------------------------
# Trim silence tab
# ---------------------------------------------------------------------------
class _TrimTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _Worker | None = None
        self._files: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        ctrl = QHBoxLayout()
        btn = QPushButton("Add Files")
        btn.clicked.connect(self._add_files)
        ctrl.addWidget(btn)

        ctrl.addWidget(QLabel("Threshold (dB):"))
        self._thresh = QDoubleSpinBox()
        self._thresh.setRange(-80.0, 0.0)
        self._thresh.setValue(-40.0)
        self._thresh.setSingleStep(1.0)
        ctrl.addWidget(self._thresh)

        ctrl.addWidget(QLabel("Min silence (ms):"))
        self._min_ms = QSpinBox()
        self._min_ms.setRange(50, 5000)
        self._min_ms.setValue(500)
        ctrl.addWidget(self._min_ms)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        actions = QHBoxLayout()
        self._btn_detect = QPushButton("Detect Silence")
        self._btn_detect.clicked.connect(self._detect)
        actions.addWidget(self._btn_detect)

        self._btn_trim = QPushButton("Trim All")
        self._btn_trim.clicked.connect(self._trim_all)
        actions.addWidget(self._btn_trim)
        actions.addStretch()
        layout.addLayout(actions)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#6c7086;")
        layout.addWidget(self._status)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Audio Files", "",
            "Audio (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;All (*)"
        )
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self._list.addItem(p)

    def _detect(self):
        if not self._files:
            self._status.setText("No files selected.")
            return
        self._status.setText("Detecting silence...")

        thresh = self._thresh.value()
        min_ms = self._min_ms.value()

        def _run():
            from yoto_up.audio.trim import detect_silence

            results = []
            for fp in self._files:
                regions = detect_silence(fp, silence_thresh_db=thresh, min_silence_ms=min_ms)
                results.append((fp, regions))
            return results

        self._worker = _Worker(_run)
        self._worker.finished.connect(self._on_detect_done)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    def _on_detect_done(self, results):
        self._list.clear()
        for fp, regions in results:
            n = len(regions) if regions else 0
            self._list.addItem(f"{fp}  [{n} silent regions]")
        self._status.setText("Detection complete.")

    def _trim_all(self):
        if not self._files:
            self._status.setText("No files selected.")
            return

        thresh = self._thresh.value()
        min_ms = self._min_ms.value()
        self._status.setText("Trimming...")

        def _run():
            from pathlib import Path
            from yoto_up.audio.trim import trim_silence

            ok = 0
            for fp in self._files:
                p = Path(fp)
                out = p.parent / f"{p.stem}_trimmed{p.suffix}"
                if trim_silence(fp, out, silence_thresh_db=thresh, min_silence_ms=min_ms):
                    ok += 1
            return ok

        self._worker = _Worker(_run)
        self._worker.finished.connect(
            lambda n: self._status.setText(f"Trimmed {n}/{len(self._files)} files.")
        )
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()


# ---------------------------------------------------------------------------
# Waveform tab
# ---------------------------------------------------------------------------
class _WaveformTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _Worker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        ctrl = QHBoxLayout()
        self._btn_open = QPushButton("Open File")
        self._btn_open.clicked.connect(self._open_file)
        ctrl.addWidget(self._btn_open)

        self._file_label = QLabel("No file selected")
        self._file_label.setStyleSheet("color:#6c7086;")
        ctrl.addWidget(self._file_label, 1)
        layout.addLayout(ctrl)

        self._waveform = WaveformWidget()
        layout.addWidget(self._waveform)

        self._info = QLabel("")
        self._info.setStyleSheet("color:#a6adc8; font-size:12px;")
        layout.addWidget(self._info)

        layout.addStretch()

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "",
            "Audio (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;All (*)"
        )
        if not path:
            return
        self._file_label.setText(path)
        self._waveform.set_data([])
        self._info.setText("Loading...")

        def _run():
            from yoto_up.audio.waveform import get_waveform_data, get_audio_duration

            data = get_waveform_data(path, num_samples=300)
            duration = get_audio_duration(path)
            return data, duration

        self._worker = _Worker(_run)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(lambda e: self._info.setText(f"Error: {e}"))
        self._worker.start()

    def _on_loaded(self, result):
        data, duration = result
        if data:
            self._waveform.set_data(data)
        dur_str = f"{duration:.1f}s" if duration else "unknown"
        samples_str = f"{len(data)} samples" if data else "no data"
        self._info.setText(f"Duration: {dur_str}  |  {samples_str}")


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
class AudioToolsPage(QWidget):
    """Audio processing tools — normalize, trim, waveform."""

    navigate_to = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.addTab(_NormalizeTab(), "Normalize")
        self._tabs.addTab(_TrimTab(), "Trim Silence")
        self._tabs.addTab(_WaveformTab(), "Waveform")
        layout.addWidget(self._tabs)

    def set_client(self, client):
        self._client = client
