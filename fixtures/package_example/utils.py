"""Utility functions."""


def helper(text: str) -> str:
    """Help with text processing."""
    return text.strip().lower()


def format_output(items: list[str]) -> str:
    """Format items for display."""
    return ", ".join(items)
