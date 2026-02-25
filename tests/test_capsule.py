"""Tests for context capsule generator."""

import shutil
from pathlib import Path

import pytest

from context_graph.capsule import generate_capsule
from context_graph.db import Database
from context_graph.indexer import Indexer
from context_graph.observations import ObservationStore


@pytest.fixture
def capsule_db(tmp_path):
    fixtures = Path(__file__).parent.parent / "fixtures"
    proj = tmp_path / "project"
    shutil.copytree(fixtures, proj)

    db = Database()
    indexer = Indexer(db, proj)
    indexer.index_project()
    return db, proj


def test_capsule_for_function(capsule_db):
    db, proj = capsule_db
    capsule = generate_capsule(db, "simple_module.greet")
    assert capsule is not None
    assert "# Context Capsule: `simple_module.greet`" in capsule
    assert "**Kind:** function" in capsule
    assert "Signature" in capsule
    assert "def greet" in capsule
    assert "Docstring" in capsule
    assert "Estimated tokens" in capsule


def test_capsule_for_class(capsule_db):
    db, proj = capsule_db
    capsule = generate_capsule(db, "class_with_methods.Child")
    assert capsule is not None
    assert "class" in capsule.lower()
    assert "inherits" in capsule.lower() or "Dependencies" in capsule


def test_capsule_for_method_with_parent(capsule_db):
    db, proj = capsule_db
    capsule = generate_capsule(db, "class_with_methods.Child.greet")
    assert capsule is not None
    assert "Parent Class" in capsule or "parent_id" in capsule.lower() or "class_with_methods.Child" in capsule


def test_capsule_nonexistent(capsule_db):
    db, _ = capsule_db
    assert generate_capsule(db, "nonexistent.node") is None


def test_capsule_with_observations(capsule_db):
    db, _ = capsule_db
    store = ObservationStore(db)
    store.add("This function is slow", node_id="simple_module.greet", tags=["perf"])
    capsule = generate_capsule(db, "simple_module.greet")
    assert "Observations" in capsule
    assert "This function is slow" in capsule


def test_capsule_with_dependencies(capsule_db):
    db, _ = capsule_db
    capsule = generate_capsule(db, "simple_module")
    assert capsule is not None
    assert "Dependencies" in capsule
