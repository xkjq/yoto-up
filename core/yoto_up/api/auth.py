"""OAuth 2.0 Device Authorization Flow for Yoto.

This module implements the `device_code` grant type which is suitable for
CLI applications that cannot open a browser inline.  The flow is:

1. Call :func:`request_device_code` to obtain a user code and verification URL.
2. Display the URL/code to the user so they can authorise in a browser.
3. Call :func:`poll_for_token` which blocks until the user completes
   authorisation (or the code expires).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import httpx
from loguru import logger

from ..models.user import TokenData
from ..storage.config import CLIENT_ID

DEVICE_AUTH_URL = "https://login.yotoplay.com/oauth/device/code"
TOKEN_URL = "https://login.yotoplay.com/oauth/token"
AUDIENCE = "https://api.yotoplay.com"


class DeviceAuthError(Exception):
    """Raised when the device authorisation flow encounters an unrecoverable error."""


@dataclass
class DeviceAuthInfo:
    """Data returned by the device authorisation endpoint."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


def request_device_code() -> DeviceAuthInfo:
    """Request a device code to start the OAuth device flow.

    Raises :class:`httpx.HTTPStatusError` on non-2xx responses.
    """
    resp = httpx.post(
        DEVICE_AUTH_URL,
        data={
            "client_id": CLIENT_ID,
            "scope": "profile offline_access",
            "audience": AUDIENCE,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    info = resp.json()
    return DeviceAuthInfo(
        device_code=info["device_code"],
        user_code=info["user_code"],
        verification_uri=info.get("verification_uri", ""),
        verification_uri_complete=info.get("verification_uri_complete", ""),
        expires_in=info.get("expires_in", 300),
        interval=info.get("interval", 5),
    )


def poll_for_token(
    auth_info: DeviceAuthInfo,
    on_status: Callable[[str], None] | None = None,
) -> TokenData | None:
    """Poll the token endpoint until the user authorises or the code expires.

    Parameters
    ----------
    auth_info:
        The :class:`DeviceAuthInfo` returned by :func:`request_device_code`.
    on_status:
        Optional callback invoked with a human-readable status string on
        each poll iteration (useful for progress indicators).

    Returns
    -------
    :class:`~yoto_up.models.user.TokenData` on success, or ``None`` if the
    device code expired before the user completed authorisation.
    """
    start = time.time()
    interval = auth_info.interval

    while time.time() - start < auth_info.expires_in:
        time.sleep(interval)
        try:
            resp = httpx.post(
                TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": auth_info.device_code,
                    "client_id": CLIENT_ID,
                    "audience": AUDIENCE,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if resp.status_code == 200:
                data = resp.json()
                if on_status:
                    on_status("Authentication successful")
                return TokenData(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token", ""),
                    id_token=data.get("id_token"),
                )

            # Guard against non-JSON error responses
            try:
                body = resp.json()
            except Exception:
                logger.error(f"Non-JSON error response: {resp.status_code}")
                if on_status:
                    on_status(f"Server error (HTTP {resp.status_code})")
                continue

            error = body.get("error", "") if isinstance(body, dict) else ""

            if error == "authorization_pending":
                if on_status:
                    on_status("Waiting for authorization...")
                continue
            elif error == "slow_down":
                interval += 5
                if on_status:
                    on_status("Slowing down polling interval...")
                continue
            elif error == "expired_token":
                if on_status:
                    on_status("Device code expired")
                return None
            else:
                desc = body.get("error_description", error)
                raise DeviceAuthError(f"Auth error: {desc}")

        except (httpx.HTTPError, OSError) as exc:
            logger.error(f"HTTP error during token poll: {exc}")
            if on_status:
                on_status(f"Network error: {exc}")

    if on_status:
        on_status("Device code expired")
    return None
