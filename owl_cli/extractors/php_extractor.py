from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_php

_PHP_LANGUAGE = Language(tree_sitter_php.language_php())
_PHP_PARSER = Parser(_PHP_LANGUAGE)


def extract_php_functions(source_bytes: bytes) -> list[dict]:
    tree = _PHP_PARSER.parse(source_bytes)
    root = tree.root_node

    classes: list[dict] = []
    _collect_classes(root, classes)

    functions: list[dict] = []
    _collect_functions(root, source_bytes, classes, functions)

    return functions


def _collect_classes(node, classes: list[dict]) -> None:
    if node.type in ("class_declaration", "interface_declaration", "trait_declaration"):
        name_node = next(
            (c for c in node.children if c.type == "name"), None
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
    if node.type in ("function_definition", "method_declaration"):
        name_node = next(
            (c for c in node.children if c.type == "name"), None
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
