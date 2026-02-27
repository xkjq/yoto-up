from asyncio.log import logger
from typing import Optional, List, Literal, cast
from pydantic import BaseModel
from yoto_up.icons import render_icon

DEFAULT_MEDIA_ID = "yoto:#aUm9i3ex3qqAMYBv-i-O-pYMKuMJGICtR3Vhf289u2Q"

class Ambient(BaseModel):
    defaultTrackDisplay: Optional[str] = None

class TrackDisplay(BaseModel):
    icon16x16: Optional[str] = None

class Track(BaseModel):
    """
    Represents a Yoto track, which can be a local audio file or a streaming track.
    For streaming tracks:
        - type: "stream"
        - trackUrl: URL to the audio stream
        - format: format of the stream (e.g. "mp3", "aac")
    Example:
        Track(
            key="01",
            type="stream",
            format="mp3",
            title="Test Streaming Playlist",
            trackUrl="https://yoto.dev/music/autumn-3.mp3",
            display=TrackDisplay(icon16x16="yoto:#ZuVmuvnoFiI4el6pBPvq0ofcgQ18HjrCmdPEE7GCnP8")
        )
    """
    title: str
    trackUrl: str
    key: str
    format: str
    uid: Optional[str] = None
    type: Literal["audio", "stream"]
    display: Optional[TrackDisplay] = None
    overlayLabelOverride: Optional[str] = None
    overlayLabel: Optional[str] = None
    duration: Optional[float] = None
    fileSize: Optional[float] = None
    channels: Optional[Literal["stereo", "mono", 1, 2]] = None
    ambient: Optional[Ambient] = None
    hasStreams: Optional[bool] = None

    def get_title(self) -> str:
        return self.title

    def get_icon_field(self) -> Optional[str]:
        if self.display is None:
            self.display = TrackDisplay()  # Ensure display is at least an empty ChapterDisplay to avoid attribute errors
        
        return self.display.icon16x16

    def set_icon_field(self, icon_value: Optional[str]) -> None:
        if self.display is None:
            self.display = TrackDisplay()
        
        self.display.icon16x16 = icon_value
    
    def clear_icon_field(self):
        if self.display is None:
            self.display = TrackDisplay()
        self.display.icon16x16 = DEFAULT_MEDIA_ID


class ChapterDisplay(BaseModel):
    icon16x16: Optional[str] = None


class Chapter(BaseModel):
    title: str
    key: Optional[str] = None
    overlayLabel: Optional[str] = None
    overlayLabelOverride: Optional[str] = None
    tracks: List[Track]
    defaultTrackDisplay: Optional[str] = None
    defaultTrackAmbient: Optional[str] = None
    duration: Optional[float] = None
    fileSize: Optional[float] = None
    display: Optional[ChapterDisplay] = None
    hidden: Optional[bool] = None
    hasStreams: Optional[bool] = None
    ambient: Optional[Ambient] = None
    availableFrom: Optional[str] = None


    def get_title(self) -> str:
        return self.title

    def get_icon_field(self) -> Optional[str]:
        """Return the icon16x16 field from the chapter's display, automatically 
        creating the display object if needed, and safely handling missing fields."""
        if self.display is None:
            self.display = ChapterDisplay()
        
        return self.display.icon16x16

    def set_icon_field(self, icon_value: Optional[str]) -> None:
        """Set the icon16x16 field in the chapter's display to the given value, 
        automatically creating the display object if needed."""
        if self.display is None:
            self.display = ChapterDisplay()
        
        self.display.icon16x16 = icon_value
    
    def clear_icon_field(self) -> None:
        """Clear the icon16x16 field in the chapter's display."""
        if self.display is None:
            self.display = ChapterDisplay()
        
        self.display.icon16x16 = DEFAULT_MEDIA_ID

    def clear_all_track_icons(self) -> None:
        """Utility method to clear icons from all tracks in this chapter."""
        if self.tracks:
            for track in self.tracks:
                track.clear_icon_field()
    
    def get_tracks(self) -> List[Track]:
        try:
            return self.tracks or []
        except Exception:
            return []

class CardStatus(BaseModel):
    name: Literal["new", "inprogress", "complete", "live", "archived"]
    updatedAt: Optional[str] = None

class CardCover(BaseModel):
    imageL: Optional[str] = None

    @staticmethod
    def media_url_from_upload_response(upload_result: object) -> Optional[str]:
        if not isinstance(upload_result, dict):
            return None
        payload = cast(dict[str, object], upload_result)
        cover_obj = payload.get("coverImage")
        if isinstance(cover_obj, dict):
            cover_payload = cast(dict[str, object], cover_obj)
            media = cover_payload.get("mediaUrl") or cover_payload.get("media_url")
            if isinstance(media, str) and media:
                return media
        top_level = payload.get("mediaUrl") or payload.get("media_url")
        return top_level if isinstance(top_level, str) and top_level else None

class CardMedia(BaseModel):
    duration: Optional[float] = None
    fileSize: Optional[float] = None
    hasStreams: Optional[bool] = None

class CardConfig(BaseModel):
    autoadvance: Optional[str] = None
    resumeTimeout: Optional[int] = None
    systemActivity: Optional[bool] = None
    trackNumberOverlayTimeout: Optional[int] = None

class CardMetadata(BaseModel):
    accent: Optional[str] = None
    addToFamilyLibrary: Optional[bool] = None
    author: Optional[str] = None
    category: Optional[Literal["", "none", "stories", "music", "radio", "podcast", "sfx", "activities", "alarms"]] = None
    copyright: Optional[str] = None
    cover: Optional[CardCover] = None
    description: Optional[str] = None
    genre: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    maxAge: Optional[int] = None
    media: Optional[CardMedia] = None
    minAge: Optional[int] = None
    musicType: Optional[List[str]] = None
    note: Optional[str] = None
    order: Optional[str] = None
    audioPreviewUrl: Optional[str] = None
    readBy: Optional[str] = None
    share: Optional[bool] = None
    status: Optional[CardStatus] = None
    tags: Optional[List[str]] = None
    feedUrl: Optional[str] = None
    numEpisodes: Optional[int] = None
    playbackDirection: Optional[Literal["DESC", "ASC"]] = None
    previewAudio: str = ""
    hidden: bool = False

    def get_cover(self) -> CardCover:
        if self.cover is None:
            self.cover = CardCover()
        return self.cover

class CardContent(BaseModel):
    activity: Optional[str] = None
    chapters: Optional[List[Chapter]] = None
    config: Optional[CardConfig] = None
    playbackType: Optional[Literal["linear", "interactive"]] = None
    version: Optional[str] = None
    hidden: bool = False

class Card(BaseModel):
    cardId: Optional[str] = None
    title: str
    metadata: Optional[CardMetadata] = None
    content: Optional[CardContent] = None
    tags: Optional[List[str]] = None
    slug: Optional[str] = None
    deleted: bool = False
    createdAt: Optional[str] = None
    createdByClientId: Optional[str] = None
    updatedAt: Optional[str] = None
    userId: Optional[str] = None

    def clear_all_icons(self):
        """Utility method to remove all icon references from the card's chapters and tracks."""
        for ch in self.get_chapters():
            ch.clear_all_track_icons()
            ch.clear_icon_field()

    def get_metadata(self) -> CardMetadata:
        if self.metadata is None:
            self.metadata = CardMetadata()
        return self.metadata

    def get_cover(self) -> CardCover:
        return self.get_metadata().get_cover()

    def clear_cover(self) -> "Card":
        self.get_metadata().cover = CardCover()
        return self

    def set_cover_url(self, url: Optional[str]) -> "Card":
        if isinstance(url, str) and url:
            self.get_cover().imageL = url
        return self

    def apply_cover_upload_result(self, upload_result: object, fallback_url: Optional[str] = None) -> "Card":
        media_url = CardCover.media_url_from_upload_response(upload_result)
        if media_url:
            self.set_cover_url(media_url)
        else:
            self.set_cover_url(fallback_url)
        return self

    def get_author(self) -> Optional[str]:
        try:
            meta = self.get_metadata()
            return getattr(meta, "author", None)
        except Exception:
            return None

    def get_category(self) -> Optional[str]:
        try:
            meta = self.get_metadata()
            return getattr(meta, "category", None) or ""
        except Exception:
            return ""

    def get_genres(self) -> list[str]:
        """Return a list of genres for the card (robust to string or list forms)."""
        try:
            meta = self.get_metadata()
            # Prefer structured metadata.genre
            genres = getattr(meta, "genre", None) or []
            if isinstance(genres, str):
                return [g.strip() for g in genres.split(",") if g.strip()]
            if genres:
                return [g for g in genres if g]
            # Fallback: inspect raw payload for alternate keys
            try:
                d = self.model_dump(exclude_none=True)
                meta_raw = d.get("metadata") or {}
                alt = meta_raw.get("genres") or meta_raw.get("genre") or []
                if isinstance(alt, str):
                    return [g.strip() for g in alt.split(",") if g.strip()]
                return [g for g in alt if g]
            except Exception:
                return []
        except Exception:
            return []

    def get_title(self) -> str:
        """Return the card's title, or an empty string if not available."""
        return self.title


    def get_tags(self) -> list[str]:
        """Return combined tags from card-level and metadata-level tags."""
        try:
            tags = []
            if self.tags:
                tags.extend([t for t in self.tags if t])
            meta = self.get_metadata()
            mtags = getattr(meta, "tags", None) or []
            if isinstance(mtags, str):
                tags.extend([t.strip() for t in mtags.split(",") if t.strip()])
            else:
                tags.extend([t for t in (mtags or []) if t])
            return tags
        except Exception:
            return []

    def get_preview_titles(self, count: int = 3) -> list[str]:
        """Return up to `count` chapter titles for compact preview."""
        try:
            ch = self.get_chapters()
            titles = []
            for c in ch[:count]:
                if hasattr(c, "title") and c.title:
                    titles.append(c.title)
                else:
                    try:
                        titles.append(str(c))
                    except Exception:
                        titles.append("")
            return [t for t in titles if t]
        except Exception:
            return []

    def get_short_description(self, limit: int = 80) -> str:
        try:
            meta = self.get_metadata()
            desc = getattr(meta, "description", None) or ""
            if not desc:
                return ""
            s = str(desc)
            return s if len(s) <= limit else s[: limit - 1] + "…"
        except Exception:
            return ""

    def get_chapters(self) -> List[Chapter]:
        """Return the list of chapters in the card, or an empty list if not available."""
        try:
            if self.content and self.content.chapters:
                return self.content.chapters
        except Exception:
            logger.warning(f"Failed to get chapters for card {self.cardId}")
        return []

    def get_track_list(self) -> List[Track]:
        """Return the list of tracks in the card, or an empty list if not available."""
        try:
            tracks = []
            chapters = self.get_chapters()
            for ch in chapters:
                if ch.tracks:
                    tracks.extend(ch.tracks)
            return tracks
        except Exception:
            logger.warning(f"Failed to get track list for card {self.cardId}")
            return []

    def get_cover_url(self) -> Optional[str]:
        """Return the URL of the card's cover image, if available."""
        try:
            if self.metadata and self.metadata.cover and self.metadata.cover.imageL:
                return self.metadata.cover.imageL
        except Exception:
            logger.warning(f"Failed to get cover URL for card {self.cardId}")
        return None

    def display_card(self, truncate_fields_limit: int | None = 50, render_icons: bool = False, api: object | None = None, render_method: str = "braille", braille_dims: tuple[int, int] = (8, 4), braille_x_scale: int | None = None, include_chapters: bool = True ):
        def trunc(val):
            if truncate_fields_limit is None or truncate_fields_limit <= 0:
                return val
            if isinstance(val, str) and len(val) > truncate_fields_limit:
                return val[:truncate_fields_limit-1] + '…'
            return val

        # Build header lines with available metadata (safe access)
        header_lines = []
        header_lines.append(f"[bold magenta]{trunc(self.title)}[/bold magenta]")
        header_lines.append(f"[cyan]ID:[/] [bold]{trunc(self.cardId) if self.cardId else ''}[/bold]")
        status_name = ''
        try:
            status_name = self.metadata.status.name if self.metadata and self.metadata.status else ''
        except Exception:
            status_name = ''
        header_lines.append(f"[yellow]Status:[/] [bold]{trunc(status_name)}[/bold]")

        # Metadata fields
        author = (self.metadata.author if self.metadata and getattr(self.metadata, 'author', None) else None)
        if author:
            header_lines.append(f"[white]Author:[/] {trunc(author)}")

        category = (self.metadata.category if self.metadata and getattr(self.metadata, 'category', None) else None)
        if category:
            header_lines.append(f"[white]Category:[/] {trunc(category)}")

        # Tags (card-level and metadata tags)
        combined_tags = []
        try:
            if self.tags:
                combined_tags.extend([t for t in self.tags if t])
            if self.metadata and getattr(self.metadata, 'tags', None):
                combined_tags.extend([t for t in self.metadata.tags or [] if t])
        except Exception:
            pass
        if combined_tags:
            header_lines.append(f"[cyan]Tags:[/] {', '.join(combined_tags)}")

        # Genre / Languages
        try:
            if self.metadata and getattr(self.metadata, 'genre', None):
                genres = [str(g) for g in (self.metadata.genre or []) if g]
                if genres:
                    header_lines.append(f"[green]Genre:[/] {', '.join(genres)}")
        except Exception:
            pass
        try:
            if self.metadata and getattr(self.metadata, 'languages', None):
                languages = [str(lang) for lang in (self.metadata.languages or []) if lang]
                if languages:
                    header_lines.append(f"[green]Languages:[/] {', '.join(languages)}")
        except Exception:
            pass

        # Age recommendation
        try:
            if self.metadata and getattr(self.metadata, 'minAge', None) is not None:
                header_lines.append(f"[blue]Min Age:[/] {self.metadata.minAge}")
            if self.metadata and getattr(self.metadata, 'maxAge', None) is not None:
                header_lines.append(f"[blue]Max Age:[/] {self.metadata.maxAge}")
        except Exception:
            pass

        # Copyright / readBy / description (truncated)
        try:
            if self.metadata and getattr(self.metadata, 'copyright', None):
                header_lines.append(f"[white]Copyright:[/] {trunc(self.metadata.copyright)}")
        except Exception:
            pass
        try:
            if self.metadata and getattr(self.metadata, 'readBy', None):
                header_lines.append(f"[white]Read By:[/] {trunc(self.metadata.readBy)}")
        except Exception:
            pass
        try:
            if self.metadata and getattr(self.metadata, 'description', None):
                header_lines.append(f"[white]Description:[/] {trunc(self.metadata.description)}")
        except Exception:
            pass

        # Cover, duration, file size, preview audio, playback type, flags, timestamps
        cover_val = ''
        try:
            cover_val = self.metadata.cover.imageL if self.metadata and self.metadata.cover and self.metadata.cover.imageL else ''
        except Exception:
            cover_val = ''
        header_lines.append(f"[green]Cover:[/] {trunc(cover_val)}")

        try:
            dur = self.metadata.media.duration if self.metadata and self.metadata.media and self.metadata.media.duration is not None else ''
        except Exception:
            dur = ''
        header_lines.append(f"[blue]Duration:[/] {dur}")
        try:
            fsize = self.metadata.media.fileSize if self.metadata and self.metadata.media and self.metadata.media.fileSize is not None else ''
        except Exception:
            fsize = ''
        header_lines.append(f"[blue]File Size:[/] {fsize}")
        try:
            prev = self.metadata.previewAudio if self.metadata and getattr(self.metadata, 'previewAudio', None) else ''
        except Exception:
            prev = ''
        header_lines.append(f"[blue]Preview Audio:[/] {trunc(prev)}")
        header_lines.append(f"[magenta]Playback Type:[/] {trunc(self.content.playbackType) if self.content and self.content.playbackType else ''}")
        #header_lines.append(f"[red]Hidden:[/] {self.hidden if hasattr(self, 'hidden') else False}")
        #header_lines.append(f"[red]Deleted:[/] {self.deleted if hasattr(self, 'deleted') else False}")
        header_lines.append(f"[white]Created At:[/] {trunc(self.createdAt) if hasattr(self, 'createdAt') and self.createdAt else ''}")
        header_lines.append(f"[white]Client ID:[/] {trunc(self.createdByClientId) if hasattr(self, 'createdByClientId') and self.createdByClientId else ''}")

        panel_text = "\n".join(line for line in header_lines if line)

        if include_chapters:
            # Add chapter and track details
            chapters_section = ""
            if self.content and hasattr(self.content, "chapters") and self.content.chapters:
                chapters_section += "\n[bold underline]Chapters & Tracks:[/bold underline]\n"
                for idx, chapter in enumerate(self.content.chapters, 1):
                    chapter_title = trunc(getattr(chapter, 'title', ''))
                    # Chapter header
                    # Attempt to render a compact inline icon for the chapter (single-line)
                    chapter_icon_inline = ""
                    if render_icons and api is not None and hasattr(api, 'get_icon_cache_path'):
                        icon_field = chapter.get_icon_field()
                        if icon_field:
                            try:
                                method = getattr(api, 'get_icon_cache_path', None)
                                cache_path = method(icon_field) if callable(method) else None
                                if cache_path and cache_path.exists():
                                    if render_method == 'braille':
                                        # Render full braille icon (all lines)
                                        ci = render_icon(cache_path, method='braille', braille_dims=(8, 4), braille_x_scale=braille_x_scale)
                                    else:
                                        ci = render_icon(cache_path, method='blocks')
                                    # Use the full icon (multi-line), indented for alignment
                                    chapter_icon_inline = "\n".join(line for line in ci.splitlines())
                            except Exception:
                                chapter_icon_inline = ""

                    chapter_icon_lines = chapter_icon_inline.splitlines() if chapter_icon_inline else []
                    chapter_details = [
                        f"[bold]Chapter {idx}:[/bold] {chapter_title}",
                        f"[blue]Duration:[/] {getattr(chapter, 'duration', '')}",
                        f"[magenta]Key:[/] {getattr(chapter, 'key', '')}",
                        f"[yellow]Overlay Label:[/] {getattr(chapter, 'overlayLabel', '')}",
                    ]
                    # Pad chapter_details if needed so its length >= chapter_icon_lines
                    if len(chapter_details) < len(chapter_icon_lines):
                        chapter_details += [""] * (len(chapter_icon_lines) - len(chapter_details))

                    for line_idx, chapter_detail in enumerate(chapter_details):
                        logger.debug(f"Chapter line {line_idx}: '{chapter_detail}' with icon line '{chapter_icon_lines[line_idx] if line_idx < len(chapter_icon_lines) else ''}'")
                        chapters_section += f"{chapter_icon_lines[line_idx] if line_idx < len(chapter_icon_lines) else ''}  {chapter_detail}\n"
                    chapters_section += "\n"
                    ## Optionally render chapter icon
                    #if render_icons and api is not None and hasattr(api, 'get_icon_cache_path'):
                    #    icon_field = getattr(chapter.display, 'icon16x16', None) if hasattr(chapter, 'display') and chapter.display else None
                    #    if icon_field:
                    #        try:
                    #            method = getattr(api, 'get_icon_cache_path', None)
                    #            cache_path = method(icon_field) if callable(method) else None
                    #            if cache_path and cache_path.exists():
                    #                # render chapter icon using requested method/scale
                    #                art = render_icon(cache_path, method=render_method, braille_dims=braille_dims, braille_x_scale=braille_x_scale)
                    #                chapters_section += "  [green]Chapter Icon:[/]\n" + art + "\n"
                    #            else:
                    #                chapters_section += "  [red]Chapter Icon: not available[/red]\n"
                    #        except Exception:
                    #            chapters_section += "  [red]Chapter Icon: error resolving[/red]\n"
                    # List tracks individually and attach per-track icons immediately beneath each track
                    if hasattr(chapter, 'tracks') and chapter.tracks:
                        for t_idx, track in enumerate(chapter.tracks, 1):
                            track_title = trunc(getattr(track, 'title', str(track)))
                            # prepare inline track icon
                            track_icon_inline = ""
                            if render_icons and api is not None and hasattr(api, 'get_icon_cache_path'):
                                t_icon_field = track.get_icon_field()
                                if t_icon_field:
                                    try:
                                        t_method = getattr(api, 'get_icon_cache_path', None)
                                        t_cache = t_method(t_icon_field) if callable(t_method) else None
                                        if t_cache and t_cache.exists():
                                                if render_method == 'braille':
                                                    # Render track braille icons at 8x4
                                                    ti = render_icon(t_cache, method='braille', braille_dims=(8, 4), braille_x_scale=braille_x_scale)
                                                else:
                                                    ti = render_icon(t_cache, method='blocks')
                                                track_icon_inline = ti if ti else ""
                                        else:
                                            track_icon_inline = "[red]Icon not available[/red]"
                                    except Exception:
                                        track_icon_inline = "[red]Icon error[/red]"

                            track_details = [
                                f"[cyan]Track {t_idx}:[/] [bold]{track_title}[/bold]",
                                f"[blue]Duration:[/] {getattr(track, 'duration', '')}",
                                f"[magenta]Format:[/] {getattr(track, 'format', '')}",
                                f"[yellow]Type:[/] {getattr(track, 'type', '')}",
                                f"[green]Key:[/] {getattr(track, 'key', '')}",
                                f"[yellow]Overlay Label:[/] {getattr(track, 'overlayLabel', '')}"
                            ]
                            icon_lines = track_icon_inline.splitlines() if track_icon_inline else []

                            # Pad track_details if needed so its length >= icon_lines
                            if len(track_details) < len(icon_lines):
                                track_details += [""] * (len(icon_lines) - len(track_details))

                            for line_idx, track_detail in enumerate(track_details):
                                chapters_section += f"    {icon_lines[line_idx] if line_idx < len(icon_lines) else ''}  {track_detail}\n"
                            chapters_section += "\n"

                            # Render icon to the left of the track details
                            #chapters_section += f"{track_icon_inline} [cyan]Track {t_idx}:[/] {track_title} [blue]Duration:[/] {getattr(track, 'duration', '')}\n"
            panel_text += chapters_section
        return panel_text

class Device(BaseModel):
    deviceId: str
    name: str
    description: str
    online: bool
    releaseChannel: str
    deviceType: str
    deviceFamily: str
    deviceGroup: str

class DeviceStatus(BaseModel):
    activeCard: str
    ambientLightSensorReading: int
    averageDownloadSpeedBytesSecond: int
    batteryLevelPercentage: int
    batteryLevelPercentageRaw: int
    buzzErrors: int
    cardInsertionState: int
    dayMode: int
    deviceId: str
    errorsLogged: int
    firmwareVersion: str
    freeDiskSpaceBytes: int
    isAudioDeviceConnected: bool
    isBackgroundDownloadActive: bool
    isBluetoothAudioConnected: bool
    isCharging: bool
    isNfcLocked: int
    isOnline: bool
    latestNfcTestErrorPercentage: int
    networkSsid: str
    nightlightMode: str
    playingSource: int
    powerCapabilities: str
    powerSource: int
    systemVolumePercentage: int
    taskWatchdogTimeoutCount: int
    temperatureCelcius: str
    totalDiskSpaceBytes: int
    updatedAt: str
    uptime: int
    userVolumePercentage: int
    utcOffsetSeconds: int
    utcTime: int
    wifiStrength: int

    def display_device_status(self):
        status_info = (
            f"[bold magenta]Device ID:[/] [bold]{self.deviceId}[/bold]\n"
            f"[cyan]Online:[/] [bold]{self.isOnline}[/bold]\n"
            f"[yellow]Firmware Version:[/] [bold]{self.firmwareVersion}[/bold]\n"
            f"[green]Battery Level:[/] [bold]{self.batteryLevelPercentage}%[/bold]\n"
            f"[blue]Free Disk Space:[/] [bold]{self.freeDiskSpaceBytes / (1024 * 1024):.2f} MB[/bold]\n"
            f"[blue]Total Disk Space:[/] [bold]{self.totalDiskSpaceBytes / (1024 * 1024):.2f} MB[/bold]\n"
            f"[blue]System Volume:[/] [bold]{self.systemVolumePercentage}%[/bold]\n"
            f"[blue]User Volume:[/] [bold]{self.userVolumePercentage}%[/bold]\n"
            f"[blue]Ambient Light Sensor Reading:[/] [bold]{self.ambientLightSensorReading}[/bold]\n"
            f"[blue]Temperature (Celsius):[/] [bold]{self.temperatureCelcius}°C[/bold]\n"
            f"[white]Last Updated At:[/] {self.updatedAt}\n"
            f"[white]Uptime:[/] {self.uptime} seconds\n"
        )
        return status_info

class ShortcutParams(BaseModel):
    card: Optional[str] = None
    chapter: Optional[str] = None
    track: Optional[str] = None

class ShortcutContentItem(BaseModel):
    cmd: Optional[str] = None
    params: Optional[ShortcutParams] = None

class ModeContent(BaseModel):
    content: Optional[List[ShortcutContentItem]] = None

class Shortcuts(BaseModel):
    modes: Optional[dict[str, ModeContent]] = None
    versionId: Optional[str] = None

class DeviceConfig(BaseModel):
    alarms: Optional[List[dict]] = None
    ambientColour: Optional[str] = None
    bluetoothEnabled: Optional[str] = None
    btHeadphonesEnabled: Optional[bool] = None
    clockFace: Optional[str] = None
    dayDisplayBrightness: Optional[str] = None
    dayTime: Optional[str] = None
    dayYotoDaily: Optional[str] = None
    dayYotoRadio: Optional[str] = None
    displayDimBrightness: Optional[str] = None
    displayDimTimeout: Optional[str] = None
    headphonesVolumeLimited: Optional[bool] = None
    hourFormat: Optional[str] = None
    maxVolumeLimit: Optional[str] = None
    nightAmbientColour: Optional[str] = None
    nightDisplayBrightness: Optional[str] = None
    nightMaxVolumeLimit: Optional[str] = None
    nightTime: Optional[str] = None
    nightYotoDaily: Optional[str] = None
    nightYotoRadio: Optional[str] = None
    repeatAll: Optional[bool] = None
    shutdownTimeout: Optional[str] = None
    volumeLevel: Optional[str] = None

class DeviceObject(BaseModel):
    config: Optional[DeviceConfig] = None
    deviceFamily: Optional[str] = None
    deviceGroup: Optional[str] = None
    deviceId: Optional[str] = None
    deviceType: Optional[str] = None
    errorCode: Optional[str] = None
    geoTimezone: Optional[str] = None
    getPosix: Optional[str] = None
    mac: Optional[str] = None
    online: Optional[bool] = None
    registrationCode: Optional[str] = None
    releaseChannelId: Optional[str] = None
    releaseChannelVersion: Optional[str] = None
    shortcuts: Optional[Shortcuts] = None


    def display_device_config(self):
        config_info = (
            f"[bold magenta]Device ID:[/] [bold]{self.deviceId}[/bold]\n"
            f"[cyan]Online:[/] [bold]{self.online}[/bold]\n"
            f"[yellow]Release Channel Version:[/] [bold]{self.releaseChannelVersion}[/bold]\n"
            f"[green]Bluetooth Enabled:[/] [bold]{self.config.bluetoothEnabled if self.config and self.config.bluetoothEnabled else ''}[/bold]\n"
            f"[blue]Clock Face:[/] [bold]{self.config.clockFace if self.config and self.config.clockFace else ''}[/bold]\n"
            f"[blue]Day Display Brightness:[/] [bold]{self.config.dayDisplayBrightness if self.config and self.config.dayDisplayBrightness else ''}[/bold]\n"
            f"[blue]Day Time:[/] [bold]{self.config.dayTime if self.config and self.config.dayTime else ''}[/bold]\n"
            f"[blue]Night Display Brightness:[/] [bold]{self.config.nightDisplayBrightness if self.config and self.config.nightDisplayBrightness else ''}[/bold]\n"
            f"[blue]Night Time:[/] [bold]{self.config.nightTime if self.config and self.config.nightTime else ''}[/bold]\n"
            f"[blue]Max Volume Limit:[/] [bold]{self.config.maxVolumeLimit if self.config and self.config.maxVolumeLimit else ''}[/bold]\n"
            f"[blue]Night Max Volume Limit:[/] [bold]{self.config.nightMaxVolumeLimit if self.config and self.config.nightMaxVolumeLimit else ''}[/bold]\n"
            f"[blue]Volume Level:[/] [bold]{self.config.volumeLevel if self.config and self.config.volumeLevel else ''}[/bold]\n"
        )
        return config_info

class TranscodedMetadata(BaseModel):
    title: Optional[str] = None


class TranscodedInfo(BaseModel):
    metadata: Optional[TranscodedMetadata] = None
    duration: Optional[float] = None
    fileSize: Optional[float] = None
    channels: Optional[Literal["stereo", "mono", 1, 2]] = None
    format: Optional[str] = None


class TranscodedAudio(BaseModel):
    transcodedSha256: str
    transcodedInfo: Optional[TranscodedInfo] = None
