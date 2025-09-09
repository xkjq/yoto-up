from textual.app import App, ComposeResult
from textual.widgets import Input, Button, Static, OptionList, Label
from textual.scroll_view import ScrollView
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets.option_list import Option
from textual.logging import TextualHandler
import asyncio
import json
import re
from pathlib import Path
import hashlib
import logging
from models import Card, CardContent
from icons import render_icon

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
            try:
                from icons import render_icon
                icon_markup = render_icon(self.cache_path)
            except Exception as e:
                icon_markup = f"[red]Error rendering icon: {e}[/red]"
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
                from icons import render_icon
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
        # Load icon cache and metadata once
        cache_dir = Path(".yoto_icon_cache")
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
                yield Static(f"Chapter {chapter_idx+1}", id=f"static_{safe_chapter_id}_header")
                # Use ChapterIconWidget for pixel art rendering
                yield ChapterIconWidget(self.api, chapter, icons_metadata, chapter_idx, id=f"icon_pixelart_{chapter_idx}")
                # Add icon search button
                print(f"SAFE CHAPTER ID: {safe_chapter_id}")
                yield Button("Search Icon", id=f"search_icon_{safe_chapter_id}", classes="small-btn")
                # Editable title
                yield Input(value=str(getattr(chapter, "title", "")), placeholder="title", id=f"edit_{safe_chapter_id}_title")
                # Editable overlayLabel
                yield Input(value=str(getattr(chapter, "overlayLabel", "")), placeholder="overlayLabel", id=f"edit_{safe_chapter_id}_overlayLabel")
                if hasattr(chapter, "tracks"):
                    for track_idx, track in enumerate(chapter.tracks):
                        track_id = f"track[{chapter_idx}][{track_idx}]"
                        safe_track_id = sanitize_id(track_id)
                        yield Static(f"  Track {track_idx+1}", id=f"static_{safe_track_id}_header")
                        yield TrackIconWidget(self.api, track, icons_metadata, track_idx, id=f"icon_pixelart_{safe_track_id}")
                        yield Button("Search Icon", id=f"search_icon_{safe_track_id}", classes="small-btn")
                        yield Input(value=str(getattr(track, "title", "")), placeholder="title", id=f"edit_{safe_track_id}_title")
                        yield Input(value=str(getattr(track, "duration", "")), placeholder="duration", id=f"edit_{safe_track_id}_duration")

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
        details.append(Static(f"Editing Card: {card.cardId}", id="header"))
        # Editable title
        details.append(Input(value=str(card.title), placeholder="title", id="edit_title"))
        # Editable metadata.description
        desc_val = str(metadata.description) if metadata and getattr(metadata, "description", None) else ""
        details.append(Input(value=desc_val, placeholder="description", id="edit_metadata_description"))
        # Editable metadata.genre (list of strings)
        genre_val = ", ".join(metadata.genre) if metadata and getattr(metadata, "genre", None) else ""
        details.append(Input(value=genre_val, placeholder="genre (comma separated)", id="edit_metadata_genre"))
        # Editable metadata.tags (list of strings)
        tags_val = ", ".join(metadata.tags) if metadata and getattr(metadata, "tags", None) else ""
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
            if metadata.cover and metadata.cover.imageL:
                details.append(Static(f"Cover Image: {metadata.cover.imageL}", id="static_coverimage"))
            if metadata.media:
                details.append(Static(f"Duration: {metadata.media.duration}", id="static_duration"))
                details.append(Static(f"File Size: {metadata.media.fileSize}", id="static_filesize"))
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
                Button("Autoselect Icons", id="autoselect_icons", classes="small-btn"),
                id="button-row"
            ),
            id="main-container"
        )

    async def on_button_pressed(self, event):
        # Handle per-chapter icon search button
        print(f"BUTTON PRESSED: {event.button.id}")
        if event.button.id and event.button.id.startswith("search_icon_"):
            m = re.match(r"search_icon_chapter_(\d+)_", event.button.id)
            if m:
                chapter_idx = int(m.group(1))
                print(f"SEARCH CHAPTER {chapter_idx}")
                await self.action_search_icon(chapter_idx)
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
        print("SEARCH CHAPTER ICON")
        # Use chapter title as default search text
        search_text = getattr(chapter, "title", "")

        async def show_icon_modal(query_string):
            logging.info(f"Icon search initiated for chapter {chapter_idx} with query: '{query_string}'")
            icons = self.api.find_best_icons_for_text(query_string, show_in_console=False)
            class IconSelectModal(ModalScreen):
                AUTO_FOCUS = None
                def __init__(self, icons, chapter_idx, query_string):
                    super().__init__()
                    self.icons = icons
                    self.chapter_idx = chapter_idx
                    self.query_string = query_string
                def compose(self):
                    opts = []
                    for i, icon in enumerate(self.icons):
                        cache_path = None
                        if "url" in icon:
                            url_hash = hashlib.sha256(icon["url"].encode()).hexdigest()[:16]
                            ext = Path(icon["url"]).suffix or ".png"
                            cache_path = Path(".yoto_icon_cache") / f"{url_hash}{ext}"
                        elif "img_url" in icon:
                            url_hash = hashlib.sha256(icon["img_url"].encode()).hexdigest()[:16]
                            ext = Path(icon["img_url"]).suffix or ".png"
                            cache_path = Path(".yotoicons_cache") / f"{url_hash}{ext}"
                        elif "cache_path" in icon:
                            cache_path = Path(icon["cache_path"])
                        if cache_path and cache_path.exists():
                            pixel_art = render_icon(cache_path)
                        else:
                            pixel_art = "[red]No image[/red]"
                        label_text = f"[b]{icon.get('title', icon.get('category', icon.get('id', 'Icon')))}[/b]\n{pixel_art}"
                        opts.append(Option(label_text, i))
                    yield Vertical(
                        Label("Select an icon for this chapter:", id="icon_select_label"),
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
                    # If the submitted input is the search box, trigger the search
                    if event.input.id == "icon_search_input":
                        new_query = event.value.strip()
                        if new_query:
                            self.dismiss({"search_query": new_query})
                async def on_button_pressed(self, event):
                    if event.button.id == "cancel_icon_select":
                        self.dismiss(None)
                    elif event.button.id == "search_icon_query":
                        # Get new query from input and rerun search
                        input_widget = self.query_one("#icon_search_input", Input)
                        new_query = input_widget.value.strip()
                        if new_query:
                            self.dismiss({"search_query": new_query})
                async def on_option_list_option_selected(self, event):
                    logging.info(f"IconSelectModal: option selected idx={event.option_id}")
                    selected_idx = event.option_id
                    selected_icon = self.icons[selected_idx]
                    self.dismiss(selected_icon)

            def handle_icon_selected(selected_icon):
                if not selected_icon:
                    return
                if isinstance(selected_icon, dict) and "search_query" in selected_icon:
                    # User requested a new search
                    asyncio.create_task(show_icon_modal(selected_icon["search_query"]))
                    return
                logging.info(f"SELECTED ICON: {selected_icon}")
                chapter = self.card.content.chapters[chapter_idx]
                pixelart_id = f"icon_pixelart_{chapter_idx}"
                card_content_widget = self.query_one("#card-content", EditCardContent)
                pixelart_widget = card_content_widget.query_one(f"#{pixelart_id}")
                if "img_url" in selected_icon and "mediaId" not in selected_icon:
                    try:
                        uploaded_icon = self.api.upload_yotoicons_icon_to_yoto_api(selected_icon)
                        media_id = uploaded_icon.get("mediaId")
                        if media_id:
                            pixelart_widget.set_icon(media_id)
                            if hasattr(chapter, "tracks") and chapter.tracks:
                                if hasattr(chapter.tracks[0], "display") and chapter.tracks[0].display:
                                    chapter.tracks[0].display.icon16x16 = f"yoto:#{media_id}"
                            logging.info(f"YotoIcons icon uploaded and set: {media_id}")
                    except Exception as e:
                        logging.error(f"Failed to upload YotoIcons icon: {e}")
                        return
                elif "mediaId" in selected_icon:
                    pixelart_widget.set_icon(selected_icon['mediaId'])
                    if hasattr(chapter, "tracks") and chapter.tracks:
                        if hasattr(chapter.tracks[0], "display") and chapter.tracks[0].display:
                            chapter.tracks[0].display.icon16x16 = f"yoto:#{selected_icon['mediaId']}"
                elif "id" in selected_icon:
                    pixelart_widget.set_icon(selected_icon['id'])
                    if hasattr(chapter, "tracks") and chapter.tracks:
                        if hasattr(chapter.tracks[0], "display") and chapter.tracks[0].display:
                            chapter.tracks[0].display.icon16x16 = f"yoto:#{selected_icon['id']}"
                self.refresh()
            await self.push_screen(IconSelectModal(icons, chapter_idx, query_string), handle_icon_selected)

        await show_icon_modal(search_text)
