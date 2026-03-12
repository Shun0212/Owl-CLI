from __future__ import annotations

from tree_sitter import Language, Parser
import tree_sitter_rust

_RUST_LANGUAGE = Language(tree_sitter_rust.language())
_RUST_PARSER = Parser(_RUST_LANGUAGE)


def extract_rust_functions(source_bytes: bytes) -> list[dict]:
    tree = _RUST_PARSER.parse(source_bytes)
    root = tree.root_node

    impl_blocks: list[dict] = []
    _collect_impl_blocks(root, impl_blocks)

    functions: list[dict] = []
    _collect_functions(root, source_bytes, impl_blocks, functions)

    return functions


def _collect_impl_blocks(node, impl_blocks: list[dict]) -> None:
    """Collect impl blocks as class-like containers."""
    if node.type == "impl_item":
        # The type name comes after "impl" keyword.
        type_node = next(
            (c for c in node.children if c.type == "type_identifier"), None
        )
        if type_node:
            impl_blocks.append(
                {
                    "name": type_node.text.decode("utf-8"),
                    "start_line": node.start_point[0],
                    "end_line": node.end_point[0],
                }
            )
    for child in node.children:
        _collect_impl_blocks(child, impl_blocks)


def _collect_functions(
    node, source_bytes: bytes, impl_blocks: list[dict], functions: list[dict]
) -> None:
    if node.type == "function_item":
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
            for impl in impl_blocks:
                if impl["start_line"] <= start_line <= impl["end_line"]:
                    class_name = impl["name"]
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
        _collect_functions(child, source_bytes, impl_blocks, functions)
