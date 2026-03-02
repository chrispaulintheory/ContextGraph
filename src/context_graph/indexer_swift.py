"""tree-sitter based Swift indexer: extracts symbols and imports."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import tree_sitter
import tree_sitter_swift as tsswift

from .db import Database
from .models import EdgeRecord, IndexedFile, NodeRecord

_LANGUAGE = tree_sitter.Language(tsswift.language())
_PARSER = tree_sitter.Parser(_LANGUAGE)

# Directories to skip when crawling a Swift project
SWIFT_IGNORE_DIRS = {
    "__pycache__", ".venv", "node_modules",
    "Pods", "Carthage", ".build", "DerivedData",
    "xcuserdata",
}

# class_declaration keyword → node kind
_KEYWORD_TO_KIND = {
    "class": "class",
    "struct": "struct",
    "enum": "enum",
    "actor": "actor",
    "extension": "extension",
}

# Node types that contain method/property declarations
_BODY_TYPES = {"class_body", "enum_class_body", "protocol_body"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _module_id_from_path(file_path: str, project_root: str) -> str:
    rel = Path(file_path).relative_to(project_root)
    parts = list(rel.parts)
    parts[-1] = parts[-1].removesuffix(".swift")
    return ".".join(parts)


def _get_class_keyword(node: tree_sitter.Node, source: bytes) -> str | None:
    for child in node.children:
        text = _node_text(child, source)
        if text in _KEYWORD_TO_KIND:
            return text
    return None


def _get_type_name(node: tree_sitter.Node, source: bytes) -> str | None:
    """Return the declared type name, handling both class/struct and extension forms."""
    for child in node.children:
        if child.type == "type_identifier":
            return _node_text(child, source)
        if child.type == "user_type":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return _node_text(sub, source)
    return None


def _build_func_signature(node: tree_sitter.Node, source: bytes) -> str:
    parts = []
    # modifiers (override, private, static, …)
    for child in node.children:
        if child.type == "modifiers":
            parts.append(_node_text(child, source))
    parts.append("func")
    # name
    for child in node.children:
        if child.type == "simple_identifier":
            parts.append(_node_text(child, source))
            break
    # parameter list
    in_params = False
    param_parts = []
    for child in node.children:
        if child.type == "(":
            in_params = True
        elif child.type == ")" and in_params:
            in_params = False
            parts.append("(" + ", ".join(param_parts) + ")")
            break
        elif in_params and child.type == "parameter":
            param_parts.append(_node_text(child, source))
    # return type
    found_arrow = False
    for child in node.children:
        if child.type == "->":
            found_arrow = True
        elif found_arrow:
            parts.append("->")
            parts.append(_node_text(child, source))
            break
    return " ".join(parts)


def _build_type_signature(node: tree_sitter.Node, source: bytes, keyword: str, name: str) -> str:
    parts = [keyword, name]
    colon_seen = False
    for child in node.children:
        if child.type == ":":
            colon_seen = True
            parts.append(":")
        elif colon_seen and child.type == "inheritance_specifier":
            parts.append(_node_text(child, source))
    return " ".join(parts)


class SwiftIndexer:
    """Indexes Swift files using tree-sitter."""

    def __init__(self, db: Database, project_root: str | Path):
        self.db = db
        self.project_root = str(Path(project_root).resolve())

    def index_file(self, file_path: str | Path, force: bool = False) -> list[NodeRecord]:
        """Index a single Swift file. Returns list of extracted nodes."""
        file_path = Path(file_path).resolve()
        fp_str = str(file_path)

        fhash = file_hash(file_path)
        if not force:
            existing = self.db.get_indexed_file(fp_str)
            if existing and existing.file_hash == fhash:
                return self.db.list_nodes(file_path=fp_str)

        source = file_path.read_bytes()
        tree = _PARSER.parse(source)
        now = time.time()

        module_id = _module_id_from_path(fp_str, self.project_root)

        self.db.delete_nodes_for_file(fp_str)
        self.db.delete_edges_for_file(fp_str)

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

        self._extract_symbols(root, source, module_id, fp_str, fhash, now, nodes, edges)
        self._extract_imports(root, source, module_id, fp_str, edges)

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
        """Index all .swift files under project root. Returns file count."""
        count = 0
        root = Path(self.project_root)
        for swift_file in sorted(root.rglob("*.swift")):
            parts = swift_file.relative_to(root).parts
            if any(p.startswith(".") or p in SWIFT_IGNORE_DIRS for p in parts):
                continue
            try:
                self.index_file(swift_file, force=force)
                count += 1
            except Exception:
                pass
        return count

    def remove_file(self, file_path: str | Path) -> None:
        fp_str = str(Path(file_path).resolve())
        self.db.delete_nodes_for_file(fp_str)
        self.db.delete_edges_for_file(fp_str)
        self.db.delete_indexed_file(fp_str)

    # ── Symbol extraction ──────────────────────────────────

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
        is_body = parent_node.type in _BODY_TYPES
        for child in parent_node.children:
            if child.type in ("class_declaration", "protocol_declaration"):
                self._handle_type_decl(child, source, parent_id, file_path, fhash, now, nodes, edges)
            elif child.type in ("function_declaration", "protocol_function_declaration"):
                self._handle_func_decl(child, source, parent_id, file_path, fhash, now, nodes, edges, is_method=is_body)
            elif child.type == "init_declaration":
                self._handle_init_decl(child, source, parent_id, file_path, fhash, now, nodes, edges)

    def _handle_type_decl(
        self,
        node: tree_sitter.Node,
        source: bytes,
        parent_id: str,
        file_path: str,
        fhash: str,
        now: float,
        nodes: list[NodeRecord],
        edges: list[EdgeRecord],
    ) -> None:
        keyword = _get_class_keyword(node, source)
        if keyword is None:
            return
        kind = _KEYWORD_TO_KIND[keyword]
        name = _get_type_name(node, source)
        if not name:
            return

        node_id = f"{parent_id}.{name}"
        sig = _build_type_signature(node, source, keyword, name)

        # Inheritance / conformance edges
        for child in node.children:
            if child.type == "inheritance_specifier":
                for sub in child.children:
                    if sub.type == "user_type":
                        for subsub in sub.children:
                            if subsub.type == "type_identifier":
                                edges.append(EdgeRecord(
                                    source_id=node_id,
                                    target_id=_node_text(subsub, source),
                                    kind="inherits",
                                    file_path=file_path,
                                    line=node.start_point[0] + 1,
                                ))

        nodes.append(NodeRecord(
            id=node_id,
            kind=kind,
            name=name,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_id=parent_id,
            signature=sig,
            file_hash=fhash,
            indexed_at=now,
        ))

        # Recurse into body
        for child in node.children:
            if child.type in _BODY_TYPES:
                self._extract_symbols(child, source, node_id, file_path, fhash, now, nodes, edges)

    def _handle_func_decl(
        self,
        node: tree_sitter.Node,
        source: bytes,
        parent_id: str,
        file_path: str,
        fhash: str,
        now: float,
        nodes: list[NodeRecord],
        edges: list[EdgeRecord],
        is_method: bool = False,
    ) -> None:
        name = None
        for child in node.children:
            if child.type == "simple_identifier":
                name = _node_text(child, source)
                break
        if not name:
            return

        nodes.append(NodeRecord(
            id=f"{parent_id}.{name}",
            kind="method" if is_method else "function",
            name=name,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_id=parent_id,
            signature=_build_func_signature(node, source),
            file_hash=fhash,
            indexed_at=now,
        ))

    def _handle_init_decl(
        self,
        node: tree_sitter.Node,
        source: bytes,
        parent_id: str,
        file_path: str,
        fhash: str,
        now: float,
        nodes: list[NodeRecord],
        edges: list[EdgeRecord],
    ) -> None:
        param_parts = []
        for child in node.children:
            if child.type == "parameter":
                param_parts.append(_node_text(child, source))
        sig = "init(" + ", ".join(param_parts) + ")"

        nodes.append(NodeRecord(
            id=f"{parent_id}.init",
            kind="method",
            name="init",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            parent_id=parent_id,
            signature=sig,
            file_hash=fhash,
            indexed_at=now,
        ))

    def _extract_imports(
        self,
        root_node: tree_sitter.Node,
        source: bytes,
        module_id: str,
        file_path: str,
        edges: list[EdgeRecord],
    ) -> None:
        for child in root_node.children:
            if child.type == "import_declaration":
                for sub in child.children:
                    if sub.type == "identifier":
                        for subsub in sub.children:
                            if subsub.type == "simple_identifier":
                                edges.append(EdgeRecord(
                                    source_id=module_id,
                                    target_id=_node_text(subsub, source),
                                    kind="imports",
                                    file_path=file_path,
                                    line=child.start_point[0] + 1,
                                ))
