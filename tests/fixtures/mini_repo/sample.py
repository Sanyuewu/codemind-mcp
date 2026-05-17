import os
from typing import Optional


# Greet a person by name
def hello(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"


class Greeter:
    """A class that greets people."""

    def __init__(self, prefix: str = "Hello") -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        """Greet a person by name."""
        return f"{self.prefix}, {name}!"
