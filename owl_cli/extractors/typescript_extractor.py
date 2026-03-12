from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_typescript

_TS_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
_TS_PARSER = Parser(_TS_LANGUAGE)

_TSX_LANGUAGE = Language(tree_sitter_typescript.language_tsx())
_TSX_PARSER = Parser(_TSX_LANGUAGE)


def extract_typescript_functions(source_bytes: bytes) -> list[dict]:
    return _extract(source_bytes, _TS_PARSER)


def extract_tsx_functions(source_bytes: bytes) -> list[dict]:
    return _extract(source_bytes, _TSX_PARSER)


def _extract(source_bytes: bytes, parser: Parser) -> list[dict]:
    tree = parser.parse(source_bytes)
    root = tree.root_node

    classes: list[dict] = []
    _collect_classes(root, classes)

    functions: list[dict] = []
    _collect_functions(root, source_bytes, classes, functions)
    _collect_arrow_functions(root, source_bytes, classes, functions)

    return functions


def _collect_classes(node, classes: list[dict]) -> None:
    if node.type in ("class_declaration", "abstract_class_declaration"):
        name_node = next(
            (c for c in node.children if c.type in ("type_identifier", "identifier")),
            None,
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
    if node.type in ("function_declaration", "generator_function_declaration"):
        name_node = next(
            (c for c in node.children if c.type == "identifier"), None
        )
        if name_node:
            _append_function(node, name_node, source_bytes, classes, functions)

    elif node.type in ("method_definition", "abstract_method_definition"):
        name_node = next(
            (c for c in node.children if c.type == "property_identifier"), None
        )
        if name_node:
            _append_function(node, name_node, source_bytes, classes, functions)

    for child in node.children:
        _collect_functions(child, source_bytes, classes, functions)


def _collect_arrow_functions(
    node, source_bytes: bytes, classes: list[dict], functions: list[dict]
) -> None:
    if node.type == "variable_declarator":
        name_node = next(
            (c for c in node.children if c.type == "identifier"), None
        )
        value_node = next(
            (c for c in node.children if c.type in ("arrow_function", "function")), None
        )
        if name_node and value_node:
            _append_function(node, name_node, source_bytes, classes, functions)
            return

    for child in node.children:
        _collect_arrow_functions(child, source_bytes, classes, functions)


def _append_function(
    node, name_node, source_bytes: bytes, classes: list[dict], functions: list[dict]
) -> None:
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
