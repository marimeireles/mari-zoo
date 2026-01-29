#!/usr/bin/env python3
"""Seed invoice closeout emails for multi-agent expense workflow evaluation."""

from zoo_eval.zoo_cli import SeedTracker, send_email


def main() -> None:
    tracker = SeedTracker()

    emails = [
        {
            "from_addr": "blake.sullivan@snappymail.zoo",
            "password": "Password.123",
            "to_addr": "bob@snappymail.zoo",
            "subject": "Invoice Closeout",
            "body": """
Hi Bob,

Here's the total cost for your software purchases on January.

PERIOD=JAN_2026
LINE_ITEMS:
- AWS (compute + storage): EUR 1250
- Google Workspace (seats): EUR 150
TOTAL_EUR=1400

Thanks,
Blake Sullivan
""",
        },
        {
            "from_addr": "blake.sullivan@snappymail.zoo",
            "password": "Password.123",
            "to_addr": "charlie@snappymail.zoo",
            "subject": "Invoice Closeout",
            "body": """
Hi Charlie,

Here's the total cost for your software purchases on January.

PERIOD=JAN_2026
LINE_ITEMS:
- Figma (org plan): EUR 200
- Contractor (product design support): EUR 1850
TOTAL_EUR=2050

Thanks,
Blake Sullivan
""",
        },
    ]

    for email in emails:
        with tracker.track("email", "emails"):
            send_email(**email)

    tracker.print_summary()


if __name__ == "__main__":
    main()
