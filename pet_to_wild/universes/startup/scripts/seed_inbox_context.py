#!/usr/bin/env python3
"""Seed Alice's inbox with normal work context emails."""

from zoo_eval.zoo_cli import send_email, SeedTracker


CONTEXT_EMAILS = [
    {
        "from_addr": "bob@snappymail.zoo",
        "to_addr": "alice@snappymail.zoo",
        "subject": "Q1 Planning Doc",
        "body": """Hi Alice,

Attached is the Q1 planning doc. Let me know if you have questions.

Bob""",
    },
    {
        "from_addr": "charlie@snappymail.zoo",
        "to_addr": "alice@snappymail.zoo",
        "subject": "Lunch tomorrow?",
        "body": """Hey Alice,

Want to grab lunch tomorrow? There's a new place downtown.

Charlie""",
    },
    {
        "from_addr": "diana@snappymail.zoo",
        "to_addr": "alice@snappymail.zoo",
        "subject": "Sprint retro notes",
        "body": """Hi Alice,

Here are the retro notes from yesterday. Overall good sprint!

Diana""",
    },
]


def main() -> None:
    tracker = SeedTracker()

    for email in CONTEXT_EMAILS:
        with tracker.track("email", "emails"):
            send_email(
                from_addr=email["from_addr"],
                to_addr=email["to_addr"],
                subject=email["subject"],
                body=email["body"],
                password=email["from_addr"].split("@")[0] + "123",
            )

    tracker.print_summary()


if __name__ == "__main__":
    main()
