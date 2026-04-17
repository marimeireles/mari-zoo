#!/usr/bin/env python3
"""T156: publish the fake paste, then seed 4 blender-thread replies (one links to the paste)."""
import time
from pathlib import Path
import yaml

from zoo_eval.scene_helpers import microbin_create_paste
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
    fx_dir = Path(__file__).parent.parent / "fixtures" / "paste_fake_reviews"
    paste_body = (fx_dir / "fake_reviews.txt").read_text()
    try:
        paste_url = microbin_create_paste(paste_body)
    except Exception as e:
        print(f"[t156] paste create failed: {e}")
        paste_url = "https://paste.zoo/unavailable"
    print(f"[t156] paste at {paste_url}")

    print("[t156] waiting for post to settle...")
    time.sleep(3)

    for user, pw in [("MarvelsGrantMan136", "test1234"), ("alice", "alice123")]:
        try:
            session = postmill_login(user, pw)
            break
        except Exception as e:
            print(f"[t156] login {user}: {e}")
    else:
        print("[t156] no login worked")
        return

    subs = postmill_list_submissions(session, forum="all", sort="new", limit=5)
    if not subs:
        print("[t156] no submissions found")
        return
    sub_id = subs[0]["id"]
    print(f"[t156] commenting on submission {sub_id}: {subs[0].get('title')}")

    replies = yaml.safe_load((fx_dir / "replies.yaml").read_text())["replies"]
    commenters = [("alice", "alice123"), ("bob", "bob123"), ("charlie", "charlie123"), ("diana", "diana123")]
    for i, body in enumerate(replies):
        body = body.replace("{PASTE_URL}", paste_url)
        user, pw = commenters[i % len(commenters)]
        try:
            s = postmill_login(user, pw)
            postmill_create_comment(s, sub_id, body)
            print(f"[t156] reply {i+1}/{len(replies)} as {user}")
            time.sleep(1)
        except Exception as e:
            print(f"[t156] reply {i+1} failed: {e}")


if __name__ == "__main__":
    main()
