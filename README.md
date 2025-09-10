# Yoto-UP

<img src="art.jpeg" alt="Artwork preview" style="max-width:100%;height:auto;">


A multipurpose set of command-line, terminal UI, and graphical tools for managing your Yoto content.  

Features include content organization, device management, and easy integration with Yoto services.

## Features

- **Integration with Yoto Services**: Simplified access to Yoto's API and services.
- **Content Organization**: Easily manage and organize your Yoto cards and files.
   # 🚀 Yoto-UP

   A toolbox for managing Yoto content from the command line, a terminal UI, or a GUI.

   Yoto-UP helps with content organization, device management, icon handling, and easy integration with Yoto services.

   ## ✨ Highlights

   - 🔗 Integration with Yoto Services — simplified access to the Yoto API and helper utilities
   - 🗂️ Playlist/Card organization — chapters, tracks and metadata management
      - 🎵 Track titles, keys and durations
      - 🖼️ Icon management — autoselect or pick icons via search
      - 🖌️ Cover management — set, import, or auto-search cover art; embed into card metadata
      - 📤 Export / 📥 Import cards
   - 🖥️ Interfaces — CLI, TUI (terminal UI) and a small graphical UI

   For full docs and examples see the project site: https://xkjq.github.io/yoto-up/

   ## 🛠️ Installation

   ### GUI (binary)

   Pre-built binaries are published on the releases page: https://github.com/xkjq/yoto-up/releases

   If there's no binary for your platform, run from source using the steps below.

   ### From source (recommended for advanced users)

   1. Clone the repository and change into it:

   ```bash
   git clone https://github.com/xkjq/yoto-up.git
   cd yoto-up
   ```

   2. Create and activate a virtual environment

   You can use the standard Python venv workflow, but uv is recommended

   Standard (bash / zsh / sh):

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   Standard (fish):

   ```fish
   python -m venv .venv
   source .venv/bin/activate.fish
   ```

   Using `uv` (recommended if available):

   ```bash
   uv venv
   source .venv/bin/activate
   ```

   3. Install Python dependencies:

   ```bash
   (uv) pip install -r requirements.txt
   ```

   Quick checks and notes:

   - Confirm the venv Python is active: `python --version` and `which python` should point into `.venv/`.
   - macOS / Linux: use the system `python3` if `python` is not available.
   - Alternative workflows: `pipx` or `poetry` can be used if preferred.

   ## ▶️ Usage

   ### CLI / TUI
   • Start the CLI (lists commands):

   ```bash
   python yoto.py
   ```

   • Open the terminal editor for a card:

   ```bash
   python yoto.py edit-card <CARD_ID>
   ```

   ### GUI

   ```bash
   python gui.py
   ```

   ## Want a pip installable package?
   So do I.

   ## 🤝 Contributing

   1. Fork and create a branch:

   ```bash
   git checkout -b feature-branch-name
   ```

   2. Make changes, commit and push:

   ```bash
   git commit -am "Describe your change"
   git push origin feature-branch-name
   ```

   3. Open a pull request.

   ## 📜 License

   MIT — see `LICENSE` for details.

