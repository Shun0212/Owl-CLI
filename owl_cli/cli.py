from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from . import __version__
from .config import OwlConfig, get_index_dir
from .diff import (
    ChangedFunction,
    get_branches,
    get_changed_functions,
    get_current_branch,
    get_function_diff,
    run_git_diff,
)
from .extractors import SUPPORTED_LANGUAGES
from .history import annotate_history, clear_history, load_history
from .indexer import CodeSearchEngine

console = Console(stderr=True)
out = Console()


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="owl-cli")
@click.pass_context
def cli(ctx):
    """owl-cli: Semantic code search using vector embeddings."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(interactive)
        return
    if ctx.invoked_subcommand not in ("mcp", "i", "interactive", "diff-search"):
        from .banner import print_banner

        print_banner(console)


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=None, type=int, help="Number of results.")
@click.option("--dir", "-d", "directory", default=".", help="Directory to search.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON.")
@click.option("--no-code", is_flag=True, help="Hide function bodies.")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
@click.option(
    "--language",
    "-l",
    "languages",
    multiple=True,
    help="Filter by language (e.g. python, typescript). Repeatable.",
)
def search(query, top_k, directory, model, output_json, no_code, exclude, languages):
    """Search code semantically. Auto-indexes on first run."""
    config = OwlConfig.load(
        target_dir=directory,
        model_override=model,
        top_k_override=top_k,
    )
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)
    engine = CodeSearchEngine(config)
    lang_list = list(languages) if languages else None
    results = engine.search(query, languages=lang_list)

    if output_json:
        data = [
            {
                "name": r.name,
                "file": r.file,
                "lineno": r.lineno,
                "end_lineno": r.end_lineno,
                "class_name": r.class_name,
                "language": r.language,
                "score": round(r.score, 4),
                **({"code": r.code} if not no_code else {}),
            }
            for r in results
        ]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    _print_results(results, config.target_dir, no_code)


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


@cli.command(name="diff")
@click.argument("revision", required=False, default=None)
@click.option("--staged", is_flag=True, help="Diff staged changes.")
@click.option("--top-k", "-k", default=5, type=int, help="Similar functions per changed function.")
@click.option("--dir", "-d", "directory", default=".", help="Directory to search.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON.")
@click.option("--no-code", is_flag=True, help="Hide function bodies.")
@click.option("--threshold", "-t", default=0.5, type=float, help="Minimum similarity score (0-1).")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
def diff_cmd(revision, staged, top_k, directory, model, output_json, no_code, threshold, exclude):
    """Semantic search based on git diff — find related functions.

    \b
    Examples:
        owl diff                  # unstaged changes
        owl diff --staged         # staged changes
        owl diff HEAD~1           # last commit
        owl diff main..feature    # branch comparison
    """
    config = OwlConfig.load(target_dir=directory, model_override=model)
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)
    engine = CodeSearchEngine(config)

    # Ensure the index is built
    engine._ensure_index()
    if engine.cache is None:
        console.print("[red]Failed to build index.[/red]")
        return

    # Get git diff
    diff_output = run_git_diff(
        revision=revision, staged=staged, target_dir=config.target_dir
    )
    if not diff_output:
        console.print("[yellow]No diff output (no changes detected).[/yellow]")
        return

    changed_funcs = get_changed_functions(
        diff_output, engine.cache.functions, config.target_dir
    )
    if not changed_funcs:
        console.print("[yellow]No indexed functions were changed in this diff.[/yellow]")
        return

    console.print(
        f"[bold]{len(changed_funcs)} changed function(s)[/bold] found in diff."
    )

    all_groups: list[dict] = []

    for cf in changed_funcs:
        similar = engine.search_by_code(
            cf.code,
            top_k=top_k,
            exclude_file=cf.file,
            exclude_lineno=cf.lineno,
            threshold=threshold,
        )

        if output_json:
            all_groups.append({
                "changed_function": {
                    "name": cf.name,
                    "file": cf.file,
                    "lineno": cf.lineno,
                    "end_lineno": cf.end_lineno,
                    "class_name": cf.class_name,
                    "language": cf.language,
                },
                "similar_functions": [
                    {
                        "name": r.name,
                        "file": r.file,
                        "lineno": r.lineno,
                        "end_lineno": r.end_lineno,
                        "class_name": r.class_name,
                        "language": r.language,
                        "score": round(r.score, 4),
                        **({"code": r.code} if not no_code else {}),
                    }
                    for r in similar
                ],
            })
        else:
            _print_diff_group(cf, similar, config.target_dir, no_code)

    if output_json:
        click.echo(json.dumps(all_groups, ensure_ascii=False, indent=2))


@cli.command(name="diff-search")
@click.option("--dir", "-d", "directory", default=".", help="Directory to search.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--top-k", "-k", default=None, type=int, help="Number of results.")
@click.option("--no-code", is_flag=True, help="Hide function bodies.")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
@click.option(
    "--language",
    "-l",
    "languages",
    multiple=True,
    help="Filter by language. Repeatable.",
)
def diff_search_cmd(directory, model, top_k, no_code, exclude, languages):
    """Search only within changed functions between branches.

    \b
    Select a branch to compare interactively, then search
    within functions that have changes. Results show diff context.
    """
    from .banner import print_banner

    print_banner(console)

    config = OwlConfig.load(
        target_dir=directory,
        model_override=model,
        top_k_override=top_k,
    )
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)

    engine = CodeSearchEngine(config)

    with console.status("[bold cyan]  Loading index...", spinner="dots"):
        idx_result = engine.build_index()

    from .model import get_model

    with console.status("[bold cyan]  Loading model...", spinner="dots"):
        get_model(config.model_name)

    # --- Branch selector ---
    current = get_current_branch(config.target_dir)
    branches = get_branches(config.target_dir)

    if not branches:
        console.print("[red]No git branches found.[/red]")
        return

    other_branches = [b for b in branches if b != current]
    if not other_branches:
        console.print("[red]No other branches to compare against.[/red]")
        return

    out.print()
    out.print(Text(f"  Current branch: {current}", style="bold green"))
    out.print()
    out.print(Text("  Compare against:", style="bold"))

    # Highlight main/master
    default_idx = 1
    for i, branch in enumerate(other_branches, 1):
        marker = " *" if branch in ("main", "master") else ""
        style = "bold yellow" if branch in ("main", "master") else ""
        out.print(Text(f"    {i}) {branch}{marker}", style=style))
        if branch in ("main", "master"):
            default_idx = i

    out.print()

    try:
        choice = input(
            f"  Select [1-{len(other_branches)}] (default: {default_idx}): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        out.print()
        console.print("[dim]  Cancelled.[/dim]")
        return

    if not choice:
        selected_idx = default_idx
    else:
        try:
            selected_idx = int(choice)
        except ValueError:
            console.print("[red]  Invalid selection.[/red]")
            return

    if selected_idx < 1 or selected_idx > len(other_branches):
        console.print("[red]  Invalid selection.[/red]")
        return

    base_branch = other_branches[selected_idx - 1]
    # Compare base branch against working tree (not ..HEAD) so that
    # line numbers in the diff match the index built from working tree.
    revision = base_branch

    console.print(f"\n[bold]  Comparing: {base_branch} -> {current}[/bold]")

    # --- Analyze diff ---
    with console.status("[bold cyan]  Analyzing diff...", spinner="dots"):
        diff_output = run_git_diff(
            revision=revision, target_dir=config.target_dir
        )

    if not diff_output:
        console.print("[yellow]  No differences found.[/yellow]")
        return

    changed_funcs = get_changed_functions(
        diff_output, engine.cache.functions, config.target_dir
    )

    if not changed_funcs:
        console.print(
            "[yellow]  No indexed functions were changed in this diff.[/yellow]"
        )
        return

    # --- Summary ---
    out.print(Rule(style="dim"))
    summary = Text()
    summary.append(f"  {len(changed_funcs)} changed function(s)", style="bold")
    summary.append("  |  ", style="dim")
    summary.append(f"{base_branch} -> {current}", style="dim")
    out.print(summary)
    out.print(Rule(style="dim"))
    out.print()

    _print_changed_list(changed_funcs, config.target_dir)
    out.print()
    _print_diff_search_help()
    out.print()

    # --- Interactive search loop ---
    state = _InteractiveState(
        top_k=config.top_k,
        no_code=no_code,
        languages=list(languages),
    )

    while True:
        try:
            raw = _read_diff_search_input(state)
        except (EOFError, KeyboardInterrupt):
            out.print()
            console.print("[dim]  Bye.[/dim]")
            break

        line = raw.strip()
        if not line:
            continue

        if line.startswith(":"):
            should_exit = _handle_diff_search_colon(
                line, state, engine, config, changed_funcs
            )
            if should_exit:
                break
            continue

        t0 = time.time()
        lang_list = state.languages if state.languages else None
        results = engine.search_in_changed(
            line, changed_funcs, top_k=state.top_k, languages=lang_list
        )
        elapsed = time.time() - t0

        _print_diff_search_results(
            results, config.target_dir, state.no_code, revision, elapsed
        )
        out.print()


@cli.command(name="find-similar")
@click.argument("target")
@click.option("--top-k", "-k", default=None, type=int, help="Number of results.")
@click.option("--dir", "-d", "directory", default=".", help="Directory to search.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON.")
@click.option("--no-code", is_flag=True, help="Hide function bodies.")
@click.option("--threshold", "-t", default=0.5, type=float, help="Minimum similarity score (0-1).")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
def find_similar(target, top_k, directory, model, output_json, no_code, threshold, exclude):
    """Find similar/duplicate implementations of a function.

    \b
    TARGET can be:
        file.py::function_name   — search for a specific function
        file.py                  — search for all functions in the file

    \b
    Examples:
        owl find-similar src/auth/login.py::validate_token
        owl find-similar src/utils.py
    """
    config = OwlConfig.load(
        target_dir=directory,
        model_override=model,
        top_k_override=top_k,
    )
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)
    engine = CodeSearchEngine(config)

    # Parse target
    if "::" in target:
        file_part, func_name = target.rsplit("::", 1)
        funcs_to_search = []
        func = engine.find_function(file_part, func_name)
        if func is None:
            console.print(
                f"[red]Function '{func_name}' not found in '{file_part}'.[/red]\n"
                f"[dim]Hint: run `owl index` first, and check file path is relative to target dir.[/dim]"
            )
            return
        funcs_to_search.append(func)
    else:
        funcs_to_search = engine.get_functions_in_file(target)
        if not funcs_to_search:
            console.print(
                f"[red]No indexed functions found in '{target}'.[/red]\n"
                f"[dim]Hint: run `owl index` first, and check file path is relative to target dir.[/dim]"
            )
            return

    all_groups: list[dict] = []

    for func in funcs_to_search:
        similar = engine.search_by_code(
            func["code"],
            top_k=config.top_k,
            exclude_file=func["file"],
            exclude_lineno=func["lineno"],
            threshold=threshold,
        )

        if output_json:
            all_groups.append({
                "query_function": {
                    "name": func["name"],
                    "file": func["file"],
                    "lineno": func["lineno"],
                    "end_lineno": func["end_lineno"],
                    "class_name": func.get("class_name"),
                    "language": func.get("language", ""),
                },
                "similar_functions": [
                    {
                        "name": r.name,
                        "file": r.file,
                        "lineno": r.lineno,
                        "end_lineno": r.end_lineno,
                        "class_name": r.class_name,
                        "language": r.language,
                        "score": round(r.score, 4),
                        **({"code": r.code} if not no_code else {}),
                    }
                    for r in similar
                ],
            })
        else:
            cf = ChangedFunction(
                name=func["name"],
                code=func["code"],
                file=func["file"],
                lineno=func["lineno"],
                end_lineno=func["end_lineno"],
                class_name=func.get("class_name"),
                language=func.get("language", ""),
            )
            _print_similar_group(cf, similar, config.target_dir, no_code)

    if output_json:
        click.echo(json.dumps(all_groups, ensure_ascii=False, indent=2))


@cli.command(name="i")
@click.option("--dir", "-d", "directory", default=".", help="Directory to search.")
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--top-k", "-k", default=None, type=int, help="Default number of results.")
@click.option("--no-code", is_flag=True, help="Hide function bodies by default.")
@click.option("--exclude", "-e", multiple=True, help="Exclude patterns (glob). Repeatable.")
@click.option(
    "--language",
    "-l",
    "languages",
    multiple=True,
    help="Default language filter. Repeatable.",
)
def interactive(directory, model, top_k, no_code, exclude, languages):
    """Start interactive search session (keeps model loaded)."""
    from .banner import print_banner

    print_banner(console)

    config = OwlConfig.load(
        target_dir=directory,
        model_override=model,
        top_k_override=top_k,
    )
    if exclude:
        config.exclude_patterns = list(config.exclude_patterns) + list(exclude)

    engine = CodeSearchEngine(config)

    with console.status("[bold cyan]  Loading index...", spinner="dots"):
        idx_result = engine.build_index()

    from .model import get_model

    with console.status("[bold cyan]  Loading model...", spinner="dots"):
        get_model(config.model_name)

    # Ready summary
    out.print(Rule(style="dim"))
    info_line = Text()
    info_line.append("  Ready", style="bold green")
    info_line.append("  |  ", style="dim")
    info_line.append(f"{idx_result.num_functions}", style="bold")
    info_line.append(" functions in ", style="dim")
    info_line.append(f"{idx_result.num_files}", style="bold")
    info_line.append(" files", style="dim")
    info_line.append("  |  ", style="dim")
    info_line.append(config.target_dir, style="dim")
    out.print(info_line)
    out.print(Rule(style="dim"))
    out.print()

    state = _InteractiveState(
        top_k=config.top_k,
        no_code=no_code,
        languages=list(languages),
    )

    _print_interactive_help()
    out.print()

    while True:
        try:
            raw = _read_input(state)
        except (EOFError, KeyboardInterrupt):
            out.print()
            console.print("[dim]  Bye.[/dim]")
            break

        line = raw.strip()
        if not line:
            continue

        if line.startswith(":"):
            should_exit = _handle_colon_command(line, state, engine, config)
            if should_exit:
                break
            continue

        t0 = time.time()
        lang_list = state.languages if state.languages else None
        results = engine.search(line, top_k=state.top_k, languages=lang_list)
        elapsed = time.time() - t0

        _print_results(results, config.target_dir, state.no_code, elapsed)
        out.print()


class _InteractiveState:
    __slots__ = ("top_k", "no_code", "languages")

    def __init__(self, top_k: int, no_code: bool, languages: list[str]):
        self.top_k = top_k
        self.no_code = no_code
        self.languages = languages


def _read_input(state: _InteractiveState) -> str:
    """Draw a framed input area with ANSI escapes and read user input.

    Renders 4 lines:
        ──────────────────────────        (top rule)
          search query or :help           (dim hint — stays visible)
          🦉 > [cursor here]             (input line)
        ──────────────────────────        (bottom rule)

    Cursor is repositioned to the input line so the user types between
    the hint and the bottom rule.
    """
    DIM = "\033[2m"
    RESET = "\033[0m"

    width = out.width
    rule = "─" * width

    # Pre-draw 4 lines: top rule, hint, blank (input), bottom rule
    sys.stdout.write(f"{DIM}{rule}{RESET}\n")
    sys.stdout.write(f"  {DIM}search query to find code, or :help for commands{RESET}\n")
    sys.stdout.write("\n")
    sys.stdout.write(f"{DIM}{rule}{RESET}\n")
    sys.stdout.flush()

    # Move cursor up 2 lines (to the blank input line) and clear it
    sys.stdout.write("\033[2A\033[2K")
    sys.stdout.flush()

    # Build plain-text prompt
    badges: list[str] = []
    if state.languages:
        badges.append(",".join(state.languages))
    if state.no_code:
        badges.append("no-code")
    if state.top_k != 10:
        badges.append(f"k={state.top_k}")
    badge_str = f" ({' '.join(badges)})" if badges else ""
    prompt = f"  \U0001F989{badge_str} > "

    raw = input(prompt)

    # Move cursor past the pre-drawn bottom rule
    sys.stdout.write("\033[1B\r")
    sys.stdout.flush()

    return raw


def _print_interactive_help() -> None:
    help_text = Text()
    help_text.append("  :lang ", style="bold cyan")
    help_text.append("py ts ...   ", style="dim")
    help_text.append("set language filter\n", style="")
    help_text.append("  :top-k ", style="bold cyan")
    help_text.append("N          ", style="dim")
    help_text.append("number of results\n", style="")
    help_text.append("  :no-code          ", style="bold cyan")
    help_text.append("toggle code display\n", style="")
    help_text.append("  :reindex          ", style="bold cyan")
    help_text.append("rebuild index\n", style="")
    help_text.append("  :status           ", style="bold cyan")
    help_text.append("show settings\n", style="")
    help_text.append("  :help             ", style="bold cyan")
    help_text.append("show this help\n", style="")
    help_text.append("  :quit             ", style="bold cyan")
    help_text.append("exit", style="")
    out.print(Panel(
        help_text,
        title="[dim]Commands  (or just type a query to search)[/dim]",
        title_align="left",
        border_style="dim",
        padding=(0, 1),
    ))


_LANG_ALIASES: dict[str, str] = {
    "py": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "rb": "ruby",
    "rs": "rust",
}


def _resolve_lang(name: str) -> str | None:
    """Resolve a language name or alias. Returns None if invalid."""
    low = name.lower()
    if low in SUPPORTED_LANGUAGES:
        return low
    return _LANG_ALIASES.get(low)


def _handle_colon_command(
    line: str,
    state: _InteractiveState,
    engine: CodeSearchEngine,
    config: OwlConfig,
) -> bool:
    """Handle a colon command. Returns True if the session should exit."""
    parts = line.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in (":quit", ":q", ":exit"):
        console.print("[dim]  Bye.[/dim]")
        return True

    if cmd in (":help", ":h"):
        _print_interactive_help()
        return False

    if cmd in (":lang", ":language", ":l"):
        if not args:
            state.languages = []
            console.print("[green]  Language filter cleared (all languages).[/green]")
        else:
            resolved: list[str] = []
            for a in args:
                lang = _resolve_lang(a)
                if lang is None:
                    console.print(
                        f"[red]  Unknown language: {a}[/red]\n"
                        f"[dim]    Supported: {', '.join(SUPPORTED_LANGUAGES)}[/dim]"
                    )
                    return False
                if lang not in resolved:
                    resolved.append(lang)
            state.languages = resolved
            console.print(f"[green]  Language filter: {', '.join(state.languages)}[/green]")
        return False

    if cmd in (":top-k", ":k"):
        if not args or not args[0].isdigit():
            console.print(f"[dim]  Current top_k: {state.top_k}[/dim]")
        else:
            state.top_k = int(args[0])
            console.print(f"[green]  top_k = {state.top_k}[/green]")
        return False

    if cmd == ":no-code":
        state.no_code = not state.no_code
        label = "hidden" if state.no_code else "shown"
        console.print(f"[green]  Code: {label}[/green]")
        return False

    if cmd == ":reindex":
        with console.status("[bold cyan]  Rebuilding index...", spinner="dots"):
            result = engine.build_index(force=True)
        console.print(
            f"[green]  Indexed {result.num_functions} functions[/green] "
            f"from {result.num_files} files [dim]({result.time_taken:.2f}s)[/dim]"
        )
        return False

    if cmd == ":status":
        info = engine.get_status()
        status_text = Text()
        status_text.append(f"  Directory   {config.target_dir}\n", style="")
        status_text.append(f"  Model       {config.model_name}\n", style="dim")
        if info:
            status_text.append(
                f"  Index       {info['num_functions']} functions"
                f" / {info['num_files']} files\n",
                style="",
            )
        status_text.append(f"  top_k       {state.top_k}\n", style="")
        lang_str = ", ".join(state.languages) if state.languages else "all"
        status_text.append(f"  Languages   {lang_str}\n", style="")
        code_str = "hidden" if state.no_code else "shown"
        status_text.append(f"  Code        {code_str}", style="")
        out.print(Panel(
            status_text,
            border_style="dim",
            padding=(0, 1),
        ))
        return False

    console.print(f"[red]  Unknown command: {cmd}[/red]  [dim](type :help)[/dim]")
    return False


def _print_results(
    results: list,
    target_dir: str,
    no_code: bool,
    elapsed: float | None = None,
) -> None:
    if not results:
        console.print("[yellow]  No results found.[/yellow]")
        return

    # Summary line
    summary = Text()
    summary.append(f"  {len(results)} result(s)", style="bold")
    if elapsed is not None:
        summary.append(f"  {elapsed:.3f}s", style="dim")
    out.print(summary)
    out.print()

    for i, r in enumerate(results, 1):
        rel_file = _relative_path(r.file, target_dir)
        location = f"{rel_file}:{r.lineno}-{r.end_lineno}"

        # Title line
        header = Text()
        header.append(f" #{i} ", style="bold bright_cyan")
        header.append(r.name, style="bold bright_white")
        if r.class_name:
            header.append(f"  ← {r.class_name}", style="bold bright_yellow")
        header.append(f"  {r.score:.4f}", style="bright_magenta")
        if r.language:
            header.append(f"  {r.language}", style="bold bright_cyan")

        subtitle = Text()
        subtitle.append(f" {location}", style="bold bright_green")

        if no_code:
            out.print(header)
            out.print(subtitle)
            out.print()
        else:
            lexer = r.language if r.language else "python"
            code = Syntax(
                r.code,
                lexer,
                theme="monokai",
                line_numbers=True,
                start_line=r.lineno,
            )
            panel = Panel(
                code,
                title=header,
                subtitle=subtitle,
                subtitle_align="left",
                border_style="bright_blue",
                expand=True,
            )
            out.print(panel)


def _print_diff_group(
    changed: ChangedFunction,
    similar: list,
    target_dir: str,
    no_code: bool,
) -> None:
    """Print a changed function and its semantically similar matches."""
    rel = _relative_path(changed.file, target_dir)
    loc = f"{rel}:{changed.lineno}-{changed.end_lineno}"

    header = Text()
    header.append("  ✏️  ", style="bold yellow")
    header.append(changed.name, style="bold bright_white")
    if changed.class_name:
        header.append(f"  ← {changed.class_name}", style="bold bright_yellow")
    if changed.language:
        header.append(f"  {changed.language}", style="bold bright_cyan")
    out.print(header)

    loc_text = Text()
    loc_text.append(f"     {loc}", style="bold bright_green")
    out.print(loc_text)

    if not similar:
        out.print(Text("     No similar functions found.", style="dim"))
        out.print()
        return

    out.print(Text(f"     → {len(similar)} similar function(s):", style="dim"))
    out.print()
    _print_results(similar, target_dir, no_code)
    out.print()


def _print_similar_group(
    query_func: ChangedFunction,
    similar: list,
    target_dir: str,
    no_code: bool,
) -> None:
    """Print a query function and its similar/duplicate matches."""
    rel = _relative_path(query_func.file, target_dir)
    loc = f"{rel}:{query_func.lineno}-{query_func.end_lineno}"

    header = Text()
    header.append("  🔎 ", style="bold cyan")
    header.append(query_func.name, style="bold bright_white")
    if query_func.class_name:
        header.append(f"  ← {query_func.class_name}", style="bold bright_yellow")
    if query_func.language:
        header.append(f"  {query_func.language}", style="bold bright_cyan")
    out.print(header)

    loc_text = Text()
    loc_text.append(f"     {loc}", style="bold bright_green")
    out.print(loc_text)

    if not similar:
        out.print(Text("     No similar functions found.", style="dim"))
        out.print()
        return

    out.print(Text(f"     → {len(similar)} similar function(s):", style="dim"))
    out.print()
    _print_results(similar, target_dir, no_code)
    out.print()


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


def _print_changed_list(
    changed_funcs: list[ChangedFunction], target_dir: str
) -> None:
    """Print a numbered list of changed functions."""
    for i, cf in enumerate(changed_funcs, 1):
        rel = _relative_path(cf.file, target_dir)
        line = Text()
        line.append(f"  {i}. ", style="dim")
        line.append(cf.name, style="bold bright_white")
        if cf.class_name:
            line.append(f" ({cf.class_name})", style="bright_yellow")
        line.append(f"  {rel}:{cf.lineno}", style="bright_green")
        out.print(line)


def _print_diff_search_help() -> None:
    help_text = Text()
    help_text.append("  :list             ", style="bold cyan")
    help_text.append("show changed functions\n", style="")
    help_text.append("  :lang ", style="bold cyan")
    help_text.append("py ts ...   ", style="dim")
    help_text.append("set language filter\n", style="")
    help_text.append("  :top-k ", style="bold cyan")
    help_text.append("N          ", style="dim")
    help_text.append("number of results\n", style="")
    help_text.append("  :no-code          ", style="bold cyan")
    help_text.append("toggle code display\n", style="")
    help_text.append("  :help             ", style="bold cyan")
    help_text.append("show this help\n", style="")
    help_text.append("  :quit             ", style="bold cyan")
    help_text.append("exit", style="")
    out.print(Panel(
        help_text,
        title="[dim]Commands  (type a query to search within changes)[/dim]",
        title_align="left",
        border_style="dim",
        padding=(0, 1),
    ))


def _read_diff_search_input(state: _InteractiveState) -> str:
    """Draw a framed input for diff-search mode."""
    DIM = "\033[2m"
    RESET = "\033[0m"

    width = out.width
    rule = "─" * width

    sys.stdout.write(f"{DIM}{rule}{RESET}\n")
    sys.stdout.write(
        f"  {DIM}search within changed code, or :help{RESET}\n"
    )
    sys.stdout.write("\n")
    sys.stdout.write(f"{DIM}{rule}{RESET}\n")
    sys.stdout.flush()

    sys.stdout.write("\033[2A\033[2K")
    sys.stdout.flush()

    badges: list[str] = []
    if state.languages:
        badges.append(",".join(state.languages))
    if state.no_code:
        badges.append("no-code")
    if state.top_k != 10:
        badges.append(f"k={state.top_k}")
    badge_str = f" ({' '.join(badges)})" if badges else ""
    prompt = f"  \U0001F989\u0394{badge_str} > "

    raw = input(prompt)

    sys.stdout.write("\033[1B\r")
    sys.stdout.flush()

    return raw


def _handle_diff_search_colon(
    line: str,
    state: _InteractiveState,
    engine: CodeSearchEngine,
    config: OwlConfig,
    changed_funcs: list[ChangedFunction],
) -> bool:
    """Handle colon commands in diff-search mode. Returns True to exit."""
    parts = line.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in (":quit", ":q", ":exit"):
        console.print("[dim]  Bye.[/dim]")
        return True

    if cmd in (":help", ":h"):
        _print_diff_search_help()
        return False

    if cmd == ":list":
        _print_changed_list(changed_funcs, config.target_dir)
        return False

    if cmd in (":lang", ":language", ":l"):
        if not args:
            state.languages = []
            console.print(
                "[green]  Language filter cleared (all languages).[/green]"
            )
        else:
            resolved: list[str] = []
            for a in args:
                lang = _resolve_lang(a)
                if lang is None:
                    console.print(
                        f"[red]  Unknown language: {a}[/red]\n"
                        f"[dim]    Supported: {', '.join(SUPPORTED_LANGUAGES)}[/dim]"
                    )
                    return False
                if lang not in resolved:
                    resolved.append(lang)
            state.languages = resolved
            console.print(
                f"[green]  Language filter: {', '.join(state.languages)}[/green]"
            )
        return False

    if cmd in (":top-k", ":k"):
        if not args or not args[0].isdigit():
            console.print(f"[dim]  Current top_k: {state.top_k}[/dim]")
        else:
            state.top_k = int(args[0])
            console.print(f"[green]  top_k = {state.top_k}[/green]")
        return False

    if cmd == ":no-code":
        state.no_code = not state.no_code
        label = "hidden" if state.no_code else "shown"
        console.print(f"[green]  Code: {label}[/green]")
        return False

    console.print(
        f"[red]  Unknown command: {cmd}[/red]  [dim](type :help)[/dim]"
    )
    return False


def _print_diff_search_results(
    results: list,
    target_dir: str,
    no_code: bool,
    revision: str,
    elapsed: float | None = None,
) -> None:
    """Print search results with diff context for each matched function."""
    if not results:
        console.print("[yellow]  No matching changed functions.[/yellow]")
        return

    summary = Text()
    summary.append(f"  {len(results)} result(s)", style="bold")
    if elapsed is not None:
        summary.append(f"  {elapsed:.3f}s", style="dim")
    out.print(summary)
    out.print()

    for i, r in enumerate(results, 1):
        rel_file = _relative_path(r.file, target_dir)
        location = f"{rel_file}:{r.lineno}-{r.end_lineno}"

        header = Text()
        header.append(f" #{i} ", style="bold bright_cyan")
        header.append(r.name, style="bold bright_white")
        if r.class_name:
            header.append(f"  <- {r.class_name}", style="bold bright_yellow")
        header.append(f"  {r.score:.4f}", style="bright_magenta")
        if r.language:
            header.append(f"  {r.language}", style="bold bright_cyan")

        subtitle = Text()
        subtitle.append(f" {location}", style="bold bright_green")

        # Get diff for this function
        diff_text = get_function_diff(
            r.file, r.lineno, r.end_lineno, revision, target_dir
        )

        if no_code:
            # Compact: header + location only
            out.print(header)
            out.print(subtitle)
            out.print()
        elif diff_text:
            # Show only the diff (already scoped to function range)
            panel = Panel(
                Syntax(diff_text, "diff", theme="monokai"),
                title=header,
                subtitle=subtitle,
                subtitle_align="left",
                border_style="bright_blue",
                expand=True,
            )
            out.print(panel)
        else:
            # No diff available — show function code as fallback
            lexer = r.language if r.language else "python"
            panel = Panel(
                Syntax(
                    r.code, lexer, theme="monokai",
                    line_numbers=True, start_line=r.lineno,
                ),
                title=header,
                subtitle=subtitle,
                subtitle_align="left",
                border_style="bright_blue",
                expand=True,
            )
            out.print(panel)


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
