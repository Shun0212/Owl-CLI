from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_python

_PY_LANGUAGE = Language(tree_sitter_python.language())
_PY_PARSER = Parser(_PY_LANGUAGE)


def extract_python_functions(source_bytes: bytes) -> list[dict]:
    tree = _PY_PARSER.parse(source_bytes)
    root = tree.root_node

    classes: list[dict] = []
    _collect_classes(root, classes)

    functions: list[dict] = []
    _collect_functions(root, source_bytes, classes, functions)

    return functions


def _collect_classes(node, classes: list[dict]) -> None:
    if node.type == "class_definition":
        name_node = next(
            (c for c in node.children if c.type == "identifier"), None
        )
        if name_node:
            classes.append(
                {
                    "name": name_node.text.decode("utf-8"),
                    "start_line": node.start_point[0],
                    "end_line": node.end_point[0],
                }
            )
    for child in node.children:
        _collect_classes(child, classes)


def _collect_functions(
    node, source_bytes: bytes, classes: list[dict], functions: list[dict]
) -> None:
    if node.type == "function_definition":
        name_node = next(
            (c for c in node.children if c.type == "identifier"), None
        )
        if name_node:
            name = name_node.text.decode("utf-8")
            start_line = node.start_point[0]
            end_line = node.end_point[0]
            code = source_bytes[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )

            class_name = None
            for cls in classes:
                if cls["start_line"] <= start_line <= cls["end_line"]:
                    class_name = cls["name"]
                    break

            functions.append(
                {
                    "name": name,
                    "code": code,
                    "lineno": start_line + 1,
                    "end_lineno": end_line + 1,
                    "class_name": class_name,
                }
            )

    for child in node.children:
        _collect_functions(child, source_bytes, classes, functions)
