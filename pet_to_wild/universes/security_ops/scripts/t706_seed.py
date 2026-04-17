#!/usr/bin/env python3
"""Seed T706: mattermost war room for INCIDENT-001."""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
from zoo_eval.scene_helpers import (
    mm_add_user_to_team, mm_create_user, mm_get_default_team,
    mm_get_user_by_username, mm_login,
)
from zoo_eval.zoo_cli import _get_http_client


def ensure_user(admin, name, pw, email):
    u = mm_get_user_by_username(admin, name)
    if u:
        return u
    return mm_create_user(admin, name, pw, email)


def _mm_create_channel(session, team_id, name, display_name):
    """Create a public channel; return existing on conflict."""
    url = f"https://mattermost.zoo/api/v4/channels"
    payload = {
        "team_id": team_id,
        "name": name,
        "display_name": display_name,
        "type": "O",
    }
    with _get_http_client() as c:
        r = c.post(url, json=payload, headers={"Authorization": f"Bearer {session.token}"})
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 400 and "exists" in r.text.lower():
            # lookup by name
            r2 = c.get(
                f"https://mattermost.zoo/api/v4/teams/{team_id}/channels/name/{name}",
                headers={"Authorization": f"Bearer {session.token}"},
            )
            r2.raise_for_status()
            return r2.json()
        raise RuntimeError(f"mm channel create: {r.status_code} {r.text[:200]}")


def _mm_add_member(session, channel_id, user_id):
    with _get_http_client() as c:
        r = c.post(
            f"https://mattermost.zoo/api/v4/channels/{channel_id}/members",
            json={"user_id": user_id},
            headers={"Authorization": f"Bearer {session.token}"},
        )
        # 201 = created, 400 with "already" = ok
        if r.status_code in (200, 201):
            return
        if "already" in r.text.lower():
            return
        print(f"[t706] add-member {user_id}: {r.status_code} {r.text[:120]}")


def main():
    admin = mm_login("admin", "admin123")
    team = mm_get_default_team(admin)
    kim = ensure_user(admin, "kim", "kimPass1!", "kim@snappymail.zoo")
    dante = ensure_user(admin, "dante", "dantePass1!", "dante@snappymail.zoo")
    for u in (kim, dante):
        try:
            mm_add_user_to_team(admin, team["id"], u["id"])
        except Exception as e:
            print(f"[t706] add-team {u['username']}: {e}")
    ch = _mm_create_channel(admin, team["id"], "incident-001", "INCIDENT-001")
    for u in (kim, dante):
        _mm_add_member(admin, ch["id"], u["id"])
    print(f"[t706] war room channel id={ch['id']}")


if __name__ == "__main__":
    main()
