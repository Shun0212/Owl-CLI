from __future__ import annotations

import gc
import os
import sys
import warnings

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from .config import DEFAULT_MODEL

_model: SentenceTransformer | None = None
_model_name: str | None = None
_device: str | None = None


def get_device() -> str:
    global _device
    if _device is not None:
        return _device

    if torch.backends.mps.is_available():
        _device = "mps"
    elif torch.cuda.is_available():
        _device = "cuda"
    else:
        _device = "cpu"
    return _device


def _is_model_cached(model_name: str) -> bool:
    """Check if the model already exists in the HuggingFace cache."""
    hf_home = os.environ.get(
        "HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    )
    cache_dir = os.path.join(hf_home, "hub")
    model_dir = f"models--{model_name.replace('/', '--')}"
    return os.path.isdir(os.path.join(cache_dir, model_dir))


def get_model(model_name: str = DEFAULT_MODEL) -> SentenceTransformer:
    global _model, _model_name, _device

    if _model is not None and _model_name == model_name:
        return _model

    device = get_device()
    warnings.filterwarnings("ignore", message=".*torch.compile.*")

    if not _is_model_cached(model_name):
        from .banner import print_download_banner

        print_download_banner(model_name)

    try:
        _model = SentenceTransformer(model_name, device=device)
    except RuntimeError:
        if device == "mps":
            print("MPS failed, falling back to CPU", file=sys.stderr)
            _device = "cpu"
            _model = SentenceTransformer(model_name, device="cpu")
        else:
            raise

    _model_name = model_name
    return _model


def encode(
    texts: list[str],
    model_name: str = DEFAULT_MODEL,
    batch_size: int = 8,
    max_retries: int = 3,
    show_progress: bool = True,
) -> np.ndarray:
    model = get_model(model_name)

    current_batch_size = batch_size
    for attempt in range(max_retries):
        try:
            embeddings = model.encode(
                texts,
                batch_size=current_batch_size,
                show_progress_bar=show_progress,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return np.asarray(embeddings, dtype=np.float32)
        except (RuntimeError, torch.OutOfMemoryError):
            cleanup_memory()
            current_batch_size = max(1, current_batch_size // 2)
            if attempt == max_retries - 1:
                raise
            print(
                f"Memory error, retrying with batch_size={current_batch_size}",
                file=sys.stderr,
            )

    raise RuntimeError("Failed to encode after retries")


def cleanup_memory() -> None:
    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    elif torch.cuda.is_available():
        torch.cuda.empty_cache()
