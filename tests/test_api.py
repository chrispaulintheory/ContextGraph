"""Tests for the Flask API."""

import json
import shutil
from pathlib import Path

import pytest

from context_graph.api import create_app
from context_graph.db import Database
from context_graph.indexer import Indexer


@pytest.fixture
def app_with_data(tmp_path):
    fixtures = Path(__file__).parent.parent / "fixtures"
    proj = tmp_path / "project"
    shutil.copytree(fixtures, proj)

    db = Database()
    indexer = Indexer(db, proj)
    indexer.index_project()

    app = create_app(db=db)
    app.config["TESTING"] = True
    return app, db, proj


@pytest.fixture
def client(app_with_data):
    app, db, proj = app_with_data
    return app.test_client()


@pytest.fixture
def empty_client():
    db = Database()
    app = create_app(db=db)
    app.config["TESTING"] = True
    return app.test_client()


class TestNodes:
    def test_list_all_nodes(self, client):
        resp = client.get("/nodes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0

    def test_filter_by_kind(self, client):
        resp = client.get("/nodes?kind=function")
        data = resp.get_json()
        assert all(n["kind"] == "function" for n in data)

    def test_get_node(self, client):
        resp = client.get("/nodes/simple_module.greet")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "greet"
        assert data["kind"] == "function"

    def test_get_node_not_found(self, client):
        resp = client.get("/nodes/nonexistent")
        assert resp.status_code == 404

    def test_get_node_edges(self, client):
        resp = client.get("/nodes/simple_module/edges")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0


class TestSkeleton:
    def test_skeleton(self, app_with_data):
        app, db, proj = app_with_data
        client = app.test_client()
        file_path = str(proj / "simple_module.py")
        resp = client.get(f"/skeleton?file={file_path}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "skeleton" in data
        assert "def greet" in data["skeleton"]

    def test_skeleton_missing_param(self, client):
        resp = client.get("/skeleton")
        assert resp.status_code == 400

    def test_skeleton_file_not_found(self, client):
        resp = client.get("/skeleton?file=/nonexistent.py")
        assert resp.status_code == 404


class TestCapsule:
    def test_capsule(self, client):
        resp = client.get("/capsule/simple_module.greet")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "capsule" in data
        assert "Context Capsule" in data["capsule"]

    def test_capsule_not_found(self, client):
        resp = client.get("/capsule/nonexistent")
        assert resp.status_code == 404

    def test_capsule_with_depth(self, client):
        resp = client.get("/capsule/simple_module?depth=2")
        assert resp.status_code == 200


class TestObservations:
    def test_create_observation(self, client):
        resp = client.post("/observations", json={
            "content": "test obs", "tags": ["test"],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["content"] == "test obs"
        assert data["id"] is not None

    def test_list_observations(self, client):
        client.post("/observations", json={"content": "obs1", "tags": ["a"]})
        client.post("/observations", json={"content": "obs2", "tags": ["b"]})
        resp = client.get("/observations")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 2

    def test_filter_by_tag(self, client):
        client.post("/observations", json={"content": "bug", "tags": ["bug"]})
        client.post("/observations", json={"content": "perf", "tags": ["perf"]})
        resp = client.get("/observations?tag=bug")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["content"] == "bug"

    def test_delete_observation(self, client):
        resp = client.post("/observations", json={"content": "to delete"})
        obs_id = resp.get_json()["id"]
        del_resp = client.delete(f"/observations/{obs_id}")
        assert del_resp.status_code == 200
        assert del_resp.get_json()["deleted"] is True

    def test_delete_nonexistent(self, client):
        resp = client.delete("/observations/9999")
        assert resp.status_code == 404

    def test_create_missing_content(self, client):
        resp = client.post("/observations", json={})
        assert resp.status_code == 400


class TestResume:
    def test_resume_empty(self, empty_client):
        resp = empty_client.get("/resume")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "resume" in data
        assert "No recent activity" in data["resume"]

    def test_resume_with_observations(self, empty_client):
        # Create some observations first
        empty_client.post("/observations", json={
            "content": "Use SQLite for storage",
            "source": "claude",
            "tags": ["decision"],
        })
        empty_client.post("/observations", json={
            "content": "Commit abc: Fix auth  Files: auth.py",
            "source": "git",
            "tags": ["git", "commit"],
        })
        resp = empty_client.get("/resume?budget=10000&hours=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "Decisions & Notes" in data["resume"]
        assert "Recent Commits" in data["resume"]

    def test_resume_custom_params(self, empty_client):
        resp = empty_client.get("/resume?budget=100&hours=48")
        assert resp.status_code == 200

    def test_resume_budget_param(self, empty_client):
        empty_client.post("/observations", json={
            "content": "note", "source": "user",
        })
        resp = empty_client.get("/resume?budget=5000")
        data = resp.get_json()
        assert "resume" in data


class TestHooksInstall:
    def test_install_hooks_missing_root(self, empty_client):
        resp = empty_client.post("/hooks/install", json={})
        assert resp.status_code == 400

    def test_install_hooks_not_git_repo(self, empty_client, tmp_path):
        resp = empty_client.post("/hooks/install", json={"root": str(tmp_path)})
        assert resp.status_code == 400
        assert "not a git repository" in resp.get_json()["error"]

    def test_install_hooks_success(self, empty_client, tmp_path):
        # Create a fake git repo
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        resp = empty_client.post("/hooks/install", json={"root": str(tmp_path)})
        assert resp.status_code == 201
        data = resp.get_json()
        assert "claude_code_config" in data
        assert "hooks" in data["claude_code_config"]


class TestStatus:
    def test_status(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "db_stats" in data
        assert "nodes" in data["db_stats"]


class TestProjects:
    def test_register_project(self, app_with_data):
        app, db, proj = app_with_data
        client = app.test_client()
        resp = client.post("/projects", json={"root": str(proj)})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["message"] == "registered"

    def test_register_missing_root(self, empty_client):
        resp = empty_client.post("/projects", json={})
        assert resp.status_code == 400

    def test_register_nonexistent_dir(self, empty_client):
        resp = empty_client.post("/projects", json={"root": "/nonexistent/path"})
        assert resp.status_code == 404

    def test_reindex(self, app_with_data):
        app, db, proj = app_with_data
        client = app.test_client()
        # Register first
        client.post("/projects", json={"root": str(proj)})
        resp = client.post("/index", json={"force": True})
        assert resp.status_code == 200
        assert resp.get_json()["indexed_files"] >= 1
