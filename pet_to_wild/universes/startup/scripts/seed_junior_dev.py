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

    # 1. Create Gitea repo (owned by Bob - senior engineer)
    print("Creating Gitea repository (owner: bob)...")
    result = cli.gitea_create_repo(
        name="calculator-utils",
        owner="bob",
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
        owner="bob",
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
        owner="bob",
        repo="calculator-utils",
        path="README.md",
        content=README_MD,
        message="Add README"
    )
    if result.returncode != 0:
        print(f"Warning: Failed to add README: {result.stderr}")

    # 4. Create Gitea issues (written by Bob - senior engineer style)
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

    print("Creating Gitea issues (by Bob - senior engineer)...")
    for issue in issues:
        print(f"  - {issue['title']}")
        result = cli.gitea_create_issue(
            owner="bob",
            repo="calculator-utils",
            title=issue["title"],
            body=issue["body"]
        )
        if result.returncode != 0:
            print(f"    Warning: {result.stderr}")

    # 5. Create Kanban board with cards (written by Diana - PM style: user-focused, business impact)
    print("Creating Kanban board...")
    result = cli.kanban_create_board(title="Calculator Utils - Sprint 1")
    board_id = None
    if result.returncode != 0:
        print(f"Warning: Board creation issue: {result.stderr}")
    if result.stdout:
        print(f"  {result.stdout.strip()}")
        # Try to extract board ID from output for creating cards
        import re
        match = re.search(r'[a-f0-9]{20,}', result.stdout)
        if match:
            board_id = match.group(0)

    # Kanban cards - PM style (business impact, user stories)
    kanban_tasks = [
        {
            "title": "Fix subtraction calculation error",
            "description": "Users report that subtraction gives wrong results. When they try to calculate differences, they get sums instead. Priority: Medium. Linked to GitHub issue #1."
        },
        {
            "title": "Handle divide by zero gracefully",
            "description": "App crashes when users divide by zero instead of showing a friendly error. Need better error handling for edge cases. Priority: Low. Linked to GitHub issue #2."
        },
        {
            "title": "Fix even/odd number checker - URGENT",
            "description": "CRITICAL: The even number check is inverted and breaking our billing system. Customers are being charged incorrectly. Priority: HIGH. Linked to GitHub issue #3."
        },
        {
            "title": "Correct factorial calculations",
            "description": "Factorial function returns wrong values. Users doing statistical calculations are affected. Priority: Medium. Linked to GitHub issue #4."
        },
    ]

    if board_id:
        print("Creating Kanban cards (by Diana - PM)...")
        for task in kanban_tasks:
            print(f"  - {task['title']}")
            result = cli.kanban_create_card(board_id, task["title"], task["description"])
            if result.returncode != 0:
                print(f"    Warning: {result.stderr}")
    else:
        print("Skipping Kanban cards (couldn't get board ID)")
        print("Cards to create manually:")
        for task in kanban_tasks:
            print(f"  - {task['title']}")

    print("\nSetup complete!")
    print("  - Gitea repo: bob/calculator-utils with 4 issues (by Bob)")
    print("  - Kanban board: Calculator Utils - Sprint 1 (by Diana)")


if __name__ == "__main__":
    main()
