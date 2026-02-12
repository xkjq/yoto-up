"""Asynchronous image loader for PySide6 widgets.

Downloads images from URLs in a background thread, caches them on disk,
and converts them to QPixmap for display.  Includes a shared singleton
cache to avoid redundant downloads.

Thread safety: the worker loads images as ``QImage`` (which is thread-safe)
and converts to ``QPixmap`` on the main thread via the signal handler.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, QSize, Qt
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import QLabel

import httpx

from yoto_up.storage.paths import _cache_dir


# ---------------------------------------------------------------------------
# Disk cache for downloaded images
# ---------------------------------------------------------------------------

_IMAGE_CACHE_DIR = _cache_dir / "images"


def _cache_path_for(url: str) -> Path:
    """Return the cache file path for a given URL (SHA256 of URL)."""
    h = hashlib.sha256(url.encode()).hexdigest()
    return _IMAGE_CACHE_DIR / h


def _ensure_cache_dir():
    _IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Download worker
# ---------------------------------------------------------------------------

class _DownloadWorker(QThread):
    """Download an image URL in a background thread.

    Emits ``image_ready(url, QImage)`` with a thread-safe QImage.  The
    caller is responsible for converting to QPixmap on the GUI thread.
    """

    image_ready = Signal(str, QImage)  # url, image (thread-safe)
    error = Signal(str, str)  # url, error message

    def __init__(self, url: str, size: QSize | None = None):
        super().__init__()
        self.url = url
        self.size = size
        self._cancelled = False

    def cancel(self) -> None:
        """Request cooperative cancellation (checked between steps)."""
        self._cancelled = True

    def run(self):
        try:
            if self._cancelled:
                return

            # Check disk cache first
            cache_path = _cache_path_for(self.url)
            if cache_path.exists():
                image = QImage(str(cache_path))
                if not image.isNull():
                    if self.size:
                        image = image.scaled(
                            self.size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                    if not self._cancelled:
                        self.image_ready.emit(self.url, image)
                    return

            if self._cancelled:
                return

            # Download
            resp = httpx.get(self.url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            data = resp.content

            if self._cancelled:
                return

            # Save to cache
            _ensure_cache_dir()
            cache_path.write_bytes(data)

            # Convert to QImage (thread-safe, unlike QPixmap)
            image = QImage()
            image.loadFromData(data)
            if image.isNull():
                self.error.emit(self.url, "Invalid image data")
                return

            if self.size:
                image = image.scaled(
                    self.size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )

            if not self._cancelled:
                self.image_ready.emit(self.url, image)

        except Exception as e:
            if not self._cancelled:
                self.error.emit(self.url, str(e))


# ---------------------------------------------------------------------------
# ImageLabel - a QLabel that loads images asynchronously
# ---------------------------------------------------------------------------

class ImageLabel(QLabel):
    """A QLabel that asynchronously loads and displays an image from a URL.

    Usage:
        label = ImageLabel(placeholder_text="Loading...")
        label.load_url("https://example.com/cover.jpg")
        # or with a specific size:
        label.load_url("https://example.com/cover.jpg", size=QSize(180, 180))

    Signals:
        image_loaded(str) - emitted with URL when image loads successfully
        image_failed(str, str) - emitted with URL and error message
    """

    image_loaded = Signal(str)
    image_failed = Signal(str, str)

    def __init__(self, placeholder_text: str = "Loading...", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder_text
        self._url: str | None = None
        self._worker: _DownloadWorker | None = None
        self._current_pixmap: QPixmap | None = None

        self.setText(placeholder_text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def load_url(self, url: str | None, size: QSize | None = None) -> None:
        """Start loading an image from the given URL.

        If url is None or empty, shows placeholder text.
        If the same URL is already loaded, does nothing.
        """
        if not url:
            self.setText(self._placeholder)
            self._current_pixmap = None
            self._url = None
            return

        if url == self._url and self._current_pixmap is not None:
            return  # already loaded

        self._url = url
        self.setText("Loading...")

        # Cancel previous download cooperatively (not terminate!)
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            # Don't wait -- just let the old worker finish silently;
            # the stale-URL check in _on_loaded prevents stale images.

        self._worker = _DownloadWorker(url, size)
        self._worker.image_ready.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, url: str, image: QImage) -> None:
        if url != self._url:
            return  # stale response
        # Convert QImage -> QPixmap on the main thread (thread-safe)
        pixmap = QPixmap.fromImage(image)
        self._current_pixmap = pixmap
        self.setPixmap(pixmap)
        self.image_loaded.emit(url)

    def _on_error(self, url: str, error: str) -> None:
        if url != self._url:
            return
        self.setText(self._placeholder)
        self.image_failed.emit(url, error)

    def clear_image(self) -> None:
        """Reset to placeholder state."""
        self._url = None
        self._current_pixmap = None
        self.setText(self._placeholder)


# ---------------------------------------------------------------------------
# Convenience function for one-shot image loading
# ---------------------------------------------------------------------------

def load_image_async(
    url: str,
    callback,
    error_callback=None,
    size: QSize | None = None,
    parent: QObject | None = None,
) -> _DownloadWorker:
    """Start a background download and call *callback(url, QImage)* when done.

    Returns the worker thread (caller should keep a reference to prevent GC).
    The callback receives a QImage; convert to QPixmap on the GUI thread.
    """
    worker = _DownloadWorker(url, size)
    worker.image_ready.connect(callback)
    if error_callback:
        worker.error.connect(error_callback)
    worker.start()
    return worker
