from asyncio.log import logger
from typing import Optional, List, Literal
from pydantic import BaseModel
from yoto_up.icons import render_icon

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

class CardStatus(BaseModel):
    name: Literal["new", "inprogress", "complete", "live", "archived"]
    updatedAt: Optional[str] = None

class CardCover(BaseModel):
    imageL: Optional[str] = None

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
                header_lines.append(f"[green]Genre:[/] {', '.join(self.metadata.genre)}")
        except Exception:
            pass
        try:
            if self.metadata and getattr(self.metadata, 'languages', None):
                header_lines.append(f"[green]Languages:[/] {', '.join(self.metadata.languages)}")
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
                        icon_field = getattr(chapter.display, 'icon16x16', None) if hasattr(chapter, 'display') and chapter.display else None
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
                                t_icon_field = getattr(track.display, 'icon16x16', None) if hasattr(track, 'display') and track.display else None
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