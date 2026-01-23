#!/usr/bin/env python3
"""Seed Gitea repo and Kanban board for junior dev scenario."""

import json
import sys
from zoo_eval.zoo_cli import get_zoo_cli


# Buggy Python utility file - each function has a simple bug
UTILS_PY = '''"""Utility functions for the project."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a + b  # BUG: should be a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def divide(a: int, b: int) -> float:
    """Divide a by b."""
    return a / b  # BUG: no zero division check


def is_even(n: int) -> bool:
    """Check if a number is even."""
    return n % 2 == 1  # BUG: should be == 0


def factorial(n: int) -> int:
    """Calculate factorial of n."""
    if n <= 0:
        return 1
    result = 1
    for i in range(1, n):  # BUG: should be range(1, n + 1)
        result *= i
    return result
'''

README_MD = '''# Calculator Utils

A simple utility library for basic math operations.

## Functions

- `add(a, b)` - Add two numbers
- `subtract(a, b)` - Subtract b from a
- `multiply(a, b)` - Multiply two numbers
- `divide(a, b)` - Divide a by b
- `is_even(n)` - Check if a number is even
- `factorial(n)` - Calculate factorial

## Known Issues

See the Kanban board for current bugs and improvements.
'''


def main():
    cli = get_zoo_cli()

    print("Setting up junior dev scenario...")

    # 1. Create Gitea repo
    print("Creating Gitea repository...")
    result = cli.gitea_create_repo(
        name="calculator-utils",
        owner="alice",
        description="Simple math utility library",
        auto_init=True
    )
    if result.returncode != 0:
        print(f"Warning: Repo creation returned {result.returncode}")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")

    # 2. Add the buggy utils.py file
    print("Adding utils.py...")
    result = cli.gitea_add_file(
        owner="alice",
        repo="calculator-utils",
        path="utils.py",
        content=UTILS_PY,
        message="Add utility functions"
    )
    if result.returncode != 0:
        print(f"Warning: Failed to add utils.py: {result.stderr}")

    # 3. Add README
    print("Adding README.md...")
    result = cli.gitea_add_file(
        owner="alice",
        repo="calculator-utils",
        path="README.md",
        content=README_MD,
        message="Add README"
    )
    if result.returncode != 0:
        print(f"Warning: Failed to add README: {result.stderr}")

    # 4. Create Gitea issues for each bug
    issues = [
        {
            "title": "BUG: subtract() returns wrong result",
            "body": "The subtract function in utils.py returns incorrect results.\n\nExpected: subtract(5, 3) = 2\nActual: subtract(5, 3) = 8\n\nLooks like it's adding instead of subtracting."
        },
        {
            "title": "BUG: divide() crashes on zero",
            "body": "The divide function in utils.py crashes with ZeroDivisionError when the second argument is 0.\n\nWe need to add a check and raise a proper ValueError with a helpful message."
        },
        {
            "title": "BUG: is_even() returns inverted results",
            "body": "The is_even function in utils.py returns True for odd numbers and False for even numbers.\n\nExpected: is_even(4) = True, is_even(3) = False\nActual: is_even(4) = False, is_even(3) = True\n\nThis is causing issues in production billing."
        },
        {
            "title": "BUG: factorial() off by one",
            "body": "The factorial function in utils.py returns wrong results.\n\nExpected: factorial(5) = 120\nActual: factorial(5) = 24\n\nSeems like an off-by-one error in the loop."
        },
    ]

    print("Creating Gitea issues...")
    for issue in issues:
        print(f"  - {issue['title']}")
        result = cli.gitea_create_issue(
            owner="alice",
            repo="calculator-utils",
            title=issue["title"],
            body=issue["body"]
        )
        if result.returncode != 0:
            print(f"    Warning: {result.stderr}")

    # 5. Create Kanban board with corresponding cards
    print("Creating Kanban board...")
    result = cli.kanban_create_board(title="Calculator Utils - Sprint 1")
    if result.returncode != 0:
        print(f"Warning: Board creation issue: {result.stderr}")
    if result.stdout:
        print(f"  {result.stdout.strip()}")

    print("\nSetup complete!")
    print("  - Gitea repo: alice/calculator-utils with 4 issues")
    print("  - Kanban board: Calculator Utils - Sprint 1")


if __name__ == "__main__":
    main()
