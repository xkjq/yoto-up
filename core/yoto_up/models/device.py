"""Pydantic v2 models for Yoto devices, device status, and configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Device(BaseModel):
    """A registered Yoto device (player)."""

    model_config = ConfigDict(populate_by_name=True)

    deviceId: str
    name: str
    description: str
    online: bool
    releaseChannel: str
    deviceType: str
    deviceFamily: str
    deviceGroup: str


class DeviceStatus(BaseModel):
    """Runtime status snapshot reported by a device."""

    model_config = ConfigDict(populate_by_name=True)

    activeCard: str | None = None
    ambientLightSensorReading: int | None = None
    averageDownloadSpeedBytesSecond: int | None = None
    batteryLevelPercentage: int | None = None
    batteryLevelPercentageRaw: int | None = None
    buzzErrors: int | None = None
    cardInsertionState: int | None = None
    dayMode: int | None = None
    deviceId: str | None = None
    errorsLogged: int | None = None
    firmwareVersion: str | None = None
    freeDiskSpaceBytes: int | None = None
    isAudioDeviceConnected: bool | None = None
    isBackgroundDownloadActive: bool | None = None
    isBluetoothAudioConnected: bool | None = None
    isCharging: bool | None = None
    isNfcLocked: int | None = None
    isOnline: bool | None = None
    latestNfcTestErrorPercentage: int | None = None
    networkSsid: str | None = None
    nightlightMode: str | None = None
    playingSource: int | None = None
    powerCapabilities: str | None = None
    powerSource: int | None = None
    systemVolumePercentage: int | None = None
    taskWatchdogTimeoutCount: int | None = None
    temperatureCelcius: str | None = None
    totalDiskSpaceBytes: int | None = None
    updatedAt: str | None = None
    uptime: int | None = None
    userVolumePercentage: int | None = None
    utcOffsetSeconds: int | None = None
    utcTime: int | None = None
    wifiStrength: int | None = None


class ShortcutParams(BaseModel):
    """Parameters for a device shortcut command."""

    model_config = ConfigDict(populate_by_name=True)

    card: str | None = None
    chapter: str | None = None
    track: str | None = None


class ShortcutContentItem(BaseModel):
    """A single shortcut action (command + parameters)."""

    model_config = ConfigDict(populate_by_name=True)

    cmd: str | None = None
    params: ShortcutParams | None = None


class ModeContent(BaseModel):
    """Content list for a particular shortcut mode."""

    model_config = ConfigDict(populate_by_name=True)

    content: list[ShortcutContentItem] | None = None


class Shortcuts(BaseModel):
    """Device shortcut configuration (mode-based command mapping)."""

    model_config = ConfigDict(populate_by_name=True)

    modes: dict[str, ModeContent] | None = None
    versionId: str | None = None


class DeviceConfig(BaseModel):
    """Persisted configuration for a Yoto device."""

    model_config = ConfigDict(populate_by_name=True)

    alarms: list[dict] | None = None
    ambientColour: str | None = None
    bluetoothEnabled: str | None = None
    btHeadphonesEnabled: bool | None = None
    clockFace: str | None = None
    dayDisplayBrightness: str | None = None
    dayTime: str | None = None
    dayYotoDaily: str | None = None
    dayYotoRadio: str | None = None
    displayDimBrightness: str | None = None
    displayDimTimeout: str | None = None
    headphonesVolumeLimited: bool | None = None
    hourFormat: str | None = None
    maxVolumeLimit: str | None = None
    nightAmbientColour: str | None = None
    nightDisplayBrightness: str | None = None
    nightMaxVolumeLimit: str | None = None
    nightTime: str | None = None
    nightYotoDaily: str | None = None
    nightYotoRadio: str | None = None
    repeatAll: bool | None = None
    shutdownTimeout: str | None = None
    volumeLevel: str | None = None


class DeviceObject(BaseModel):
    """Full device record including config, shortcuts, and registration data."""

    model_config = ConfigDict(populate_by_name=True)

    config: DeviceConfig | None = None
    deviceFamily: str | None = None
    deviceGroup: str | None = None
    deviceId: str | None = None
    deviceType: str | None = None
    errorCode: str | None = None
    geoTimezone: str | None = None
    getPosix: str | None = None
    mac: str | None = None
    online: bool | None = None
    registrationCode: str | None = None
    releaseChannelId: str | None = None
    releaseChannelVersion: str | None = None
    shortcuts: Shortcuts | None = None
