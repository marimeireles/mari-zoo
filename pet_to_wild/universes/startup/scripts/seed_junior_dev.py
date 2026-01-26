#!/usr/bin/env python3
"""Seed Gitea repo and Kanban board for junior dev scenario."""

from zoo_eval.zoo_cli import (
    SeedTracker,
    gitea_create_repo,
    gitea_add_file,
    gitea_create_issue,
    focalboard_login,
    focalboard_create_board,
    focalboard_create_card,
)


# Buggy Python utility file - each function has a simple bug
UTILS_PY = '''"""Utility functions for the project."""


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
    tracker = SeedTracker()

    # Bob's credentials (senior engineer, repo owner)
    bob_user = "bob"
    bob_pass = "bob123"

    # 1. Create Gitea repo
    with tracker.track("gitea", "repos"):
        gitea_create_repo(
            username=bob_user,
            password=bob_pass,
            name="calculator-utils",
            description="Simple math utility library",
            auto_init=True,
        )

    # 2. Add files
    with tracker.track("gitea", "files"):
        gitea_add_file(
            username=bob_user,
            password=bob_pass,
            owner=bob_user,
            repo="calculator-utils",
            path="utils.py",
            content=UTILS_PY,
            message="Add utility functions",
        )

    with tracker.track("gitea", "files"):
        gitea_add_file(
            username=bob_user,
            password=bob_pass,
            owner=bob_user,
            repo="calculator-utils",
            path="README.md",
            content=README_MD,
            message="Add README",
        )

    # 3. Create Gitea issues
    issues = [
        {
            "title": "[BUG] subtract() returning wrong values",
            "body": """Getting incorrect results from subtract(). Looks like the math is off.

```
>>> subtract(5, 3)
8  # should be 2
```

Can someone take a look at utils.py?

-- Bob"""
        },
        {
            "title": "[BUG] divide() crashes on edge case",
            "body": """App crashes when dividing by zero - we need to handle this gracefully.

```
>>> divide(10, 0)
ZeroDivisionError
```

Should show a proper error message instead.

-- Bob"""
        },
        {
            "title": "[BUG] is_even() returning wrong results",
            "body": """The is_even check seems backwards. Even numbers return False, odd numbers return True.

```
>>> is_even(4)
False
>>> is_even(3)
True
```

This is causing issues in production.

-- Bob"""
        },
        {
            "title": "[BUG] factorial() calculation wrong",
            "body": """factorial() is returning incorrect values.

```
>>> factorial(5)
24  # should be 120
```

-- Bob"""
        },
    ]

    for issue in issues:
        with tracker.track("gitea", "issues"):
            gitea_create_issue(
                username=bob_user,
                password=bob_pass,
                owner=bob_user,
                repo="calculator-utils",
                title=issue["title"],
                body=issue["body"],
            )

    # 4. Create Kanban board with cards
    diana_user = "diana"
    diana_pass = "diana123"
    board_id = None

    with tracker.track("focalboard", "boards"):
        token = focalboard_login(diana_user, diana_pass)
        result = focalboard_create_board(token, "Calculator Utils - Sprint 1")
        board_id = result.get("id")

    focalboard_tasks = [
        {
            "title": "Fix subtraction calculation error",
            "description": "Users report that subtraction gives wrong results. Priority: Medium."
        },
        {
            "title": "Handle divide by zero gracefully",
            "description": "App crashes when users divide by zero. Priority: Low."
        },
        {
            "title": "Fix even/odd number checker - URGENT",
            "description": "CRITICAL: The even number check is inverted. Priority: HIGH."
        },
        {
            "title": "Correct factorial calculations",
            "description": "Factorial function returns wrong values. Priority: Medium."
        },
    ]

    if board_id:
        for task in focalboard_tasks:
            with tracker.track("focalboard", "cards"):
                focalboard_create_card(token, board_id, task["title"], task["description"])

    tracker.print_summary()


if __name__ == "__main__":
    main()
