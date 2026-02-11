"""Dashboard / Home page for the Yoto-UP GUI application.

Displays a welcome banner, library statistics, quick-action buttons,
and a grid of recently modified cards.  All API calls are dispatched to
a background ``QThread`` so the UI remains responsive.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Catppuccin Mocha colour tokens
# ---------------------------------------------------------------------------

_BG_BASE = "#1e1e2e"
_BG_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_TEXT_DIM = "#a6adc8"
_ACCENT = "#89b4fa"
_ACCENT_HOVER = "#74c7ec"
_RED = "#f38ba8"
_GREEN = "#a6e3a1"
_OVERLAY = "#45475a"


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


class _Worker(QThread):
    """Run *fn(*args)* on a background thread and emit the result."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    def run(self):
        try:
            result = self.fn(*self.args)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Card tile (small, used for "recently modified" section)
# ---------------------------------------------------------------------------


class _RecentCardTile(QFrame):
    """A compact tile representing a single recently modified card."""

    clicked = Signal(str)  # card_id

    def __init__(self, card_id: str, title: str, cover_url: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._card_id = card_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(160, 190)
        self.setObjectName("recentCardTile")
        self.setStyleSheet(f"""
            QFrame#recentCardTile {{
                background-color: {_BG_SURFACE};
                border: 1px solid {_OVERLAY};
                border-radius: 8px;
            }}
            QFrame#recentCardTile:hover {{
                border: 1px solid {_ACCENT};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Cover placeholder
        cover_label = QLabel()
        cover_label.setFixedSize(144, 130)
        cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_label.setStyleSheet(f"""
            background-color: {_OVERLAY};
            border-radius: 6px;
            color: {_TEXT_DIM};
            font-size: 11px;
        """)
        cover_label.setText("No Cover")
        self._cover_label = cover_label
        layout.addWidget(cover_label)

        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(False)
        title_label.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 12px;
            font-weight: 500;
        """)
        title_label.setMaximumWidth(144)
        # Elide long titles
        metrics = title_label.fontMetrics()
        elided = metrics.elidedText(title, Qt.TextElideMode.ElideRight, 138)
        title_label.setText(elided)
        layout.addWidget(title_label)

    # -- interaction ---------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._card_id)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------


class DashboardPage(QWidget):
    """Main dashboard / landing page of the application.

    Signals
    -------
    navigate_to(str)
        Emitted with a destination name (``"library"``, ``"create_card"``,
        ``"devices"``) when a quick-action button is clicked.
    card_selected(str)
        Emitted with a *card_id* when a recent-card tile is clicked.
    """

    navigate_to = Signal(str)
    card_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._client = None
        self._worker: _Worker | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client) -> None:
        """Receive the :class:`YotoClient` reference from the main window."""
        self._client = client

    def refresh(self) -> None:
        """Reload statistics and recent cards from the API.

        If no client is set the method is a no-op.
        """
        if self._client is None:
            return
        self._show_loading(True)
        self._worker = _Worker(self._fetch_data)
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background-color: {_BG_BASE};")

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(24)

        # -- Welcome banner ------------------------------------------------
        banner = QLabel("Welcome to Yoto-UP")
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 28px;
            font-weight: 700;
            padding: 16px;
        """)
        root.addWidget(banner)

        subtitle = QLabel("Manage your Yoto cards, tracks, and devices")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 14px;
            margin-bottom: 8px;
        """)
        root.addWidget(subtitle)

        # -- Stats section -------------------------------------------------
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_BG_SURFACE};
                border-radius: 10px;
            }}
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(24, 16, 24, 16)
        stats_layout.setSpacing(48)

        self._cards_stat = self._make_stat_widget("Cards in Library", "--")
        self._devices_stat = self._make_stat_widget("Connected Devices", "--")

        stats_layout.addStretch()
        stats_layout.addWidget(self._cards_stat)
        stats_layout.addWidget(self._devices_stat)
        stats_layout.addStretch()

        root.addWidget(stats_frame)

        # -- Quick actions -------------------------------------------------
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(16)

        btn_library = self._make_action_button("Open Library", "library")
        btn_create = self._make_action_button("Create Card", "create_card")
        btn_devices = self._make_action_button("Manage Devices", "devices")

        actions_layout.addStretch()
        actions_layout.addWidget(btn_library)
        actions_layout.addWidget(btn_create)
        actions_layout.addWidget(btn_devices)
        actions_layout.addStretch()

        root.addLayout(actions_layout)

        # -- Recently modified cards ---------------------------------------
        recent_header = QLabel("Recently Modified Cards")
        recent_header.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 16px;
            font-weight: 600;
            padding-top: 8px;
        """)
        root.addWidget(recent_header)

        # Loading indicator
        self._loading_label = QLabel("Loading...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 14px;
            padding: 24px;
        """)
        self._loading_label.setVisible(False)
        root.addWidget(self._loading_label)

        # Container for recent card tiles
        self._recent_container = QWidget()
        self._recent_layout = QHBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(12)
        self._recent_layout.addStretch()  # centre tiles
        root.addWidget(self._recent_container)

        # Placeholder when no cards are available
        self._empty_label = QLabel("No cards yet. Create or import a card to get started!")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 13px;
            padding: 24px;
        """)
        root.addWidget(self._empty_label)

        root.addStretch()

    # ------------------------------------------------------------------
    # Helpers -- widget factories
    # ------------------------------------------------------------------

    @staticmethod
    def _make_stat_widget(label_text: str, value_text: str) -> QWidget:
        """Return a small vertical widget showing a numeric value and label."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        value = QLabel(value_text)
        value.setObjectName("statValue")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet(f"""
            color: {_ACCENT};
            font-size: 32px;
            font-weight: 700;
        """)
        layout.addWidget(value)

        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 13px;
        """)
        layout.addWidget(label)

        return container

    def _make_action_button(self, text: str, target: str) -> QPushButton:
        """Return a styled quick-action button wired to *navigate_to*."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(44)
        btn.setMinimumWidth(160)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_ACCENT};
                color: {_BG_BASE};
                font-size: 14px;
                font-weight: 600;
                border: none;
                border-radius: 8px;
                padding: 0 24px;
            }}
            QPushButton:hover {{
                background-color: {_ACCENT_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {_ACCENT};
            }}
        """)
        btn.clicked.connect(lambda: self.navigate_to.emit(target))
        return btn

    # ------------------------------------------------------------------
    # Background data loading
    # ------------------------------------------------------------------

    def _fetch_data(self):
        """Called on a worker thread -- fetches cards and devices."""
        cards = []
        devices = []
        if self._client is not None:
            # Get library
            try:
                resp = self._client.get("/card/family/library")
                resp.raise_for_status()
                payload = resp.json()
                raw_cards = payload.get("cards", payload.get("card", []))
                if isinstance(raw_cards, list):
                    cards = raw_cards
            except Exception:
                cards = []

            # Get devices
            try:
                resp = self._client.get("/device/family")
                resp.raise_for_status()
                payload = resp.json()
                raw_devices = payload.get("devices", payload.get("device", []))
                if isinstance(raw_devices, list):
                    devices = raw_devices
            except Exception:
                devices = []

        return {"cards": cards, "devices": devices}

    def _on_data_loaded(self, data: dict) -> None:
        """Handle successful API response on the main thread."""
        self._show_loading(False)

        cards = data.get("cards", [])
        devices = data.get("devices", [])

        # Update stats
        self._update_stat(self._cards_stat, str(len(cards)))
        self._update_stat(self._devices_stat, str(len(devices)))

        # Populate recent cards (last 5 by updatedAt)
        self._populate_recent_cards(cards)

    def _on_data_error(self, message: str) -> None:
        """Handle API errors."""
        self._show_loading(False)
        self._update_stat(self._cards_stat, "?")
        self._update_stat(self._devices_stat, "?")
        self._empty_label.setText(f"Failed to load data: {message}")
        self._empty_label.setVisible(True)

    # ------------------------------------------------------------------
    # UI update helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_stat(stat_widget: QWidget, value: str) -> None:
        """Update the displayed value in a stat widget."""
        lbl = stat_widget.findChild(QLabel, "statValue")
        if lbl is not None:
            lbl.setText(value)

    def _populate_recent_cards(self, raw_cards: list[dict]) -> None:
        """Fill the recent-cards row with up to 5 tiles."""
        # Clear existing tiles
        while self._recent_layout.count() > 0:
            item = self._recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not raw_cards:
            self._empty_label.setVisible(True)
            self._recent_container.setVisible(False)
            return

        # Sort by updatedAt descending, take the 5 most recent
        sorted_cards = sorted(
            raw_cards,
            key=lambda c: c.get("updatedAt", "") or "",
            reverse=True,
        )[:5]

        self._recent_layout.addStretch()
        for card_data in sorted_cards:
            card_id = card_data.get("cardId", "")
            title = card_data.get("title", "Untitled")
            cover_url = None
            metadata = card_data.get("metadata")
            if isinstance(metadata, dict):
                cover = metadata.get("cover")
                if isinstance(cover, dict):
                    cover_url = cover.get("imageL")

            tile = _RecentCardTile(card_id, title, cover_url, parent=self)
            tile.clicked.connect(self.card_selected.emit)
            self._recent_layout.addWidget(tile)
        self._recent_layout.addStretch()

        self._empty_label.setVisible(False)
        self._recent_container.setVisible(True)

    def _show_loading(self, loading: bool) -> None:
        """Toggle the loading indicator and hide content while loading."""
        self._loading_label.setVisible(loading)
        self._recent_container.setVisible(not loading)
        self._empty_label.setVisible(False)
