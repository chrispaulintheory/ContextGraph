"""Token estimation and statistics tracking."""

from __future__ import annotations

from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Estimate tokens in text using a ~3.5 chars/token heuristic.

    Code skews tighter than prose (more punctuation, short identifiers),
    so 3.5 chars/token is more accurate than the common 4.0.
    """
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def estimate_tokens_from_chars(char_count: int) -> int:
    """Estimate tokens directly from a character count."""
    if char_count <= 0:
        return 0
    return max(1, int(char_count / 3.5))


@dataclass(frozen=True)
class TokenStats:
    original: int
    optimized: int

    @property
    def saved(self) -> int:
        return max(0, self.original - self.optimized)

    @property
    def percentage(self) -> float:
        if self.original == 0:
            return 0.0
        return (self.saved / self.original) * 100

    def __str__(self) -> str:
        return (
            f"Original: {self.original} tokens | "
            f"Optimized: {self.optimized} tokens | "
            f"Saved: {self.saved} ({self.percentage:.1f}%)"
        )
