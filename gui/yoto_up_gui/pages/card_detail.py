"""Card Detail overlay -- displays full card information in a modal overlay.

The overlay paints a semi-transparent dark scrim over the parent widget and
centres a scrollable detail panel.  It supports fade-in animation, keyboard
dismissal (Escape / Enter), and click-outside-to-close behaviour.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Catppuccin Mocha colour tokens
# ---------------------------------------------------------------------------

_BG_BASE = "#1e1e2e"
_BG_SURFACE = "#313244"
_BG_SURFACE_1 = "#3b3d54"
_TEXT = "#cdd6f4"
_TEXT_DIM = "#a6adc8"
_ACCENT = "#89b4fa"
_ACCENT_HOVER = "#74c7ec"
_RED = "#f38ba8"
_RED_HOVER = "#eba0ac"
_GREEN = "#a6e3a1"
_YELLOW = "#f9e2af"
_OVERLAY = "#45475a"
_SCRIM = QColor(17, 17, 27, 180)  # #11111b at ~70 % opacity


# ---------------------------------------------------------------------------
# Helper: formatted duration
# ---------------------------------------------------------------------------


def _fmt_duration(seconds: float | None) -> str:
    """Return a human-friendly ``mm:ss`` or ``hh:mm:ss`` string."""
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Status badge colours
# ---------------------------------------------------------------------------

_STATUS_COLOURS: dict[str, str] = {
    "live": _GREEN,
    "complete": _ACCENT,
    "inprogress": _YELLOW,
    "new": _TEXT_DIM,
    "archived": _OVERLAY,
}


# ---------------------------------------------------------------------------
# Card Detail Overlay
# ---------------------------------------------------------------------------


class CardDetailOverlay(QWidget):
    """Full-screen modal overlay displaying card details.

    Signals
    -------
    closed()
        Emitted when the overlay is dismissed.
    edit_requested(str)
        Emitted with the *card_id* when the user clicks **Edit**.
    delete_requested(str)
        Emitted with the *card_id* after the user confirms deletion.
    """

    closed = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._client = None
        self._card_id: str | None = None
        self._card_data: dict | None = None

        # Overlay covers the entire parent area
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Opacity effect for fade-in animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(200)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._setup_ui()
        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client) -> None:
        """Receive the :class:`YotoClient` reference."""
        self._client = client

    def show_card(self, card) -> None:
        """Populate the overlay with *card* data and display it.

        Parameters
        ----------
        card:
            A ``Card`` model instance **or** a plain ``dict`` with the same
            shape as the API JSON.  The overlay reads attributes / keys
            defensively so either form works.
        """
        if hasattr(card, "model_dump"):
            # Pydantic model -- convert to dict for uniform access
            self._card_data = card.model_dump()
        elif isinstance(card, dict):
            self._card_data = card
        else:
            return

        self._card_id = self._card_data.get("cardId")
        self._populate()
        self._show_animated()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        # Root layout fills entire overlay
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Central card panel (fixed max-width, vertically centred)
        self._panel = QFrame()
        self._panel.setFixedWidth(620)
        self._panel.setMaximumHeight(700)
        self._panel.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._panel.setStyleSheet(f"""
            QFrame {{
                background-color: {_BG_SURFACE};
                border-radius: 14px;
            }}
        """)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # -- Header (close button) -----------------------------------------
        header = QHBoxLayout()
        header.setContentsMargins(16, 12, 12, 0)
        header.addStretch()

        self._close_btn = QPushButton("X")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {_TEXT_DIM};
                font-size: 16px;
                font-weight: 700;
                border: none;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background-color: {_OVERLAY};
                color: {_TEXT};
            }}
        """)
        self._close_btn.clicked.connect(self._dismiss)
        header.addWidget(self._close_btn)
        panel_layout.addLayout(header)

        # -- Scrollable content area ---------------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {_BG_SURFACE};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {_OVERLAY};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self._scroll_content = QWidget()
        self._content_layout = QVBoxLayout(self._scroll_content)
        self._content_layout.setContentsMargins(24, 8, 24, 24)
        self._content_layout.setSpacing(12)
        scroll.setWidget(self._scroll_content)
        panel_layout.addWidget(scroll, stretch=1)

        # -- Build the inner content widgets (all initially blank) ---------
        self._build_content_widgets()

        # -- Footer buttons ------------------------------------------------
        footer = QHBoxLayout()
        footer.setContentsMargins(24, 12, 24, 16)
        footer.setSpacing(12)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedHeight(36)
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_ACCENT};
                color: {_BG_BASE};
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 6px;
                padding: 0 24px;
            }}
            QPushButton:hover {{
                background-color: {_ACCENT_HOVER};
            }}
        """)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        footer.addWidget(self._edit_btn)

        footer.addStretch()

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(36)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {_RED};
                font-size: 13px;
                font-weight: 600;
                border: 1px solid {_RED};
                border-radius: 6px;
                padding: 0 24px;
            }}
            QPushButton:hover {{
                background-color: {_RED};
                color: {_BG_BASE};
            }}
        """)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        footer.addWidget(self._delete_btn)

        panel_layout.addLayout(footer)

        # Centre the panel in the overlay
        root.addStretch()
        centre_row = QHBoxLayout()
        centre_row.addStretch()
        centre_row.addWidget(self._panel)
        centre_row.addStretch()
        root.addLayout(centre_row)
        root.addStretch()

    def _build_content_widgets(self) -> None:
        """Create the labels and sections inside the scroll area."""
        lay = self._content_layout

        # Cover image placeholder
        self._cover_label = QLabel()
        self._cover_label.setFixedHeight(220)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setStyleSheet(f"""
            background-color: {_OVERLAY};
            border-radius: 10px;
            color: {_TEXT_DIM};
            font-size: 13px;
        """)
        self._cover_label.setText("No Cover Image")
        lay.addWidget(self._cover_label)

        # Title
        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 22px;
            font-weight: 700;
        """)
        lay.addWidget(self._title_label)

        # Author
        self._author_label = QLabel()
        self._author_label.setWordWrap(True)
        self._author_label.setStyleSheet(f"""
            color: {_TEXT_DIM};
            font-size: 14px;
        """)
        lay.addWidget(self._author_label)

        # Status badge
        self._status_badge = QLabel()
        self._status_badge.setFixedHeight(24)
        self._status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_badge.setStyleSheet(f"""
            color: {_BG_BASE};
            font-size: 11px;
            font-weight: 700;
            border-radius: 12px;
            padding: 0 14px;
        """)
        self._status_badge.setMaximumWidth(120)
        lay.addWidget(self._status_badge)

        # Description
        self._desc_label = QLabel()
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 13px;
            line-height: 1.5;
        """)
        lay.addWidget(self._desc_label)

        # Separator
        lay.addWidget(self._separator())

        # Chapters / tracks header
        self._chapters_header = QLabel("Chapters & Tracks")
        self._chapters_header.setStyleSheet(f"""
            color: {_TEXT};
            font-size: 15px;
            font-weight: 600;
        """)
        lay.addWidget(self._chapters_header)

        # Chapters container (populated dynamically)
        self._chapters_container = QWidget()
        self._chapters_layout = QVBoxLayout(self._chapters_container)
        self._chapters_layout.setContentsMargins(0, 0, 0, 0)
        self._chapters_layout.setSpacing(6)
        lay.addWidget(self._chapters_container)

        # Separator
        lay.addWidget(self._separator())

        # Tags / Genre / Category
        self._tags_label = QLabel()
        self._tags_label.setWordWrap(True)
        self._tags_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self._tags_label)

        self._genre_label = QLabel()
        self._genre_label.setWordWrap(True)
        self._genre_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self._genre_label)

        self._category_label = QLabel()
        self._category_label.setWordWrap(True)
        self._category_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self._category_label)

        # Separator
        lay.addWidget(self._separator())

        # Timestamps
        self._created_label = QLabel()
        self._created_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self._created_label)

        self._updated_label = QLabel()
        self._updated_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self._updated_label)

        lay.addStretch()

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {_OVERLAY};")
        return sep

    # ------------------------------------------------------------------
    # Populate from data
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        """Fill all content widgets from ``_card_data``."""
        d = self._card_data or {}
        meta = d.get("metadata") or {}
        content = d.get("content") or {}

        # Title
        self._title_label.setText(d.get("title", "Untitled"))

        # Author
        author = meta.get("author", "")
        if author:
            self._author_label.setText(f"by {author}")
            self._author_label.setVisible(True)
        else:
            self._author_label.setVisible(False)

        # Status badge
        status_obj = meta.get("status") or {}
        status_name = status_obj.get("name", "")
        if status_name:
            colour = _STATUS_COLOURS.get(status_name, _TEXT_DIM)
            self._status_badge.setText(status_name.upper())
            self._status_badge.setStyleSheet(f"""
                QLabel {{
                    background-color: {colour};
                    color: {_BG_BASE};
                    font-size: 11px;
                    font-weight: 700;
                    border-radius: 12px;
                    padding: 2px 14px;
                }}
            """)
            self._status_badge.setVisible(True)
        else:
            self._status_badge.setVisible(False)

        # Cover placeholder (actual image loading is left to a future
        # network-image widget; for now we display the URL or a placeholder)
        cover = (meta.get("cover") or {}).get("imageL")
        if cover:
            self._cover_label.setText("Cover image available")
        else:
            self._cover_label.setText("No Cover Image")

        # Description
        desc = meta.get("description", "")
        if desc:
            self._desc_label.setText(desc)
            self._desc_label.setVisible(True)
        else:
            self._desc_label.setVisible(False)

        # Chapters & tracks
        self._populate_chapters(content.get("chapters") or [])

        # Tags
        tags = d.get("tags") or meta.get("tags") or []
        if tags:
            self._tags_label.setText(f"Tags: {', '.join(tags)}")
            self._tags_label.setVisible(True)
        else:
            self._tags_label.setVisible(False)

        # Genre
        genre = meta.get("genre") or []
        if genre:
            self._genre_label.setText(f"Genre: {', '.join(genre)}")
            self._genre_label.setVisible(True)
        else:
            self._genre_label.setVisible(False)

        # Category
        category = meta.get("category", "")
        if category and category not in ("", "none"):
            self._category_label.setText(f"Category: {category}")
            self._category_label.setVisible(True)
        else:
            self._category_label.setVisible(False)

        # Timestamps
        created = d.get("createdAt", "")
        updated = d.get("updatedAt", "")
        if created:
            self._created_label.setText(f"Created: {created}")
            self._created_label.setVisible(True)
        else:
            self._created_label.setVisible(False)
        if updated:
            self._updated_label.setText(f"Updated: {updated}")
            self._updated_label.setVisible(True)
        else:
            self._updated_label.setVisible(False)

    def _populate_chapters(self, chapters: list) -> None:
        """Fill the chapters section with chapter/track rows."""
        # Clear existing
        while self._chapters_layout.count() > 0:
            item = self._chapters_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        if not chapters:
            empty = QLabel("No chapters")
            empty.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
            self._chapters_layout.addWidget(empty)
            return

        for ch_idx, chapter in enumerate(chapters):
            ch_title = chapter.get("title", f"Chapter {ch_idx + 1}")
            ch_duration = chapter.get("duration")

            # Chapter header row
            ch_label = QLabel(
                f"{ch_idx + 1}. {ch_title}   {_fmt_duration(ch_duration)}"
            )
            ch_label.setStyleSheet(f"""
                color: {_ACCENT};
                font-size: 13px;
                font-weight: 600;
                padding: 4px 0px;
            """)
            self._chapters_layout.addWidget(ch_label)

            # Tracks within this chapter
            tracks = chapter.get("tracks") or []
            for tr_idx, track in enumerate(tracks):
                tr_title = track.get("title", f"Track {tr_idx + 1}")
                tr_dur = track.get("duration")
                tr_label = QLabel(
                    f"    {tr_idx + 1}. {tr_title}   {_fmt_duration(tr_dur)}"
                )
                tr_label.setStyleSheet(f"""
                    color: {_TEXT};
                    font-size: 12px;
                    padding-left: 16px;
                """)
                self._chapters_layout.addWidget(tr_label)

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _show_animated(self) -> None:
        """Show the overlay with a fade-in animation."""
        if self.parent():
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self.setFocus()

        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _dismiss(self) -> None:
        """Hide the overlay and emit *closed*."""
        self.hide()
        self.closed.emit()

    # ------------------------------------------------------------------
    # Painting -- semi-transparent scrim
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _SCRIM)
        painter.end()

    # ------------------------------------------------------------------
    # Interaction -- click outside or keyboard dismiss
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        """Dismiss when clicking outside the detail panel."""
        if not self._panel.geometry().contains(event.pos()):
            self._dismiss()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._dismiss()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Resize tracking -- keep overlay covering parent
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

    def parentResizeEvent(self) -> None:
        """Call this from the parent's resizeEvent to keep the overlay sized."""
        if self.parent():
            self.setGeometry(self.parent().rect())

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_edit_clicked(self) -> None:
        if self._card_id:
            self.edit_requested.emit(self._card_id)

    def _on_delete_clicked(self) -> None:
        if not self._card_id:
            return
        title = (self._card_data or {}).get("title", "this card")
        reply = QMessageBox.question(
            self,
            "Delete Card",
            f"Are you sure you want to delete \"{title}\"?\n\n"
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(self._card_id)
            self._dismiss()
