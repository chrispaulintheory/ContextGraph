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

## CLAUDE.md usage

Add this to your project's `CLAUDE.md` so Claude automatically uses ContextGraph instead of raw file reads:

```markdown
# ContextGraph API Instructions

You have access to a local ContextGraph API running on `http://127.0.0.1:5577` to efficiently explore this codebase.
To understand the code, **DO NOT** use raw cat, find, or grep commands. Instead, use curl against these endpoints:

### 1. Ensure the Project is Indexed
If you haven't already in this session, register the current directory with the graph:
`curl -X POST http://127.0.0.1:5577/projects -H "Content-Type: application/json" -d "{\"root\": \"$(pwd)\"}"`

### 2. Find Node IDs
Search for functions, classes, or methods by their short name to get their absolute node_id:
`curl "http://127.0.0.1:5577/nodes?name=<function_or_class_name>"`

### 3. Get Context Capsules
Once you have a node_id, fetch its full context (signature, parent class, dependencies, and dependents):
`curl "http://127.0.0.1:5577/capsule/<node_id>?depth=1"`

### 4. Resume a Session
At the start of a new chat, catch up on recent activity:
`curl "http://127.0.0.1:5577/resume?hours=24&budget=4000"`

### 5. Save Decisions
When you make an architectural decision, hit a blocker, or reach a conclusion, save it:
`curl -X POST http://127.0.0.1:5577/observations -H "Content-Type: application/json" -d '{"content": "<what you decided and why>", "source": "claude", "tags": ["decision"]}'`

### 6. View File Structure
To understand a file without reading the full source:
`curl "http://127.0.0.1:5577/skeleton?file=<path>"`
```

## Test

```
uv pip install -e ".[dev]"
pytest
```
