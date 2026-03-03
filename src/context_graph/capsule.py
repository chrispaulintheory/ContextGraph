"""Context capsule markdown generator."""

from __future__ import annotations

from .db import Database
from .graph import Graph
from .models import NodeRecord
from .observations import ObservationStore
from .skeletonizer import skeletonize
from .tokens import TokenStats, estimate_tokens


def generate_capsule(
    db: Database,
    node_id: str,
    depth: int = 1,
) -> tuple[str, TokenStats] | None:
    """Generate a context capsule markdown document for a node.

    Includes: pivot signature, parent class skeleton, depth-1
    dependencies/dependents, linked observations, token estimate.
    """
    node = db.get_node(node_id)
    if node is None:
        return None

    graph = Graph(db)
    obs_store = ObservationStore(db)
    sections: list[str] = []

    # TRACK ORIGINAL TOKENS
    # Original is the full content of the pivot and its parent (if applicable)
    original_text = ""
    try:
        with open(node.file_path) as f:
            file_lines = f.readlines()
        # line_start/end are usually 1-indexed
        node_source = "".join(file_lines[node.line_start - 1 : node.line_end])
        original_text += node_source
    except (OSError, IndexError):
        pass

    # Header
    sections.append(f"# Context Capsule: `{node.id}`\n")

    # Pivot info
    sections.append(f"**Kind:** {node.kind}  ")
    sections.append(f"**File:** `{node.file_path}`  ")
    sections.append(f"**Lines:** {node.line_start}–{node.line_end}\n")

    # Signature
    if node.signature:
        sections.append("## Signature\n")
        sections.append(f"```python\n{node.signature}\n```\n")

    # Docstring
    if node.docstring:
        sections.append("## Docstring\n")
        sections.append(f"> {node.docstring}\n")

    # Decorators
    if node.decorators:
        sections.append("## Decorators\n")
        for dec in node.decorators:
            sections.append(f"- `@{dec}`")
        sections.append("")

    # Parent context
    if node.parent_id:
        parent = db.get_node(node.parent_id)
        if parent and parent.kind == "class":
            sections.append("## Parent Class\n")
            try:
                with open(parent.file_path) as f:
                    parent_full_source = f.read()
                original_text += parent_full_source
                skeleton = skeletonize(parent_full_source)
                # Extract just the class section
                lines = skeleton.split("\n")
                class_lines = []
                in_class = False
                for line in lines:
                    if f"class {parent.name}" in line:
                        in_class = True
                    if in_class:
                        class_lines.append(line)
                        if class_lines and line and not line[0].isspace() and not line.startswith("class"):
                            class_lines.pop()
                            break
                if class_lines:
                    sections.append(f"```python\n{chr(10).join(class_lines)}\n```\n")
            except (OSError, ValueError):
                sections.append(f"Parent: `{parent.id}` ({parent.kind})\n")

    # Dependencies (what this node depends on)
    deps = graph.dependencies(node_id, depth=depth)
    if deps:
        sections.append("## Dependencies\n")
        sections.append("| Target | Kind | Line |")
        sections.append("|--------|------|------|")
        seen = set()
        for edge in deps:
            key = (edge.target_id, edge.kind)
            if key not in seen:
                seen.add(key)
                sections.append(f"| `{edge.target_id}` | {edge.kind} | {edge.line or '—'} |")
        sections.append("")

    # Dependents (who depends on this node)
    dependents = graph.dependents(node_id, depth=depth)
    if dependents:
        sections.append("## Dependents\n")
        sections.append("| Source | Kind | Line |")
        sections.append("|--------|------|------|")
        seen = set()
        for edge in dependents:
            key = (edge.source_id, edge.kind)
            if key not in seen:
                seen.add(key)
                sections.append(f"| `{edge.source_id}` | {edge.kind} | {edge.line or '—'} |")
        sections.append("")

    # Observations
    observations = obs_store.list(node_id=node_id)
    if observations:
        sections.append("## Observations\n")
        for obs in observations:
            tags = f" [{', '.join(obs.tags)}]" if obs.tags else ""
            sections.append(f"- {obs.content}{tags}")
        sections.append("")

    # Token estimate
    content = "\n".join(sections)
    stats = TokenStats(
        original=estimate_tokens(original_text),
        optimized=estimate_tokens(content),
    )
    content += f"\n---\n*Token Savings: {stats.saved} tokens ({stats.percentage:.1f}% reduction)*\n"

    return content, stats
