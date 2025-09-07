# Overview


Yoto-UP is a set of command-line, terminal UI (Textual) and graphical (Flet) tools to manage Yoto content and devices. It provides helpers for:

- Uploading audio files and creating or appending to Yoto cards
- Managing playlists and cards
- Uploading and caching 16x16 icons
- A small terminal pixel-art editor used for icons

The repository is organised roughly as follows:

- `yoto_api.py` — API client for Yoto services
- `yoto.py` — CLI entry-points and scripts
- `gui.py` — Graphical UI using Flet
- `yoto_app/` — UI helpers, playlists UI, upload tasks, and dialogs
- `models.py` — Pydantic data models used with the API

