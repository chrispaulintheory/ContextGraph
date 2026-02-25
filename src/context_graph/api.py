"""Flask API for ContextGraph."""

from __future__ import annotations

import hashlib
from pathlib import Path

from flask import Flask, jsonify, request

from .capsule import generate_capsule
from .db import Database
from .graph import Graph
from .observations import ObservationStore
from .resume import generate_resume
from .skeletonizer import skeletonize_file
from .watcher import ProjectWatcher


def _project_db_path(root: str) -> Path:
    """Return per-project DB path: ~/.context_graph/projects/<hash>/context.db"""
    h = hashlib.sha256(root.encode()).hexdigest()[:16]
    return Path.home() / ".context_graph" / "projects" / h / "context.db"


def create_app(db: Database | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # State: registered projects with their watchers
    projects: dict[str, ProjectWatcher] = {}
    # Cache of per-project databases (keyed by resolved root path)
    dbs: dict[str, Database] = {}

    def _get_db(root: str | None = None) -> Database:
        if db is not None:
            return db
        if root:
            if root not in dbs:
                db_path = _project_db_path(root)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                dbs[root] = Database(str(db_path))
            return dbs[root]
        # Fallback: global in-memory DB
        if not hasattr(app, "_db"):
            app._db = Database()
        return app._db

    # ── Projects ───────────────────────────────────────────

    @app.route("/projects", methods=["POST"])
    def register_project():
        data = request.get_json(force=True)
        project_root = data.get("root")
        if not project_root:
            return jsonify({"error": "missing 'root'"}), 400

        project_root = str(Path(project_root).resolve())
        if not Path(project_root).is_dir():
            return jsonify({"error": "directory not found"}), 404

        if project_root in projects:
            return jsonify({"message": "already registered", "root": project_root})

        project_db = _get_db(project_root)
        watcher = ProjectWatcher(project_db, project_root)
        file_count = watcher.index_now()
        watcher.start()
        projects[project_root] = watcher

        return jsonify({
            "message": "registered",
            "root": project_root,
            "indexed_files": file_count,
        }), 201

    # ── Index ──────────────────────────────────────────────

    @app.route("/index", methods=["POST"])
    def reindex():
        data = request.get_json(force=True) if request.data else {}
        force = data.get("force", False)
        total = 0
        for watcher in projects.values():
            total += watcher.index_now(force=force)
        return jsonify({"indexed_files": total})

    # ── Nodes ──────────────────────────────────────────────

    @app.route("/nodes")
    def list_nodes():
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        file_path = request.args.get("file")
        kind = request.args.get("kind")
        name = request.args.get("name")
        nodes = d.list_nodes(file_path=file_path, kind=kind, name=name)
        return jsonify([{
            "id": n.id, "kind": n.kind, "name": n.name,
            "file_path": n.file_path,
            "line_start": n.line_start, "line_end": n.line_end,
            "signature": n.signature, "docstring": n.docstring,
            "parent_id": n.parent_id, "is_external": n.is_external,
        } for n in nodes])

    @app.route("/nodes/<path:node_id>")
    def get_node(node_id):
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        node = d.get_node(node_id)
        if node is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "id": node.id, "kind": node.kind, "name": node.name,
            "file_path": node.file_path,
            "line_start": node.line_start, "line_end": node.line_end,
            "signature": node.signature, "docstring": node.docstring,
            "parent_id": node.parent_id, "decorators": node.decorators,
            "is_external": node.is_external,
        })

    @app.route("/nodes/<path:node_id>/edges")
    def get_node_edges(node_id):
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        direction = request.args.get("direction", "both")
        kind = request.args.get("kind")

        edges = []
        if direction in ("out", "both"):
            edges.extend(d.get_edges(source_id=node_id, kind=kind))
        if direction in ("in", "both"):
            edges.extend(d.get_edges(target_id=node_id, kind=kind))

        return jsonify([{
            "id": e.id, "source_id": e.source_id, "target_id": e.target_id,
            "kind": e.kind, "line": e.line, "resolved": e.resolved,
        } for e in edges])

    # ── Skeleton ───────────────────────────────────────────

    @app.route("/skeleton")
    def skeleton():
        file_path = request.args.get("file")
        if not file_path:
            return jsonify({"error": "missing 'file' parameter"}), 400
        path = Path(file_path)
        if not path.is_file():
            return jsonify({"error": "file not found"}), 404
        result = skeletonize_file(path)
        return jsonify({"file": str(path), "skeleton": result})

    # ── Capsule ────────────────────────────────────────────

    @app.route("/capsule/<path:node_id>")
    def capsule(node_id):
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        depth = request.args.get("depth", 1, type=int)
        result = generate_capsule(d, node_id, depth=depth)
        if result is None:
            return jsonify({"error": "node not found"}), 404
        return jsonify({"node_id": node_id, "capsule": result})

    # ── Observations ───────────────────────────────────────

    @app.route("/observations", methods=["POST"])
    def create_observation():
        data = request.get_json(force=True)
        root = data.get("root")
        if root:
            root = str(Path(root).resolve())
        if db is None and root is None:
            return jsonify({"error": "missing 'root'"}), 400
        d = _get_db(root)
        store = ObservationStore(d)
        content = data.get("content")
        if not content:
            return jsonify({"error": "missing 'content'"}), 400

        obs = store.add(
            content=content,
            node_id=data.get("node_id"),
            tags=data.get("tags", []),
            source=data.get("source", "user"),
        )
        return jsonify({
            "id": obs.id, "content": obs.content,
            "node_id": obs.node_id, "tags": obs.tags,
        }), 201

    @app.route("/observations")
    def list_observations():
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        store = ObservationStore(d)
        node_id = request.args.get("node_id")
        tag = request.args.get("tag")
        observations = store.list(node_id=node_id, tag=tag)
        return jsonify([{
            "id": o.id, "content": o.content,
            "node_id": o.node_id, "tags": o.tags,
            "source": o.source,
        } for o in observations])

    @app.route("/observations/<int:obs_id>", methods=["DELETE"])
    def delete_observation(obs_id):
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        store = ObservationStore(d)
        if store.delete(obs_id):
            return jsonify({"deleted": True})
        return jsonify({"error": "not found"}), 404

    # ── Resume ─────────────────────────────────────────────

    @app.route("/resume")
    def resume():
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        budget = request.args.get("budget", 4000, type=int)
        hours = request.args.get("hours", 24, type=int)
        md = generate_resume(d, budget=budget, hours=hours)
        return jsonify({"resume": md})

    # ── Hooks ──────────────────────────────────────────────

    @app.route("/hooks/install", methods=["POST"])
    def install_hooks():
        import stat
        data = request.get_json(force=True)
        root = data.get("root")
        if not root:
            return jsonify({"error": "missing 'root'"}), 400

        root_path = Path(root).resolve()
        git_dir = root_path / ".git"
        if not git_dir.is_dir():
            return jsonify({"error": "not a git repository"}), 400

        # Install git post-commit hook
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        hook_src = Path(__file__).parent.parent.parent / "hooks" / "post_commit.sh"
        hook_dst = hooks_dir / "post-commit"

        if hook_src.is_file():
            hook_dst.write_text(hook_src.read_text())
            hook_dst.chmod(hook_dst.stat().st_mode | stat.S_IEXEC)
            git_hook_installed = True
        else:
            git_hook_installed = False

        # Return Claude Code hook config snippet
        claude_hook_src = Path(__file__).parent.parent.parent / "hooks" / "claude_post_edit.sh"
        claude_config = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "command": str(claude_hook_src.resolve()) if claude_hook_src.is_file() else "hooks/claude_post_edit.sh",
                    }
                ]
            }
        }

        return jsonify({
            "git_hook_installed": git_hook_installed,
            "claude_code_config": claude_config,
            "message": "Add claude_code_config to .claude/settings.json",
        }), 201

    # ── Status ─────────────────────────────────────────────

    @app.route("/status")
    def status():
        root = request.args.get("root")
        if root:
            root = str(Path(root).resolve())
        d = _get_db(root)
        stats = d.stats()
        watcher_info = {
            root: {"running": w.is_running}
            for root, w in projects.items()
        }
        return jsonify({
            "db_stats": stats,
            "watchers": watcher_info,
        })

    return app


def main():
    """Run the API server."""
    app = create_app()
    app.run(host="127.0.0.1", port=5577, debug=True)


if __name__ == "__main__":
    main()
