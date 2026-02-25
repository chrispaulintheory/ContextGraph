# ContextGraph

Local Python context engine that reduces LLM token usage. Indexes your codebase (AST signatures, dependency graphs, skeletons) and persists session memory so you don't have to re-explain your project every time you start a new chat.

## Install

```
uv pip install -e .
```

## Run

```
context-graph
```

Server starts at `http://127.0.0.1:5577`.

## Key endpoints

- `POST /projects` — register a project root for indexing
- `GET /capsule/<node_id>` — structural context for a function/class
- `GET /skeleton?file=<path>` — signatures-only view of a file
- `POST /observations` — save a decision or note
- `GET /resume` — catch-up prompt for a new chat session

## Test

```
uv pip install -e ".[dev]"
pytest
```
