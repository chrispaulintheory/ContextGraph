"""Dependency graph traversal queries."""

from __future__ import annotations

from .db import Database
from .models import EdgeRecord, NodeRecord


class Graph:
    """Query interface for the dependency graph."""

    def __init__(self, db: Database):
        self.db = db

    def dependents(self, node_id: str, kind: str | None = None, depth: int = 1) -> list[EdgeRecord]:
        """Get edges where node_id is the target (who depends on this node)."""
        if depth <= 0:
            return []
        edges = self.db.get_edges(target_id=node_id, kind=kind)
        if depth > 1:
            for edge in list(edges):
                edges.extend(self.dependents(edge.source_id, kind=kind, depth=depth - 1))
        return edges

    def dependencies(self, node_id: str, kind: str | None = None, depth: int = 1) -> list[EdgeRecord]:
        """Get edges where node_id is the source (what this node depends on)."""
        if depth <= 0:
            return []
        edges = self.db.get_edges(source_id=node_id, kind=kind)
        if depth > 1:
            for edge in list(edges):
                edges.extend(self.dependencies(edge.target_id, kind=kind, depth=depth - 1))
        return edges

    def callers(self, node_id: str, depth: int = 1) -> list[EdgeRecord]:
        """Who calls this node?"""
        return self.dependents(node_id, kind="calls", depth=depth)

    def callees(self, node_id: str, depth: int = 1) -> list[EdgeRecord]:
        """What does this node call?"""
        return self.dependencies(node_id, kind="calls", depth=depth)

    def importers(self, node_id: str) -> list[EdgeRecord]:
        """Who imports this node?"""
        return self.dependents(node_id, kind="imports")

    def imports(self, node_id: str) -> list[EdgeRecord]:
        """What does this node import?"""
        return self.dependencies(node_id, kind="imports")

    def superclasses(self, node_id: str, depth: int = 1) -> list[EdgeRecord]:
        """Inheritance chain upward."""
        return self.dependencies(node_id, kind="inherits", depth=depth)

    def subclasses(self, node_id: str, depth: int = 1) -> list[EdgeRecord]:
        """Inheritance chain downward."""
        return self.dependents(node_id, kind="inherits", depth=depth)

    def neighborhood(self, node_id: str, depth: int = 1) -> dict:
        """Get all edges within depth of a node, grouped by direction."""
        return {
            "dependencies": self.dependencies(node_id, depth=depth),
            "dependents": self.dependents(node_id, depth=depth),
        }

    def resolve_target(self, target_name: str) -> NodeRecord | None:
        """Try to resolve an unqualified target name to a node."""
        # Try exact match first
        node = self.db.get_node(target_name)
        if node:
            return node
        # Try matching by short name
        candidates = self.db.list_nodes(name=target_name)
        if len(candidates) == 1:
            return candidates[0]
        return None
