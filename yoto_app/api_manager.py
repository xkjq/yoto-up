from yoto_api import YotoAPI
from yoto_app import config
from loguru import logger
import os


def ensure_api(api_ref, client=None):
    """Return the shared YotoAPI instance, creating it with `client` if needed.

    - api_ref: dict-like container where the instance is stored under 'api'
    - client: optional client id to pass to YotoAPI when creating
    """
    # prefer dict-like container
    try:
        api = api_ref.get('api') if isinstance(api_ref, dict) else None
    except Exception:
        api = None
    if api:
        return api
    cid = None
    try:
        if client is not None:
            cid = (client or '').strip()
        else:
            cid = config.CLIENT_ID if hasattr(config, 'CLIENT_ID') else ''
    except Exception:
        cid = client or ''
    api = YotoAPI(cid, auto_start_authentication=False, debug=True, app_path=os.getenv("FLET_APP_STORAGE_DATA"))
    try:
        if isinstance(api_ref, dict):
            api_ref['api'] = api
    except Exception:
        try:
            logger.error("api_manager.ensure_api: failed to set api_ref['api']")
        except Exception:
            pass
    return api
