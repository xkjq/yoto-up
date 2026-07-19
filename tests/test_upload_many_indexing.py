import asyncio

from yoto_up.yoto_api import YotoAPI


def _api() -> YotoAPI:
    # Build an instance without running __init__ (no auth / network).
    return YotoAPI.__new__(YotoAPI)


def test_many_async_uploads_each_file_once_in_order(monkeypatch):
    """Regression test for a bug where upload_and_transcode_many_async launched
    every worker with the default idx=0, so all files were uploaded as
    media_files[0]. This produced cards whose chapters all shared a single
    trackUrl. Each input file must be uploaded exactly once, and results must
    be returned in input order.
    """
    api = _api()

    seen = []

    async def fake_upload(*args, audio_path=None, filename=None, **kwargs):
        seen.append(audio_path)
        # Echo the path back so we can assert on ordering of results.
        return {"audio_path": audio_path, "filename": filename}

    monkeypatch.setattr(api, "upload_and_transcode_audio_async", fake_upload)

    files = [f"/media/track{i:02d}.mp3" for i in range(6)]
    results = asyncio.run(
        api.upload_and_transcode_many_async(files, show_progress=False)
    )

    # Every file uploaded exactly once (no duplicates, none skipped).
    assert sorted(seen) == sorted(files)
    assert len(set(seen)) == len(files)

    # Results preserve input order, one per file.
    assert [r["audio_path"] for r in results] == files


def test_many_async_passes_matching_filename(monkeypatch):
    """filename_list entries must line up with their file by index, not idx=0."""
    api = _api()

    pairs = []

    async def fake_upload(*args, audio_path=None, filename=None, **kwargs):
        pairs.append((audio_path, filename))
        return {"audio_path": audio_path, "filename": filename}

    monkeypatch.setattr(api, "upload_and_transcode_audio_async", fake_upload)

    files = [f"/media/track{i:02d}.mp3" for i in range(4)]
    names = [f"Chapter {i}" for i in range(4)]
    asyncio.run(
        api.upload_and_transcode_many_async(
            files, filename_list=names, show_progress=False
        )
    )

    # Each path is paired with the filename at the same index.
    assert sorted(pairs) == sorted(zip(files, names))
