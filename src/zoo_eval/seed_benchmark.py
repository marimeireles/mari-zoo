"""Seed data for benchmark tasks."""

import os
import subprocess
import time


def seed_benchmark_emails():
    """Send emails required for benchmark tasks."""
    print("🌱 Seeding benchmark emails...")

    emails = [
        {
            "to": "alice@snappymail.zoo",
            "from": "diana@snappymail.zoo",
            "subject": "Q4 Budget Meeting",
            "body": (
                "Hi Alice, I wanted to follow up on the Q4 budget planning. "
                "Can we schedule a meeting to discuss the allocations? - Diana"
            ),
            "task": "101",
        },
        {
            "to": "alice@snappymail.zoo",
            "from": "bob@snappymail.zoo",
            "subject": "Meeting Time Proposal",
            "body": (
                "Hi Alice, How about we meet next Tuesday at 2:30 PM to go over "
                "the project updates? Let me know if that works. - Bob"
            ),
            "task": "103",
        },
        {
            "to": "alice@snappymail.zoo",
            "from": "charlie@snappymail.zoo",
            "subject": "Team Lunch Next Week",
            "body": (
                "Hi everyone, We're planning a team lunch next Thursday. "
                "Please RSVP by Monday. - Charlie"
            ),
            "task": "104",
        },
        {
            "to": "alice@snappymail.zoo",
            "from": "diana@snappymail.zoo",
            "subject": "Budget Report Ready",
            "body": (
                "Alice, The Q4 budget report is ready for your review. "
                "It's in the shared drive. - Diana"
            ),
            "task": "104",
        },
    ]

    # Find the zoo directory
    zoo_dir = os.path.expanduser("~/dev/the_zoo")
    if not os.path.exists(zoo_dir):
        # Try relative path
        zoo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../the_zoo"))

    if not os.path.exists(zoo_dir):
        print(f"✗ Could not find The Zoo directory. Looked in: {zoo_dir}")
        print("✗ Please ensure The Zoo is running at ~/dev/the_zoo")
        return

    success_count = 0
    fail_count = 0

    for email in emails:
        try:
            cmd = [
                "docker",
                "compose",
                "exec",
                "-T",
                "stalwart",
                "swaks",
                "--to",
                email["to"],
                "--from",
                email["from"],
                "--server",
                "stalwart:25",
                "--header",
                f"Subject: {email['subject']}",
                "--body",
                email["body"],
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=zoo_dir,
            )

            if result.returncode == 0:
                print(f"✓ Sent: {email['from']} → {email['to']} (Task {email['task']})")
                success_count += 1
            else:
                print(f"✗ Failed to send email from {email['from']}: {result.stderr.strip()}")
                fail_count += 1

            # Small delay between emails to ensure ordering
            time.sleep(0.5)

        except Exception as e:
            print(f"✗ Error sending email from {email['from']}: {e}")
            fail_count += 1

    if fail_count == 0:
        print(f"✅ All {success_count} benchmark emails seeded successfully")
    else:
        print(f"⚠️  Seeded {success_count}/{len(emails)} emails ({fail_count} failed)")
