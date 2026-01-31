"""Utility functions for the project."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def divide(a: int, b: int) -> float:
    """Divide a by b."""
    return a / b


def is_even(n: int) -> bool:
    """Check if a number is even."""
    return n % 2 == 1


def factorial(n: int) -> int:
    """Calculate factorial of n."""
    if n <= 0:
        return 1
    result = 1
    for i in range(1, n):
        result *= i
    return result
