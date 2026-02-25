"""Tests for observations CRUD."""

import time

import pytest

from context_graph.db import Database
from context_graph.models import NodeRecord
from context_graph.observations import ObservationStore


@pytest.fixture
def store(db):
    return ObservationStore(db)


def test_add_and_get(store):
    obs = store.add("test observation", tags=["test"])
    assert obs.id is not None
    got = store.get(obs.id)
    assert got.content == "test observation"
    assert got.tags == ["test"]


def test_list_all(store):
    store.add("one")
    store.add("two")
    all_obs = store.list()
    assert len(all_obs) == 2


def test_filter_by_tag(store):
    store.add("bug report", tags=["bug"])
    store.add("performance note", tags=["perf"])
    bugs = store.list(tag="bug")
    assert len(bugs) == 1
    assert bugs[0].content == "bug report"


def test_filter_by_node(store, db):
    db.upsert_node(NodeRecord(
        id="mod.foo", kind="function", name="foo",
        file_path="mod.py", line_start=1, line_end=5,
        file_hash="abc", indexed_at=time.time(),
    ))
    store.add("linked obs", node_id="mod.foo")
    store.add("unlinked obs")
    linked = store.list(node_id="mod.foo")
    assert len(linked) == 1


def test_delete(store):
    obs = store.add("to delete")
    assert store.delete(obs.id)
    assert store.get(obs.id) is None


def test_delete_nonexistent(store):
    assert not store.delete(9999)


def test_list_since(store):
    store.add("old note", source="user")
    import time
    # The observation was just created, so list_since with a recent cutoff should find it
    since = time.time() - 60
    results = store.list_since(since)
    assert len(results) >= 1
    assert any(o.content == "old note" for o in results)


def test_list_since_with_source_filter(store):
    store.add("user note", source="user")
    store.add("git note", source="git")
    import time
    since = time.time() - 60
    results = store.list_since(since, source="git")
    assert len(results) == 1
    assert results[0].content == "git note"


def test_deduplicate_hook_observations(store):
    obs1 = store.add("Edited: auth.py", source="hook")
    obs2 = store.add("Edited: auth.py", source="hook")
    obs3 = store.add("Edited: models.py", source="hook")

    all_obs = [obs1, obs2, obs3]
    deduped = ObservationStore.deduplicate_hook_observations(all_obs)
    contents = [o.content for o in deduped]
    assert len(deduped) == 2
    assert "Edited: auth.py" in contents
    assert "Edited: models.py" in contents


def test_deduplicate_keeps_most_recent():
    """Dedup keeps the observation with the latest timestamp."""
    from context_graph.models import Observation
    import time
    now = time.time()
    obs_old = Observation(id=1, content="Edited: a.py", created_at=now - 100, source="hook")
    obs_new = Observation(id=2, content="Edited: a.py", created_at=now, source="hook")
    deduped = ObservationStore.deduplicate_hook_observations([obs_old, obs_new])
    assert len(deduped) == 1
    assert deduped[0].id == 2
