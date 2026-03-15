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


def get_branches(target_dir: str = ".") -> list[str]:
    """List local git branch names (short format)."""
    cmd = ["git", "-C", target_dir, "branch", "--format=%(refname:short)"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [b.strip() for b in result.stdout.splitlines() if b.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def get_current_branch(target_dir: str = ".") -> str:
    """Get the name of the currently checked-out branch."""
    cmd = ["git", "-C", target_dir, "rev-parse", "--abbrev-ref", "HEAD"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


def get_function_diff(
    file_path: str,
    func_start: int,
    func_end: int,
    revision: str,
    target_dir: str = ".",
) -> str:
    """Extract unified diff lines that fall within a function's line range.

    Tracks new-file line numbers within each hunk and only includes
    lines whose position falls within [func_start, func_end].
    """
    try:
        rel_path = str(Path(file_path).relative_to(Path(target_dir).resolve()))
    except ValueError:
        rel_path = file_path

    cmd = ["git", "-C", target_dir, "diff", revision, "--", rel_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

    if not result.stdout:
        return ""

    # First pass: collect hunks as (header, [(diff_line, new_line_no), ...])
    raw_lines = result.stdout.splitlines()
    hunks: list[tuple[str, list[tuple[str, int]]]] = []
    current_header = ""
    current_items: list[tuple[str, int]] = []
    line_no = 0

    for raw in raw_lines:
        m = _HUNK_HEADER_RE.match(raw)
        if m:
            if current_header:
                hunks.append((current_header, current_items))
            current_header = raw
            current_items = []
            line_no = int(m.group(3))
            continue
        if raw.startswith(("diff --git", "index ", "--- ", "+++ ")):
            continue
        if not current_header:
            continue

        if raw.startswith("-"):
            # Deletion: associated with current position, doesn't advance
            current_items.append((raw, line_no))
        elif raw.startswith("+"):
            # Addition: at line_no in new file, then advance
            current_items.append((raw, line_no))
            line_no += 1
        else:
            # Context: at line_no in new file, then advance
            current_items.append((raw, line_no))
            line_no += 1

    if current_header:
        hunks.append((current_header, current_items))

    # Second pass: filter to lines within function range
    output: list[str] = []
    for _header, items in hunks:
        filtered = [
            dl for dl, ln in items if func_start <= ln <= func_end
        ]
        if filtered:
            output.extend(filtered)

    return "\n".join(output)


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
