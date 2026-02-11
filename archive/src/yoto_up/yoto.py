#!/usr/bin/env python3
import re
import typer
from yoto_up.models import Card, CardContent, CardMetadata, Chapter
from yoto_up.tui import EditCardApp
from yoto_up.yoto_api import YotoAPI
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import difflib
import json
from rich.prompt import Confirm
from pathlib import Path
import asyncio
from typing import Optional, List
from typing import get_origin, get_args, get_type_hints
import typing
import shutil
import os
import tempfile
import math
import sys
import pydantic

app = typer.Typer()
console = Console()

api_options = {}


def get_api():
    return YotoAPI(**api_options)


def analyze_gain_requirements(paths: List[str], target_lufs: float = -16.0, strategy: str = 'auto', target_peak: float = 0.9):
    """Perform a pre-adjustment analysis for the given audio files.

    Returns a dict mapping filepath -> {lufs, max_amp, avg_amp, recommended_gain_db}.
    If strategy == 'lufs', recommendation is target_lufs - file_lufs when LUFS is available; files without LUFS
    will have recommended_gain_db set to None.
    If strategy == 'peak', recommendation is calculated using peak-based estimation (target_peak / max_amp).
    If strategy == 'auto' (default), prefer LUFS when available, otherwise fall back to peak estimation.
    """
    try:
        from yoto_up.waveform_utils import batch_audio_stats
    except Exception:
        raise RuntimeError("waveform_utils unavailable; cannot analyze audio")

    waveform_cache = {}
    stats = batch_audio_stats(paths, waveform_cache)
    plan = {}
    for audio, max_amp, avg_amp, lufs, ext, filepath in stats:
        rec_gain = None
        # Strategy: 'auto' prefers LUFS when available, 'lufs' requires LUFS, 'peak' uses peak
        if strategy == 'auto':
            if lufs is not None:
                rec_gain = float(target_lufs) - float(lufs)
            else:
                try:
                    peak = float(max_amp) if max_amp is not None else None
                except Exception:
                    peak = None
                if peak and peak > 0:
                    rec_gain = 20.0 * math.log10(target_peak / float(peak))
                else:
                    rec_gain = None
        elif strategy == 'lufs':
            if lufs is not None:
                rec_gain = float(target_lufs) - float(lufs)
            else:
                rec_gain = None
        elif strategy == 'peak':
            try:
                peak = float(max_amp) if max_amp is not None else None
            except Exception:
                peak = None
            if peak and peak > 0:
                rec_gain = 20.0 * math.log10(target_peak / float(peak))
            else:
                rec_gain = None
        else:
            # unknown strategy -> behave like auto
            if lufs is not None:
                rec_gain = float(target_lufs) - float(lufs)
            else:
                try:
                    peak = float(max_amp) if max_amp is not None else None
                except Exception:
                    peak = None
                if peak and peak > 0:
                    rec_gain = 20.0 * math.log10(target_peak / float(peak))
                else:
                    rec_gain = None
        plan[filepath] = {
            'lufs': (float(lufs) if lufs is not None else None),
            'max_amp': (float(max_amp) if max_amp is not None else None),
            'avg_amp': (float(avg_amp) if avg_amp is not None else None),
            'recommended_gain_db': (float(rec_gain) if rec_gain is not None else None),
            'ext': ext,
        }
    return plan


def apply_gain_plan(plan: dict, out_dir: str, dry_run: bool = False, progress_callback=None):
    """Apply gain adjustments described by `plan` to files, writing to out_dir.

    Returns list of written paths (or planned paths in dry-run).
    """
    try:
        from pydub import AudioSegment
    except Exception:
        raise RuntimeError("pydub is required to apply gain adjustments")

    os.makedirs(out_dir, exist_ok=True)
    written = []
    total = len(plan)
    for idx, (filepath, info) in enumerate(plan.items()):
        try:
            gain_db = float(info.get('recommended_gain_db', 0.0))
            base, ext = os.path.splitext(os.path.basename(filepath))
            tag = f"_norm_{int(gain_db*100)}"
            dest_name = f"{base}{tag}{ext}"
            dest_path = os.path.join(out_dir, dest_name)
            if dry_run:
                written.append(dest_path)
                if progress_callback:
                    try:
                        progress_callback(idx + 1, total)
                    except Exception:
                        pass
                continue
            seg = AudioSegment.from_file(filepath)
            seg = seg.apply_gain(gain_db)
            fmt = ext.lstrip('.') or 'mp3'
            seg.export(dest_path, format=fmt)
            written.append(dest_path)
            if progress_callback:
                try:
                    progress_callback(idx + 1, total)
                except Exception:
                    pass
        except Exception:
            # skip failures but continue
            if progress_callback:
                try:
                    progress_callback(idx + 1, total)
                except Exception:
                    pass
            continue
    return written


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


def get_cards(name, ignore_case, regex, tags: Optional[str] = None, category: Optional[str] = None):
    """Fetch cards and optionally filter by name, tags (comma-separated), and metadata.category.

    - name: substring or regex depending on flags
    - tags: comma-separated list; card must include ALL provided tags (in top-level tags or metadata.tags)
    - category: category string to match against metadata.category (honors ignore_case)
    """
    API = get_api()
    cards = API.get_myo_content()

    # If caller asked to filter by tags or category, the summary objects returned
    # by get_myo_content() may omit nested metadata/tags. In that case fetch
    # full card objects so filters can inspect metadata reliably.
    if (tags is not None or category is not None) and cards:
        try:
            full_cards = []
            for c in cards:
                try:
                    full = API.get_card(getattr(c, 'cardId', None))
                    full_cards.append(full or c)
                except Exception:
                    full_cards.append(c)
            cards = full_cards
        except Exception:
            # fallback: leave summary cards in place
            pass

    # Filter by name (existing behavior)
    if name:
        if ignore_case:
            cards = [card for card in cards if card.title and name.lower() in (card.title or '').lower()]
        elif regex:
            cards = [card for card in cards if card.title and re.search(name, card.title, re.IGNORECASE)]

    # Filter by category. Supports exact match or regex when `regex` is True.
    if category is not None:
        if regex:
            try:
                cre = re.compile(category, re.IGNORECASE if ignore_case else 0)
            except re.error:
                cre = None

            def cat_match(c):
                try:
                    mc = None
                    if getattr(c, 'metadata', None):
                        mc = getattr(c.metadata, 'category', None)
                    if mc is None:
                        return False
                    if cre is None:
                        return (str(mc).lower() == category.lower()) if ignore_case else (str(mc) == category)
                    return bool(cre.search(str(mc)))
                except Exception:
                    return False

        else:
            target = category.lower() if ignore_case else category

            def cat_match(c):
                try:
                    mc = None
                    if getattr(c, 'metadata', None):
                        mc = getattr(c.metadata, 'category', None)
                    if mc is None:
                        return False
                    return str(mc).lower() == target if ignore_case else str(mc) == target
                except Exception:
                    return False

        cards = [c for c in cards if cat_match(c)]

    # Filter by tags (comma-separated). By default match ANY of the tags. If regex flag is set,
    # treat each requested tag as a regex and match against found tags.
    if tags is not None:
        wanted_raw = [t.strip() for t in tags.split(',') if t.strip()]

        def has_any_tag(c):
            try:
                found = []
                if getattr(c, 'tags', None):
                    found.extend([t for t in c.tags if t])
                if getattr(c, 'metadata', None) and getattr(c.metadata, 'tags', None):
                    found.extend([t for t in c.metadata.tags if t])
                if not found:
                    return False
                if regex:
                    # any requested regex must match at least one found tag
                    for pat in wanted_raw:
                        try:
                            cre = re.compile(pat, re.IGNORECASE if ignore_case else 0)
                        except re.error:
                            # invalid regex -> skip
                            continue
                        for f in found:
                            if cre.search(str(f)):
                                return True
                    return False
                else:
                    found_l = [str(x).lower() for x in found if x]
                    wanted_l = [w.lower() for w in wanted_raw]
                    # any-of semantics: return True if any wanted tag is present
                    return any(w in found_l for w in wanted_l)
            except Exception:
                return False

        cards = [c for c in cards if has_any_tag(c)]

    return cards


@app.command()
def list_cards(
    name: str = typer.Option(None, help="Name of the card to filter (optional)"),
    ignore_case: bool = typer.Option(True, help="Ignore case when filtering by name"),
    regex: bool = typer.Option(False, help="Use regex for name filtering"),
    tags: Optional[str] = typer.Option(None, help="Comma-separated list of tags to filter by (card must include all)"),
    category: Optional[str] = typer.Option(None, help="Filter by metadata.category"),
    truncate: Optional[int] = typer.Option(
        50, help="Truncate fields to this many characters"
    ),
    table: bool = typer.Option(False, help="Display cards in a table format"),
    include_chapters: bool = typer.Option(False, help="Include chapters and tracks in display"),
):
    cards = get_cards(name, ignore_case, regex, tags=tags, category=category)

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
        rich_table = Table(title="Yoto Cards")
        rich_table.add_column("Card ID", style="cyan", no_wrap=True)
        rich_table.add_column("Title", style="magenta")
        rich_table.add_column("Description", style="green")
        for card in cards:
            desc = (
                (card.metadata.description[: truncate - 3] + "...")
                if card.metadata.description and len(card.metadata.description) > truncate
                else (card.metadata.description or "")
            )
            rich_table.add_row(card.cardId, card.title or "", desc)
        console.print(rich_table)
        return
    else:
        for card in cards:
            rprint(
                Panel.fit(
                    card.display_card(truncate_fields_limit=truncate, include_chapters=include_chapters),
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
    tags: Optional[str] = typer.Option(None, help="Comma-separated tags to filter deletion (optional)"),
    category: Optional[str] = typer.Option(None, help="Category to filter deletion (optional)"),
):
    cards = get_cards(name, ignore_case, regex, tags=tags, category=category)
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
    show_schema: bool = typer.Option(False, "--schema", help="Show the Card schema (paths, types) and values for this card"),
):
    """Get details of a Yoto card by its ID."""
    API = get_api()
    card = API.get_card(card_id)
    if card:
        if show_schema:
            # Prepare model introspection helpers (copied/adapted from edit_card --list-keys)
            models_module = sys.modules.get('yoto_up.models')
            globalns = models_module.__dict__ if models_module is not None else globals()

            primitive_types = (str, int, float, bool)

            def describe_type(tp) -> str:
                origin = get_origin(tp)
                # Lists
                if origin is list or origin is List:
                    args = get_args(tp)
                    if args:
                        return f"List[{describe_type(args[0])}]"
                    return "List[Unknown]"
                # Union / Optional
                if origin is typing.Union:
                    args = [a for a in get_args(tp) if a is not type(None)]
                    if len(args) == 1:
                        return f"Optional[{describe_type(args[0])}]"
                    return f"Union[{', '.join(describe_type(a) for a in args)}]"
                try:
                    if isinstance(tp, type):
                        if issubclass(tp, pydantic.BaseModel):
                            return tp.__name__
                        if tp in primitive_types:
                            return tp.__name__
                        return getattr(tp, '__name__', str(tp))
                except Exception:
                    pass
                return str(tp)

            def collect_paths(tp, prefix: str = '', depth: int = 0, max_depth: int = 8):
                if depth > max_depth:
                    return []
                origin = get_origin(tp)
                results = []

                # handle lists (List[T] -> prefix[].field)
                if origin is list or origin is List:
                    args = get_args(tp)
                    elem = args[0] if args else None
                    list_path = f"{prefix}[]" if prefix else "[]"
                    if elem is None:
                        results.append((list_path, 'List[Unknown]'))
                        return results

                    try:
                        if isinstance(elem, type) and issubclass(elem, pydantic.BaseModel):
                            results.append((list_path, describe_type(tp)))
                            mf = getattr(elem, 'model_fields', None)
                            if isinstance(mf, dict):
                                items = [(n, f.annotation if hasattr(f, 'annotation') else None) for n, f in mf.items()]
                            else:
                                ff = getattr(elem, '__fields__', None)
                                if isinstance(ff, dict):
                                    items = [(n, getattr(f, 'outer_type_', None)) for n, f in ff.items()]
                                else:
                                    try:
                                        hints = get_type_hints(elem, globalns=globalns)
                                    except Exception:
                                        hints = getattr(elem, '__annotations__', {})
                                    items = list(hints.items())

                            for name, sub_tp in items:
                                sub_prefix = f"{prefix}[].{name}" if prefix else f"[].{name}"
                                results.extend(collect_paths(sub_tp, sub_prefix, depth + 1, max_depth))
                            return results
                        else:
                            results.append((list_path, describe_type(tp)))
                            return results
                    except Exception:
                        results.append((list_path, describe_type(tp)))
                        return results

                # handle pydantic models
                try:
                    if isinstance(tp, type) and issubclass(tp, pydantic.BaseModel):
                        try:
                            hints = get_type_hints(tp, globalns=globalns)
                        except Exception:
                            hints = getattr(tp, '__annotations__', {})
                        for name, sub_tp in hints.items():
                            sub_prefix = f"{prefix}.{name}" if prefix else name
                            try:
                                if isinstance(sub_tp, type) and sub_tp in primitive_types:
                                    results.append((sub_prefix, describe_type(sub_tp)))
                                    continue
                            except Exception:
                                pass
                            sub_results = collect_paths(sub_tp, sub_prefix, depth + 1, max_depth)
                            if sub_results:
                                results.extend(sub_results)
                            else:
                                results.append((sub_prefix, describe_type(sub_tp)))
                        return results
                except Exception:
                    pass

                # handle Union/Optional
                if origin is typing.Union:
                    for a in get_args(tp):
                        if a is type(None):
                            continue
                        results.extend(collect_paths(a, prefix, depth + 1, max_depth))
                    return results

                if prefix:
                    results.append((prefix, describe_type(tp)))
                return results

            # extract values from card according to path
            try:
                card_data = card.model_dump(exclude_none=True)
            except Exception:
                card_data = dict(getattr(card, '__dict__', {}) or {})

            def traverse_value(val, parts):
                # returns scalar or list of scalars/dicts depending on path
                if val is None:
                    return None
                if not parts:
                    return val
                part = parts[0]
                rest = parts[1:]
                # list indicator e.g. chapters[] or [].
                if part.endswith('[]'):
                    key = part[:-2]
                    if isinstance(val, dict):
                        seq = val.get(key) or []
                    else:
                        seq = getattr(val, key, None) or []
                    if not isinstance(seq, list):
                        return None
                    results = []
                    for item in seq:
                        results.append(traverse_value(item, rest))
                    return results
                # part may be '[]' meaning current value is a list
                if part == '[]':
                    if not isinstance(val, list):
                        return None
                    results = []
                    for item in val:
                        results.append(traverse_value(item, rest))
                    return results
                # normal dict/key
                if isinstance(val, dict):
                    nextv = val.get(part)
                else:
                    nextv = getattr(val, part, None)
                return traverse_value(nextv, rest)

            # collect schema paths from Card model
            try:
                from yoto_up.models import Card as CardModel
            except Exception:
                CardModel = Card

            raw = collect_paths(CardModel, '', 0, 8)
            # normalize and dedupe similar to edit_card
            keys = []
            seen = set()
            for path, t in raw:
                if not path:
                    continue
                norm = path.replace('.[].', '.').replace('[]..', '[]')
                if norm not in seen:
                    seen.add(norm)
                    keys.append((norm, t))

            typer.echo(f"Schema + values for card {card_id}:")
            for k, t in sorted(keys):
                # prepare parts for traversal
                parts = k.split('.') if k else []
                value = traverse_value(card_data, parts)
                # pretty print value
                if isinstance(value, list):
                    # show count and a short sample
                    sample = [v for v in value if v is not None][:3]
                    sval = f"List(len={len(value)}) sample={json.dumps(sample, default=str)[:200]}"
                else:
                    try:
                        sval = json.dumps(value, default=str, ensure_ascii=False)
                    except Exception:
                        sval = str(value)
                typer.echo(f"  {k}: {t} = {sval}")
            return

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
def edit_card(
    card_id: Optional[str] = typer.Argument(None, help="Card ID (optional when --list-keys is used)"),
    title: Optional[str] = typer.Option(None, help="Set a new title for the card"),
    slug: Optional[str] = typer.Option(None, help="Set/replace top-level slug for the card"),
    description: Optional[str] = typer.Option(None, help="Set/replace metadata.description"),
    author: Optional[str] = typer.Option(None, help="Set/replace metadata.author"),
    category: Optional[str] = typer.Option(None, help="Set/replace metadata.category"),
    tags: Optional[str] = typer.Option(None, help='Comma-separated list of tags to set on the card'),
    genres: Optional[str] = typer.Option(None, help='Comma-separated list for metadata.genre'),
    languages: Optional[str] = typer.Option(None, help='Comma-separated list for metadata.languages'),
    min_age: Optional[int] = typer.Option(None, help='Set metadata.minAge'),
    max_age: Optional[int] = typer.Option(None, help='Set metadata.maxAge'),
    copyright: Optional[str] = typer.Option(None, help='Set metadata.copyright'),
    note: Optional[str] = typer.Option(None, help='Set metadata.note'),
    read_by: Optional[str] = typer.Option(None, help='Set metadata.readBy'),
    share: Optional[bool] = typer.Option(None, help='Set metadata.share (true/false)'),
    hidden: Optional[bool] = typer.Option(None, help='Set metadata.hidden (true/false)'),
    preview_audio: Optional[str] = typer.Option(None, help='Set metadata.previewAudio'),
    playback_direction: Optional[str] = typer.Option(None, help="Set metadata.playbackDirection ('ASC'|'DESC')"),
    accent: Optional[str] = typer.Option(None, help='Set metadata.accent'),
    add_to_family_library: Optional[bool] = typer.Option(None, help='Set metadata.addToFamilyLibrary'),
    music_type: Optional[str] = typer.Option(None, help='Comma-separated list for metadata.musicType'),
    # Flexible key=value setters for arbitrary nested fields, e.g. --set metadata.cover.imageL=/path/img.jpg
    set_fields: Optional[List[str]] = typer.Option(
        None,
        "--set",
        "-S",
        help="Set arbitrary key paths using key=value (multiple allowed). Example: -S metadata.author=NewAuthor",
    ),
    show_set_keys: bool = typer.Option(
        False,
        "--list-keys",
        help="Show available key paths that can be used with --set and exit",
    ),
):
    """Edit a Yoto card by its ID.

    If no update flags are provided this launches the interactive TUI editor.
    If one or more flags are passed (e.g. --title, --tags) the card is updated
    directly via the API and the TUI is not launched.
    """
    # If user requested the available set keys, generate them dynamically from the Card model
    if show_set_keys:
        # attempt to get module globals for resolving forward refs
        models_module = sys.modules.get('yoto_up.models')
        globalns = models_module.__dict__ if models_module is not None else globals()

        primitive_types = (str, int, float, bool)

        def describe_type(tp) -> str:
            origin = get_origin(tp)
            # Lists
            if origin is list or origin is List:
                args = get_args(tp)
                if args:
                    return f"List[{describe_type(args[0])}]"
                return "List[Unknown]"
            # Union / Optional
            if origin is typing.Union:
                args = [a for a in get_args(tp) if a is not type(None)]
                if len(args) == 1:
                    return f"Optional[{describe_type(args[0])}]"
                return f"Union[{', '.join(describe_type(a) for a in args)}]"
            try:
                if isinstance(tp, type):
                    if issubclass(tp, pydantic.BaseModel):
                        return tp.__name__
                    if tp in primitive_types:
                        return tp.__name__
                    return getattr(tp, '__name__', str(tp))
            except Exception:
                pass
            return str(tp)

        def collect_paths(tp, prefix: str = '', depth: int = 0, max_depth: int = 6):
            if depth > max_depth:
                return []
            origin = get_origin(tp)
            results = []

            # handle lists (List[T] -> prefix[] and prefix[].field)
            if origin is list or origin is List:
                args = get_args(tp)
                elem = args[0] if args else None
                list_path = f"{prefix}[]" if prefix else "[]"
                if elem is None:
                    results.append((list_path, 'List[Unknown]'))
                    return results

                # If element is a pydantic model, recurse using prefix[].field
                try:
                    if isinstance(elem, type) and issubclass(elem, pydantic.BaseModel):
                        results.append((list_path, describe_type(tp)))
                        # Prefer pydantic v2 model_fields then v1 __fields__
                        mf = getattr(elem, 'model_fields', None)
                        if isinstance(mf, dict):
                            items = [(n, f.annotation if hasattr(f, 'annotation') else None) for n, f in mf.items()]
                        else:
                            ff = getattr(elem, '__fields__', None)
                            if isinstance(ff, dict):
                                items = [(n, getattr(f, 'outer_type_', None)) for n, f in ff.items()]
                            else:
                                # fallback to annotations
                                try:
                                    hints = get_type_hints(elem, globalns=globalns)
                                except Exception:
                                    hints = getattr(elem, '__annotations__', {})
                                items = list(hints.items())

                        for name, sub_tp in items:
                            sub_prefix = f"{prefix}[].{name}" if prefix else f"[].{name}"
                            results.extend(collect_paths(sub_tp, sub_prefix, depth + 1, max_depth))
                        return results
                    else:
                        results.append((list_path, describe_type(tp)))
                        return results
                except Exception:
                    results.append((list_path, describe_type(tp)))
                    return results

            # handle pydantic models
            try:
                if isinstance(tp, type) and issubclass(tp, pydantic.BaseModel):
                    try:
                        hints = get_type_hints(tp, globalns=globalns)
                    except Exception:
                        hints = getattr(tp, '__annotations__', {})
                    for name, sub_tp in hints.items():
                        sub_prefix = f"{prefix}.{name}" if prefix else name
                        # if subfield is a primitive -> leaf
                        try:
                            if isinstance(sub_tp, type) and sub_tp in primitive_types:
                                results.append((sub_prefix, describe_type(sub_tp)))
                                continue
                        except Exception:
                            pass
                        # recurse
                        sub_results = collect_paths(sub_tp, sub_prefix, depth + 1, max_depth)
                        if sub_results:
                            results.extend(sub_results)
                        else:
                            results.append((sub_prefix, describe_type(sub_tp)))
                    return results
            except Exception:
                pass

            # handle Union/Optional
            if origin is typing.Union:
                for a in get_args(tp):
                    if a is type(None):
                        continue
                    results.extend(collect_paths(a, prefix, depth + 1, max_depth))
                return results

            # fallback: primitive or unknown
            if prefix:
                results.append((prefix, describe_type(tp)))
            return results

        # Start from Card class
        try:
            from yoto_up.models import Card as CardModel
        except Exception:
            CardModel = Card

        raw = collect_paths(CardModel, '', 0, 6)
        # normalize and dedupe
        keys = []
        seen = set()
        for path, t in raw:
            if not path:
                continue
            # normalize list markers (ensure consistent use of [])
            norm = path.replace('.[].', '.').replace('[]..', '[]')
            if norm not in seen:
                seen.add(norm)
                keys.append((norm, t))

        typer.echo("Available keys for --set (path: type):")
        for k, t in sorted(keys):
            typer.echo(f"  {k}: {t}")
        return

    API = get_api()
    card = API.get_card(card_id)
    if not card:
        typer.echo(f"Card with ID '{card_id}' not found.")
        raise typer.Exit(code=1)

    # Determine whether to apply direct updates or launch the TUI
    direct_update = any(x is not None for x in (title, description, author, category, tags))

    if not direct_update:
        # Launch the existing TUI editor
        def run_tui():
            app = EditCardApp(card, API)
            app.run()
            return getattr(app, "result", None)

        result = run_tui()
        if result:
            typer.echo(f"Card updated: {result.cardId}")
        else:
            typer.echo("Edit cancelled.")
        return

    # Apply direct updates
    try:
        # Convert the existing card to a mutable dict so we can apply arbitrary changes
        try:
            card_data = card.model_dump(exclude_none=False)
        except Exception:
            # fallback for non-pydantic Card-like objects
            card_data = dict(getattr(card, "__dict__", {}) or {})

        def set_in_dict(d: dict, path: str, value):
            parts = path.split('.') if path else []
            cur = d
            for p in parts[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            if parts:
                cur[parts[-1]] = value

        # Helper to parse comma-separated lists
        def parse_list(s: Optional[str]):
            if s is None:
                return None
            return [t.strip() for t in s.split(',') if t.strip()]

        # Apply explicit flags to card_data
        if title is not None:
            card_data['title'] = title
        if slug is not None:
            card_data['slug'] = slug

        # Ensure metadata dict exists
        if 'metadata' not in card_data or card_data.get('metadata') is None:
            card_data['metadata'] = {}

        if description is not None:
            card_data['metadata']['description'] = description
        if author is not None:
            card_data['metadata']['author'] = author
        if category is not None:
            card_data['metadata']['category'] = category
        if genres is not None:
            card_data['metadata']['genre'] = parse_list(genres)
        if languages is not None:
            card_data['metadata']['languages'] = parse_list(languages)
        if min_age is not None:
            card_data['metadata']['minAge'] = int(min_age)
        if max_age is not None:
            card_data['metadata']['maxAge'] = int(max_age)
        if copyright is not None:
            card_data['metadata']['copyright'] = copyright
        if note is not None:
            card_data['metadata']['note'] = note
        if read_by is not None:
            card_data['metadata']['readBy'] = read_by
        if share is not None:
            card_data['metadata']['share'] = bool(share)
        if hidden is not None:
            card_data['metadata']['hidden'] = bool(hidden)
        if preview_audio is not None:
            card_data['metadata']['previewAudio'] = preview_audio
        if playback_direction is not None:
            card_data['metadata']['playbackDirection'] = playback_direction
        if accent is not None:
            card_data['metadata']['accent'] = accent
        if add_to_family_library is not None:
            card_data['metadata']['addToFamilyLibrary'] = bool(add_to_family_library)
        if music_type is not None:
            card_data['metadata']['musicType'] = parse_list(music_type)

        # tags: set both top-level and metadata.tags
        if tags is not None:
            parsed = parse_list(tags) or []
            card_data['tags'] = parsed
            card_data['metadata']['tags'] = parsed

        # Apply any explicit --set key=value pairs
        if set_fields:
            for kv in set_fields:
                if '=' not in kv:
                    typer.echo(f"Ignoring malformed --set value (no '='): {kv}")
                    continue
                key, val = kv.split('=', 1)
                key = key.strip()
                val = val.strip()
                # Convert some simple types
                if val.lower() in ('true', 'false'):
                    parsed_val = val.lower() == 'true'
                else:
                    try:
                        parsed_val = int(val)
                    except Exception:
                        # comma-separated lists -> list
                        if ',' in val:
                            parsed_val = [p.strip() for p in val.split(',') if p.strip()]
                        else:
                            parsed_val = val
                set_in_dict(card_data, key, parsed_val)

        # Re-validate into a Card model if possible
        try:
            updated_card = Card.model_validate(card_data)
        except Exception:
            # Best-effort: update attributes directly on the original card
            # (this is less strict but avoids crashing if validation fails)
            for k, v in card_data.items():
                try:
                    setattr(card, k, v)
                except Exception:
                    pass
            updated_card = card

        # Send update
        updated = API.update_card(updated_card)
        try:
            updated_id = getattr(updated, 'cardId', getattr(card, 'cardId', None))
            typer.echo(f"Card updated: {updated_id}")
        except Exception:
            typer.echo("Card updated.")
    except Exception as exc:
        typer.echo(f"Failed to update card: {exc}")
        raise typer.Exit(code=1)


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
    local_norm: bool = typer.Option(
        False, help="Apply local loudness normalization using ffmpeg-normalize"
    ),
    local_norm_target: float = typer.Option(
        -23.0, help="Target LUFS for local normalization"
    ),
    local_norm_batch: bool = typer.Option(
        False, help="Use batch mode for local normalization"
    ),
):
    import asyncio
    from yoto_up.normalization import AudioNormalizer

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

        temp_norm_dir = None
        if local_norm:
            typer.echo(f"Running local normalization (Target: {local_norm_target} LUFS, Batch: {local_norm_batch})...")
            try:
                temp_norm_dir = tempfile.mkdtemp(prefix="yoto_norm_")
                normalizer = AudioNormalizer(target_level=local_norm_target, batch_mode=local_norm_batch)
                media_files_str = [str(f) for f in media_files]
                
                normalized_files = await asyncio.to_thread(
                    normalizer.normalize, media_files_str, temp_norm_dir
                )
                media_files = [Path(f) for f in normalized_files]
                typer.echo("Normalization complete.")
            except Exception as e:
                typer.echo(f"[bold red]Normalization failed: {e}[/bold red]")
                if temp_norm_dir:
                    shutil.rmtree(temp_norm_dir)
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
        
        if temp_norm_dir and os.path.exists(temp_norm_dir):
            shutil.rmtree(temp_norm_dir)

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
    trim: bool = typer.Option(False, "--trim", help="Copy trimmed files to a temporary (non-destructive) location"),
    dest_dir: Optional[str] = typer.Option(None, "--dest", help="Destination directory for trimmed files (defaults to a temp dir)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned trimmed file paths but don't write files"),
    keep_silence_ms: int = typer.Option(0, "--keep-silence-ms", help="Milliseconds of silence to keep at each trimmed edge"),
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

    # Optionally trim matched segment non-destructively by copying trimmed
    # files to a temporary or user-specified directory. This uses the
    # `trim_audio_file` helper from the analysis module which preserves
    # file format via pydub.
    if trim:
        # Determine how many seconds to remove from the chosen side
        remove_seconds = float(seconds_matched or 0.0)
        if remove_seconds <= 0.0:
            console.print("[yellow]No matched seconds found; nothing to trim.[/yellow]")
        else:
            # Prepare destination directory
            if dest_dir:
                out_dir = os.path.abspath(dest_dir)
                os.makedirs(out_dir, exist_ok=True)
                created_temp = False
            else:
                out_dir = tempfile.mkdtemp(prefix="yoto_trim_")
                created_temp = True

            console.print(f"Trimming {len(files)} files to: [bold]{out_dir}[/bold]")

            trimmed_paths = []
            for src in files:
                try:
                    src_path = os.path.abspath(src)
                    fn = Path(src_path).name
                    dest_path = os.path.join(out_dir, fn)

                    if dry_run:
                        console.print(f"[cyan]Dry-run:[/] would write trimmed file: {dest_path}")
                        trimmed_paths.append(dest_path)
                        continue

                    # Decide which side to remove
                    remove_intro = remove_seconds if side == "intro" else 0.0
                    remove_outro = remove_seconds if side == "outro" else 0.0

                    io_mod.trim_audio_file(
                        src_path,
                        dest_path,
                        remove_intro_seconds=remove_intro,
                        remove_outro_seconds=remove_outro,
                        keep_silence_ms=keep_silence_ms,
                    )
                    trimmed_paths.append(dest_path)
                    console.print(f"[green]Trimmed:[/] {src_path} -> {dest_path}")
                except Exception as e:
                    console.print(f"[red]Failed to trim {src}: {e}[/red]")

            if trimmed_paths:
                console.print(Panel('\n'.join(trimmed_paths), title="Trimmed files"))
                if created_temp:
                    console.print(f"Temporary trimmed files are in: [bold]{out_dir}[/bold]")

    # (Gain adjustment is handled by the separate `normalize` command.)

    console.print(f"[blue]Analysis suggests remove the first {seconds_matched} seconds from the {side}.[/blue]")
    console.print("Rerun <command> with --trim option to apply.")


@app.command(name="intro")
def intro(
    files: List[str] = typer.Argument(..., help="Audio files to analyze"),
    seconds: float = typer.Option(10.0, "--seconds", "-S", help="Max seconds to inspect at the chosen side"),
    window_seconds: float = typer.Option(0.1, "--window", help="Window size (seconds) used by per-window analyzer"),
    sr: int = typer.Option(22050, "--sr", help="Sample rate used for feature extraction"),
    n_mfcc: int = typer.Option(13, "--n-mfcc", help="Number of MFCC coefficients to compute"),
    threshold: float = typer.Option(0.99, "--threshold", "-t", help="Per-window similarity threshold (0..1)"),
    min_files_fraction: float = typer.Option(0.9, "--min-fraction", help="Minimum fraction of files required to declare a common prefix"),
    trim: bool = typer.Option(False, "--trim", help="Copy trimmed files to a temporary (non-destructive) location"),
    dest_dir: Optional[str] = typer.Option(None, "--dest", help="Destination directory for trimmed files (defaults to a temp dir)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned trimmed file paths but don't write files"),
    keep_silence_ms: int = typer.Option(0, "--keep-silence-ms", help="Milliseconds of silence to keep at each trimmed edge"),
    gain_db: Optional[float] = typer.Option(None, "--gain-db", help="(unused) kept for compatibility"),
):
    """Analyze the intro side (shortcut for `intro-outro --side intro`)."""
    return intro_outro(
        files=files,
        side="intro",
        seconds=seconds,
        window_seconds=window_seconds,
        sr=sr,
        n_mfcc=n_mfcc,
        threshold=threshold,
        min_files_fraction=min_files_fraction,
        trim=trim,
        dest_dir=dest_dir,
        dry_run=dry_run,
        keep_silence_ms=keep_silence_ms,
        gain_db=gain_db,
    )


@app.command(name="outro")
def outro(
    files: List[str] = typer.Argument(..., help="Audio files to analyze"),
    seconds: float = typer.Option(10.0, "--seconds", "-S", help="Max seconds to inspect at the chosen side"),
    window_seconds: float = typer.Option(0.1, "--window", help="Window size (seconds) used by per-window analyzer"),
    sr: int = typer.Option(22050, "--sr", help="Sample rate used for feature extraction"),
    n_mfcc: int = typer.Option(13, "--n-mfcc", help="Number of MFCC coefficients to compute"),
    threshold: float = typer.Option(0.99, "--threshold", "-t", help="Per-window similarity threshold (0..1)"),
    min_files_fraction: float = typer.Option(0.9, "--min-fraction", help="Minimum fraction of files required to declare a common prefix"),
    trim: bool = typer.Option(False, "--trim", help="Copy trimmed files to a temporary (non-destructive) location"),
    dest_dir: Optional[str] = typer.Option(None, "--dest", help="Destination directory for trimmed files (defaults to a temp dir)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned trimmed file paths but don't write files"),
    keep_silence_ms: int = typer.Option(0, "--keep-silence-ms", help="Milliseconds of silence to keep at each trimmed edge"),
    gain_db: Optional[float] = typer.Option(None, "--gain-db", help="(unused) kept for compatibility"),
):
    """Analyze the outro side (shortcut for `intro-outro --side outro`)."""
    return intro_outro(
        files=files,
        side="outro",
        seconds=seconds,
        window_seconds=window_seconds,
        sr=sr,
        n_mfcc=n_mfcc,
        threshold=threshold,
        min_files_fraction=min_files_fraction,
        trim=trim,
        dest_dir=dest_dir,
        dry_run=dry_run,
        keep_silence_ms=keep_silence_ms,
        gain_db=gain_db,
    )


@app.command(name="normalize")
def normalize(
    files: List[str] = typer.Argument(..., help="Audio files to analyze or adjust"),
    auto: bool = typer.Option(False, "--auto", help="Analyze files and show recommended per-file gain to reach target LUFS"),
    apply: bool = typer.Option(False, "--apply", help="Apply recommended gains (non-destructive)"),
    gain_db: Optional[float] = typer.Option(None, "--gain-db", help="Apply a fixed gain (dB) to output copies; non-destructive"),
    dest: Optional[str] = typer.Option(None, "--dest", help="Destination directory for adjusted files (defaults to a temp dir)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned adjusted files but don't write them"),
    target_lufs: float = typer.Option(-16.0, "--target-lufs", help="Target LUFS for auto normalization"),
    per_file: bool = typer.Option(False, "--per-file", help="Apply per-file normalization instead of a single global gain (default: preserve per-track differences)"),
):
    """Normalize or apply gain adjustments to audio files (non-destructive).

    Examples:
      python -m yoto_up.yoto normalize *.mp3 --auto
      python -m yoto_up.yoto normalize *.mp3 --auto --apply --dest /tmp/adjusted
      python -m yoto_up.yoto normalize *.mp3 --gain-db -3.0
    """
    # Validate input
    if not files:
        typer.echo("No files provided")
        raise typer.Exit(code=2)

    # Local rich imports used for formatted output
    from rich.panel import Panel
    from rich.table import Table

    # If a fixed gain was requested, apply it to copies
    if gain_db is not None:
        # prepare out dir
        if dest:
            out_dir = os.path.abspath(dest)
            os.makedirs(out_dir, exist_ok=True)
            created_temp = False
        else:
            out_dir = tempfile.mkdtemp(prefix="yoto_gain_")
            created_temp = True

        console.print(f"Applying fixed gain {gain_db:+.2f} dB to {len(files)} file(s) -> {out_dir}")
        try:
            from pydub import AudioSegment
        except Exception:
            console.print("[red]pydub is required for gain adjustment but is not available.[/red]")
            raise typer.Exit(code=1)

        # Use a progress bar while writing files
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
        written = []
        total = len(files)
        if dry_run:
            # dry-run: just list planned paths
            for src in files:
                src_path = os.path.abspath(src)
                base, ext = os.path.splitext(os.path.basename(src_path))
                tag = f"_adj_{int(gain_db*100)}"
                dest_name = f"{base}{tag}{ext}"
                dest_path = os.path.join(out_dir, dest_name)
                console.print(f"[cyan]Dry-run:[/] would write: {dest_path}")
                written.append(dest_path)
        else:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn()) as prog:
                task = prog.add_task("Applying fixed gain...", total=total)

                def _cb(completed, tot):
                    try:
                        prog.update(task, completed=completed)
                    except Exception:
                        pass

                # Build a tiny plan for fixed-gain application to reuse apply_gain_plan
                fixed_plan = {}
                for src in files:
                    fixed_plan[os.path.abspath(src)] = {'recommended_gain_db': float(gain_db)}

                written = apply_gain_plan(fixed_plan, out_dir, dry_run=False, progress_callback=_cb)

        if written:
            console.print(Panel('\n'.join(written), title="Gain-adjusted files"))
            if created_temp:
                console.print(f"Temporary files are in: [bold]{out_dir}[/bold]")
        return

    # If auto analysis or apply requested
    if auto or apply:
        try:
            plan = analyze_gain_requirements(list(files), target_lufs=target_lufs)
        except Exception as e:
            console.print(f"[red]Auto-gain analysis failed: {e}[/red]")
            raise typer.Exit(code=1)

        # Compute applied gain policy: by default preserve per-track differences by
        # applying a single global gain (mean of recommendations). If --per-file is
        # passed, apply each file's recommended gain individually.
        recs = [float(info.get('recommended_gain_db', 0.0)) for info in plan.values()]
        global_gain = float(sum(recs) / len(recs)) if recs else 0.0

        # Show recommendations with an "Applied" column so user sees the difference
        t = Table(title=f"Auto-gain recommendations (target {target_lufs} LUFS)")
        t.add_column("File", style="cyan", overflow="fold")
        t.add_column("LUFS", style="magenta", justify="right")
        t.add_column("Peak", style="yellow", justify="right")
        t.add_column("Recommended dB", style="green", justify="right")
        t.add_column("Applied dB", style="bright_green", justify="right")
        for p, info in plan.items():
            lu = info.get('lufs')
            pk = info.get('max_amp')
            rg = float(info.get('recommended_gain_db', 0.0))
            applied = rg if per_file else global_gain
            t.add_row(
                p,
                f"{lu:.2f}" if lu is not None else "(n/a)",
                f"{pk:.3f}" if pk is not None else "(n/a)",
                f"{rg:+.2f} dB",
                f"{applied:+.2f} dB",
            )
        console.print(t)

        if apply:
            if dest:
                apply_out = os.path.abspath(dest)
                os.makedirs(apply_out, exist_ok=True)
                created_temp2 = False
            else:
                apply_out = tempfile.mkdtemp(prefix="yoto_auto_gain_")
                created_temp2 = True
            # Use a progress bar for applying the plan
            try:
                from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
                total = len(plan)
                with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TimeElapsedColumn()) as prog:
                    task = prog.add_task("Applying auto-gain plan...", total=total)

                    def _cb(completed, tot):
                        try:
                            prog.update(task, completed=completed)
                        except Exception:
                            pass

                    if per_file:
                        plan_to_apply = plan
                    else:
                        plan_to_apply = {}
                        for p, info in plan.items():
                            plan_to_apply[p] = dict(info)
                            plan_to_apply[p]['recommended_gain_db'] = global_gain

                    written = apply_gain_plan(plan_to_apply, apply_out, dry_run=dry_run, progress_callback=_cb)
            except Exception as e:
                console.print(f"[red]Failed to apply gain plan: {e}[/red]")
                raise typer.Exit(code=1)
            if written:
                console.print(Panel('\n'.join(written), title="Applied gain files"))
                if created_temp2:
                    console.print(f"Temporary auto-gain files are in: [bold]{apply_out}[/bold]")
        return

    # If we reach here, no operation requested
    console.print("No operation specified. Use --gain-db for a fixed gain or --auto/--apply for normalization.")


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
    return card


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
