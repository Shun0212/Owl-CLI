from __future__ import annotations

from pathlib import Path

from .python_extractor import extract_python_functions

_EXTRACTORS: dict[str, callable] = {
    ".py": extract_python_functions,
}


def extract_functions(file_path: str | Path) -> list[dict]:
    file_path = Path(file_path)
    ext = file_path.suffix

    extractor = _EXTRACTORS.get(ext)
    if extractor is None:
        return []

    try:
        source_bytes = file_path.read_bytes()
    except (OSError, UnicodeDecodeError) as e:
        return []

    results = extractor(source_bytes)
    for func in results:
        func["file"] = str(file_path)

    return results


def supported_extensions() -> list[str]:
    return list(_EXTRACTORS.keys())
