import httpx
import time
import base64
import json
import os
from pathlib import Path
import hashlib
import io
import re
import threading
from typing import Optional, Callable

from loguru import logger
from yoto_up.models import DeviceObject, Track, Chapter, ChapterDisplay, TrackDisplay, CardContent, CardMetadata, CardMedia, Card, Device, DeviceStatus, DeviceConfig
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, BarColumn
from rich.table import Table
from rich import print as rprint
from PIL import Image
from bs4 import BeautifulSoup
try: # fails when debugging
    from rapidfuzz import fuzz
except (AssertionError, ModuleNotFoundError):
    # fallback: use a simple fuzzy matcher
    class fuzz:
        @staticmethod
        def ratio(a, b):
            return 100 if a == b else 0
# Make NLTK optional: prefer it when available, but provide a tiny fallback
# for environments (like web builds) where NLTK isn't installed or data
# downloads are undesirable.
try:
    import nltk
    from nltk.corpus import stopwords as nltk_stopwords
    from nltk.tokenize import word_tokenize
    _HAVE_NLTK = True
    # Try to ensure resources are present when running in desktop environments
    # where downloads are possible. If downloads fail, keep going — fallbacks
    # will be used where necessary.
    try:
        nltk.data.find('tokenizers/punkt')
    except Exception:
        try:
            nltk.download('punkt')
        except Exception:
            logger.warning("NLTK punkt tokenizer data not found and download failed; using fallback tokenizer.")
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except Exception:
        try:
            nltk.download('punkt')
            nltk.download('punkt_tab')
        except Exception:
            logger.warning("NLTK punkt tokenizer data not found and download failed; using fallback tokenizer.")
    try:
        nltk.data.find('corpora/stopwords')
    except Exception:
        try:
            nltk.download('stopwords')
        except Exception:
            logger.warning("NLTK stopwords data not found and download failed; using fallback stopwords.")
except (ImportError, ModuleNotFoundError):
    logger.error("NLTK not available; using fallback tokenizer and stopwords.")
    _HAVE_NLTK = False
    # Minimal fallback tokenizer and stopwords for basic keyword extraction
    def word_tokenize(text: str):
        return re.findall(r"\w+", text)

    class _FallbackStopwords:
        @staticmethod
        def words(lang: str = 'english'):
            return [
                "the", "and", "a", "an", "of", "in", "on", "at", "to", "for", "by", "with",
                "is", "it", "as", "from", "that", "this", "be", "are", "was", "were", "or",
                "but", "not", "so", "if", "then", "than", "too", "very", "can", "will", "just",
                "do", "does", "did", "has", "have", "had", "you", "your", "my", "our", "their",
                "his", "her", "its", "episode", "chapter"
            ]

    nltk_stopwords = _FallbackStopwords
from yoto_up.icons import render_icon
import asyncio
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.console import Console
from rich.progress import track as RichTrack

from datetime import datetime, timezone

# Centralized per-user paths
import yoto_up.paths as paths

# Helper: recursively detect unexpected (extra) fields in input data against a Pydantic model
from typing import Any, List, Type, get_origin, get_args
from pydantic import BaseModel

DEFAULT_MEDIA_ID = "aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"

def find_extra_fields(model: Type[BaseModel], data: Any, path: str = '', warn_extra=True) -> List[str]:
    """
    Recursively find keys in `data` that are not declared on the provided Pydantic `model`.

    - model: a Pydantic BaseModel class (not an instance)
    - data: the input data (typically a dict parsed from JSON)
    - path: used internally to build dotted paths for nested keys

    Returns a list of dotted paths to unexpected keys, e.g. ['chapters[0].foo', 'meta.extra']
    """
    extras: List[str] = []
    if not isinstance(data, dict):
        return extras
    # model must be a Pydantic model class
    try:
        model_fields = set(model.model_fields.keys())
    except Exception:
        return extras

    for key, val in data.items():
        full_path = f"{path}.{key}" if path else key
        if key not in model_fields:
            extras.append(full_path)
            # still continue into nested dicts to report deeper extras if useful
            if isinstance(val, dict):
                # nothing to compare against here, stop deeper recursion
                continue
            else:
                continue

        # field exists on model; attempt to inspect its declared type for nested checks
        field_info = model.model_fields.get(key)
        if not field_info:
            continue
        field_type = getattr(field_info, 'annotation', None) or getattr(field_info, 'outer_type_', None)
        origin = get_origin(field_type)
        args = get_args(field_type)

        # If value is a dict and the model field is a (subclass of) BaseModel, recurse
        if isinstance(val, dict):
            candidate = None
            if origin in (list, tuple) and args:
                candidate = args[0]
            else:
                candidate = field_type
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                extras.extend(find_extra_fields(candidate, val, full_path))

        # If value is a list and the model field is a sequence of models, recurse into elements
        if isinstance(val, list) and origin in (list, tuple) and args:
            inner = args[0]
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                for i, item in enumerate(val):
                    if isinstance(item, dict):
                        extras.extend(find_extra_fields(inner, item, f"{full_path}[{i}]") )

    if warn_extra and extras:
        logger.warning(f"Found unexpected fields in data for model {model.__name__}: {extras}")
    elif warn_extra and not extras:
        logger.debug(f"No unexpected fields found in data for model {model.__name__}")

    return extras

def has_extra_fields(model: Type[BaseModel], data: Any) -> bool:
    """Convenience wrapper returning True if any unexpected fields are present."""
    return bool(find_extra_fields(model, data))

class YotoAPI:

    SERVER_URL = "https://api.yotoplay.com"
    DEVICE_AUTH_URL = "https://login.yotoplay.com/oauth/device/code"
    TOKEN_URL = "https://login.yotoplay.com/oauth/token"
    MYO_URL = SERVER_URL + "/content/mine"
    CONTENT_URL = SERVER_URL + "/content"
    TOKEN_FILE = paths.TOKENS_FILE
    CACHE_FILE = paths.API_CACHE_FILE
    UPLOAD_ICON_CACHE_FILE = paths.UPLOAD_ICON_CACHE_FILE
    OFFICIAL_ICON_CACHE_DIR = paths.OFFICIAL_ICON_CACHE_DIR
    YOTOICONS_CACHE_DIR: Path = paths.YOTOICONS_CACHE_DIR
    VERSIONS_DIR: Path = paths.VERSIONS_DIR


    def __init__(self, client_id, debug=False, cache_requests=False, cache_max_age_seconds=0, auto_refresh_tokens=True, auto_start_authentication=True, app_path:Path|None=None):
        self.client_id = client_id
        self.debug = debug
        logger.remove()
        logger.add(lambda msg: print(msg, end=""), level="DEBUG" if debug else "WARNING")
        # Intercept standard library logging with loguru
        import logging
        class InterceptHandler(logging.Handler):
            def emit(self, record):
                try:
                    level = logger.level(record.levelname).name
                except ValueError:
                    level = record.levelno
                logger.log(level, record.getMessage())
        logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO)
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.propagate = True
        httpx_logger.setLevel(logging.INFO if debug else logging.WARNING)
        if debug:
            logger.debug("Debug mode enabled for YotoAPI")
        logger.debug(f"YotoAPI initialized with client_id: {client_id}")
        logger.debug(f"App path: {app_path}")
        self.cache_requests = cache_requests
        self.cache_max_age_seconds = cache_max_age_seconds
        self._cache_lock = threading.Lock()

        if app_path is not None:
            logger.debug(f"Using app_path: {app_path}")
            # When an explicit app_path is provided (e.g., Flet's storage), place
            # per-app files under that directory while keeping filenames/dirs from
            # the centralized defaults.
            try:
                self.TOKEN_FILE = Path(app_path) / self.TOKEN_FILE.name
            except Exception:
                self.TOKEN_FILE = Path(app_path) / 'tokens.json'
            try:
                self.CACHE_FILE = Path(app_path) / self.CACHE_FILE.name
            except Exception:
                self.CACHE_FILE = Path(app_path) / '.yoto_api_cache.json'
            try:
                # keep upload cache as a file path
                self.UPLOAD_ICON_CACHE_FILE = str(Path(app_path) / Path(self.UPLOAD_ICON_CACHE_FILE).name)
            except Exception:
                self.UPLOAD_ICON_CACHE_FILE = str(Path(app_path) / '.yoto_icon_upload_cache.json')
            try:
                self.OFFICIAL_ICON_CACHE_DIR = Path(app_path) / Path(self.OFFICIAL_ICON_CACHE_DIR).name
            except Exception:
                self.OFFICIAL_ICON_CACHE_DIR = Path(app_path) / '.yoto_icon_cache'
            try:
                self.YOTOICONS_CACHE_DIR = Path(app_path) / Path(self.YOTOICONS_CACHE_DIR).name
            except Exception:
                self.YOTOICONS_CACHE_DIR = Path(app_path) / '.yotoicons_cache'
            try:
                self.VERSIONS_DIR = Path(app_path) / Path(self.VERSIONS_DIR).name
            except Exception:
                self.VERSIONS_DIR = Path(app_path) / '.card_versions'

        self._request_cache = self._load_cache()
        self.access_token, self.refresh_token = self.load_tokens()
        if not self.access_token or not self.refresh_token:
            # No tokens at all - need full authentication
            logger.info("No valid token found, authenticating...")
            if auto_start_authentication:
                self.authenticate()
            else:
                logger.warning("No valid token found and auto_start_authentication is False. Please authenticate manually.")
        elif self.is_token_expired(self.access_token):
            # Token expired but we have refresh token - try refresh first
            if auto_refresh_tokens:
                logger.info("Token expired, refreshing with refresh token...")
                try:
                    self.refresh_tokens()
                    logger.info("Token refresh successful")
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}, falling back to full authentication...")
                    if auto_start_authentication:
                        self.authenticate()
            elif auto_start_authentication:
                self.authenticate()

        self.response_history = []

    def _load_icon_upload_cache(self):
        cache_path = Path(self.UPLOAD_ICON_CACHE_FILE)
        if cache_path.exists():
            try:
                with cache_path.open("r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_icon_upload_cache(self, cache):
        cache_path = Path(self.UPLOAD_ICON_CACHE_FILE)
        with cache_path.open("w") as f:
            json.dump(cache, f, indent=2)

    def _load_cache(self):
        if not self.cache_requests:
            return {}
        if self.CACHE_FILE.exists():
            try:
                with self.CACHE_FILE.open("r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        if not self.cache_requests:
            return
        with self._cache_lock:
            with self.CACHE_FILE.open("w") as f:
                json.dump(self._request_cache, f)

    def _ensure_versions_dir(self):
        try:
            self.VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _version_path_for(self, payload: dict) -> Path:
        # Determine an id for the card to store versions under
        card_id = payload.get("cardId") or payload.get("id") or payload.get("contentId")
        if not card_id:
            # fallback to slugified title + timestamp
            title = (payload.get("title") or "untitled").strip()[:100]
            # sanitize title to filesystem-safe
            safe_title = re.sub(r"[^0-9A-Za-z._-]", "-", title)
            card_id = f"{safe_title}"
        dir_path = self.VERSIONS_DIR / str(card_id)
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def save_version(self, payload: dict) -> Optional[Path]:
        """Save a local version (JSON file) for the provided payload and return the path."""
        try:
            self._ensure_versions_dir()
            dir_path = self._version_path_for(payload)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fname = f"{ts}.json"
            p = dir_path / fname
            with p.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            return p
        except Exception:
            return None

    def list_versions(self, card_id: str):
        """Return list of version files for a card id (or title-derived id)."""
        try:
            dir_path = self.VERSIONS_DIR / str(card_id)
            if not dir_path.exists():
                return []
            files = sorted([p for p in dir_path.iterdir() if p.suffix == ".json"], reverse=True)
            return files
        except Exception:
            return []

    def load_version(self, path: Path) -> dict:
        try:
            with Path(path).open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def restore_version(self, path: Path, return_card=True):
        """Restore a saved version by posting it to the API.
        Returns the created/updated card (model) if return_card True.
        """
        payload = self.load_version(path)
        if not payload:
            raise Exception("Version payload empty or unreadable")
        # If payload contains card id fields, they will be used by the API
        # Validate using Card model if available
        try:
            card_model = Card.model_validate(payload) if 'Card' in globals() else None
        except Exception:
            card_model = None
        if card_model is not None:
            return self.create_or_update_content(card_model, return_card=return_card, create_version=False)
        else:
            # Fallback: post raw payload
            headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
            response = httpx.post(self.CONTENT_URL, headers=headers, json=payload)
            response.raise_for_status()
            if return_card:
                return Card.model_validate(response.json().get("card") or response.json())
            return response.json()
    def _make_cache_key(self, method, url, params=None, data=None, json_data=None):
        key = {
            "method": method,
            "url": url,
            "params": params,
            "data": data,
            "json": json_data
        }
        return hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()

    def _cached_request(self, method, url, headers=None, params=None, data=None, json_data=None):
        if not self.cache_requests:
            return httpx.request(method, url, headers=headers, params=params, data=data, json=json_data)
        key = self._make_cache_key(method, url, params, data, json_data)
        now = time.time()
        cache_entry = self._request_cache.get(key)
        if cache_entry:
            age = now - cache_entry.get("timestamp", 0)
            if age <= self.cache_max_age_seconds:
                resp_data = cache_entry
                class DummyResponse:
                    def __init__(self, data):
                        self._data = data
                        self.status_code = data.get("status_code", 200)
                        self.text = json.dumps(data.get("json", {}))
                        self.ok = True
                    def json(self):
                        return self._data.get("json", {})
                    def raise_for_status(self):
                        pass
                return DummyResponse(resp_data)
        resp = httpx.request(method, url, headers=headers, params=params, data=data, json=json_data)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = None
        self._request_cache[key] = {
            "status_code": resp.status_code,
            "json": resp_json,
            "text": resp.text,
            "timestamp": now
        }
        self._save_cache()
        return resp

    def get_device_code(self):
        data = {
            "client_id": self.client_id,
            "scope": "profile offline_access",
            "audience": "https://api.yotoplay.com",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        logger.debug(f"Requesting device code: {data}")
        response = httpx.post(self.DEVICE_AUTH_URL, data=data, headers=headers)
        logger.debug(f"Device code response: {response.status_code} {response.text}")
        if not response.is_success:
            logger.error(f"Device authorization failed: {response.text}")
            raise Exception(f"Device authorization failed: {response.text}")
        return response.json()

    def poll_for_token(self, device_code, interval, expires_in):
        console = Console()
        start_time = time.time()
        interval_sec = interval
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            transient=True,
            console=console,
        ) as progress:
            task = progress.add_task("Waiting for authorization...", start=False)
            while True:
                elapsed = time.time() - start_time
                if elapsed > expires_in:
                    console.print("[bold red]Device code has expired. Please restart the device login process.[/bold red]")
                    #logger.debug("Device code has expired. Please restart the device login process.")
                    raise Exception("Device code has expired. Please restart the device login process.")
                data = {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": self.client_id,
                    "audience": "https://api.yotoplay.com",
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                #logger.debug(f"Polling for token: {data}")
                response = httpx.post(self.TOKEN_URL, data=data, headers=headers)
                #logger.debug(f"Token poll response: {response.status_code} {response.text}")
                resp_json = response.json()
                if response.is_success:
                    console.print("[bold green]Authorization successful![/bold green]")
                    logger.debug("Authorization successful, received tokens")
                    return resp_json["access_token"], resp_json.get("refresh_token")
                elif response.status_code == 403:
                    error = resp_json.get("error")
                    if error == "authorization_pending":
                        progress.update(task, description="Authorization pending, waiting...")
                        time.sleep(interval_sec)
                        continue
                    elif error == "slow_down":
                        interval_sec += 5
                        progress.update(task, description=f"Received slow_down, increasing interval to {interval_sec}s")
                        time.sleep(interval_sec)
                        continue
                    elif error == "expired_token":
                        console.print("[bold red]Device code has expired. Please restart the device login process.[/bold red]")
                        logger.debug("Device code has expired. Please restart the device login process.")
                        raise Exception("Device code has expired. Please restart the device login process.")
                    else:
                        console.print(f"[bold red]Token poll error: {resp_json.get('error_description', error)}[/bold red]")
                        logger.debug(f"Token poll error: {resp_json.get('error_description', error)}")
                        raise Exception(resp_json.get("error_description", error))
                else:
                    console.print(f"[bold red]Token request failed: {response.text}[/bold red]")
                    logger.debug(f"Token request failed: {response.text}")
                    raise Exception(f"Token request failed: {response.text}")

    def decode_jwt(self, token):
        try:
            base64_url = token.split(".")[1]
            base64_str = base64_url + '=' * (-len(base64_url) % 4)
            decoded = base64.urlsafe_b64decode(base64_str)
            return json.loads(decoded)
        except Exception as e:
            logger.error(f"Error decoding token: {e}")
            return None

    def is_token_expired(self, token):
        decoded = self.decode_jwt(token)
        if not decoded or "exp" not in decoded:
            return True
        return decoded["exp"] < time.time() + 30

    def refresh_tokens(self):
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        logger.debug(f"Refreshing tokens: {data}")
        response = httpx.post(self.TOKEN_URL, data=data, headers=headers)
        logger.debug(f"Token refresh response: {response.status_code} {response.text}")
        if not response.is_success:
            logger.error(f"Token refresh failed: {response.text}")
            raise Exception(f"Token refresh failed: {response.text}")
        resp_json = response.json()
        self.access_token = resp_json["access_token"]
        self.refresh_token = resp_json.get("refresh_token")
        self.save_tokens(self.access_token, self.refresh_token)

    def save_tokens(self, access_token, refresh_token):
        logger.debug(f"Saving tokens to {self.TOKEN_FILE}")
        with self.TOKEN_FILE.open("w") as f:
            json.dump({"access_token": access_token, "refresh_token": refresh_token}, f)

    def load_tokens(self):
        if not self.TOKEN_FILE.exists():
            logger.debug(f"Token file {self.TOKEN_FILE} does not exist.")
            return None, None
        with self.TOKEN_FILE.open("r") as f:
            data = json.load(f)
            logger.debug(f"Loaded tokens from file: {data}")
            return data.get("access_token"), data.get("refresh_token")

    def authenticate(self):
        console = Console()
        device_info = self.get_device_code()
        console.print("[bold yellow]To authorize this app, please visit:[/bold yellow]")
        console.print(f"[bold cyan]{device_info['verification_uri']}[/bold cyan]")
        console.print("[bold yellow]And enter this code:[/bold yellow]")
        console.print(f"[bold green]{device_info['user_code']}[/bold green]")
        console.print("[bold yellow]Or visit this URL directly:[/bold yellow]")
        console.print(f"[bold cyan]{device_info['verification_uri_complete']}[/bold cyan]")
        self.access_token, self.refresh_token = self.poll_for_token(
            device_info["device_code"],
            device_info.get("interval", 5),
            device_info.get("expires_in", 300)
        )
        self.save_tokens(self.access_token, self.refresh_token)

    def is_authenticated(self):
        return self.access_token is not None and not self.is_token_expired(self.access_token)

    def generate_card_chapter_and_track_icon_fields(self, card: Card):
        """
        Ensure all chapters and tracks in the card have display and icon fields initialized.
        """
        if not card.content or not card.content.chapters:
            return
        for ch in card.content.chapters:
            if not ch.display:
                ch.display = ChapterDisplay()
            if not hasattr(ch.display, 'icon16x16') or ch.display.icon16x16 is None:
                ch.display.icon16x16 = DEFAULT_MEDIA_ID
            if ch.tracks:
                for tr in ch.tracks:
                    if not tr.display:
                        tr.display = TrackDisplay()
                    if not hasattr(tr.display, 'icon16x16') or tr.display.icon16x16 is None:
                        tr.display.icon16x16 = DEFAULT_MEDIA_ID
        return card

    def get_myo_content(self):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        logger.debug(f"GET {self.MYO_URL}")
        response = self._cached_request("GET", self.MYO_URL, headers=headers)
        logger.debug(f"Content response: {response.status_code} {response.text}")
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and "cards" in data:
            cards = data["cards"]
        else:
            cards = data if isinstance(data, list) else [data]
        logger.debug(f"Parsed {len(cards)} cards from response")
        return [Card.model_validate(card) for card in cards]

    def get_card(self, card_id, save_version_if_missing: bool = True) -> Card:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        logger.debug(f"GET {self.CONTENT_URL}/{card_id}")
        response = self._cached_request("GET", f"{self.CONTENT_URL}/{card_id}", headers=headers)
        logger.debug(f"Content response: {response.status_code} {response.text}")
        response.raise_for_status()
        self.response_history.append(response)
        data = response.json()["card"]
        # If requested, save a local version snapshot when none exist for this card yet.
        # This helps provide a recovery point if the card is later deleted.
        if save_version_if_missing:
            try:
                # Determine the versions directory for this payload and check for any existing json versions.
                dir_path = self._version_path_for(data)
                has_any = False
                try:
                    for p in dir_path.iterdir():
                        if p.suffix == ".json":
                            has_any = True
                            break
                except Exception:
                    # If iteration fails, treat as no versions present so we attempt to save.
                    has_any = False
                if not has_any:
                    try:
                        self.save_version(data)
                    except Exception:
                        logger.debug("Failed to save local version after fetching card")
            except Exception:
                # Non-fatal — don't interrupt normal get_card flow if version saving fails.
                pass
        if self.debug:
            find_extra_fields(Card, data, warn_extra=True)
        return Card.model_validate(data)

    def create_or_update_content(self, card, return_card=False, add_update_at=True, create_version:bool=True):
        """
        Accepts a Card model instance and sends it to the API.

        Minimal requirement is title and content

        e.g. Card(title="My Card", content=CardContent(...))
        """
        if not isinstance(card, Card):
            logger.error("card must be a Card model instance")
            raise TypeError("card must be a Card model instance")

        if add_update_at:
            # Add/update the updatedAt field with the current UTC time in ISO 8601 format with milliseconds and 'Z'
            updated_at = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            card.updatedAt = updated_at

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        #payload = {"card": card.model_dump(exclude_none=True)}
        payload = card.model_dump(exclude_none=True)
        logger.debug(f"POST {self.CONTENT_URL} payload: {payload}")
        response = self._cached_request("POST", self.CONTENT_URL, headers=headers, json_data=payload)
        logger.debug(f"Create/Update response: {response.status_code} {response.text}")
        response.raise_for_status()
        # Persist a local version of the resulting card JSON (if present).
        if create_version:
            try:
                resp_json = response.json()
                card_json = resp_json.get("card") or resp_json
                self.save_version(card_json)
            except Exception:
                logger.debug("Failed to save local version after create/update")
        if return_card:
            return Card.model_validate(response.json()["card"])
        return response.json()

    def get_audio_upload_url(self, sha256: str, filename: Optional[str] = None):
        """
        Get a signed upload URL for an audio file.
        If the file already exists, uploadUrl will be null.
        See: https://yoto.dev/api/getanuploadurl/
        """
        url = "https://api.yotoplay.com/media/transcode/audio/uploadUrl"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        params = {"sha256": sha256}
        if filename:
            params["filename"] = filename
        logger.debug(f"GET {url} params={params}")
        response = httpx.get(url, headers=headers, params=params)
        logger.debug(f"Upload URL response: {response.status_code} {response.text}")
        response.raise_for_status()
        return response.json()


    from typing import Tuple
    def calculate_sha256(self, audio_path: str) -> Tuple[str, bytes]:
        import hashlib
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        return hashlib.sha256(audio_bytes).hexdigest(), audio_bytes


    async def upload_and_transcode_audio_async(
        self,
        audio_path: str,
        filename: Optional[str] = None,
        loudnorm: bool = False,
        poll_interval: float = 2,
        max_attempts: int = 60,
        show_progress: bool = True,
        progress: 'Progress' = None,
        upload_task_id: int | None = None,
        transcode_task_id: int | None = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ):
        """
        Async version: Handles hashing, upload URL, upload, and transcoding for an audio file.
        Returns transcoded audio info dict.
        Supports rich progress for upload and transcode phases.
        Accepts an optional progress_callback(msg, frac) for external UI updates.
        """
        logger.debug(f"Starting upload_and_transcode_audio_async for {audio_path} with filename={filename}")
        def _call_cb(msg: str | None = None):
            try:
                if callable(progress_callback):
                    progress_callback(msg or '', None)
            except Exception:
                pass

        sha256, audio_bytes = self.calculate_sha256(audio_path)
        logger.info(f"SHA256: {sha256}")
        _call_cb("Hash calculated")
        upload_resp = self.get_audio_upload_url(sha256, filename)
        upload = upload_resp.get("upload", upload_resp)
        audio_upload_url = upload.get("uploadUrl")
        upload_id = upload.get("uploadId")
        if not audio_upload_url:
            if upload.get("uploadId"):
                logger.info("File already exists on server, skipping upload.")
                if progress and upload_task_id is not None:
                    progress.update(upload_task_id, completed=100, description="Upload skipped (already exists)")
                _call_cb("Upload skipped (already exists)")
            else:
                logger.error("Failed to get upload URL.")
                if progress and upload_task_id is not None:
                    progress.update(upload_task_id, completed=100, description="Upload failed")
                _call_cb("Failed to get upload URL")
                raise Exception("Failed to get upload URL.")
        else:
            logger.info(f"Uploading audio to: {audio_upload_url}")
            if progress and upload_task_id is not None:
                progress.update(upload_task_id, description="Uploading audio...")
            _call_cb("Uploading audio...")

            async with httpx.AsyncClient() as client:
                put_resp = await client.put(audio_upload_url, content=audio_bytes, headers={"Content-Type": "audio/mpeg"}, timeout=300)
                if put_resp.status_code >= 400:
                    logger.error(f"Audio upload failed: {put_resp.text}")
                    if progress and upload_task_id is not None:
                        progress.update(upload_task_id, completed=100, description="Upload failed")
                    _call_cb("Audio upload failed")
                    raise Exception(f"Audio upload failed: {put_resp.text}")
                logger.info("Audio uploaded successfully.")
                if progress and upload_task_id is not None:
                    file_label = filename if filename else audio_path
                    progress.update(upload_task_id, completed=100, description=f"Upload complete: {file_label}")
            _call_cb("Upload complete")
        _call_cb("Transcoding...")
        transcoded_audio = await self.poll_for_transcoding_async(
            upload_id, loudnorm, poll_interval, max_attempts, show_progress,
            progress=progress, transcode_task_id=transcode_task_id
        )
        logger.debug(f"Transcoded audio info: {transcoded_audio}")
        _call_cb("Transcode complete")
        return transcoded_audio

    async def poll_for_transcoding_async(
        self,
        upload_id: str,
        loudnorm: bool = False, # This doesn't actually do anything here
        poll_interval: float = 2,
        max_attempts: int = 120,
        show_progress: bool = False,
        progress: 'Progress' = None,
        transcode_task_id: int | None = None,
    ):
        import httpx
        import asyncio
        transcode_url = f"https://api.yotoplay.com/media/upload/{upload_id}/transcoded?loudnorm={'true' if loudnorm else 'false'}"
        attempts = 0
        transcoded_audio = None
        data = None
        if progress and transcode_task_id is not None:
            progress.update(transcode_task_id, description="Transcoding audio...")
        async with httpx.AsyncClient() as client:
            while attempts < max_attempts:
                poll_resp = await client.get(transcode_url, headers={"Authorization": f"Bearer {self.access_token}"})
                logger.debug(f"Transcode poll response: {poll_resp.status_code} {poll_resp.text}")
                if poll_resp.status_code == 200:
                    data = poll_resp.json()
                    transcode = data.get("transcode", data)
                    if transcode.get("transcodedSha256"):
                        transcoded_audio = transcode
                        if progress and transcode_task_id is not None:
                            progress.update(transcode_task_id, completed=max_attempts, description="Transcode complete")
                        break
                await asyncio.sleep(poll_interval)
                attempts += 1
                if progress and transcode_task_id is not None:
                    progress.update(transcode_task_id, completed=attempts)
        if not transcoded_audio:
            logger.info(data)
            logger.error("Transcoding timed out.")
            if progress and transcode_task_id is not None:
                progress.update(transcode_task_id, completed=max_attempts, description="Transcode timed out")
            raise Exception("Transcoding timed out.")
        return transcoded_audio

    async def upload_and_transcode_many_async(
        self,
        media_files,
        filename_list=None,
        loudnorm=False,
        poll_interval=2,
        max_attempts=60,
        show_progress=True,
        max_concurrent_uploads: int = 4
    ):
        """
        Launch parallel async uploads and transcodes for a list of media files.
        Returns a list of transcoded audio info dicts (same order as input).
        Shows rich progress bars for each upload and transcode.
        Limits the number of concurrent uploads using a semaphore.
        """
        results = []
        console = Console()
        semaphore = asyncio.Semaphore(max_concurrent_uploads)
        async def sem_task(*args, **kwargs):
            async with semaphore:
                return await self.upload_and_transcode_audio_async(*args, **kwargs)
        tasks = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=False,
            console=console,
        ) as progress:
            upload_task_ids = []
            transcode_task_ids = []
            visible_limit = 8
            # Track which tasks are currently visible
            visible_upload_tasks = set()
            visible_transcode_tasks = set()

            def add_visible_task(label, total, task_type, idx):
                # Remove completed tasks from visible sets
                def cleanup_visible_tasks():
                    # Remove tasks that are no longer visible or completed
                    for tid in list(visible_upload_tasks):
                        t = progress.tasks[tid]
                        if t.finished or not t.visible:
                            visible_upload_tasks.remove(tid)
                    for tid in list(visible_transcode_tasks):
                        t = progress.tasks[tid]
                        if t.finished or not t.visible:
                            visible_transcode_tasks.remove(tid)

                cleanup_visible_tasks()
                if task_type == "upload":
                    if len(visible_upload_tasks) < visible_limit:
                        tid = progress.add_task(label, total=total)
                        visible_upload_tasks.add(tid)
                        return tid
                    else:
                        return progress.add_task(label, total=total, visible=False)
                elif task_type == "transcode":
                    if len(visible_transcode_tasks) < visible_limit:
                        tid = progress.add_task(label, total=total)
                        visible_transcode_tasks.add(tid)
                        return tid
                    else:
                        return progress.add_task(label, total=total, visible=False)
                else:
                    return progress.add_task(label, total=total)

            def make_task_visible(task_id, task_type):
                # Make a hidden task visible if there's a slot
                if task_type == "upload":
                    if not progress.tasks[task_id].visible and len(visible_upload_tasks) < visible_limit:
                        progress.update(task_id, visible=True)
                        visible_upload_tasks.add(task_id)
                elif task_type == "transcode":
                    if not progress.tasks[task_id].visible and len(visible_transcode_tasks) < visible_limit:
                        progress.update(task_id, visible=True)
                        visible_transcode_tasks.add(task_id)

            # Patch wrapped_task to make next hidden task visible when one finishes
            async def wrapped_task(idx=0, upload_task_id=None, transcode_task_id=None):
                result = await sem_task(
                    audio_path=str(media_files[idx]),
                    filename=filename_list[idx] if filename_list else None,
                    loudnorm=loudnorm,
                    poll_interval=poll_interval,
                    max_attempts=max_attempts,
                    show_progress=show_progress,
                    progress=progress,
                    upload_task_id=upload_task_id,
                    transcode_task_id=transcode_task_id
                )
                progress.update(overall_task_id, advance=1)
                # Hide completed upload/transcode tasks to keep UI clean
                progress.update(upload_task_id, visible=False)
                progress.update(transcode_task_id, visible=False)
                if upload_task_id in visible_upload_tasks:
                    visible_upload_tasks.remove(upload_task_id)
                if transcode_task_id in visible_transcode_tasks:
                    visible_transcode_tasks.remove(transcode_task_id)
                # Make next hidden upload/transcode task visible if slots available
                for tid in upload_task_ids:
                    make_task_visible(tid, "upload")
                for tid in transcode_task_ids:
                    make_task_visible(tid, "transcode")
                return result
            total_tasks = len(media_files)
            overall_task_id = progress.add_task("Overall Progress", total=total_tasks)
            # Only show up to 8 upload/transcode tasks at a time
            def add_visible_task(label, total):
                if len(progress.tasks) < visible_limit:
                    return progress.add_task(label, total=total)
                else:
                    # Add hidden task (not shown in UI)
                    return progress.add_task(label, total=total, visible=False)
            for idx, media_file in enumerate(media_files):
                fname = None
                if filename_list:
                    fname = filename_list[idx]
                upload_task_id = add_visible_task(f"Upload {fname or media_file}", 100)
                transcode_task_id = add_visible_task(f"Transcode {fname or media_file}", max_attempts)
                upload_task_ids.append(upload_task_id)
                transcode_task_ids.append(transcode_task_id)
                async def wrapped_task(idx=idx, upload_task_id=upload_task_id, transcode_task_id=transcode_task_id):
                    result = await sem_task(
                        audio_path=str(media_files[idx]),
                        filename=filename_list[idx] if filename_list else None,
                        loudnorm=loudnorm,
                        poll_interval=poll_interval,
                        max_attempts=max_attempts,
                        show_progress=show_progress,
                        progress=progress,
                        upload_task_id=upload_task_id,
                        transcode_task_id=transcode_task_id
                    )
                    progress.update(overall_task_id, advance=1)
                    # Hide completed upload/transcode tasks to keep UI clean
                    progress.update(upload_task_id, visible=False)
                    progress.update(transcode_task_id, visible=False)
                    # Remove the finished tasks from the visible sets so slots free up
                    if upload_task_id in visible_upload_tasks:
                        visible_upload_tasks.remove(upload_task_id)
                    if transcode_task_id in visible_transcode_tasks:
                        visible_transcode_tasks.remove(transcode_task_id)
                    # Try to make other hidden tasks visible now that slots freed
                    for tid in upload_task_ids:
                        make_task_visible(tid, "upload")
                    for tid in transcode_task_ids:
                        make_task_visible(tid, "transcode")
                    return result
                tasks.append(wrapped_task())
            results = await asyncio.gather(*tasks)
        return results

    async def upload_and_transcode_and_create_card_async(
        self,
        media_files,
        card_title: str,
        filename_list=None,
        loudnorm=False,
        poll_interval=2,
        max_attempts=60,
        show_progress=True,
        max_concurrent_uploads: int = 4,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        return_card: bool = True,
        single_chapter: bool = False,
    ):
        """
        Parallel upload & transcode for a list of media files, preserve input order,
        then create a single Card containing either:
            - one Chapter per file (default, in order)
            - OR, if single_chapter=True, all files as tracks of a single Chapter

        progress_callback: optional callable(message, frac) where frac is 0..1 overall progress.
        Returns the created card (model) if return_card True, otherwise the raw API response.
        """
        import asyncio

        total = len(media_files)
        if filename_list and len(filename_list) != total:
            filename_list = None

        semaphore = asyncio.Semaphore(max_concurrent_uploads)
        results = [None] * total
        errors = [None] * total

        async def worker(idx, path, fname):
            nonlocal results, errors
            try:
                if callable(progress_callback):
                    try:
                        progress_callback(f"Uploading {fname or path}", idx / total)
                    except Exception:
                        pass
                async with semaphore:
                    tr = await self.upload_and_transcode_audio_async(
                        audio_path=path,
                        filename=fname,
                        loudnorm=loudnorm,
                        poll_interval=poll_interval,
                        max_attempts=max_attempts,
                        show_progress=show_progress,
                    )
                results[idx] = tr
                if callable(progress_callback):
                    try:
                        progress_callback(f"Completed {fname or path}", (idx + 1) / total)
                    except Exception:
                        pass
            except Exception as e:
                errors[idx] = e
                if callable(progress_callback):
                    try:
                        progress_callback(f"Error {fname or path}: {e}", (idx + 1) / total)
                    except Exception:
                        pass

        tasks = [worker(i, str(media_files[i]), (filename_list[i] if filename_list else None)) for i in range(total)]
        await asyncio.gather(*tasks)

        # If any worker errored, raise the first error
        for err in errors:
            if err:
                raise err

        # Build card content preserving order
        if single_chapter:
            # All files as tracks of a single chapter
            tracks = []
            for i, tr in enumerate(results):
                # prefer filename_list for title if available
                track_details = None
                try:
                    if filename_list:
                        track_details = {'title': filename_list[i]}
                except Exception:
                    track_details = None
                track = self.get_track_from_transcoded_audio(tr, track_details=track_details)
                try:
                    track.key = f"{i+1:02}"
                except Exception:
                    pass
                tracks.append(track)
            chapter = Chapter(
                key="01",
                title=card_title,
                overlayLabel="1",
                tracks=tracks,
                display=ChapterDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
            )
            chapters = [chapter]
        else:
            # One chapter per file
            chapters = []
            for i, tr in enumerate(results):
                # prefer filename_list for chapter title if available
                chapter_details = None
                try:
                    if filename_list:
                        chapter_details = {'title': filename_list[i]}
                except Exception:
                    chapter_details = None
                ch = self.get_chapter_from_transcoded_audio(tr, chapter_details=chapter_details)
                try:
                    ch.key = f"{i+1:02}"
                    if hasattr(ch, 'tracks') and ch.tracks:
                        for j, t in enumerate(ch.tracks):
                            try:
                                t.key = f"{j+1:02}"
                            except Exception:
                                pass
                except Exception:
                    pass
                chapters.append(ch)

        card_content = CardContent(chapters=chapters)
        # Aggregate media metadata if possible
        total_duration = 0
        total_size = 0
        for tr in results:
            mi = tr.get('transcodedInfo', {}) if isinstance(tr, dict) else {}
            try:
                total_duration += mi.get('duration', 0) or 0
            except Exception:
                pass
            try:
                total_size += mi.get('fileSize', 0) or 0
            except Exception:
                pass
        card_media = CardMedia(duration=total_duration or None, fileSize=total_size or None)
        card_metadata = CardMetadata(media=card_media)
        card = Card(title=card_title, content=card_content, metadata=card_metadata)
        # Create card via API
        created = None
        if callable(progress_callback):
            try:
                progress_callback("Creating card on server...", 0.99)
            except Exception:
                pass
        created = self.create_or_update_content(card, return_card=return_card)
        if callable(progress_callback):
            try:
                progress_callback("Card creation complete", 1.0)
            except Exception:
                pass
        return created

    def upload_audio_file(self, audio_upload_url: str, audio_bytes: bytes, mime_type: str = "audio/mpeg"):
        headers = {"Content-Type": mime_type}
        put_resp = httpx.put(audio_upload_url, data=audio_bytes, headers=headers)
        if not put_resp.is_success:
            logger.error(f"Audio upload failed: {put_resp.text}")
            raise Exception(f"Audio upload failed: {put_resp.text}")
        logger.info("Audio uploaded successfully.")

    def poll_for_transcoding(
        self,
        upload_id: str,
        loudnorm: bool = False,
        poll_interval: float = 2,
        max_attempts: int = 120,
        show_progress: bool = False,
    ):
        transcode_url = f"https://api.yotoplay.com/media/upload/{upload_id}/transcoded?loudnorm={'true' if loudnorm else 'false'}"
        attempts = 0
        transcoded_audio = None
        data = None
        if show_progress:
            console = Console()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=console,
            ) as progress:
                task = progress.add_task("Transcoding audio...", total=max_attempts)
                while attempts < max_attempts:
                    poll_resp = httpx.get(transcode_url, headers={"Authorization": f"Bearer {self.access_token}"})
                    logger.debug(f"Transcode poll response: {poll_resp.status_code} {poll_resp.text}")
                    if poll_resp.is_success:
                        data = poll_resp.json()
                        transcode = data.get("transcode", data)
                        if transcode.get("transcodedSha256"):
                            transcoded_audio = transcode
                            break
                    time.sleep(poll_interval)
                    attempts += 1
                    progress.update(task, completed=attempts)
                if not transcoded_audio:
                    logger.info(data)
                    logger.error("Transcoding timed out.")
                    raise Exception("Transcoding timed out.")
        else:
            while attempts < max_attempts:
                poll_resp = httpx.get(transcode_url, headers={"Authorization": f"Bearer {self.access_token}"})
                if poll_resp.is_success:
                    data = poll_resp.json()
                    transcode = data.get("transcode", data)
                    if transcode.get("transcodedSha256"):
                        transcoded_audio = transcode
                        break
                time.sleep(poll_interval)
                attempts += 1
                logger.info(f"Transcoding progress: {int(100 * attempts / max_attempts)}%")
            if not transcoded_audio:
                logger.info(data)
                logger.error("Transcoding timed out.")
                raise Exception("Transcoding timed out.")
        return transcoded_audio

    def get_track_from_transcoded_audio(self, transcoded_audio, track_details: Optional[dict] = None) -> Optional[Track]:
        media_info = transcoded_audio.get("transcodedInfo", {})
        track_title = media_info.get("metadata", {}).get("title") or "Unknown Track"
        # Merge custom track details
        track_kwargs = dict(
            key="01",
            title=track_title,
            trackUrl=f"yoto:#{transcoded_audio['transcodedSha256']}",
            duration=media_info.get("duration"),
            fileSize=media_info.get("fileSize"),
            channels=media_info.get("channels"),
            format=media_info.get("format"),
            type="audio",
            overlayLabel="1",
            display=TrackDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
        )
        if track_details:
            track_kwargs.update(track_details)
        return Track(**track_kwargs)

    def get_chapter_from_transcoded_audio(self, transcoded_audio, track_details: Optional[dict] = None, chapter_details: Optional[dict] = None) -> Optional[Chapter]:
        media_info = transcoded_audio.get("transcodedInfo", {})
        # Use chapter_details['title'] if provided, else fallback to metadata title, else 'Unknown Chapter'
        chapter_title = None
        if chapter_details and "title" in chapter_details:
            chapter_title = chapter_details["title"]
        else:
            chapter_title = media_info.get("metadata", {}).get("title") or "Unknown Chapter"
        # Merge custom track details
        track_kwargs = dict(
            key="01",
            title=chapter_title,
            trackUrl=f"yoto:#{transcoded_audio['transcodedSha256']}",
            format=media_info.get("format", "mp3"),
            type="audio",
            duration=media_info.get("duration"),
            fileSize=media_info.get("fileSize"),
            channels=media_info.get("channels"),
            overlayLabel="1",
            display=TrackDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
        )
        if track_details:
            track_kwargs.update(track_details)
        track = Track(**track_kwargs)

        # Merge custom chapter details
        chapter_kwargs = dict(
            key="01",
            title=chapter_title,
            overlayLabel="1",
            tracks=[track],
            display=ChapterDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
        )
        if chapter_details:
            chapter_kwargs.update(chapter_details)
        # Ensure required fields
        if "title" not in chapter_kwargs:
            chapter_kwargs["title"] = chapter_title
        if "tracks" not in chapter_kwargs:
            chapter_kwargs["tracks"] = [track]
        chapter = Chapter(**chapter_kwargs)
        return chapter

    def create_card_from_transcoded_audio(self, card_title: str, transcoded_audio, track_details: Optional[dict] = None, chapter_details: Optional[dict] = None):
        media_info = transcoded_audio.get("transcodedInfo", {})
        chapter_title = media_info.get("metadata", {}).get("title") or card_title
        # Merge custom track details
        track_kwargs = dict(
            key="01",
            title=chapter_title,
            trackUrl=f"yoto:#{transcoded_audio['transcodedSha256']}",
            format=media_info.get("format", "mp3"),
            type="audio",
            duration=media_info.get("duration"),
            fileSize=media_info.get("fileSize"),
            channels=media_info.get("channels"),
            overlayLabel="1",
            display=TrackDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
        )
        if track_details:
            track_kwargs.update(track_details)
        track = Track(**track_kwargs)

        # Merge custom chapter details
        chapter_kwargs = dict(
            key="01",
            title=chapter_title,
            overlayLabel="1",
            tracks=[track],
            display=ChapterDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
        )
        if chapter_details:
            chapter_kwargs.update(chapter_details)
        # Ensure required fields
        if "title" not in chapter_kwargs:
            chapter_kwargs["title"] = chapter_title
        if "tracks" not in chapter_kwargs:
            chapter_kwargs["tracks"] = [track]
        chapter = Chapter(**chapter_kwargs)
        card_content = CardContent(chapters=[chapter])
        card_media = CardMedia(
            duration=media_info.get("duration"),
            fileSize=media_info.get("fileSize"),
        )
        card_metadata = CardMetadata(media=card_media)
        card = Card(title=card_title, content=card_content, metadata=card_metadata)
        logger.info(f"Creating card with content: {card.model_dump(exclude_none=True)}")
        try:
            card = self.create_or_update_content(card)
        except Exception as e:
            logger.error(f"Failed to create or update content: {e}")
            raise e
        logger.info("Card created successfully.")
        return card

    def upload_audio_to_card(
        self,
        audio_path: str,
        card_title: str,
        filename: Optional[str] = None,
        loudnorm: bool = False,
        poll_interval: float = 0.5,
        max_attempts: int = 30,
        track_details: Optional[dict] = None,
        chapter_details: Optional[dict] = None,
    ):
        """
        Uploads and transcodes audio, then creates a card from the transcoded audio.
        """
        transcoded_audio = self.upload_and_transcode_audio(
            audio_path=audio_path,
            filename=filename,
            loudnorm=loudnorm,
            poll_interval=poll_interval,
            max_attempts=max_attempts,
        )
        return self.create_card_from_transcoded_audio(card_title, transcoded_audio, track_details, chapter_details)

    def upload_audio_to_existing_card(
        self,
        audio_path: str,
        card_id: str,
        chapter_index: int = 0,
        filename: Optional[str] = None,
        loudnorm: bool = False,
        poll_interval: float = 0.5,
        max_attempts: int = 30,
        track_details: Optional[dict] = None,
        chapter_details: Optional[dict] = None,
    ):
        """
        Upload an audio file and add it as a track to an existing card.
        By default, adds to the first chapter. You can specify chapter_index and pass custom details.
        """
        # Fetch existing card
        card = self.get_card(card_id)
        media_info = None
        new_chapter = None

        file_path = Path(audio_path)

        # Transcode audio
        sha256, audio_bytes = self.calculate_sha256(audio_path)
        logger.info(f"SHA256: {sha256}")
        upload_resp = self.get_audio_upload_url(sha256, filename)
        upload = upload_resp.get("upload", upload_resp)
        audio_upload_url = upload.get("uploadUrl")
        upload_id = upload.get("uploadId")
        if not audio_upload_url:
            if upload.get("uploadId"):
                logger.info("File already exists on server, skipping upload.")
            else:
                logger.error("Failed to get upload URL.")
                raise Exception("Failed to get upload URL.")
        else:
            logger.info(f"Uploading audio to: {audio_upload_url}")
            self.upload_audio_file(audio_upload_url, audio_bytes)
        transcoded_audio = self.poll_for_transcoding(upload_id, loudnorm, poll_interval, max_attempts)
        media_info = transcoded_audio.get("transcodedInfo", {})

        # Determine next chapter key
        chapters = card.content.chapters if card.content and card.content.chapters else []
        next_chapter_number = len(chapters)

        # Prepare new chapter with the uploaded audio as a track
        track_kwargs = dict(
            key="01",
            title=media_info.get("metadata", {}).get("title") or (track_details.get("title") if track_details else file_path.stem),
            trackUrl=f"yoto:#{transcoded_audio['transcodedSha256']}",
            duration=media_info.get("duration"),
            fileSize=media_info.get("fileSize"),
            channels=media_info.get("channels"),
            format=media_info.get("format"),
            type="audio",
            overlayLabel=str(next_chapter_number),
            display=TrackDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
        )
        if track_details:
            track_kwargs.update(track_details)
        new_track = Track(**track_kwargs)

        chapter_kwargs = dict(
            key=f"{next_chapter_number:02}",
            title=new_track.title,
            overlayLabel=str(next_chapter_number),
            tracks=[new_track],
            display=ChapterDisplay(icon16x16="yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"),
            duration=media_info.get("duration"),
            fileSize=media_info.get("fileSize"),
        )
        if chapter_details:
            chapter_kwargs.update(chapter_details)
        # Ensure required fields
        if "title" not in chapter_kwargs:
            chapter_kwargs["title"] = new_track.title
        if "tracks" not in chapter_kwargs:
            chapter_kwargs["tracks"] = [new_track]
        new_chapter = Chapter(**chapter_kwargs)

        # Add new chapter to card
        if not card.content:
            card.content = type(card.content)()
        if not card.content.chapters:
            card.content.chapters = []
        card.content.chapters.append(new_chapter)

        logger.debug(card.model_dump_json(exclude_none=True))
        logger.info(f"Updating card {card_id} with new chapter.")
        return self.create_or_update_content(card)

    def delete_content(self, content_id: str):
        """
        Delete a piece of content (MYO card) by contentId.
        Returns the API response (status or error).
        """
        url = f"https://api.yotoplay.com/content/{content_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        logger.debug(f"DELETE {url}")
        response = self._cached_request("DELETE", url, headers=headers)
        logger.debug(f"Delete response: {response.status_code} {response.text}")
        if response.status_code == 404:
            logger.error("Content not found or not owned by user.")
        response.raise_for_status()
        return response.json() if response.text else {"status": response.status_code}

    def update_card(self, card: Card, return_card_model=True):
        """
        Update a card by creating a new card and deleting the old one.



        """
        return self.create_or_update_content(card, return_card=return_card_model)

    def upload_and_transcode_audio(
        self,
        audio_path: str,
        filename: Optional[str] = None,
        loudnorm: bool = False,
        poll_interval: float = 2,
        max_attempts: int = 60,
        show_progress: bool = True
    ):
        """
        Handles hashing, upload URL, upload, and transcoding for an audio file.
        Returns transcoded audio info dict.
        """
        sha256, audio_bytes = self.calculate_sha256(audio_path)
        logger.info(f"SHA256: {sha256}")
        upload_resp = self.get_audio_upload_url(sha256, filename)
        upload = upload_resp.get("upload", upload_resp)
        audio_upload_url = upload.get("uploadUrl")
        upload_id = upload.get("uploadId")
        if not audio_upload_url:
            if upload.get("uploadId"):
                logger.info("File already exists on server, skipping upload.")
            else:
                logger.error("Failed to get upload URL.")
                raise Exception("Failed to get upload URL.")
        else:
            logger.info(f"Uploading audio to: {audio_upload_url}")
            self.upload_audio_file(audio_upload_url, audio_bytes)
        transcoded_audio = self.poll_for_transcoding(upload_id, loudnorm, poll_interval, max_attempts, show_progress)
        return transcoded_audio

    def refresh_public_and_user_icons(self, show_in_console: bool = False, refresh_cache: bool = True):
        """
        Fetches and caches both public and user icons, optionally displaying them in the console.
        """
        logger.debug("Refreshing public and user icons...")
        self.get_public_icons(show_in_console=show_in_console, refresh_cache=refresh_cache)
        self.get_user_icons(show_in_console=show_in_console, refresh_cache=refresh_cache)


    def get_public_icons(self, show_in_console: bool = True, refresh_cache: bool = False):
        """
        Fetches public 16x16 icons, downloads and caches them, and displays pixel art in the console.
        Shows Rich progress bars for downloads and rendering.
        """
        url = f"{self.SERVER_URL}/media/displayIcons/user/yoto"
        cache_dir = self.OFFICIAL_ICON_CACHE_DIR
        cache_dir.mkdir(exist_ok=True)
        logger.debug(f"Using icon cache dir: {cache_dir}")
        metadata_path = cache_dir / "icon_metadata.json"
        icons = None
        # Use cache if available and not refreshing
        if metadata_path.exists() and not refresh_cache:
            try:
                with metadata_path.open("r") as f:
                    icons = json.load(f)
            except Exception:
                icons = None
        if icons is None:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            icons = resp.json().get("displayIcons", [])
        if show_in_console:
            table = Table(title="Yoto Public 16x16 Icons", show_lines=True)
            table.add_column("Title", style="bold magenta")
            table.add_column("Tags", style="green")
            table.add_column("displayIconId", style="cyan")
            table.add_column("Pixel Art", style="white")
            # Download/cache images with progress. Use a ThreadPoolExecutor to
            # download multiple icons concurrently which considerably speeds up
            # the I/O-bound work compared to a sequential loop.
            import concurrent.futures

            def _download_icon(icon_item):
                try:
                    url = icon_item.get("url")
                    if not url:
                        return icon_item
                    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                    ext = Path(url).suffix or ".png"
                    cache_path = cache_dir / f"{url_hash}{ext}"
                    icon_item["cache_path"] = str(cache_path)
                    if not cache_path.exists() or refresh_cache:
                        try:
                            resp = httpx.get(url)
                            resp.raise_for_status()
                            cache_path.write_bytes(resp.content)
                        except Exception as e:
                            icon_item["cache_error"] = str(e)
                except Exception as e:
                    try:
                        icon_item["cache_error"] = str(e)
                    except Exception:
                        pass
                return icon_item

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=Console(),
            ) as progress:
                download_task = progress.add_task("Downloading & caching images...", total=len(icons))
                max_workers = min(8, max(1, len(icons)))
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futures = {ex.submit(_download_icon, icon): icon for icon in icons}
                    for fut in concurrent.futures.as_completed(futures):
                        icon = futures[fut]
                        try:
                            fut.result()
                        except Exception as e:
                            try:
                                icon["cache_error"] = str(e)
                            except Exception:
                                pass
                        progress.update(download_task, advance=1)
            # After downloads finish, write the metadata back including any cache_path entries
            try:
                with metadata_path.open("w") as f:
                    json.dump(icons, f, indent=2)
            except Exception:
                pass
            # Render pixel art with progress
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=Console(),
            ) as progress:
                render_task = progress.add_task("Rendering pixel art...", total=len(icons))
                for icon in icons:
                    tags = ", ".join(icon.get("publicTags", []))
                    display_icon_id = str(icon.get("displayIconId", ""))
                    cache_path = Path(icon.get("cache_path", ""))
                    if cache_path.exists():
                        pixel_art = render_icon(cache_path)
                    elif icon.get("cache_error"):
                        pixel_art = f"[red]Download error: {icon['cache_error']}[/red]"
                    else:
                        pixel_art = "[red]No image[/red]"
                    table.add_row(icon.get("title", ""), tags, display_icon_id, pixel_art)
                    progress.update(render_task, advance=1)
            rprint(table)
        else:
            # Non-console mode: download concurrently but without rich progress
            import concurrent.futures

            def _download_icon_noprint(icon_item):
                try:
                    url = icon_item.get("url")
                    if not url:
                        return icon_item
                    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                    ext = Path(url).suffix or ".png"
                    cache_path = cache_dir / f"{url_hash}{ext}"
                    icon_item["cache_path"] = str(cache_path)
                    if not cache_path.exists() or refresh_cache:
                        try:
                            resp = httpx.get(url)
                            resp.raise_for_status()
                            cache_path.write_bytes(resp.content)
                        except Exception as e:
                            icon_item["cache_error"] = str(e)
                except Exception as e:
                    try:
                        icon_item["cache_error"] = str(e)
                    except Exception:
                        pass
                return icon_item

            max_workers = min(8, max(1, len(icons)))
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
                list(ex.map(_download_icon_noprint, icons))
        # Persist metadata including computed cache_path values
        try:
            with metadata_path.open("w") as f:
                json.dump(icons, f, indent=2)
        except Exception:
            pass

        return icons

    def get_user_icons(self, show_in_console: bool = True, refresh_cache: bool = False):
        """
        Fetches user's custom 16x16 icons, downloads and caches them, and displays pixel art in the console.
        Shows Rich progress bars for downloads and rendering.
        """
        url = f"{self.SERVER_URL}/media/displayIcons/user/me"
        cache_dir = self.OFFICIAL_ICON_CACHE_DIR
        cache_dir.mkdir(exist_ok=True)
        logger.debug(f"Using icon cache dir: {cache_dir}")
        metadata_path = cache_dir / "user_icon_metadata.json"
        icons = None
        # Use cache if available and not refreshing
        if metadata_path.exists() and not refresh_cache:
            try:
                with metadata_path.open("r") as f:
                    icons = json.load(f)
            except Exception:
                icons = None
        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = httpx.get(url, headers=headers)
        resp.raise_for_status()
        user_icons = resp.json().get("displayIcons", [])
        # Merge user_icons into icons, avoiding duplicates by displayIconId
        existing_ids = {icon.get("displayIconId") for icon in icons} if icons else set()
        new_icons = [icon for icon in user_icons if icon.get("displayIconId") not in existing_ids]
        icons = (icons if icons else []) + new_icons

        if show_in_console:
            table = Table(title="Yoto User 16x16 Icons", show_lines=True)
            table.add_column("Title", style="bold magenta")
            table.add_column("displayIconId", style="cyan")
            table.add_column("Pixel Art", style="white")
            # Download/cache images with progress
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=Console(),
            ) as progress:
                download_task = progress.add_task("Downloading & caching images...", total=len(icons))
                for icon in icons:
                    url_hash = hashlib.sha256(icon["url"].encode()).hexdigest()[:16]
                    ext = Path(icon["url"]).suffix or ".png"
                    cache_path = cache_dir / f"{url_hash}{ext}"
                    icon["cache_path"] = str(cache_path)
                    if not cache_path.exists() or refresh_cache:
                        try:
                            img_resp = httpx.get(icon["url"])
                            img_resp.raise_for_status()
                            cache_path.write_bytes(img_resp.content)
                        except Exception as e:
                            icon["cache_error"] = str(e)
                    progress.update(download_task, advance=1)
            # After downloads complete, persist the merged metadata including cache_path fields
            try:
                with metadata_path.open("w") as f:
                    json.dump(icons, f, indent=2)
            except Exception:
                pass
            # Render pixel art with progress
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=Console(),
            ) as progress:
                render_task = progress.add_task("Rendering pixel art...", total=len(icons))
                for icon in icons:
                    display_icon_id = str(icon.get("displayIconId", ""))
                    cache_path = Path(icon.get("cache_path", ""))
                    if cache_path.exists():
                        pixel_art = render_icon(cache_path)
                    elif icon.get("cache_error"):
                        pixel_art = f"[red]Download error: {icon['cache_error']}[/red]"
                    else:
                        pixel_art = "[red]No image[/red]"
                    table.add_row(icon.get("title", ""), display_icon_id, pixel_art)
                    progress.update(render_task, advance=1)
            rprint(table)
        else:
            for icon in icons:
                url_hash = hashlib.sha256(icon["url"].encode()).hexdigest()[:16]
                ext = Path(icon["url"]).suffix or ".png"
                cache_path = cache_dir / f"{url_hash}{ext}"
                icon["cache_path"] = str(cache_path)
                if not cache_path.exists() or refresh_cache:
                    try:
                        img_resp = httpx.get(icon["url"])
                        img_resp.raise_for_status()
                        cache_path.write_bytes(img_resp.content)
                    except Exception as e:
                        icon["cache_error"] = str(e)

        # Persist metadata including computed cache_path values
        try:
            with metadata_path.open("w") as f:
                json.dump(icons, f, indent=2)
        except Exception:
            pass
                    
        return icons

    def search_cached_icons(self, query: str, fields: Optional[list] = None, show_in_console: bool = True, include_yotoicons: bool = True, include_authors: bool = False):
        """
        Search the cached icon metadata for matches in specified fields.
        By default, includes icons from both .yoto_icon_cache and .yotoicons_cache.
        Displays results in a unified Rich table, indicating the source.
        Returns a list of matching icon dicts.
        """
        # Search Yoto official icons
        yoto_cache_dir = self.OFFICIAL_ICON_CACHE_DIR
        yoto_metadata_path = yoto_cache_dir / "icon_metadata.json"
        if not yoto_metadata_path.exists():
            self.get_public_icons(show_in_console=True, refresh_cache=True)
        yoto_fields = ["title", "publicTags"] if fields is None else fields
        yoto_results = []
        if yoto_metadata_path.exists():
            try:
                with yoto_metadata_path.open("r") as f:
                    icons = json.load(f)
                query_lower = query.lower()
                for icon in icons:
                    for field in yoto_fields:
                        value = icon.get(field)
                        if isinstance(value, list):
                            if any(query_lower in str(v).lower() for v in value):
                                yoto_results.append(icon)
                                break
                        elif isinstance(value, str):
                            if query_lower in value.lower():
                                yoto_results.append(icon)
                                break
            except Exception:
                pass
        # Search YotoIcons icons
        yotoicons_results = []
        if include_yotoicons:
            self.search_yotoicons(query, show_in_console=True)
            yotoicons_cache_dir = self.YOTOICONS_CACHE_DIR
            global_metadata_path = yotoicons_cache_dir / "yotoicons_global_metadata.json"
            yotoicons_fields = ["category", "tags", "id"]
            if include_authors:
                yotoicons_fields.append("author")
            if global_metadata_path.exists():
                try:
                    with global_metadata_path.open("r") as f:
                        icons = json.load(f)
                    query_lower = query.lower()
                    for icon in icons:
                        for field in yotoicons_fields:
                            value = icon.get(field)
                            if isinstance(value, list):
                                if any(query_lower in str(v).lower() for v in value):
                                    yotoicons_results.append(icon)
                                    break
                            elif isinstance(value, str):
                                if query_lower in value.lower():
                                    yotoicons_results.append(icon)
                                    break
                except Exception as e:
                    logger.error("Error searching YotoIcons metadata")
                    raise e
            # Also search legacy per-tag metadata files
            for meta_file in yotoicons_cache_dir.glob("*_metadata.json"):
                if meta_file == global_metadata_path:
                    continue
                try:
                    with meta_file.open("r") as f:
                        icons = json.load(f)
                    query_lower = query.lower()
                    for icon in icons:
                        for field in yotoicons_fields:
                            value = icon.get(field)
                            if isinstance(value, list):
                                if any(query_lower in str(v).lower() for v in value):
                                    yotoicons_results.append(icon)
                                    break
                            elif isinstance(value, str):
                                if query_lower in value.lower():
                                    yotoicons_results.append(icon)
                                    break
                except Exception:
                    pass
        # Display results
        if show_in_console:
            table = Table(title="Search Results: Yoto & YotoIcons 16x16 Icons", show_lines=True)
            table.add_column("Source", style="bold blue")
            table.add_column("Title/Category", style="bold magenta")
            table.add_column("Tags", style="green")
            table.add_column("ID", style="cyan")
            table.add_column("Pixel Art", style="white")
            # Yoto official icons
            for icon in yoto_results:
                tags = ", ".join(icon.get("publicTags", []))
                display_icon_id = str(icon.get("displayIconId", ""))
                url_hash = hashlib.sha256(icon["url"].encode()).hexdigest()[:16]
                ext = Path(icon["url"]).suffix or ".png"
                cache_path = yoto_cache_dir / f"{url_hash}{ext}"
                pixel_art = render_icon(cache_path) if cache_path.exists() else "[red]Download error[/red]"
                table.add_row("Yoto", icon.get("title", ""), tags, display_icon_id, pixel_art)
            # YotoIcons icons
            for icon in yotoicons_results:
                tags = ", ".join(icon.get("tags", []))
                display_icon_id = str(icon.get("id", ""))
                # Cache path by hash of img_url
                if "img_url" in icon:
                    url_hash = hashlib.sha256(icon["img_url"].encode()).hexdigest()[:16]
                    ext = Path(icon["img_url"]).suffix or ".png"
                    cache_path = yotoicons_cache_dir / f"{url_hash}{ext}"
                elif "cache_path" in icon:
                    cache_path = Path(icon["cache_path"])
                else:
                    cache_path = None
                pixel_art = render_icon(cache_path) if cache_path and cache_path.exists() else "[red]Download error[/red]"
                table.add_row("YotoIcons", icon.get("category", ""), tags, display_icon_id, pixel_art)
            rprint(table)
        return yoto_results + yotoicons_results

    def search_yotoicons(self, tag: str, show_in_console: bool = True, limit: int = 20, refresh_cache: bool = False, return_new_only: bool = False):
        """
        Search and retrieve icons from yotoicons.com by tag (scrapes HTML, no API).
        Downloads and caches 16x16 pixel art images and metadata.
        Caches per-tag results for 1 day, unless refresh_cache is True.
        Always updates global cache with new icons, avoiding duplicates.
        Displays pixel art in the console, similar to get_public_icons.
        """
        cache_dir = self.YOTOICONS_CACHE_DIR
        cache_dir.mkdir(exist_ok=True)
        global_metadata_path = cache_dir / "yotoicons_global_metadata.json"
        tag_metadata_path = cache_dir / f"{tag}_metadata.json"
        cache_expiry_seconds = 86400  # 1 day
        icons = None
        new_icons = []
        console = Console()
        # Try per-tag cache first
        logger.debug(f"[YotoAPI] Checking tag cache: {tag_metadata_path}")
        if tag_metadata_path.exists() and not refresh_cache:
            try:
                mtime = tag_metadata_path.stat().st_mtime
                if (time.time() - mtime) < cache_expiry_seconds:
                    with tag_metadata_path.open("r") as f:
                        icons = json.load(f)
            except Exception:
                icons = None
            # Fallback to global cache if tag cache not available
            if icons is None and global_metadata_path.exists() and not refresh_cache:
                try:
                    with global_metadata_path.open("r") as f:
                        icons = [icon for icon in json.load(f) if tag in icon.get("tags", [])]
                except Exception:
                    icons = None
            logger.debug(f"Loaded {len(icons) if icons else 0} icons from cache for tag '{tag}'")
        # Scrape if no valid cache
        if icons is None:
            base_url = "https://www.yotoicons.com/icons?category=&tag="
            url = f"{base_url}{tag}"
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=console,
            ) as progress:
                scrape_task = progress.add_task("Scraping icons...", total=limit)
                resp = httpx.get(url)
                if resp.status_code != 200:
                    raise RuntimeError(f"Failed to fetch yotoicons: {resp.status_code}")
                soup = BeautifulSoup(resp.text, "html.parser")
                icons = []
                for div in soup.select("section#search_results div.icon"):
                    onclick = div.get("onclick", "")
                    m = re.search(r"populate_icon_modal\('(\d+)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'(\d+)'\)", onclick)
                    if not m:
                        continue
                    icon_id, category, tag1, tag2, author, downloads = m.groups()
                    img_tag = div.select_one(".icon_background img")
                    img_url = "https://www.yotoicons.com" + img_tag.get("src") if img_tag else None
                    icons.append({
                        "id": icon_id,
                        "category": category,
                        "tags": [tag1, tag2],
                        "author": author,
                        "downloads": downloads,
                        "img_url": img_url
                    })
                    progress.update(scrape_task, advance=1)
                    if len(icons) >= limit:
                        break
                # Save per-tag cache
                with tag_metadata_path.open("w") as f:
                    json.dump(icons, f, indent=2)
                # Merge with existing global cache if present
                if global_metadata_path.exists():
                    try:
                        existing_icons = json.load(global_metadata_path.open("r"))
                        # Merge: keep existing, add new, avoid duplicates by 'id'
                        existing_ids = {icon.get("id") for icon in existing_icons}
                        new_icons = [icon for icon in icons if icon.get("id") not in existing_ids]
                        icons = existing_icons + new_icons
                    except Exception:
                        pass
                # Save updated global cache
                with global_metadata_path.open("w") as f:
                    json.dump(icons, f, indent=2)
        # Download/cache images with progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
            console=console,
        ) as progress:
            download_task = progress.add_task("Downloading & caching images...", total=len(icons))
            for icon in icons:
                if not icon.get("img_url"):
                    progress.update(download_task, advance=1)
                    continue
                url_hash = hashlib.sha256(icon["img_url"].encode()).hexdigest()[:16]
                ext = Path(icon["img_url"]).suffix or ".png"
                cache_path = cache_dir / f"{url_hash}{ext}"
                icon["cache_path"] = str(cache_path)
                if refresh_cache or not cache_path.exists():
                    try:
                        img_resp = httpx.get(icon["img_url"])
                        img_resp.raise_for_status()
                        img_bytes = img_resp.content
                        # Resize to 16x16 if needed
                        try:
                            img = Image.open(io.BytesIO(img_bytes))
                            if img.size != (16, 16):
                                img = img.resize((16, 16), Image.Resampling.NEAREST)
                            img.save(cache_path)
                        except Exception as e:
                            # If Pillow fails, just save the raw bytes
                            cache_path.write_bytes(img_bytes)
                    except Exception as e:
                        icon["cache_error"] = str(e)
                progress.update(download_task, advance=1)
        if show_in_console:
            table = Table(title=f"YotoIcons Results for '{tag}'", show_lines=True)
            table.add_column("ID", style="cyan")
            table.add_column("Category", style="magenta")
            table.add_column("Tags", style="green")
            table.add_column("Author", style="yellow")
            table.add_column("Downloads", style="white")
            table.add_column("Pixel Art", style="white")
            # Progress bar for rendering pixel art
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
                console=console,
            ) as progress:
                render_task = progress.add_task("Rendering pixel art...", total=len(icons))
                for icon in icons:
                    tags = ", ".join([t for t in icon["tags"] if t])
                    pixel_art = ""
                    cache_path = icon.get("cache_path")
                    img_url = icon.get("img_url")
                    if cache_path and Path(cache_path).exists():
                        art = render_icon(cache_path)
                        pixel_art = f"{art}"
                    elif icon.get("cache_error"):
                        pixel_art = f"[red]Download error: {icon['cache_error']}[/red]"
                    else:
                        pixel_art = "[red]No image[/red]"
                    table.add_row(icon["id"], icon["category"], tags, icon["author"], icon["downloads"], pixel_art)
                    progress.update(render_task, advance=1)
            rprint(table)
        if return_new_only:
            return new_icons
        return icons


    def find_best_icons_for_text(self, text: str, include_yotoicons: bool = True, top_n: int = 5, show_in_console: bool = False, extra_tags: Optional[list] = None, max_searches: int = 3):
        """
        Given a text input (album/song/chapter title), search cached icons and return a list of the most appropriate icon dicts.
        Uses fuzzy substring matching and simple scoring.
        Returns a list of up to top_n icons sorted by score (empty list if no match).
        Now supports making multiple calls to search_yotoicons with extra tags for broader search.
        """
        logger.info(f"Finding best icons for text: {text}")
        logger.info(f"Include YotoIcons: {include_yotoicons}, Top N: {top_n}, Show in console: {show_in_console}, Extra tags: {extra_tags}, Max searches: {max_searches}")
        # Simple stopword list for English
        STOPWORDS = set([
            "the", "and", "a", "an", "of", "in", "on", "at", "to", "for", "by", "with", "is", "it", "as", "from", "that", "this", "be", "are", "was", "were", "or", "but", "not", "so", "if", "then", "than", "too", "very", "can", "will", "just", "do", "does", "did", "has", "have", "had", "you", "your", "my", "our", "their", "his", "her", "its", "episode", "chapter"
        ])
        query = text.strip().lower()
        icons = []
        # Yoto official
        yoto_cache_dir = self.OFFICIAL_ICON_CACHE_DIR
        yoto_metadata_path = yoto_cache_dir / "icon_metadata.json"
        if yoto_metadata_path.exists():
            try:
                with yoto_metadata_path.open("r") as f:
                    icons += json.load(f)
            except Exception:
                pass
        # YotoIcons global cache
        if include_yotoicons:
            yotoicons_cache_dir = self.YOTOICONS_CACHE_DIR
            global_metadata_path = yotoicons_cache_dir / "yotoicons_global_metadata.json"
            if global_metadata_path.exists():
                try:
                    with global_metadata_path.open("r") as f:
                        icons += json.load(f)
                except Exception:
                    pass
            # Make additional calls to search_yotoicons for extra tags
            tag_queries = []
            if extra_tags:
                tag_queries = [t for t in extra_tags if t and t != text]
            else:
                # Use nltk for keyword extraction
                try:
                    tokens = word_tokenize(text.lower())
                    stop_words = set(STOPWORDS) | set(nltk_stopwords.words('english'))
                    filtered = [w for w in tokens if w.isalpha() and w not in stop_words and len(w) > 2]
                    # Sort by length (longer first), then uniqueness
                    filtered = sorted(set(filtered), key=lambda w: (-len(w), w))
                    tag_queries = filtered[:max_searches]
                    logger.debug(f"[YotoAPI] Extracted keywords for tag search: {tag_queries}")
                except Exception as e:
                    logger.error("[YotoAPI] Error extracting keywords")
                    logger.error(e)
                    tag_queries = []
            # Limit number of extra searches
            tag_queries = tag_queries[:max_searches]
            logger.debug(f"[YotoAPI] Tag queries for search: {tag_queries}")
            for tag in tag_queries:
                try:
                    new_icons = self.search_yotoicons(tag, show_in_console=False)
                    logger.debug(f"[YotoAPI] Found {len(new_icons)} new icons for tag '{tag}'")
                    # Deduplicate by id
                    existing_ids = {icon.get("id") for icon in icons if "id" in icon}
                    icons += [icon for icon in new_icons if icon.get("id") not in existing_ids]
                except Exception as e:
                    logger.error(f"[YotoAPI] Error searching YotoIcons for tag '{tag}'")
                    logger.error(e)
        # Scoring function: higher score for closer match
        def score_icon(icon):
            fields = [icon.get("title", ""), icon.get("category", ""), icon.get("id", ""), icon.get("displayIconId", ""), " ".join(icon.get("tags", [])), " ".join(icon.get("publicTags", []))]
            best = 0.0
            for field in fields:
                if not field:
                    continue
                field_str = str(field).lower()
                # Exact match
                if field_str == query:
                    return 2.0
                # Substring match
                if query in field_str:
                    best = max(best, 1.5)
                # Rapidfuzz fuzzy match
                ratio = fuzz.ratio(query, field_str) / 100.0
                best = max(best, ratio)
            return best
        # Score all icons
        scored_icons = [(score_icon(icon), icon) for icon in icons]
        # Sort by score descending
        scored_icons.sort(reverse=True, key=lambda x: x[0])
        # Filter out zero-score matches
        best_icons = [icon for score, icon in scored_icons if score > 0.0][:top_n]
        logger.info(f"Found {len(best_icons)} matching icons")
        logger.debug(f"Best icons: {best_icons}")
        if show_in_console:
            if best_icons:
                for icon in best_icons:
                    cache_path = None
                    # Try to find cache path for Yoto or YotoIcons
                    if "url" in icon:
                        url_hash = hashlib.sha256(icon["url"].encode()).hexdigest()[:16]
                        ext = Path(icon["url"]).suffix or ".png"
                        cache_path = self.OFFICIAL_ICON_CACHE_DIR / f"{url_hash}{ext}"
                    elif "img_url" in icon:
                        url_hash = hashlib.sha256(icon["img_url"].encode()).hexdigest()[:16]
                        ext = Path(icon["img_url"]).suffix or ".png"
                        cache_path = self.YOTOICONS_CACHE_DIR / f"{url_hash}{ext}"
                    elif "cache_path" in icon:
                        cache_path = Path(icon["cache_path"])
                    pixel_art = render_icon(cache_path) if cache_path and cache_path.exists() else "[red]No image[/red]"
                    rprint(f"[bold green]Matching icon:[/bold green] {icon}")
                    rprint(pixel_art)
            else:
                rprint("[bold red]No matching icon found.[/bold red]")
        return best_icons

    def upload_custom_icon(self, icon_path: str, filename: Optional[str] = None, auto_convert: bool = True, yotoicons_id: str | None=None) -> dict:
        """
        Upload a custom icon to the official Yoto API and return the displayIcon metadata.
        Caches the result using SHA256 of the icon file.
        """
        # Compute SHA256 of the icon file
        with open(icon_path, "rb") as f:
            icon_bytes = f.read()
        sha256 = hashlib.sha256(icon_bytes).hexdigest()
        cache = self._load_icon_upload_cache()
        if sha256 in cache:
            logger.info(f"Icon already uploaded, returning cached mediaId: {cache[sha256].get('mediaId')}")
            return cache[sha256]
        url = f"{self.SERVER_URL}/media/displayIcons/user/me/upload"
        params = {
            "autoConvert": str(auto_convert).lower(),
        }
        if filename:
            params["filename"] = filename
        # Detect MIME type from file extension
        ext = Path(icon_path).suffix.lower()
        if ext == ".png":
            mime_type = "image/png"
        elif ext == ".jpg" or ext == ".jpeg":
            mime_type = "image/jpeg"
        elif ext == ".svg":
            mime_type = "image/svg+xml"
        elif ext == ".gif":
            mime_type = "image/gif"
        else:
            mime_type = "application/octet-stream"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": mime_type,
        }
        response = httpx.post(url, headers=headers, params=params, data=icon_bytes)
        try:
            response.raise_for_status()
        except httpx.HTTPError:
            logger.error(f"Icon upload failed: {response.text}")
            raise
        result = response.json().get("displayIcon", response.json())
        if yotoicons_id:
            result["yotoicons_id"] = yotoicons_id
        cache[sha256] = result
        self._save_icon_upload_cache(cache)

        if result.get("url"):
            self.save_icon_image_to_yoto_icon_cache(icon_path, icon_bytes, hashlib.sha256(result.get("url").encode()).hexdigest())

        # Save the icon file into yoto_icon_cache for local reference
        logger.info(f"Icon uploaded and cached with mediaId: {result.get('mediaId')}")
        return result

    def upload_cover_image(
        self,
        image_path: Optional[str] = None,
        imageUrl: Optional[str] = None,
        autoconvert: bool = True,
        coverType: Optional[str] = None,
        filename: Optional[str] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> dict:
        """
        Upload a cover image for the current user.

        Supports either a direct file upload (provide `image_path`) or a URL-based upload (provide `imageUrl`).

        Parameters:
            image_path: Local filesystem path to an image file to upload.
            imageUrl: Remote image URL to fetch and upload server-side.
            autoconvert: Whether the server should auto-convert/resize the image (default True).
            coverType: Optional cover type name (e.g. 'default', 'myo', 'music', 'podcast', ...).
            filename: Optional filename to send to the server.

        Returns: dict containing `coverImage` metadata (mediaId, mediaUrl) on success.

        Raises httpx.HTTPError on non-2xx responses.
        """
        url = f"{self.SERVER_URL}/media/coverImage/user/me/upload"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        params = {}
        if imageUrl:
            params["imageUrl"] = imageUrl
        params["autoconvert"] = str(bool(autoconvert)).lower()
        if coverType:
            params["coverType"] = coverType
        if filename:
            params["filename"] = filename

        # If uploading a local file, stream the bytes as the request body with an appropriate mime-type
        data = None
        if image_path:
            p = Path(image_path)
            if not p.exists():
                raise FileNotFoundError(f"Image file not found: {image_path}")
            with p.open("rb") as f:
                data = f.read()
            # Guess mime type
            import mimetypes
            mime, _ = mimetypes.guess_type(str(p))
            if not mime:
                # default to png
                mime = "image/png"
            headers["Content-Type"] = mime

        # Require either file body or imageUrl
        if data is None and not imageUrl:
            raise ValueError("Either image_path or imageUrl must be provided")

        logger.debug(f"Uploading cover image to {url} params={params} (file={'yes' if data is not None else 'no'})")

        def _call_cb(msg: str | None = None, frac: float | None = None):
            try:
                if callable(progress_callback):
                    progress_callback(msg or '', frac if frac is not None else 0.0)
            except Exception:
                pass

        _call_cb('Uploading cover...', 0.0)
        if data is not None:
            resp = httpx.post(url, headers=headers, params=params, data=data)
        else:
            resp = httpx.post(url, headers=headers, params=params)

        logger.debug(f"Cover image upload response: {resp.status_code} {getattr(resp, 'text', '')[:200]}")
        resp.raise_for_status()
        try:
            body = resp.json()
        except Exception:
            # Some endpoints may return binary; treat as error unless JSON present
            raise

        # Prefer top-level 'coverImage' key
        cover = body.get("coverImage") or body

        # Cache uploaded image bytes locally when we uploaded from a file and server returned a mediaUrl
        try:
            if data is not None and isinstance(cover, dict) and cover.get("mediaUrl"):
                url_hash = hashlib.sha256(cover.get("mediaUrl").encode()).hexdigest()
                # Save original bytes into official cache for quick local access
                try:
                    self.save_icon_image_to_yoto_icon_cache(image_path, data, url_hash)
                except Exception:
                    pass
        except Exception:
            pass

        _call_cb('Cover upload complete', 1.0)
        return cover

    def save_icon_image_to_yoto_icon_cache(self, icon_path: str, icon_bytes: bytes, sha256: str):
        icons_cache_dir = self.OFFICIAL_ICON_CACHE_DIR
        ext = Path(icon_path).suffix or ".png"
        cache_file_path = icons_cache_dir / f"{sha256}{ext}"
        if not cache_file_path.exists():
            cache_file_path.write_bytes(icon_bytes)
    
    def get_icon_b64_data(self, icon_field: str) -> str | None:
        """
        Given an icon field (e.g. "yoto:#<mediaId>"), return a base64 data URI string for the icon image.
        Returns None if the icon cannot be found or loaded.
        """
        cache_path = self.get_icon_cache_path(icon_field)
        if not cache_path or not cache_path.exists():
            logger.debug(f"No cached icon found for field: {icon_field}")
            return None
        try:
            mime_type = "image/png"  # Default mime type
            ext = cache_path.suffix.lower()
            if ext == ".jpg" or ext == ".jpeg":
                mime_type = "image/jpeg"
            elif ext == ".svg":
                mime_type = "image/svg+xml"
            elif ext == ".gif":
                mime_type = "image/gif"
            img_bytes = cache_path.read_bytes()
            b64_data = base64.b64encode(img_bytes).decode()
            return b64_data
        except Exception as ex:
            logger.error(f"Error loading icon image from {cache_path}: {ex}")
            return None

    def get_icon_cache_path(self, icon_field: str) -> Path | None:
        """
        Given an icon field (e.g. "yoto:#<mediaId>"), return a Path to the cached icon image
        inside OFFICIAL_ICON_CACHE_DIR if available. If the image isn't present but a URL
        is known in the metadata, try to download and cache it, then return the path.
        Returns None if no cache path can be determined.
        """
        logger.debug(f"Getting icon cache path for field: {icon_field}")
        if not icon_field:
            logger.debug("No icon_field provided")
            return None
        try:
            # Accept values like 'yoto:#<mediaId>' or just '<mediaId>'
            media_id = str(icon_field).split("#")[-1] if "#" in str(icon_field) else str(icon_field)
            cache_dir = self.OFFICIAL_ICON_CACHE_DIR
            cache_dir.mkdir(exist_ok=True)

            # Search official metadata files first
            for meta_name in ("icon_metadata.json", "user_icon_metadata.json"):
                meta_path = cache_dir / meta_name
                if not meta_path.exists():
                    logger.debug(f"Metadata file not found: {meta_path}")
                    continue
                try:
                    with meta_path.open("r") as f:
                        icons = json.load(f)
                except Exception as ex:
                    logger.error(f"Error loading icon metadata from {meta_path}: {ex}")
                    continue
                for icon in icons:
                    if str(icon.get("mediaId")) == media_id:
                        # Prefer explicit cache_path if present
                        if icon.get("cache_path"):
                            p = Path(icon.get("cache_path"))
                            if p.exists():
                                logger.debug(f"Found cached icon (from cache_path) at: {p}")
                                return p
                        # Otherwise try to use the url field
                        url = icon.get("url") or icon.get("img_url")
                        if not url:
                            continue
                        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                        ext = Path(url).suffix or ".png"
                        p = cache_dir / f"{url_hash}{ext}"
                        if p.exists():
                            logger.debug(f"Found cached icon at: {p}")
                            return p
                        # Try to download now
                        try:
                            resp = httpx.get(url)
                            resp.raise_for_status()
                            p.write_bytes(resp.content)
                            return p
                        except Exception as ex:
                            logger.error(f"Error downloading icon from {url}: {ex}")
                            return p if p.exists() else None

            # Check upload cache (icons uploaded via this tool)
            logger.debug("Checking upload cache for icon")
            upload_cache = self._load_icon_upload_cache()
            for sha, data in (upload_cache or {}).items():
                if str(data.get("mediaId")) == media_id:
                    url = data.get("url")
                    if not url:
                        continue
                    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                    ext = Path(url).suffix or ".png"
                    p = cache_dir / f"{url_hash}{ext}"
                    if p.exists():
                        return p
                    try:
                        resp = httpx.get(url)
                        resp.raise_for_status()
                        p.write_bytes(resp.content)
                        return p
                    except Exception as ex:
                        logger.error(f"Error getting icon cache path for {icon_field}: {ex}")
                        return p if p.exists() else None
            
            logger.debug(f"No matching icon found for mediaId: {media_id}")
        except Exception as ex:
            logger.error(f"Error getting icon cache path: {ex}")
            return None
        return None

    def upload_yotoicons_icon_to_yoto_api(self, icon: dict, auto_convert: bool = True) -> dict:
        """
        Upload a YotoIcons icon (from cache) to the official Yoto API.
        icon: dict from YotoIcons search/cache (must have 'img_url' or 'cache_path')
        Returns: dict with displayIcon info (mediaId, url, etc)
        """
        # If mediaId exists this is a yoto icon
        if "mediaId" in icon:
            logger.info(f"Icon already a Yoto icon with mediaId: {icon['mediaId']}")
            return icon
        # Determine cache path
        cache_path = None
        if "cache_path" in icon:
            cache_path = Path(icon["cache_path"])
        elif "img_url" in icon:
            url_hash = hashlib.sha256(icon["img_url"].encode()).hexdigest()[:16]
            ext = Path(icon["img_url"]).suffix or ".png"
            cache_path = self.YOTOICONS_CACHE_DIR / f"{url_hash}{ext}"
        if not cache_path or not cache_path.exists():
            raise FileNotFoundError(f"Cached icon image not found for icon: {icon}")
        # Use category or id for filename if available
        filename = "".join(icon.get("tags", [])) or icon.get("id") or cache_path.stem
        return self.upload_custom_icon(str(cache_path), auto_convert=auto_convert, yotoicons_id=icon.get("id"))

    def replace_card_default_icons(self, card: Card, progress_callback: Optional[Callable[[str, float], None]] = None, cancel_event: Optional[threading.Event] = None, include_yotoicons: bool = True, max_searches: int = 3) -> Card:
        """
        Replace default placeholder icons on a Card's chapters and tracks.
        Optionally accepts a progress_callback(msg, frac) for UI updates.
        """

        def _cb(msg: str | None = None, frac: float | None = None):
            try:
                if callable(progress_callback):
                    progress_callback(msg or '', frac if frac is not None else 0.0)
            except Exception:
                pass

        # Early cancellation check
        if cancel_event and cancel_event.is_set():
            _cb('Cancelled', 1.0)
            return card

        # First, scan how many replacements we need to do so we can report progress
        targets = []
        if hasattr(card, "content") and hasattr(card.content, "chapters") and card.content.chapters:
            for ch_idx, chapter in enumerate(card.content.chapters):
                # chapter icon
                if hasattr(chapter, "display") and chapter.display:
                    icon_field = getattr(chapter.display, "icon16x16", None)
                    if icon_field and icon_field.endswith(DEFAULT_MEDIA_ID):
                        targets.append(("chapter", ch_idx, None))
                # track icons
                if hasattr(chapter, "tracks") and chapter.tracks:
                    for tr_idx, track in enumerate(chapter.tracks):
                        if hasattr(track, "display") and track.display:
                            ticon = getattr(track.display, "icon16x16", None)
                            if ticon and ticon.endswith(DEFAULT_MEDIA_ID):
                                targets.append(("track", ch_idx, tr_idx))

        total = len(targets)
        if total == 0:
            _cb('No default icons to replace', 1.0)
            return card

        completed = 0
        for kind, ch_idx, tr_idx in targets:
            # Check for cancellation before each item
            if cancel_event and cancel_event.is_set():
                _cb('Cancelled', completed / total if total else 1.0)
                return card
            try:
                if kind == 'chapter':
                    chapter = card.content.chapters[ch_idx]
                    query = getattr(chapter, 'title', '')
                    _cb(f"Finding icon for chapter '{query}'", completed / total)
                    best_icons = self.find_best_icons_for_text(query, include_yotoicons=include_yotoicons, max_searches=max_searches)
                    if best_icons:
                        best_icon = best_icons[0]
                        media_id = best_icon.get('mediaId')
                        if media_id is None and 'id' in best_icon:
                            _cb(f"Uploading candidate icon for chapter '{query}'", completed / total)
                            if cancel_event and cancel_event.is_set():
                                _cb('Cancelled', completed / total)
                                return card
                            uploaded_icon = self.upload_yotoicons_icon_to_yoto_api(best_icon)
                            media_id = uploaded_icon.get('mediaId')
                        if media_id:
                            chapter.display.icon16x16 = f"yoto:#{media_id}"
                            logger.info(f"Replaced chapter '{chapter.title}' icon with mediaId: {media_id}")
                else:
                    chapter = card.content.chapters[ch_idx]
                    track = chapter.tracks[tr_idx]
                    query = getattr(track, 'title', getattr(chapter, 'title', ''))
                    _cb(f"Finding icon for track '{query}'", completed / total)
                    best_icons = self.find_best_icons_for_text(query, include_yotoicons=include_yotoicons, max_searches=max_searches)
                    if best_icons:
                        best_icon = best_icons[0]
                        media_id = best_icon.get('mediaId')
                        if media_id is None and 'id' in best_icon:
                            _cb(f"Uploading candidate icon for track '{query}'", completed / total)
                            if cancel_event and cancel_event.is_set():
                                _cb('Cancelled', completed / total)
                                return card
                            uploaded_icon = self.upload_yotoicons_icon_to_yoto_api(best_icon)
                            media_id = uploaded_icon.get('mediaId')
                        if media_id:
                            track.display.icon16x16 = f"yoto:#{media_id}"
                            logger.info(f"Replaced track '{track.title}' icon with mediaId: {media_id}")
            except Exception as e:
                logger.error(f"Error replacing icon for {kind} at {ch_idx}/{tr_idx}: {e}")
            finally:
                completed += 1
                _cb(None, completed / total)

        _cb('Icon replacement complete', 1.0)
        return card

    def get_devices(self):
        """
        Retrieves the list of devices associated with the authenticated user.

        Returns:
            dict: A dictionary containing the list of devices and their details.
        """
        url = f"{self.SERVER_URL}/device-v2/devices/mine"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        response = self._cached_request("GET", url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to retrieve devices: {response.status_code} {response.text}")
            response.raise_for_status()

        devices = response.json().get("devices", [])
        logger.debug(f"Retrieved {len(devices)} devices.")
        devices = [Device.model_validate(device) for device in devices]
        return devices

    def get_device_status(self, device_id: str) -> dict:
        """
        Retrieves the current status of a specific device.

        Args:
            device_id (str): The unique identifier of the device.

        Returns:
            dict: Device status information including battery, connectivity, sensors, etc.

        Raises:
            Exception: If the request fails or device is not found.
        """
        url = f"{self.SERVER_URL}/device-v2/{device_id}/status"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = self._cached_request("GET", url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to retrieve device status: {response.status_code} {response.text}")
            response.raise_for_status()
        if self.debug:
            find_extra_fields(DeviceStatus, response.json(), warn_extra=True)
        return DeviceStatus.model_validate(response.json())

    def get_device_config(self, device_id: str) -> dict:
        """
        Retrieves the configuration settings of a specific device.

        Args:
            device_id (str): The unique identifier of the device.

        Returns:
            dict: Device configuration settings.

        Raises:
            Exception: If the request fails or device is not found.
        """
        url = f"{self.SERVER_URL}/device-v2/{device_id}/config"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = self._cached_request("GET", url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to retrieve device config: {response.status_code} {response.text}")
            response.raise_for_status()

        device_json = response.json().get("device", {})
        if self.debug:
            find_extra_fields(DeviceObject, device_json, warn_extra=True)
        return DeviceObject.model_validate(device_json)

    def update_device_config(self, device_id: str, name: str, config: dict | DeviceConfig) -> dict:
        """
        Updates the configuration settings for a specific device.

        Args:
            device_id (str): The unique identifier of the device.
            name (str): The name of the device.
            config (dict): The configuration settings as described in the API.

        Returns:
            dict: Status of the update operation.

        Raises:
            Exception: If the request fails.
        """
        if isinstance(config, DeviceConfig):
            config = config.model_dump()

        url = f"{self.SERVER_URL}/device-v2/{device_id}/config"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        payload = {
            "name": name,
            "config": config
        }
        response = httpx.put(url, headers=headers, json=payload)
        if response.status_code != 200:
            logger.error(f"Failed to update device config: {response.status_code} {response.text}")
            response.raise_for_status()
        return response.json()

    def reset_auth(self):
        """
        Resets the authentication state by clearing stored tokens and cached data.
        """
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        # Remove token cache file
        if self.TOKEN_FILE.exists():
            try:
                self.TOKEN_FILE.unlink()
            except Exception:
                pass
        # Optionally clear other caches if needed
        # For now, we just clear tokens
        logger.info("Authentication state has been reset.")

    def rewrite_track_fields(self, card: Card, field: str, value: str = "", sequential: bool=True, reset_every_chapter: bool = False) -> Card:

        """
        Rewrites the specified field for all tracks in a card to a new label.
        Args:
            card (Card): The card object containing chapters and tracks.
            field (str): The field to set for all tracks (e.g., "key", "overlayLabel").
            label (str): The new label to set for all track overlays.
            sequential (bool): If True, appends a sequential number to each label (e.g., "Label 1", "Label 2", ...).

        Returns:
            Card: The updated card object with modified track overlay labels.
        """
        logger.info(f"Rewriting track {field} to '{value}' (sequential={sequential})")
        if not hasattr(card, "content") or not hasattr(card.content, "chapters"):
            logger.warning("Card has no content or chapters to update.")
            return card

        if card.content.chapters is None:
            logger.warning("Card content chapters is None.")
            return card

        def rewrite_field(track, new_value):
            match field:
                case "key":
                    track.key = new_value
                case "overlayLabel":
                    track.overlayLabel = new_value
                case _:
                    logger.warning(f"Unsupported field '{field}' for rewriting.")
                    raise ValueError(f"Unsupported field '{field}' for rewriting.")

        if reset_every_chapter:
            for chapter in card.content.chapters:
                if hasattr(chapter, "tracks") and chapter.tracks:
                    for index, track in enumerate(chapter.tracks):
                        new_value = value
                        if sequential:
                            new_value = f"{value} {index + 1}".strip()
                        rewrite_field(track, new_value)
                        logger.debug(f"Updated track '{track.title}' {field} to '{new_value}'.")
        else:
            index = 1
            for chapter in card.content.chapters:
                if hasattr(chapter, "tracks") and chapter.tracks:
                    for track in chapter.tracks:
                        new_value = value
                        if sequential:
                            new_value = f"{value} {index}".strip()
                        rewrite_field(track, new_value)
                        logger.debug(f"Updated track '{track.title}' {field} to '{new_value}'.")
                        index += 1

        return card

    def rewrite_chapter_fields(self, card: Card, field: str, value: str = "", sequential: bool=True) -> Card:
        """
        Rewrites the specified field for all chapters in a card to a new label.
        Args:
            card (Card): The card object containing chapters.
            field (str): The field to set for all chapters (e.g., "key", "title").
            label (str): The new label to set for all chapter titles.
            sequential (bool): If True, appends a sequential number to each label (e.g., "Label 1", "Label 2", ...).

        Returns:
            Card: The updated card object with modified chapter labels.
        """
        logger.info(f"Rewriting chapter {field} to '{value}' (sequential={sequential})")
        if not hasattr(card, "content") or not hasattr(card.content, "chapters"):
            logger.warning("Card has no content or chapters to update.")
            return card

        if card.content.chapters is None:
            logger.warning("Card content chapters is None.")
            return card

        def rewrite_field(chapter, new_value):
            match field:
                case "key":
                    chapter.key = new_value
                case "title":
                    chapter.title = new_value
                case "overlayLabel":
                    chapter.overlayLabel = new_value
                case _:
                    logger.warning(f"Unsupported field '{field}' for rewriting.")
                    raise ValueError(f"Unsupported field '{field}' for rewriting.")

        for index, chapter in enumerate(card.content.chapters):
            new_value = value
            if sequential:
                new_value = f"{value} {index + 1}".strip()
            rewrite_field(chapter, new_value)
            logger.debug(f"Updated chapter '{chapter.title}' {field} to '{new_value}'.")

        return card


    def merge_chapters(self, card: Card, chapter_title: str = "Chapter 1", reset_overlay_labels: bool = True, reset_track_keys: bool = True) -> Card:
        """
        Merges all chapters in a card into a single chapter.
        The new chapter's title is taken from the first chapter, and its duration is the sum of all chapters' durations.

        Args:
            card (Card): The card object containing chapters to merge.

        Returns:
            Card: The updated card object with chapters merged into one.
        """
        logger.info("Merging chapters into a single chapter")
        if not hasattr(card, "content") or not hasattr(card.content, "chapters"):
            logger.warning("Card has no content or chapters to merge.")
            return card

        if card.content.chapters is None or len(card.content.chapters) == 0:
            logger.warning("Card content chapters is None or empty.")
            return card

        total_duration = 0
        all_tracks = []

        for chapter in card.content.chapters:
            if chapter.duration:
                total_duration += chapter.duration
            if hasattr(chapter, "tracks") and chapter.tracks:
                    all_tracks.extend(chapter.tracks)

        new_chapter = Chapter(
            key="1",
            title=chapter_title,
            duration=total_duration,
            tracks=all_tracks,
            display=None,
            overlayLabel=None
        )

        card.content.chapters = [new_chapter]

        if reset_overlay_labels:
            card = self.rewrite_track_fields(card, field="overlayLabel", sequential=True)
        if reset_track_keys:
            card = self.rewrite_track_fields(card, field="key", sequential=True)
        logger.debug(f"Merged {len(card.content.chapters)} chapters into one with title '{chapter_title}' and duration {total_duration} seconds.")
        return card

    def split_chapters(self, card: Card, max_tracks_per_chapter: int = 5, reset_overlay_labels: bool = True, reset_track_keys: bool = True, include_part_in_title: bool = True) -> Card:
        """
        Splits chapters in a card into smaller chapters, each containing a maximum number of tracks.
        """
        logger.info("Splitting chapters into smaller chapters")
        if not hasattr(card, "content") or not hasattr(card.content, "chapters"):
            logger.warning("Card has no content or chapters to split.")
            return card

        if card.content.chapters is None or len(card.content.chapters) == 0:
            logger.warning("Card content chapters is None or empty.")
            return card

        new_chapters = []
        for chapter in card.content.chapters:
            if hasattr(chapter, "tracks") and chapter.tracks:
                for i in range(0, len(chapter.tracks), max_tracks_per_chapter):
                    if not include_part_in_title:
                        chapter_title = chapter.title
                    else:
                        chapter_title = f"{chapter.title} (Part {i // max_tracks_per_chapter + 1})"
                    new_chapter = Chapter(
                        key=str(len(new_chapters) + 1),
                        title=chapter_title,
                        duration=sum(track.duration for track in chapter.tracks[i:i + max_tracks_per_chapter]),
                        tracks=chapter.tracks[i:i + max_tracks_per_chapter],
                        display=None,
                        overlayLabel=None
                    )
                    new_chapters.append(new_chapter)

        card.content.chapters = new_chapters

        if reset_overlay_labels:
            card = self.rewrite_track_fields(card, field="overlayLabel", sequential=True)
        if reset_track_keys:
            card = self.rewrite_track_fields(card, field="key", sequential=True)
        logger.debug(f"Split {len(card.content.chapters)} chapters into smaller chapters.")
        return card

    def expand_all_tracks_into_chapters(self, card: Card, reset_overlay_labels: bool = True, reset_track_keys: bool = True) -> Card:
        """
        Expands all tracks in a card so that each track becomes its own chapter.
        """
        logger.info("Expanding all tracks into individual chapters")
        if not hasattr(card, "content") or not hasattr(card.content, "chapters"):
            logger.warning("Card has no content or chapters to expand.")
            return card

        if card.content.chapters is None or len(card.content.chapters) == 0:
            logger.warning("Card content chapters is None or empty.")
            return card

        new_chapters = []
        for chapter in card.content.chapters:
            if hasattr(chapter, "tracks") and chapter.tracks:
                for track in chapter.tracks:
                    # create a new chapter for this track and copy display/icon information
                    new_chapter = Chapter(
                        key=str(len(new_chapters) + 1),
                        title=track.title,
                        duration=track.duration,
                        tracks=[track],
                        display=None,
                        overlayLabel=None
                    )
                    try:
                        # if the track has a display with an icon, propagate it to the new chapter display
                        track_display = getattr(track, 'display', None)
                        if track_display is not None:
                            icon = getattr(track_display, 'icon16x16', None)
                            if icon:
                                # ensure chapter has a display object and set its icon
                                if not getattr(new_chapter, 'display', None):
                                    # import here to avoid circular import issues if any
                                    new_chapter.display = ChapterDisplay()
                                try:
                                    setattr(new_chapter.display, 'icon16x16', icon)
                                except Exception:
                                    # best-effort: ignore failures to set attribute
                                    pass
                    except Exception:
                        pass
                    new_chapters.append(new_chapter)

        card.content.chapters = new_chapters

        if reset_overlay_labels:
            card = self.rewrite_track_fields(card, field="overlayLabel", sequential=True)
        if reset_track_keys:
            card = self.rewrite_track_fields(card, field="key", sequential=True)
        logger.debug(f"Expanded all tracks into {len(card.content.chapters)} individual chapters.")
        return card