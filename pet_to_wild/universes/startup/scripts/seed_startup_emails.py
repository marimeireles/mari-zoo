#!/usr/bin/env python3
"""Seed startup-specific emails for task evaluation."""

import sys
import time

from zoo_eval.zoo_cli import send_email_with_result, check_inbox, get_zoo_cli


def seed_startup_emails() -> int:
    """Seed a few contextual emails for the startup universe."""
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

    for idx, email in enumerate(emails, start=1):
        print(f"\n[{idx}/{total_emails}] 📤 Sending email...")
        print(f"  From: {email['from_addr']}")
        print(f"  To: {email['to_addr']}")
        print(f"  Subject: {email['subject']}")

        result = send_email_with_result(**email)
        if result.returncode == 0:
            sent_count += 1
            print(f"  ✓ Successfully sent")
            if result.stdout.strip():
                print(f"    CLI Output: {result.stdout.strip()}")
        else:
            print(f"  ✗ Failed to send")
            print(f"    CLI Error (returncode={result.returncode}):", file=sys.stderr)
            if result.stderr.strip():
                print(f"    Stderr: {result.stderr.strip()}", file=sys.stderr)
            if result.stdout.strip():
                print(f"    Stdout: {result.stdout.strip()}", file=sys.stderr)

    return sent_count


def main() -> None:
    cli = get_zoo_cli()
    zoo_cmd = cli._get_command()

    print(f"📧 Seeding startup emails")
    print(f"  🐳 Docker compose project: {cli.compose_project}")
    print(f"  🛠️  Zoo CLI command: {' '.join(zoo_cmd)}")
    if cli.cli_path:
        print(f"  📁 Using custom CLI from: {cli.cli_path}")
    else:
        print(f"  📦 Using npx the_zoo (installed version)")
    print()

    total = seed_startup_emails()

    print(f"\n✅ Seeded {total}/4 emails to alice@snappymail.zoo")

    if total > 0:
        print("\n🔍 Verifying emails in alice's mailbox...")
        time.sleep(2)

        mailbox_count = check_inbox("alice@snappymail.zoo", "alice123")
        if mailbox_count and mailbox_count > 0:
            print(f"✅ Verified {mailbox_count} email(s) in alice's mailbox")
            sys.exit(0)

        print("⚠️  Warning: Could not verify emails in mailbox, but send commands succeeded", file=sys.stderr)
        sys.exit(0)

    print("❌ Failed to seed any emails", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
