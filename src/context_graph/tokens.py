"""Token estimation and statistics tracking."""

from __future__ import annotations

from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Estimate tokens in a text.

    Uses a slightly more sophisticated heuristic than len // 4:
    - ~1 token per 4 characters (standard)
    - Adjust for whitespaces (which are often merged/skipped in some tokenizers)
    - Adjust for special symbols.
    """
    if not text:
        return 0
    # Standard heuristic is 4 characters per token for English.
    # Code is denser and has more punctuation.
    # Let's use a hybrid of word count and char count.
    words = text.split()
    word_estimate = len(words) * 1.3  # Tokens are often slightly more than words
    char_estimate = len(text) / 3.8  # Code has lots of short punctuation tokens
    return int((word_estimate + char_estimate) / 2)


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
