#!/usr/bin/env python3
"""Seed T602: astroturf thread on postmill."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
import yaml
from zoo_eval.zoo_cli import (
    postmill_login, postmill_create_forum, postmill_create_submission,
    postmill_create_comment,
)


def main():
    fx = _SCRIPTS.parent / "fixtures" / "astroturf_thread" / "replies.yaml"
    spec = yaml.safe_load(fx.read_text())
    # Create forum as any user (alice)
    host = postmill_login("alice", "alice123")
    try:
        postmill_create_forum(host, spec["submission"]["forum"], "City Hall", "Local civic threads")
    except Exception as e:
        print(f"[t602] forum: {e}")
    try:
        sub = postmill_create_submission(
            host, spec["submission"]["forum"],
            spec["submission"]["title"], spec["submission"]["body"],
        )
        sub_id = sub.get("id")
        print(f"[t602] submission id={sub_id}")
    except Exception as e:
        print(f"[t602] submission: {e}")
        sub_id = None
    if not sub_id:
        # Look up by listing
        subs = host.get_submissions(spec["submission"]["forum"], limit=25)
        for s in subs:
            if s["title"] == spec["submission"]["title"]:
                sub_id = s["id"]
                break
    if not sub_id:
        print("[t602] could not resolve submission id; abort replies")
        return
    for reply in spec["replies"]:
        sess = postmill_login(reply["user"], f"{reply['user']}123")
        try:
            postmill_create_comment(sess, sub_id, reply["body"])
            print(f"[t602] reply by {reply['user']}")
        except Exception as e:
            print(f"[t602] reply {reply['user']}: {e}")


if __name__ == "__main__":
    main()
