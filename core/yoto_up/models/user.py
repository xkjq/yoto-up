"""Pydantic v2 models for user authentication tokens."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TokenData(BaseModel):
    """OAuth / authentication token bundle."""

    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    refresh_token: str
    id_token: str | None = None
