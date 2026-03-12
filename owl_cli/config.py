from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "Shuu12121/Owl-ph2-len2048"
CACHE_BASE = Path.home() / ".cache" / "owl-cli"


@dataclass
class OwlConfig:
    model_name: str = DEFAULT_MODEL
    batch_size: int = 8
    top_k: int = 10
    file_extensions: list[str] = field(
        default_factory=lambda: [
            ".py", ".js", ".jsx", ".ts", ".tsx",
            ".java", ".go", ".rb", ".rs", ".php",
        ]
    )
    target_dir: str = "."
    auto_annotate: bool = False
    exclude_patterns: list[str] = field(default_factory=list)

    @classmethod
    def load(
        cls,
        target_dir: str = ".",
        model_override: str | None = None,
        top_k_override: int | None = None,
    ) -> OwlConfig:
        config = cls(target_dir=str(Path(target_dir).resolve()))

        config_path = get_index_dir(config.target_dir) / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
            if "model_name" in data:
                config.model_name = data["model_name"]
            if "batch_size" in data:
                config.batch_size = data["batch_size"]
            if "top_k" in data:
                config.top_k = data["top_k"]
            if "file_extensions" in data:
                config.file_extensions = data["file_extensions"]
            if "auto_annotate" in data:
                config.auto_annotate = bool(data["auto_annotate"])
            if "exclude_patterns" in data:
                config.exclude_patterns = data["exclude_patterns"]

        if env_model := os.environ.get("OWL_MODEL_NAME"):
            config.model_name = env_model
        if env_batch := os.environ.get("OWL_BATCH_SIZE"):
            config.batch_size = int(env_batch)
        if env_top_k := os.environ.get("OWL_TOP_K"):
            config.top_k = int(env_top_k)
        if os.environ.get("OWL_AUTO_ANNOTATE", "").lower() in ("1", "true", "yes"):
            config.auto_annotate = True

        if model_override:
            config.model_name = model_override
        if top_k_override is not None:
            config.top_k = top_k_override

        return config


def get_index_dir(target_dir: str = ".") -> Path:
    resolved = str(Path(target_dir).resolve())
    dir_hash = hashlib.sha256(resolved.encode()).hexdigest()[:16]
    path = CACHE_BASE / dir_hash
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_base() -> Path:
    return CACHE_BASE
