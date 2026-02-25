"""Skeletonizer: strip function bodies, keep signatures + docstrings."""

from __future__ import annotations

from pathlib import Path

import tree_sitter
import tree_sitter_python as tspython

_LANGUAGE = tree_sitter.Language(tspython.language())
_PARSER = tree_sitter.Parser(_LANGUAGE)


def skeletonize(source: str) -> str:
    """Strip function/method bodies, keeping signatures and docstrings.

    Replaces body contents (after docstring) with `...`.
    Preserves original formatting and indentation.
    """
    source_bytes = source.encode("utf-8")
    tree = _PARSER.parse(source_bytes)
    # Collect byte ranges to replace: (start, end, replacement)
    replacements: list[tuple[int, int, bytes]] = []
    _collect_replacements(tree.root_node, source_bytes, replacements)

    # Apply replacements in reverse order to preserve byte offsets
    result = bytearray(source_bytes)
    for start, end, replacement in sorted(replacements, reverse=True):
        result[start:end] = replacement
    return result.decode("utf-8")


def skeletonize_file(file_path: str | Path) -> str:
    """Skeletonize a file from disk."""
    return skeletonize(Path(file_path).read_text())


def _collect_replacements(
    node: tree_sitter.Node,
    source: bytes,
    replacements: list[tuple[int, int, bytes]],
) -> None:
    """Recursively find function bodies to replace."""
    for child in node.children:
        actual = child
        if child.type == "decorated_definition":
            for sub in child.children:
                if sub.type in ("function_definition", "class_definition"):
                    actual = sub
                    break

        if actual.type == "function_definition":
            body = actual.child_by_field_name("body")
            if body and body.type == "block":
                _replace_body(body, source, replacements)

        elif actual.type == "class_definition":
            body = actual.child_by_field_name("body")
            if body and body.type == "block":
                # Recurse into class body to find methods
                _collect_replacements(body, source, replacements)

        else:
            _collect_replacements(child, source, replacements)


def _replace_body(
    body: tree_sitter.Node,
    source: bytes,
    replacements: list[tuple[int, int, bytes]],
) -> None:
    """Replace a function body, keeping the docstring if present."""
    children = [c for c in body.children if c.type not in ("newline",)]

    # Find docstring (first expression_statement containing a string)
    docstring_end = None
    rest_start = None

    for i, child in enumerate(children):
        if i == 0 and child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    docstring_end = child.end_byte
                    break
            if docstring_end is not None:
                # Find the start of the next meaningful content
                if i + 1 < len(children):
                    rest_start = children[i + 1].start_byte
                else:
                    rest_start = body.end_byte
                break
            else:
                rest_start = child.start_byte
                break
        elif child.type not in ("indent", "dedent", "INDENT", "DEDENT"):
            rest_start = child.start_byte
            break

    if rest_start is None:
        return

    # Determine indentation of body content
    indent = _get_indent(body, source)

    if docstring_end is not None:
        # Replace everything after docstring with ...
        replacements.append((rest_start, body.end_byte, f"{indent}...\n".encode()))
    else:
        # Replace entire body content with ...
        replacements.append((rest_start, body.end_byte, f"{indent}...\n".encode()))


def _get_indent(body: tree_sitter.Node, source: bytes) -> str:
    """Get the indentation string for the first line of a block."""
    # Find the start of the line containing the first child
    for child in body.children:
        if child.type in ("newline", "indent", "dedent", "INDENT", "DEDENT"):
            continue
        line_start = source.rfind(b"\n", 0, child.start_byte)
        if line_start == -1:
            line_start = 0
        else:
            line_start += 1
        prefix = source[line_start:child.start_byte]
        return prefix.decode("utf-8")
    return "    "
