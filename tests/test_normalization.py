import os
import pytest
from unittest.mock import MagicMock, patch
from yoto_up.normalization import AudioNormalizer


def test_get_codec_for_ext():
    norm = AudioNormalizer()
    assert norm._get_codec_for_ext(".mp3") == "libmp3lame"
    assert norm._get_codec_for_ext(".MP3") == "libmp3lame"
    assert norm._get_codec_for_ext(".wav") == "pcm_s16le"
    assert norm._get_codec_for_ext(".m4a") == "aac"
    assert norm._get_codec_for_ext(".aac") == "aac"
    assert norm._get_codec_for_ext(".flac") == "flac"
    assert norm._get_codec_for_ext(".ogg") == "libvorbis"
    assert norm._get_codec_for_ext(".unknown") == "aac"  # default fallback


def test_normalize_empty_list():
    norm = AudioNormalizer()
    assert norm.normalize([], "/tmp/out") == []


@patch("yoto_up.normalization.FFmpegNormalize")
def test_normalize_individual_mode(mock_ffmpeg_norm):
    # Setup normalizer mock instance
    mock_instance = MagicMock()
    mock_ffmpeg_norm.return_value = mock_instance

    norm = AudioNormalizer(target_level=-16.0, true_peak=-2.0, batch_mode=False)

    progress_events = []
    def progress_cb(msg, frac):
        progress_events.append((msg, frac))

    inputs = ["/media/track1.mp3", "/media/track2.wav"]
    out_dir = "/tmp/normalized"

    # Call normalize
    with patch("os.makedirs") as mock_makedirs:
        results = norm.normalize(inputs, out_dir, progress_callback=progress_cb)

    # Check output paths structure
    assert results == ["/tmp/normalized/track1.mp3", "/tmp/normalized/track2.wav"]
    mock_makedirs.assert_called_once_with(out_dir, exist_ok=True)

    # Verify FFmpegNormalize was called twice (once for each file)
    assert mock_ffmpeg_norm.call_count == 2
    
    # First file details
    first_call_args = mock_ffmpeg_norm.call_args_list[0][1]
    assert first_call_args["target_level"] == -16.0
    assert first_call_args["true_peak"] == -2.0
    assert first_call_args["audio_codec"] == "libmp3lame"
    assert first_call_args["batch"] is False

    # Second file details
    second_call_args = mock_ffmpeg_norm.call_args_list[1][1]
    assert second_call_args["audio_codec"] == "pcm_s16le"

    # Verify methods called on mock instance
    assert mock_instance.add_media_file.call_count == 2
    mock_instance.add_media_file.assert_any_call("/media/track1.mp3", "/tmp/normalized/track1.mp3")
    mock_instance.add_media_file.assert_any_call("/media/track2.wav", "/tmp/normalized/track2.wav")
    assert mock_instance.run_normalization.call_count == 2

    # Verify progress events
    assert len(progress_events) == 3
    assert progress_events[0] == ("Normalizing track1.mp3...", 0.0)
    assert progress_events[1] == ("Normalizing track2.wav...", 0.5)
    assert progress_events[2] == ("Normalization complete", 1.0)


@patch("yoto_up.normalization.FFmpegNormalize")
def test_normalize_batch_mode(mock_ffmpeg_norm):
    mock_instance = MagicMock()
    mock_ffmpeg_norm.return_value = mock_instance

    norm = AudioNormalizer(target_level=-23.0, true_peak=-1.0, batch_mode=True)

    progress_events = []
    def progress_cb(msg, frac):
        progress_events.append((msg, frac))

    inputs = ["/media/track1.mp3", "/media/track2.mp3"]
    out_dir = "/tmp/normalized"

    with patch("os.makedirs") as mock_makedirs:
        results = norm.normalize(inputs, out_dir, progress_callback=progress_cb)

    assert results == ["/tmp/normalized/track1.mp3", "/tmp/normalized/track2.mp3"]
    mock_makedirs.assert_called_once_with(out_dir, exist_ok=True)

    # In batch mode, FFmpegNormalize is instantiated once
    mock_ffmpeg_norm.assert_called_once()
    call_args = mock_ffmpeg_norm.call_args[1]
    assert call_args["batch"] is True
    assert call_args["audio_codec"] == "libmp3lame"

    # Both media files are added before run_normalization is called
    assert mock_instance.add_media_file.call_count == 2
    mock_instance.add_media_file.assert_any_call("/media/track1.mp3", "/tmp/normalized/track1.mp3")
    mock_instance.add_media_file.assert_any_call("/media/track2.mp3", "/tmp/normalized/track2.mp3")
    mock_instance.run_normalization.assert_called_once()

    # Progress callbacks check
    assert len(progress_events) == 2
    assert progress_events[0] == ("Normalizing (Batch)...", 0.1)
    assert progress_events[1] == ("Normalization complete", 1.0)
