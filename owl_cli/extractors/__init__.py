from __future__ import annotations

from pathlib import Path

from .python_extractor import extract_python_functions
from .javascript_extractor import extract_javascript_functions
from .typescript_extractor import extract_typescript_functions, extract_tsx_functions
from .java_extractor import extract_java_functions
from .go_extractor import extract_go_functions
from .ruby_extractor import extract_ruby_functions
from .rust_extractor import extract_rust_functions
from .php_extractor import extract_php_functions

_EXTRACTORS: dict[str, callable] = {
    ".py": extract_python_functions,
    ".js": extract_javascript_functions,
    ".jsx": extract_javascript_functions,
    ".ts": extract_typescript_functions,
    ".tsx": extract_tsx_functions,
    ".java": extract_java_functions,
    ".go": extract_go_functions,
    ".rb": extract_ruby_functions,
    ".rs": extract_rust_functions,
    ".php": extract_php_functions,
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
