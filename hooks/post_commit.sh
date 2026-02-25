#!/usr/bin/env bash
# Git post-commit hook: records commit info as a ContextGraph observation.
# Runs in the background so it never blocks git.

CONTEXT_GRAPH_URL="${CONTEXT_GRAPH_URL:-http://127.0.0.1:5577}"

_post_observation() {
    SHA=$(git rev-parse --short HEAD 2>/dev/null)
    MESSAGE=$(git log -1 --pretty=%s 2>/dev/null)
    FILES=$(git diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null | tr '\n' ', ' | sed 's/,$//')

    # Use Python for safe JSON encoding of the commit message
    PAYLOAD=$(python3 -c "
import json, sys
print(json.dumps({
    'content': f'Commit {sys.argv[1]}: {sys.argv[2]}  Files: {sys.argv[3]}',
    'source': 'git',
    'tags': ['git', 'commit'],
}))
" "$SHA" "$MESSAGE" "$FILES" 2>/dev/null)

    [ -z "$PAYLOAD" ] && return

    curl -s -X POST "${CONTEXT_GRAPH_URL}/observations" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" >/dev/null 2>&1
}

_post_observation &
