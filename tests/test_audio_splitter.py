import tempfile
from pathlib import Path
from yoto_up.audio_splitter import _format_output_name


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
