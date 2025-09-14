# Features

This section gives a quick tour of the major features in Yoto-UP. 

- [Playlist Management]
    - Search, view and filter playlists
    - Create and edit playlists with features including
        - Convert between different playlist format (e.g. Chapters -> Tracks, Tracks -> Chapters)
        - Versioning: made a mistake updating a playlist? simply revert to any old version 

- [Icon management](icon_management.md)
    - Search, cache and upload 16×16 pixel icons
    - Render pixel art for inspection
    - Automatically upload and attach to playlists
    - Helpers in `yoto_api.py` for external app integration
    - Available both in terminal and the full GUI

- [Cover management](cover_management.md)
    - Easy cover management
    - Search and upload cover images for cards

- [Uploading audio files](uploading.md)
    - Create new cards or append tracks/chapters to existing cards
    - Concurrency and progress reporting
    - CLI and Flet UI workflows
    - Volume adjustment

- [Import and export playlist](import_export.md)
    - Easily import and export playlists/cards for sharing

# Quickstart

Get started with Yoto-UP in just a few steps:

1. **Download a release:**
    - Go to the [GitHub Releases page](https://github.com/xkjq/yoto-up/releases).
    - Download the latest release for your platform (e.g. `yoto-up-linux.tar.gz`, `yoto-up-windows.zip`, or `yoto-up-macos.tar.gz`).
    - Extract the archive to a folder of your choice.

2. **Run the GUI:**
    - On Linux/macOS:
      ```sh
      cd <extracted-folder>
      ./yoto-up
      ```
    - On Windows:
      - Extract the zip, then double-click `yoto-up.exe` (or run it from PowerShell/cmd).

3. **Authenticate:**
    - The first time you run the app, click the **Authenticate** button and follow the instructions to link your Yoto account.

4. **Start using features:**
    - Use the tabs to manage playlists, upload audio, edit cards, and more.