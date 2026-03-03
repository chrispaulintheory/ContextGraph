# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable)
uv pip install -e .

# Run server
source .venv/bin/activate && context-graph

# Install with dev deps and run tests
uv pip install -e ".[dev]"
pytest

# Check Project Token Efficiency
curl "http://127.0.0.1:5577/status?root=$(pwd)"
```

## Architecture

ContextGraph is a local HTTP service (Flask, port 5577) that indexes codebases via AST and serves structural context to LLMs instead of raw file contents. Responses include a `token_stats` object to track optimization (Original vs. Optimized tokens).

### Module map

| Module | Role |
|--------|------|
| `api.py` | Flask app factory (`create_app`) and `main()` entry point; all routes live here |
| `models.py` | Dataclasses: `NodeRecord`, `EdgeRecord`, `Observation`, `IndexedFile` |
| `db.py` | `Database` class — SQLite CRUD for nodes, edges, observations, indexed_files |
| `indexer.py` | `Indexer` — tree-sitter Python AST walker; produces nodes + edges |
| `indexer_swift.py` | `SwiftIndexer` — same contract as `Indexer` but for Swift files |
| `watcher.py` | `ProjectWatcher` wraps watchdog + `_MultiIndexer` (dispatches by extension) + debounced re-index |
| `skeletonizer.py` | `skeletonize_file` — signatures-only view of a file, no source read required |
| `capsule.py` | `generate_capsule` — fetches a node + its edges to depth N |
| `graph.py` | Graph traversal helpers used by capsule |
| `observations.py` | `ObservationStore` — session memory CRUD on top of `Database` |
| `resume.py` | `generate_resume` — produces token-budgeted markdown catch-up summary |

### Key conventions

**Node IDs** are dot-separated qualified names: `src.context_graph.indexer.Indexer.index_file`. The `root` query param on every API request is the absolute project path used to route to the correct per-project database.

**Edge kinds**: `calls`, `imports`, `inherits`, `decorates`

**Node kinds**: `module`, `class`, `function`, `method`

**Incremental indexing**: `Indexer.index_file` hashes the file and skips re-indexing if the hash hasn't changed (unless `force=True`). Clearing old nodes/edges before re-indexing happens at the file level, not the project level.

**Project registration flow**: `POST /projects` → creates `Database` + `ProjectWatcher` → calls `watcher.index_now()` (blocking full index) → `watcher.start()` (background watchdog thread). State lives in the `create_app` closure (`projects` dict, `dbs` dict).

**Hooks**: `POST /hooks/install` installs a git `post-commit` hook and returns the Claude Code `settings.json` snippet for the `PostToolUse` hook (auto re-index on file edits).

### Testing

Tests use an in-memory `Database()` via `conftest.py` fixtures. The Flask test client is created via `create_app(db=in_memory_db)` so tests never touch disk.
