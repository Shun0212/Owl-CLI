"""Search history persistence for owl-cli."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import get_index_dir

HISTORY_FILENAME = "history.json"


@dataclass
class HistoryResult:
    name: str
    file: str
    lineno: int
    end_lineno: int
    class_name: str | None
    score: float


@dataclass
class HistoryEntry:
    timestamp: str
    query: str
    num_results: int
    results: list[HistoryResult] = field(default_factory=list)
    annotation: str | None = None


def save_history_entry(
    target_dir: str,
    query: str,
    results: list,
) -> None:
    """Append a search entry to the history file."""
    entry = HistoryEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        query=query,
        num_results=len(results),
        results=[
            HistoryResult(
                name=r.name,
                file=r.file,
                lineno=r.lineno,
                end_lineno=r.end_lineno,
                class_name=r.class_name,
                score=round(r.score, 4),
            )
            for r in results
        ],
    )

    history = _load_history_raw(target_dir)
    history.append(asdict(entry))
    _atomic_write_history(target_dir, history)


def load_history(target_dir: str) -> list[HistoryEntry]:
    """Load all history entries for a project directory."""
    raw = _load_history_raw(target_dir)
    entries = []
    for item in raw:
        entries.append(
            HistoryEntry(
                timestamp=item["timestamp"],
                query=item["query"],
                num_results=item["num_results"],
                results=[
                    HistoryResult(**r) for r in item.get("results", [])
                ],
                annotation=item.get("annotation"),
            )
        )
    return entries


def annotate_history(target_dir: str, index: int, annotation: str) -> bool:
    """Add an annotation to a history entry.

    Args:
        target_dir: Resolved project directory path.
        index: 1-based index into the history list (negative for recent entries,
               e.g. -1 = most recent).
        annotation: The annotation text to save.

    Returns:
        True if the entry was found and annotated, False otherwise.
    """
    history = _load_history_raw(target_dir)
    if not history:
        return False

    try:
        history[index if index < 0 else index - 1]["annotation"] = annotation
    except IndexError:
        return False

    _atomic_write_history(target_dir, history)
    return True


def clear_history(target_dir: str) -> None:
    """Delete the history file for a project directory."""
    path = _history_path(target_dir)
    if path.exists():
        path.unlink()


def _history_path(target_dir: str) -> Path:
    return get_index_dir(target_dir) / HISTORY_FILENAME


def _load_history_raw(target_dir: str) -> list[dict]:
    path = _history_path(target_dir)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write_history(target_dir: str, data: list[dict]) -> None:
    path = _history_path(target_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
