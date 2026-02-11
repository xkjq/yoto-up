"""Slide-in navigation drawer for page switching."""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    Signal,
    Qt,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# Unicode icons used as lightweight placeholders until real icons are added.
_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("\u2302", "Dashboard", "dashboard"),
    ("\U0001F4DA", "Card Library", "card_library"),
    ("\u270E", "Card Editor", "card_editor"),
    ("\U0001F464", "Account", "account"),
    ("\U0001F4F1", "Devices", "devices"),
    ("\U0001F3B5", "Audio Tools", "audio_tools"),
]

EXPANDED_WIDTH = 240
COLLAPSED_WIDTH = 0


class NavigationDrawer(QFrame):
    """A slide-in panel from the left containing navigation links.

    Signals
    -------
    page_selected(str)
        Emitted with the page key when the user clicks a navigation item.
    """

    page_selected = Signal(str)

    # ---- animated width property ----------------------------------------
    def _get_drawer_width(self) -> int:
        return self.maximumWidth()

    def _set_drawer_width(self, w: int) -> None:
        self.setFixedWidth(max(w, 0))

    drawerWidth = Property(int, _get_drawer_width, _set_drawer_width)

    # ---- construction ---------------------------------------------------
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("nav_drawer")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(EXPANDED_WIDTH)

        self._active_page: str = "dashboard"
        self._buttons: dict[str, QPushButton] = {}
        self._expanded = True

        self._build_ui()

        # animation
        self._anim = QPropertyAnimation(self, b"drawerWidth")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    # ---- UI construction ------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(2)

        # App brand label
        brand = QLabel("  Yoto-UP")
        brand.setObjectName("page_title")
        brand.setStyleSheet("font-size: 18px; padding: 8px 16px;")
        layout.addWidget(brand)

        layout.addSpacing(8)

        for icon, label, key in _NAV_ITEMS:
            btn = QPushButton(f"  {icon}   {label}")
            btn.setObjectName("nav_button")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=key: self._on_click(k))
            layout.addWidget(btn)
            self._buttons[key] = btn

        layout.addStretch()
        self._refresh_active()

    # ---- interaction ----------------------------------------------------
    def _on_click(self, key: str) -> None:
        self.set_active_page(key)
        self.page_selected.emit(key)

    def set_active_page(self, key: str) -> None:
        """Programmatically update the highlighted navigation item."""
        self._active_page = key
        self._refresh_active()

    def _refresh_active(self) -> None:
        for k, btn in self._buttons.items():
            btn.setProperty("active", k == self._active_page)
            # Force style recalc so the dynamic property selector applies.
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ---- toggle animation -----------------------------------------------
    def toggle(self) -> None:
        """Slide the drawer open or closed."""
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        """Animate the drawer open."""
        self._anim.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(EXPANDED_WIDTH)
        self._anim.start()
        self._expanded = True

    def collapse(self) -> None:
        """Animate the drawer closed."""
        self._anim.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(COLLAPSED_WIDTH)
        self._anim.start()
        self._expanded = False

    @property
    def is_expanded(self) -> bool:  # noqa: D401
        return self._expanded
