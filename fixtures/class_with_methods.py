"""Module with a class hierarchy."""

from dataclasses import dataclass


@dataclass
class Base:
    """A base class."""
    name: str

    def describe(self) -> str:
        """Describe this object."""
        return f"Base({self.name})"


class Child(Base):
    """A child class inheriting from Base."""

    def describe(self) -> str:
        """Override describe."""
        base = super().describe()
        return f"Child -> {base}"

    def greet(self) -> str:
        """Greet using name."""
        return f"Hi, I'm {self.name}"
