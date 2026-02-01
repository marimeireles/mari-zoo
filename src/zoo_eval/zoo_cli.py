"""
Direct API implementations for Zoo services.

Uses httpx for HTTP APIs (Gitea, Focalboard) and smtplib/imaplib for email.
No external dependencies on the_zoo CLI - everything runs natively in Python.
"""

from __future__ import annotations

import base64
import os
import subprocess
from contextlib import contextmanager
from typing import Any

from .helpers import ZOO_ADMIN_USER, ZOO_ADMIN_PASS
from .zoo import _get_compose_project


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
# Auth.zoo API (Direct HTTP)
# =============================================================================

AUTH_ZOO_API_KEY = "zoo-seed-api-key"


def _auth_request(
    endpoint: str,
    method: str = "GET",
    body: dict | None = None,
) -> Any:
    """Make a request to Auth.zoo API."""
    with _get_http_client() as client:
        url = f"https://auth.zoo{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": AUTH_ZOO_API_KEY,
        }

        response = client.request(
            method=method,
            url=url,
            json=body,
            headers=headers,
        )

        if response.status_code >= 400:
            if response.status_code == 409:
                return {"already_exists": True}
            raise RuntimeError(f"Auth.zoo API error {response.status_code}: {response.text}")

        if response.text:
            try:
                return response.json()
            except Exception:
                return response.text
        return {}


def auth_create_user(
    username: str,
    email: str,
    name: str,
    password: str,
) -> dict:
    """Create a user in auth.zoo.

    Args:
        username: User's username (for login)
        email: User's email address
        name: User's full name
        password: User's password

    Returns:
        Dict with user info or already_exists flag
    """
    return _auth_request(
        "/api/users",
        method="POST",
        body={
            "username": username,
            "email": email,
            "name": name,
            "password": password,
        },
    )


def auth_list_users() -> list[dict]:
    """List all users in auth.zoo.

    Returns:
        List of user dicts
    """
    response = _auth_request("/api/users")
    return response if isinstance(response, list) else []


# =============================================================================
# Gitea API (Direct HTTP)
# =============================================================================

def _gitea_request(
    endpoint: str,
    method: str = "GET",
    body: dict | None = None,
    username: str | None = None,
    password: str | None = None,
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


def gitea_list_users(username: str = ZOO_ADMIN_USER, password: str = ZOO_ADMIN_PASS) -> list[dict]:
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
    owner: str | None = None,
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
            username=ZOO_ADMIN_USER,
            password=ZOO_ADMIN_PASS,
        )
        if org_check.get("id"):
            endpoint = f"/api/v1/orgs/{actual_owner}/repos"
            auth_user, auth_pass = ZOO_ADMIN_USER, ZOO_ADMIN_PASS
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
    body: dict | None = None,
    token: str | None = None,
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


def _get_team_id(token: str, team_id: str | None = None) -> str | None:
    """Get team ID, looking up from API if not provided."""
    if team_id:
        return team_id
    teams = focalboard_get_teams(token)
    return teams[0].get("id") if teams else None


def focalboard_list_boards(token: str, team_id: str | None = None) -> list[dict]:
    """List all boards."""
    team_id = _get_team_id(token, team_id)
    if not team_id:
        return []

    response = _focalboard_request(f"/api/v2/teams/{team_id}/boards", token=token)
    return response if isinstance(response, list) else []


def focalboard_create_board(
    token: str,
    title: str,
    team_id: str | None = None,
) -> dict:
    """Create a Focalboard board."""
    team_id = _get_team_id(token, team_id)
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

def _build_swaks_args(
    from_addr: str, to_addr: str, subject: str, body: str, password: str, html: bool = False
) -> list[str]:
    """Build swaks command arguments for sending email."""
    args = [
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
        args.extend(["--add-header", "Content-Type: text/html"])
    args.extend(["--body", body])
    return args


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
    project = _get_compose_project()
    swaks_args = _build_swaks_args(from_addr, to_addr, subject, body, password, html)

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

    project = _get_compose_project()
    swaks_args = _build_swaks_args(from_addr, to_addr, subject, body, password, html)
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


def check_inbox(user: str, password: str, folder: str = "INBOX") -> int | None:
    """Check inbox message count using docker exec + curl."""
    project = _get_compose_project()

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


# =============================================================================
# Postmill (Reddit-like) API (Direct HTTP)
# =============================================================================

class PostmillSession:
    """Authenticated session for Postmill API calls.

    Postmill uses session cookies and CSRF tokens for authentication.
    This class manages the session state across multiple requests.
    """

    def __init__(self, username: str, password: str):
        import httpx

        self.username = username
        self.password = password
        self._csrf_token: str | None = None
        self._logged_in = False

        proxy_port = _get_proxy_port()
        proxy_url = f"http://localhost:{proxy_port}"

        # Persistent client that maintains cookies across requests
        self._client = httpx.Client(
            proxy=proxy_url,
            verify=False,
            timeout=30.0,
            follow_redirects=True,
        )

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        """Make a request to Postmill."""
        url = f"http://postmill.zoo{endpoint}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Zoo Seed Script)",
        }

        if method == "POST" and self._csrf_token:
            if data is None:
                data = {}
            data["_csrf_token"] = self._csrf_token

        response = self._client.request(
            method=method,
            url=url,
            headers=headers,
            data=data,
            json=json_body,
        )

        return response

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def _extract_csrf_token(self, html: str) -> str | None:
        """Extract CSRF token from HTML page."""
        import re
        # Look for hidden input with name="_csrf_token" or "_token"
        match = re.search(r'name=["\']_csrf_token["\'][^>]*value=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']_csrf_token["\']', html)
        if match:
            return match.group(1)
        match = re.search(r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        return None

    def login(self) -> bool:
        """Login to Postmill and establish session."""
        # Get login page to extract CSRF token
        response = self._request("/login")
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get login page: {response.status_code}")

        self._csrf_token = self._extract_csrf_token(response.text)
        if not self._csrf_token:
            raise RuntimeError("Could not find CSRF token on login page")

        # Submit login form to /login_check endpoint
        response = self._request(
            "/login_check",
            method="POST",
            data={
                "_username": self.username,
                "_password": self.password,
                "_remember_me": "on",
            },
        )

        # Check if login succeeded (should redirect to home or show username)
        self._logged_in = self.username.lower() in response.text.lower()
        return self._logged_in

    def get_submissions(self, forum: str = "all", sort: str = "new", limit: int = 25) -> list[dict]:
        """Get list of submissions from a forum."""
        response = self._request(f"/f/{forum}/{sort}")
        if response.status_code != 200:
            return []

        # Parse submission IDs and titles from HTML
        import re
        submissions = []
        # Look for submission links: /f/{forum}/{id}/-/{slug}
        pattern = r'href=["\']/f/([^/]+)/(\d+)/-/([^"\']+)["\'][^>]*>([^<]+)</a>'
        matches = re.findall(pattern, response.text)
        for forum_name, sub_id, slug, title in matches[:limit]:
            submissions.append({
                "id": int(sub_id),
                "forum": forum_name,
                "slug": slug,
                "title": title.strip(),
            })
        return submissions

    def get_submission(self, submission_id: int) -> dict | None:
        """Get a single submission by ID."""
        # We need to find the submission URL first
        submissions = self.get_submissions(limit=50)
        for sub in submissions:
            if sub["id"] == submission_id:
                response = self._request(f"/f/{sub['forum']}/{sub['id']}/-/{sub['slug']}")
                if response.status_code == 200:
                    sub["html"] = response.text
                    # Extract CSRF token for commenting
                    self._csrf_token = self._extract_csrf_token(response.text)
                return sub
        return None

    def create_comment(
        self,
        submission_id: int,
        body: str,
        parent_id: int | None = None,
    ) -> dict:
        """Create a comment on a submission."""
        if not self._logged_in:
            self.login()

        # Get the submission page to get CSRF token and form action
        submission = self.get_submission(submission_id)
        if not submission:
            raise RuntimeError(f"Submission {submission_id} not found")

        # Post comment
        endpoint = f"/f/{submission['forum']}/{submission_id}/-/{submission['slug']}/comment"
        data = {
            "comment[body]": body,
        }
        if parent_id:
            data["comment[parent]"] = str(parent_id)

        response = self._request(endpoint, method="POST", data=data)

        if response.status_code >= 400:
            raise RuntimeError(f"Failed to create comment: {response.status_code}")

        return {"success": True, "submission_id": submission_id}

    def create_forum(
        self,
        name: str,
        title: str,
        description: str = "",
        sidebar: str = "",
    ) -> dict:
        """Create a new forum.

        Args:
            name: Forum URL name (lowercase, no spaces)
            title: Display title for the forum
            description: Short description
            sidebar: Sidebar content (markdown)

        Returns:
            Dict with success status and forum name
        """
        if not self._logged_in:
            self.login()

        # Get the create forum page to get CSRF token
        response = self._request("/create_forum")
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get create forum page: {response.status_code}")

        self._csrf_token = self._extract_csrf_token(response.text)
        if not self._csrf_token:
            raise RuntimeError("Could not find CSRF token on create forum page")

        # Submit the form
        data = {
            "create_forum[name]": name,
            "create_forum[title]": title,
            "create_forum[description]": description,
            "create_forum[sidebar]": sidebar,
        }

        response = self._request("/create_forum", method="POST", data=data)

        # Check if forum was created (redirect to forum page or shows forum)
        if response.status_code >= 400:
            raise RuntimeError(f"Failed to create forum: {response.status_code}")

        # Check if we got redirected to the new forum
        if f"/f/{name}" in str(response.url) or name.lower() in response.text.lower():
            return {"success": True, "name": name, "title": title}

        # Check for error messages
        if "already" in response.text.lower() or "exists" in response.text.lower():
            return {"success": True, "name": name, "already_exists": True}

        return {"success": True, "name": name}

    def create_submission(
        self,
        forum: str,
        title: str,
        body: str = "",
        url: str = "",
    ) -> dict:
        """Create a new submission/post in a forum.

        Args:
            forum: Forum name to post in
            title: Submission title
            body: Text body (for text submissions)
            url: URL (for link submissions) - if provided, body is ignored

        Returns:
            Dict with success status and submission info
        """
        if not self._logged_in:
            self.login()

        # Determine submission type
        is_link = bool(url)
        submit_type = "link" if is_link else "text"

        # Get the submit page to get CSRF token
        submit_url = f"/f/{forum}/submit/{submit_type}"
        response = self._request(submit_url)
        if response.status_code != 200:
            # Try alternate URL format
            submit_url = f"/submit/{submit_type}?forum={forum}"
            response = self._request(submit_url)
            if response.status_code != 200:
                raise RuntimeError(f"Failed to get submit page: {response.status_code}")

        self._csrf_token = self._extract_csrf_token(response.text)
        if not self._csrf_token:
            raise RuntimeError("Could not find CSRF token on submit page")

        # Submit the form
        if is_link:
            data = {
                "submission[title]": title,
                "submission[url]": url,
                "submission[forum]": forum,
            }
        else:
            data = {
                "submission[title]": title,
                "submission[body]": body,
                "submission[forum]": forum,
            }

        response = self._request(submit_url, method="POST", data=data)

        if response.status_code >= 400:
            raise RuntimeError(f"Failed to create submission: {response.status_code}")

        # Try to extract submission ID from redirect URL
        import re
        match = re.search(r'/f/[^/]+/(\d+)/', str(response.url))
        submission_id = int(match.group(1)) if match else None

        return {
            "success": True,
            "forum": forum,
            "title": title,
            "id": submission_id,
        }


def postmill_login(username: str, password: str) -> PostmillSession:
    """Login to Postmill and return authenticated session.

    Args:
        username: Postmill username
        password: Postmill password

    Returns:
        PostmillSession object for making authenticated requests
    """
    session = PostmillSession(username, password)
    if not session.login():
        raise RuntimeError(f"Failed to login to Postmill as {username}")
    return session


def postmill_list_submissions(
    session: PostmillSession,
    forum: str = "all",
    sort: str = "new",
    limit: int = 25,
) -> list[dict]:
    """List submissions from a Postmill forum.

    Args:
        session: Authenticated PostmillSession
        forum: Forum name (default "all" for all forums)
        sort: Sort order ("new", "hot", "top", etc.)
        limit: Maximum number of submissions to return

    Returns:
        List of submission dicts with id, forum, slug, title
    """
    return session.get_submissions(forum=forum, sort=sort, limit=limit)


def postmill_create_comment(
    session: PostmillSession,
    submission_id: int,
    body: str,
    parent_id: int | None = None,
) -> dict:
    """Create a comment on a Postmill submission.

    Args:
        session: Authenticated PostmillSession
        submission_id: ID of the submission to comment on
        body: Comment text (supports markdown)
        parent_id: Optional parent comment ID for replies

    Returns:
        Dict with success status
    """
    return session.create_comment(submission_id, body, parent_id)


def postmill_create_forum(
    session: PostmillSession,
    name: str,
    title: str,
    description: str = "",
    sidebar: str = "",
) -> dict:
    """Create a new forum in Postmill.

    Args:
        session: Authenticated PostmillSession
        name: Forum URL name (lowercase, no spaces, e.g., "testing")
        title: Display title for the forum
        description: Short description of the forum
        sidebar: Sidebar content (supports markdown)

    Returns:
        Dict with success status and forum name
    """
    return session.create_forum(name, title, description, sidebar)


def postmill_create_submission(
    session: PostmillSession,
    forum: str,
    title: str,
    body: str = "",
    url: str = "",
) -> dict:
    """Create a new submission/post in a Postmill forum.

    Args:
        session: Authenticated PostmillSession
        forum: Forum name to post in
        title: Submission title
        body: Text body (for text submissions)
        url: URL (for link submissions) - if provided, creates a link post

    Returns:
        Dict with success status and submission info including ID if available
    """
    return session.create_submission(forum, title, body, url)
