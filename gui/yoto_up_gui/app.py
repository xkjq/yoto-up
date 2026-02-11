"""Main application window with navigation shell and page stack."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from yoto_up_gui.widgets.nav_drawer import NavigationDrawer

# Page implementations
from yoto_up_gui.pages.dashboard import DashboardPage
from yoto_up_gui.pages.card_library import CardLibraryPage
from yoto_up_gui.pages.card_editor import CardEditorPage
from yoto_up_gui.pages.account import AccountPage
from yoto_up_gui.pages.devices import DevicesPage
from yoto_up_gui.pages.audio_tools import AudioToolsPage


# ---------------------------------------------------------------------------
# Page registry -- maps nav key -> (display title, page class)
# ---------------------------------------------------------------------------

_PAGE_REGISTRY: list[tuple[str, str, type[QWidget]]] = [
    ("dashboard", "Dashboard", DashboardPage),
    ("card_library", "Card Library", CardLibraryPage),
    ("card_editor", "Card Editor", CardEditorPage),
    ("account", "Account", AccountPage),
    ("devices", "Devices", DevicesPage),
    ("audio_tools", "Audio Tools", AudioToolsPage),
]


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Top-level application window with toolbar, navigation drawer, and
    a stacked widget that holds all pages.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Yoto-UP Card Manager")
        self.resize(1200, 800)
        self.setMinimumSize(800, 600)

        # Central widget wrapping everything
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- toolbar -------------------------------------------------------
        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("toolbar")
        toolbar_frame.setFixedHeight(52)
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(4, 0, 12, 0)
        toolbar_layout.setSpacing(4)

        self._hamburger_btn = QPushButton("\u2630")  # trigram / hamburger
        self._hamburger_btn.setObjectName("hamburger_button")
        self._hamburger_btn.setFixedSize(44, 44)
        self._hamburger_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toolbar_layout.addWidget(self._hamburger_btn)

        self._title_label = QLabel("Dashboard")
        self._title_label.setObjectName("page_title")
        toolbar_layout.addWidget(self._title_label)

        toolbar_layout.addStretch()
        root_layout.addWidget(toolbar_frame)

        # ---- body (nav drawer + page stack) --------------------------------
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._nav_drawer = NavigationDrawer()
        body_layout.addWidget(self._nav_drawer)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        body_layout.addWidget(self._stack)

        root_layout.addWidget(body)

        # ---- pages ----------------------------------------------------------
        self._pages: dict[str, QWidget] = {}
        self._page_titles: dict[str, str] = {}

        for key, title, page_cls in _PAGE_REGISTRY:
            page = page_cls()
            self._pages[key] = page
            self._page_titles[key] = title
            self._stack.addWidget(page)

        # Show dashboard by default
        self._switch_page("dashboard")

        # ---- signals --------------------------------------------------------
        self._hamburger_btn.clicked.connect(self._nav_drawer.toggle)
        self._nav_drawer.page_selected.connect(self._switch_page)

    # ---- public helpers ----------------------------------------------------

    def get_page(self, key: str) -> QWidget | None:
        """Return the page widget registered under *key*, or ``None``."""
        return self._pages.get(key)

    def switch_to(self, key: str) -> None:
        """Programmatically navigate to a page by key."""
        self._switch_page(key)

    # ---- internal ----------------------------------------------------------

    def _switch_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        self._title_label.setText(self._page_titles.get(key, ""))
        self._nav_drawer.set_active_page(key)
