"""Card tile widget for the library grid view."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_TILE_WIDTH = 180
_TILE_HEIGHT = 220
_IMAGE_HEIGHT = 160

# Palette of placeholder background colours, picked by title hash.
_PLACEHOLDER_COLORS = [
    "#f38ba8",
    "#fab387",
    "#f9e2af",
    "#a6e3a1",
    "#89b4fa",
    "#cba6f7",
    "#94e2d5",
    "#f5c2e7",
    "#eba0ac",
    "#89dceb",
]


class _CoverLabel(QLabel):
    """Displays a card cover image or a coloured placeholder with the
    first letter of the card title.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_TILE_WIDTH - 4, _IMAGE_HEIGHT)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)

        self._pixmap: QPixmap | None = None
        self._letter: str = ""
        self._bg_color: QColor = QColor("#45475a")

    def set_cover(self, pixmap: QPixmap | None, title: str) -> None:
        """Set the cover image.  If *pixmap* is ``None`` a placeholder is
        generated from the first letter of *title*."""
        self._pixmap = pixmap
        self._letter = (title[:1].upper()) if title else "?"
        idx = sum(ord(c) for c in title) % len(_PLACEHOLDER_COLORS)
        self._bg_color = QColor(_PLACEHOLDER_COLORS[idx])
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Centre-crop: source rect is the centred sub-rectangle
            x = (scaled.width() - rect.width()) // 2
            y = (scaled.height() - rect.height()) // 2
            source = QRect(x, y, rect.width(), rect.height())
            painter.drawPixmap(rect, scaled, source)
        else:
            # Coloured placeholder
            painter.setBrush(self._bg_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 8, 8)

            painter.setPen(QColor("#1e1e2e"))
            font = QFont()
            font.setPixelSize(64)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._letter)

        painter.end()


class CardTile(QFrame):
    """A clickable tile representing one Yoto card in a grid view.

    Signals
    -------
    clicked(str)
        Emitted with the card ID on single click.
    double_clicked(str)
        Emitted with the card ID on double-click.
    """

    clicked = Signal(str)
    double_clicked = Signal(str)

    def __init__(
        self,
        card_id: str = "",
        title: str = "",
        cover_image: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card_tile")
        self.setFixedSize(_TILE_WIDTH, _TILE_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._card_id = card_id
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self._cover = _CoverLabel()
        layout.addWidget(self._cover, alignment=Qt.AlignmentFlag.AlignCenter)

        self._title_label = QLabel()
        self._title_label.setObjectName("card_title")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumHeight(50)
        layout.addWidget(self._title_label)

        # Apply initial data
        self.set_data(card_id, title, cover_image)

    # ---- public API --------------------------------------------------------

    @property
    def card_id(self) -> str:
        return self._card_id

    @card_id.setter
    def card_id(self, value: str) -> None:
        self._card_id = value

    @property
    def title(self) -> str:
        return self._title_label.text()

    @title.setter
    def title(self, value: str) -> None:
        self._title_label.setText(value)
        self._cover.set_cover(self._cover._pixmap, value)

    @property
    def cover_image(self) -> QPixmap | None:
        return self._cover._pixmap

    @cover_image.setter
    def cover_image(self, pixmap: QPixmap | None) -> None:
        self._cover.set_cover(pixmap, self._title_label.text())

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value
        self.setProperty("selected", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_data(
        self,
        card_id: str,
        title: str,
        cover_image: QPixmap | None = None,
    ) -> None:
        """Bulk-set all tile data in one call."""
        self._card_id = card_id
        self._title_label.setText(title)
        self._cover.set_cover(cover_image, title)

    # ---- events ------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._card_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._card_id)
        super().mouseDoubleClickEvent(event)
