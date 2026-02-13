"""Device operations against the Yoto API.

Functions for listing devices, querying their runtime status, and reading
or updating device configuration.
"""

from __future__ import annotations

from loguru import logger

from ..models.device import Device, DeviceObject, DeviceStatus
from .client import YotoClient


def get_devices(client: YotoClient) -> list[Device]:
    """Fetch all devices registered to the authenticated user.

    Returns a list of :class:`Device` instances.  Devices that fail to
    parse are logged and skipped.
    """
    resp = client.get("/device")
    resp.raise_for_status()
    data = resp.json()

    # The API wraps devices under a "devices" key (or may return a bare list).
    raw_devices: list[dict] = (
        data.get("devices", data) if isinstance(data, dict) else data
    )

    devices: list[Device] = []
    for raw in raw_devices:
        try:
            devices.append(Device(**raw))
        except Exception as exc:
            device_id = raw.get("deviceId", "<unknown>")
            logger.warning(f"Failed to parse device {device_id}: {exc}")
    return devices


def get_device_status(client: YotoClient, device_id: str) -> DeviceStatus:
    """Fetch the runtime status snapshot for a single device.

    Raises :class:`httpx.HTTPStatusError` on non-2xx responses.
    """
    resp = client.get(f"/device/{device_id}/status")
    resp.raise_for_status()
    data = resp.json()

    # Unwrap if nested under a key.
    raw = (
        data.get("status", data)
        if isinstance(data, dict) and "status" in data
        else data
    )
    return DeviceStatus(**raw)


def get_device_config(client: YotoClient, device_id: str) -> DeviceObject:
    """Fetch the full device object (including configuration and shortcuts).

    Returns a :class:`DeviceObject` which contains the :class:`DeviceConfig`
    as a sub-model.

    Raises :class:`httpx.HTTPStatusError` on non-2xx responses.
    """
    resp = client.get(f"/device/{device_id}")
    resp.raise_for_status()
    data = resp.json()

    # Unwrap if nested under a key.
    raw = (
        data.get("device", data)
        if isinstance(data, dict) and "device" in data
        else data
    )
    return DeviceObject(**raw)


def update_device_config(
    client: YotoClient,
    device_id: str,
    name: str,
    config: dict,
) -> dict:
    """Update a device's configuration.

    Parameters
    ----------
    client:
        An authenticated :class:`YotoClient`.
    device_id:
        The device to update.
    name:
        The human-readable name to assign to the device.
    config:
        A dict of configuration key/value pairs to merge into the device
        config.  Only the keys present in *config* are updated; existing
        keys not mentioned are left untouched.

    Returns
    -------
    The raw JSON response dict from the server.
    """
    payload = {
        "name": name,
        "config": config,
    }
    resp = client.put(f"/device/{device_id}", json=payload)
    resp.raise_for_status()
    return resp.json()
