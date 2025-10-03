#!/usr/bin/env python3
import re
import typer
from yoto_up.models import Card, CardContent, CardMetadata, Chapter
from yoto_up.tui import EditCardApp
from yoto_up.yoto_api import YotoAPI
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
import difflib
import json
from rich.prompt import Confirm
from pathlib import Path
import asyncio
from typing import Optional, List
import shutil

app = typer.Typer()
console = Console()

api_options = {}


def get_api():
    return YotoAPI(**api_options)


@app.callback()
def main(
    client_id: str = typer.Option(
        "RslORm04nKbhf04qb91r2Pxwjsn3Hnd5", "--client-id", "-c", help="Yoto client ID"
    ),
    cache_requests: bool = typer.Option(
        True, "--cache-requests", "-r", help="Enable API request caching"
    ),
    cache_max_age_seconds: int = typer.Option(
        0, "--cache-max-age-seconds", "-a", help="Max cache age in seconds"
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
):
    global api_options
    api_options = dict(
        client_id=client_id,
        cache_requests=cache_requests,
        cache_max_age_seconds=cache_max_age_seconds,
        debug=debug,
    )


@app.command()
def create_content(
    title: str = typer.Option(..., help="Title of the content"),
    description: str = typer.Option("", help="Description of the content"),
    content_type: str = typer.Option(
        "audio", help="Type of content (e.g. audio, text)"
    ),
    data: str = typer.Option(..., help="Content data (e.g. URL or text)"),
):
    """Create or update Yoto content."""
    API = get_api()
    typer.echo(API.create_or_update_content(title, description, content_type, data))


def get_cards(name, ignore_case, regex):
    API = get_api()
    cards = API.get_myo_content()
    if name:
        if ignore_case:
            cards = [card for card in cards if name.lower() in card.title.lower()]
        elif regex:
            cards = [
                card for card in cards if re.search(name, card.title, re.IGNORECASE)
            ]
    return cards


@app.command()
def list_cards(
    name: str = typer.Option(None, help="Name of the card to filter (optional)"),
    ignore_case: bool = typer.Option(True, help="Ignore case when filtering by name"),
    regex: bool = typer.Option(False, help="Use regex for name filtering"),
    truncate: Optional[int] = typer.Option(
        50, help="Truncate fields to this many characters"
    ),
    table: bool = typer.Option(False, help="Display cards in a table format"),
    include_chapters: bool = typer.Option(False, help="Include chapters and tracks in display"),
):
    cards = get_cards(name, ignore_case, regex)

    if not cards:
        rprint("[bold red]No cards found.[/bold red]")
        return

    if include_chapters:
        full_cards = []
        API = get_api()
        for summary_card in cards:
            try:
                full_card = API.get_card(summary_card.cardId)
                if full_card:
                    full_cards.append(full_card)
                else:
                    full_cards.append(summary_card)
            except Exception:
                full_cards.append(summary_card)
        cards = full_cards

    if table:
        from rich.table import Table

        table = Table(title="Yoto Cards")
        table.add_column("Card ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="magenta")
        table.add_column("Description", style="green")
        for card in cards:
            desc = (
                (card.metadata.description[: truncate - 3] + "...")
                if card.metadata.description and len(card.metadata.description) > truncate
                else (card.metadata.description or "")
            )
            table.add_row(card.cardId, card.title or "", desc)
        console.print(table)
        return
    else:
        for card in cards:
            rprint(
                Panel.fit(
                    card.display_card(truncate_fields_limit=truncate),
                    title=f"[bold green]Card[/bold green]",
                    subtitle=f"[bold cyan]{card.cardId}[/bold cyan]",
                )
            )


@app.command()
def delete_card(id: str):
    """Delete a Yoto card by its ID."""
    API = get_api()
    if not Confirm.ask(
        f"Are you sure you want to delete card with ID '{id}'?", default=False
    ):
        typer.echo("Deletion cancelled.")
        return
    response = API.delete_content(id)
    typer.echo(response)


@app.command()
def delete_cards(
    name: str,
    ignore_case: bool = typer.Option(True, help="Ignore case when filtering by name"),
    regex: bool = typer.Option(False, help="Use regex for name filtering"),
):
    cards = get_cards(name, ignore_case, regex)
    to_delete = cards
    if not to_delete:
        rprint(f"[bold red]No cards found with the name '{name}'.[/bold red]")
        return
    rprint(
        f"[bold yellow]Found {len(to_delete)} cards with the name '{name}':[/bold yellow]"
    )
    for card in to_delete:
        rprint(
            f"- [bold magenta]{card.title}[/bold magenta] ([cyan]ID: {card.cardId}[/cyan])"
        )
    if not Confirm.ask(
        f"[bold red]Are you sure you want to delete all {len(to_delete)} cards named '{name}'?[/bold red]",
        default=False,
    ):
        rprint("[bold green]Deletion cancelled.[/bold green]")
        return
    API = get_api()
    for card in to_delete:
        response = API.delete_content(card.cardId)
        rprint(f"[bold red]Deleted card ID {card.cardId}:[/bold red] {response}")


@app.command()
def get_card(
    card_id: str,
    chapters: bool = typer.Option(True, help="Show chapters and tracks"),
    icons: bool = typer.Option(True, help="Render icons in card display"),
    icons_method: str = typer.Option(
        "braille", help="Icon rendering method: 'braille' or 'blocks'"
    ),
    braille_scale: int = typer.Option(
        None, help="Horizontal scale for braille rendering (integer)"
    ),
    braille_dims: str = typer.Option(
        "8x4", help="Braille character grid dims as WxH, e.g. 8x4"
    ),
):
    """Get details of a Yoto card by its ID."""
    API = get_api()
    card = API.get_card(card_id)
    if card:
        # parse braille_dims
        try:
            w, h = (int(x) for x in braille_dims.split("x"))
        except Exception:
            w, h = 8, 4
        rprint(
            Panel.fit(
                card.display_card(
                    render_icons=icons,
                    api=API,
                    render_method=icons_method,
                    braille_dims=(w, h),
                    braille_x_scale=braille_scale,
                    include_chapters=chapters
                ),
                title="[bold green]Card Details[/bold green]",
                subtitle=f"[bold cyan]{card.cardId}[/bold cyan]",
            )
        )
    else:
        typer.echo(f"Card with ID '{card_id}' not found.")


@app.command()
def export_card(
    card_id: str,
    path: str = typer.Option("cards", help="Path to export JSON file (optional)"),
    include_name: bool = typer.Option(True, help="Include card name in export"),
):
    """Export a Yoto card by its ID to a JSON file."""
    API = get_api()
    try:
        card = API.get_card(card_id)
    except Exception as e:
        typer.echo(f"Error retrieving card with ID '{card_id}': {e}")
        typer.echo("Please check the card ID is correct.")
        raise typer.Exit(code=1)
    export_dir = Path(path)
    export_dir.mkdir(parents=True, exist_ok=True)
    if card:
        if include_name and card.title:
            export_path = (
                Path(path)
                / f"{re.sub(r'[^a-zA-Z0-9_-]', '_', card.title)}_{card_id}.json"
            )
        else:
            export_path = Path(path) / f"card_{card_id}.json"
        try:
            card_data = card.model_dump(exclude_none=True)
        except AttributeError:
            card_data = card.__dict__
        with open(export_path, "w") as f:
            json.dump(card_data, f, indent=2)
        typer.echo(f"Card exported to {export_path}")
    else:
        typer.echo(f"Card with ID '{card_id}' not found.")


@app.command()
def edit_card(card_id: str):
    """Edit a Yoto card by its ID using a rich TUI."""
    API = get_api()
    card = API.get_card(card_id)
    if not card:
        typer.echo(f"Card with ID '{card_id}' not found.")
        raise typer.Exit(code=1)

    def run_tui():
        app = EditCardApp(card, API)
        app.run()
        return getattr(app, "result", None)

    result = run_tui()
    if result:
        typer.echo(f"Card updated: {result.cardId}")
    else:
        typer.echo("Edit cancelled.")


@app.command()
def export_cards(
    name: str = typer.Option(None, help="Name of the card to filter (optional)"),
    ignore_case: bool = typer.Option(True, help="Ignore case when filtering by name"),
    regex: bool = typer.Option(False, help="Use regex for name filtering"),
    path: str = typer.Option("cards", help="Path to export JSON file (optional)"),
    include_name: bool = typer.Option(True, help="Include card name in export"),
):
    API = get_api()
    cards = get_cards(name, ignore_case, regex)
    export_dir = Path(path)
    export_dir.mkdir(parents=True, exist_ok=True)
    if not cards:
        typer.echo("No cards found.")
        return
    for summary_card in cards:
        card = API.get_card(summary_card.cardId)
        if include_name and card.title:
            export_path = (
                export_dir
                / f"{re.sub(r'[^a-zA-Z0-9_-]', '_', card.title)}_{card.cardId}.json"
            )
        else:
            export_path = export_dir / f"card_{card.cardId}.json"
        try:
            card_data = card.model_dump(exclude_none=True)
        except AttributeError:
            card_data = card.__dict__
        with open(export_path, "w") as f:
            json.dump(card_data, f, indent=2)
        typer.echo(f"Card exported to {export_path}")


@app.command()
def import_card(path: str):
    API = get_api()
    with open(path, "r") as f:
        s = json.loads(f.read())
        card_data = Card.model_validate(s)
        print(card_data)
        card_data.cardId = None
    card = API.create_or_update_content(card_data, return_card=True)
    typer.echo(f"Card imported from {path}: {card.cardId}")


@app.command()
def paths(
    json_out: bool = typer.Option(False, "--json", help="Output paths as JSON"),
    clear: bool = typer.Option(
        False,
        "--clear",
        help="Delete all user data (tokens, caches, UI state, icon caches, versions).",
    ),
):
    """Show the resolved per-user/config/cache paths used by the application."""
    try:
        import yoto_up.paths as paths_mod
    except Exception as e:
        typer.echo(f"Failed to import yoto_up.paths: {e}")
        raise typer.Exit(code=1)

    data = {
        "FLET_APP_STORAGE_DATA": str(paths_mod.FLET_APP_STORAGE_DATA)
        if getattr(paths_mod, "FLET_APP_STORAGE_DATA", None)
        else None,
        "BASE_DATA_DIR": str(getattr(paths_mod, "_BASE_DATA_DIR", "")),
        "BASE_CONFIG_DIR": str(getattr(paths_mod, "_BASE_CONFIG_DIR", "")),
        "BASE_CACHE_DIR": str(getattr(paths_mod, "_BASE_CACHE_DIR", "")),
        "TOKENS_FILE": str(getattr(paths_mod, "TOKENS_FILE", "")),
        "UI_STATE_FILE": str(getattr(paths_mod, "UI_STATE_FILE", "")),
        "OFFICIAL_ICON_CACHE_DIR": str(
            getattr(paths_mod, "OFFICIAL_ICON_CACHE_DIR", "")
        ),
        "YOTOICONS_CACHE_DIR": str(getattr(paths_mod, "YOTOICONS_CACHE_DIR", "")),
        "UPLOAD_ICON_CACHE_FILE": str(getattr(paths_mod, "UPLOAD_ICON_CACHE_FILE", "")),
        "API_CACHE_FILE": str(getattr(paths_mod, "API_CACHE_FILE", "")),
        "VERSIONS_DIR": str(getattr(paths_mod, "VERSIONS_DIR", "")),
    }
    # If requested, clear the user data paths
    if clear:
        if not Confirm.ask(
            "Are you sure you want to DELETE ALL user data (tokens, ui state, caches, icon caches, versions)?",
            default=False,
        ):
            typer.echo("Cancelled.")
            return
        # Files to remove (best-effort)
        files = [
            getattr(paths_mod, "TOKENS_FILE", None),
            getattr(paths_mod, "UI_STATE_FILE", None),
            getattr(paths_mod, "UPLOAD_ICON_CACHE_FILE", None),
            getattr(paths_mod, "API_CACHE_FILE", None),
        ]
        dirs = [
            getattr(paths_mod, "OFFICIAL_ICON_CACHE_DIR", None),
            getattr(paths_mod, "YOTOICONS_CACHE_DIR", None),
            getattr(paths_mod, "VERSIONS_DIR", None),
        ]
        removed = {"files": [], "dirs": [], "errors": []}
        for f in files:
            try:
                if f is None:
                    continue
                p = Path(f)
                if p.exists():
                    p.unlink()
                    removed["files"].append(str(p))
            except Exception as e:
                removed["errors"].append(f"failed to remove file {f}: {e}")
        for d in dirs:
            try:
                if d is None:
                    continue
                p = Path(d)
                if p.exists() and p.is_dir():
                    shutil.rmtree(p)
                    removed["dirs"].append(str(p))
            except Exception as e:
                removed["errors"].append(f"failed to remove dir {d}: {e}")
        typer.echo("Clear operation complete. Removed:")
        for r in removed["files"]:
            typer.echo(f"  file: {r}")
        for r in removed["dirs"]:
            typer.echo(f"  dir: {r}")
        for e in removed["errors"]:
            typer.echo(f"  ERROR: {e}")
        return

    if json_out:
        typer.echo(json.dumps(data, indent=2))
    else:
        for k, v in data.items():
            typer.echo(f"{k}: {v}")


@app.command()
def versions(
    verb: str = typer.Argument(
        ..., help="Action: list|show|preview|restore|delete|delete-all"
    ),
    target: Optional[str] = typer.Argument(
        None, help="Card id or path to version file (positional)"
    ),
    path: str = typer.Option(
        None, help="Path to a specific version file (for show/restore/delete)"
    ),
):
    """Manage local card versions saved by the application.

    The command accepts a verb and either a card id (for `list` and `delete-all`) or a
    path to a saved version file (for `show`, `preview`, `restore`, `delete`).

    Examples:
        # list versions for a card id
        python yoto.py versions list 28LBG

        # show a saved version JSON (positional path)
        python yoto.py versions show .card_versions/28LBG/20250911T204616Z.json

        # preview a saved version
        python yoto.py versions preview .card_versions/28LBG/20250911T204616Z.json

        # restore a saved version to the server (will ask for confirmation)
        python yoto.py versions restore .card_versions/28LBG/20250911T204616Z.json

    Actions:
        list: list version files for a card id
        show: print the JSON for a specific version file (positional path or --path)
        preview: render a brief preview of a saved card version
        restore: POST the version back to the API to restore content (positional path or --path)
        delete: delete a specific version file (positional path or --path)
        delete-all: remove all saved versions for the given card id
    """
    API = get_api()
    verb_l = (verb or "").lower()
    try:
        # If the user passed a path as the positional target, prefer it for show/preview/restore/delete
        effective_path = None
        if path:
            effective_path = Path(path)
        elif target:
            t = Path(target)
            if (
                t.exists()
                or "/" in target
                or target.startswith(".")
                or target.endswith(".json")
            ):
                effective_path = t

        if verb_l == "list":
            card_id = target
            if not card_id:
                typer.echo(
                    "Please provide a card id (or title-derived id) to list versions"
                )
                raise typer.Exit(code=1)
            files = API.list_versions(card_id)
            if not files:
                typer.echo("No versions found")
                return
            for p in files:
                typer.echo(str(p))
            return

        if verb_l == "show":
            if not effective_path:
                typer.echo(
                    "Please provide --path to a version file or pass the file path as the positional target"
                )
                raise typer.Exit(code=1)
            data = API.load_version(effective_path)
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
            return

        if verb_l == "preview":
            if not effective_path:
                typer.echo(
                    "Please provide --path to a version file or pass the file path as the positional target"
                )
                raise typer.Exit(code=1)
            card = Card.model_validate(API.load_version(effective_path))
            # If this looks like a full card, try to pretty print key fields
            if card:
                rprint(
                    Panel.fit(
                        card.display_card(truncate_fields_limit=100),
                        title=f"[bold green]Card Preview[/bold green]",
                        subtitle=f"[bold cyan]{getattr(card, 'cardId', getattr(card, 'id', 'unknown'))}[/bold cyan]",
                    )
                )

            return

        if verb_l == "restore":
            if not effective_path:
                typer.echo(
                    "Please provide --path to a version file to restore or pass it as the positional target"
                )
                raise typer.Exit(code=1)
            p = effective_path
            if not p.exists():
                typer.echo(f"File not found: {p}")
                raise typer.Exit(code=1)
            if not Confirm.ask(
                f"Are you sure you want to restore version {p.name}? This will POST to the server.",
                default=False,
            ):
                typer.echo("Cancelled")
                return
            restored = API.restore_version(p, return_card=True)
            typer.echo(
                f"Restored card: {getattr(restored, 'cardId', getattr(restored, 'id', 'unknown'))}"
            )
            return

        if verb_l == "delete":
            if not effective_path:
                typer.echo(
                    "Please provide --path to a version file to delete or pass it as the positional target"
                )
                raise typer.Exit(code=1)
            p = effective_path
            if not p.exists():
                typer.echo(f"File not found: {p}")
                raise typer.Exit(code=1)
            if not Confirm.ask(f"Delete version file {p}?", default=False):
                typer.echo("Cancelled")
                return
            p.unlink()
            typer.echo(f"Deleted {p}")
            return

        if verb_l == "delete-all":
            if not card_id:
                typer.echo("Please provide a card id to delete all versions for")
                raise typer.Exit(code=1)
            files = API.list_versions(card_id)
            if not files:
                typer.echo("No versions to delete")
                return
            if not Confirm.ask(
                f"Are you sure you want to delete ALL {len(files)} version files for '{card_id}'?",
                default=False,
            ):
                typer.echo("Cancelled")
                return
            for p in files:
                try:
                    p.unlink()
                except Exception:
                    pass
            typer.echo(f"Deleted {len(files)} files for {card_id}")
            return

        typer.echo(f"Unknown verb: {verb}")
        raise typer.Exit(code=2)
    except Exception as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


@app.command()
def create_card_from_folder(
    folder: str = typer.Argument(..., help="Path to folder containing media files"),
    title: str = typer.Option(
        None, help="Title for the new card, if not provided, folder name is used"
    ),
    loudnorm: bool = typer.Option(
        False, help="Apply loudness normalization to uploads"
    ),
    poll_interval: float = typer.Option(2, help="Transcoding poll interval (seconds)"),
    max_attempts: int = typer.Option(120, help="Max transcoding poll attempts"),
    files_as_tracks: bool = typer.Option(
        False, help="Treat each file as a separate track"
    ),
    add_to_card: str = typer.Option(None, help="Add tracks to an existing card"),
    strip_track_numbers: bool = typer.Option(
        True, help="Strip leading track numbers from filenames"
    ),
):
    import asyncio

    async def async_main():
        API = get_api()
        folder_path = Path(folder)

        card_title = title
        if card_title is None:
            # Use the folder name as title if not provided
            card_title = folder_path.name
        if not folder_path.exists() or not folder_path.is_dir():
            typer.echo(f"[bold red]Folder not found: {folder}[/bold red]")
            raise typer.Exit(code=1)
        media_files = sorted(
            [
                f
                for f in folder_path.iterdir()
                if f.is_file()
                and f.suffix.lower() in {".mp3", ".wav", ".aac", ".m4a", ".ogg"}
            ]
        )
        if not media_files:
            typer.echo(f"[bold red]No media files found in folder: {folder}[/bold red]")
            raise typer.Exit(code=1)

        existing_card = None
        if add_to_card:
            typer.echo(f"Adding tracks to existing card: {add_to_card}")
            existing_card = API.get_card(add_to_card)
            if not existing_card:
                typer.echo(f"[bold red]Card not found: {add_to_card}[/bold red]")
                raise typer.Exit(code=1)

        if files_as_tracks:
            typer.echo(f"Creating single chapter with {len(media_files)} tracks...")
            if existing_card:
                tracks = existing_card.content.chapters[0].tracks
            else:
                tracks = []
                chapter = Chapter(title="Chapter 1", key="01", tracks=tracks)
                chapters = [chapter]
            transcoded_audios = await API.upload_and_transcode_many_async(
                media_files,
                loudnorm=loudnorm,
                poll_interval=poll_interval,
                max_attempts=max_attempts,
                show_progress=True,
            )
            for idx, (media_file, transcoded_audio) in enumerate(
                zip(media_files, transcoded_audios), len(tracks) + 1
            ):
                track_title = media_file.stem
                if strip_track_numbers:
                    track_title = re.sub(r"^\d+\s*-\s*", "", track_title)
                track = API.get_track_from_transcoded_audio(
                    transcoded_audio,
                    track_details={"title": track_title, "key": f"{idx:02d}"},
                )
                tracks.append(track)
            # chapters.tracks.append(tracks)
            chapters[-1].tracks = tracks
        else:
            if existing_card:
                chapters = existing_card.content.chapters
            else:
                chapters = []
            transcoded_audios = await API.upload_and_transcode_many_async(
                media_files,
                loudnorm=loudnorm,
                poll_interval=poll_interval,
                max_attempts=max_attempts,
                show_progress=True,
            )
            for idx, (media_file, transcoded_audio) in enumerate(
                zip(media_files, transcoded_audios), len(chapters) + 1
            ):
                chapter_title = media_file.stem
                if strip_track_numbers:
                    chapter_title = re.sub(r"^\d+\s*-\s*", "", chapter_title)
                chapters.append(
                    API.get_chapter_from_transcoded_audio(
                        transcoded_audio,
                        chapter_details={"title": chapter_title, "key": f"{idx:02d}"},
                    )
                )
        if not chapters:
            typer.echo("[bold red]No chapters created from media files.[/bold red]")
            raise typer.Exit(code=1)

        if existing_card:
            result = API.create_or_update_content(existing_card, return_card=True)
        else:
            card_content = CardContent(chapters=chapters)
            card_metadata = CardMetadata()
            new_card = Card(
                title=card_title, content=card_content, metadata=card_metadata
            )
            typer.echo(f"Creating card '{card_title}' with {len(chapters)} chapters...")
            result = API.create_or_update_content(new_card, return_card=True)
        typer.echo(f"[bold green]Card created: {result.cardId}[/bold green]")
        print(result.model_dump_json(exclude_none=True))

    asyncio.run(async_main())


@app.command()
def get_public_icons(show_in_console: bool = True):
    API = get_api()
    icons = API.get_public_icons(show_in_console=show_in_console)
    if not icons:
        typer.echo("[bold red]No public icons found.[/bold red]")
        raise typer.Exit(code=1)


@app.command(name="intro-outro")
def intro_outro(
    files: List[str] = typer.Argument(..., help="Audio files to analyze"),
    side: str = typer.Option("intro", "--side", "-s", help="Which side to analyze: intro or outro"),
    seconds: float = typer.Option(10.0, "--seconds", "-S", help="Max seconds to inspect at the chosen side"),
    window_seconds: float = typer.Option(0.1, "--window", help="Window size (seconds) used by per-window analyzer"),
    sr: int = typer.Option(22050, "--sr", help="Sample rate used for feature extraction"),
    n_mfcc: int = typer.Option(13, "--n-mfcc", help="Number of MFCC coefficients to compute"),
    threshold: float = typer.Option(0.99, "--threshold", "-t", help="Per-window similarity threshold (0..1)"),
    min_files_fraction: float = typer.Option(0.9, "--min-fraction", help="Minimum fraction of files required to declare a common prefix"),
):
    """Analyze a set of audio files to find common intro/outro segments using the per-window analyzer (same as GUI).

    Example:
      python yoto.py intro-outro file1.mp3 file2.mp3 --side intro --seconds 8 --window 0.1
    """
    try:
        from yoto_up.yoto_app import intro_outro as io_mod
    except Exception as e:
        typer.echo(f"Failed to import intro_outro analysis module: {e}")
        raise typer.Exit(code=1)

    try:
        result = io_mod.per_window_common_prefix(
            paths=files,
            side=side,
            max_seconds=seconds,
            window_seconds=window_seconds,
            sr=sr,
            n_mfcc=n_mfcc,
            similarity_threshold=threshold,
            min_files_fraction=min_files_fraction,
        )
    except Exception as e:
        typer.echo(f"Analysis failed: {e}")
        raise typer.Exit(code=1)

    # Print a concise summary similar to GUI, using rich for nicer formatting
    tpl = result.get("template") or ""
    windows_matched = int(result.get("windows_matched", 0) or 0)
    seconds_matched = float(result.get("seconds_matched", 0.0) or 0.0)
    per_window_frac = result.get("per_window_frac", []) or []
    per_file_per_window = result.get("per_file_per_window", {}) or {}

    # Summary panel
    from rich.panel import Panel
    from rich.table import Table
    from rich.align import Align
    summary_lines = [f"Seconds matched: {seconds_matched}", f"Windows matched: {windows_matched}"]
    if tpl:
        summary_lines.insert(0, f"Template: {tpl}")
    console.print(Panel('\n'.join(summary_lines), title="Intro/Outro Analysis", subtitle=f"side={side} seconds={seconds} window={window_seconds}"))

    # Per-window fractions (show up to first 20 windows)
    if per_window_frac:
        try:
            display_vals = per_window_frac[:20]
            frac_text = ', '.join(f"{float(v):.3f}" for v in display_vals)
            if len(per_window_frac) > 20:
                frac_text += f", ... (+{len(per_window_frac)-20} more)"
            console.print(Panel(frac_text, title=f"Per-window fraction (first {min(20, len(per_window_frac))})"))
        except Exception:
            pass

    # Build table of per-file mean scores
    tbl = Table(title="Per-file mean scores", show_lines=False)
    tbl.add_column("File", style="cyan", overflow="fold")
    tbl.add_column("Mean", style="magenta", justify="right")
    tbl.add_column("Bar", style="green")

    # helper to render a small bar for score
    def score_bar(mean: float, width: int = 20) -> str:
        try:
            n = max(0, min(width, int(round(mean * width))))
            return '█' * n + ' ' * (width - n)
        except Exception:
            return ''

    # Compute mean for each file and add to table sorted by mean desc
    rows = []
    for p, arr in per_file_per_window.items():
        try:
            if windows_matched > 0:
                vals = list(arr)[:windows_matched]
                mean = sum(float(v or 0.0) for v in vals) / float(len(vals) if vals else 1)
            else:
                mean = 0.0
        except Exception:
            mean = 0.0
        rows.append((p, mean))

    for p, mean in sorted(rows, key=lambda r: r[1], reverse=True):
        tbl.add_row(p, f"{mean:.3f}", score_bar(mean))

    console.print(tbl)


@app.command()
def get_user_icons(show_in_console: bool = True):
    API = get_api()
    icons = API.get_user_icons(show_in_console=show_in_console)
    if not icons:
        typer.echo("[bold red]No user icons found.[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def search_icons(query: str, fields: str = "title,publicTags"):
    API = get_api()
    field_list = [f.strip() for f in fields.split(",") if f.strip()]
    results = API.search_cached_icons(query, field_list, show_in_console=True)
    if not results:
        typer.echo("[bold red]No matching icons found.[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def search_yotoicons(
    tag: str, show_in_console: bool = True, refresh_cache: bool = False
):
    API = get_api()
    icons = API.search_yotoicons(
        tag, show_in_console=show_in_console, refresh_cache=refresh_cache
    )
    if not icons:
        typer.echo(f"[bold red]No icons found for tag '{tag}'.[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def find_best_icons(
    text: str, include_yotoicons: bool = True, show_in_console: bool = True
):
    API = get_api()
    icons = API.find_best_icons_for_text(
        text, include_yotoicons=include_yotoicons, show_in_console=show_in_console
    )
    if not icons:
        typer.echo(f"[bold red]No matching icons found for text: {text}[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def upload_cover_image(path: str):
    API = get_api()
    result = API.upload_cover_image(path)
    if not result:
        typer.echo(f"[bold red]Failed to upload cover image: {path}[/bold red]")
        raise typer.Exit(code=1)
    typer.echo(f"[bold green]Cover image uploaded successfully: {result}[/bold green]")


@app.command()
def get_devices():
    API = get_api()
    devices = API.get_devices()
    if not devices:
        typer.echo("[bold red]No devices found.[/bold red]")
        raise typer.Exit(code=1)
    for device in devices:
        panel_text = (
            f"[bold magenta]{getattr(device, 'name', '')}[/bold magenta]\n"
            f"[cyan]ID:[/] [bold]{getattr(device, 'deviceId', '')}[/bold]\n"
            f"[green]Type:[/] {getattr(device, 'deviceType', '')}\n"
            f"[white]Description:[/] {getattr(device, 'description', '')}\n"
            f"[blue]Online:[/] {getattr(device, 'online', '')}\n"
            f"[blue]Family:[/] {getattr(device, 'deviceFamily', '')}\n"
            f"[blue]Group:[/] {getattr(device, 'deviceGroup', '')}\n"
            f"[yellow]Channel:[/] {getattr(device, 'releaseChannel', '')}\n"
        )
        rprint(
            Panel.fit(
                panel_text,
                title=f"[bold green]Device[/bold green]",
                subtitle=f"[bold cyan]{getattr(device, 'deviceId', '')}[/bold cyan]",
            )
        )


@app.command()
def get_device_status(device_id: str):
    API = get_api()
    device = API.get_device_status(device_id)
    rprint(Panel.fit(device.display_device_status()))


@app.command()
def get_device_config(device_id: str):
    API = get_api()
    config = API.get_device_config(device_id)
    print(config)
    rprint(Panel.fit(config.display_device_config()))


@app.command(name="reset-auth")
def reset_auth(
    reauth: bool = typer.Option(
        False, "--reauth", "-r", help="Start authentication immediately after reset"
    ),
):
    """Reset stored authentication tokens (delete local token file) and optionally start authentication."""
    API = get_api()
    API.reset_auth()

    if reauth:
        typer.echo("Starting authentication...")
        try:
            API.authenticate()
            typer.echo("Authentication complete.")
        except Exception as e:
            typer.echo(f"Authentication failed: {e}")
            raise typer.Exit(code=1)
    else:
        typer.echo(
            "Authentication reset. Run any command to trigger authentication or run 'yoto.py reset-auth --reauth' to authenticate now."
        )


@app.command()
def fix_card(
    card_id: str,
    ensure_chapter_titles: bool = True,
    ensure_sequential_overlay_labels: bool = True,
    ensure_sequential_track_keys: bool = True,
) -> Card:
    """
    Fix common issues in a Yoto card.
    """
    API = get_api()
    card = API.get_card(card_id)
    if not card:
        raise ValueError(f"Card not found: {card_id}")

    # Example fix: Ensure all chapters have titles
    if ensure_chapter_titles:
        for idx, chapter in enumerate(card.content.chapters, 1):
            if not chapter.title:
                chapter.title = f"Chapter {idx}"

    if ensure_sequential_overlay_labels:
        card = API.rewrite_track_fields(
            card, "overlayLabel", sequential=True, reset_every_chapter=True
        )

    if ensure_sequential_track_keys:
        card = API.rewrite_track_fields(card, "key", sequential=True)

    # Update the card on the server
    card = API.create_or_update_content(card, return_card=True)
    rprint(
        Panel.fit(
            card.display_card(),
            title="[bold green]Fixed Card Details[/bold green]",
            subtitle=f"[bold cyan]{card.cardId}[/bold cyan]",
        )
    )


@app.command()
def merge_chapters(
    card_id: str, reset_overlay_labels: bool = True, sequential_labels: bool = True
) -> Card:
    """
    Merges chapters in a card into a single chapter.
    """
    API = get_api()
    card = API.get_card(card_id)
    card = API.merge_chapters(card, reset_overlay_labels=reset_overlay_labels)
    card = API.create_or_update_content(card, return_card=True)
    rprint(
        Panel.fit(
            card.display_card(render_icons=True),
            title="[bold green]Converted Card Details[/bold green]",
            subtitle=f"[bold cyan]{card.cardId}[/bold cyan]",
        )
    )


@app.command()
def expand_all_tracks(card_id: str):
    """
    Expands all tracks in a card into individual chapters.
    """
    API = get_api()
    card = API.get_card(card_id)
    card = API.expand_all_tracks_to_chapters(card)
    card = API.create_or_update_content(card, return_card=True)
    rprint(
        Panel.fit(
            card.display_card(render_icons=True),
            title="[bold green]Converted Card Details[/bold green]",
            subtitle=f"[bold cyan]{card.cardId}[/bold cyan]",
        )
    )


@app.command()
def gui():
    """Launch the GUI application."""
    # Try to start the Flet GUI by importing the local `gui` module and
    # invoking ft.app with its `main` target. If that fails (missing deps
    # or running in an environment where direct import is problematic),
    # fall back to launching the script with the current Python interpreter.
    try:
        import importlib

        gui_mod = importlib.import_module("gui")
        try:
            import flet as ft

            # Use the same assets/upload dirs as gui.py
            ft.app(
                target=gui_mod.main, assets_dir="assets", upload_dir="assets/uploads"
            )
            return
        except Exception as e:
            # Flet import or app start failed; fall back to subprocess
            print(
                f"Failed to start GUI via flet API: {e}; falling back to running gui.py"
            )
    except Exception:
        # Importing gui failed; fall back to running the script directly
        pass

    # Subprocess fallback
    try:
        import subprocess
        import sys

        script_path = Path(__file__).parent / "gui.py"
        subprocess.run([sys.executable, str(script_path)])
    except Exception as e:
        print(f"Failed to launch GUI subprocess: {e}")


if __name__ == "__main__":
    app()
