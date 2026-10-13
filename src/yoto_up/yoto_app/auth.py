import threading

from loguru import logger
from yoto_up import oauth_pkce
from yoto_up.yoto_app.api_manager import ensure_api
from yoto_up.yoto_app import config
from yoto_up.paths import TOKENS_FILE
import flet as ft


def delete_tokens_file():
    """Delete the tokens.json file if it exists."""
    try:
        if TOKENS_FILE.exists():
            TOKENS_FILE.unlink()
    except OSError as e:
        logger.error(f"Failed to delete tokens file {TOKENS_FILE}: {e}")


def start_device_auth(
    page, instr_container=None, api_ref=None, show_snack_fn=None, enable_tabs_fn=None
):
    """Start the browser-based OAuth (PKCE) sign-in on a background thread.

    The deprecated device-code flow has been replaced by the authorization code
    flow with PKCE and a loopback redirect. A web browser is opened for the user
    to sign in, and the result is received on a temporary local server.

    - page: flet Page
    - instr_container: control to render instructions into (fallback: page.auth_instructions)
    - api_ref: dict container for storing the API instance
    - show_snack_fn: callable(message, error=False)
    - enable_tabs_fn: optional callable(page) to enable authenticated tabs
    """
    client = config.CLIENT_ID if hasattr(config, "CLIENT_ID") else None
    if not client:
        logger.error("start_device_auth: CLIENT_ID is not configured")
        if show_snack_fn:
            show_snack_fn("Client ID required", error=True)
        return

    container = (
        instr_container
        if instr_container is not None
        else getattr(page, "auth_instructions", None)
    )
    snack = show_snack_fn or (lambda *args, **kwargs: None)

    def _show_url(url):
        # Render the login URL so the user can open/copy it if the browser does
        # not launch automatically.
        try:
            if container is not None and hasattr(container, "controls"):
                container.controls.clear()
                container.controls.append(
                    ft.Text(
                        value="A browser window will open so you can sign in to Yoto. "
                        "If it does not open automatically, visit this URL:",
                        selectable=True,
                    )
                )
                container.controls.append(ft.Text(value=url, selectable=True))
                container.controls.append(
                    ft.Row(
                        controls=[
                            ft.TextButton(
                                content=ft.Text(value="Open Link"),
                                on_click=lambda e, u=url: (
                                    logger.debug(f"Opening browser for URL: {u}"),
                                    __import__("webbrowser").open(u),
                                ),
                            ),
                            ft.TextButton(
                                content=ft.Text(value="Copy Link"),
                                on_click=lambda e, u=url: (
                                    logger.debug(f"Copying URL to clipboard: {u}"),
                                    page.run_task(ft.Clipboard().set(u)),
                                ),
                            ),
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

    def _mark_complete():
        try:
            if container is not None and hasattr(container, "controls"):
                container.controls.clear()
                container.controls.append(
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
                f"start_device_auth: failed to update auth instructions on success: {e}"
            )

    def _worker():
        try:
            api = ensure_api(api_ref if isinstance(api_ref, dict) else {}, client)
            tokens = api.authenticate_with_browser(on_authorization_url=_show_url)
            access = tokens.get("access_token")
            refresh = tokens.get("refresh_token")
            api.access_token = access
            api.refresh_token = refresh
            api.save_tokens(access, refresh)
            if isinstance(api_ref, dict):
                api_ref["api"] = api
            snack("Authenticated")
            try:
                page.auth_complete()
            except Exception as e:
                logger.debug(f"start_device_auth: page.auth_complete failed: {e}")
            _mark_complete()
        except (oauth_pkce.AuthFlowError, TimeoutError) as e:
            logger.error(f"start_device_auth: auth failed: {e}")
            snack(f"Auth failed: {e}", error=True)
        except Exception as e:
            logger.error(f"start_device_auth: unexpected auth failure: {e}")
            snack(f"Auth failed: {e}", error=True)

    threading.Thread(target=_worker, daemon=True).start()
