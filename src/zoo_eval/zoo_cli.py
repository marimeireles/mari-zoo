"""
Wrapper around The Zoo CLI for seeding and managing Zoo services.

Calls the_zoo CLI (TypeScript) under the hood instead of reimplementing APIs.
This ensures a single source of truth for Zoo service interactions.

Required environment:
- THE_ZOO_PATH: Path to the_zoo repository (default: ../the_zoo relative to zoo-eval)
- Node.js with tsx installed (for running the TypeScript CLI)
"""

import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


# =============================================================================
# Seed Tracker - Generic tracking for API operations
# =============================================================================

class SeedTracker:
    """Track success/failure of seeding operations and print summary.

    Usage:
        tracker = SeedTracker()  # Default: continue on errors
        tracker = SeedTracker(fail_fast=True)  # Stop on first error

        with tracker.track("gitea", "repos"):
            gitea_create_repo(...)
        with tracker.track("focalboard", "boards"):
            focalboard_create_board(...)
        with tracker.track("email", "emails"):
            send_email(...)

        tracker.print_summary()
        # Output:
        # Seeded Email: 1/1 emails
        # Seeded Focalboard: 1/1 boards
        # Seeded Gitea: 1/1 repos
    """

    def __init__(self, fail_fast: bool = False):
        """Initialize tracker.

        Args:
            fail_fast: If True, re-raise exceptions instead of continuing.
                       Useful for debugging seed scripts.
        """
        self._results: dict[tuple[str, str], dict[str, int]] = {}
        self._fail_fast = fail_fast

    @contextmanager
    def track(self, category: str, item_type: str):
        """Context manager to track an operation."""
        key = (category, item_type)
        if key not in self._results:
            self._results[key] = {"success": 0, "total": 0}
        self._results[key]["total"] += 1
        try:
            yield
            self._results[key]["success"] += 1
        except Exception as e:
            if self._fail_fast:
                raise  # Re-raise for debugging
            # Otherwise continue silently

    def print_summary(self):
        """Print summary in format: Seeded Gitea: 1/1 repos, 2/2 files"""
        categories: dict[str, list[str]] = {}
        for (cat, item_type), counts in self._results.items():
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f"{counts['success']}/{counts['total']} {item_type}")

        for cat, items in sorted(categories.items()):
            print(f"Seeded {cat.title()}: {', '.join(items)}")


# =============================================================================
# The Zoo CLI Wrapper
# =============================================================================

def _get_zoo_cli_path() -> str:
    """Get the path to the_zoo CLI executable."""
    # Check environment variable first
    if zoo_path := os.environ.get("THE_ZOO_PATH"):
        cli_path = Path(zoo_path) / "cli" / "bin" / "thezoo.ts"
        if cli_path.exists():
            return str(cli_path)

    # Try to find it relative to this file (sibling repo)
    this_file = Path(__file__).resolve()
    # Go up to zoo-eval root, then to parent, then to the_zoo
    zoo_eval_root = this_file.parent.parent.parent
    sibling_path = zoo_eval_root.parent / "the_zoo" / "cli" / "bin" / "thezoo.ts"
    if sibling_path.exists():
        return str(sibling_path)

    raise FileNotFoundError(
        "Could not find the_zoo CLI. Set THE_ZOO_PATH environment variable "
        "or ensure the_zoo repo is a sibling of zoo-eval."
    )


def _get_tsx_path() -> str:
    """Get the path to tsx (TypeScript runner)."""
    # Check if tsx is in PATH
    tsx = shutil.which("tsx")
    if tsx:
        return tsx

    # Check if npx is available as fallback
    npx = shutil.which("npx")
    if npx:
        return npx

    raise FileNotFoundError(
        "Could not find tsx or npx. Install tsx globally with: npm install -g tsx"
    )


def _get_zoo_instance() -> str | None:
    """Auto-detect the running Zoo instance name from Docker."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=caddy"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            # Extract project name from container name (e.g., "the_zoo-caddy-1" -> "the_zoo")
            container = result.stdout.strip().split("\n")[0]
            parts = container.rsplit("-", 2)
            if len(parts) >= 2:
                return parts[0]
    except Exception:
        pass
    return None


def _run_zoo_cli(
    *args: str,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run the_zoo CLI with the given arguments.

    Args:
        *args: CLI arguments (e.g., "gitea", "create-repo", "--name", "test")
        timeout: Command timeout in seconds
        check: If True, raise on non-zero exit code

    Returns:
        CompletedProcess with stdout/stderr
    """
    cli_path = _get_zoo_cli_path()
    tsx_path = _get_tsx_path()

    # Auto-detect instance and inject --instance flag if needed
    args_list = list(args)
    if "--instance" not in args_list:
        instance = _get_zoo_instance()
        if instance:
            # Insert --instance after the command name (e.g., "email --instance the_zoo send ...")
            if len(args_list) >= 1:
                args_list.insert(1, "--instance")
                args_list.insert(2, instance)

    # Build command
    if "npx" in tsx_path:
        cmd = [tsx_path, "tsx", cli_path] + args_list
    else:
        cmd = [tsx_path, cli_path] + args_list

    # Pass environment with ZOO_DEV=1 so the CLI can detect non-CLI instances
    env = os.environ.copy()
    env["ZOO_DEV"] = "1"

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=Path(cli_path).parent.parent.parent,  # Run from the_zoo root
        env=env,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            f"the_zoo CLI failed: {result.stderr or result.stdout}"
        )

    return result


# =============================================================================
# Gitea API (via the_zoo CLI)
# =============================================================================

def gitea_list_users(username: str = "admin", password: str = "admin123") -> list[dict]:
    """
    List all Gitea users (requires admin).

    Note: The CLI doesn't support custom auth, uses hardcoded admin credentials.
    The username/password params are kept for API compatibility but ignored.
    """
    result = _run_zoo_cli("gitea", "users")
    # Parse output - CLI outputs human-readable text, not JSON
    # For now, return empty list as the CLI doesn't support JSON output
    # TODO: Add --json flag to the_zoo CLI for machine-readable output
    return []


def gitea_create_repo(
    username: str,
    password: str,
    name: str,
    owner: Optional[str] = None,
    description: str = "",
    private: bool = False,
    auto_init: bool = True,
) -> dict:
    """
    Create a Gitea repository.

    Args:
        username: Authenticated user's username (used as owner if owner not specified)
        password: Authenticated user's password (not used - CLI uses owner's default password)
        name: Repository name
        owner: Owner (org or user name). If None, uses username.
        description: Repository description
        private: Whether the repo is private
        auto_init: Initialize with README

    Returns:
        Empty dict (CLI doesn't return JSON)
    """
    args = [
        "gitea", "create-repo",
        "--name", name,
        "--owner", owner or username,
    ]

    if description:
        args.extend(["--description", description])
    if private:
        args.append("--private")
    if not auto_init:
        args.append("--no-auto-init")

    _run_zoo_cli(*args)
    return {}


def gitea_add_file(
    username: str,
    password: str,
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str = "",
    branch: str = "main",
) -> dict:
    """
    Add or update a file in a Gitea repository.

    Args:
        username: Authenticated user's username (not used - CLI uses owner's password)
        password: Authenticated user's password (not used)
        owner: Repository owner
        repo: Repository name
        path: File path in repo
        content: File content
        message: Commit message
        branch: Target branch

    Returns:
        Empty dict (CLI doesn't return JSON)
    """
    args = [
        "gitea", "add-file",
        "--owner", owner,
        "--repo", repo,
        "--path", path,
        "--content", content,
        "--branch", branch,
    ]

    if message:
        args.extend(["--message", message])

    _run_zoo_cli(*args)
    return {}


def gitea_create_issue(
    username: str,
    password: str,
    owner: str,
    repo: str,
    title: str,
    body: str = "",
) -> dict:
    """
    Create an issue in a Gitea repository.

    Args:
        username: Authenticated user's username (not used - CLI uses owner's password)
        password: Authenticated user's password (not used)
        owner: Repository owner
        repo: Repository name
        title: Issue title
        body: Issue body

    Returns:
        Empty dict (CLI doesn't return JSON)
    """
    args = [
        "gitea", "create-issue",
        "--owner", owner,
        "--repo", repo,
        "--title", title,
    ]

    if body:
        args.extend(["--body", body])

    _run_zoo_cli(*args)
    return {}


def gitea_list_issues(
    username: str,
    password: str,
    owner: str,
    repo: str,
) -> list[dict]:
    """
    List issues in a Gitea repository.

    Note: The CLI doesn't have a list-issues command yet.
    TODO: Add to the_zoo CLI
    """
    # Not implemented in the_zoo CLI
    return []


def gitea_create_comment(
    username: str,
    password: str,
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
) -> dict:
    """
    Create a comment on a Gitea issue.

    Note: The CLI doesn't have a create-comment command yet.
    TODO: Add to the_zoo CLI
    """
    # Not implemented in the_zoo CLI
    raise NotImplementedError("gitea_create_comment not yet available in the_zoo CLI")


# =============================================================================
# Focalboard (Kanban) API (via the_zoo CLI)
# =============================================================================

def focalboard_login(username: str, password: str) -> str:
    """
    Login to Focalboard and get auth token.

    Returns:
        Auth token string (parsed from CLI output)
    """
    result = _run_zoo_cli(
        "kanban", "login",
        "--username", username,
        "--password", password,
    )

    # Parse token from output like "Token: abc123..."
    match = re.search(r"Token:\s+(\S+)", result.stdout)
    if match:
        return match.group(1)

    raise ValueError(f"Could not parse token from login output: {result.stdout}")


def focalboard_get_teams(token: str) -> list[dict]:
    """Get all teams.

    Note: The CLI doesn't expose this directly.
    """
    # Not directly available via CLI
    return []


def focalboard_list_boards(token: str, team_id: Optional[str] = None) -> list[dict]:
    """
    List all boards.

    Note: Token is ignored - CLI uses its own auth.
    """
    result = _run_zoo_cli("kanban", "boards")
    # Parse output - returns human-readable text
    return []


def focalboard_create_board(
    token: str,
    title: str,
    team_id: Optional[str] = None,
) -> dict:
    """
    Create a Focalboard board.

    Args:
        token: Auth token (ignored - CLI handles auth)
        title: Board title
        team_id: Team ID (optional - uses default)

    Returns:
        Dict with board info (parsed from CLI output)
    """
    args = ["kanban", "create-board", "--title", title]

    if team_id:
        args.extend(["--team", team_id])

    result = _run_zoo_cli(*args)

    # Try to parse board ID from output
    match = re.search(r"ID:\s+(\S+)", result.stdout)
    if match:
        return {"id": match.group(1), "title": title}

    return {"title": title}


def focalboard_create_card(
    token: str,
    board_id: str,
    title: str,
    description: str = "",
) -> dict:
    """
    Create a card on a Focalboard board.

    Args:
        token: Auth token (ignored - CLI handles auth)
        board_id: Board ID
        title: Card title
        description: Card description (not yet supported in CLI)

    Returns:
        Dict with card info
    """
    result = _run_zoo_cli(
        "kanban", "create-card",
        "--board", board_id,
        "--title", title,
    )

    # Try to parse card ID from output
    match = re.search(r"ID:\s+(\S+)", result.stdout)
    if match:
        return {"id": match.group(1), "title": title}

    return {"title": title}


def focalboard_list_cards(token: str, board_id: str, limit: int = 100) -> list[dict]:
    """
    List cards on a board.

    Note: Token is ignored - CLI handles auth.
    """
    result = _run_zoo_cli(
        "kanban", "cards",
        "--board", board_id,
        "--limit", str(limit),
    )
    return []


# =============================================================================
# Email API (via the_zoo CLI)
# =============================================================================

def send_email(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    password: str,
    html: bool = False,
) -> None:
    """
    Send an email via SMTP.

    Args:
        from_addr: Sender email address
        to_addr: Recipient email address
        subject: Email subject
        body: Email body text
        password: Sender's password
        html: Whether body is HTML

    Raises:
        RuntimeError: If email sending fails
    """
    args = [
        "email", "send",
        "--from", from_addr,
        "--to", to_addr,
        "--subject", subject,
        "--body", body,
        "--password", password,
    ]

    if html:
        args.append("--html")

    _run_zoo_cli(*args)


def send_email_with_result(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    password: str,
    html: bool = False,
    max_retries: int = 15,
    retry_delay: float = 3.0,
) -> subprocess.CompletedProcess:
    """
    Send an email and return full result (for debugging).

    Note: Retry logic is handled by the caller since CLI doesn't support retries.
    """
    import time

    args = [
        "email", "send",
        "--from", from_addr,
        "--to", to_addr,
        "--subject", subject,
        "--body", body,
        "--password", password,
    ]

    if html:
        args.append("--html")

    for attempt in range(max_retries):
        result = _run_zoo_cli(*args, check=False)
        if result.returncode == 0:
            return result
        # Retry on connection errors
        if "Connection refused" in (result.stderr or "") or "ECONNREFUSED" in (result.stderr or ""):
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
        break

    return result


def check_inbox(user: str, password: str, folder: str = "INBOX") -> Optional[int]:
    """
    Check inbox message count.

    Args:
        user: Email address
        password: Email password
        folder: Mailbox folder (default: INBOX)

    Returns:
        Number of messages in inbox, or None if check failed
    """
    result = _run_zoo_cli(
        "email", "inbox",
        "--user", user,
        "--password", password,
        "--folder", folder,
        "--limit", "0",  # Just get count
        check=False,
    )

    if result.returncode == 0 and result.stdout:
        # Parse "Messages: N" from output
        match = re.search(r"Messages:\s+(\d+)", result.stdout)
        if match:
            return int(match.group(1))

    return None
