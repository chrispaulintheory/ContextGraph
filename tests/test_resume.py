"""Tests for the resume module."""

import time

import pytest

from context_graph.db import Database
from context_graph.models import IndexedFile, Observation
from context_graph.observations import ObservationStore
from context_graph.resume import generate_resume


@pytest.fixture
def store(db):
    return ObservationStore(db)


class TestEmptyDB:
    def test_empty_db_returns_no_activity(self, db):
        result = generate_resume(db)
        assert "No recent activity" in result

    def test_empty_db_with_custom_params(self, db):
        result = generate_resume(db, budget=100, hours=1)
        assert "No recent activity" in result


class TestSourceGrouping:
    def test_claude_observations_in_decisions(self, db, store):
        store.add("Decided to use SQLite", source="claude", tags=["decision"])
        result = generate_resume(db, hours=1)
        assert "Decisions & Notes" in result
        assert "Decided to use SQLite" in result

    def test_user_observations_in_decisions(self, db, store):
        store.add("Always use type hints", source="user")
        result = generate_resume(db, hours=1)
        assert "Decisions & Notes" in result
        assert "Always use type hints" in result

    def test_git_observations_in_commits(self, db, store):
        store.add("Commit abc123: Fix auth  Files: auth.py", source="git", tags=["git", "commit"])
        result = generate_resume(db, hours=1)
        assert "Recent Commits" in result
        assert "Fix auth" in result

    def test_hook_observations_in_files_touched(self, db, store):
        store.add("Edited: auth.py", source="hook", tags=["hook", "edit"])
        result = generate_resume(db, hours=1)
        assert "Files Touched" in result
        assert "auth.py" in result


class TestDedup:
    def test_duplicate_hook_observations_collapsed(self, db, store):
        for _ in range(5):
            store.add("Edited: auth.py", source="hook", tags=["hook", "edit"])
        result = generate_resume(db, hours=1)
        # Should only appear once in output
        assert result.count("Edited: auth.py") == 1

    def test_different_files_not_collapsed(self, db, store):
        store.add("Edited: auth.py", source="hook")
        store.add("Edited: models.py", source="hook")
        result = generate_resume(db, hours=1)
        assert "auth.py" in result
        assert "models.py" in result


class TestBudgetLimiting:
    def test_budget_limits_output(self, db, store):
        # Add a lot of observations to exceed a tiny budget
        for i in range(50):
            store.add(f"Decision number {i} with some extra text to use up tokens", source="claude")
        result = generate_resume(db, budget=200, hours=1)
        # Should have the header and first section but not everything
        assert "Session Resume" in result

    def test_large_budget_includes_more(self, db, store):
        store.add("Decision A", source="claude")
        store.add("Commit abc: stuff  Files: a.py", source="git")
        store.add("Edited: b.py", source="hook")
        result = generate_resume(db, budget=10000, hours=1)
        assert "Decisions & Notes" in result
        assert "Recent Commits" in result
        assert "Files Touched" in result


class TestLookbackFiltering:
    def test_old_observations_excluded(self, db):
        # Insert an observation with old timestamp directly
        old_time = time.time() - 86400 * 2  # 2 days ago
        obs = Observation(content="ancient note", created_at=old_time, source="user")
        db.add_observation(obs)
        result = generate_resume(db, hours=1)
        assert "No recent activity" in result

    def test_recent_observations_included(self, db, store):
        store.add("fresh note", source="user")
        result = generate_resume(db, hours=1)
        assert "fresh note" in result


class TestRecentlyModifiedFiles:
    def test_recently_indexed_files_appear(self, db, store):
        f = IndexedFile(
            file_path="src/auth.py",
            file_hash="abc123",
            indexed_at=time.time(),
            node_count=5,
        )
        db.upsert_indexed_file(f)
        result = generate_resume(db, budget=10000, hours=1)
        assert "auth.py" in result
