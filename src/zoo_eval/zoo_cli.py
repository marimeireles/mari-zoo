"""
Direct interface to The Zoo services.

Uses REST APIs directly instead of shelling out to the CLI:
- Gitea: https://gitea.zoo/api/v1/...
- Focalboard: http://focalboard.zoo/api/v2/...
- Email: docker compose exec (SMTP/IMAP require container access)

All HTTP requests go through the Zoo proxy at localhost:3128.
"""

import base64
import os
import re
import subprocess
from contextlib import contextmanager
from typing import Optional

import requests

from .zoo import _get_compose_project


# =============================================================================
# Seed Tracker - Generic tracking for API operations
# =============================================================================

class SeedTracker:
    """Track success/failure of seeding operations and print summary.

    Usage:
        tracker = SeedTracker()

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

    def __init__(self):
        self._results: dict[tuple[str, str], dict[str, int]] = {}

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
        except Exception:
            pass  # Don't re-raise, allow script to continue

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
# Configuration
# =============================================================================

def _get_proxy_url() -> str:
    """Get the Zoo proxy URL."""
    port = os.environ.get("ZOO_PROXY_PORT", "3128")
    return f"http://localhost:{port}"


# =============================================================================
# HTTP Client
# =============================================================================

class ZooHTTP:
    """HTTP client for Zoo services with proxy support."""

    def __init__(self):
        self.proxy_url = _get_proxy_url()
        self.session = requests.Session()
        self.session.proxies = {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }
        self.session.verify = False  # Zoo uses self-signed certs

        # Suppress InsecureRequestWarning
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def request(
        self,
        method: str,
        url: str,
        auth: Optional[tuple[str, str]] = None,
        token: Optional[str] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        """Make an HTTP request through the Zoo proxy."""
        req_headers = headers or {}

        if token:
            req_headers["Authorization"] = f"Bearer {token}"

        return self.session.request(
            method=method,
            url=url,
            auth=auth,
            json=json,
            headers=req_headers,
        )


# Singleton HTTP client
_http: Optional[ZooHTTP] = None


def _get_http() -> ZooHTTP:
    global _http
    if _http is None:
        _http = ZooHTTP()
    return _http


# =============================================================================
# Gitea API
# =============================================================================

GITEA_BASE = "https://gitea.zoo/api/v1"


def gitea_list_users(username: str, password: str) -> list[dict]:
    """
    List all Gitea users (requires admin).

    Args:
        username: Admin username
        password: Admin password

    Returns:
        List of user data
    """
    http = _get_http()
    resp = http.request("GET", f"{GITEA_BASE}/admin/users", auth=(username, password))
    resp.raise_for_status()
    return resp.json()


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
        username: Authenticated user's username
        password: Authenticated user's password
        name: Repository name
        owner: Owner (org name). If None, creates under authenticated user.
        description: Repository description
        private: Whether the repo is private
        auto_init: Initialize with README

    Returns:
        Created repository data
    """
    http = _get_http()
    auth = (username, password)

    if owner:
        # Check if owner is an org
        org_resp = http.request("GET", f"{GITEA_BASE}/orgs/{owner}", auth=auth)
        if org_resp.status_code == 200:
            endpoint = f"{GITEA_BASE}/orgs/{owner}/repos"
        else:
            raise ValueError(f"Organization '{owner}' not found")
    else:
        endpoint = f"{GITEA_BASE}/user/repos"

    resp = http.request(
        "POST",
        endpoint,
        auth=auth,
        json={
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init,
        },
    )
    resp.raise_for_status()
    return resp.json()


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
        username: Authenticated user's username
        password: Authenticated user's password
        owner: Repository owner
        repo: Repository name
        path: File path in repo
        content: File content (will be base64 encoded)
        message: Commit message
        branch: Target branch

    Returns:
        API response with commit info
    """
    http = _get_http()
    encoded_content = base64.b64encode(content.encode()).decode()

    resp = http.request(
        "POST",
        f"{GITEA_BASE}/repos/{owner}/{repo}/contents/{path}",
        auth=(username, password),
        json={
            "content": encoded_content,
            "message": message or f"Add {path}",
            "branch": branch,
        },
    )
    resp.raise_for_status()
    return resp.json()


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
        username: Authenticated user's username
        password: Authenticated user's password
        owner: Repository owner
        repo: Repository name
        title: Issue title
        body: Issue body

    Returns:
        Created issue data
    """
    http = _get_http()
    resp = http.request(
        "POST",
        f"{GITEA_BASE}/repos/{owner}/{repo}/issues",
        auth=(username, password),
        json={"title": title, "body": body},
    )
    resp.raise_for_status()
    return resp.json()


# =============================================================================
# Focalboard (Kanban) API
# =============================================================================

FOCALBOARD_BASE = "http://focalboard.zoo/api/v2"


def focalboard_login(username: str, password: str) -> str:
    """
    Login to Focalboard and get auth token.

    Args:
        username: Focalboard username
        password: Focalboard password

    Returns:
        Auth token string
    """
    http = _get_http()
    resp = http.request(
        "POST",
        f"{FOCALBOARD_BASE}/login",
        json={"type": "normal", "username": username, "password": password},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    data = resp.json()

    if "token" not in data:
        raise ValueError(f"Login failed: {data}")

    return data["token"]


def focalboard_get_teams(token: str) -> list[dict]:
    """Get all teams."""
    http = _get_http()
    resp = http.request(
        "GET",
        f"{FOCALBOARD_BASE}/teams",
        token=token,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    return resp.json()


def focalboard_list_boards(token: str, team_id: Optional[str] = None) -> list[dict]:
    """
    List all boards.

    Args:
        token: Auth token from focalboard_login
        team_id: Team ID (auto-detected if not provided)

    Returns:
        List of board data
    """
    http = _get_http()

    if not team_id:
        teams = focalboard_get_teams(token)
        if not teams:
            return []
        team_id = teams[0]["id"]

    resp = http.request(
        "GET",
        f"{FOCALBOARD_BASE}/teams/{team_id}/boards",
        token=token,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    return resp.json()


def focalboard_create_board(
    token: str,
    title: str,
    team_id: Optional[str] = None,
) -> dict:
    """
    Create a Focalboard board.

    Args:
        token: Auth token
        title: Board title
        team_id: Team ID (auto-detected if not provided)

    Returns:
        Created board data
    """
    http = _get_http()

    if not team_id:
        teams = focalboard_get_teams(token)
        if not teams:
            raise ValueError("No teams found")
        team_id = teams[0]["id"]

    resp = http.request(
        "POST",
        f"{FOCALBOARD_BASE}/boards",
        token=token,
        headers={"X-Requested-With": "XMLHttpRequest"},
        json={
            "title": title,
            "teamId": team_id,
            "type": "O",
            "showDescription": True,
            "isTemplate": False,
        },
    )
    resp.raise_for_status()
    return resp.json()


def focalboard_create_card(
    token: str,
    board_id: str,
    title: str,
    description: str = "",
) -> dict:
    """
    Create a card on a Focalboard board.

    Args:
        token: Auth token
        board_id: Board ID
        title: Card title
        description: Card description

    Returns:
        Created card data
    """
    http = _get_http()
    resp = http.request(
        "POST",
        f"{FOCALBOARD_BASE}/boards/{board_id}/cards",
        token=token,
        headers={"X-Requested-With": "XMLHttpRequest"},
        json={
            "title": title,
            "contentOrder": [],
            "properties": {},
        },
    )
    resp.raise_for_status()
    return resp.json()


def focalboard_list_cards(token: str, board_id: str, limit: int = 100) -> list[dict]:
    """
    List cards on a board.

    Args:
        token: Auth token
        board_id: Board ID
        limit: Max cards to return

    Returns:
        List of card data
    """
    http = _get_http()
    resp = http.request(
        "GET",
        f"{FOCALBOARD_BASE}/boards/{board_id}/cards?per_page={limit}",
        token=token,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    return resp.json()


# =============================================================================
# Email (via docker compose exec - SMTP/IMAP require container access)
# =============================================================================

def _docker_compose_exec(
    service: str,
    command: list[str],
    project: Optional[str] = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a command inside a docker compose service."""
    project = project or _get_compose_project()
    cmd = ["docker", "compose", "-p", project, "exec", "-T", service] + command
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def send_email(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    password: str,
    html: bool = False,
) -> None:
    """
    Send an email via SMTP (using swaks inside stalwart container).

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
    result = send_email_with_result(from_addr, to_addr, subject, body, password, html)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to send email: {result.stderr}")


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

    Args:
        from_addr: Sender email address
        to_addr: Recipient email address
        subject: Email subject
        body: Email body text
        password: Sender's password
        html: Whether body is HTML
        max_retries: Number of retries if connection fails
        retry_delay: Seconds to wait between retries

    Returns:
        CompletedProcess with returncode, stdout, stderr
    """
    import time

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

    for attempt in range(max_retries):
        result = _docker_compose_exec("stalwart", swaks_args)
        if result.returncode == 0:
            return result
        # Retry on connection refused (service still starting)
        if "Connection refused" in (result.stderr or ""):
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
        # Other errors - don't retry
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
    curl_cmd = [
        "curl", "-s",
        "-u", f"{user}:{password}",
        f"imap://localhost/{folder}",
        "--request", f"EXAMINE {folder}",
    ]

    result = _docker_compose_exec("stalwart", curl_cmd)

    if result.returncode == 0 and result.stdout:
        match = re.search(r"\* (\d+) EXISTS", result.stdout)
        if match:
            return int(match.group(1))

    return None
