# Cover Management

This section covers uploading and managing cover images for cards.

What you can do

- Upload a cover image from a local file or via a remote URL.
- The tool uploads directly using Yoto's API.

Key code locations

- `yoto_api.py`
  - `upload_cover_image(image_path, imageUrl, autoconvert, ...)` — upload and return cover metadata
  - `get_icon_cache_path` — used to cache/download images for preview

- `yoto_app/add_cover_dialog.py` — UI dialog that lets you select and upload a cover for a card

Usage notes

- The API expects either a file body or an `imageUrl`. If you provide a local file, it will be streamed in the request body.
- The function returns cover metadata including `mediaId` and `mediaUrl`. Store or pass that into a card's metadata as appropriate.
