# Icon Management

Yoto-UP includes tools to find, render, cache and upload small 16×16 icons used as card/chapter artwork.

??? example "See a sample of it working in the terminal"
    This example shows editing a newly created playlist and letting the icon be automatically selected.
    <script src="https://asciinema.org/a/ebXKat85slfP1ayc76wWJycsB.js" id="asciicast-ebXKat85slfP1ayc76wWJycsB" async="true"></script>

- Search Official Yoto icons and YotoIcons (scrapes / caches results).
- Download and cache official Yoto icons to `.yoto_icon_cache/`.
- Upload a YotoIcons icon to the official Yoto API (creating a `displayIcon`).
- Render pixel-art previews in the terminal (useful for picking icons).

Key code locations

- `yoto_api.py`
  - `get_public_icons` — download and cache official icons
  - `search_yotoicons` / `search_yotoicons` — scrape and cache YotoIcons results
  - `upload_yotoicons_icon_to_yoto_api` / `upload_custom_icon` — upload icons to Yoto
  - `get_icon_cache_path` — utility to resolve a cached path from an icon field

- `icons.py` — small renderer used to display pixel art in the terminal
- `yoto_app/` — UI dialogs and helpers exposing icon search/upload from the Flet UI

Usage tips

- When uploading icons, a `displayIcon` (mediaId + url) is returned; prefer referencing the returned mediaId when assigning to `TrackDisplay` / `ChapterDisplay` fields.
