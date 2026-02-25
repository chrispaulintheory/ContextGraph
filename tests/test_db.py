"""Tests for db.py and models.py."""

import time

from context_graph.db import Database
from context_graph.models import EdgeRecord, IndexedFile, NodeRecord, Observation


def _make_node(id="mod.foo", kind="function", name="foo", **kw) -> NodeRecord:
    defaults = dict(
        file_path="mod.py", line_start=1, line_end=5,
        file_hash="abc123", indexed_at=time.time(),
    )
    defaults.update(kw)
    return NodeRecord(id=id, kind=kind, name=name, **defaults)


def test_upsert_and_get_node(db):
    node = _make_node()
    db.upsert_node(node)
    got = db.get_node("mod.foo")
    assert got is not None
    assert got.id == "mod.foo"
    assert got.kind == "function"


def test_upsert_node_updates(db):
    db.upsert_node(_make_node(signature="def foo():"))
    db.upsert_node(_make_node(signature="def foo(x):"))
    got = db.get_node("mod.foo")
    assert got.signature == "def foo(x):"


def test_list_nodes_filters(db):
    db.upsert_node(_make_node(id="a.f", kind="function", name="f", file_path="a.py"))
    db.upsert_node(_make_node(id="b.C", kind="class", name="C", file_path="b.py"))
    assert len(db.list_nodes(kind="function")) == 1
    assert len(db.list_nodes(file_path="b.py")) == 1
    assert len(db.list_nodes()) == 2


def test_delete_nodes_for_file(db):
    db.upsert_node(_make_node(id="a.f", file_path="a.py"))
    db.upsert_node(_make_node(id="b.g", file_path="b.py"))
    deleted = db.delete_nodes_for_file("a.py")
    assert deleted == 1
    assert len(db.list_nodes()) == 1


def test_upsert_and_get_edges(db):
    db.upsert_node(_make_node(id="a.f", file_path="a.py"))
    db.upsert_node(_make_node(id="b.g", file_path="b.py"))
    edge = EdgeRecord(source_id="a.f", target_id="b.g", kind="calls", file_path="a.py", line=10)
    db.upsert_edge(edge)
    edges = db.get_edges(source_id="a.f")
    assert len(edges) == 1
    assert edges[0].target_id == "b.g"


def test_edge_unique_constraint(db):
    db.upsert_node(_make_node(id="a.f", file_path="a.py"))
    db.upsert_node(_make_node(id="b.g", file_path="b.py"))
    edge = EdgeRecord(source_id="a.f", target_id="b.g", kind="calls", file_path="a.py")
    db.upsert_edge(edge)
    db.upsert_edge(edge)  # should not raise
    assert len(db.get_edges()) == 1


def test_observations_crud(db):
    obs = Observation(content="foo is slow", created_at=time.time(), tags=["perf"])
    obs_id = db.add_observation(obs)
    assert obs_id is not None

    got = db.get_observation(obs_id)
    assert got.content == "foo is slow"
    assert got.tags == ["perf"]

    all_obs = db.list_observations()
    assert len(all_obs) == 1

    assert db.delete_observation(obs_id)
    assert db.get_observation(obs_id) is None


def test_observations_filter_by_tag(db):
    db.add_observation(Observation(content="a", created_at=time.time(), tags=["bug"]))
    db.add_observation(Observation(content="b", created_at=time.time(), tags=["perf"]))
    assert len(db.list_observations(tag="bug")) == 1


def test_observations_linked_to_node(db):
    db.upsert_node(_make_node(id="mod.foo"))
    db.add_observation(Observation(
        content="linked", node_id="mod.foo", created_at=time.time()
    ))
    assert len(db.list_observations(node_id="mod.foo")) == 1


def test_indexed_files(db):
    f = IndexedFile(file_path="a.py", file_hash="abc", indexed_at=time.time(), node_count=3)
    db.upsert_indexed_file(f)
    got = db.get_indexed_file("a.py")
    assert got.node_count == 3
    assert len(db.list_indexed_files()) == 1
    db.delete_indexed_file("a.py")
    assert db.get_indexed_file("a.py") is None


def test_list_observations_since(db):
    now = time.time()
    old = Observation(content="old", created_at=now - 7200, source="user")
    new = Observation(content="new", created_at=now - 100, source="claude")
    db.add_observation(old)
    db.add_observation(new)

    # All since 1 hour ago
    results = db.list_observations_since(now - 3600)
    assert len(results) == 1
    assert results[0].content == "new"

    # Filter by source
    results = db.list_observations_since(now - 86400, source="claude")
    assert len(results) == 1
    assert results[0].source == "claude"

    # With limit
    results = db.list_observations_since(now - 86400, limit=1)
    assert len(results) == 1


def test_list_observations_since_ordering(db):
    now = time.time()
    db.add_observation(Observation(content="first", created_at=now - 200, source="user"))
    db.add_observation(Observation(content="second", created_at=now - 100, source="user"))
    results = db.list_observations_since(now - 3600)
    assert results[0].content == "second"  # newest first


def test_list_recently_indexed_files(db):
    now = time.time()
    old_file = IndexedFile(file_path="old.py", file_hash="aaa", indexed_at=now - 7200, node_count=1)
    new_file = IndexedFile(file_path="new.py", file_hash="bbb", indexed_at=now - 100, node_count=2)
    db.upsert_indexed_file(old_file)
    db.upsert_indexed_file(new_file)

    # Since 1 hour ago
    results = db.list_recently_indexed_files(now - 3600)
    assert len(results) == 1
    assert results[0].file_path == "new.py"

    # With limit
    results = db.list_recently_indexed_files(now - 86400, limit=1)
    assert len(results) == 1

    # Ordering: most recent first
    db.upsert_indexed_file(IndexedFile(file_path="newer.py", file_hash="ccc", indexed_at=now - 50, node_count=3))
    results = db.list_recently_indexed_files(now - 86400)
    assert results[0].file_path == "newer.py"


def test_stats(db):
    s = db.stats()
    assert s == {"nodes": 0, "edges": 0, "observations": 0, "indexed_files": 0}
    db.upsert_node(_make_node())
    s = db.stats()
    assert s["nodes"] == 1
