import threading
import httpx
import json
import os
import time
from yoto_up.yoto_app.api_manager import ensure_api
from loguru import logger
from yoto_up.yoto_app import config
from yoto_up.paths import TOKENS_FILE
import flet as ft


def delete_tokens_file():
    """Delete the tokens.json file if it exists."""
    try:
        if TOKENS_FILE.exists():
            TOKENS_FILE.unlink()
    except Exception as e:
        logger.error(f"Failed to delete tokens file {TOKENS_FILE}: {e}")


def poll_device_token(info, client, page, instr_container, api_ref, show_snack_fn):
    """Poll the device token endpoint and, on success, initialize YotoAPI and update UI.

    Parameters:
    - info: device code response dict
    - client: client id
    - page: flet Page object
    - instr_container: control where instructions/status are shown
    - api_ref: dict-like container to store API instance
    - show_snack_fn: callable(page, message, error=False)
    - enable_tabs_fn: optional callable(page) to enable authenticated tabs
    """
    logger.debug("[auth] poll_device_token: started background poll")
    start = time.time()
    interval = info.get("interval", 2)
    expires_in = info.get("expires_in", 300)
    token_url = "https://login.yotoplay.com/oauth/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    while time.time() - start < expires_in:
        time.sleep(interval)
        try:
            data = {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": info.get("device_code"),
                "client_id": client,
                "audience": "https://api.yotoplay.com",
            }
            token_resp = httpx.post(token_url, data=data, headers=headers)
            try:
                logger.debug(
                    f"[auth] poll_device_token: status={token_resp.status_code}"
                )
            except Exception as e:
                logger.debug(
                    f"poll_device_token: failed printing token_resp.status_code: {e}"
                )

            if token_resp.status_code == 200:
                try:
                    tokens = token_resp.json()
                except Exception as e:
                    logger.debug(
                        f"poll_device_token: failed to parse token response JSON: {e}"
                    )
                    return
                access = tokens.get("access_token")
                refresh = tokens.get("refresh_token")
                idt = tokens.get("id_token") if isinstance(tokens, dict) else None
                if access:
                    try:
                        out = {"access_token": access, "refresh_token": refresh}
                        if idt:
                            out["id_token"] = idt
                        try:
                            api = ensure_api(api_ref, client)
                            try:
                                api.save_tokens(access, refresh)
                            except Exception as e:
                                logger.debug(
                                    f"poll_device_token: api.save_tokens failed: {e}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"poll_device_token: failed to initialize API for saving tokens: {e}"
                            )
                            api = ensure_api(api_ref, client)
                    except Exception as e:
                        logger.debug(
                            f"poll_device_token: failed to write tokens.json: {e}"
                        )
                        api = ensure_api(api_ref, client)
                    api_ref["api"] = api
                    show_snack_fn("Authenticated")
                    # Enable tabs if function provided
                    page.auth_complete()
                    # Update embedded instructions
                    try:
                        if instr_container is not None and hasattr(
                            instr_container, "controls"
                        ):
                            instr_container.controls.clear()
                            instr_container.controls.append(
                                ft.Text(
                                    value="Authentication complete",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREEN,
                                )
                            )
                            page.update()
                    except Exception as e:
                        logger.debug(
                            "poll_device_token: failed updating instr_container controls; attempting fallback auth_status",
                            e,
                        )
                        try:
                            # fallback: small auth status text
                            if hasattr(page, "auth_status"):
                                page.auth_status.value = "Authentication complete"
                                page.auth_status.update()
                        except Exception as e2:
                            logger.debug(
                                f"poll_device_token: failed in fallback auth_status update: {e2}"
                            )
                    return

            # handle other responses
            try:
                err = token_resp.json()
                code = err.get("error")
                if code == "authorization_pending":
                    continue
                if code == "slow_down":
                    interval += 5
                    continue
                # surface error
                show_snack_fn(
                    f"Auth error: {err.get('error_description') or code}", error=True
                )
                if instr_container is not None and hasattr(instr_container, "controls"):
                    instr_container.controls.append(
                        ft.Text(
                            value=f"Auth error: {err.get('error_description') or code}"
                        )
                    )
                    page.update()
                return
            except Exception as e:
                logger.debug(
                    f"poll_device_token: non-json response when checking token endpoint: {e}"
                )
                # non-json response, keep polling
        except Exception as e:
            logger.debug(f"poll_device_token: unhandled exception during polling: {e}")
            try:
                show_snack_fn(f"Auth polling error: {e}", error=True)
            except Exception as e2:
                logger.debug(
                    f"poll_device_token: failed to show auth polling error snackbar: {e2}"
                )
            return

    # expired
    try:
        show_snack_fn("Device code expired", error=True)
    except Exception as e:
        logger.debug(
            f"poll_device_token: failed to show device code expired snackbar: {e}"
        )
    if instr_container is not None and hasattr(instr_container, "controls"):
        try:
            instr_container.controls.append(ft.Text(value="Device code expired"))
            page.update()
        except Exception as e:
            logger.debug(
                f"poll_device_token: failed to update instr_container with expired message: {e}"
            )


def start_device_auth(
    page, instr_container=None, api_ref=None, show_snack_fn=None, enable_tabs_fn=None
):
    """Request device code and start background poll thread.

    - page: flet Page
    - client_id_field: TextField control or str
    - instr_container: control to render instructions into (fallback: page.auth_instructions)
    - api_ref: dict container for storing API instance
    - show_snack_fn: callable(page, message, error=False)
    - enable_tabs_fn: callable(page) to enable tabs
    """
    client = config.CLIENT_ID if hasattr(config, "CLIENT_ID") else None
    if not client:
        try:
            if show_snack_fn:
                show_snack_fn("Client ID required", error=True)
            else:
                print("Client ID required")
        except Exception as e:
            logger.error(
                f"start_device_auth: failed handling missing client id notification: {e}"
            )
        return
    try:
        data = {
            "client_id": client,
            "scope": "profile offline_access",
            "audience": "https://api.yotoplay.com",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = httpx.post(
            "https://login.yotoplay.com/oauth/device/code", data=data, headers=headers
        )
        resp.raise_for_status()
        info = resp.json()
        verification_uri = info.get("verification_uri") or ""
        verification_uri_complete = (
            info.get("verification_uri_complete") or verification_uri
        )
        user_code = info.get("user_code") or ""

        # Build simple instructions in the provided container
        try:
            container = (
                instr_container
                if instr_container is not None
                else getattr(page, "auth_instructions", None)
            )
            if container is not None:
                container.controls.clear()
                container.controls.append(
                    ft.Text(
                        value=f"Visit: {verification_uri} and enter the code displayed below.",
                        selectable=True,
                    )
                )
                container.controls.append(
                    ft.Text(value=f"Code: {user_code}", selectable=True)
                )
                container.controls.append(
                    ft.Row(
                        controls=[
                            ft.Text(
                                value="Alternatively open (click) this direct link: "
                            ),
                            ft.TextButton(
                                content=verification_uri_complete,
                                on_click=lambda e, url=verification_uri_complete: (
                                    __import__("webbrowser").open(url)
                                ),
                            ),
                        ]
                    )
                )
                container.controls.append(
                    ft.Row(
                        controls=[
                            ft.Text(
                                value="Doing this links your Yoto account with this app."
                            ),
                            ft.Text(value=""),
                        ]
                    )
                )
                container.controls.append(
                    getattr(page, "auth_status", ft.Text(value=""))
                )
                page.update()
        except Exception as e:
            logger.debug(
                f"start_device_auth: failed to populate auth instructions container: {e}"
            )

        # Start background poll
        threading.Thread(
            target=lambda: poll_device_token(
                info,
                client,
                page,
                instr_container or getattr(page, "auth_instructions", None),
                api_ref or {},
                show_snack_fn or (lambda p, m, error=False: None),
            ),
            daemon=True,
        ).start()
    except Exception as e:
        logger.debug(f"start_device_auth: exception when initiating device auth: {e}")
        try:
            if show_snack_fn:
                show_snack_fn(f"Auth start failed: {e}", error=True)
        except Exception as e2:
            logger.debug(
                f"start_device_auth: failed to show auth start failed snackbar: {e2}"
            )
