from textual.app import App, ComposeResult
from textual.widgets import Input, Button, Static, OptionList, Label, ProgressBar
from textual.scroll_view import ScrollView
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets.option_list import Option
from textual.logging import TextualHandler
from rich.text import Text
import asyncio
import json
import re
from pathlib import Path
from yoto_up.paths import OFFICIAL_ICON_CACHE_DIR, YOTOICONS_CACHE_DIR
import hashlib
import logging
import tempfile
import urllib.request
from yoto_up.models import Card, CardContent
from yoto_up.icons import render_icon

logging.basicConfig(handlers=[TextualHandler()], level=logging.INFO)
logging.debug("TEST")


class ChapterIconWidget(Static):
    def __init__(self, api, chapter, icons_metadata, chapter_idx, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api = api
        self.chapter = chapter
        self.icons_metadata = icons_metadata
        self.chapter_idx = chapter_idx
        self.cache_path = self.get_cache_path()
        self.markup = True
        self.refresh_icon()

    def get_cache_path(self):
        icon_field = getattr(self.chapter.display, "icon16x16", None) if hasattr(self.chapter, "display") and self.chapter.display else None
        logging.info(f"Chapter {self.chapter_idx} icon field: {icon_field}")
        # Ask the API for the canonical cache path
        cache_path = None
        try:
            cache_path = self.api.get_icon_cache_path(icon_field)
        except Exception:
            cache_path = None
        # If not found, try refreshing user icons (which may populate the cache) and retry once
        if not cache_path:
            try:
                self.api.get_user_icons()
                cache_path = self.api.get_icon_cache_path(icon_field)
            except Exception:
                cache_path = None
        return cache_path

    def refresh_icon(self, new_icons_metadata=None):
        logging.info(f"Refreshing icon for chapter {self.chapter_idx}")
        if new_icons_metadata is not None:
            self.icons_metadata = new_icons_metadata
        self.cache_path = self.get_cache_path()
        logging.info(f"Chapter {self.chapter_idx} cache path: {self.cache_path}")
        icon_markup = None
        if self.cache_path and self.cache_path.exists():
            icon_markup = render_icon(self.cache_path)
        else:
            logging.info(f"Chapter {self.chapter_idx} icon cache path does not exist")
            logging.info(self.cache_path)
            icon_markup = "[red]Icon not found[/red]"
        self.update(icon_markup)

    def set_icon(self, media_id, icons_metadata=None):
        """
        Update the widget to show the icon for the given media_id.
        Optionally update icons_metadata.
        """
        logging.info(f"Setting icon for chapter {self.chapter_idx}: {media_id}")
        if icons_metadata is not None:
            self.icons_metadata = icons_metadata
        # Update chapter's display field
        if hasattr(self.chapter, "display") and self.chapter.display:
            self.chapter.display.icon16x16 = f"yoto:#{media_id}"
        self.cache_path = self.get_cache_path()
        self.refresh_icon()

class TrackIconWidget(Static):
    def __init__(self, api, track, icons_metadata, track_idx, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api = api
        self.track = track
        self.icons_metadata = icons_metadata
        self.track_idx = track_idx
        self.cache_path = self.get_cache_path()
        self.markup = True
        self.refresh_icon()

    def get_cache_path(self):
        icon_field = getattr(self.track.display, "icon16x16", None) if hasattr(self.track, "display") and self.track.display else None
        logging.info(f"Track {self.track_idx} icon field: {icon_field}")
        cache_path = None
        try:
            cache_path = self.api.get_icon_cache_path(icon_field)
        except Exception:
            cache_path = None
        if not cache_path:
            try:
                self.api.get_user_icons()
                cache_path = self.api.get_icon_cache_path(icon_field)
            except Exception:
                cache_path = None
        return cache_path

    def refresh_icon(self, new_icons_metadata=None):
        logging.info(f"Refreshing icon for track {self.track_idx}")
        if new_icons_metadata is not None:
            self.icons_metadata = new_icons_metadata
        self.cache_path = self.get_cache_path()
        icon_markup = None
        if self.cache_path and self.cache_path.exists():
            try:
                icon_markup = render_icon(self.cache_path)
            except Exception as e:
                icon_markup = f"[red]Error rendering icon: {e}[/red]"
        else:
            icon_markup = "[red]Icon not found[/red]"
        self.update(icon_markup)

    def set_icon(self, media_id, icons_metadata=None):
        logging.info(f"Setting icon for track {self.track_idx}: {media_id}")
        if icons_metadata is not None:
            self.icons_metadata = icons_metadata
        if hasattr(self.track, "display") and self.track.display:
            self.track.display.icon16x16 = f"yoto:#{media_id}"
        self.cache_path = self.get_cache_path()
        self.refresh_icon()

class EditCardContent(Static):
    def __init__(self, api, content: CardContent, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.card_content = content
        self.api = api

    def compose(self):
        def sanitize_id(s):
            return re.sub(r"[^a-zA-Z0-9_-]", "_", s)
        # Load icon cache and metadata once (use centralized paths)
        cache_dir = OFFICIAL_ICON_CACHE_DIR
        metadata_path = cache_dir / "icon_metadata.json"
        icons_metadata = None
        if metadata_path.exists():
            try:
                with metadata_path.open("r") as f:
                    icons_metadata = json.load(f)
            except Exception:
                icons_metadata = None
        # Only show editable fields for chapter title and overlayLabel
        if hasattr(self.card_content, "chapters"):
            for chapter_idx, chapter in enumerate(self.card_content.chapters):
                chapter_id = f"chapter[{chapter_idx}]"
                safe_chapter_id = sanitize_id(chapter_id)
                yield Static(
                    Text(f"Chapter {chapter_idx+1}", style="bold yellow"),
                    id=f"static_{safe_chapter_id}_header",
                    classes="centered-header colored-header"
                )
                # Use ChapterIconWidget for pixel art rendering
                yield ChapterIconWidget(self.api, chapter, icons_metadata, chapter_idx, id=f"icon_pixelart_{chapter_idx}")
                # Add icon search buttons: full search and local-only search
                yield Horizontal(
                    Button("Search Icon", id=f"search_icon_{safe_chapter_id}", classes="small-btn"),
                )
                # Editable title
                yield Static("Title:", id=f"label_{safe_chapter_id}_title")
                yield Input(value=str(getattr(chapter, "title", "")), placeholder="title", id=f"edit_{safe_chapter_id}_title")
                # Editable overlayLabel
                yield Static("Overlay Label:", id=f"label_{safe_chapter_id}_overlayLabel")
                yield Input(value=str(getattr(chapter, "overlayLabel", "")), placeholder="overlayLabel", id=f"edit_{safe_chapter_id}_overlayLabel")
                if hasattr(chapter, "tracks"):
                    for track_idx, track in enumerate(chapter.tracks):
                        track_id = f"track[{chapter_idx}][{track_idx}]"
                        safe_track_id = sanitize_id(track_id)
                        yield Static(f"  Track {track_idx+1}", id=f"static_{safe_track_id}_header")
                        yield TrackIconWidget(self.api, track, icons_metadata, track_idx, id=f"icon_pixelart_{safe_track_id}")
                        yield Horizontal(
                            Button("Search Icon", id=f"search_icon_{safe_track_id}", classes="small-btn"),
                            classes="button-row"
                        )
                        yield Static("Title:", id=f"label_{safe_track_id}_title")
                        yield Input(value=str(getattr(track, "title", "")), placeholder="title", id=f"edit_{safe_track_id}_title")
                        yield Static("Overlay Label:", id=f"label_{safe_track_id}_overlayLabel")
                        yield Input(value=str(getattr(track, "overlayLabel", "")), placeholder="overlayLabel", id=f"edit_{safe_track_id}_overlayLabel")
                        yield Static("Key:", id=f"label_{safe_track_id}_key")
                        yield Input(value=str(getattr(track, "key", "")), placeholder="key", id=f"edit_{safe_track_id}_key")
                        yield Static(f"Duration: {getattr(track, 'duration', '')}", id=f"static_{safe_track_id}_duration")

# Textual TUI for editing card details
class EditCardApp(App):
    CSS_PATH = "tui.css"
    def __init__(self, card, api, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api = api
        # Icon will fail if the card's chapters/tracks don't have display.icon16x16 fields populated
        self.card: Card = self.api.generate_card_chapter_and_track_icon_fields(card)
        self.result = None

    def compose(self) -> ComposeResult:
        #logger.debug("Editing card: {}", self.card.cardId)
        def sanitize_id(s):
            return re.sub(r"[^a-zA-Z0-9_-]", "_", s)
        # Editable fields: title, metadata.description, metadata.genre, metadata.tags
        card = self.card
        metadata = card.metadata if hasattr(card, "metadata") and card.metadata else None
        # Display card details nicely
        details = []
        details.append(Static(f"Editing Card: [blue]{card.cardId}[/blue]", id="header"))
        # Editable title
        details.append(Static("Title:", id="label_title"))
        details.append(Input(value=str(card.title), placeholder="title", id="edit_title"))
        # Editable metadata.description
        desc_val = str(metadata.description) if metadata and getattr(metadata, "description", None) else ""
        details.append(Static("Description:", id="label_metadata_description"))
        details.append(Input(value=desc_val, placeholder="description", id="edit_metadata_description"))
        # Editable metadata.genre (list of strings)
        genre_val = ", ".join(metadata.genre) if metadata and getattr(metadata, "genre", None) else ""
        details.append(Static("Genre:", id="label_metadata_genre"))
        details.append(Input(value=genre_val, placeholder="genre (comma separated)", id="edit_metadata_genre"))
        # Editable metadata.tags (list of strings)
        tags_val = ", ".join(metadata.tags) if metadata and getattr(metadata, "tags", None) else ""
        details.append(Static("Tags:", id="label_metadata_tags"))
        details.append(Input(value=tags_val, placeholder="tags (comma separated)", id="edit_metadata_tags"))
        # Display other card details as Static widgets
        details.append(Static(f"Card ID: {card.cardId}", id="static_cardid"))
        details.append(Static(f"Deleted: {card.deleted}", id="static_deleted"))
        details.append(Static(f"Created At: {card.createdAt}", id="static_createdat"))
        details.append(Static(f"Created By Client ID: {card.createdByClientId}", id="static_createdbyclientid"))
        if metadata:
            details.append(Static(f"Author: {metadata.author}", id="static_author"))
            details.append(Static(f"Category: {metadata.category}", id="static_category"))
            details.append(Static(f"Copyright: {metadata.copyright}", id="static_copyright"))
            details.append(Static(f"Accent: {metadata.accent}", id="static_accent"))
            details.append(Static(f"Status: {metadata.status.name if metadata.status else ''}", id="static_status"))
        # Main layout
        yield Vertical(
            ScrollView(
                Horizontal(
                    Vertical(*details, id="main-scroll"),
                    EditCardContent(self.api, card.content, id="card-content"),
                    id="main-horizontal"
                ),
            ),
            Horizontal(
                Button("Save", id="save", classes="small-btn"),
                Button("Cancel", id="cancel", classes="small-btn"),
                Button("Show JSON", id="show_json", classes="small-btn"),
                Button("Show Cover", id="show_cover", classes="small-btn"),
                Button("Autoselect Icons", id="autoselect_icons", classes="small-btn"),
                id="button-row"
            ),
            id="main-container"
        )

    async def on_button_pressed(self, event):
        # Handle per-chapter icon search button
        print(f"BUTTON PRESSED: {event.button.id}")
        if event.button.id and event.button.id.startswith("search_icon_"):
            # chapter search (matches ids like search_icon_chapter_<n>_)
            m = re.match(r"search_icon_chapter_(\d+)_", event.button.id)
            if m:
                chapter_idx = int(m.group(1))
                print(f"SEARCH CHAPTER {chapter_idx}")
                await self.action_search_icon(chapter_idx)
                return
            # Attempt to match track search button ids of the form
            # search_icon_track_<chapter>_<track>_
            m2 = re.match(r"search_icon_track_(\d+)_(\d+)_", event.button.id) or re.match(r"search_icon_track_(\d+)__(\d+)_", event.button.id)
            if m2:
                chapter_idx = int(m2.group(1))
                track_idx = int(m2.group(2))
                print(f"SEARCH TRACK chapter={chapter_idx} track={track_idx}")
                await self.action_search_icon_for_track(chapter_idx, track_idx)
                return
        if event.button.id == "save":
            # Update only editable fields
            card = self.card
            metadata = card.metadata if hasattr(card, "metadata") and card.metadata else None
            # Title
            input_title = self.query_one("#edit_title", Input).value
            card.title = input_title
            # Metadata.description
            input_desc = self.query_one("#edit_metadata_description", Input).value
            if metadata:
                metadata.description = input_desc
            # Metadata.genre (comma separated)
            input_genre = self.query_one("#edit_metadata_genre", Input).value
            if metadata:
                metadata.genre = [g.strip() for g in input_genre.split(",") if g.strip()]
            # Metadata.tags (comma separated)
            input_tags = self.query_one("#edit_metadata_tags", Input).value
            if metadata:
                metadata.tags = [t.strip() for t in input_tags.split(",") if t.strip()]
            self.result = self.api.update_card(card)
            await self.action_quit()
        elif event.button.id == "cancel":
            await self.action_quit()
        elif event.button.id == "show_json":
            # Show full card model as JSON in a modal overlay
            class CardJsonModal(ModalScreen):
                def compose(self):
                    card_json = json.dumps(self.app.card, default=lambda o: o.__dict__, indent=2)
                    yield Label("Card Model JSON Export", id="json_export_label")
                    # Use a Vertical container to ensure layout, and force Static to fill ScrollView
                    yield Vertical(
                        Static(card_json, markup=True, id="json_export", classes="json-static"),
                        Button("Close", id="close_json", classes="small-btn"),
                        id="json_modal_container"
                    )
                async def on_button_pressed(self, event):
                    if event.button.id == "close_json":
                        self.dismiss()
            await self.push_screen(CardJsonModal())
        elif event.button.id == "show_cover":
            # Render the card cover image (if present) in a modal using braille renderer
            cover_url = None
            try:
                metadata = self.card.metadata if hasattr(self.card, 'metadata') and self.card.metadata else None
                if metadata and metadata.cover and getattr(metadata.cover, 'imageL', None):
                    cover_url = metadata.cover.imageL
            except Exception:
                cover_url = None

            class CoverModal(ModalScreen):
                def __init__(self, cover_url):
                    super().__init__()
                    self.cover_url = cover_url
                    self.temp_path = None

                def compose(self):
                    # placeholder while loading
                    yield Vertical(
                        Label("Loading cover image...", id="cover_loading_label"),
                        id="cover_modal_container"
                    )

                async def on_mount(self):
                    # Download or resolve local path and render
                    art = "[red]No cover available[/red]"
                    try:
                        if not self.cover_url:
                            art = "[red]No cover available[/red]"
                        else:
                            # If cover_url looks like a file path, try to use it directly
                            if self.cover_url.startswith("file://"):
                                p = Path(self.cover_url[len("file://"):])
                                if p.exists():
                                    art = render_icon(p, method='braille', braille_dims=(24, 12))
                            elif self.cover_url.startswith("http://") or self.cover_url.startswith("https://"):
                                # download to temp file
                                tf = tempfile.NamedTemporaryFile(prefix="yoto_cover_", suffix=Path(self.cover_url).suffix or ".png", delete=False)
                                try:
                                    urllib.request.urlretrieve(self.cover_url, tf.name)
                                    self.temp_path = Path(tf.name)
                                    art = render_icon(self.temp_path, method='braille', braille_dims=(24, 12))
                                finally:
                                    tf.close()
                            else:
                                # treat as local path
                                p = Path(self.cover_url)
                                if p.exists():
                                    art = render_icon(p, method='braille', braille_dims=(24, 12))
                                else:
                                    art = f"[red]Cover path not found: {self.cover_url}[/red]"
                    except Exception as e:
                        art = f"[red]Error rendering cover: {e}[/red]"

                    # Replace modal content with rendered art and close button
                    self.dismiss()
                    # Push a simple modal showing the art
                    class CoverDisplayModal(ModalScreen):
                        def compose(self):
                            yield Vertical(
                                Static(art, markup=True),
                                Button("Close", id="close_cover", classes="small-btn"),
                                id="cover_display_container"
                            )
                        async def on_button_pressed(self, event):
                            if event.button.id == "close_cover":
                                self.dismiss()

                    await self.app.push_screen(CoverDisplayModal())

            await self.push_screen(CoverModal(cover_url))
        elif event.button.id == "autoselect_icons":
            # Show loading modal
            class LoadingModal(ModalScreen):
                def compose(self):
                    yield Vertical(
                        Label("Autoselecting icons... Please wait, this may take some time.", id="loading_label", classes="centered-label"),
                        id="loading_modal_container",
                        classes="centered-modal"
                    )
            loading_modal = LoadingModal()
            await self.push_screen(loading_modal)
            # Run icon replacement in background
            def do_autoselect():
                self.card = self.api.replace_card_default_icons(self.card)
                card_content_widget = self.query_one("#card-content", EditCardContent)
                if hasattr(self.card.content, "chapters") and self.card.content.chapters:
                    for idx, chapter in enumerate(self.card.content.chapters):
                        pixelart_id = f"icon_pixelart_{idx}"
                        try:
                            pixelart_widget = card_content_widget.query_one(f"#{pixelart_id}")
                            pixelart_widget.refresh_icon()
                        except Exception:
                            pass
                self.refresh()
            # Run in executor to avoid blocking UI
            await asyncio.get_event_loop().run_in_executor(None, do_autoselect)
            # Dismiss loading modal
            loading_modal.dismiss()

    async def action_search_icon(self, chapter_idx):
        """
        Called when user clicks 'Search Icon' for a chapter. Prompts for search text, shows icon choices, lets user select.
        """
        chapter = self.card.content.chapters[chapter_idx]
        # Use chapter title as default search text
        search_text = getattr(chapter, "title", "")

        # Use shared modal helper (implemented as a separate method)
        # Build chapter-specific on_selected handler and call the helper.

        # Expose a simple chapter-specific on_selected
        def on_selected_for_chapter(selected_icon):
            if not selected_icon:
                return
            logging.info(f"SELECTED ICON: {selected_icon}")
            chapter = self.card.content.chapters[chapter_idx]
            pixelart_id = f"icon_pixelart_{chapter_idx}"
            card_content_widget = self.query_one("#card-content", EditCardContent)
            try:
                pixelart_widget = card_content_widget.query_one(f"#{pixelart_id}")
            except Exception:
                pixelart_widget = None
            if isinstance(selected_icon, dict) and "img_url" in selected_icon and "mediaId" not in selected_icon:
                try:
                    uploaded_icon = self.api.upload_yotoicons_icon_to_yoto_api(selected_icon)
                    media_id = uploaded_icon.get("mediaId")
                    if media_id:
                        if pixelart_widget:
                            pixelart_widget.set_icon(media_id)
                        if hasattr(chapter, "tracks") and chapter.tracks:
                            if hasattr(chapter.tracks[0], "display") and chapter.tracks[0].display:
                                chapter.tracks[0].display.icon16x16 = f"yoto:#{media_id}"
                        logging.info(f"YotoIcons icon uploaded and set: {media_id}")
                except Exception as e:
                    logging.error(f"Failed to upload YotoIcons icon: {e}")
                    return
            elif isinstance(selected_icon, dict) and "mediaId" in selected_icon:
                if pixelart_widget:
                    try:
                        pixelart_widget.set_icon(selected_icon['mediaId'])
                    except Exception:
                        logging.exception("Failed to set chapter pixelart widget icon")
                if hasattr(chapter, "tracks") and chapter.tracks:
                    if hasattr(chapter.tracks[0], "display") and chapter.tracks[0].display:
                        chapter.tracks[0].display.icon16x16 = f"yoto:#{selected_icon['mediaId']}"
            elif isinstance(selected_icon, dict) and "id" in selected_icon:
                if pixelart_widget:
                    try:
                        pixelart_widget.set_icon(selected_icon['id'])
                    except Exception:
                        logging.exception("Failed to set chapter pixelart widget icon")
                if hasattr(chapter, "tracks") and chapter.tracks:
                    if hasattr(chapter.tracks[0], "display") and chapter.tracks[0].display:
                        chapter.tracks[0].display.icon16x16 = f"yoto:#{selected_icon['id']}"
            self.refresh()
            # If selected_icon refers to a cached file path, display it directly and set model to file://
            if isinstance(selected_icon, dict) and 'cache_path' in selected_icon:
                try:
                    cp = Path(selected_icon['cache_path'])
                    if pixelart_widget:
                        try:
                            pixel_art = render_icon(cp)
                            pixelart_widget.update(pixel_art)
                        except Exception:
                            logging.exception("Failed to render cached icon for chapter pixelart widget")
                        try:
                            pixelart_widget.cache_path = cp
                        except Exception:
                            pass
                    if hasattr(chapter, 'tracks') and chapter.tracks:
                        if hasattr(chapter.tracks[0], 'display') and chapter.tracks[0].display:
                            chapter.tracks[0].display.icon16x16 = f"file://{cp}"
                except Exception:
                    logging.exception("Failed to apply cached icon for chapter")
        self.refresh()
        await self._show_icon_modal(search_text, on_selected_for_chapter)

    async def _show_icon_modal(self, query_string, on_selected):
        """Shared modal flow: shows search -> select modal and calls on_selected(payload).
        """
        logging.info(f"Icon search initiated with query: '{query_string}'")
        # Add a progress bar to indicate search progress
        class IconSearchModal(ModalScreen):
            def compose(self):
                yield Vertical(
                    Label("Searching for icons...", id="search_label"),
                    ProgressBar(total=100, id="search_progress"),
                    id="search_modal_container"
                )

        search_modal = IconSearchModal()
        await self.push_screen(search_modal)

        # Simulate search progress
        progress_bar = search_modal.query_one("#search_progress", ProgressBar)
        for i in range(1, 101):
            progress_bar.advance(1)
            await asyncio.sleep(0.05)  # Simulate search delay

        # Build icons list by first trying cached metadata, else fall back to API
        icons = []
        logging.info("Attempting to use cached icon metadata for fast search")
        try:
            # Look for metadata files in both cache directories
            candidate_meta_files = []
            for cache_dir in (OFFICIAL_ICON_CACHE_DIR, YOTOICONS_CACHE_DIR):
                if cache_dir and cache_dir.exists():
                    for name in ("icon_metadata.json", "user_icon_metadata.json"):
                        p = cache_dir / name
                        if p.exists():
                            candidate_meta_files.append(p)
            # Load and aggregate metadata
            aggregated = []
            for mpath in candidate_meta_files:
                try:
                    with mpath.open('r') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            aggregated.extend(data)
                except Exception:
                    logging.exception(f"Failed to load icon metadata: {mpath}")
            # If we have metadata, filter by query_string
            if aggregated:
                q = (query_string or "").strip().lower()
                if q:
                    matches = []
                    for icon in aggregated:
                        hay = " ".join(
                            filter(None, (
                                str(icon.get('title', '')),
                                " ".join(icon.get('publicTags', [])) if isinstance(icon.get('publicTags'), list) else str(icon.get('publicTags', '')),
                                str(icon.get('category', '')),
                                str(icon.get('displayIconId', '')),
                                str(icon.get('id', '')),
                            ))
                        ).lower()
                        if q in hay:
                            matches.append(icon)
                    if matches:
                        icons = matches
            # If no local matches, fall back to API search
            if not icons:
                try:
                    icons = self.api.find_best_icons_for_text(query_string, show_in_console=False)
                except Exception:
                    logging.exception("API icon search failed")
                    icons = []
        except Exception:
            logging.exception("Cached metadata search failed, falling back to API")
            try:
                icons = self.api.find_best_icons_for_text(query_string, show_in_console=False)
            except Exception:
                logging.exception("API icon search failed")
                icons = []
        search_modal.dismiss()

        class IconSelectModal(ModalScreen):
            AUTO_FOCUS = None
            def __init__(self, icons, query_string):
                super().__init__()
                self.icons = icons
                self.query_string = query_string
            def compose(self):
                opts = []
                for i, icon in enumerate(self.icons):
                    cache_path = None
                    if "url" in icon:
                        url_hash = hashlib.sha256(icon["url"].encode()).hexdigest()[:16]
                        ext = Path(icon["url"]).suffix or ".png"
                        cache_path = OFFICIAL_ICON_CACHE_DIR / f"{url_hash}{ext}"
                    elif "img_url" in icon:
                        url_hash = hashlib.sha256(icon["img_url"].encode()).hexdigest()[:16]
                        ext = Path(icon["img_url"]).suffix or ".png"
                        cache_path = YOTOICONS_CACHE_DIR / f"{url_hash}{ext}"
                    elif "cache_path" in icon:
                        cache_path = Path(icon["cache_path"])
                    if cache_path and cache_path.exists():
                        pixel_art = render_icon(cache_path)
                    else:
                        pixel_art = "[red]No image[/red]"
                    label_text = f"[b]{icon.get('title', icon.get('category', icon.get('id', 'Icon')))}[/b]\n{pixel_art}"
                    opts.append(Option(label_text, i))
                yield Vertical(
                    Label("Select an icon:", id="icon_select_label"),
                    Horizontal(
                        Input(
                            value=self.query_string,
                            placeholder="Search icons...",
                            id="icon_search_input"
                        ),
                        Button("Search", id="search_icon_query", classes="small-btn"),
                        Button("Cancel", id="cancel_icon_select", classes="small-btn"),
                        id="icon_modal_controls"
                    ),
                    OptionList(*opts, id="icon_option_list"),
                )

            async def on_input_submitted(self, event):
                if event.input.id == "icon_search_input":
                    new_query = event.value.strip()
                    if new_query:
                        self.dismiss({"search_query": new_query})
            async def on_button_pressed(self, event):
                if event.button.id == "cancel_icon_select":
                    self.dismiss(None)
                elif event.button.id == "search_icon_query":
                    input_widget = self.query_one("#icon_search_input", Input)
                    new_query = input_widget.value.strip()
                    if new_query:
                        self.dismiss({"search_query": new_query})
            async def on_option_list_option_selected(self, event):
                logging.info(f"IconSelectModal: option selected idx={event.option_id}")
                selected_idx = event.option_id
                selected_icon = self.icons[selected_idx]
                try:
                    on_selected(selected_icon)
                except Exception:
                    logging.exception("on_selected callback raised")
                self.dismiss(selected_icon)

        def handle_icon_selected(selected_icon):
            if not selected_icon:
                return
            if isinstance(selected_icon, dict) and "search_query" in selected_icon:
                # User requested a new search
                asyncio.create_task(self._show_icon_modal(selected_icon["search_query"], on_selected))
                return
            try:
                on_selected(selected_icon)
            except Exception:
                logging.exception("on_selected handler failed")

        await self.push_screen(IconSelectModal(icons, query_string), handle_icon_selected)

    async def action_search_icon_for_track(self, chapter_idx, track_idx):
        """
        Search icons for a specific track and apply selection to the TrackIconWidget.
        """
        try:
            chapter = self.card.content.chapters[chapter_idx]
            track = chapter.tracks[track_idx]
        except Exception:
            return
        search_text = getattr(track, "title", "")

        def on_selected_for_track(selected_icon):
            if not selected_icon:
                return
            logging.info(f"SELECTED ICON FOR TRACK: {selected_icon}")
            safe_track_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"track[{chapter_idx}][{track_idx}]")
            pixelart_id = f"icon_pixelart_{safe_track_id}"
            card_content_widget = self.query_one("#card-content", EditCardContent)
            try:
                pixelart_widget = card_content_widget.query_one(f"#{pixelart_id}")
            except Exception:
                pixelart_widget = None
            if isinstance(selected_icon, dict) and "img_url" in selected_icon and "mediaId" not in selected_icon:
                try:
                    uploaded_icon = self.api.upload_yotoicons_icon_to_yoto_api(selected_icon)
                    media_id = uploaded_icon.get("mediaId")
                    if media_id:
                        if pixelart_widget:
                            pixelart_widget.set_icon(media_id)
                        if hasattr(track, "display") and track.display:
                            track.display.icon16x16 = f"yoto:#{media_id}"
                        logging.info(f"YotoIcons icon uploaded and set for track: {media_id}")
                except Exception as e:
                    logging.error(f"Failed to upload YotoIcons icon: {e}")
                    return
            elif isinstance(selected_icon, dict) and "mediaId" in selected_icon:
                if pixelart_widget:
                    try:
                        pixelart_widget.set_icon(selected_icon['mediaId'])
                    except Exception:
                        logging.exception("Failed to set track pixelart widget icon")
                if hasattr(track, "display") and track.display:
                    track.display.icon16x16 = f"yoto:#{selected_icon['mediaId']}"
            elif isinstance(selected_icon, dict) and "id" in selected_icon:
                if pixelart_widget:
                    try:
                        pixelart_widget.set_icon(selected_icon['id'])
                    except Exception:
                        logging.exception("Failed to set track pixelart widget icon")
                if hasattr(track, "display") and track.display:
                    track.display.icon16x16 = f"yoto:#{selected_icon['id']}"
            self.refresh()

            # If selected_icon refers to a cached file path, display it directly and set model to file://
            if isinstance(selected_icon, dict) and 'cache_path' in selected_icon:
                cp = None
                try:
                    cp = Path(selected_icon['cache_path'])
                    if pixelart_widget:
                        try:
                            pixel_art = render_icon(cp)
                            pixelart_widget.update(pixel_art)
                        except Exception:
                            logging.exception("Failed to render cached icon for track pixelart widget")
                        try:
                            pixelart_widget.cache_path = cp
                        except Exception:
                            pass
                    if hasattr(track, 'display') and track.display and cp is not None:
                        track.display.icon16x16 = f"file://{cp}"
                    self.refresh()
                    return
                except Exception:
                    logging.exception("Failed to apply cached icon for track")

        # Reuse the same modal flow; the helper will call our on_selected_for_track
        await self._show_icon_modal(search_text, on_selected_for_track)
