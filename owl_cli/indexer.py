from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import faiss
import numpy as np

from .cache import CacheState, compute_file_hash, diff_files, scan_files
from .config import OwlConfig
from .extractors import extract_functions
from .history import save_history_entry
from .model import encode


@dataclass
class SearchResult:
    name: str
    code: str
    file: str
    lineno: int
    end_lineno: int
    class_name: str | None
    score: float


@dataclass
class IndexResult:
    num_files: int
    num_functions: int
    time_taken: float
    from_cache: bool


class CodeSearchEngine:
    def __init__(self, config: OwlConfig):
        self.config = config
        self.cache: CacheState | None = None

    def build_index(self, force: bool = False) -> IndexResult:
        start = time.time()
        target = self.config.target_dir

        files = scan_files(target, self.config.file_extensions)
        if not files:
            return IndexResult(0, 0, time.time() - start, False)

        current_hashes = {f: compute_file_hash(f) for f in files}

        if not force:
            self.cache = CacheState.load(target)

        if (
            self.cache is not None
            and not force
            and self.cache.model_name == self.config.model_name
        ):
            changed, unchanged, deleted = diff_files(
                current_hashes, self.cache.file_hashes
            )
            if not changed and not deleted:
                self.cache.file_hashes = current_hashes
                return IndexResult(
                    len(files),
                    len(self.cache.functions),
                    time.time() - start,
                    True,
                )
        else:
            changed = files
            unchanged = []
            self.cache = None

        reused_functions: list[dict] = []
        reused_embeddings: list[np.ndarray] = []

        if self.cache is not None and self.cache.embeddings is not None:
            unchanged_set = set(unchanged)
            for i, func in enumerate(self.cache.functions):
                if func.get("file") in unchanged_set:
                    reused_functions.append(func)
                    reused_embeddings.append(self.cache.embeddings[i])

        new_functions: list[dict] = []
        print(f"Extracting functions from {len(changed)} file(s)...", file=sys.stderr)
        for file_path in changed:
            funcs = extract_functions(file_path)
            new_functions.extend(funcs)

        all_functions = reused_functions + new_functions

        if not all_functions:
            return IndexResult(len(files), 0, time.time() - start, False)

        if new_functions:
            codes = [f["code"] for f in new_functions]
            print(
                f"Encoding {len(codes)} function(s)...", file=sys.stderr
            )
            new_embs = encode(
                codes,
                model_name=self.config.model_name,
                batch_size=self.config.batch_size,
            )
        else:
            new_embs = np.empty((0, 0), dtype=np.float32)

        if reused_embeddings:
            reused_embs = np.stack(reused_embeddings)
            if new_embs.size > 0:
                all_embeddings = np.vstack([reused_embs, new_embs])
            else:
                all_embeddings = reused_embs
        else:
            all_embeddings = new_embs

        dim = all_embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(all_embeddings)

        self.cache = CacheState(
            functions=all_functions,
            embeddings=all_embeddings,
            faiss_index=index,
            file_hashes=current_hashes,
            model_name=self.config.model_name,
            last_indexed=time.time(),
        )
        self.cache.save(target)

        elapsed = time.time() - start
        return IndexResult(len(files), len(all_functions), elapsed, False)

    def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        if top_k is None:
            top_k = self.config.top_k

        if self.cache is None:
            self.cache = CacheState.load(self.config.target_dir)

        if self.cache is None or self.cache.faiss_index is None:
            print("No index found, building...", file=sys.stderr)
            self.build_index()
        else:
            files = scan_files(
                self.config.target_dir, self.config.file_extensions
            )
            current_hashes = {f: compute_file_hash(f) for f in files}
            changed, _, deleted = diff_files(
                current_hashes, self.cache.file_hashes
            )
            if changed or deleted:
                print("Files changed, rebuilding index...", file=sys.stderr)
                self.build_index()

        if self.cache is None or self.cache.faiss_index is None:
            return []

        query_vec = encode(
            [query],
            model_name=self.config.model_name,
            batch_size=1,
            show_progress=False,
        )

        k = min(top_k, self.cache.faiss_index.ntotal)
        if k == 0:
            return []

        scores, indices = self.cache.faiss_index.search(query_vec, k)

        results: list[SearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            func = self.cache.functions[idx]
            results.append(
                SearchResult(
                    name=func["name"],
                    code=func["code"],
                    file=func["file"],
                    lineno=func["lineno"],
                    end_lineno=func["end_lineno"],
                    class_name=func.get("class_name"),
                    score=float(score),
                )
            )

        save_history_entry(self.config.target_dir, query, results)

        return results

    def get_status(self) -> dict | None:
        if self.cache is None:
            self.cache = CacheState.load(self.config.target_dir)
        if self.cache is None:
            return None
        return {
            "num_files": len(self.cache.file_hashes),
            "num_functions": len(self.cache.functions),
            "model_name": self.cache.model_name,
            "last_indexed": self.cache.last_indexed,
        }
