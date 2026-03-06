#!/usr/bin/env python3
"""Seed community replies to the agent's vacuum recommendation post.

Note: Kept as script due to dynamic logic (find latest post, loop over comments).
Data is loaded from fixtures/vacuum_shopping/replies.yaml
"""

import time
from pathlib import Path

import yaml

from zoo_eval.auth import get_credential
from zoo_eval.zoo_cli import postmill_login, postmill_list_submissions, postmill_create_comment


def load_replies() -> list[str]:
    """Load vacuum replies from fixture file."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "vacuum_shopping" / "replies.yaml"
    with open(fixture_path) as f:
        data = yaml.safe_load(f)
    return data["replies"]


def main():
    print("Waiting for post to be fully saved...")
    time.sleep(3)

    # Login using credentials
    print("Logging into Postmill...")
    cred = get_credential("postmill", "emma.lopez")
    session = postmill_login(cred.username, cred.password)

    # Find the most recent submission
    print("Finding the latest submission...")
    submissions = postmill_list_submissions(session, forum="all", sort="new", limit=5)

    if not submissions:
        print("No submissions found!")
        return

    latest = submissions[0]
    submission_id = latest["id"]
    print(f"Found submission #{submission_id}: {latest['title']}")

    # Load and post replies
    replies = load_replies()
    print(f"Seeding {len(replies)} community replies...")

    for i, body in enumerate(replies):
        try:
            postmill_create_comment(
                session=session,
                submission_id=submission_id,
                body=body,
            )
            print(f"  Posted reply {i+1}/{len(replies)}")
            time.sleep(1)
        except Exception as e:
            print(f"  Failed to post reply {i+1}: {e}")

    print("Successfully seeded vacuum recommendation replies!")


if __name__ == "__main__":
    main()
