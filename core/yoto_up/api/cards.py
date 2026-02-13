"""Card CRUD operations against the Yoto API.

All functions accept a :class:`~yoto_up.api.client.YotoClient` as their first
argument and return parsed Pydantic models.
"""

from __future__ import annotations

from loguru import logger

from ..models.card import Card, CardContent, CardMetadata
from .client import YotoClient


def get_library(client: YotoClient) -> list[Card]:
    """Fetch all cards in the authenticated user's library.

    Returns a list of :class:`Card` instances parsed from the API response.
    Cards that fail to parse are logged and skipped.
    """
    resp = client.get("/content/mine")
    resp.raise_for_status()
    data = resp.json()

    # The API wraps the list in a top-level "cards" key (or may return a
    # bare list -- handle both).
    raw_cards: list[dict] = data.get("cards", data) if isinstance(data, dict) else data

    cards: list[Card] = []
    for raw in raw_cards:
        try:
            cards.append(_parse_card(raw))
        except Exception as exc:
            card_id = raw.get("cardId", "<unknown>")
            logger.warning(f"Failed to parse card {card_id}: {exc}")
    return cards


def get_card(client: YotoClient, card_id: str) -> Card:
    """Fetch a single card by its ID.

    Raises :class:`httpx.HTTPStatusError` on non-2xx responses.
    """
    resp = client.get(f"/content/{card_id}")
    resp.raise_for_status()
    data = resp.json()

    # The response may wrap the card in a "card" key.
    raw = data.get("card", data) if isinstance(data, dict) and "card" in data else data
    return _parse_card(raw)


def create_or_update_card(client: YotoClient, card: Card) -> Card:
    """Create a new card or update an existing one.

    The Yoto API uses POST ``/content`` for both creation and updates.
    If ``card.cardId`` is set the existing card is updated; otherwise a new
    card is created.

    Returns the card as returned by the server (with any server-assigned
    fields populated).
    """
    payload = card.model_dump(exclude_none=True)
    resp = client.post("/content", json=payload)
    resp.raise_for_status()
    data = resp.json()

    raw = data.get("card", data) if isinstance(data, dict) and "card" in data else data
    return _parse_card(raw)


def delete_card(client: YotoClient, card_id: str) -> bool:
    """Delete a card by its ID.

    Returns ``True`` if the server responded with a success status code,
    ``False`` otherwise.
    """
    try:
        resp = client.delete(f"/content/{card_id}")
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error(f"Failed to delete card {card_id}: {exc}")
        return False


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _parse_card(raw: dict) -> Card:
    """Parse a raw dict into a :class:`Card`, handling nested structures.

    The API sometimes returns metadata and content as flat dicts that need
    to be explicitly parsed into their Pydantic sub-models.

    A shallow copy is made so the caller's original dict is not mutated.
    """
    data = dict(raw)
    # Ensure nested objects are parsed through their models so that
    # validation is applied consistently.
    if "metadata" in data and isinstance(data["metadata"], dict):
        data["metadata"] = CardMetadata(**data["metadata"])
    if "content" in data and isinstance(data["content"], dict):
        data["content"] = CardContent(**data["content"])
    return Card(**data)
