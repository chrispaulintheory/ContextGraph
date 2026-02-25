"""Dataclasses for ContextGraph records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class NodeRecord:
    id: str  # qualified name: "pkg.mod.Class.method"
    kind: str  # 'module' | 'class' | 'function' | 'method'
    name: str  # short name
    file_path: str
    line_start: int
    line_end: int
    file_hash: str
    indexed_at: float
    parent_id: str | None = None
    signature: str | None = None
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    is_external: bool = False

    @property
    def decorators_json(self) -> str:
        return json.dumps(self.decorators)

    @classmethod
    def from_row(cls, row: dict) -> NodeRecord:
        return cls(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            file_path=row["file_path"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            file_hash=row["file_hash"],
            indexed_at=row["indexed_at"],
            parent_id=row["parent_id"],
            signature=row["signature"],
            docstring=row["docstring"],
            decorators=json.loads(row["decorators"]) if row["decorators"] else [],
            is_external=bool(row["is_external"]),
        )


@dataclass
class EdgeRecord:
    source_id: str
    target_id: str
    kind: str  # 'calls' | 'imports' | 'inherits' | 'decorates'
    file_path: str
    id: int | None = None
    line: int | None = None
    metadata: dict | None = None
    resolved: bool = False

    @property
    def metadata_json(self) -> str | None:
        return json.dumps(self.metadata) if self.metadata else None

    @classmethod
    def from_row(cls, row: dict) -> EdgeRecord:
        return cls(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            kind=row["kind"],
            file_path=row["file_path"],
            line=row["line"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            resolved=bool(row["resolved"]),
        )


@dataclass
class Observation:
    content: str
    created_at: float
    id: int | None = None
    node_id: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "user"

    @property
    def tags_json(self) -> str:
        return json.dumps(self.tags)

    @classmethod
    def from_row(cls, row: dict) -> Observation:
        return cls(
            id=row["id"],
            content=row["content"],
            created_at=row["created_at"],
            node_id=row["node_id"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            source=row["source"],
        )


@dataclass
class IndexedFile:
    file_path: str
    file_hash: str
    indexed_at: float
    node_count: int = 0

    @classmethod
    def from_row(cls, row: dict) -> IndexedFile:
        return cls(
            file_path=row["file_path"],
            file_hash=row["file_hash"],
            indexed_at=row["indexed_at"],
            node_count=row["node_count"],
        )
