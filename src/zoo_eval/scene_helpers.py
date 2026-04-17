"""Shared helper functions for startup-universe scene scripts.

Every helper uses the Zoo squid proxy (via zoo_cli._get_http_client) so that
scripts can reach the .zoo hostnames from inside the compose network as well
as from the host.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from zoo_eval.auth import get_credential
from zoo_eval.zoo_cli import _get_http_client


# ---------------------------------------------------------------------------
# Gitea: branch, pull request, commit status, tag, wiki, collaborator
# ---------------------------------------------------------------------------

GITEA_BASE = "https://gitea.zoo/api/v1"


def _gitea_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def gitea_create_branch(
    username: str, password: str, owner: str, repo: str, branch: str, from_branch: str = "main"
) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{GITEA_BASE}/repos/{owner}/{repo}/branches",
            headers=_gitea_auth(username, password),
            json={"new_branch_name": branch, "old_branch_name": from_branch},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"gitea_create_branch {branch} failed: {r.status_code} {r.text[:200]}")
        return r.json()


def gitea_create_pull_request(
    username: str,
    password: str,
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{GITEA_BASE}/repos/{owner}/{repo}/pulls",
            headers=_gitea_auth(username, password),
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"gitea PR failed: {r.status_code} {r.text[:300]}")
        return r.json()


def gitea_set_commit_status(
    username: str,
    password: str,
    owner: str,
    repo: str,
    sha: str,
    state: str,
    context: str = "ci/build",
    description: str = "",
    target_url: str = "",
) -> dict:
    """state in {pending, success, error, failure, warning}"""
    with _get_http_client() as c:
        r = c.post(
            f"{GITEA_BASE}/repos/{owner}/{repo}/statuses/{sha}",
            headers=_gitea_auth(username, password),
            json={
                "state": state,
                "context": context,
                "description": description,
                "target_url": target_url,
            },
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"gitea status failed: {r.status_code} {r.text[:200]}")
        return r.json()


def gitea_get_branch(
    username: str, password: str, owner: str, repo: str, branch: str
) -> dict | None:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/branches/{branch}",
            headers=_gitea_auth(username, password),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def gitea_list_commits(
    username: str, password: str, owner: str, repo: str, limit: int = 20, sha: str | None = None
) -> list[dict]:
    params: dict[str, Any] = {"limit": limit}
    if sha:
        params["sha"] = sha
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/commits",
            headers=_gitea_auth(username, password),
            params=params,
        )
        r.raise_for_status()
        return r.json()


def gitea_create_tag(
    username: str, password: str, owner: str, repo: str, tag: str, target: str = "main", message: str = ""
) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{GITEA_BASE}/repos/{owner}/{repo}/tags",
            headers=_gitea_auth(username, password),
            json={"tag_name": tag, "target": target, "message": message},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"gitea tag failed: {r.status_code} {r.text[:200]}")
        return r.json()


def gitea_list_tags(
    username: str, password: str, owner: str, repo: str
) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/tags",
            headers=_gitea_auth(username, password),
        )
        r.raise_for_status()
        return r.json()


def gitea_add_collaborator(
    username: str,
    password: str,
    owner: str,
    repo: str,
    collaborator: str,
    permission: str = "read",
) -> None:
    with _get_http_client() as c:
        r = c.put(
            f"{GITEA_BASE}/repos/{owner}/{repo}/collaborators/{collaborator}",
            headers=_gitea_auth(username, password),
            json={"permission": permission},
        )
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"gitea add collab failed: {r.status_code} {r.text[:200]}")


def gitea_create_wiki_page(
    username: str,
    password: str,
    owner: str,
    repo: str,
    title: str,
    content_base64: str,
    message: str = "seed wiki page",
) -> dict:
    """Create a wiki page. Gitea API wants content as base64."""
    with _get_http_client() as c:
        r = c.post(
            f"{GITEA_BASE}/repos/{owner}/{repo}/wiki/new",
            headers=_gitea_auth(username, password),
            json={
                "title": title,
                "content_base64": content_base64,
                "message": message,
            },
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"gitea wiki failed: {r.status_code} {r.text[:300]}")
        return r.json()


def gitea_wiki_write(
    username: str, password: str, owner: str, repo: str, title: str, markdown: str
) -> dict:
    encoded = base64.b64encode(markdown.encode()).decode()
    return gitea_create_wiki_page(username, password, owner, repo, title, encoded)


def gitea_list_comments(
    username: str, password: str, owner: str, repo: str, issue_number: int
) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers=_gitea_auth(username, password),
        )
        r.raise_for_status()
        return r.json()


def gitea_get_file_contents(
    username: str, password: str, owner: str, repo: str, path: str, ref: str = "main"
) -> str | None:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/contents/{path}",
            headers=_gitea_auth(username, password),
            params={"ref": ref},
        )
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("encoding") == "base64":
            return base64.b64decode(j["content"]).decode()
        return j.get("content", "")


def gitea_get_pull_request(
    username: str, password: str, owner: str, repo: str, number: int
) -> dict | None:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/pulls/{number}",
            headers=_gitea_auth(username, password),
        )
        if r.status_code != 200:
            return None
        return r.json()


def gitea_list_pulls(
    username: str, password: str, owner: str, repo: str, state: str = "all"
) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/pulls",
            headers=_gitea_auth(username, password),
            params={"state": state},
        )
        r.raise_for_status()
        return r.json()


def gitea_list_pull_reviews(
    username: str, password: str, owner: str, repo: str, number: int
) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/repos/{owner}/{repo}/pulls/{number}/reviews",
            headers=_gitea_auth(username, password),
        )
        r.raise_for_status()
        return r.json()


def gitea_user_exists(username_admin: str, password_admin: str, name: str) -> bool:
    with _get_http_client() as c:
        r = c.get(
            f"{GITEA_BASE}/users/{name}",
            headers=_gitea_auth(username_admin, password_admin),
        )
        return r.status_code == 200


def gitea_admin_create_user(
    admin_user: str,
    admin_password: str,
    username: str,
    password: str,
    email: str,
    full_name: str = "",
    must_change_password: bool = False,
) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{GITEA_BASE}/admin/users",
            headers=_gitea_auth(admin_user, admin_password),
            json={
                "username": username,
                "password": password,
                "email": email,
                "full_name": full_name or username,
                "must_change_password": must_change_password,
                "source_id": 0,
                "login_name": username,
            },
        )
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 422 and "already exists" in r.text.lower():
            return {"exists": True}
        raise RuntimeError(f"create user {username}: {r.status_code} {r.text[:200]}")


# ---------------------------------------------------------------------------
# Mattermost
# ---------------------------------------------------------------------------

MM_BASE = "https://mattermost.zoo/api/v4"


class MMSession:
    def __init__(self, token: str, user_id: str):
        self.token = token
        self.user_id = user_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }


def mm_login(login_id: str, password: str) -> MMSession:
    with _get_http_client() as c:
        r = c.post(
            f"{MM_BASE}/users/login",
            json={"login_id": login_id, "password": password},
        )
        if r.status_code != 200:
            raise RuntimeError(f"mm_login {login_id}: {r.status_code} {r.text[:200]}")
        token = r.headers.get("Token") or r.headers.get("token")
        if not token:
            raise RuntimeError("mm_login: no Token header")
        return MMSession(token=token, user_id=r.json()["id"])


def mm_create_user(
    admin: MMSession, username: str, password: str, email: str, nickname: str = ""
) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{MM_BASE}/users",
            headers=admin.headers,
            json={
                "username": username,
                "password": password,
                "email": email,
                "nickname": nickname or username,
            },
        )
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 400 and ("already" in r.text.lower() or "exists" in r.text.lower()):
            # fetch by username
            r2 = c.get(
                f"{MM_BASE}/users/username/{username}", headers=admin.headers
            )
            if r2.status_code == 200:
                return r2.json()
        raise RuntimeError(f"mm create user {username}: {r.status_code} {r.text[:200]}")


def mm_get_user_by_username(session: MMSession, username: str) -> dict | None:
    with _get_http_client() as c:
        r = c.get(f"{MM_BASE}/users/username/{username}", headers=session.headers)
        if r.status_code == 200:
            return r.json()
        return None


def mm_get_default_team(session: MMSession) -> dict:
    with _get_http_client() as c:
        r = c.get(f"{MM_BASE}/teams", headers=session.headers, params={"per_page": 50})
        r.raise_for_status()
        teams = r.json()
        if not teams:
            raise RuntimeError("mm_get_default_team: no teams exist")
        return teams[0]


def mm_add_user_to_team(session: MMSession, team_id: str, user_id: str) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{MM_BASE}/teams/{team_id}/members",
            headers=session.headers,
            json={"team_id": team_id, "user_id": user_id},
        )
        if r.status_code in (200, 201):
            return r.json()
        # 400 "already a member" is fine
        if r.status_code == 400 and "already" in r.text.lower():
            return {"exists": True}
        raise RuntimeError(f"mm_add_user_to_team: {r.status_code} {r.text[:200]}")


def mm_create_direct_channel(session: MMSession, user_a: str, user_b: str) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{MM_BASE}/channels/direct",
            headers=session.headers,
            json=[user_a, user_b],
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"mm_create_direct: {r.status_code} {r.text[:200]}")
        return r.json()


def mm_post(session: MMSession, channel_id: str, message: str) -> dict:
    with _get_http_client() as c:
        r = c.post(
            f"{MM_BASE}/posts",
            headers=session.headers,
            json={"channel_id": channel_id, "message": message},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"mm_post: {r.status_code} {r.text[:200]}")
        return r.json()


def mm_list_posts_for_channel(session: MMSession, channel_id: str, per_page: int = 60) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{MM_BASE}/channels/{channel_id}/posts",
            headers=session.headers,
            params={"per_page": per_page},
        )
        r.raise_for_status()
        posts = r.json().get("posts", {})
        return list(posts.values())


def mm_search_posts(session: MMSession, team_id: str, terms: str) -> list[dict]:
    with _get_http_client() as c:
        r = c.post(
            f"{MM_BASE}/teams/{team_id}/posts/search",
            headers=session.headers,
            json={"terms": terms, "is_or_search": False},
        )
        if r.status_code != 200:
            return []
        return list(r.json().get("posts", {}).values())


# ---------------------------------------------------------------------------
# Microbin (paste.zoo)
# ---------------------------------------------------------------------------

MICROBIN_BASE = "https://paste.zoo"


def microbin_create_paste(
    content: str,
    expiration: str = "never",
    syntax_highlight: str = "none",
) -> str:
    """Return the URL of the created paste.

    Microbin does not support titles. Embed any title into the first line of
    the content if needed. Endpoint is /upload (multipart), which 302s to
    /upload/<animal-path> on success.
    """
    with _get_http_client() as c:
        files = {
            "content": (None, content),
            "expiration": (None, expiration),
            "syntax_highlight": (None, syntax_highlight),
            "privacy": (None, "public"),
        }
        r = c.post(f"{MICROBIN_BASE}/upload", files=files, follow_redirects=False)
        if r.status_code in (301, 302, 303):
            loc = r.headers.get("location", "")
            if loc.startswith("/"):
                loc = f"{MICROBIN_BASE}{loc}"
            return loc
        raise RuntimeError(f"microbin create: {r.status_code} {r.text[:200]}")


def microbin_list_pastes_html() -> str:
    """Microbin's /list endpoint returns HTML listing of pastes."""
    with _get_http_client() as c:
        r = c.get(f"{MICROBIN_BASE}/list")
        if r.status_code == 200:
            return r.text
        return ""


# ---------------------------------------------------------------------------
# Miniflux
# ---------------------------------------------------------------------------

MINIFLUX_BASE = "https://miniflux.zoo/v1"
MINIFLUX_ADMIN = ("admin", "zoopassword")


def miniflux_get_category(auth: tuple[str, str], title: str = "All") -> dict | None:
    with _get_http_client() as c:
        r = c.get(f"{MINIFLUX_BASE}/categories", auth=auth)
        r.raise_for_status()
        for cat in r.json():
            if cat.get("title") == title:
                return cat
        if r.json():
            return r.json()[0]
    return None


def miniflux_create_feed(auth: tuple[str, str], feed_url: str) -> dict:
    cat = miniflux_get_category(auth)
    payload = {"feed_url": feed_url}
    if cat:
        payload["category_id"] = cat["id"]
    with _get_http_client() as c:
        r = c.post(f"{MINIFLUX_BASE}/feeds", auth=auth, json=payload)
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 400 and "already" in r.text.lower():
            # find the existing feed
            r2 = c.get(f"{MINIFLUX_BASE}/feeds", auth=auth)
            r2.raise_for_status()
            for f in r2.json():
                if f.get("feed_url") == feed_url:
                    return f
        raise RuntimeError(f"miniflux feed: {r.status_code} {r.text[:300]}")


def miniflux_refresh_feed(auth: tuple[str, str], feed_id: int) -> None:
    with _get_http_client() as c:
        c.put(f"{MINIFLUX_BASE}/feeds/{feed_id}/refresh", auth=auth)


# ---------------------------------------------------------------------------
# Focalboard: boards, columns (select options), card status moves
# ---------------------------------------------------------------------------

FB_BASE = "https://focalboard.zoo"


def fb_login(username: str, password: str) -> str:
    with _get_http_client() as c:
        r = c.post(
            f"{FB_BASE}/api/v2/login",
            json={"type": "normal", "username": username, "password": password},
        )
        if r.status_code != 200:
            raise RuntimeError(f"fb_login {username}: {r.status_code} {r.text[:200]}")
        return r.json()["token"]


def fb_get_teams(token: str) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{FB_BASE}/api/v2/teams",
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        return r.json()


def fb_list_blocks(token: str, board_id: str) -> list[dict]:
    with _get_http_client() as c:
        r = c.get(
            f"{FB_BASE}/api/v2/boards/{board_id}/blocks",
            headers={"Authorization": f"Bearer {token}"},
            params={"all": "true"},
        )
        r.raise_for_status()
        return r.json()


def fb_update_card_status(
    token: str, board_id: str, card_id: str, status_option_id: str, status_property_id: str
) -> None:
    """PATCH a card block to set its status property."""
    with _get_http_client() as c:
        r = c.patch(
            f"{FB_BASE}/api/v2/boards/{board_id}/blocks/{card_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"updatedFields": {"properties": {status_property_id: status_option_id}}},
        )
        if r.status_code not in (200, 204):
            raise RuntimeError(f"fb card update {card_id}: {r.status_code} {r.text[:200]}")
