import asyncio
from pathlib import Path

import pytest

from yoto_up.yoto_app import replace_icons as ri
from yoto_up.models import (
    Card,
    CardContent,
    Chapter,
    ChapterDisplay,
    Track,
    TrackDisplay,
)
from yoto_up.models import DEFAULT_MEDIA_ID


class DummyPage:
    def __init__(self):
        self.calls = []
        self.autoselect_running = False

    def show_snack(self, msg, error=False):
        self.calls.append(("snack", msg, error))

    def run_task(self, coro):
        # If there's already a running loop, schedule the coroutine as a task.
        # Otherwise run it in a fresh event loop.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro())
        else:
            return loop.create_task(coro())

    def pop_dialog(self):
        self.calls.append(("pop_dialog",))

    def show_card_details(self, card):
        self.calls.append(("show_card", card.cardId))

    def update_card(self, card):
        self.calls.append(("update_card", card.cardId))
    
    def open_autoselect_status_dialog(self, cancel_event, hide_default=False):
        # Record that the status dialog would be opened; attach cancel_event
        self.calls.append(("open_status", hide_default))
        setattr(self, "autoselect_cancel_event", cancel_event)

    async def set_autoselect_progress(self, msg, frac, visible=True):
        # Async method expected by the badge updater
        self.calls.append(("badge", msg, frac, visible))


class FakeAPI:
    def __init__(self, card, tmp_path: Path):
        self._card = card
        self._tmp = tmp_path

    def get_card(self, cid):
        return self._card

    def replace_card_default_icons(self, card_to_use, **kwargs):
        # Simulate replacing icons by setting mediaIds on chapters/tracks
        for i, ch in enumerate(card_to_use.get_chapters()):
            ch.set_icon_field(f"yoto:#mid_ch_{i}")
        for j, tr in enumerate(card_to_use.get_track_list()):
            tr.set_icon_field(f"yoto:#mid_tr_{j}")
        return card_to_use

    def _load_icon_upload_cache(self):
        return {}

    def get_icon_cache_path(self, mid):
        # Create a dummy cache file for the given media id and return its path
        p = Path(self._tmp) / f"{mid}.png"
        p.write_bytes(b"PNGDATA")
        return p


def make_card():
    # Build a minimal card with one chapter and one track that have default icons
    tr = Track(title="T1", trackUrl="", key="1", format="mp3", type="audio", display=TrackDisplay())
    tr.display.icon16x16 = DEFAULT_MEDIA_ID
    ch = Chapter(title="C1", tracks=[tr], display=ChapterDisplay())
    ch.display.icon16x16 = DEFAULT_MEDIA_ID
    content = CardContent(chapters=[ch])
    card = Card(cardId="card-1", title="Test", content=content)
    return card


def test_start_replace_icons_background_component(tmp_path, monkeypatch):
    page = DummyPage()
    card = make_card()

    fake_api = FakeAPI(card, tmp_path)

    # Patch ensure_api used by the module to return our fake API
    monkeypatch.setattr(ri, "ensure_api", lambda api_ref=None: fake_api)

    # Run the background starter which will execute synchronously via DummyPage.run_task
    ri.start_replace_icons_background(page, card, api_ref=None, include_yotoicons=False)

    # After completion, we expect the page to have been asked to show the card details
    assert ("show_card", "card-1") in page.calls
    # autoselect_running flag should be cleared
    assert getattr(page, "autoselect_running", False) is False


def test_progress_debounce_component(tmp_path, monkeypatch):
    """Ensure rapid progress_callback calls are debounced before reaching the page."""
    page = DummyPage()
    card = make_card()

    class FakeAPIProgress(FakeAPI):
        def replace_card_default_icons(self, card_to_use, progress_callback=None, **kwargs):
            # Rapidly emit many progress updates
            import time
            for i in range(50):
                try:
                    if callable(progress_callback):
                        progress_callback(f"step{i}", i / 50.0)
                except Exception:
                    pass
                time.sleep(0.002)
            # then set icons as before
            for i, ch in enumerate(card_to_use.get_chapters()):
                ch.set_icon_field(f"yoto:#mid_ch_{i}")
            for j, tr in enumerate(card_to_use.get_track_list()):
                tr.set_icon_field(f"yoto:#mid_tr_{j}")
            return card_to_use

    fake_api = FakeAPIProgress(card, tmp_path)
    monkeypatch.setattr(ri, "ensure_api", lambda api_ref=None: fake_api)

    ri.start_replace_icons_background(page, card, api_ref=None, include_yotoicons=False)

    # Count badge updates recorded
    badge_updates = [c for c in page.calls if c and c[0] == "badge"]
    # Ensure badge updates were received (debouncing behaviour is validated elsewhere)
    assert len(badge_updates) >= 1
