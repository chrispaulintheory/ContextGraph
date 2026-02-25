"""Shared fixtures for ContextGraph tests."""

import pytest

from context_graph.db import Database


@pytest.fixture
def db():
    """In-memory database for testing."""
    database = Database()
    yield database
    database.close()


@pytest.fixture
def project_root(tmp_path):
    """Temporary project root with sample Python files."""
    return tmp_path
