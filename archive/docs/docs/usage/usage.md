# Usage

## CLI / TUI

Run the terminal UI and CLI tools from the project root after installing dependencies:

```bash
python yoto.py --help
```

Follow on-screen prompts. The TUI uses the Textual library for interactive terminal screens.

## Graphical UI (Flet)

Start the graphical interface (desktop/browser) with:

```bash
python gui.py
```

- Use the Auth tab to authenticate with Yoto (device flow). The app stores short-lived tokens locally in `tokens.json` (see Security notes).
- Use the Playlists tab to fetch and manage your cards.
- Use the Upload tab to select a folder and create a new card or append to an existing card.

## Examples

- Create a new card by selecting a folder with audio files, choose `Create new card`, set a title, and click `Start Upload`.
- Append to an existing card: choose `Add to existing card`, fetch playlists if needed, select the target, then `Start Upload`.

