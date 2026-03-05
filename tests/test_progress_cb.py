import threading
from yoto_up.yoto_api import YotoAPI
from yoto_up.models import Card, CardContent, Chapter, Track, DEFAULT_MEDIA_ID


def _api() -> YotoAPI:
    return YotoAPI.__new__(YotoAPI)


def make_card_one_track():
    t = Track(title="T1", trackUrl="yoto:#a", key="01", format="mp3", type="audio")
    ch = Chapter(title="C1", key="00", tracks=[t])
    card = Card(title="Card", content=CardContent(chapters=[ch]))
    card.get_chapters()[0].tracks[0].set_icon_field(DEFAULT_MEDIA_ID)
    # ensure chapter icon not default to avoid chapter being targeted
    card.get_chapters()[0].set_icon_field("yoto:#existing")
    return card


def test_progress_callback_debounced(monkeypatch):
    api = _api()
    card = make_card_one_track()

    # fake search returns single candidate
    monkeypatch.setattr(
        api,
        "find_best_icons_for_text",
        lambda *a, **k: [{"id": "y1", "img_url": "http://example/icon1.png"}],
    )

    # fake upload returns mediaId
    monkeypatch.setattr(
        api,
        "upload_yotoicons_icon_to_yoto_api",
        lambda cand: {"mediaId": "MID-y1"},
    )

    # Replace threading.Timer with a controllable fake that records instances
    fake_timers = []

    class FakeTimer:
        def __init__(self, interval, callback):
            self.interval = interval
            self.callback = callback
            self.cancelled = False
            fake_timers.append(self)

        def start(self):
            # no-op; we'll run manually
            return

        def cancel(self):
            self.cancelled = True

        def run(self):
            if not self.cancelled:
                self.callback()

    monkeypatch.setattr(threading, "Timer", FakeTimer)

    events = []

    def progress_cb(msg, frac):
        events.append((msg, frac))

    # Run replace; internal _cb will create FakeTimer instances instead of real timers
    res = api.replace_card_default_icons(card, parallel_workers=2, progress_callback=progress_cb)

    # At least one fake timer should have been created
    assert fake_timers, "No timer instances were created"

    # Earlier timers should be cancelled; only the last should run
    for t in fake_timers[:-1]:
        assert t.cancelled, "Earlier timer was not cancelled"

    # Trigger the last timer to simulate debounce expiry
    fake_timers[-1].run()

    # progress_cb should have been called once with a message (coalesced)
    assert len(events) == 1, f"Expected 1 progress event, got {len(events)}"
    msg, frac = events[0]
    assert msg is not None
    assert frac is not None
