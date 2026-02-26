from yoto_up.yoto_api import YotoAPI
from yoto_up.models import Card, TranscodedAudio


def _api() -> YotoAPI:
    return YotoAPI.__new__(YotoAPI)


def test_make_cache_key_is_stable_for_equivalent_payloads():
    api = _api()
    key_a = api._make_cache_key(
        "GET",
        "https://example.test",
        params={"b": 2, "a": 1},
        json_data={"z": [3, 2, 1], "x": {"k2": "v2", "k1": "v1"}},
    )
    key_b = api._make_cache_key(
        "GET",
        "https://example.test",
        params={"a": 1, "b": 2},
        json_data={"x": {"k1": "v1", "k2": "v2"}, "z": [3, 2, 1]},
    )
    assert key_a == key_b


def test_get_track_from_transcoded_audio_defaults():
    api = _api()
    transcoded = TranscodedAudio.model_validate({"transcodedSha256": "abc123"})

    track = api.get_track_from_transcoded_audio(transcoded)

    assert track is not None
    assert track.title == "Unknown Track"
    assert track.trackUrl == "yoto:#abc123"
    assert track.format == "mp3"
    assert track.type == "audio"


def test_get_track_from_transcoded_audio_applies_overrides():
    api = _api()
    transcoded = TranscodedAudio.model_validate(
        {
            "transcodedSha256": "sha-1",
            "transcodedInfo": {
                "metadata": {"title": "From Metadata"},
                "duration": 12.5,
                "fileSize": 512,
                "channels": "stereo",
                "format": "aac",
            },
        }
    )

    track = api.get_track_from_transcoded_audio(
        transcoded,
        track_details={"title": "Override", "key": "09", "overlayLabel": "9"},
    )

    assert track is not None
    assert track.title == "Override"
    assert track.key == "09"
    assert track.overlayLabel == "9"
    assert track.trackUrl == "yoto:#sha-1"
    assert track.format == "aac"


def test_get_chapter_from_transcoded_audio_uses_model_and_overrides():
    api = _api()
    transcoded = TranscodedAudio.model_validate(
        {
            "transcodedSha256": "sha-2",
            "transcodedInfo": {
                "metadata": {"title": "Chapter Metadata"},
                "duration": 33.0,
                "fileSize": 2048,
                "channels": "mono",
                "format": "mp3",
            },
        }
    )

    chapter = api.get_chapter_from_transcoded_audio(
        transcoded,
        track_details={"title": "Track Override"},
        chapter_details={"title": "Chapter Override", "key": "02"},
    )

    assert chapter is not None
    assert chapter.title == "Chapter Override"
    assert chapter.key == "02"
    assert chapter.tracks[0].title == "Track Override"
    assert chapter.tracks[0].trackUrl == "yoto:#sha-2"


def test_create_card_from_transcoded_audio_builds_card_and_calls_create(monkeypatch):
    api = _api()
    transcoded = TranscodedAudio.model_validate(
        {
            "transcodedSha256": "sha-3",
            "transcodedInfo": {
                "metadata": {"title": "Meta Title"},
                "duration": 44.0,
                "fileSize": 4096,
                "format": "mp3",
            },
        }
    )

    captured: dict[str, Card] = {}

    def _fake_create(card: Card):
        captured["card"] = card
        return card

    monkeypatch.setattr(api, "create_or_update_content", _fake_create)

    result = api.create_card_from_transcoded_audio("Card Title", transcoded)

    assert isinstance(result, Card)
    assert "card" in captured
    assert captured["card"].title == "Card Title"
    assert captured["card"].content is not None
    assert captured["card"].content.chapters is not None
    assert captured["card"].content.chapters[0].tracks[0].trackUrl == "yoto:#sha-3"


def test_upload_audio_to_card_validates_transcoded_audio_before_delegating(monkeypatch):
    api = _api()

    def _fake_upload_and_transcode_audio(**kwargs):
        return {"transcodedSha256": "sha-4", "transcodedInfo": {"metadata": {"title": "A"}}}

    observed: dict[str, object] = {}

    def _fake_create_card(card_title, transcoded_audio, track_details, chapter_details):
        observed["card_title"] = card_title
        observed["transcoded_audio"] = transcoded_audio
        observed["track_details"] = track_details
        observed["chapter_details"] = chapter_details
        return {"ok": True}

    monkeypatch.setattr(api, "upload_and_transcode_audio", _fake_upload_and_transcode_audio)
    monkeypatch.setattr(api, "create_card_from_transcoded_audio", _fake_create_card)

    result = api.upload_audio_to_card(
        audio_path="/tmp/a.mp3",
        card_title="Test Card",
        track_details={"title": "T"},
        chapter_details={"title": "C"},
    )

    assert result == {"ok": True}
    assert observed["card_title"] == "Test Card"
    assert isinstance(observed["transcoded_audio"], TranscodedAudio)
    assert observed["track_details"] == {"title": "T"}
    assert observed["chapter_details"] == {"title": "C"}
