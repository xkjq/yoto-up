"""Card Library page -- browsable grid of Yoto cards with pagination.

Cards are displayed as visual tiles in a configurable grid (3x3 or 4x4,
auto-selected from the window width).  Navigation is keyboard-friendly:
arrow keys move the selection, Page Up / Page Down / ``[`` / ``]`` change
pages, and Enter or a left-click opens the card detail overlay.

All API calls are dispatched to a background ``QThread``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QThread, QSize
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
_OVERLAY = "#45475a"
_HIGHLIGHT_BORDER = "#89b4fa"
_SELECTED_BG = "#3b3d54"


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
# Individual card tile
# ---------------------------------------------------------------------------


class _CardTile(QFrame):
    """A single card tile in the library grid."""

    clicked = Signal(str)  # card_id

    def __init__(
        self,
        card_id: str,
        title: str,
        cover_url: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._card_id = card_id
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(120, 150)
        self.setObjectName("cardTile")
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Cover image placeholder
        self._cover_label = QLabel()
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._cover_label.setMinimumHeight(80)
        self._cover_label.setStyleSheet(f"""
            background-color: {_OVERLAY};
            border-radius: 6px;
            color: {_TEXT_DIM};
            font-size: 11px;
        """)
        self._cover_label.setText("No Cover")
        layout.addWidget(self._cover_label, stretch=1)

        # Title
        self._title_label = QLabel(title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumHeight(36)
        self._title_label.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 12px;
            font-weight: 500;
        """)
        layout.addWidget(self._title_label, stretch=0)

    # -- selection -----------------------------------------------------------

    @property
    def card_id(self) -> str:
        return self._card_id

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(f"""
                QFrame#cardTile {{
                    background-color: {_SELECTED_BG};
                    border: 2px solid {_HIGHLIGHT_BORDER};
                    border-radius: 10px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#cardTile {{
                    background-color: {_BG_SURFACE};
                    border: 1px solid {_OVERLAY};
                    border-radius: 10px;
                }}
                QFrame#cardTile:hover {{
                    border: 1px solid {_ACCENT};
                }}
            """)

    # -- interaction ---------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._card_id)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Card Library page
# ---------------------------------------------------------------------------


class CardLibraryPage(QWidget):
    """Paginated grid view of all cards in the user's library.

    Signals
    -------
    card_selected(str)
        Emitted with a *card_id* when the user activates a card (Enter /
        left-click).
    navigate_to(str)
        Emitted with a destination name for the main window router.
    """

    card_selected = Signal(str)
    navigate_to = Signal(str)

    # Grid presets: (columns, rows)
    _GRID_SMALL = (3, 3)
    _GRID_LARGE = (4, 4)
    _GRID_THRESHOLD_WIDTH = 900  # pixels -- switch to 4x4 above this

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._client = None
        self._worker: _Worker | None = None

        # Data
        self._all_cards: list[dict] = []
        self._filtered_cards: list[dict] = []

        # Pagination / selection state
        self._current_page: int = 0
        self._selected_index: int = 0  # index within current page
        self._grid_cols: int = 3
        self._grid_rows: int = 3

        # Tile widgets currently displayed
        self._tiles: list[_CardTile] = []

        self._setup_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client) -> None:
        """Receive the :class:`YotoClient` reference."""
        self._client = client

    def refresh(self) -> None:
        """Reload the card library from the API."""
        if self._client is None:
            return
        self._show_loading(True)
        self._worker = _Worker(self._fetch_library)
        self._worker.finished.connect(self._on_library_loaded)
        self._worker.error.connect(self._on_library_error)
        self._worker.start()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def cards_per_page(self) -> int:
        return self._grid_cols * self._grid_rows

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @property
    def total_pages(self) -> int:
        if not self._filtered_cards:
            return 1
        return max(1, math.ceil(len(self._filtered_cards) / self.cards_per_page))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"background-color: {_BG_BASE};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        # -- Top bar: search / filter --------------------------------------
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        header = QLabel("Card Library")
        header.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 20px;
            font-weight: 700;
        """)
        top_bar.addWidget(header)

        top_bar.addStretch()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search cards...")
        self._search_input.setFixedHeight(36)
        self._search_input.setMinimumWidth(220)
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_BG_SURFACE};
                color: {_TEXT};
                border: 1px solid {_OVERLAY};
                border-radius: 6px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {_ACCENT};
            }}
        """)
        self._search_input.textChanged.connect(self._on_search_changed)
        top_bar.addWidget(self._search_input)

        root.addLayout(top_bar)

        # -- Loading label -------------------------------------------------
        self._loading_label = QLabel("Loading...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 14px;
            padding: 48px;
        """)
        self._loading_label.setVisible(False)
        root.addWidget(self._loading_label)

        # -- Empty state ---------------------------------------------------
        self._empty_label = QLabel("No cards found.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 14px;
            padding: 48px;
        """)
        self._empty_label.setVisible(False)
        root.addWidget(self._empty_label)

        # -- Card grid container -------------------------------------------
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(12)
        root.addWidget(self._grid_container, stretch=1)

        # -- Bottom bar: pagination ----------------------------------------
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        self._btn_prev = QPushButton("<  Prev")
        self._btn_prev.setFixedHeight(32)
        self._btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_prev.setStyleSheet(self._nav_button_style())
        self._btn_prev.clicked.connect(self._prev_page)
        bottom_bar.addWidget(self._btn_prev)

        bottom_bar.addStretch()

        self._page_label = QLabel("Page 1 of 1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 13px;
        """)
        bottom_bar.addWidget(self._page_label)

        bottom_bar.addStretch()

        self._btn_next = QPushButton("Next  >")
        self._btn_next.setFixedHeight(32)
        self._btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_next.setStyleSheet(self._nav_button_style())
        self._btn_next.clicked.connect(self._next_page)
        bottom_bar.addWidget(self._btn_next)

        root.addLayout(bottom_bar)

    @staticmethod
    def _nav_button_style() -> str:
        return f"""
            QPushButton {{
                background-color: {_BG_SURFACE};
                color: {_TEXT};
                border: 1px solid {_OVERLAY};
                border-radius: 6px;
                padding: 0 18px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                border: 1px solid {_ACCENT};
                color: {_ACCENT};
            }}
            QPushButton:disabled {{
                color: {_OVERLAY};
                border: 1px solid {_BG_SURFACE};
            }}
        """

    # ------------------------------------------------------------------
    # Grid sizing (auto-select 3x3 or 4x4 based on width)
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_w = event.size().width()
        if new_w >= self._GRID_THRESHOLD_WIDTH:
            cols, rows = self._GRID_LARGE
        else:
            cols, rows = self._GRID_SMALL

        if cols != self._grid_cols or rows != self._grid_rows:
            self._grid_cols = cols
            self._grid_rows = rows
            # Re-render the current page with the new grid size
            self._render_page()

    # ------------------------------------------------------------------
    # Search / filter
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        query = text.strip().lower()
        if not query:
            self._filtered_cards = list(self._all_cards)
        else:
            self._filtered_cards = [
                c for c in self._all_cards
                if query in (c.get("title", "") or "").lower()
                or query in (
                    (c.get("metadata", {}) or {}).get("author", "") or ""
                ).lower()
                or query in " ".join(
                    (c.get("tags", []) or [])
                ).lower()
            ]
        self._current_page = 0
        self._selected_index = 0
        self._render_page()

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _next_page(self) -> None:
        if self._current_page < self.total_pages - 1:
            self._current_page += 1
            self._selected_index = 0
            self._render_page()

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._selected_index = 0
            self._render_page()

    # ------------------------------------------------------------------
    # Keyboard navigation
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        key = event.key()

        # Page navigation
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_BracketRight):
            self._next_page()
            return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_BracketLeft):
            self._prev_page()
            return

        # Arrow-key selection within the grid
        if key == Qt.Key.Key_Right:
            self._move_selection(1)
            return
        if key == Qt.Key.Key_Left:
            self._move_selection(-1)
            return
        if key == Qt.Key.Key_Down:
            self._move_selection(self._grid_cols)
            return
        if key == Qt.Key.Key_Up:
            self._move_selection(-self._grid_cols)
            return

        # Activate selected card
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate_selected()
            return

        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        """Mouse wheel scrolls through pages."""
        delta = event.angleDelta().y()
        if delta < 0:
            self._next_page()
        elif delta > 0:
            self._prev_page()

    def _move_selection(self, delta: int) -> None:
        """Move the selected tile index by *delta* positions."""
        page_count = len(self._tiles)
        if page_count == 0:
            return
        new_index = self._selected_index + delta
        if 0 <= new_index < page_count:
            self._selected_index = new_index
            self._update_tile_selection()

    def _activate_selected(self) -> None:
        """Emit *card_selected* for the currently highlighted tile."""
        if 0 <= self._selected_index < len(self._tiles):
            tile = self._tiles[self._selected_index]
            self.card_selected.emit(tile.card_id)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_page(self) -> None:
        """Populate the grid with tiles for the current page."""
        # Clear previous tiles
        self._clear_grid()

        page_cards = self._page_slice()
        if not page_cards and not self._filtered_cards:
            self._empty_label.setVisible(True)
            self._grid_container.setVisible(False)
        else:
            self._empty_label.setVisible(not page_cards)
            self._grid_container.setVisible(bool(page_cards))

        self._tiles = []
        for idx, card_data in enumerate(page_cards):
            card_id = card_data.get("cardId", "")
            title = card_data.get("title", "Untitled")
            cover_url = None
            metadata = card_data.get("metadata")
            if isinstance(metadata, dict):
                cover = metadata.get("cover")
                if isinstance(cover, dict):
                    cover_url = cover.get("imageL")

            tile = _CardTile(card_id, title, cover_url, parent=self._grid_container)
            tile.clicked.connect(self.card_selected.emit)

            row = idx // self._grid_cols
            col = idx % self._grid_cols
            self._grid_layout.addWidget(tile, row, col)
            self._tiles.append(tile)

        # Fill remaining grid cells with invisible spacers so the layout
        # does not collapse unevenly
        total_cells = self._grid_cols * self._grid_rows
        for idx in range(len(page_cards), total_cells):
            spacer = QWidget()
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            row = idx // self._grid_cols
            col = idx % self._grid_cols
            self._grid_layout.addWidget(spacer, row, col)

        # Clamp selected index
        if self._selected_index >= len(self._tiles):
            self._selected_index = max(0, len(self._tiles) - 1)
        self._update_tile_selection()
        self._update_page_label()

    def _clear_grid(self) -> None:
        """Remove all widgets from the grid layout."""
        while self._grid_layout.count() > 0:
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._tiles = []

    def _page_slice(self) -> list[dict]:
        """Return the subset of filtered cards for the current page."""
        start = self._current_page * self.cards_per_page
        end = start + self.cards_per_page
        return self._filtered_cards[start:end]

    def _update_tile_selection(self) -> None:
        """Update tile border highlights to reflect ``_selected_index``."""
        for idx, tile in enumerate(self._tiles):
            tile.set_selected(idx == self._selected_index)

    def _update_page_label(self) -> None:
        page_display = self._current_page + 1
        total = self.total_pages
        self._page_label.setText(f"Page {page_display} of {total}")
        self._btn_prev.setEnabled(self._current_page > 0)
        self._btn_next.setEnabled(self._current_page < total - 1)

    # ------------------------------------------------------------------
    # Background data loading
    # ------------------------------------------------------------------

    def _fetch_library(self):
        """Called on a worker thread -- fetches the full card library."""
        if self._client is None:
            return []
        resp = self._client.get("/card/family/library")
        resp.raise_for_status()
        payload = resp.json()
        raw_cards = payload.get("cards", payload.get("card", []))
        if not isinstance(raw_cards, list):
            return []
        return raw_cards

    def _on_library_loaded(self, cards: list) -> None:
        self._show_loading(False)
        self._all_cards = cards
        self._filtered_cards = list(cards)
        self._current_page = 0
        self._selected_index = 0
        # Re-apply any active search filter
        current_query = self._search_input.text().strip()
        if current_query:
            self._on_search_changed(current_query)
        else:
            self._render_page()

    def _on_library_error(self, message: str) -> None:
        self._show_loading(False)
        self._empty_label.setText(f"Failed to load library: {message}")
        self._empty_label.setVisible(True)
        self._grid_container.setVisible(False)

    def _show_loading(self, loading: bool) -> None:
        self._loading_label.setVisible(loading)
        self._grid_container.setVisible(not loading)
        self._empty_label.setVisible(False)
