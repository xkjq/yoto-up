"""Icon operations against the Yoto API and yotoicons.com.

Functions for fetching, uploading, and searching display icons that can be
assigned to card chapters and tracks.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from loguru import logger

from .client import YotoClient

# ------------------------------------------------------------------
# Yoto API icon endpoints
# ------------------------------------------------------------------


def get_public_icons(client: YotoClient) -> list[dict[str, Any]]:
    """Fetch the public (Yoto-provided) icon library.

    Returns a list of dicts, each containing at least ``mediaId`` and
    ``url`` keys.
    """
    resp = client.get("/media/displayIcons/user/yoto")
    resp.raise_for_status()
    data = resp.json()

    # Handle both a raw list and a wrapper object.
    if isinstance(data, list):
        return data
    return data.get("displayIcons", data.get("icons", []))


def get_user_icons(client: YotoClient) -> list[dict[str, Any]]:
    """Fetch the authenticated user's custom uploaded icons.

    Returns a list of dicts, each containing at least ``mediaId`` and
    ``url`` keys.
    """
    resp = client.get("/media/displayIcons/user/me")
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list):
        return data
    return data.get("displayIcons", data.get("icons", []))


def upload_icon(
    client: YotoClient,
    image_data: bytes,
    filename: str,
) -> dict[str, Any]:
    """Upload a custom icon image for use on cards.

    Parameters
    ----------
    client:
        An authenticated :class:`YotoClient`.
    image_data:
        The raw image bytes (PNG or JPEG recommended).
    filename:
        Original filename (used to derive the MIME type and to label the
        upload on the server).

    Returns
    -------
    The raw JSON response dict from the server, typically containing
    ``mediaId`` and ``url`` of the newly uploaded icon.
    """
    # Determine MIME type from extension.
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
        "/media/displayIcons/user/me",
        files={"file": (filename, image_data, mime_type)},
    )
    resp.raise_for_status()
    return resp.json()


def get_icon_data(client: YotoClient, media_id: str) -> bytes | None:
    """Download the raw image bytes for a specific icon by media ID.

    Returns ``None`` if the icon cannot be fetched.
    """
    try:
        resp = client.get(f"/media/displayIcons/{media_id}")
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        logger.warning(f"Failed to download icon {media_id}: {exc}")
        return None


# ------------------------------------------------------------------
# yotoicons.com scraping (no BeautifulSoup dependency)
# ------------------------------------------------------------------

_YOTOICONS_BASE = "https://yotoicons.com"


def search_yotoicons(tag: str, limit: int = 20) -> list[dict[str, str]]:
    """Search yotoicons.com for community icons matching *tag*.

    This performs simple HTML scraping using regex -- no external HTML
    parsing library is required.

    Parameters
    ----------
    tag:
        A search term (e.g. ``"dinosaur"``, ``"music"``).
    limit:
        Maximum number of results to return.

    Returns
    -------
    A list of dicts with keys ``"title"``, ``"url"``, and ``"page_url"``.
    """
    try:
        resp = httpx.get(
            f"{_YOTOICONS_BASE}/search",
            params={"q": tag},
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "yoto-up/0.1 (icon search)",
            },
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"yotoicons.com search failed: {exc}")
        return []

    html = resp.text
    return _parse_icon_results(html, limit)


def _parse_icon_results(html: str, limit: int) -> list[dict[str, str]]:
    """Extract icon image URLs and titles from yotoicons.com HTML.

    Uses simple regex patterns to pull ``<img>`` tags and their ``alt``
    attributes from the search results page.
    """
    results: list[dict[str, str]] = []

    # Look for icon image tags -- yotoicons.com typically renders results
    # as <img> elements inside anchor tags.  The patterns below are
    # intentionally lenient to accommodate minor markup changes.

    # Pattern: <a href="..."><img src="..." alt="..."></a>
    anchor_pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>'
        r'\s*<img[^>]+src=["\']([^"\']+)["\'][^>]*'
        r'(?:alt=["\']([^"\']*)["\'])?',
        re.IGNORECASE | re.DOTALL,
    )

    for match in anchor_pattern.finditer(html):
        page_url = match.group(1)
        img_url = match.group(2)
        title = match.group(3) or ""

        # Only include results that look like icon images.
        if not img_url or not _looks_like_icon_url(img_url):
            continue

        # Resolve relative URLs.
        if img_url.startswith("/"):
            img_url = f"{_YOTOICONS_BASE}{img_url}"
        if page_url.startswith("/"):
            page_url = f"{_YOTOICONS_BASE}{page_url}"

        results.append(
            {
                "title": title.strip(),
                "url": img_url,
                "page_url": page_url,
            }
        )
        if len(results) >= limit:
            break

    # Fallback: try standalone <img> tags if anchor pattern found nothing.
    if not results:
        img_pattern = re.compile(
            r'<img[^>]+src=["\']([^"\']+)["\'][^>]*'
            r'(?:alt=["\']([^"\']*)["\'])?',
            re.IGNORECASE,
        )
        for match in img_pattern.finditer(html):
            img_url = match.group(1)
            title = match.group(2) or ""

            if not _looks_like_icon_url(img_url):
                continue

            if img_url.startswith("/"):
                img_url = f"{_YOTOICONS_BASE}{img_url}"

            results.append(
                {
                    "title": title.strip(),
                    "url": img_url,
                    "page_url": "",
                }
            )
            if len(results) >= limit:
                break

    return results


def _looks_like_icon_url(url: str) -> bool:
    """Heuristic: return ``True`` if *url* looks like an icon image."""
    url_lower = url.lower()
    # Skip common non-icon resources.
    if any(
        skip in url_lower
        for skip in ("favicon", "logo", "banner", "sprite", "data:image")
    ):
        return False
    # Strip query parameters and fragments before checking extensions.
    path_part = url_lower.split("?", 1)[0].split("#", 1)[0]
    # Accept common image extensions.
    return any(path_part.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))
