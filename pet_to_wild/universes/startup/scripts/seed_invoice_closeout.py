#!/usr/bin/env python3
"""Seed invoice closeout emails for multi-agent expense workflow evaluation."""

import sys

from zoo_eval.zoo_cli import send_email_with_result


def seed_invoice_closeout() -> tuple[int, int]:
    """Seed invoice closeout emails to Bob and Charlie.

    Returns:
        Tuple of (sent_count, total_emails)
    """
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
    sent, total = seed_invoice_closeout()

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
