"""Audio upload and transcoding operations against the Yoto API.

The typical workflow for adding audio to a card is:

1. :func:`calculate_sha256` -- hash the local file.
2. :func:`get_upload_url` -- obtain a pre-signed S3 upload URL from Yoto.
3. :func:`upload_audio` -- PUT the audio bytes to S3.
4. :func:`poll_transcoding` -- wait for the server to transcode and register
   the track.

The convenience wrapper :func:`upload_and_transcode` bundles steps 1--4.
"""

from __future__ import annotations

import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from loguru import logger

from .client import YotoClient

# ------------------------------------------------------------------
# SHA-256 helper
# ------------------------------------------------------------------


def calculate_sha256(audio_path: str | Path) -> tuple[str, bytes]:
    """Calculate the SHA-256 hash of a file.

    Parameters
    ----------
    audio_path:
        Path to the file on disk.

    Returns
    -------
    A 2-tuple of ``(hex_digest, raw_bytes)`` where *raw_bytes* is the
    complete file content.
    """
    path = Path(audio_path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    digest = h.hexdigest()
    data = path.read_bytes()
    return digest, data


# ------------------------------------------------------------------
# Upload URL
# ------------------------------------------------------------------


def get_upload_url(
    client: YotoClient,
    sha256: str,
    filename: str | None = None,
) -> dict[str, Any]:
    """Request a pre-signed upload URL from the Yoto API.

    Parameters
    ----------
    client:
        An authenticated :class:`YotoClient`.
    sha256:
        Hex-encoded SHA-256 digest of the file to upload.
    filename:
        Optional original filename, used by the server for labelling.

    Returns
    -------
    A dict containing at least ``uploadUrl`` and ``uploadId`` keys.
    """
    payload: dict[str, Any] = {"sha256": sha256}
    if filename:
        payload["filename"] = filename

    resp = client.post("/media/upload/audio", json=payload)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------
# Upload audio to S3
# ------------------------------------------------------------------


def upload_audio(
    upload_url: str,
    audio_bytes: bytes,
    mime_type: str = "audio/mpeg",
) -> None:
    """Upload raw audio bytes to a pre-signed S3 URL.

    Parameters
    ----------
    upload_url:
        The pre-signed URL obtained from :func:`get_upload_url`.
    audio_bytes:
        The raw audio file content.
    mime_type:
        MIME type of the audio.  Defaults to ``audio/mpeg``.

    Raises
    ------
    httpx.HTTPStatusError
        If the upload fails.
    """
    resp = httpx.put(
        upload_url,
        content=audio_bytes,
        headers={"Content-Type": mime_type},
        timeout=120.0,
    )
    resp.raise_for_status()
    logger.debug(f"Audio uploaded to S3 ({len(audio_bytes)} bytes)")


# ------------------------------------------------------------------
# Transcoding poll
# ------------------------------------------------------------------


def poll_transcoding(
    client: YotoClient,
    upload_id: str,
    interval: float = 2.0,
    max_attempts: int = 120,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Poll the Yoto API until an uploaded audio file finishes transcoding.

    Parameters
    ----------
    client:
        An authenticated :class:`YotoClient`.
    upload_id:
        The ``uploadId`` returned by :func:`get_upload_url`.
    interval:
        Seconds between poll requests.
    max_attempts:
        Maximum number of poll iterations before giving up.
    on_progress:
        Optional callback invoked with a status string each iteration.

    Returns
    -------
    The final transcoding result dict, which typically contains the
    ``trackUrl``, ``key``, ``format``, ``duration``, etc.

    Raises
    ------
    TranscodingError
        If the maximum number of attempts is exceeded or the server
        reports a permanent failure.
    """
    for attempt in range(1, max_attempts + 1):
        resp = client.get(f"/media/upload/audio/{upload_id}")
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "").lower()

        if status in ("complete", "completed", "done"):
            if on_progress:
                on_progress("Transcoding complete")
            return data

        if status in ("failed", "error"):
            error_msg = data.get("error", data.get("message", "Unknown error"))
            raise TranscodingError(f"Transcoding failed: {error_msg}")

        if on_progress:
            pct = data.get("progress", "")
            on_progress(
                f"Transcoding in progress ({status})"
                + (f" {pct}%" if pct else "")
                + f" [attempt {attempt}/{max_attempts}]"
            )

        time.sleep(interval)

    raise TranscodingError(
        f"Transcoding did not complete after {max_attempts} attempts"
    )


# ------------------------------------------------------------------
# Convenience: upload + transcode in one call
# ------------------------------------------------------------------


def upload_and_transcode(
    client: YotoClient,
    audio_path: str | Path,
    filename: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Upload a local audio file and wait for transcoding to complete.

    This is the high-level convenience function that combines
    :func:`calculate_sha256`, :func:`get_upload_url`, :func:`upload_audio`,
    and :func:`poll_transcoding`.

    Parameters
    ----------
    client:
        An authenticated :class:`YotoClient`.
    audio_path:
        Path to the audio file on disk.
    filename:
        Optional override for the filename sent to the API.  Defaults to
        the file's actual name.
    on_progress:
        Optional callback invoked with status strings during the process.

    Returns
    -------
    The transcoding result dict.
    """
    path = Path(audio_path)
    if filename is None:
        filename = path.name

    # Step 1: hash
    if on_progress:
        on_progress(f"Calculating checksum for {filename}...")
    sha256, audio_bytes = calculate_sha256(path)

    # Step 2: request upload URL
    if on_progress:
        on_progress("Requesting upload URL...")
    upload_info = get_upload_url(client, sha256, filename)
    upload_url: str = upload_info["uploadUrl"]
    upload_id: str = upload_info["uploadId"]

    # Step 3: upload to S3
    if on_progress:
        on_progress(f"Uploading {filename} ({len(audio_bytes)} bytes)...")
    mime_type = _guess_mime_type(filename)
    upload_audio(upload_url, audio_bytes, mime_type=mime_type)

    # Step 4: poll for transcoding
    if on_progress:
        on_progress("Waiting for transcoding...")
    return poll_transcoding(client, upload_id, on_progress=on_progress)


# ------------------------------------------------------------------
# Cover image upload
# ------------------------------------------------------------------


def upload_cover_image(
    client: YotoClient,
    image_path: str | Path,
) -> dict[str, Any]:
    """Upload a cover image for a card.

    Parameters
    ----------
    client:
        An authenticated :class:`YotoClient`.
    image_path:
        Path to the image file on disk (PNG or JPEG recommended).

    Returns
    -------
    A dict containing the uploaded image URL and any associated metadata
    from the server response.
    """
    path = Path(image_path)
    image_data = path.read_bytes()
    filename = path.name

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    mime_type = mime_map.get(ext, "image/png")

    resp = client.post(
        "/media/upload/image",
        files={"file": (filename, image_data, mime_type)},
    )
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _guess_mime_type(filename: str) -> str:
    """Guess the MIME type for an audio file, falling back to audio/mpeg."""
    guessed, _ = mimetypes.guess_type(filename)
    if guessed and guessed.startswith("audio/"):
        return guessed
    return "audio/mpeg"


class TranscodingError(Exception):
    """Raised when audio transcoding fails or times out."""
