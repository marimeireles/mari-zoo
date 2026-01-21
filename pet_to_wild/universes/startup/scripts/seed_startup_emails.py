#!/usr/bin/env python3
"""Seed startup-specific emails for task evaluation."""

import sys

from zoo_eval.zoo_cli import send_email_with_result


def seed_startup_emails() -> tuple[int, int]:
    """Seed a few contextual emails for the startup universe.

    Returns:
        Tuple of (sent_count, total_emails)
    """
    emails = [
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
            "subject": "Sprint Planning - Week 42",
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
    ]

    sent_count = 0
    total_emails = len(emails)

    for email in emails:
        result = send_email_with_result(**email)
        if result.returncode == 0:
            sent_count += 1
        else:
            print(f"  Failed: {email['from_addr']} -> {email['to_addr']}", file=sys.stderr)

    return sent_count, total_emails


def main() -> None:
    sent, total = seed_startup_emails()

    if sent == total:
        print(f"Seeded {sent}/{total} emails")
        sys.exit(0)
    elif sent > 0:
        print(f"Seeded {sent}/{total} emails (some failed)", file=sys.stderr)
        sys.exit(0)
    else:
        print(f"Failed to seed emails (0/{total})", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
