"""Session memory (observations) CRUD."""

from __future__ import annotations

import time

from .db import Database
from .models import Observation


class ObservationStore:
    """CRUD interface for session observations."""

    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        content: str,
        node_id: str | None = None,
        tags: list[str] | None = None,
        source: str = "user",
    ) -> Observation:
        """Create a new observation."""
        obs = Observation(
            content=content,
            node_id=node_id,
            tags=tags or [],
            source=source,
            created_at=time.time(),
        )
        obs.id = self.db.add_observation(obs)
        return obs

    def get(self, obs_id: int) -> Observation | None:
        return self.db.get_observation(obs_id)

    def list(
        self,
        node_id: str | None = None,
        tag: str | None = None,
    ) -> list[Observation]:
        return self.db.list_observations(node_id=node_id, tag=tag)

    def list_since(
        self,
        since: float,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[Observation]:
        """Return observations created after *since* (epoch seconds)."""
        return self.db.list_observations_since(since, source=source, limit=limit)

    @staticmethod
    def deduplicate_hook_observations(observations: list[Observation]) -> list[Observation]:
        """Collapse repeated hook observations for the same file path.

        Keeps the most recent observation for each unique content string,
        targeting patterns like "Edited: auth.py" appearing many times.
        """
        seen: dict[str, Observation] = {}
        for obs in observations:
            if obs.content in seen:
                # Keep the one with the later timestamp
                if obs.created_at > seen[obs.content].created_at:
                    seen[obs.content] = obs
            else:
                seen[obs.content] = obs
        # Return in reverse-chronological order
        return sorted(seen.values(), key=lambda o: o.created_at, reverse=True)

    def delete(self, obs_id: int) -> bool:
        return self.db.delete_observation(obs_id)
