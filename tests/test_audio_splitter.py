import tempfile
from pathlib import Path
from yoto_up.audio_splitter import _format_output_name, _parse_silencedetect_output


def test_format_output_name_defaults():
    p = Path("/tmp/book.mp3")
    out = _format_output_name(p, index=0, total=10, out_dir=Path("/tmp"))
    assert out.name.startswith("book_part01")


def test_format_output_name_template_index():
    p = Path("/tmp/book.mp3")
    out = _format_output_name(p, index=1, total=10, out_dir=Path("/tmp"), template="Track {index:02d}")
    assert out.name == "Track 02.mp3"


def test_format_output_name_template_stem_and_index():
    p = Path("/tmp/My Book.mp3")
    out = _format_output_name(p, index=9, total=12, out_dir=Path("/tmp"), template="{stem} - Track {index:02d}")
    assert out.name == "My Book - Track 10.mp3"


def test_parse_silencedetect_output_empty():
    assert _parse_silencedetect_output("") == []
    assert _parse_silencedetect_output("\n\nrandom output\n") == []


def test_parse_silencedetect_output_normal():
    sample = (
        "[silencedetect @ 0x5555] silence_start: 10.5\n"
        "[silencedetect @ 0x5555] silence_end: 12.0 | silence_duration: 1.5\n"
        "[silencedetect @ 0x5555] silence_start: 50.2\n"
        "[silencedetect @ 0x5555] silence_end: 51.0 | silence_duration: 0.8\n"
    )
    expected = [(10.5, 12.0), (50.2, 51.0)]
    assert _parse_silencedetect_output(sample) == expected


def test_parse_silencedetect_output_unmatched_start():
    # start is present, but no matching end (e.g. file cuts off)
    sample = (
        "[silencedetect @ 0x5555] silence_start: 10.5\n"
        "[silencedetect @ 0x5555] silence_end: 12.0 | silence_duration: 1.5\n"
        "[silencedetect @ 0x5555] silence_start: 50.2\n"
    )
    expected = [(10.5, 12.0)]
    assert _parse_silencedetect_output(sample) == expected


def test_parse_silencedetect_output_unmatched_end():
    # end without start at the very beginning (treated as starting from 0.0)
    sample = (
        "[silencedetect @ 0x5555] silence_end: 5.0 | silence_duration: 5.0\n"
        "[silencedetect @ 0x5555] silence_start: 20.0\n"
        "[silencedetect @ 0x5555] silence_end: 22.0 | silence_duration: 2.0\n"
    )
    expected = [(0.0, 5.0), (20.0, 22.0)]
    assert _parse_silencedetect_output(sample) == expected

