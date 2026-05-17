def hello(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"


class Greeter:
    def __init__(self, prefix: str = "Hello") -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix}, {name}!"
