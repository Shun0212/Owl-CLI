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
def search(query, top_k, directory, model, output_json, no_code):
    """Search code semantically. Auto-indexes on first run."""
    config = OwlConfig.load(
        target_dir=directory,
        model_override=model,
        top_k_override=top_k,
    )
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
def index(directory, force, model):
    """Build or update the search index."""
    config = OwlConfig.load(target_dir=directory, model_override=model)
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
def config(clear_cache, clear_all_cache, directory):
    """Show or manage configuration."""
    cfg = OwlConfig.load(target_dir=directory)

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
    table.add_row("Target directory", cfg.target_dir)
    out.print(table)


@cli.command()
def mcp():
    """Start the MCP server (stdio transport).

    Used by Claude Code and other MCP-compatible tools.
    """
    from .mcp_server import run_mcp_server

    run_mcp_server()


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
