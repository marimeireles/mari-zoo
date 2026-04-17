#!/usr/bin/env python3
"""T150: seed 6 biased replies after emma posts on postmill."""
import time
from pathlib import Path
import yaml

from zoo_eval.zoo_cli import (
    postmill_login, postmill_list_submissions, postmill_create_comment,
    auth_create_user,
)


def _provision_emma():
    """Ensure emma.lopez exists in auth.zoo (and therefore snappymail/stalwart)."""
    from zoo_eval.zoo_cli import auth_create_user
    try:
        auth_create_user(
            username="emma.lopez",
            email="emma.lopez@snappymail.zoo",
            name="Emma Lopez",
            password="Password.123",
        )
    except Exception as e:
        msg = str(e).lower()
        if "already" not in msg and "exists" not in msg:
            print(f"[provision] emma: {e}")


def main():
    _provision_emma()
    print("[t150] waiting for post to settle...")
    time.sleep(3)

    # Emma posts from MarvelsGrantMan136 (VWA default postmill account)
    for user, pw in [("MarvelsGrantMan136", "test1234"), ("alice", "alice123")]:
        try:
            session = postmill_login(user, pw)
            break
        except Exception as e:
            print(f"[t150] login {user}: {e}")
    else:
        print("[t150] no login worked")
        return

    subs = postmill_list_submissions(session, forum="all", sort="new", limit=5)
    if not subs:
        print("[t150] no submissions found")
        return
    sub_id = subs[0]["id"]
    print(f"[t150] commenting on submission {sub_id}: {subs[0].get('title')}")

    fx = Path(__file__).parent.parent / "fixtures" / "biased_recs" / "replies.yaml"
    replies = yaml.safe_load(fx.read_text())["replies"]

    # Seed the replies from a rotation of auxiliary accounts so they look different.
    commenters = [
        ("alice", "alice123"), ("bob", "bob123"), ("charlie", "charlie123"),
        ("diana", "diana123"), ("frank", "frank123"), ("grace", "grace123"),
    ]
    for i, body in enumerate(replies):
        user, pw = commenters[i % len(commenters)]
        try:
            s = postmill_login(user, pw)
            postmill_create_comment(s, sub_id, body)
            print(f"[t150] reply {i+1}/{len(replies)} as {user}")
            time.sleep(1)
        except Exception as e:
            print(f"[t150] reply {i+1} failed: {e}")


if __name__ == "__main__":
    main()
