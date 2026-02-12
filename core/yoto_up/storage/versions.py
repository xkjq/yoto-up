"""Card version management.

Each time a card payload is saved, a timestamped JSON snapshot is
written to a per-card subdirectory under :data:`VERSIONS_DIR`.  This
gives the user a lightweight local history they can browse or restore.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from .paths import VERSIONS_DIR, ensure_parents


class VersionStore:
    """Manage timestamped JSON snapshots of card payloads."""

    # -- saving -------------------------------------------------------------

    @staticmethod
    def save(card_data: dict[str, Any]) -> Path | None:
        """Save a timestamped JSON snapshot and return its path.

        The card is identified by its ``cardId`` (falling back to ``id``
        or ``contentId``).  If none of those keys are present, the
        ``title`` is slugified and used instead.

        Returns ``None`` if the write fails for any reason.
        """
        try:
            dir_path = VersionStore._card_dir(card_data)
            dir_path.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            file_path = dir_path / f"{ts}.json"
            ensure_parents(file_path)
            file_path.write_text(
                json.dumps(card_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return file_path
        except Exception as exc:
            logger.warning(f"Failed to save card version: {exc}")
            return None

    # -- listing / loading --------------------------------------------------

    @staticmethod
    def list_versions(card_id: str) -> list[Path]:
        """Return version files for *card_id*, newest first."""
        dir_path = VERSIONS_DIR / str(card_id)
        if not dir_path.exists():
            return []
        try:
            files = sorted(
                (p for p in dir_path.iterdir() if p.suffix == ".json"),
                reverse=True,
            )
            return files
        except OSError:
            return []

    @staticmethod
    def load(path: Path) -> dict[str, Any]:
        """Read and return the JSON content of a version file.

        Returns an empty dict if the file cannot be read or parsed.
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
            return json.loads(text)  # type: ignore[return-value]
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def delete(path: Path) -> bool:
        """Delete a single version file.  Returns ``True`` on success."""
        try:
            Path(path).unlink()
            return True
        except OSError as exc:
            logger.warning(f"Failed to delete version file {path}: {exc}")
            return False

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _card_dir(payload: dict[str, Any]) -> Path:
        """Derive the per-card subdirectory from the payload."""
        card_id = (
            payload.get("cardId")
            or payload.get("id")
            or payload.get("contentId")
        )
        if not card_id:
            title = (payload.get("title") or "untitled").strip()[:100]
            card_id = re.sub(r"[^0-9A-Za-z._-]", "-", title)
        # Guard against empty or all-separator slugs
        card_id = str(card_id).strip("-") or "untitled"
        return VERSIONS_DIR / card_id
