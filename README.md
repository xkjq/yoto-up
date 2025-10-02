# Yoto-UP

<img src="art.jpeg" alt="Artwork preview" style="max-width:100%;height:auto;">


A multipurpose set of command-line, terminal UI, and graphical tools for managing your Yoto content.  

Features include content organization, device management, and easy integration with Yoto services.

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
   - 🔊 Audio preparation — normalize volume levels, auto-trim silence, and apply basic level adjustments before upload
   - 🖼️ Icon editor — feature rich editor with text and image stamping

   For full docs and examples see the project site: https://xkjq.github.io/yoto-up/

   ### Command Line First

   Leveraging Python libraries like Typer, Rich, and Textual for a vibrant, user-friendly command-line experience. Creating and managing cards with text has never been easier or more colorful 🌈.

   ### Graphical Interface Included

   For tasks better suited to a visual workflow, Yoto-UP also provides a GUI built with Flet, making advanced operations accessible and sometimes even intuitive.

   ## 🛠️ Installation

   ### With uv(x)

   1. [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
   
   2. Run with uvx _(without installing if you just want to try it out)_<sup>[1]</sup>

      Command line
      ```bash
      uvx --from "git+https://github.com/xkjq/yoto-up.git@main#egg=yoto-up" yoto [command]
      ```

      GUI
      ```bash
      uvx --from "git+https://github.com/xkjq/yoto-up.git@main#egg=yoto-up[gui]" yoto gui
      ```

   3. If you like it, install with uv tool<sup>[2]</sup>
      ```bash
      uv tool install "git+https://github.com/xkjq/yoto-up.git@main#egg=yoto-up"
      ```
      This should add the command `yoto` to your path, test it out with
      ```bash
      yoto --help
      ```

      or if you want the GUI
      ```bash
      uv tool install "git+https://github.com/xkjq/yoto-up.git@main#egg=yoto-up[gui]"
      ```
      Then run

      ```bash
      yoto gui
      ```

[1] uvx allows you to run a python tool/package without installation (by creating a temporary isolated environment).

[2] uv tool also supports upgrading the tool once installed, see [their docs](https://docs.astral.sh/uv/guides/tools/#installing-tools) for more information.
      

   ### From source

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

   For more details please see the (docs)[https://xkjq.github.io/yoto-up/]

   ### CLI / TUI
   • Start the CLI (lists commands):

   ```bash
   python yoto.py --help
   ```

   • Open the terminal editor for a card:

   ```bash
   python yoto.py edit-card <CARD_ID>
   ```

   [![asciicast](https://asciinema.org/a/tYjCFv9kBx8cyCVv1sUSXOCoC.svg)](https://asciinema.org/a/tYjCFv9kBx8cyCVv1sUSXOCoC)
   [![asciicast](https://asciinema.org/a/ebXKat85slfP1ayc76wWJycsB.svg)](https://asciinema.org/a/ebXKat85slfP1ayc76wWJycsB)

   ### GUI

   ```bash
   python gui.py
   ```

   or 

   ```bash
   flet run gui.py
   ```

   or

   ```bash
   python yoto.py gui
   ```


   ## 📜 License

   MIT — see `LICENSE` for details.

