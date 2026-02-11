## yoto.py — Command-line arguments

### Table of contents

- [Global options](#global-options-callback)
- [Commands](#commands)
  - [create_content](#create_content)
  - [list_cards](#list_cards)
  - [delete_card](#delete_card)
  - [delete_cards](#delete_cards)
  - [get_card](#get_card)
  - [export_card](#export_card)
  - [edit_card](#edit_card)
  - [export_cards](#export_cards)
  - [import_card](#import_card)
  - [versions](#versions)
  - [create_card_from_folder](#create_card_from_folder)
  - [get_public_icons](#get_public_icons)
  - [get_user_icons](#get_user_icons)
  - [search_icons](#search_icons)
  - [search_yotoicons](#search_yotoicons)
  - [find_best_icons](#find_best_icons)
  - [upload_cover_image](#upload_cover_image)
  - [get_devices](#get_devices)
  - [get_device_status](#get_device_status)
  - [get_device_config](#get_device_config)
  - [paths](#paths)
  - [reset-auth](#reset-auth-command-name-reset-auth)
  - [fix_card](#fix_card)
  - [merge_chapters](#merge_chapters)
  - [expand_all_tracks](#expand_all_tracks)
  - [gui](#gui)

This page lists the CLI commands and options exposed by `yoto.py` in this repository. For general help run:

```
python yoto.py --help
python yoto.py <command> --help
```

### Global options (callback)

- `--client-id`, `-c` (string)
  - Default: `RslORm04nKbhf04qb91r2Pxwjsn3Hnd5`
  - Description: Yoto client ID

- `--cache-requests`, `-r` (bool)
  - Default: `True`
  - Description: Enable API request caching

- `--cache-max-age-seconds`, `-a` (int)
  - Default: `0`
  - Description: Max cache age in seconds

- `--debug`, `-d` (bool)
  - Default: `False`
  - Description: Enable debug mode


---

### Commands

Below are the commands and their arguments. Required positional arguments are shown first.

#### create_content

Create or update Yoto content.

Usage:

`python yoto.py create-content --title <TITLE> --data <DATA> [--description <DESC>] [--content-type <TYPE>]`

Options:
- `--title` (string) — required
- `--description` (string) — default: `""`
- `--content-type` (string) — default: `"audio"`
- `--data` (string) — required (e.g. URL or text)


#### list_cards

List cards, optionally filtered by name.

Options:
- `--name` (string) — filter by name (optional)
- `--ignore-case` (bool) — default: `True`
- `--regex` (bool) — default: `False`
- `--truncate` (int) — default: `50` (truncate fields)


#### delete_card

Delete a Yoto card by ID.

Usage: `python yoto.py delete-card <id>`

Positional:
- `id` (string)


#### delete_cards

Delete cards by name (interactive confirmation).

Positional:
- `name` (string)

Options:
- `--ignore-case` (bool) — default: `True`
- `--regex` (bool) — default: `False`


#### get_card

Get details of a Yoto card by ID.

Usage: `python yoto.py get-card <card_id> [options]`

Positional:
- `card_id` (string)

Options:
- `--icons` (bool) — default: `True` (render icons in card display)
- `--icons-method` (string) — default: `braille` (`braille` or `blocks`)
- `--braille-scale` (int) — default: `None` (horizontal scale)
- `--braille-dims` (string) — default: `8x4` (WxH)


#### export_card

Export a card to a JSON file.

Positional:
- `card_id` (string)

Options:
- `--path` (string) — default: `cards` (export directory)
- `--include-name` (bool) — default: `True` (include card name in filename)


#### edit_card

Open the rich TUI editor for a card.

Usage: `python yoto.py edit-card <card_id>`

Positional:
- `card_id` (string)


#### export_cards

Export multiple cards to files.

Options:
- `--name` (string) — filter by name
- `--ignore-case` (bool) — default: `True`
- `--regex` (bool) — default: `False`
- `--path` (string) — default: `cards`
- `--include-name` (bool) — default: `True`


#### import_card

Import a saved JSON card file into the server.

Positional:
- `path` (string)


#### versions

Manage local card versions saved by the application.

Usage: `python yoto.py versions <verb> [target] [--path PATH]`

Positional:
- `verb` (string) — one of: `list`, `show`, `preview`, `restore`, `delete`, `delete-all`
- `target` (string, optional) — card id or path to version file (positional)

Options:
- `--path` (string) — path to a specific version file (for show/restore/delete)

Notes: `list` expects a card id; `show`, `preview`, `restore`, `delete` accept either `--path` or the file path as the positional `target`.


#### create_card_from_folder

Create a card from a folder of media files.

Positional:
- `folder` (string) — path to folder containing media files

Options:
- `--title` (string) — optional, default: folder name
- `--loudnorm` (bool) — default: `False` (apply loudness normalization)
- `--poll-interval` (float) — default: `2` (seconds)
- `--max-attempts` (int) — default: `120` (transcoding poll attempts)
- `--files-as-tracks` (bool) — default: `False` (treat files as tracks)
- `--add-to-card` (string) — card id to add tracks to
- `--strip-track-numbers` (bool) — default: `True` (strip leading track numbers)


#### get_public_icons

Options:
- `--show-in-console` (bool) — default: `True`


#### get_user_icons

Options:
- `--show-in-console` (bool) — default: `True`


#### search_icons

Positional:
- `query` (string)

Options:
- `--fields` (string) — default: `title,publicTags` (comma-separated list)


#### search_yotoicons

Positional:
- `tag` (string)

Options:
- `--show-in-console` (bool) — default: `True`
- `--refresh-cache` (bool) — default: `False`


#### find_best_icons

Positional:
- `text` (string)

Options:
- `--include-yotoicons` (bool) — default: `True`
- `--show-in-console` (bool) — default: `True`


#### upload_cover_image

Positional:
- `path` (string)


#### get_devices

No options.


#### get_device_status

Positional:
- `device_id` (string)


#### get_device_config

Positional:
- `device_id` (string)


#### paths

Show the resolved per-user/config/cache paths used by the application.

Options:
- `--json` (bool) — default: `False` — Output the resolved paths as JSON.
- `--clear` (bool) — default: `False` — Delete all user data (tokens, UI state, API caches, icon caches, and saved versions). The command will prompt for confirmation before deleting files and directories.

Notes:
- When `--clear` is used the CLI will attempt to remove the following files (best-effort): tokens file, UI state file, upload icon cache, and API cache file. It will also remove the icon cache directories (official and yotoicons) and the versions directory. Use with caution — this is destructive and irreversible.

Examples:
- Show paths in human-readable form:

```
python yoto.py paths
```

- Output paths as JSON (machine friendly):

```
python yoto.py paths --json
```

- Delete all user data (prompts for confirmation):

```
python yoto.py paths --clear
```


#### reset-auth (command name: `reset-auth`)

Options:
- `--reauth`, `-r` (bool) — default: `False` — Start authentication immediately after reset


#### fix_card

Positional:
- `card_id` (string)

Options:
- `--ensure-chapter-titles` (bool) — default: `True`
- `--ensure-sequential-overlay-labels` (bool) — default: `True`
- `--ensure-sequential-track-keys` (bool) — default: `True`


#### merge_chapters

Positional:
- `card_id` (string)

Options:
- `--reset-overlay-labels` (bool) — default: `True`
- `--sequential-labels` (bool) — default: `True`


#### expand_all_tracks

Positional:
- `card_id` (string)

#### gui

Launches the flet based gui.
---

