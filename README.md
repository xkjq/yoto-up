# Yoto-UP

A multipurpose set of command-line, terminal UI, and graphical tools for managing your Yoto content.  

Features include content organization, device management, and easy integration with Yoto services.

## Features

- **Integration with Yoto Services**: Simplified access to Yoto's API and services.
- **Content Organization**: Easily manage and organize your Yoto cards and files.
   # 🚀 Yoto-UP

   A friendly toolbox for managing Yoto content from the command line, a terminal UI, or a small GUI.

   Yoto-UP helps with content organization, device management, icon handling, and easy integration with Yoto services.

   ## ✨ Highlights

   - 🔗 Integration with Yoto Services — simplified access to the Yoto API and helper utilities
   - 🗂️ Content organization — chapters, tracks and metadata management
      - 🎵 Track titles, keys and durations
      - 🖼️ Icon management — autoselect or pick icons via search
      - 🖌️ Cover management — set, import, or auto-search cover art; embed into card metadata
      - 📤 Export / 📥 Import cards
   - 🖥️ Interfaces — CLI, TUI (terminal UI) and a small graphical UI

   For full docs and examples see the project site: https://xkjq.github.io/yoto-up/

   ## 🛠️ Installation

   1. Clone the repository:

   ```bash
   git clone https://github.com/your-repo/yoto-up.git
   ```

   2. Enter the project folder and create a virtualenv:

   ```bash
   cd yoto-up
   python -m venv .venv
   source .venv/bin/activate
   ```

   3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

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

