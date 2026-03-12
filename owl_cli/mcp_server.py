from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import OwlConfig
from .history import annotate_history, clear_history, load_history
from .indexer import CodeSearchEngine

mcp = FastMCP("owl-cli")


@mcp.tool()
def search_code(
    query: str,
    top_k: int = 10,
    directory: str = ".",
    exclude_patterns: list[str] | None = None,
    languages: list[str] | None = None,
) -> str:
    """Search code semantically using natural language.

    IMPORTANT: The query MUST be written in English. The default embedding
    model is English-only and does not understand other languages.
    Even if the user's request is in another language, always translate
    the search query to English before calling this tool.

    You SHOULD set the directory parameter to the project root you are
    currently working in. Choose the most appropriate scope for the search
    (e.g. the whole project root, or a specific subdirectory like "src/").

    Args:
        query: Natural language description in English of what you're looking for.
               Examples: "authentication logic", "database connection pooling",
               "error handling middleware"
        top_k: Number of results to return (default 10).
        directory: Absolute path to the directory to search in. You should
                   always set this to the project you are working on.
                   Use a subdirectory to narrow scope if needed.
        exclude_patterns: Optional list of glob patterns to exclude from indexing.
                          Examples: ["tests/", "src/tests/**", "*_test.py"]
        languages: Optional list of languages to filter results by.
                   Examples: ["python"], ["typescript", "javascript"]
                   Supported: go, java, javascript, php, python, ruby, rust, typescript

    Returns:
        JSON array of matching functions with file paths, line numbers,
        and relevance scores.
    """
    config = OwlConfig.load(target_dir=directory, top_k_override=top_k)
    if exclude_patterns:
        config.exclude_patterns = list(config.exclude_patterns) + exclude_patterns
    engine = CodeSearchEngine(config)
    results = engine.search(query, languages=languages)

    data = [
        {
            "name": r.name,
            "file": r.file,
            "lineno": r.lineno,
            "end_lineno": r.end_lineno,
            "class_name": r.class_name,
            "language": r.language,
            "score": round(r.score, 4),
            "code": r.code,
        }
        for r in results
    ]
    output = json.dumps(data, ensure_ascii=False, indent=2)

    if config.auto_annotate:
        output += (
            "\n\n[auto_annotate] Please evaluate the usefulness of these search"
            " results and call the annotate_search tool with a brief assessment"
            " (e.g. whether the results were relevant, which ones were most"
            " helpful, or if the query should be refined)."
        )

    return output


@mcp.tool()
def index_code(
    directory: str = ".",
    force: bool = False,
    exclude_patterns: list[str] | None = None,
) -> str:
    """Build or update the semantic search index for a codebase.

    Args:
        directory: Absolute path to the directory to index. You should
                   always set this to the project you are working on.
        force: Force full rebuild, ignoring cache.
        exclude_patterns: Optional list of glob patterns to exclude from indexing.
                          Examples: ["tests/", "src/tests/**", "*_test.py"]

    Returns:
        JSON object with indexing stats.
    """
    config = OwlConfig.load(target_dir=directory)
    if exclude_patterns:
        config.exclude_patterns = list(config.exclude_patterns) + exclude_patterns
    engine = CodeSearchEngine(config)
    result = engine.build_index(force=force)

    return json.dumps(
        {
            "num_files": result.num_files,
            "num_functions": result.num_functions,
            "time_taken": round(result.time_taken, 2),
            "from_cache": result.from_cache,
        }
    )


@mcp.tool()
def index_status(directory: str = ".") -> str:
    """Check the status of the search index.

    Args:
        directory: Absolute path to the directory to check. You should
                   always set this to the project you are working on.

    Returns:
        JSON object with index status info, or a message if no index exists.
    """
    config = OwlConfig.load(target_dir=directory)
    engine = CodeSearchEngine(config)
    info = engine.get_status()

    if info is None:
        return json.dumps({"status": "no_index", "message": "No index found."})

    return json.dumps(info)


@mcp.tool()
def search_history(directory: str = ".", limit: int = 20, clear: bool = False) -> str:
    """View or clear the search history for a project.

    Args:
        directory: Absolute path to the directory. You should always set this
                   to the project you are working on.
        limit: Maximum number of recent entries to return (default 20).
        clear: If True, clear the history and return a confirmation.

    Returns:
        JSON array of history entries (most recent last), or a confirmation
        message if clearing.
    """
    target_dir = str(Path(directory).resolve())

    if clear:
        clear_history(target_dir)
        return json.dumps({"status": "cleared", "message": "Search history cleared."})

    entries = load_history(target_dir)

    if not entries:
        return json.dumps({"status": "empty", "message": "No search history found."})

    shown = entries[-limit:] if limit < len(entries) else entries
    return json.dumps(
        [asdict(e) for e in shown],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def annotate_search(
    annotation: str, directory: str = ".", index: int = -1
) -> str:
    """Add an annotation to a search history entry.

    Use this tool after search_code to record observations, summaries,
    or notes about the search results. By default it annotates the most
    recent search.

    Args:
        annotation: The annotation text to attach to the history entry.
        directory: Absolute path to the directory. You should always set this
                   to the project you are working on.
        index: Which history entry to annotate. Use -1 for the most recent
               search (default), -2 for the one before that, or a positive
               1-based index.

    Returns:
        JSON object confirming success or failure.
    """
    target_dir = str(Path(directory).resolve())
    ok = annotate_history(target_dir, index, annotation)
    if ok:
        return json.dumps({"status": "ok", "message": "Annotation saved."})
    return json.dumps({"status": "error", "message": "History entry not found."})


@mcp.tool()
def detect_excludes(directory: str = ".") -> str:
    """Auto-detect directories and file patterns that likely contain
    non-production code (tests, examples, benchmarks, etc.).

    Returns suggestions that the user can review before applying.
    Use this before index_code to help the user decide what to exclude.

    Args:
        directory: Absolute path to the project directory. You should
                   always set this to the project you are working on.

    Returns:
        JSON object with suggested exclude patterns, each with a reason
        and matched file count.
    """
    from .cache import detect_exclude_suggestions

    config = OwlConfig.load(target_dir=directory)
    suggestions = detect_exclude_suggestions(
        config.target_dir, config.file_extensions
    )

    existing = set(config.exclude_patterns)
    data = [
        {
            "pattern": s.pattern,
            "reason": s.reason,
            "file_count": s.file_count,
            "already_excluded": s.pattern in existing,
        }
        for s in suggestions
    ]
    return json.dumps(
        {
            "suggestions": data,
            "current_exclude_patterns": config.exclude_patterns,
        },
        ensure_ascii=False,
        indent=2,
    )


def run_mcp_server() -> None:
    mcp.run(transport="stdio")
