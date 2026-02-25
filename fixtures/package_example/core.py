"""Core processing module."""

from .utils import helper


def process(data: list[str]) -> list[str]:
    """Process a list of strings."""
    return [helper(item) for item in data]


def transform(item: str) -> str:
    """Transform a single item."""
    return item.upper()
