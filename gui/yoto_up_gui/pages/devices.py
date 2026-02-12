"""Device Manager page for viewing Yoto player devices and their status."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from yoto_up.api.devices import get_devices, get_device_status
from yoto_up.models.device import Device, DeviceStatus

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
_OVERLAY = "#45475a"


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
# DevicesPage
# ---------------------------------------------------------------------------

class DevicesPage(QWidget):
    """List registered Yoto devices and inspect their live status.

    Signals
    -------
    navigate_to(str)
        Request navigation to another page by key.
    """

    navigate_to = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("devices_page")
        self._client = None
        self._devices: list[Device] = []
        self._worker: Worker | None = None
        self._status_worker: Worker | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_client(self, client) -> None:
        """Provide the authenticated :class:`YotoClient`."""
        self._client = client

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("Devices")
        title.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {_TEXT};"
        )
        header.addWidget(title)
        header.addStretch()

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        header.addWidget(self._status_label)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(self._button_style(_ACCENT))
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_devices)
        header.addWidget(refresh_btn)

        root.addLayout(header)

        # Splitter: device list | device detail
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_SURFACE}; width: 3px; }}"
        )
        root.addWidget(splitter, 1)

        # ---- Left: device list ----
        left_frame = QFrame()
        left_frame.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border-radius: 8px; }}"
        )
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)

        list_title = QLabel("Registered Devices")
        list_title.setStyleSheet(
            f"color: {_TEXT}; font-weight: bold; font-size: 13px; padding: 4px;"
        )
        left_layout.addWidget(list_title)

        self._device_list = QListWidget()
        self._device_list.setStyleSheet(
            f"QListWidget {{ background: {_BG}; color: {_TEXT}; border: 1px solid {_SURFACE}; "
            f"border-radius: 4px; font-size: 13px; }}"
            f"QListWidget::item {{ padding: 8px 10px; border-bottom: 1px solid {_OVERLAY}; }}"
            f"QListWidget::item:selected {{ background: {_ACCENT}; color: {_BG}; }}"
            f"QListWidget::item:hover {{ background: {_OVERLAY}; }}"
        )
        self._device_list.currentRowChanged.connect(self._on_device_selected)
        left_layout.addWidget(self._device_list, 1)

        self._list_placeholder = QLabel("No devices loaded.\nClick Refresh to fetch devices.")
        self._list_placeholder.setStyleSheet(
            f"color: {_SUBTEXT}; font-size: 12px; padding: 20px;"
        )
        self._list_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self._list_placeholder)

        splitter.addWidget(left_frame)

        # ---- Right: device detail ----
        right_frame = QFrame()
        right_frame.setStyleSheet(
            f"QFrame {{ background: {_SURFACE}; border-radius: 8px; }}"
        )
        right_outer = QVBoxLayout(right_frame)
        right_outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {_SURFACE}; }}"
        )
        right_outer.addWidget(scroll)

        self._detail_container = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(16, 12, 16, 12)
        self._detail_layout.setSpacing(12)
        scroll.setWidget(self._detail_container)

        # Placeholder
        self._detail_placeholder = QLabel("Select a device to view details.")
        self._detail_placeholder.setStyleSheet(
            f"color: {_SUBTEXT}; font-size: 14px; padding: 40px;"
        )
        self._detail_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_layout.addWidget(self._detail_placeholder)

        # Detail widgets (initially hidden, built on demand)
        self._detail_widgets_frame = QFrame()
        self._detail_widgets_frame.setVisible(False)
        self._build_detail_widgets()
        self._detail_layout.addWidget(self._detail_widgets_frame)

        self._detail_layout.addStretch()

        splitter.addWidget(right_frame)

        # Splitter proportions
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def _build_detail_widgets(self) -> None:
        """Pre-build all the label/progress-bar widgets for the detail panel."""
        layout = QVBoxLayout(self._detail_widgets_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Device name header
        self._detail_name = QLabel("")
        self._detail_name.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {_TEXT};"
        )
        layout.addWidget(self._detail_name)

        # Identity group
        identity_group = self._make_group("Identity")
        id_layout = QVBoxLayout(identity_group)
        self._lbl_device_id = self._make_detail_row(id_layout, "Device ID")
        self._lbl_device_type = self._make_detail_row(id_layout, "Type")
        self._lbl_device_family = self._make_detail_row(id_layout, "Family")
        self._lbl_firmware = self._make_detail_row(id_layout, "Firmware")
        layout.addWidget(identity_group)

        # Status group
        status_group = self._make_group("Status")
        st_layout = QVBoxLayout(status_group)

        # Online indicator
        online_row = QHBoxLayout()
        online_label = QLabel("Online:")
        online_label.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        online_label.setFixedWidth(120)
        online_row.addWidget(online_label)
        self._online_indicator = QLabel("")
        self._online_indicator.setFixedSize(14, 14)
        self._online_indicator.setStyleSheet(
            f"background: {_SUBTEXT}; border-radius: 7px;"
        )
        online_row.addWidget(self._online_indicator)
        self._online_text = QLabel("Unknown")
        self._online_text.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        online_row.addWidget(self._online_text)
        online_row.addStretch()
        st_layout.addLayout(online_row)

        # Battery
        battery_row = QHBoxLayout()
        battery_lbl = QLabel("Battery:")
        battery_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        battery_lbl.setFixedWidth(120)
        battery_row.addWidget(battery_lbl)
        self._battery_bar = QProgressBar()
        self._battery_bar.setRange(0, 100)
        self._battery_bar.setValue(0)
        self._battery_bar.setFixedHeight(18)
        self._battery_bar.setStyleSheet(self._progress_style(_GREEN))
        battery_row.addWidget(self._battery_bar, 1)
        self._battery_text = QLabel("")
        self._battery_text.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        self._battery_text.setFixedWidth(50)
        battery_row.addWidget(self._battery_text)
        st_layout.addLayout(battery_row)

        # Storage
        storage_row = QHBoxLayout()
        storage_lbl = QLabel("Storage:")
        storage_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        storage_lbl.setFixedWidth(120)
        storage_row.addWidget(storage_lbl)
        self._storage_bar = QProgressBar()
        self._storage_bar.setRange(0, 100)
        self._storage_bar.setValue(0)
        self._storage_bar.setFixedHeight(18)
        self._storage_bar.setStyleSheet(self._progress_style(_ACCENT))
        storage_row.addWidget(self._storage_bar, 1)
        self._storage_text = QLabel("")
        self._storage_text.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        self._storage_text.setFixedWidth(100)
        storage_row.addWidget(self._storage_text)
        st_layout.addLayout(storage_row)

        # WiFi strength
        wifi_row = QHBoxLayout()
        wifi_lbl = QLabel("WiFi Strength:")
        wifi_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        wifi_lbl.setFixedWidth(120)
        wifi_row.addWidget(wifi_lbl)
        self._wifi_bar = QProgressBar()
        self._wifi_bar.setRange(0, 100)
        self._wifi_bar.setValue(0)
        self._wifi_bar.setFixedHeight(18)
        self._wifi_bar.setStyleSheet(self._progress_style(_YELLOW))
        wifi_row.addWidget(self._wifi_bar, 1)
        self._wifi_text = QLabel("")
        self._wifi_text.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        self._wifi_text.setFixedWidth(80)
        wifi_row.addWidget(self._wifi_text)
        st_layout.addLayout(wifi_row)

        self._lbl_temperature = self._make_detail_row(st_layout, "Temperature")
        self._lbl_last_updated = self._make_detail_row(st_layout, "Last Updated")

        layout.addWidget(status_group)

        # Volume group
        volume_group = self._make_group("Volume (read-only)")
        vol_layout = QVBoxLayout(volume_group)

        # System volume
        sys_vol_row = QHBoxLayout()
        sys_vol_lbl = QLabel("System Volume:")
        sys_vol_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        sys_vol_lbl.setFixedWidth(120)
        sys_vol_row.addWidget(sys_vol_lbl)
        self._sys_vol_bar = QProgressBar()
        self._sys_vol_bar.setRange(0, 100)
        self._sys_vol_bar.setValue(0)
        self._sys_vol_bar.setFixedHeight(18)
        self._sys_vol_bar.setStyleSheet(self._progress_style(_ACCENT))
        sys_vol_row.addWidget(self._sys_vol_bar, 1)
        self._sys_vol_text = QLabel("")
        self._sys_vol_text.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        self._sys_vol_text.setFixedWidth(50)
        sys_vol_row.addWidget(self._sys_vol_text)
        vol_layout.addLayout(sys_vol_row)

        # User volume
        usr_vol_row = QHBoxLayout()
        usr_vol_lbl = QLabel("User Volume:")
        usr_vol_lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        usr_vol_lbl.setFixedWidth(120)
        usr_vol_row.addWidget(usr_vol_lbl)
        self._usr_vol_bar = QProgressBar()
        self._usr_vol_bar.setRange(0, 100)
        self._usr_vol_bar.setValue(0)
        self._usr_vol_bar.setFixedHeight(18)
        self._usr_vol_bar.setStyleSheet(self._progress_style(_ACCENT))
        usr_vol_row.addWidget(self._usr_vol_bar, 1)
        self._usr_vol_text = QLabel("")
        self._usr_vol_text.setStyleSheet(f"color: {_SUBTEXT}; font-size: 11px;")
        self._usr_vol_text.setFixedWidth(50)
        usr_vol_row.addWidget(self._usr_vol_text)
        vol_layout.addLayout(usr_vol_row)

        layout.addWidget(volume_group)

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_group(title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet(
            f"QGroupBox {{ color: {_TEXT}; font-weight: bold; font-size: 13px; "
            f"background: {_BG}; border: 1px solid {_OVERLAY}; "
            f"border-radius: 6px; margin-top: 8px; padding: 16px 10px 10px 10px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; "
            f"padding: 0 6px; }}"
        )
        return group

    @staticmethod
    def _make_detail_row(parent_layout, label_text: str) -> QLabel:
        """Add a label: value row and return the value label."""
        row = QHBoxLayout()
        lbl = QLabel(f"{label_text}:")
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold;")
        lbl.setFixedWidth(120)
        row.addWidget(lbl)
        value = QLabel("--")
        value.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(value, 1)
        parent_layout.addLayout(row)
        return value

    @staticmethod
    def _button_style(color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; color: {_BG}; border: none; "
            f"border-radius: 4px; padding: 6px 14px; font-weight: bold; font-size: 12px; }}"
            f"QPushButton:hover {{ opacity: 0.85; }}"
            f"QPushButton:pressed {{ opacity: 0.7; }}"
            f"QPushButton:disabled {{ background: {_SUBTEXT}; }}"
        )

    @staticmethod
    def _progress_style(color: str) -> str:
        return (
            f"QProgressBar {{ background: {_OVERLAY}; border: none; border-radius: 4px; "
            f"text-align: center; color: {_BG}; font-size: 10px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )

    # ------------------------------------------------------------------
    # Device list loading
    # ------------------------------------------------------------------

    def _refresh_devices(self) -> None:
        if not self._client:
            QMessageBox.warning(
                self, "Not Connected",
                "No API client. Please log in on the Account page.",
            )
            return

        self._status_label.setText("Loading devices...")
        self._status_label.setStyleSheet(f"color: {_YELLOW}; font-size: 12px;")
        self._worker = Worker(get_devices, self._client)
        self._worker.finished.connect(self._on_devices_loaded)
        self._worker.error.connect(self._on_devices_error)
        self._worker.start()

    def _on_devices_loaded(self, devices: list[Device]) -> None:
        self._devices = devices
        self._device_list.clear()

        if not devices:
            self._list_placeholder.setVisible(True)
            self._list_placeholder.setText("No devices found.")
            self._status_label.setText("0 devices")
            self._status_label.setStyleSheet(f"color: {_SUBTEXT}; font-size: 12px;")
            return

        self._list_placeholder.setVisible(False)
        for device in devices:
            online_icon = "\u2B24 " if device.online else "\u25CB "
            item = QListWidgetItem(f"{online_icon}{device.name}")
            item.setData(Qt.ItemDataRole.UserRole, device.deviceId)
            self._device_list.addItem(item)

        self._status_label.setText(f"{len(devices)} device(s)")
        self._status_label.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")

    def _on_devices_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")
        self._status_label.setStyleSheet(f"color: {_RED}; font-size: 12px;")

    # ------------------------------------------------------------------
    # Device selection
    # ------------------------------------------------------------------

    def _on_device_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._devices):
            return

        device = self._devices[row]
        self._show_device_basic(device)

        # Fetch live status
        if self._client:
            self._status_label.setText(f"Loading status for {device.name}...")
            self._status_label.setStyleSheet(f"color: {_YELLOW}; font-size: 12px;")
            status_worker = Worker(get_device_status, self._client, device.deviceId)
            status_worker.finished.connect(
                lambda status, dev=device: self._on_status_loaded(dev, status)
            )
            status_worker.error.connect(self._on_status_error)
            self._status_worker = status_worker
            status_worker.start()

    def _show_device_basic(self, device: Device) -> None:
        """Populate the detail panel with data from the :class:`Device`."""
        self._detail_placeholder.setVisible(False)
        self._detail_widgets_frame.setVisible(True)

        self._detail_name.setText(device.name)
        self._lbl_device_id.setText(device.deviceId)
        self._lbl_device_type.setText(device.deviceType)
        self._lbl_device_family.setText(device.deviceFamily)
        self._lbl_firmware.setText("--")

        if device.online:
            self._online_indicator.setStyleSheet(
                f"background: {_GREEN}; border-radius: 7px;"
            )
            self._online_text.setText("Online")
            self._online_text.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
        else:
            self._online_indicator.setStyleSheet(
                f"background: {_RED}; border-radius: 7px;"
            )
            self._online_text.setText("Offline")
            self._online_text.setStyleSheet(f"color: {_RED}; font-size: 12px;")

        # Reset dynamic fields until status is loaded
        self._battery_bar.setValue(0)
        self._battery_text.setText("--")
        self._storage_bar.setValue(0)
        self._storage_text.setText("--")
        self._wifi_bar.setValue(0)
        self._wifi_text.setText("--")
        self._lbl_temperature.setText("--")
        self._lbl_last_updated.setText("--")
        self._sys_vol_bar.setValue(0)
        self._sys_vol_text.setText("--")
        self._usr_vol_bar.setValue(0)
        self._usr_vol_text.setText("--")

    def _on_status_loaded(self, device: Device, status: DeviceStatus) -> None:
        self._status_label.setText("")

        # Firmware
        self._lbl_firmware.setText(status.firmwareVersion or "--")

        # Battery
        bat = status.batteryLevelPercentage
        if bat is not None:
            self._battery_bar.setValue(bat)
            self._battery_text.setText(f"{bat}%")
            charging = " (charging)" if status.isCharging else ""
            self._battery_text.setText(f"{bat}%{charging}")
        else:
            self._battery_bar.setValue(0)
            self._battery_text.setText("N/A")

        # Storage
        total = status.totalDiskSpaceBytes
        free = status.freeDiskSpaceBytes
        if total and free and total > 0:
            used = total - free
            pct = max(0, min(100, int((used / total) * 100)))
            self._storage_bar.setValue(pct)
            total_mb = total / (1024 * 1024)
            free_mb = free / (1024 * 1024)
            self._storage_text.setText(
                f"{free_mb:.0f} / {total_mb:.0f} MB free"
            )
        else:
            self._storage_bar.setValue(0)
            self._storage_text.setText("N/A")

        # WiFi
        wifi = status.wifiStrength
        if wifi is not None:
            # wifiStrength is typically dBm (negative), map to percentage
            # Roughly: -30 = excellent, -70 = weak, -90 = unusable
            wifi_pct = max(0, min(100, int((wifi + 90) * 100 / 60)))
            self._wifi_bar.setValue(wifi_pct)
            ssid = status.networkSsid or ""
            self._wifi_text.setText(f"{wifi} dBm {ssid}")
        else:
            self._wifi_bar.setValue(0)
            self._wifi_text.setText("N/A")

        # Temperature
        temp = status.temperatureCelcius
        if temp is not None:
            self._lbl_temperature.setText(f"{temp} C")
        else:
            self._lbl_temperature.setText("N/A")

        # Last updated
        self._lbl_last_updated.setText(status.updatedAt or "Unknown")

        # Volumes
        sys_vol = status.systemVolumePercentage
        if sys_vol is not None:
            self._sys_vol_bar.setValue(sys_vol)
            self._sys_vol_text.setText(f"{sys_vol}%")
        else:
            self._sys_vol_bar.setValue(0)
            self._sys_vol_text.setText("N/A")

        usr_vol = status.userVolumePercentage
        if usr_vol is not None:
            self._usr_vol_bar.setValue(usr_vol)
            self._usr_vol_text.setText(f"{usr_vol}%")
        else:
            self._usr_vol_bar.setValue(0)
            self._usr_vol_text.setText("N/A")

    def _on_status_error(self, msg: str) -> None:
        self._status_label.setText(f"Status error: {msg}")
        self._status_label.setStyleSheet(f"color: {_RED}; font-size: 12px;")
