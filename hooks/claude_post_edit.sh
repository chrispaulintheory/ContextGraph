#!/usr/bin/env bash
# Claude Code post-tool hook: records edited file paths as ContextGraph observations.
# Reads tool info from stdin JSON. Runs background curl so it never blocks Claude.

CONTEXT_GRAPH_URL="${CONTEXT_GRAPH_URL:-http://127.0.0.1:5577}"

# Read stdin (Claude Code passes tool result as JSON)
INPUT=$(cat)

# Extract the tool name and file path using Python for safe JSON parsing
PAYLOAD=$(python3 -c "
import json, os, sys
try:
    data = json.loads(sys.argv[1])
    tool = data.get('tool_name', '')
    # Only handle Edit and Write tools
    if tool not in ('Edit', 'Write'):
        sys.exit(0)
    file_path = data.get('tool_input', {}).get('file_path', '')
    if not file_path:
        sys.exit(0)
    print(json.dumps({
        'content': f'Edited: {file_path}',
        'source': 'hook',
        'tags': ['hook', 'edit'],
        'root': os.getcwd(),
    }))
except Exception:
    sys.exit(0)
" "$INPUT" 2>/dev/null)

[ -z "$PAYLOAD" ] && exit 0

curl -s -X POST "${CONTEXT_GRAPH_URL}/observations" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" >/dev/null 2>&1 &
