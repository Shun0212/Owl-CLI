from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import OwlConfig, get_index_dir
from .history import annotate_history, clear_history, load_history
from .indexer import CodeSearchEngine

console = Console(stderr=True)
out = Console()


@click.group()
@click.version_option(version=__version__, prog_name="owl-cli")
def cli():
    """owl-cli: Semantic code search using vector embeddings."""


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=None, type=int, help="Number of results.")
@click.option("--dir", "-d", "directory", default=".", help="Directory to search.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON.")
@click.option("--no-code", is_flag=True, help="Hide function bodies.")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
def search(query, top_k, directory, model, output_json, no_code, exclude):
    """Search code semantically. Auto-indexes on first run."""
    config = OwlConfig.load(
        target_dir=directory,
        model_override=model,
        top_k_override=top_k,
    )
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)
    engine = CodeSearchEngine(config)
    results = engine.search(query)

    if output_json:
        data = [
            {
                "name": r.name,
                "file": r.file,
                "lineno": r.lineno,
                "end_lineno": r.end_lineno,
                "class_name": r.class_name,
                "score": round(r.score, 4),
                **({"code": r.code} if not no_code else {}),
            }
            for r in results
        ]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        rel_file = _relative_path(r.file, config.target_dir)
        location = f"{rel_file}:{r.lineno}-{r.end_lineno}"
        class_info = f"  Class: {r.class_name}" if r.class_name else ""

        header = Text()
        header.append(f"  #{i} ", style="bold cyan")
        header.append(f"{r.name}", style="bold white")
        header.append(f"  score: {r.score:.4f}", style="dim")

        subtitle = Text()
        subtitle.append(f"  {location}", style="green")
        if class_info:
            subtitle.append(class_info, style="yellow")

        if no_code:
            out.print(header)
            out.print(subtitle)
            out.print()
        else:
            code = Syntax(
                r.code,
                "python",
                theme="monokai",
                line_numbers=True,
                start_line=r.lineno,
            )
            panel = Panel(
                code,
                title=header,
                subtitle=subtitle,
                subtitle_align="left",
                border_style="dim",
                expand=True,
            )
            out.print(panel)


@cli.command()
@click.option("--dir", "-d", "directory", default=".", help="Directory to index.")
@click.option("--force", "-f", is_flag=True, help="Force full rebuild.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
def index(directory, force, model, exclude):
    """Build or update the search index."""
    config = OwlConfig.load(target_dir=directory, model_override=model)
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)
    engine = CodeSearchEngine(config)

    console.print(f"Indexing [bold]{Path(directory).resolve()}[/bold] ...")
    result = engine.build_index(force=force)

    if result.from_cache:
        console.print(
            f"[green]Index is up to date.[/green] "
            f"{result.num_functions} functions in {result.num_files} files "
            f"({result.time_taken:.2f}s)"
        )
    else:
        console.print(
            f"[green]Indexed {result.num_functions} functions[/green] "
            f"from {result.num_files} files ({result.time_taken:.2f}s)"
        )


@cli.command()
@click.option("--dir", "-d", "directory", default=".", help="Target directory.")
def status(directory):
    """Show index status and configuration."""
    config = OwlConfig.load(target_dir=directory)
    engine = CodeSearchEngine(config)
    info = engine.get_status()

    if info is None:
        console.print("[yellow]No index found.[/yellow] Run `owl index` first.")
        return

    table = Table(title="Owl-CLI Index Status", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Directory", config.target_dir)
    table.add_row("Files", str(info["num_files"]))
    table.add_row("Functions", str(info["num_functions"]))
    table.add_row("Model", info["model_name"])

    ts = info["last_indexed"]
    if ts:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        table.add_row("Last indexed", dt.strftime("%Y-%m-%d %H:%M:%S"))

    index_dir = get_index_dir(config.target_dir)
    size = sum(f.stat().st_size for f in index_dir.iterdir() if f.is_file())
    table.add_row("Cache size", _human_size(size))
    table.add_row("Cache path", str(index_dir))

    out.print(table)


@cli.command()
@click.option("--clear-cache", is_flag=True, help="Clear the cache for this directory.")
@click.option("--clear-all-cache", is_flag=True, help="Clear all owl-cli caches.")
@click.option("--dir", "-d", "directory", default=".", help="Target directory.")
@click.option("--add-exclude", multiple=True, help="Add exclude pattern(s). Repeatable.")
@click.option("--remove-exclude", multiple=True, help="Remove exclude pattern(s). Repeatable.")
@click.option("--auto-exclude", is_flag=True, help="Auto-detect and suggest exclude patterns.")
def config(clear_cache, clear_all_cache, directory, add_exclude, remove_exclude, auto_exclude):
    """Show or manage configuration."""
    cfg = OwlConfig.load(target_dir=directory)

    if auto_exclude:
        _interactive_auto_exclude(cfg)
        return

    if add_exclude or remove_exclude:
        _update_exclude_patterns(cfg, add_exclude, remove_exclude)
        return

    if clear_all_cache:
        import shutil

        from .config import get_cache_base

        cache_base = get_cache_base()
        if cache_base.exists():
            shutil.rmtree(cache_base)
            console.print("[green]All caches cleared.[/green]")
        else:
            console.print("[yellow]No cache to clear.[/yellow]")
        return

    if clear_cache:
        import shutil

        index_dir = get_index_dir(cfg.target_dir)
        if index_dir.exists():
            shutil.rmtree(index_dir)
            console.print("[green]Cache cleared.[/green]")
        else:
            console.print("[yellow]No cache to clear.[/yellow]")
        return

    table = Table(title="Owl-CLI Configuration", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Model", cfg.model_name)
    table.add_row("Batch size", str(cfg.batch_size))
    table.add_row("Top K", str(cfg.top_k))
    table.add_row("File extensions", ", ".join(cfg.file_extensions))
    table.add_row("Exclude patterns", ", ".join(cfg.exclude_patterns) if cfg.exclude_patterns else "(none)")
    table.add_row("Target directory", cfg.target_dir)

    owlignore = Path(cfg.target_dir) / ".owlignore"
    table.add_row(".owlignore", "found" if owlignore.exists() else "not found")

    out.print(table)


@cli.command()
def mcp():
    """Start the MCP server (stdio transport).

    Used by Claude Code and other MCP-compatible tools.
    """
    from .mcp_server import run_mcp_server

    run_mcp_server()


@cli.command()
@click.option("--dir", "-d", "directory", default=".", help="Target directory.")
@click.option("--clear", is_flag=True, help="Clear search history.")
@click.option("--limit", "-n", default=20, type=int, help="Number of entries to show.")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--annotate",
    nargs=2,
    type=(int, str),
    default=None,
    help="Annotate entry: --annotate INDEX TEXT",
)
def history(directory, clear, limit, output_json, annotate):
    """Show or clear search history."""
    target_dir = str(Path(directory).resolve())

    if clear:
        clear_history(target_dir)
        console.print("[green]Search history cleared.[/green]")
        return

    if annotate is not None:
        idx, text = annotate
        ok = annotate_history(target_dir, idx, text)
        if ok:
            console.print("[green]Annotation saved.[/green]")
        else:
            console.print("[red]History entry not found.[/red]")
        return

    entries = load_history(target_dir)

    if not entries:
        console.print("[yellow]No search history found.[/yellow]")
        return

    shown = entries[-limit:] if limit < len(entries) else entries

    if output_json:
        from dataclasses import asdict

        click.echo(json.dumps([asdict(e) for e in shown], ensure_ascii=False, indent=2))
        return

    table = Table(title=f"Search History (showing {len(shown)} of {len(entries)})")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Time", style="cyan")
    table.add_column("Query", style="bold white")
    table.add_column("Results", justify="right", style="green")
    table.add_column("Annotation", style="yellow", max_width=40)

    for i, entry in enumerate(shown, 1):
        dt = datetime.fromisoformat(entry.timestamp).astimezone()
        time_str = dt.strftime("%Y-%m-%d %H:%M")
        ann = entry.annotation or ""
        table.add_row(str(i), time_str, entry.query, str(entry.num_results), ann)

    out.print(table)


def _interactive_auto_exclude(cfg: OwlConfig) -> None:
    from .cache import detect_exclude_suggestions

    console.print(
        f"Scanning [bold]{cfg.target_dir}[/bold] for non-production code..."
    )
    suggestions = detect_exclude_suggestions(
        cfg.target_dir, cfg.file_extensions
    )

    if not suggestions:
        console.print("[green]No additional exclude patterns suggested.[/green]")
        return

    existing = set(cfg.exclude_patterns)

    # Build table of suggestions.
    table = Table(title="Suggested Exclude Patterns")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Pattern", style="bold white")
    table.add_column("Reason", style="cyan")
    table.add_column("Files", justify="right", style="green")
    table.add_column("Status", style="yellow")

    actionable: list[tuple[int, str]] = []  # (display_num, pattern)
    for i, s in enumerate(suggestions, 1):
        if s.pattern in existing:
            status = "already excluded"
        else:
            status = "new"
            actionable.append((i, s.pattern))
        table.add_row(str(i), s.pattern, s.reason, str(s.file_count), status)

    out.print(table)

    if not actionable:
        console.print("[green]All suggested patterns are already excluded.[/green]")
        return

    console.print(
        f"\n[bold]Found {len(actionable)} new pattern(s).[/bold]"
    )
    console.print(
        "Enter numbers to exclude (comma-separated), [bold]a[/bold] for all, "
        "or [bold]n[/bold] to cancel:"
    )

    choice = click.prompt("Selection", default="a")
    choice = choice.strip().lower()

    if choice == "n":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    if choice == "a":
        selected = [pat for _, pat in actionable]
    else:
        selected = []
        for token in choice.replace(" ", "").split(","):
            try:
                num = int(token)
            except ValueError:
                console.print(f"[red]Invalid input: {token}[/red]")
                continue
            for display_num, pat in actionable:
                if display_num == num:
                    selected.append(pat)
                    break
            else:
                console.print(f"[yellow]#{num} is not a new pattern, skipping.[/yellow]")

    if not selected:
        console.print("[yellow]No patterns selected.[/yellow]")
        return

    # Persist via _update_exclude_patterns.
    _update_exclude_patterns(cfg, tuple(selected), ())


def _update_exclude_patterns(
    cfg: OwlConfig, add: tuple[str, ...], remove: tuple[str, ...]
) -> None:
    patterns = list(cfg.exclude_patterns)
    for p in add:
        if p not in patterns:
            patterns.append(p)
            console.print(f"[green]Added exclude pattern:[/green] {p}")
        else:
            console.print(f"[yellow]Pattern already exists:[/yellow] {p}")
    for p in remove:
        if p in patterns:
            patterns.remove(p)
            console.print(f"[green]Removed exclude pattern:[/green] {p}")
        else:
            console.print(f"[yellow]Pattern not found:[/yellow] {p}")

    config_path = get_index_dir(cfg.target_dir) / "config.json"
    data: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
    data["exclude_patterns"] = patterns
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if patterns:
        console.print(f"\nCurrent exclude patterns: {', '.join(patterns)}")
    else:
        console.print("\nNo exclude patterns configured.")


def _relative_path(file_path: str, base_dir: str) -> str:
    try:
        return str(Path(file_path).relative_to(Path(base_dir).resolve()))
    except ValueError:
        return file_path


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
