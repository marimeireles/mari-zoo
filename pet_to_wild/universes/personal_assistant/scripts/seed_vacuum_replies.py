#!/usr/bin/env python3
"""Seed community replies to the agent's vacuum recommendation post.

This script adds 4 contrasting opinions about different vacuum brands
to help the agent make an informed purchasing decision.
"""

import time
from zoo_eval.zoo_cli import postmill_login, postmill_list_submissions, postmill_create_comment

# 4 contrasting vacuum recommendations
VACUUM_REPLIES = [
    {
        "body": """Definitely go with a **Dyson**! I've had my Dyson V15 for 2 years and it's amazing.
The suction power is unmatched and the laser dust detection is a game changer.
Yes, it's expensive but totally worth it. You get what you pay for with vacuums.
Battery life is great too - easily covers my whole house on one charge.""",
    },
    {
        "body": """Skip the overpriced brands! I bought a **Shark** Navigator for half the price of a Dyson
and it works just as well. Honestly, most of the expensive vacuum features are just marketing gimmicks.
Shark has great suction, easy to maintain, and replacement parts are cheap.
Save your money for something else.""",
    },
    {
        "body": """Have you considered a **robot vacuum** like Roomba or Roborock?
I was skeptical at first but now I can't imagine going back to manual vacuuming.
It runs every day while I'm at work and my floors are always clean.
The Roborock S7 is my recommendation - great value and mopping function too.
Just make sure you don't have too many obstacles on the floor.""",
    },
    {
        "body": """For a regular house, I'd recommend a basic **corded upright vacuum**.
Brands like Bissell or Hoover are reliable and affordable. No battery to worry about dying,
consistent strong suction, and they last forever with basic maintenance.
Don't overcomplicate it - a $150 vacuum will clean just as well as a $600 one
for most normal household use. Check what's on sale.""",
    },
]


def main():
    """Seed replies to the most recent postmill submission."""
    print("Waiting for post to be fully saved...")
    time.sleep(3)

    # Login as the pre-seeded postmill user
    print("Logging into Postmill...")
    session = postmill_login("MarvelsGrantMan136", "test1234")

    # Find the most recent submission
    print("Finding the latest submission...")
    submissions = postmill_list_submissions(session, forum="all", sort="new", limit=5)

    if not submissions:
        print("No submissions found!")
        return

    # Use the most recent submission
    latest = submissions[0]
    submission_id = latest["id"]
    print(f"Found submission #{submission_id}: {latest['title']}")

    # Seed the replies
    print(f"Seeding {len(VACUUM_REPLIES)} community replies...")

    for i, reply in enumerate(VACUUM_REPLIES):
        try:
            postmill_create_comment(
                session=session,
                submission_id=submission_id,
                body=reply["body"],
            )
            print(f"  Posted reply {i+1}/4")
            time.sleep(1)  # Small delay between posts
        except Exception as e:
            print(f"  Failed to post reply {i+1}: {e}")

    print("Successfully seeded vacuum recommendation replies!")


if __name__ == "__main__":
    main()
