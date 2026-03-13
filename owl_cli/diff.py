"""Git diff parsing and changed-function detection for owl-cli."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChangedRegion:
    """A contiguous region of changed lines in a file."""

    start_line: int
    end_line: int


@dataclass
class ChangedFile:
    """A file modified in a git diff with its changed line regions."""

    path: str
    regions: list[ChangedRegion] = field(default_factory=list)


@dataclass
class ChangedFunction:
    """A function touched by a git diff."""

    name: str
    code: str
    file: str
    lineno: int
    end_lineno: int
    class_name: str | None
    language: str


def run_git_diff(
    revision: str | None = None,
    staged: bool = False,
    target_dir: str = ".",
) -> str:
    """Run git diff and return raw unified diff output."""
    cmd = ["git", "-C", target_dir, "diff", "--unified=0", "--no-color"]
    if staged:
        cmd.append("--staged")
    if revision:
        cmd.append(revision)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"git diff failed: {e.stderr.strip()}", file=sys.stderr)
        return ""
    except FileNotFoundError:
        print("git is not installed or not in PATH.", file=sys.stderr)
        return ""


_DIFF_FILE_RE = re.compile(r"^diff --git a/.+ b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_diff(diff_output: str) -> list[ChangedFile]:
    """Parse unified diff output into ChangedFile objects."""
    files: list[ChangedFile] = []
    current_file: ChangedFile | None = None

    for line in diff_output.splitlines():
        file_match = _DIFF_FILE_RE.match(line)
        if file_match:
            current_file = ChangedFile(path=file_match.group(1))
            files.append(current_file)
            continue

        hunk_match = _HUNK_RE.match(line)
        if hunk_match and current_file is not None:
            start = int(hunk_match.group(1))
            count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            if count == 0:
                # Pure deletion — mark the line where code was removed
                current_file.regions.append(ChangedRegion(start, start))
            else:
                current_file.regions.append(
                    ChangedRegion(start, start + count - 1)
                )

    return files


def _regions_overlap(
    func_start: int, func_end: int, regions: list[ChangedRegion]
) -> bool:
    """Check if a function's line range overlaps with any changed region."""
    for r in regions:
        if func_start <= r.end_line and func_end >= r.start_line:
            return True
    return False


def get_changed_functions(
    diff_output: str,
    indexed_functions: list[dict],
    target_dir: str = ".",
) -> list[ChangedFunction]:
    """Map diff regions to indexed functions that were modified.

    Args:
        diff_output: Raw unified diff text.
        indexed_functions: List of function dicts from the search index.
        target_dir: Resolved project root directory.

    Returns:
        List of ChangedFunction objects for functions overlapping with diff.
    """
    changed_files = parse_diff(diff_output)
    if not changed_files:
        return []

    target_root = Path(target_dir).resolve()

    # Build a lookup: resolved file path → list of changed regions
    file_regions: dict[str, list[ChangedRegion]] = {}
    for cf in changed_files:
        resolved = str((target_root / cf.path).resolve())
        file_regions[resolved] = cf.regions

    result: list[ChangedFunction] = []
    seen: set[tuple[str, int]] = set()

    for func in indexed_functions:
        fpath = func["file"]
        if fpath not in file_regions:
            continue

        regions = file_regions[fpath]
        if _regions_overlap(func["lineno"], func["end_lineno"], regions):
            key = (fpath, func["lineno"])
            if key in seen:
                continue
            seen.add(key)
            result.append(
                ChangedFunction(
                    name=func["name"],
                    code=func["code"],
                    file=func["file"],
                    lineno=func["lineno"],
                    end_lineno=func["end_lineno"],
                    class_name=func.get("class_name"),
                    language=func.get("language", ""),
                )
            )

    return result
