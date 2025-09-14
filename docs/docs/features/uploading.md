# Uploading Audio Files

Yoto-UP supports creating new cards from a local folder of audio files, or appending audio as tracks/chapters to existing cards.

Modes

- Create new card
  - Upload a folder of audio files and create a single new Yoto card.
  - Optionally create a single combined "chapter" containing all files (single-chapter mode) or one chapter per file.

- Append to existing card
  - Upload files and append them as new chapters or add tracks to an existing chapter.
  - Use the Playlists tab to fetch and select a target card. If playlists are empty, use the Fetch button.

Where to configure

- Concurrency: the Flet UI exposes a `Concurrency` field to control how many uploads run concurrently.
- Upload mode: choose `Create new card` or `Add to existing card` in the Upload tab.

Key code locations

- `yoto_app/upload_tasks.py` — upload orchestration moved from `gui.py`; this contains the worker loop, progress updates, and append logic.
- `yoto_api.py` — helpers to upload audio, poll for transcoding, and build Chapter/Track objects:
  - `upload_and_transcode_audio_async`
  - `get_chapter_from_transcoded_audio`
  - `upload_and_transcode_and_create_card_async`

Example workflow (Flet UI)

1. Authenticate via the Auth tab.
2. Open Playlists and click `Fetch Playlists` if needed.
3. Open Upload, set a folder path, pick `Create new card` or `Add to existing card`.
4. Click `Start Upload` and monitor the progress bars.

