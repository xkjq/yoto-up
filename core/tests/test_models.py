"""Tests for core data models."""
import pytest
from yoto_up.models.card import (
    Card, CardContent, CardMetadata, CardConfig, CardStatus, CardCover,
    CardMedia, Chapter, Track, TrackDisplay, ChapterDisplay, Ambient,
)
from yoto_up.models.device import Device, DeviceStatus, DeviceConfig, DeviceObject
from yoto_up.models.user import TokenData


class TestCard:
    def test_minimal_card(self):
        card = Card(title="Test")
        assert card.title == "Test"
        assert card.cardId is None
        assert card.deleted is False

    def test_full_card(self):
        card = Card(
            cardId="abc123",
            title="My Story",
            metadata=CardMetadata(
                author="Author",
                category="stories",
                tags=["bedtime", "adventure"],
                status=CardStatus(name="live"),
                cover=CardCover(imageL="https://example.com/cover.jpg"),
            ),
            content=CardContent(
                chapters=[
                    Chapter(
                        title="Chapter 1",
                        key="01",
                        tracks=[
                            Track(title="Track 1", trackUrl="https://example.com/1.mp3", key="01", format="mp3", type="audio", duration=120.5),
                            Track(title="Track 2", trackUrl="https://example.com/2.mp3", key="02", format="mp3", type="audio", duration=90.0),
                        ]
                    ),
                    Chapter(
                        title="Chapter 2",
                        key="02",
                        tracks=[
                            Track(title="Track 3", trackUrl="https://example.com/3.mp3", key="01", format="mp3", type="audio", duration=60.0),
                        ]
                    ),
                ],
                playbackType="linear",
            ),
        )
        assert card.total_tracks == 3
        assert card.chapter_count == 2
        assert card.total_duration == pytest.approx(270.5)

    def test_card_no_chapters_properties(self):
        card = Card(title="Empty")
        assert card.total_tracks == 0
        assert card.chapter_count == 0
        assert card.total_duration == 0.0

    def test_card_serialization(self):
        card = Card(title="Test", cardId="123")
        data = card.model_dump()
        assert data["title"] == "Test"
        assert data["cardId"] == "123"

        restored = Card.model_validate(data)
        assert restored.title == card.title
        assert restored.cardId == card.cardId

    def test_track_types(self):
        audio = Track(title="Audio", trackUrl="url", key="01", format="mp3", type="audio")
        assert audio.type == "audio"

        stream = Track(title="Stream", trackUrl="url", key="01", format="mp3", type="stream")
        assert stream.type == "stream"

    def test_card_metadata_categories(self):
        for cat in ["none", "stories", "music", "radio", "podcast", "sfx", "activities", "alarms"]:
            meta = CardMetadata(category=cat)
            assert meta.category == cat

    def test_card_status_values(self):
        for status in ["new", "inprogress", "complete", "live", "archived"]:
            s = CardStatus(name=status)
            assert s.name == status


class TestDevice:
    def test_device_creation(self):
        dev = Device(
            deviceId="dev1",
            name="My Player",
            description="Living Room",
            online=True,
            releaseChannel="stable",
            deviceType="v3",
            deviceFamily="yoto",
            deviceGroup="player",
        )
        assert dev.name == "My Player"
        assert dev.online is True

    def test_device_status_optional_fields(self):
        status = DeviceStatus()
        assert status.batteryLevelPercentage is None
        assert status.isOnline is None

    def test_device_config(self):
        config = DeviceConfig(
            bluetoothEnabled="true",
            maxVolumeLimit="80",
            dayTime="07:00",
            nightTime="19:00",
        )
        assert config.maxVolumeLimit == "80"


class TestTokenData:
    def test_token_creation(self):
        token = TokenData(access_token="abc", refresh_token="xyz")
        assert token.access_token == "abc"
        assert token.id_token is None

    def test_token_with_id(self):
        token = TokenData(access_token="abc", refresh_token="xyz", id_token="idt")
        assert token.id_token == "idt"

    def test_token_serialization(self):
        token = TokenData(access_token="a", refresh_token="r")
        data = token.model_dump()
        restored = TokenData.model_validate(data)
        assert restored.access_token == token.access_token
