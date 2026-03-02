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
        index_dir = Path(target_dir) / ".owl" / "index"

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
) -> list[str]:
    if file_extensions is None:
        file_extensions = [".py"]

    root = Path(directory).resolve()
    gitignore_spec = _load_gitignore_spec(root)

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


def _should_skip(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    skip_dirs = {
        ".git", ".owl", "__pycache__", "node_modules",
        ".venv", "venv", ".tox", ".mypy_cache", ".ruff_cache",
        ".pytest_cache", "dist", "build", ".eggs",
    }
    return bool(skip_dirs & set(parts))


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
