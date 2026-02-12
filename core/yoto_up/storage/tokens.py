"""Persistent storage for OAuth tokens.

Tokens are stored as a JSON file in the platform-specific config
directory (see :data:`paths.TOKENS_FILE`).  All writes go through
:func:`atomic_write` to avoid corrupted files on crash.
"""

from __future__ import annotations

import json

from loguru import logger

from ..models.user import TokenData
from .paths import TOKENS_FILE, atomic_write, ensure_parents


def load_tokens() -> TokenData | None:
    """Load saved tokens from disk.

    Returns ``None`` if the file does not exist or cannot be parsed.
    """
    if not TOKENS_FILE.exists():
        return None
    try:
        data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
        return TokenData(**data)
    except Exception as exc:
        logger.warning(f"Failed to load tokens from {TOKENS_FILE}: {exc}")
        return None


def save_tokens(token_data: TokenData) -> None:
    """Persist *token_data* to disk atomically."""
    ensure_parents(TOKENS_FILE)
    atomic_write(
        TOKENS_FILE,
        token_data.model_dump_json(indent=2),
    )
    logger.debug(f"Tokens saved to {TOKENS_FILE}")


def delete_tokens() -> None:
    """Remove the persisted tokens file, if it exists."""
    try:
        if TOKENS_FILE.exists():
            TOKENS_FILE.unlink()
            logger.debug(f"Tokens deleted from {TOKENS_FILE}")
    except OSError as exc:
        logger.error(f"Failed to delete tokens at {TOKENS_FILE}: {exc}")
