"""Pydantic v2 models for Yoto cards, chapters, and tracks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Ambient(BaseModel):
    """Ambient display settings for a track or chapter."""

    model_config = ConfigDict(populate_by_name=True)

    defaultTrackDisplay: str | None = None


class TrackDisplay(BaseModel):
    """Visual display metadata for a track (e.g. icon reference)."""

    model_config = ConfigDict(populate_by_name=True)

    icon16x16: str | None = None


class Track(BaseModel):
    """A single audio or streaming track within a chapter.

    For streaming tracks, *type* is ``"stream"`` and *trackUrl* points at
    the remote audio resource.
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str
    trackUrl: str
    key: str
    format: str
    uid: str | None = None
    type: Literal["audio", "stream"]
    display: TrackDisplay | None = None
    overlayLabelOverride: str | None = None
    overlayLabel: str | None = None
    duration: float | None = None
    fileSize: float | None = None
    channels: Literal["stereo", "mono", 1, 2] | None = None
    ambient: Ambient | None = None
    hasStreams: bool | None = None


class ChapterDisplay(BaseModel):
    """Visual display metadata for a chapter."""

    model_config = ConfigDict(populate_by_name=True)

    icon16x16: str | None = None


class Chapter(BaseModel):
    """A chapter groups one or more tracks with shared display metadata."""

    model_config = ConfigDict(populate_by_name=True)

    title: str
    key: str | None = None
    overlayLabel: str | None = None
    overlayLabelOverride: str | None = None
    tracks: list[Track] = []
    defaultTrackDisplay: str | None = None
    defaultTrackAmbient: str | None = None
    duration: float | None = None
    fileSize: float | None = None
    display: ChapterDisplay | None = None
    hidden: bool | None = None
    hasStreams: bool | None = None
    ambient: Ambient | None = None
    availableFrom: str | None = None


class CardStatus(BaseModel):
    """Workflow status of a card."""

    model_config = ConfigDict(populate_by_name=True)

    name: Literal["new", "inprogress", "complete", "live", "archived"]
    updatedAt: str | None = None


class CardCover(BaseModel):
    """Cover image reference for a card."""

    model_config = ConfigDict(populate_by_name=True)

    imageL: str | None = None


class CardMedia(BaseModel):
    """Aggregate media information for a card."""

    model_config = ConfigDict(populate_by_name=True)

    duration: float | None = None
    fileSize: float | None = None
    hasStreams: bool | None = None


class CardConfig(BaseModel):
    """Playback configuration for a card."""

    model_config = ConfigDict(populate_by_name=True)

    autoadvance: str | None = None
    resumeTimeout: int | None = None
    systemActivity: bool | None = None
    trackNumberOverlayTimeout: int | None = None


class CardMetadata(BaseModel):
    """Rich metadata associated with a card (author, category, cover, etc.)."""

    model_config = ConfigDict(populate_by_name=True)

    accent: str | None = None
    addToFamilyLibrary: bool | None = None
    author: str | None = None
    category: (
        Literal[
            "",
            "none",
            "stories",
            "music",
            "radio",
            "podcast",
            "sfx",
            "activities",
            "alarms",
        ]
        | None
    ) = None
    copyright: str | None = None
    cover: CardCover | None = None
    description: str | None = None
    genre: list[str] | None = None
    languages: list[str] | None = None
    maxAge: int | None = None
    media: CardMedia | None = None
    minAge: int | None = None
    musicType: list[str] | None = None
    note: str | None = None
    order: str | None = None
    audioPreviewUrl: str | None = None
    readBy: str | None = None
    share: bool | None = None
    status: CardStatus | None = None
    tags: list[str] | None = None
    feedUrl: str | None = None
    numEpisodes: int | None = None
    playbackDirection: Literal["DESC", "ASC"] | None = None
    previewAudio: str = ""
    hidden: bool = False


class CardContent(BaseModel):
    """Playback content of a card (chapters, playback type, config)."""

    model_config = ConfigDict(populate_by_name=True)

    activity: str | None = None
    chapters: list[Chapter] | None = None
    config: CardConfig | None = None
    playbackType: Literal["linear", "interactive"] | None = None
    version: str | None = None
    hidden: bool = False


class Card(BaseModel):
    """Top-level representation of a Yoto card.

    The only strictly required field is *title*; everything else is optional
    so that partial API responses can be parsed without error.
    """

    model_config = ConfigDict(populate_by_name=True)

    cardId: str | None = None
    title: str
    metadata: CardMetadata | None = None
    content: CardContent | None = None
    tags: list[str] | None = None
    slug: str | None = None
    deleted: bool = False
    createdAt: str | None = None
    createdByClientId: str | None = None
    updatedAt: str | None = None
    userId: str | None = None

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------

    @property
    def total_duration(self) -> float:
        """Sum of all track durations across every chapter (seconds)."""
        if not self.content or not self.content.chapters:
            return 0.0
        total = 0.0
        for chapter in self.content.chapters:
            for track in chapter.tracks:
                if track.duration is not None:
                    total += track.duration
        return total

    @property
    def total_tracks(self) -> int:
        """Total number of tracks across all chapters."""
        if not self.content or not self.content.chapters:
            return 0
        return sum(len(chapter.tracks) for chapter in self.content.chapters)

    @property
    def chapter_count(self) -> int:
        """Number of chapters on this card."""
        if not self.content or not self.content.chapters:
            return 0
        return len(self.content.chapters)
