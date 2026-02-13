"""Icon picker dialog for selecting card/chapter icons."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


_ICON_DISPLAY_SIZE = 48


class _IconThumbnail(QFrame):
    """A single selectable icon thumbnail in the picker grid."""

    clicked = Signal(str, QPixmap)          # media_id, pixmap
    double_clicked = Signal(str, QPixmap)   # media_id, pixmap

    def __init__(
        self,
        media_id: str,
        pixmap: QPixmap,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._media_id = media_id
        self._pixmap = pixmap
        self._selected = False

        self.setFixedSize(_ICON_DISPLAY_SIZE + 12, _ICON_DISPLAY_SIZE + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame { border: 2px solid transparent; border-radius: 6px; }"
            "QFrame:hover { border-color: #585b70; background-color: #313244; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        label = QLabel()
        label.setPixmap(
            pixmap.scaled(
                _ICON_DISPLAY_SIZE,
                _ICON_DISPLAY_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    @property
    def media_id(self) -> str:
        return self._media_id

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value
        if value:
            self.setStyleSheet(
                "QFrame { border: 2px solid #89b4fa; border-radius: 6px;"
                " background-color: #313244; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { border: 2px solid transparent; border-radius: 6px; }"
                "QFrame:hover { border-color: #585b70; background-color: #313244; }"
            )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._media_id, self._pixmap)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._media_id, self._pixmap)
        super().mouseDoubleClickEvent(event)


class IconPicker(QDialog):
    """Modal dialog for browsing and selecting an icon.

    Signals
    -------
    icon_selected(str, QPixmap)
        Emitted with (media_id, pixmap) when the user confirms a selection.
    """

    icon_selected = Signal(str, QPixmap)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Icon")
        self.setMinimumSize(520, 460)
        self.resize(560, 500)
        self.setModal(True)

        self._thumbnails: list[_IconThumbnail] = []
        self._selected_id: str | None = None
        self._selected_pixmap: QPixmap | None = None

        self._build_ui()

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Search bar
        search_row = QHBoxLayout()
        search_label = QLabel("Search:")
        search_label.setStyleSheet("color: #cdd6f4;")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter icons\u2026")
        self._search_edit.textChanged.connect(self._filter_icons)
        search_row.addWidget(search_label)
        search_row.addWidget(self._search_edit)
        outer.addLayout(search_row)

        # Scrollable grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setSpacing(6)
        self._scroll.setWidget(self._grid_container)
        outer.addWidget(self._scroll)

        # Buttons
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        outer.addLayout(self._bottom_bar())

    def _bottom_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._selection_label = QLabel("No icon selected")
        self._selection_label.setStyleSheet("color: #6c7086; font-size: 12px;")
        row.addWidget(self._selection_label)
        row.addStretch()
        row.addWidget(self._button_box)
        return row

    # ---- public API --------------------------------------------------------

    def set_icons(self, icons: list[tuple[str, QPixmap]]) -> None:
        """Populate the grid with *(media_id, pixmap)* pairs.

        Call this before ``exec()`` to fill the picker with data fetched from
        the API or local cache.
        """
        self._clear_grid()
        columns = max((self._scroll.viewport().width()) // 66, 4)
        for i, (media_id, pixmap) in enumerate(icons):
            thumb = _IconThumbnail(media_id, pixmap)
            thumb.clicked.connect(self._on_thumb_clicked)
            thumb.double_clicked.connect(self._on_thumb_double_clicked)
            self._thumbnails.append(thumb)
            self._grid_layout.addWidget(thumb, i // columns, i % columns)

    # ---- internal ----------------------------------------------------------

    def _clear_grid(self) -> None:
        for thumb in self._thumbnails:
            self._grid_layout.removeWidget(thumb)
            thumb.deleteLater()
        self._thumbnails.clear()
        self._selected_id = None
        self._selected_pixmap = None

    def _on_thumb_clicked(self, media_id: str, pixmap: QPixmap) -> None:
        # Deselect previous
        for thumb in self._thumbnails:
            thumb.selected = thumb.media_id == media_id
        self._selected_id = media_id
        self._selected_pixmap = pixmap
        self._selection_label.setText(f"Selected: {media_id}")

    def _on_thumb_double_clicked(self, media_id: str, pixmap: QPixmap) -> None:
        self._selected_id = media_id
        self._selected_pixmap = pixmap
        self._on_accept()

    def _on_accept(self) -> None:
        if self._selected_id and self._selected_pixmap:
            self.icon_selected.emit(self._selected_id, self._selected_pixmap)
            self.accept()

    def _filter_icons(self, text: str) -> None:
        needle = text.lower()
        for thumb in self._thumbnails:
            thumb.setVisible(needle in thumb.media_id.lower() if needle else True)
