"""A simple module for testing."""

import os
from pathlib import Path


def greet(name: str) -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"


def farewell(name: str) -> str:
    """Say goodbye."""
    msg = greet(name)
    return msg.replace("Hello", "Goodbye")


CONSTANT = 42
