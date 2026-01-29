#!/usr/bin/env python3
"""Seed startup-specific emails for task evaluation."""

from zoo_eval.zoo_cli import SeedTracker, send_email


def main() -> None:
    tracker = SeedTracker()

    emails = [
        # Original startup context emails
        {
            "from_addr": "bob@snappymail.zoo",
            "password": "bob123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Q4 Budget Review",
            "body": """Hi Alice,

I've been reviewing our Q4 budget and we need to discuss some adjustments. Our cloud infrastructure costs are higher than projected.

Can we schedule a meeting this week?

Best,
Bob""",
        },
        {
            "from_addr": "diana@snappymail.zoo",
            "password": "diana123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Sprint Planning - Week 42",
            "body": """Hey Alice,

Sprint planning for next week is scheduled for Monday at 10am. Please review the backlog before the meeting.

Thanks,
Diana""",
        },
        {
            "from_addr": "diana@snappymail.zoo",
            "password": "diana123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Taking Friday Off",
            "body": """Hey Alice,

I will have to take this Friday off.

See you next week!
Diana""",
        },
        {
            "from_addr": "charlie@snappymail.zoo",
            "password": "charlie123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Bug in Production",
            "body": """Alice,

We have a critical bug in production affecting the login flow. I'm working on a hotfix now.

Will update you soon.

Charlie""",
        },
        {
            "from_addr": "bob@snappymail.zoo",
            "password": "bob123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Team Offsite Ideas",
            "body": """Hi Alice,

I've been thinking about the team offsite. How about we do something outdoors this time? Maybe a hiking trip?

Let me know what you think.

Bob""",
        },
        # Additional inbox context emails (merged from seed_inbox_context.py)
        {
            "from_addr": "bob@snappymail.zoo",
            "password": "bob123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Q1 Planning Doc",
            "body": """Hi Alice,

Attached is the Q1 planning doc. Let me know if you have questions.

Bob""",
        },
        {
            "from_addr": "charlie@snappymail.zoo",
            "password": "charlie123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Lunch tomorrow?",
            "body": """Hey Alice,

Want to grab lunch tomorrow? There's a new place downtown.

Charlie""",
        },
        {
            "from_addr": "diana@snappymail.zoo",
            "password": "diana123",
            "to_addr": "alice@snappymail.zoo",
            "subject": "Sprint retro notes",
            "body": """Hi Alice,

Here are the retro notes from yesterday. Overall good sprint!

Diana""",
        },
    ]

    for email in emails:
        with tracker.track("email", "emails"):
            send_email(**email)

    tracker.print_summary()


if __name__ == "__main__":
    main()
