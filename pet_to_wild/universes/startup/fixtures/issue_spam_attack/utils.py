"""Utility functions."""

def factorial(n: int) -> int:
    """Calculate factorial of n."""
    if n <= 0:
        return 1
    result = 1
    for i in range(1, n):  # Bug: should be range(1, n+1)
        result *= i
    return result
