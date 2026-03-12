from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_go

_GO_LANGUAGE = Language(tree_sitter_go.language())
_GO_PARSER = Parser(_GO_LANGUAGE)


def extract_go_functions(source_bytes: bytes) -> list[dict]:
    tree = _GO_PARSER.parse(source_bytes)
    root = tree.root_node

    # Go has no classes, but methods belong to receiver types.
    type_specs: list[dict] = []
    _collect_type_specs(root, type_specs)

    functions: list[dict] = []
    _collect_functions(root, source_bytes, type_specs, functions)

    return functions


def _collect_type_specs(node, type_specs: list[dict]) -> None:
    """Collect type declarations (struct, interface) as class-like containers."""
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                name_node = next(
                    (c for c in child.children if c.type == "type_identifier"), None
                )
                if name_node:
                    type_specs.append(
                        {
                            "name": name_node.text.decode("utf-8"),
                            "start_line": child.start_point[0],
                            "end_line": child.end_point[0],
                        }
                    )
    for child in node.children:
        _collect_type_specs(child, type_specs)


def _collect_functions(
    node, source_bytes: bytes, type_specs: list[dict], functions: list[dict]
) -> None:
    if node.type == "function_declaration":
        name_node = next(
            (c for c in node.children if c.type == "identifier"), None
        )
        if name_node:
            _append_function(node, name_node, source_bytes, None, functions)

    elif node.type == "method_declaration":
        name_node = next(
            (c for c in node.children if c.type == "field_identifier"), None
        )
        receiver_type = _get_receiver_type(node)
        if name_node:
            _append_function(node, name_node, source_bytes, receiver_type, functions)

    for child in node.children:
        _collect_functions(child, source_bytes, type_specs, functions)


def _get_receiver_type(node) -> str | None:
    """Extract the receiver type name from a method_declaration."""
    param_list = next(
        (c for c in node.children if c.type == "parameter_list"), None
    )
    if param_list is None:
        return None
    # Look for type_identifier inside the parameter_list (receiver).
    for child in param_list.children:
        if child.type == "parameter_declaration":
            for c in child.children:
                if c.type == "type_identifier":
                    return c.text.decode("utf-8")
                if c.type == "pointer_type":
                    inner = next(
                        (x for x in c.children if x.type == "type_identifier"), None
                    )
                    if inner:
                        return inner.text.decode("utf-8")
    return None


def _append_function(
    node, name_node, source_bytes: bytes, class_name: str | None, functions: list[dict]
) -> None:
    name = name_node.text.decode("utf-8")
    start_line = node.start_point[0]
    end_line = node.end_point[0]
    code = source_bytes[node.start_byte : node.end_byte].decode(
        "utf-8", errors="replace"
    )

    functions.append(
        {
            "name": name,
            "code": code,
            "lineno": start_line + 1,
            "end_lineno": end_line + 1,
            "class_name": class_name,
        }
    )
