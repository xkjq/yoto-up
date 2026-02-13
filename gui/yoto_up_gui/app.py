"""Main application window with navigation shell and page stack."""

from __future__ import annotations

import httpx
from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from yoto_up.api.client import YotoClient
from yoto_up_gui.widgets.nav_drawer import NavigationDrawer

# Page implementations
from yoto_up_gui.pages.dashboard import DashboardPage
from yoto_up_gui.pages.card_library import CardLibraryPage
from yoto_up_gui.pages.card_editor import CardEditorPage
from yoto_up_gui.pages.account import AccountPage
from yoto_up_gui.pages.devices import DevicesPage
from yoto_up_gui.pages.audio_tools import AudioToolsPage
from yoto_up_gui.pages.card_detail import CardDetailOverlay


# ---------------------------------------------------------------------------
# Background workers -- each creates its OWN httpx client to avoid
# sharing the non-thread-safe httpx.Client inside YotoClient.
# ---------------------------------------------------------------------------

class _CardFetchWorker(QThread):
    """Fetch a single card's data from the API on a background thread."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, client: YotoClient, card_id: str) -> None:
        super().__init__()
        self._client = client
        self._card_id = card_id

    def run(self) -> None:
        try:
            # Ensure the token is still valid (refreshes if expired)
            self._client._ensure_valid_token()
            token = self._client.access_token
            if not token:
                self.error.emit("Not authenticated")
                return
            with httpx.Client(timeout=30.0) as http:
                resp = http.get(
                    f"{self._client.SERVER_URL}/content/{self._card_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                self.finished.emit(resp.json())
        except Exception as exc:
            self.error.emit(str(exc))


class _CardDeleteWorker(QThread):
    """Delete a card via the API on a background thread."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, client: YotoClient, card_id: str) -> None:
        super().__init__()
        self._client = client
        self._card_id = card_id

    def run(self) -> None:
        try:
            # Ensure the token is still valid (refreshes if expired)
            self._client._ensure_valid_token()
            token = self._client.access_token
            if not token:
                self.error.emit("Not authenticated")
                return
            with httpx.Client(timeout=30.0) as http:
                resp = http.delete(
                    f"{self._client.SERVER_URL}/content/{self._card_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


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

        # ---- client lifecycle ----------------------------------------------
        self._client = YotoClient()

        # Workers kept alive to prevent premature garbage-collection.
        # We also track them in a list so old workers can finish cleanly.
        self._active_workers: list[QThread] = []
        self._card_fetch_worker: _CardFetchWorker | None = None
        self._card_delete_worker: _CardDeleteWorker | None = None

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

        # ---- card detail overlay --------------------------------------------
        self._card_detail_overlay = CardDetailOverlay(central)
        self._card_detail_overlay.set_client(self._client)
        self._card_detail_overlay.edit_requested.connect(self._on_overlay_edit_requested)
        self._card_detail_overlay.delete_requested.connect(self._on_overlay_delete_requested)
        # closed signal -- no action needed, overlay hides itself

        # ---- status bar -----------------------------------------------------
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._auth_status_label = QLabel("Not authenticated")
        self._status_bar.addPermanentWidget(self._auth_status_label)

        # ---- distribute client to pages that accept it ---------------------
        self._distribute_client()

        # Show dashboard by default
        self._switch_page("dashboard")

        # ---- signals --------------------------------------------------------
        self._hamburger_btn.clicked.connect(self._nav_drawer.toggle)
        self._nav_drawer.page_selected.connect(self._switch_page)

        # Account auth flow
        account_page: AccountPage = self._pages["account"]  # type: ignore[assignment]
        account_page.auth_changed.connect(self._on_auth_changed)

        # Dashboard navigation
        dashboard_page: DashboardPage = self._pages["dashboard"]  # type: ignore[assignment]
        dashboard_page.navigate_to.connect(self._on_dashboard_navigate)
        dashboard_page.card_selected.connect(self._on_card_selected)

        # Library card selection
        library_page: CardLibraryPage = self._pages["card_library"]  # type: ignore[assignment]
        library_page.card_selected.connect(self._on_card_selected)

        # Card editor saved
        editor_page: CardEditorPage = self._pages["card_editor"]  # type: ignore[assignment]
        editor_page.card_saved.connect(self._on_card_saved)

        # Connect navigate_to on all pages that have it
        for key, page in self._pages.items():
            if hasattr(page, "navigate_to") and isinstance(
                getattr(type(page), "navigate_to", None), Signal
            ):
                page.navigate_to.connect(self._switch_page)

        # ---- initial auth status -------------------------------------------
        self._update_auth_status_display()

    # ---- public helpers ----------------------------------------------------

    def get_page(self, key: str) -> QWidget | None:
        """Return the page widget registered under *key*, or ``None``."""
        return self._pages.get(key)

    def switch_to(self, key: str) -> None:
        """Programmatically navigate to a page by key."""
        self._switch_page(key)

    # ---- client distribution -----------------------------------------------

    def _distribute_client(self) -> None:
        """Pass the client to every page that has a ``set_client`` method."""
        for page in self._pages.values():
            if hasattr(page, "set_client") and callable(page.set_client):
                page.set_client(self._client)

    # ---- worker lifecycle --------------------------------------------------

    def _track_worker(self, worker: QThread) -> None:
        """Keep a reference to *worker* and clean up when it finishes."""
        self._active_workers.append(worker)
        worker.finished.connect(lambda *_: self._remove_worker(worker))

    def _remove_worker(self, worker: QThread) -> None:
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass

    # ---- auth flow ---------------------------------------------------------

    def _on_auth_changed(self, logged_in: bool) -> None:
        """Handle login / logout from the Account page."""
        self._update_auth_status_display()
        if logged_in:
            # Re-distribute the (now authenticated) client to all pages
            self._distribute_client()
            self._card_detail_overlay.set_client(self._client)
            # Refresh data-driven pages
            dashboard: DashboardPage = self._pages["dashboard"]  # type: ignore[assignment]
            library: CardLibraryPage = self._pages["card_library"]  # type: ignore[assignment]
            dashboard.refresh()
            library.refresh()
        # When logged out we leave existing page state as-is; pages already
        # guard against a missing / unauthenticated client.

    def _update_auth_status_display(self) -> None:
        """Update the status-bar label to reflect current auth state."""
        if self._client.is_authenticated:
            self._auth_status_label.setText("Authenticated")
        else:
            self._auth_status_label.setText("Not authenticated")

    # ---- dashboard navigation ----------------------------------------------

    def _on_dashboard_navigate(self, destination: str) -> None:
        """Map dashboard quick-action names to page keys."""
        if destination == "library":
            self._switch_page("card_library")
        elif destination == "create_card":
            self._switch_page("card_editor")
            editor: CardEditorPage = self._pages["card_editor"]  # type: ignore[assignment]
            editor.new_card()
        elif destination == "devices":
            self._switch_page("devices")
        else:
            # Fall through -- treat destination as a page key
            self._switch_page(destination)

    # ---- card selection (dashboard + library) ------------------------------

    def _on_card_selected(self, card_id: str) -> None:
        """Fetch full card data and display it in the overlay."""
        if not self._client.is_authenticated:
            return
        worker = _CardFetchWorker(self._client, card_id)
        worker.finished.connect(self._on_card_fetched)
        worker.error.connect(self._on_card_fetch_error)
        self._card_fetch_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_card_fetched(self, card_data: dict) -> None:
        """Show the card detail overlay with the fetched data."""
        # The API may return the card nested under a "card" key
        if "card" in card_data and isinstance(card_data["card"], dict):
            card_data = card_data["card"]
        self._card_detail_overlay.show_card(card_data)

    def _on_card_fetch_error(self, message: str) -> None:
        """Surface card-fetch errors on the status bar."""
        self._status_bar.showMessage(f"Failed to load card: {message}", 5000)

    # ---- card detail overlay actions ---------------------------------------

    def _on_overlay_edit_requested(self, card_id: str) -> None:
        """Open the card editor with the card currently shown in the overlay."""
        self._card_detail_overlay.hide()
        card_data = self._card_detail_overlay._card_data
        if card_data is not None:
            from yoto_up.models.card import Card

            try:
                card = Card.model_validate(card_data)
            except Exception:
                card = Card(title=card_data.get("title", "Untitled"))
                card.cardId = card_id
            self._switch_page("card_editor")
            editor: CardEditorPage = self._pages["card_editor"]  # type: ignore[assignment]
            editor.edit_card(card)

    def _on_overlay_delete_requested(self, card_id: str) -> None:
        """Delete the card via the API, then refresh the library."""
        if not self._client.is_authenticated:
            return
        worker = _CardDeleteWorker(self._client, card_id)
        worker.finished.connect(self._on_card_deleted)
        worker.error.connect(self._on_card_delete_error)
        self._card_delete_worker = worker
        self._track_worker(worker)
        worker.start()

    def _on_card_deleted(self) -> None:
        """Refresh the library after a successful card deletion."""
        self._status_bar.showMessage("Card deleted.", 3000)
        library: CardLibraryPage = self._pages["card_library"]  # type: ignore[assignment]
        library.refresh()

    def _on_card_delete_error(self, message: str) -> None:
        self._status_bar.showMessage(f"Delete failed: {message}", 5000)

    # ---- card editor saved -------------------------------------------------

    def _on_card_saved(self, card_id: str) -> None:
        """After a card is saved, switch to the library and refresh."""
        self._switch_page("card_library")
        library: CardLibraryPage = self._pages["card_library"]  # type: ignore[assignment]
        library.refresh()

    # ---- internal ----------------------------------------------------------

    def _switch_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        self._title_label.setText(self._page_titles.get(key, ""))
        self._nav_drawer.set_active_page(key)

        # Auto-refresh data pages when switching to them
        if self._client.is_authenticated:
            if key == "dashboard" and hasattr(page, "refresh"):
                page.refresh()
            elif key == "card_library" and hasattr(page, "refresh"):
                page.refresh()

    # ---- resize forwarding -------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._card_detail_overlay.parentResizeEvent()

    # ---- cleanup (Fix 1: close YotoClient on window close) -----------------

    def closeEvent(self, event) -> None:
        """Ensure the HTTP client is closed when the window is destroyed."""
        # Wait briefly for any running workers to finish
        for worker in list(self._active_workers):
            if worker.isRunning():
                worker.wait(1000)
        self._client.close()
        super().closeEvent(event)
