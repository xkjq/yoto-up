import os
import pytest
from unittest.mock import MagicMock, patch
import flet as ft

from yoto_up.yoto_app.playlists import build_playlists_panel
from yoto_up.yoto_app.library import build_library_panel
from yoto_up.yoto_app.icon_browser import build_icon_browser_panel
from yoto_up.yoto_app.show_waveforms import show_waveforms_popup


class MockPage:
    def __init__(self):
        self.dialog = None
        self.api_ref = {}
        self.web = False
        self.controls = []

    def update(self):
        pass

    def run_task(self, coro, *args, **kwargs):
        pass

    def show_snack(self, msg, error=False):
        pass

    def pop_dialog(self):
        pass

    def show_dialog(self, dialog):
        self.dialog = dialog


def test_build_playlists_panel_dry_run():
    page = MockPage()
    # Mock ensure_api to return a fake API to prevent auth/network calls
    with patch("yoto_up.yoto_app.playlists.ensure_api") as mock_ensure:
        mock_api = MagicMock()
        mock_ensure.return_value = mock_api
        
        # This will trigger UI control rendering, testing Padding/Margin namespaces
        res = build_playlists_panel(page)
        assert isinstance(res, dict)
        assert "playlists_column" in res


def test_build_library_panel_dry_run():
    page = MockPage()
    with patch("yoto_up.yoto_app.library.ensure_api") as mock_ensure:
        mock_api = MagicMock()
        mock_ensure.return_value = mock_api
        
        # Test building library UI tab
        res = build_library_panel(page)
        assert res is not None


def test_build_icon_browser_panel_dry_run():
    page = MockPage()
    mock_api = MagicMock()
    mock_api.YOTOICONS_CACHE_DIR = "/tmp"
    
    # Test building icon browser tab (passing the ensure_api and show_snack parameters)
    res = build_icon_browser_panel(
        page,
        api_ref=page.api_ref,
        ensure_api=lambda ref: mock_api,
        show_snack=page.show_snack
    )
    assert res is not None


def test_show_waveforms_popup_dry_run():
    page = MockPage()
    
    # Construct Mock for file_rows_column containing rows with a filename attribute
    file_rows_column = MagicMock()
    file_rows_column.controls = [
        MagicMock(filename="/tmp/fake_track1.mp3"),
        MagicMock(filename="/tmp/fake_track2.wav")
    ]
    
    # Mock batch_audio_stats to avoid file checks and audio stats computation
    with patch("yoto_up.yoto_app.show_waveforms.batch_audio_stats") as mock_stats:
        # Return fake stats matching expected tuple: (audio_np, max_amp, avg_amp, lufs, ext, filepath)
        mock_stats.return_value = [
            (None, None, None, None, ".mp3", "/tmp/fake_track1.mp3"),
            (None, None, None, None, ".wav", "/tmp/fake_track2.wav")
        ]
        
        # Call waveforms popup builder with all required positional arguments
        show_waveforms_popup(
            page,
            file_rows_column=file_rows_column,
            show_snack=page.show_snack,
            gain_adjusted_files={},
            audio_adjust_utils=MagicMock(),
            waveform_cache={}
        )
        
        # Verify dialog is populated
        assert page.dialog is not None


def test_colour_picker_dry_run():
    from yoto_up.yoto_app.colour_picker import ColourPicker
    page = MockPage()
    selected_color = None

    def on_color_selected(color):
        nonlocal selected_color
        selected_color = color

    picker = ColourPicker(
        current_color="#ff0000",
        on_color_selected=on_color_selected
    )
    dialog = picker.build_dialog(page=page)
    assert dialog is not None
    assert dialog.content is not None
    assert picker.current_color == "#ff0000"
