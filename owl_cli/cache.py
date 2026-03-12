from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import faiss
import numpy as np
import pathspec

from .config import get_index_dir


@dataclass
class CacheState:
    functions: list[dict] = field(default_factory=list)
    embeddings: np.ndarray | None = None
    faiss_index: faiss.IndexFlatIP | None = None
    file_hashes: dict[str, str] = field(default_factory=dict)
    model_name: str = ""
    last_indexed: float = 0.0

    def save(self, target_dir: str) -> None:
        index_dir = get_index_dir(target_dir)

        meta = {
            "file_hashes": self.file_hashes,
            "model_name": self.model_name,
            "last_indexed": self.last_indexed,
            "num_functions": len(self.functions),
        }
        _atomic_write_json(index_dir / "meta.json", meta)
        _atomic_write_json(index_dir / "functions.json", self.functions)

        if self.embeddings is not None:
            tmp = index_dir / "embeddings_tmp.npy"
            np.save(tmp, self.embeddings)
            tmp.replace(index_dir / "embeddings.npy")

        if self.faiss_index is not None:
            tmp = str(index_dir / "faiss.index.tmp")
            faiss.write_index(self.faiss_index, tmp)
            Path(tmp).replace(index_dir / "faiss.index")

    @classmethod
    def load(cls, target_dir: str) -> CacheState | None:
        index_dir = get_index_dir(target_dir)

        meta_path = index_dir / "meta.json"
        funcs_path = index_dir / "functions.json"
        emb_path = index_dir / "embeddings.npy"
        faiss_path = index_dir / "faiss.index"

        if not all(p.exists() for p in [meta_path, funcs_path, emb_path, faiss_path]):
            return None

        try:
            with open(meta_path) as f:
                meta = json.load(f)
            with open(funcs_path) as f:
                functions = json.load(f)
            embeddings = np.load(emb_path)
            faiss_index = faiss.read_index(str(faiss_path))
        except (json.JSONDecodeError, OSError, RuntimeError):
            return None

        return cls(
            functions=functions,
            embeddings=embeddings,
            faiss_index=faiss_index,
            file_hashes=meta.get("file_hashes", {}),
            model_name=meta.get("model_name", ""),
            last_indexed=meta.get("last_indexed", 0.0),
        )


def compute_file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_files(
    directory: str,
    file_extensions: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    if file_extensions is None:
        file_extensions = [".py"]

    root = Path(directory).resolve()
    gitignore_spec = _load_gitignore_spec(root)
    owlignore_spec = _load_owlignore_spec(root)
    exclude_spec = _build_exclude_spec(exclude_patterns)

    results: list[str] = []
    for ext in file_extensions:
        for path in root.rglob(f"*{ext}"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root))
            if _should_skip(rel):
                continue
            if gitignore_spec and gitignore_spec.match_file(rel):
                continue
            if owlignore_spec and owlignore_spec.match_file(rel):
                continue
            if exclude_spec and exclude_spec.match_file(rel):
                continue
            results.append(str(path))

    results.sort()
    return results


def diff_files(
    current_hashes: dict[str, str],
    cached_hashes: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    added_or_modified = []
    unchanged = []
    deleted = []

    for path, h in current_hashes.items():
        if path in cached_hashes and cached_hashes[path] == h:
            unchanged.append(path)
        else:
            added_or_modified.append(path)

    for path in cached_hashes:
        if path not in current_hashes:
            deleted.append(path)

    return added_or_modified, unchanged, deleted


def _load_gitignore_spec(root: Path) -> pathspec.PathSpec | None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    try:
        with open(gitignore) as f:
            return pathspec.PathSpec.from_lines("gitwildmatch", f)
    except OSError:
        return None


def _load_owlignore_spec(root: Path) -> pathspec.PathSpec | None:
    owlignore = root / ".owlignore"
    if not owlignore.exists():
        return None
    try:
        with open(owlignore) as f:
            return pathspec.PathSpec.from_lines("gitwildmatch", f)
    except OSError:
        return None


def _build_exclude_spec(patterns: list[str] | None) -> pathspec.PathSpec | None:
    if not patterns:
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


@dataclass
class ExcludeSuggestion:
    pattern: str
    reason: str
    file_count: int


# Well-known directory names that typically contain non-production code.
_KNOWN_NON_PROD_DIRS: dict[str, str] = {
    "tests": "test suite",
    "test": "test suite",
    "testing": "test suite",
    "spec": "test specs",
    "specs": "test specs",
    "__tests__": "test suite (JS-style)",
    "examples": "example / demo code",
    "example": "example / demo code",
    "samples": "sample code",
    "sample": "sample code",
    "demos": "demo code",
    "demo": "demo code",
    "benchmarks": "benchmark code",
    "benchmark": "benchmark code",
    "docs": "documentation",
    "doc": "documentation",
    "fixtures": "test fixtures",
    "scripts": "utility scripts",
    "tools": "utility tools",
    "migrations": "database migrations",
    "e2e": "end-to-end tests",
    "integration": "integration tests",
    "stubs": "type stubs",
}

# File-name patterns that typically indicate non-production code.
_KNOWN_NON_PROD_PATTERNS: dict[str, str] = {
    "test_*.py": "test files (pytest convention)",
    "*_test.py": "test files (suffix convention)",
    "conftest.py": "pytest configuration",
    "setup.py": "package setup script",
    "noxfile.py": "Nox automation",
    "fabfile.py": "Fabric deploy script",
    "tasks.py": "Invoke task runner",
    "Gruntfile.js": "Grunt task runner",
    "gulpfile.js": "Gulp task runner",
    "webpack.config.*": "Webpack config",
    "vite.config.*": "Vite config",
    "jest.config.*": "Jest config",
    "*.stories.*": "Storybook stories",
    "*.spec.*": "spec / test files",
    "*.test.*": "test files",
}


def detect_exclude_suggestions(
    directory: str,
    file_extensions: list[str] | None = None,
) -> list[ExcludeSuggestion]:
    """Scan the project and suggest directories / patterns to exclude."""
    if file_extensions is None:
        file_extensions = [".py"]

    root = Path(directory).resolve()
    gitignore_spec = _load_gitignore_spec(root)
    owlignore_spec = _load_owlignore_spec(root)
    ext_set = set(file_extensions)

    suggestions: list[ExcludeSuggestion] = []
    seen_patterns: set[str] = set()

    # 1) Check top-level and second-level directories against known names.
    for depth_limit in (1, 2):
        for d in sorted(root.rglob("*")):
            if not d.is_dir():
                continue
            rel = d.relative_to(root)
            if len(rel.parts) > depth_limit:
                continue
            if _should_skip(str(rel)):
                continue
            dirname = rel.parts[-1].lower()
            if dirname in _KNOWN_NON_PROD_DIRS:
                pattern = str(rel) + "/"
                if pattern in seen_patterns:
                    continue
                # Count matching files inside.
                count = sum(
                    1
                    for ext in ext_set
                    for f in d.rglob(f"*{ext}")
                    if f.is_file()
                )
                if count == 0:
                    continue
                reason = _KNOWN_NON_PROD_DIRS[dirname]
                suggestions.append(ExcludeSuggestion(pattern, reason, count))
                seen_patterns.add(pattern)

    # 2) Check file-name patterns at the project root level.
    for glob_pat, reason in _KNOWN_NON_PROD_PATTERNS.items():
        matches = list(root.glob(glob_pat))
        # Also check one level deep.
        matches += list(root.glob(f"*/{glob_pat}"))
        real_matches = [
            m for m in matches
            if m.is_file()
            and m.suffix in ext_set
            and not _should_skip(str(m.relative_to(root)))
        ]
        if real_matches and glob_pat not in seen_patterns:
            suggestions.append(
                ExcludeSuggestion(glob_pat, reason, len(real_matches))
            )
            seen_patterns.add(glob_pat)

    return suggestions


def _should_skip(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    skip_dirs = {
        ".git", "__pycache__", "node_modules",
        ".venv", "venv", ".tox", ".mypy_cache", ".ruff_cache",
        ".pytest_cache", "dist", "build", ".eggs",
        # Go
        "vendor",
        # Rust
        "target",
        # Java
        ".gradle", ".mvn", ".idea",
        # Ruby
        ".bundle",
        # PHP
        ".composer",
    }
    return bool(skip_dirs & set(parts))


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
