import json
from yoto_up.yoto_api import YotoAPI
from yoto_up.models import Card, CardContent, Chapter, Track, DEFAULT_MEDIA_ID


def _api() -> YotoAPI:
    return YotoAPI.__new__(YotoAPI)


def test_find_best_icons_from_local_cache(tmp_path, monkeypatch):
    api = _api()
    cache_dir = tmp_path / "yotoicons"
    cache_dir.mkdir()
    metadata = [
        {"id": "1", "title": "Dog", "img_url": "http://example/dog.png", "tags": ["dog"]},
        {"id": "2", "title": "Cat", "img_url": "http://example/cat.png", "tags": ["cat"]},
    ]
    (cache_dir / "yotoicons_global_metadata.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(api, "YOTOICONS_CACHE_DIR", cache_dir)

    results = api.find_best_icons_for_text("dog", include_yotoicons=True)
    assert isinstance(results, list)
    assert any("Dog" in (r.get("title") or "") for r in results)


def make_test_card_two_tracks():
    # Build a Card with one chapter and two tracks needing default icons
    t1 = Track(title="T1", trackUrl="yoto:#a", key="01", format="mp3", type="audio")
    t2 = Track(title="T2", trackUrl="yoto:#b", key="02", format="mp3", type="audio")
    # set default icon marker
    t1.display = t1.display or None
    t2.display = t2.display or None
    ch = Chapter(title="C1", key="00", tracks=[t1, t2])
    card = Card(title="Card", content=CardContent(chapters=[ch]))
    # ensure icons appear as DEFAULT_MEDIA_ID so they're considered for replacement
    for tr in card.get_chapters()[0].tracks:
        tr.set_icon_field(DEFAULT_MEDIA_ID)
    # Set chapter icon to a non-default to avoid the chapter itself being targeted
    card.get_chapters()[0].set_icon_field("yoto:#existing")
    return card


def test_replace_card_default_icons_parallel(monkeypatch):
    api = _api()
    card = make_test_card_two_tracks()

    # Return two distinct candidates so both targets can get different mediaIds
    def fake_find_best_icons_for_text(query, include_yotoicons=True, top_n=5, max_searches=3, exclude_media_ids=None, **kwargs):
        return [
            {"id": "y1", "img_url": "http://example/icon1.png"},
            {"id": "y2", "img_url": "http://example/icon2.png"},
        ]

    def fake_upload_yotoicons_icon_to_yoto_api(candidate):
        return {"mediaId": "MID-" + (candidate.get("id") or "x")}

    monkeypatch.setattr(api, "find_best_icons_for_text", fake_find_best_icons_for_text)
    monkeypatch.setattr(api, "upload_yotoicons_icon_to_yoto_api", fake_upload_yotoicons_icon_to_yoto_api)

    new_card = api.replace_card_default_icons(card, parallel_workers=2, max_searches=2)
    assert new_card is not None
    chapters = new_card.get_chapters()
    assert chapters and chapters[0].tracks
    media_ids = [t.get_icon_field() for t in chapters[0].tracks]
    # Ensure both tracks have been assigned a yoto media id (not left as default)
    assert all(m is not None and m != DEFAULT_MEDIA_ID for m in media_ids)
