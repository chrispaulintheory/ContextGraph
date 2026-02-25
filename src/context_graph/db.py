"""SQLite connection, schema creation, and CRUD operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import EdgeRecord, IndexedFile, NodeRecord, Observation

SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL,
    parent_id   TEXT,
    signature   TEXT,
    docstring   TEXT,
    decorators  TEXT,
    is_external INTEGER DEFAULT 0,
    file_hash   TEXT NOT NULL,
    indexed_at  REAL NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    line        INTEGER,
    metadata    TEXT,
    resolved    INTEGER DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    node_id     TEXT,
    tags        TEXT,
    created_at  REAL NOT NULL,
    source      TEXT DEFAULT 'user',
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS indexed_files (
    file_path   TEXT PRIMARY KEY,
    file_hash   TEXT NOT NULL,
    indexed_at  REAL NOT NULL,
    node_count  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_nodes_file     ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_name     ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_parent   ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_kind     ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_external ON nodes(is_external);
CREATE INDEX IF NOT EXISTS idx_edges_source   ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target   ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind     ON edges(kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique ON edges(source_id, target_id, kind);
CREATE INDEX IF NOT EXISTS idx_obs_node       ON observations(node_id);
CREATE INDEX IF NOT EXISTS idx_obs_created    ON observations(created_at);
CREATE INDEX IF NOT EXISTS idx_obs_source     ON observations(source);
"""


class Database:
    """SQLite database for a single project."""

    def __init__(self, db_path: str | Path | None = None):
        """Open (or create) the database. Pass None or ':memory:' for in-memory."""
        if db_path is None:
            db_path = ":memory:"
        else:
            db_path = str(db_path)
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.conn.close()

    # ── Nodes ──────────────────────────────────────────────

    def upsert_node(self, node: NodeRecord) -> None:
        self.conn.execute(
            """INSERT INTO nodes (id, kind, name, file_path, line_start, line_end,
               parent_id, signature, docstring, decorators, is_external, file_hash, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind, name=excluded.name, file_path=excluded.file_path,
                 line_start=excluded.line_start, line_end=excluded.line_end,
                 parent_id=excluded.parent_id, signature=excluded.signature,
                 docstring=excluded.docstring, decorators=excluded.decorators,
                 is_external=excluded.is_external, file_hash=excluded.file_hash,
                 indexed_at=excluded.indexed_at""",
            (
                node.id, node.kind, node.name, node.file_path,
                node.line_start, node.line_end, node.parent_id,
                node.signature, node.docstring, node.decorators_json,
                int(node.is_external), node.file_hash, node.indexed_at,
            ),
        )
        self.conn.commit()

    def upsert_nodes(self, nodes: list[NodeRecord]) -> None:
        self.conn.executemany(
            """INSERT INTO nodes (id, kind, name, file_path, line_start, line_end,
               parent_id, signature, docstring, decorators, is_external, file_hash, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind, name=excluded.name, file_path=excluded.file_path,
                 line_start=excluded.line_start, line_end=excluded.line_end,
                 parent_id=excluded.parent_id, signature=excluded.signature,
                 docstring=excluded.docstring, decorators=excluded.decorators,
                 is_external=excluded.is_external, file_hash=excluded.file_hash,
                 indexed_at=excluded.indexed_at""",
            [
                (
                    n.id, n.kind, n.name, n.file_path,
                    n.line_start, n.line_end, n.parent_id,
                    n.signature, n.docstring, n.decorators_json,
                    int(n.is_external), n.file_hash, n.indexed_at,
                )
                for n in nodes
            ],
        )
        self.conn.commit()

    def get_node(self, node_id: str) -> NodeRecord | None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return NodeRecord.from_row(row) if row else None

    def list_nodes(
        self,
        file_path: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        external: bool | None = None,
    ) -> list[NodeRecord]:
        clauses, params = [], []
        if file_path is not None:
            clauses.append("file_path = ?")
            params.append(file_path)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if name is not None:
            clauses.append("name = ?")
            params.append(name)
        if external is not None:
            clauses.append("is_external = ?")
            params.append(int(external))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM nodes{where}", params).fetchall()
        return [NodeRecord.from_row(r) for r in rows]

    def delete_nodes_for_file(self, file_path: str) -> int:
        cur = self.conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
        self.conn.commit()
        return cur.rowcount

    # ── Edges ──────────────────────────────────────────────

    def upsert_edge(self, edge: EdgeRecord) -> None:
        self.conn.execute(
            """INSERT INTO edges (source_id, target_id, kind, file_path, line, metadata, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, kind) DO UPDATE SET
                 file_path=excluded.file_path, line=excluded.line,
                 metadata=excluded.metadata, resolved=excluded.resolved""",
            (
                edge.source_id, edge.target_id, edge.kind,
                edge.file_path, edge.line, edge.metadata_json, int(edge.resolved),
            ),
        )
        self.conn.commit()

    def upsert_edges(self, edges: list[EdgeRecord]) -> None:
        self.conn.executemany(
            """INSERT INTO edges (source_id, target_id, kind, file_path, line, metadata, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, kind) DO UPDATE SET
                 file_path=excluded.file_path, line=excluded.line,
                 metadata=excluded.metadata, resolved=excluded.resolved""",
            [
                (
                    e.source_id, e.target_id, e.kind,
                    e.file_path, e.line, e.metadata_json, int(e.resolved),
                )
                for e in edges
            ],
        )
        self.conn.commit()

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: str | None = None,
    ) -> list[EdgeRecord]:
        clauses, params = [], []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM edges{where}", params).fetchall()
        return [EdgeRecord.from_row(r) for r in rows]

    def delete_edges_for_file(self, file_path: str) -> int:
        cur = self.conn.execute("DELETE FROM edges WHERE file_path = ?", (file_path,))
        self.conn.commit()
        return cur.rowcount

    # ── Observations ───────────────────────────────────────

    def add_observation(self, obs: Observation) -> int:
        cur = self.conn.execute(
            """INSERT INTO observations (content, node_id, tags, created_at, source)
               VALUES (?, ?, ?, ?, ?)""",
            (obs.content, obs.node_id, obs.tags_json, obs.created_at, obs.source),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_observation(self, obs_id: int) -> Observation | None:
        row = self.conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
        return Observation.from_row(row) if row else None

    def list_observations(
        self,
        node_id: str | None = None,
        tag: str | None = None,
    ) -> list[Observation]:
        clauses, params = [], []
        if node_id is not None:
            clauses.append("node_id = ?")
            params.append(node_id)
        if tag is not None:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM observations{where} ORDER BY created_at DESC", params
        ).fetchall()
        return [Observation.from_row(r) for r in rows]

    def list_observations_since(
        self,
        since: float,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[Observation]:
        """Return observations created after *since* (epoch), newest first."""
        clauses = ["created_at > ?"]
        params: list = [since]
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT * FROM observations{where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [Observation.from_row(r) for r in rows]

    def delete_observation(self, obs_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ── Indexed Files ──────────────────────────────────────

    def upsert_indexed_file(self, f: IndexedFile) -> None:
        self.conn.execute(
            """INSERT INTO indexed_files (file_path, file_hash, indexed_at, node_count)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(file_path) DO UPDATE SET
                 file_hash=excluded.file_hash, indexed_at=excluded.indexed_at,
                 node_count=excluded.node_count""",
            (f.file_path, f.file_hash, f.indexed_at, f.node_count),
        )
        self.conn.commit()

    def get_indexed_file(self, file_path: str) -> IndexedFile | None:
        row = self.conn.execute(
            "SELECT * FROM indexed_files WHERE file_path = ?", (file_path,)
        ).fetchone()
        return IndexedFile.from_row(row) if row else None

    def delete_indexed_file(self, file_path: str) -> bool:
        cur = self.conn.execute("DELETE FROM indexed_files WHERE file_path = ?", (file_path,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_recently_indexed_files(
        self,
        since: float,
        limit: int | None = None,
    ) -> list[IndexedFile]:
        """Return files indexed after *since*, most recent first."""
        sql = "SELECT * FROM indexed_files WHERE indexed_at > ? ORDER BY indexed_at DESC"
        params: list = [since]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [IndexedFile.from_row(r) for r in rows]

    def list_indexed_files(self) -> list[IndexedFile]:
        rows = self.conn.execute("SELECT * FROM indexed_files ORDER BY file_path").fetchall()
        return [IndexedFile.from_row(r) for r in rows]

    # ── Stats ──────────────────────────────────────────────

    def stats(self) -> dict:
        node_count = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        obs_count = self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        file_count = self.conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0]
        return {
            "nodes": node_count,
            "edges": edge_count,
            "observations": obs_count,
            "indexed_files": file_count,
        }
