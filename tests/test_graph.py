"""Tests for graph traversal queries."""

import shutil
from pathlib import Path

import pytest

from context_graph.db import Database
from context_graph.graph import Graph
from context_graph.indexer import Indexer


@pytest.fixture
def graph_db(tmp_path):
    fixtures = Path(__file__).parent.parent / "fixtures"
    proj = tmp_path / "project"
    shutil.copytree(fixtures, proj)

    db = Database()
    indexer = Indexer(db, proj)
    indexer.index_project()
    graph = Graph(db)
    return db, graph


def test_dependencies(graph_db):
    db, graph = graph_db
    deps = graph.dependencies("simple_module")
    assert len(deps) > 0
    kinds = {e.kind for e in deps}
    assert "imports" in kinds


def test_dependents(graph_db):
    db, graph = graph_db
    # greet is called by farewell
    deps = graph.dependents("greet", kind="calls")
    assert any(e.source_id.endswith("farewell") for e in deps)


def test_callers(graph_db):
    db, graph = graph_db
    callers = graph.callers("greet")
    assert len(callers) > 0


def test_callees(graph_db):
    db, graph = graph_db
    callees = graph.callees("simple_module.farewell")
    targets = {e.target_id for e in callees}
    assert "greet" in targets


def test_imports(graph_db):
    db, graph = graph_db
    imports = graph.imports("simple_module")
    targets = {e.target_id for e in imports}
    assert "os" in targets


def test_superclasses(graph_db):
    db, graph = graph_db
    supers = graph.superclasses("class_with_methods.Child")
    assert any(e.target_id == "Base" for e in supers)


def test_subclasses(graph_db):
    db, graph = graph_db
    subs = graph.subclasses("Base", depth=1)
    assert any(e.source_id == "class_with_methods.Child" for e in subs)


def test_neighborhood(graph_db):
    db, graph = graph_db
    hood = graph.neighborhood("simple_module")
    assert "dependencies" in hood
    assert "dependents" in hood


def test_resolve_target(graph_db):
    db, graph = graph_db
    node = graph.resolve_target("simple_module.greet")
    assert node is not None
    assert node.name == "greet"
