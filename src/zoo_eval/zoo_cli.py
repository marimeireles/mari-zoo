"""
Direct API implementations for Zoo services.

Uses httpx for HTTP APIs (Gitea, Focalboard) and smtplib/imaplib for email.
No external dependencies on the_zoo CLI - everything runs natively in Python.
"""

import base64
import os
import subprocess
from contextlib import contextmanager
from typing import Any, Optional


# =============================================================================
# Configuration
# =============================================================================

def _get_proxy_port() -> int:
    """Get the Zoo proxy port from environment or default."""
    return int(os.environ.get("ZOO_PROXY_PORT", "3128"))


def _get_http_client():
    """Get an httpx client configured for the Zoo proxy."""
    import httpx

    proxy_port = _get_proxy_port()
    proxy_url = f"http://localhost:{proxy_port}"

    return httpx.Client(
        proxy=proxy_url,
        verify=False,  # Zoo uses self-signed certs
        timeout=30.0,
    )


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
# Gitea API (Direct HTTP)
# =============================================================================

def _gitea_request(
    endpoint: str,
    method: str = "GET",
    body: Optional[dict] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> Any:
    """Make an authenticated request to Gitea API."""
    with _get_http_client() as client:
        url = f"https://gitea.zoo{endpoint}"
        auth = (username, password) if username and password else None

        response = client.request(
            method=method,
            url=url,
            json=body,
            auth=auth,
        )

        if response.status_code >= 400:
            # Don't fail on 409 Conflict (already exists)
            if response.status_code == 409:
                return {"already_exists": True}
            raise RuntimeError(f"Gitea API error {response.status_code}: {response.text}")

        if response.text:
            try:
                return response.json()
            except Exception:
                return response.text
        return {}


def gitea_list_users(username: str = "admin", password: str = "admin123") -> list[dict]:
    """List all Gitea users (requires admin)."""
    response = _gitea_request(
        "/api/v1/admin/users",
        username=username,
        password=password,
    )
    return response if isinstance(response, list) else []


def gitea_create_repo(
    username: str,
    password: str,
    name: str,
    owner: Optional[str] = None,
    description: str = "",
    private: bool = False,
    auto_init: bool = True,
) -> dict:
    """Create a Gitea repository."""
    actual_owner = owner or username

    # Check if owner is an org
    endpoint = "/api/v1/user/repos"
    auth_user, auth_pass = username, password

    try:
        org_check = _gitea_request(
            f"/api/v1/orgs/{actual_owner}",
            username="admin",
            password="admin123",
        )
        if org_check.get("id"):
            endpoint = f"/api/v1/orgs/{actual_owner}/repos"
            auth_user, auth_pass = "admin", "admin123"
    except Exception:
        pass  # Not an org, use user endpoint

    return _gitea_request(
        endpoint,
        method="POST",
        body={
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init,
        },
        username=auth_user,
        password=auth_pass,
    )


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
    """Add or update a file in a Gitea repository."""
    # Content must be base64 encoded
    content_b64 = base64.b64encode(content.encode()).decode()

    return _gitea_request(
        f"/api/v1/repos/{owner}/{repo}/contents/{path}",
        method="POST",
        body={
            "content": content_b64,
            "message": message or f"Add {path}",
            "branch": branch,
        },
        username=username,
        password=password,
    )


def gitea_create_issue(
    username: str,
    password: str,
    owner: str,
    repo: str,
    title: str,
    body: str = "",
) -> dict:
    """Create an issue in a Gitea repository."""
    return _gitea_request(
        f"/api/v1/repos/{owner}/{repo}/issues",
        method="POST",
        body={
            "title": title,
            "body": body,
        },
        username=username,
        password=password,
    )


def gitea_list_issues(
    username: str,
    password: str,
    owner: str,
    repo: str,
) -> list[dict]:
    """List issues in a Gitea repository."""
    response = _gitea_request(
        f"/api/v1/repos/{owner}/{repo}/issues",
        username=username,
        password=password,
    )
    return response if isinstance(response, list) else []


def gitea_create_comment(
    username: str,
    password: str,
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
) -> dict:
    """Create a comment on a Gitea issue."""
    return _gitea_request(
        f"/api/v1/repos/{owner}/{repo}/issues/{issue_number}/comments",
        method="POST",
        body={"body": body},
        username=username,
        password=password,
    )


# =============================================================================
# Focalboard (Kanban) API (Direct HTTP)
# =============================================================================

def _focalboard_request(
    endpoint: str,
    method: str = "GET",
    body: Optional[dict] = None,
    token: Optional[str] = None,
) -> Any:
    """Make a request to Focalboard API."""
    with _get_http_client() as client:
        url = f"http://focalboard.zoo{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = client.request(
            method=method,
            url=url,
            json=body,
            headers=headers,
        )

        if response.status_code >= 400:
            raise RuntimeError(f"Focalboard API error {response.status_code}: {response.text}")

        if response.text:
            try:
                return response.json()
            except Exception:
                return response.text
        return {}


def focalboard_login(username: str, password: str) -> str:
    """Login to Focalboard and get auth token."""
    response = _focalboard_request(
        "/api/v2/login",
        method="POST",
        body={
            "type": "normal",
            "username": username,
            "password": password,
        },
    )

    if response.get("token"):
        return response["token"]

    raise ValueError(f"Login failed: {response}")


def focalboard_get_teams(token: str) -> list[dict]:
    """Get all teams."""
    response = _focalboard_request("/api/v2/teams", token=token)
    return response if isinstance(response, list) else []


def focalboard_list_boards(token: str, team_id: Optional[str] = None) -> list[dict]:
    """List all boards."""
    # Get team ID if not provided
    if not team_id:
        teams = focalboard_get_teams(token)
        if teams:
            team_id = teams[0].get("id")

    if not team_id:
        return []

    response = _focalboard_request(f"/api/v2/teams/{team_id}/boards", token=token)
    return response if isinstance(response, list) else []


def focalboard_create_board(
    token: str,
    title: str,
    team_id: Optional[str] = None,
) -> dict:
    """Create a Focalboard board."""
    # Get team ID if not provided
    if not team_id:
        teams = focalboard_get_teams(token)
        if teams:
            team_id = teams[0].get("id")

    if not team_id:
        raise ValueError("No team ID available")

    return _focalboard_request(
        "/api/v2/boards",
        method="POST",
        body={
            "title": title,
            "teamId": team_id,
            "type": "O",  # Open board
        },
        token=token,
    )


def focalboard_create_card(
    token: str,
    board_id: str,
    title: str,
    description: str = "",
) -> dict:
    """Create a card on a Focalboard board."""
    return _focalboard_request(
        "/api/v2/boards/" + board_id + "/blocks",
        method="POST",
        body=[{
            "type": "card",
            "title": title,
            "boardId": board_id,
            "fields": {
                "properties": {},
                "contentOrder": [],
            },
        }],
        token=token,
    )


def focalboard_list_cards(token: str, board_id: str, limit: int = 100) -> list[dict]:
    """List cards on a board."""
    response = _focalboard_request(
        f"/api/v2/boards/{board_id}/blocks?type=card",
        token=token,
    )
    result = response if isinstance(response, list) else []
    return result[:limit]


# =============================================================================
# Email API (Direct SMTP/IMAP)
# =============================================================================

def _get_docker_project() -> str | None:
    """Auto-detect the running Zoo Docker Compose project name."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=stalwart"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            container = result.stdout.strip().split("\n")[0]
            parts = container.rsplit("-", 2)
            if len(parts) >= 2:
                return parts[0]
    except Exception:
        pass
    return None


def send_email(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    password: str,
    html: bool = False,
) -> None:
    """Send an email via SMTP using docker exec + swaks.

    Uses swaks inside the stalwart container for reliable delivery.
    """
    project = _get_docker_project()
    if not project:
        raise RuntimeError("Could not detect Zoo Docker project")

    # Build swaks command
    swaks_args = [
        "swaks",
        "--to", to_addr,
        "--from", from_addr,
        "--server", "stalwart:587",
        "--auth-user", from_addr,
        "--auth-password", password,
        "--header", f"Subject: {subject}",
        "--tls",
    ]

    if html:
        swaks_args.extend(["--add-header", "Content-Type: text/html"])

    swaks_args.extend(["--body", body])

    # Run via docker exec
    result = subprocess.run(
        ["docker", "compose", "-p", project, "exec", "-T", "stalwart"] + swaks_args,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to send email: {result.stderr or result.stdout}")


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
    """Send an email and return full result (for debugging)."""
    import time

    project = _get_docker_project()
    if not project:
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Could not detect Zoo Docker project",
        )

    swaks_args = [
        "swaks",
        "--to", to_addr,
        "--from", from_addr,
        "--server", "stalwart:587",
        "--auth-user", from_addr,
        "--auth-password", password,
        "--header", f"Subject: {subject}",
        "--tls",
    ]

    if html:
        swaks_args.extend(["--add-header", "Content-Type: text/html"])

    swaks_args.extend(["--body", body])

    cmd = ["docker", "compose", "-p", project, "exec", "-T", "stalwart"] + swaks_args

    for attempt in range(max_retries):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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
    """Check inbox message count using docker exec + curl."""
    project = _get_docker_project()
    if not project:
        return None

    try:
        cmd = [
            "docker", "compose", "-p", project, "exec", "-T", "stalwart",
            "curl", "-s", "-u", f"{user}:{password}",
            f"imap://localhost/{folder}",
            "--request", f"EXAMINE {folder}",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            import re
            match = re.search(r"\* (\d+) EXISTS", result.stdout)
            if match:
                return int(match.group(1))
    except Exception:
        pass

    return None
