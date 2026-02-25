"""Tests for the file watcher."""

import time
from pathlib import Path

import pytest

from context_graph.db import Database
from context_graph.watcher import ProjectWatcher


@pytest.fixture
def watcher_setup(tmp_path):
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "initial.py").write_text('def hello():\n    return "hi"\n')

    db = Database()
    watcher = ProjectWatcher(db, proj)
    yield db, watcher, proj
    watcher.stop()


def test_initial_index(watcher_setup):
    db, watcher, proj = watcher_setup
    count = watcher.index_now()
    assert count == 1
    assert db.stats()["nodes"] > 0


def test_watcher_start_stop(watcher_setup):
    db, watcher, proj = watcher_setup
    watcher.start()
    assert watcher.is_running
    watcher.stop()
    assert not watcher.is_running


def test_watcher_detects_new_file(watcher_setup):
    db, watcher, proj = watcher_setup
    watcher.index_now()
    watcher.start()

    # Create a new file
    (proj / "new_module.py").write_text('def new_func():\n    pass\n')
    # Wait for debounce + processing
    time.sleep(1.5)

    nodes = db.list_nodes(name="new_func")
    assert len(nodes) >= 1


def test_watcher_detects_modification(watcher_setup):
    db, watcher, proj = watcher_setup
    watcher.index_now()
    watcher.start()

    # Modify initial file
    (proj / "initial.py").write_text('def hello():\n    return "hi"\n\ndef added():\n    pass\n')
    time.sleep(1.5)

    nodes = db.list_nodes(name="added")
    assert len(nodes) >= 1


def test_watcher_detects_deletion(watcher_setup):
    db, watcher, proj = watcher_setup
    watcher.index_now()
    initial_nodes = db.stats()["nodes"]
    assert initial_nodes > 0

    watcher.start()
    (proj / "initial.py").unlink()
    time.sleep(1.5)

    assert db.stats()["nodes"] == 0
