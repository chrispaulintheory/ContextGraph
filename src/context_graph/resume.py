"""Resume endpoint: generates a catch-up prompt from recent activity."""

from __future__ import annotations

import time

from .capsule import generate_capsule
from .db import Database
from .observations import ObservationStore


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def generate_resume(
    db: Database,
    budget: int = 4000,
    hours: int = 24,
) -> str:
    """Build a prioritized markdown catch-up prompt from recent activity.

    Fills sections in priority order, stopping when *budget* tokens exhausted:
      1. Claude/user observations (decisions, blockers)
      2. Recent git commits (message + file list)
      3. Capsules for recently-modified files
      4. Files touched (deduplicated hook observations)

    Returns markdown string.  Empty DB → short "no activity" message.
    """
    since = time.time() - (hours * 3600)
    store = ObservationStore(db)
    sections: list[str] = []
    used = 0

    def _add(section: str, force_first: bool = False) -> bool:
        """Append *section* if it fits in the budget. Returns True if added.

        If *force_first* is True and no sections exist yet, always add
        (truncated to budget) so the resume is never empty when data exists.
        """
        nonlocal used
        cost = _estimate_tokens(section)
        if used + cost > budget:
            if force_first and not sections:
                # Truncate to fit budget
                max_chars = budget * 4
                section = section[:max_chars]
                sections.append(section)
                used = budget
                return True
            return False
        sections.append(section)
        used += cost
        return True

    # ── 1. High-priority observations (claude / user) ─────────────
    high_obs = store.list_since(since, source="claude") + store.list_since(since, source="user")
    # Deduplicate and sort by time (newest first)
    seen_ids: set[int] = set()
    unique_high: list = []
    for o in sorted(high_obs, key=lambda x: x.created_at, reverse=True):
        if o.id not in seen_ids:
            seen_ids.add(o.id)
            unique_high.append(o)

    if unique_high:
        lines = ["## Decisions & Notes\n"]
        for o in unique_high:
            tags = f" [{', '.join(o.tags)}]" if o.tags else ""
            lines.append(f"- {o.content}{tags}")
        lines.append("")
        _add("\n".join(lines), force_first=True)

    # ── 2. Git commit observations ────────────────────────────────
    git_obs = store.list_since(since, source="git")
    if git_obs:
        lines = ["## Recent Commits\n"]
        for o in git_obs:
            lines.append(f"- {o.content}")
        lines.append("")
        _add("\n".join(lines))

    # ── 3. Capsules for recently-modified files ───────────────────
    recent_files = db.list_recently_indexed_files(since)
    if recent_files:
        capsule_lines = ["## Recently Modified Files\n"]
        for f in recent_files:
            if used >= budget:
                break
            # Try to generate a capsule for the module node
            # Module node id is typically the filename stem
            file_stem = f.file_path.rsplit("/", 1)[-1].replace(".py", "")
            capsule_text = generate_capsule(db, file_stem, depth=1)
            if capsule_text and _estimate_tokens(capsule_text) + used <= budget:
                capsule_lines.append(capsule_text)
            else:
                capsule_lines.append(f"- `{f.file_path}`")
        capsule_lines.append("")
        _add("\n".join(capsule_lines))

    # ── 4. Hook observations (file edits, deduplicated) ───────────
    hook_obs = store.list_since(since, source="hook")
    if hook_obs:
        deduped = ObservationStore.deduplicate_hook_observations(hook_obs)
        lines = ["## Files Touched\n"]
        for o in deduped:
            lines.append(f"- {o.content}")
        lines.append("")
        _add("\n".join(lines))

    if not sections:
        return "No recent activity found.\n"

    header = "# Session Resume\n\n"
    content = header + "\n".join(sections)
    content += f"\n---\n*Budget used: ~{used} of {budget} tokens*\n"
    return content
