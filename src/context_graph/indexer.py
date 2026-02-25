"""tree-sitter based Python indexer: extracts symbols, references, and edges."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import tree_sitter
import tree_sitter_python as tspython

from .db import Database
from .models import EdgeRecord, IndexedFile, NodeRecord

_LANGUAGE = tree_sitter.Language(tspython.language())
_PARSER = tree_sitter.Parser(_LANGUAGE)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_docstring(body_node: tree_sitter.Node, source: bytes) -> str | None:
    """Extract docstring from the first statement in a block if it's a string."""
    if body_node is None or body_node.type != "block":
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    raw = _node_text(sub, source)
                    # Strip triple quotes
                    for q in ('"""', "'''"):
                        if raw.startswith(q) and raw.endswith(q):
                            return raw[3:-3].strip()
                    # Single-quoted string used as docstring
                    if (raw.startswith('"') and raw.endswith('"')) or (
                        raw.startswith("'") and raw.endswith("'")
                    ):
                        return raw[1:-1].strip()
                    return raw
            break
        # Skip comments/newlines but stop at non-expression-statement
        if child.type not in ("comment", "newline"):
            break
    return None


def _extract_decorators(node: tree_sitter.Node, source: bytes) -> list[str]:
    """Extract decorator names from a decorated_definition or inline decorators."""
    decorators = []
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type == "decorator":
                # Get everything after '@'
                text = _node_text(child, source).lstrip("@").strip()
                decorators.append(text)
    return decorators


def _build_signature(node: tree_sitter.Node, source: bytes) -> str:
    """Build signature line from a function_definition node."""
    parts = []
    for child in node.children:
        if child.type == ":":
            break
        parts.append(_node_text(child, source))
    return " ".join(parts) + ":"


def _module_id_from_path(file_path: str, project_root: str) -> str:
    """Convert file path to module-style qualified name."""
    rel = Path(file_path).relative_to(project_root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


class Indexer:
    """Indexes Python files using tree-sitter."""

    def __init__(self, db: Database, project_root: str | Path):
        self.db = db
        self.project_root = str(Path(project_root).resolve())

    def index_file(self, file_path: str | Path, force: bool = False) -> list[NodeRecord]:
        """Index a single Python file. Returns list of extracted nodes."""
        file_path = Path(file_path).resolve()
        fp_str = str(file_path)

        # Incremental: check hash
        fhash = file_hash(file_path)
        if not force:
            existing = self.db.get_indexed_file(fp_str)
            if existing and existing.file_hash == fhash:
                return self.db.list_nodes(file_path=fp_str)

        source = file_path.read_bytes()
        tree = _PARSER.parse(source)
        now = time.time()

        module_id = _module_id_from_path(fp_str, self.project_root)

        # Clear old data for this file
        self.db.delete_nodes_for_file(fp_str)
        self.db.delete_edges_for_file(fp_str)

        # Create module node
        root = tree.root_node
        module_node = NodeRecord(
            id=module_id,
            kind="module",
            name=module_id.split(".")[-1],
            file_path=fp_str,
            line_start=root.start_point[0] + 1,
            line_end=root.end_point[0] + 1,
            file_hash=fhash,
            indexed_at=now,
        )

        nodes: list[NodeRecord] = [module_node]
        edges: list[EdgeRecord] = []

        # Walk top-level children
        self._extract_symbols(root, source, module_id, fp_str, fhash, now, nodes, edges)
        self._extract_imports(root, source, module_id, fp_str, nodes, edges, now, fhash)
        self._extract_calls(root, source, module_id, fp_str, edges)

        self.db.upsert_nodes(nodes)
        self.db.upsert_edges(edges)
        self.db.upsert_indexed_file(IndexedFile(
            file_path=fp_str,
            file_hash=fhash,
            indexed_at=now,
            node_count=len(nodes),
        ))

        return nodes

    def index_project(self, force: bool = False) -> int:
        """Index all .py files under project root. Returns file count."""
        count = 0
        root = Path(self.project_root)
        for py_file in sorted(root.rglob("*.py")):
            # Skip venv, cache, context_graph dirs
            parts = py_file.relative_to(root).parts
            if any(p.startswith(".") or p in ("__pycache__", ".venv", "node_modules") for p in parts):
                continue
            self.index_file(py_file, force=force)
            count += 1
        return count

    def remove_file(self, file_path: str | Path) -> None:
        """Remove all index data for a file."""
        fp_str = str(Path(file_path).resolve())
        self.db.delete_nodes_for_file(fp_str)
        self.db.delete_edges_for_file(fp_str)
        self.db.delete_indexed_file(fp_str)

    def _extract_symbols(
        self,
        parent_node: tree_sitter.Node,
        source: bytes,
        parent_id: str,
        file_path: str,
        fhash: str,
        now: float,
        nodes: list[NodeRecord],
        edges: list[EdgeRecord],
    ) -> None:
        """Recursively extract function/class definitions."""
        for child in parent_node.children:
            actual = child
            decorators: list[str] = []

            if child.type == "decorated_definition":
                decorators = _extract_decorators(child, source)
                # The actual definition is the last child
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        actual = sub
                        break

            if actual.type == "function_definition":
                name_node = actual.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(name_node, source)
                node_id = f"{parent_id}.{name}"

                # Determine kind
                kind = "method" if parent_node.type == "block" else "function"
                # If parent is class body, it's a method
                body = actual.child_by_field_name("body")

                node = NodeRecord(
                    id=node_id,
                    kind=kind,
                    name=name,
                    file_path=file_path,
                    line_start=actual.start_point[0] + 1,
                    line_end=actual.end_point[0] + 1,
                    parent_id=parent_id,
                    signature=_build_signature(actual, source),
                    docstring=_extract_docstring(body, source),
                    decorators=decorators,
                    file_hash=fhash,
                    indexed_at=now,
                )
                nodes.append(node)

                # Add decorator edges
                for dec in decorators:
                    dec_name = dec.split("(")[0]  # strip args
                    edges.append(EdgeRecord(
                        source_id=node_id,
                        target_id=dec_name,
                        kind="decorates",
                        file_path=file_path,
                        line=actual.start_point[0] + 1,
                    ))

                # Recurse into nested definitions
                if body:
                    self._extract_symbols(body, source, node_id, file_path, fhash, now, nodes, edges)

            elif actual.type == "class_definition":
                name_node = actual.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(name_node, source)
                node_id = f"{parent_id}.{name}"

                body = actual.child_by_field_name("body")

                # Extract base classes
                superclasses = actual.child_by_field_name("superclasses")
                if superclasses:
                    for arg in superclasses.children:
                        if arg.type == "identifier":
                            base_name = _node_text(arg, source)
                            edges.append(EdgeRecord(
                                source_id=node_id,
                                target_id=base_name,
                                kind="inherits",
                                file_path=file_path,
                                line=actual.start_point[0] + 1,
                            ))

                node = NodeRecord(
                    id=node_id,
                    kind="class",
                    name=name,
                    file_path=file_path,
                    line_start=actual.start_point[0] + 1,
                    line_end=actual.end_point[0] + 1,
                    parent_id=parent_id,
                    docstring=_extract_docstring(body, source),
                    decorators=decorators,
                    file_hash=fhash,
                    indexed_at=now,
                )
                nodes.append(node)

                # Recurse into class body
                if body:
                    self._extract_symbols(body, source, node_id, file_path, fhash, now, nodes, edges)

    def _extract_imports(
        self,
        root_node: tree_sitter.Node,
        source: bytes,
        module_id: str,
        file_path: str,
        nodes: list[NodeRecord],
        edges: list[EdgeRecord],
        now: float,
        fhash: str,
    ) -> None:
        """Extract import statements and create edges."""
        for child in root_node.children:
            if child.type == "import_statement":
                # import foo, bar
                for sub in child.children:
                    if sub.type == "dotted_name":
                        target = _node_text(sub, source)
                        edges.append(EdgeRecord(
                            source_id=module_id,
                            target_id=target,
                            kind="imports",
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        ))

            elif child.type == "import_from_statement":
                # from foo import bar, baz
                module_name = None
                imported_names = []
                for sub in child.children:
                    if sub.type == "dotted_name" and module_name is None:
                        module_name = _node_text(sub, source)
                    elif sub.type == "dotted_name":
                        imported_names.append(_node_text(sub, source))
                    elif sub.type == "aliased_import":
                        name_node = sub.child_by_field_name("name")
                        if name_node:
                            imported_names.append(_node_text(name_node, source))

                if module_name:
                    for name in imported_names:
                        target = f"{module_name}.{name}"
                        edges.append(EdgeRecord(
                            source_id=module_id,
                            target_id=target,
                            kind="imports",
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        ))
                    if not imported_names:
                        # from foo import *  or just the module
                        edges.append(EdgeRecord(
                            source_id=module_id,
                            target_id=module_name,
                            kind="imports",
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                        ))

    def _extract_calls(
        self,
        root_node: tree_sitter.Node,
        source: bytes,
        module_id: str,
        file_path: str,
        edges: list[EdgeRecord],
    ) -> None:
        """Walk tree to find call expressions and create 'calls' edges."""
        # Find the enclosing function for call context
        self._walk_calls(root_node, source, module_id, file_path, edges)

    def _walk_calls(
        self,
        node: tree_sitter.Node,
        source: bytes,
        scope_id: str,
        file_path: str,
        edges: list[EdgeRecord],
    ) -> None:
        """Recursively walk nodes to find calls, tracking scope."""
        for child in node.children:
            actual = child
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        actual = sub
                        break

            if actual.type == "function_definition":
                name_node = actual.child_by_field_name("name")
                if name_node:
                    new_scope = f"{scope_id}.{_node_text(name_node, source)}"
                    body = actual.child_by_field_name("body")
                    if body:
                        self._walk_calls(body, source, new_scope, file_path, edges)
                continue

            if actual.type == "class_definition":
                name_node = actual.child_by_field_name("name")
                if name_node:
                    new_scope = f"{scope_id}.{_node_text(name_node, source)}"
                    body = actual.child_by_field_name("body")
                    if body:
                        self._walk_calls(body, source, new_scope, file_path, edges)
                continue

            if child.type == "call" or (child.type == "expression_statement" and child.child_count > 0):
                self._process_call_nodes(child, source, scope_id, file_path, edges)

            # Recurse for other node types (if/for/while blocks, etc.)
            self._walk_calls(child, source, scope_id, file_path, edges)

    def _process_call_nodes(
        self,
        node: tree_sitter.Node,
        source: bytes,
        scope_id: str,
        file_path: str,
        edges: list[EdgeRecord],
    ) -> None:
        """Find call nodes and create edges."""
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                if func_node.type == "identifier":
                    target = _node_text(func_node, source)
                elif func_node.type == "attribute":
                    target = _node_text(func_node, source)
                else:
                    target = _node_text(func_node, source)
                edges.append(EdgeRecord(
                    source_id=scope_id,
                    target_id=target,
                    kind="calls",
                    file_path=file_path,
                    line=node.start_point[0] + 1,
                ))

        for child in node.children:
            self._process_call_nodes(child, source, scope_id, file_path, edges)
