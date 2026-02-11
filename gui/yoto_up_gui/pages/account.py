"""Account & Settings page for authentication and app configuration."""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from yoto_up.api.auth import DeviceAuthInfo, request_device_code, poll_for_token
from yoto_up.api.client import YotoClient
from yoto_up.models.user import TokenData
from yoto_up.storage.config import AppSettings
from yoto_up.storage.paths import (
    _cache_dir,
    _config_dir,
    _data_dir,
    API_CACHE_FILE,
    ICON_CACHE_DIR,
)

# ---------------------------------------------------------------------------
# Catppuccin Mocha palette
# ---------------------------------------------------------------------------
_BG = "#1e1e2e"
_SURFACE = "#313244"
_TEXT = "#cdd6f4"
_ACCENT = "#89b4fa"
_GREEN = "#a6e3a1"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"
_SUBTEXT = "#a6adc8"


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class Worker(QThread):
    """Run *fn* with *args* in a background thread."""

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
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Auth polling worker (special, emits status updates)
# ---------------------------------------------------------------------------

class AuthPollWorker(QThread):
    """Poll the Yoto device auth endpoint in a background thread.

    Signals
    -------
    status_update(str)
        Human-readable status during polling (e.g. "Waiting...").
    auth_complete(object)
        Emits the :class:`TokenData` on success, or ``None`` on expiry.
    auth_error(str)
        Emitted if an unrecoverable error occurs.
    """

    status_update = Signal(str)
    auth_complete = Signal(object)
    auth_error = Signal(str)

    def __init__(self, auth_info: DeviceAuthInfo):
        super().__init__()
        self._auth_info = auth_info

    def run(self):
        try:
            token_data = poll_for_token(
                self._auth_info,
                on_status=self._on_status,
            )
            self.auth_complete.emit(token_data)
        except Exception as e:
            self.auth_error.emit(str(e))

    def _on_status(self, msg: str) -> None:
        self.status_update.emit(msg)


# ---------------------------------------------------------------------------
# AccountPage
# ---------------------------------------------------------------------------

class AccountPage(QWidget):
    """Account management, settings, and data tools.

    Signals
    -------
    auth_changed(bool)
        Emitted when the user logs in (``True``) or logs out (``False``).
    navigate_to(str)
        Request navigation to another page by key.
    """

    auth_changed = Signal(bool)
    navigate_to = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("account_page")
        self._client: YotoClient | None = None
        self._auth_poll_worker: AuthPollWorker | None = None
        self._worker: Worker | None = None

        self._build_ui()
        self._load_settings_into_form()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client: YotoClient) -> None:
        """Provide the :class:`YotoClient` instance."""
        self._client = client
        self._refresh_auth_display()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {_BG}; }}"
        )
        outer.addWidget(scroll)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(16)
        scroll.setWidget(container)

        page_title = QLabel("Account & Settings")
        page_title.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {_TEXT}; padding-bottom: 4px;"
        )
        root.addWidget(page_title)

        # ---- Authentication section ----
        auth_group = self._make_group("Authentication")
        auth_layout = QVBoxLayout(auth_group)

        self._auth_status_label = QLabel("Checking...")
        self._auth_status_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 13px;")
        auth_layout.addWidget(self._auth_status_label)

        self._auth_detail_label = QLabel("")
        self._auth_detail_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        self._auth_detail_label.setWordWrap(True)
        auth_layout.addWidget(self._auth_detail_label)

        # Device code display (hidden initially)
        self._device_code_frame = QFrame()
        self._device_code_frame.setStyleSheet(
            f"QFrame {{ background: {_BG}; border: 1px solid {_ACCENT}; "
            f"border-radius: 8px; padding: 12px; }}"
        )
        dc_layout = QVBoxLayout(self._device_code_frame)
        dc_layout.setSpacing(6)

        dc_title = QLabel("Device Authorization")
        dc_title.setStyleSheet(f"color: {_ACCENT}; font-weight: bold; font-size: 14px;")
        dc_layout.addWidget(dc_title)

        self._device_code_label = QLabel("")
        self._device_code_label.setStyleSheet(
            f"color: {_YELLOW}; font-size: 28px; font-weight: bold; "
            f"letter-spacing: 4px; padding: 8px 0;"
        )
        self._device_code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dc_layout.addWidget(self._device_code_label)

        self._verification_url_label = QLabel("")
        self._verification_url_label.setStyleSheet(
            f"color: {_ACCENT}; font-size: 12px;"
        )
        self._verification_url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        dc_layout.addWidget(self._verification_url_label)

        self._poll_status_label = QLabel("")
        self._poll_status_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        dc_layout.addWidget(self._poll_status_label)

        self._device_code_frame.setVisible(False)
        auth_layout.addWidget(self._device_code_frame)

        # Auth buttons
        auth_btn_row = QHBoxLayout()
        self._login_btn = QPushButton("Login")
        self._login_btn.setStyleSheet(self._button_style(_GREEN))
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.clicked.connect(self._start_login)
        auth_btn_row.addWidget(self._login_btn)

        self._logout_btn = QPushButton("Logout")
        self._logout_btn.setStyleSheet(self._button_style(_RED))
        self._logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logout_btn.clicked.connect(self._logout)
        auth_btn_row.addWidget(self._logout_btn)

        auth_btn_row.addStretch()
        auth_layout.addLayout(auth_btn_row)

        root.addWidget(auth_group)

        # ---- Settings section ----
        settings_group = self._make_group("Settings")
        settings_layout = QVBoxLayout(settings_group)

        # Debug mode
        self._debug_check = QCheckBox("Debug mode")
        self._debug_check.setStyleSheet(f"color: {_TEXT}; font-size: 12px;")
        settings_layout.addWidget(self._debug_check)

        # Cache enabled
        self._cache_check = QCheckBox("API cache enabled")
        self._cache_check.setStyleSheet(f"color: {_TEXT}; font-size: 12px;")
        settings_layout.addWidget(self._cache_check)

        # Cache max age
        cache_age_row = QHBoxLayout()
        cache_age_lbl = QLabel("Cache max age (seconds):")
        cache_age_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px;")
        cache_age_row.addWidget(cache_age_lbl)
        self._cache_age_spin = QSpinBox()
        self._cache_age_spin.setRange(0, 86400)
        self._cache_age_spin.setSingleStep(60)
        self._cache_age_spin.setStyleSheet(self._input_style())
        cache_age_row.addWidget(self._cache_age_spin)
        cache_age_row.addStretch()
        settings_layout.addLayout(cache_age_row)

        # Audio target LUFS
        lufs_row = QHBoxLayout()
        lufs_lbl = QLabel("Audio target LUFS:")
        lufs_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px;")
        lufs_row.addWidget(lufs_lbl)
        self._lufs_spin = QDoubleSpinBox()
        self._lufs_spin.setRange(-50.0, 0.0)
        self._lufs_spin.setSingleStep(0.5)
        self._lufs_spin.setValue(-16.0)
        self._lufs_spin.setDecimals(1)
        self._lufs_spin.setStyleSheet(self._input_style())
        lufs_row.addWidget(self._lufs_spin)
        lufs_row.addStretch()
        settings_layout.addLayout(lufs_row)

        # Save settings button
        save_settings_row = QHBoxLayout()
        save_settings_btn = QPushButton("Save Settings")
        save_settings_btn.setStyleSheet(self._button_style(_GREEN))
        save_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_settings_btn.clicked.connect(self._save_settings)
        save_settings_row.addWidget(save_settings_btn)
        save_settings_row.addStretch()

        self._settings_status = QLabel("")
        self._settings_status.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        save_settings_row.addWidget(self._settings_status)

        settings_layout.addLayout(save_settings_row)
        root.addWidget(settings_group)

        # ---- Data Management section ----
        data_group = self._make_group("Data Management")
        data_layout = QVBoxLayout(data_group)

        # Storage paths
        paths_info = [
            ("Config directory", str(_config_dir)),
            ("Data directory", str(_data_dir)),
            ("Cache directory", str(_cache_dir)),
        ]
        for label_text, path_text in paths_info:
            row = QHBoxLayout()
            lbl = QLabel(f"{label_text}:")
            lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
            lbl.setFixedWidth(140)
            row.addWidget(lbl)
            path_lbl = QLabel(path_text)
            path_lbl.setStyleSheet(
                f"color: {_SUBTEXT}; font-size: 11px; background: {_BG}; "
                f"padding: 3px 6px; border-radius: 3px;"
            )
            path_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            row.addWidget(path_lbl, 1)
            data_layout.addLayout(row)

        # Buttons
        data_btn_row = QHBoxLayout()

        clear_icon_btn = QPushButton("Clear Icon Cache")
        clear_icon_btn.setStyleSheet(self._button_style(_YELLOW))
        clear_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_icon_btn.clicked.connect(self._clear_icon_cache)
        data_btn_row.addWidget(clear_icon_btn)

        clear_api_btn = QPushButton("Clear API Cache")
        clear_api_btn.setStyleSheet(self._button_style(_YELLOW))
        clear_api_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_api_btn.clicked.connect(self._clear_api_cache)
        data_btn_row.addWidget(clear_api_btn)

        open_data_btn = QPushButton("Open Data Folder")
        open_data_btn.setStyleSheet(self._button_style(_ACCENT))
        open_data_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_data_btn.clicked.connect(self._open_data_folder)
        data_btn_row.addWidget(open_data_btn)

        data_btn_row.addStretch()

        self._data_status = QLabel("")
        self._data_status.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        data_btn_row.addWidget(self._data_status)

        data_layout.addLayout(data_btn_row)
        root.addWidget(data_group)

        root.addStretch()

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_group(title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet(
            f"QGroupBox {{ color: {_TEXT}; font-weight: bold; font-size: 14px; "
            f"background: {_SURFACE}; border: 1px solid {_SURFACE}; "
            f"border-radius: 8px; margin-top: 10px; padding: 18px 12px 12px 12px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 12px; "
            f"padding: 0 6px; }}"
        )
        return group

    @staticmethod
    def _input_style() -> str:
        return (
            f"background: {_BG}; color: {_TEXT}; border: 1px solid {_SURFACE}; "
            f"border-radius: 4px; padding: 4px 6px; font-size: 12px;"
        )

    @staticmethod
    def _button_style(color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; color: {_BG}; border: none; "
            f"border-radius: 4px; padding: 6px 14px; font-weight: bold; font-size: 12px; }}"
            f"QPushButton:hover {{ opacity: 0.85; }}"
            f"QPushButton:pressed {{ opacity: 0.7; }}"
            f"QPushButton:disabled {{ background: {_SUBTEXT}; }}"
        )

    # ------------------------------------------------------------------
    # Auth display
    # ------------------------------------------------------------------

    def _refresh_auth_display(self) -> None:
        if self._client and self._client.is_authenticated:
            self._auth_status_label.setText("Logged in")
            self._auth_status_label.setStyleSheet(
                f"color: {_GREEN}; font-size: 13px; font-weight: bold;"
            )
            # Try to show token expiry
            expiry_text = ""
            if self._client.access_token:
                decoded = YotoClient.decode_jwt(self._client.access_token)
                if decoded and "exp" in decoded:
                    exp_time = decoded["exp"]
                    remaining = exp_time - time.time()
                    if remaining > 0:
                        mins = int(remaining // 60)
                        expiry_text = f"Token expires in {mins} minutes"
                    else:
                        expiry_text = "Token expired (will auto-refresh)"
            self._auth_detail_label.setText(expiry_text)
            self._login_btn.setVisible(False)
            self._logout_btn.setVisible(True)
            self._device_code_frame.setVisible(False)
        else:
            self._auth_status_label.setText("Not authenticated")
            self._auth_status_label.setStyleSheet(
                f"color: {_RED}; font-size: 13px; font-weight: bold;"
            )
            self._auth_detail_label.setText(
                "Click Login to authenticate with your Yoto account."
            )
            self._login_btn.setVisible(True)
            self._logout_btn.setVisible(False)

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def _start_login(self) -> None:
        self._login_btn.setEnabled(False)
        self._auth_status_label.setText("Requesting device code...")
        self._auth_status_label.setStyleSheet(f"color: {_YELLOW}; font-size: 13px;")

        self._worker = Worker(request_device_code)
        self._worker.finished.connect(self._on_device_code_received)
        self._worker.error.connect(self._on_login_error)
        self._worker.start()

    def _on_device_code_received(self, auth_info: DeviceAuthInfo) -> None:
        self._login_btn.setEnabled(True)

        # Show device code UI
        self._device_code_frame.setVisible(True)
        self._device_code_label.setText(auth_info.user_code)
        self._verification_url_label.setText(
            f"Visit: {auth_info.verification_uri_complete or auth_info.verification_uri}"
        )
        self._poll_status_label.setText("Waiting for authorization...")

        # Open browser
        url = auth_info.verification_uri_complete or auth_info.verification_uri
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        # Start polling in background thread
        self._auth_poll_worker = AuthPollWorker(auth_info)
        self._auth_poll_worker.status_update.connect(self._on_poll_status)
        self._auth_poll_worker.auth_complete.connect(self._on_auth_complete)
        self._auth_poll_worker.auth_error.connect(self._on_login_error)
        self._auth_poll_worker.start()

    def _on_poll_status(self, msg: str) -> None:
        self._poll_status_label.setText(msg)

    def _on_auth_complete(self, token_data) -> None:
        if token_data is None:
            self._poll_status_label.setText("Authorization expired or failed.")
            self._poll_status_label.setStyleSheet(f"color: {_RED}; font-size: 11px;")
            self._refresh_auth_display()
            return

        # Store tokens
        if self._client:
            self._client.set_tokens(token_data)
        self._device_code_frame.setVisible(False)
        self._refresh_auth_display()
        self.auth_changed.emit(True)

    def _on_login_error(self, msg: str) -> None:
        self._login_btn.setEnabled(True)
        self._auth_status_label.setText("Login failed")
        self._auth_status_label.setStyleSheet(f"color: {_RED}; font-size: 13px;")
        self._auth_detail_label.setText(msg)
        QMessageBox.critical(self, "Login Error", msg)

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    def _logout(self) -> None:
        reply = QMessageBox.question(
            self,
            "Confirm Logout",
            "Are you sure you want to log out? Saved tokens will be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._client:
                self._client.clear_tokens()
            self._refresh_auth_display()
            self.auth_changed.emit(False)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings_into_form(self) -> None:
        settings = AppSettings.load()
        self._debug_check.setChecked(settings.get("debug", False))
        self._cache_check.setChecked(settings.get("cache_enabled", False))
        self._cache_age_spin.setValue(settings.get("cache_max_age", 0))
        self._lufs_spin.setValue(settings.get("audio_target_lufs", -16.0))

    def _save_settings(self) -> None:
        settings = {
            "debug": self._debug_check.isChecked(),
            "cache_enabled": self._cache_check.isChecked(),
            "cache_max_age": self._cache_age_spin.value(),
            "audio_target_lufs": self._lufs_spin.value(),
        }
        try:
            AppSettings.save(settings)
            self._settings_status.setText("Settings saved.")
            self._settings_status.setStyleSheet(f"color: {_GREEN}; font-size: 11px;")
        except Exception as exc:
            self._settings_status.setText(f"Error: {exc}")
            self._settings_status.setStyleSheet(f"color: {_RED}; font-size: 11px;")

    # ------------------------------------------------------------------
    # Data management
    # ------------------------------------------------------------------

    def _clear_icon_cache(self) -> None:
        count = 0
        try:
            if ICON_CACHE_DIR.exists():
                for f in ICON_CACHE_DIR.iterdir():
                    if f.is_file():
                        f.unlink()
                        count += 1
            self._data_status.setText(f"Cleared {count} cached icon(s).")
            self._data_status.setStyleSheet(f"color: {_GREEN}; font-size: 11px;")
        except Exception as exc:
            self._data_status.setText(f"Error: {exc}")
            self._data_status.setStyleSheet(f"color: {_RED}; font-size: 11px;")

    def _clear_api_cache(self) -> None:
        try:
            if API_CACHE_FILE.exists():
                API_CACHE_FILE.unlink()
            self._data_status.setText("API cache cleared.")
            self._data_status.setStyleSheet(f"color: {_GREEN}; font-size: 11px;")
        except Exception as exc:
            self._data_status.setText(f"Error: {exc}")
            self._data_status.setStyleSheet(f"color: {_RED}; font-size: 11px;")

    def _open_data_folder(self) -> None:
        from PySide6.QtCore import QUrl

        path = _data_dir
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
