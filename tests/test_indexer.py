"""Tests for the tree-sitter indexer."""

import shutil
from pathlib import Path

import pytest

from context_graph.db import Database
from context_graph.indexer import Indexer


@pytest.fixture
def indexed_simple(tmp_path):
    """Index the simple_module fixture."""
    fixtures = Path(__file__).parent.parent / "fixtures"
    # Copy fixtures to tmp_path to use as project root
    proj = tmp_path / "project"
    shutil.copytree(fixtures, proj)

    db = Database()
    indexer = Indexer(db, proj)
    indexer.index_file(proj / "simple_module.py")
    return db, indexer, proj


@pytest.fixture
def indexed_class(tmp_path):
    """Index the class_with_methods fixture."""
    fixtures = Path(__file__).parent.parent / "fixtures"
    proj = tmp_path / "project"
    shutil.copytree(fixtures, proj)

    db = Database()
    indexer = Indexer(db, proj)
    indexer.index_file(proj / "class_with_methods.py")
    return db, indexer, proj


class TestSimpleModule:
    def test_module_node_created(self, indexed_simple):
        db, _, _ = indexed_simple
        nodes = db.list_nodes(kind="module")
        assert any(n.name == "simple_module" for n in nodes)

    def test_functions_extracted(self, indexed_simple):
        db, _, _ = indexed_simple
        funcs = db.list_nodes(kind="function")
        names = {n.name for n in funcs}
        assert "greet" in names
        assert "farewell" in names

    def test_function_signature(self, indexed_simple):
        db, _, _ = indexed_simple
        node = db.get_node("simple_module.greet")
        assert node is not None
        assert "name: str" in node.signature
        assert "-> str" in node.signature

    def test_function_docstring(self, indexed_simple):
        db, _, _ = indexed_simple
        node = db.get_node("simple_module.greet")
        assert node.docstring == "Return a greeting string."

    def test_import_edges(self, indexed_simple):
        db, _, _ = indexed_simple
        edges = db.get_edges(source_id="simple_module", kind="imports")
        targets = {e.target_id for e in edges}
        assert "os" in targets
        assert "pathlib.Path" in targets

    def test_call_edges(self, indexed_simple):
        db, _, _ = indexed_simple
        edges = db.get_edges(source_id="simple_module.farewell", kind="calls")
        targets = {e.target_id for e in edges}
        assert "greet" in targets

    def test_incremental_skip(self, indexed_simple):
        db, indexer, proj = indexed_simple
        # Second index should be a no-op (same hash)
        nodes = indexer.index_file(proj / "simple_module.py")
        assert len(nodes) > 0  # returns cached nodes

    def test_force_reindex(self, indexed_simple):
        db, indexer, proj = indexed_simple
        nodes = indexer.index_file(proj / "simple_module.py", force=True)
        assert len(nodes) > 0


class TestClassModule:
    def test_class_extracted(self, indexed_class):
        db, _, _ = indexed_class
        classes = db.list_nodes(kind="class")
        names = {n.name for n in classes}
        assert "Base" in names
        assert "Child" in names

    def test_methods_extracted(self, indexed_class):
        db, _, _ = indexed_class
        methods = db.list_nodes(kind="method")
        names = {n.name for n in methods}
        assert "describe" in names
        assert "greet" in names

    def test_method_parent(self, indexed_class):
        db, _, _ = indexed_class
        # Child.greet should have parent Child
        node = db.get_node("class_with_methods.Child.greet")
        assert node is not None
        assert node.parent_id == "class_with_methods.Child"

    def test_inherits_edge(self, indexed_class):
        db, _, _ = indexed_class
        edges = db.get_edges(source_id="class_with_methods.Child", kind="inherits")
        targets = {e.target_id for e in edges}
        assert "Base" in targets

    def test_decorator_on_base(self, indexed_class):
        db, _, _ = indexed_class
        node = db.get_node("class_with_methods.Base")
        assert "dataclass" in node.decorators


class TestProjectIndex:
    def test_index_project(self, tmp_path):
        fixtures = Path(__file__).parent.parent / "fixtures"
        proj = tmp_path / "project"
        shutil.copytree(fixtures, proj)

        db = Database()
        indexer = Indexer(db, proj)
        count = indexer.index_project()
        assert count >= 5  # at least 5 .py files in fixtures

        stats = db.stats()
        assert stats["nodes"] > 10
        assert stats["edges"] > 0

    def test_remove_file(self, tmp_path):
        fixtures = Path(__file__).parent.parent / "fixtures"
        proj = tmp_path / "project"
        shutil.copytree(fixtures, proj)

        db = Database()
        indexer = Indexer(db, proj)
        indexer.index_file(proj / "simple_module.py")
        assert len(db.list_nodes(file_path=str((proj / "simple_module.py").resolve()))) > 0

        indexer.remove_file(proj / "simple_module.py")
        assert len(db.list_nodes(file_path=str((proj / "simple_module.py").resolve()))) == 0
