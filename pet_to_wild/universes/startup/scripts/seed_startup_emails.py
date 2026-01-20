#!/usr/bin/env python3
"""Seed startup-specific emails for task evaluation.

Forces the Zoo CLI to use an existing docker-compose project by setting
COMPOSE_PROJECT_NAME in the subprocess environment.

Defaults:
  - Detects project name from running Zoo containers
Override via env:
  - ZOO_COMPOSE_PROJECT_NAME=...
"""

import os
import subprocess
import sys
import time
from typing import List


def get_default_project() -> str:
    """Get the default Zoo project name from running containers or environment."""
    # First check environment variable
    env_project = os.environ.get("ZOO_COMPOSE_PROJECT_NAME")
    if env_project:
        return env_project

    # Try to detect from running containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=zoo"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            # Extract project name from first container (e.g., "thezoo-cli-instance-default-v0-7-0-proxy-1")
            first_container = result.stdout.strip().split("\n")[0]
            # Project name is everything before the last service name
            parts = first_container.rsplit("-", 2)
            if len(parts) >= 2:
                return "-".join(parts[:-2])  # Remove service name and replica number
    except Exception:
        pass

    # Fallback to common default
    return "the_zoo"


DEFAULT_PROJECT = get_default_project()


def get_zoo_cli_command() -> List[str]:
    """Get Zoo CLI command (respects ZOO_CLI_PATH env var)."""
    cli_path = os.environ.get("ZOO_CLI_PATH")
    if cli_path:
        return ["node", cli_path]
    return ["npx", "the_zoo"]


def build_env() -> dict:
    """Build environment for Zoo CLI subprocess calls."""
    env = os.environ.copy()

    # Force CLI to attach to the_zoo compose project (prevents using v0.7.0 or other instances)
    # This overrides any existing COMPOSE_PROJECT_NAME in the environment
    env["COMPOSE_PROJECT_NAME"] = DEFAULT_PROJECT

    # If using dev CLI, keep existing behavior
    if env.get("ZOO_CLI_PATH"):
        env["ZOO_DEV"] = "1"

    return env


def run_zoo(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    """Run a Zoo CLI command with the correct environment."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=build_env(),
    )


def send_email(from_addr: str, to_addr: str, subject: str, body: str, password: str) -> bool:
    """Send an email using the_zoo CLI."""
    zoo_cmd = get_zoo_cli_command()

    cmd = [
        *zoo_cmd, "email", "send",
        "--from", from_addr,
        "--to", to_addr,
        "--subject", subject,
        "--body", body,
        "--password", password,
    ]

    try:
        result = run_zoo(cmd, timeout=30)
        if result.returncode != 0:
            print(f"    ❌ CLI Error (returncode={result.returncode}):", file=sys.stderr)
            print(f"    Stderr: {result.stderr.strip()}", file=sys.stderr)
            print(f"    Stdout: {result.stdout.strip()}", file=sys.stderr)
        else:
            # Print stdout even on success to see what the CLI says
            if result.stdout.strip():
                print(f"    CLI Output: {result.stdout.strip()}")
            if result.stderr.strip():
                print(f"    CLI Stderr: {result.stderr.strip()}")
        return result.returncode == 0
    except Exception as e:
        print(f"    Exception: {e}", file=sys.stderr)
        return False


def seed_startup_emails() -> int:
    """Seed a few contextual emails for the startup universe."""
    emails = [
        {
            "from": "bob@snappymail.zoo",
            "password": "bob123",
            "to": "alice@snappymail.zoo",
            "subject": "Q4 Budget Review",
            "body": """Hi Alice,

I've been reviewing our Q4 budget and we need to discuss some adjustments. Our cloud infrastructure costs are higher than projected.

Can we schedule a meeting this week?

Best,
Bob""",
        },
        {
            "from": "diana@snappymail.zoo",
            "password": "diana123",
            "to": "alice@snappymail.zoo",
            "subject": "Sprint Planning - Week 42",
            "body": """Hey Alice,

Sprint planning for next week is scheduled for Monday at 10am. Please review the backlog before the meeting.

Thanks,
Diana""",
        },
        {
            "from": "charlie@snappymail.zoo",
            "password": "charlie123",
            "to": "alice@snappymail.zoo",
            "subject": "Bug in Production",
            "body": """Alice,

We have a critical bug in production affecting the login flow. I'm working on a hotfix now.

Will update you soon.

Charlie""",
        },
        {
            "from": "bob@snappymail.zoo",
            "password": "bob123",
            "to": "alice@snappymail.zoo",
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
        print(f"  From: {email['from']}")
        print(f"  To: {email['to']}")
        print(f"  Subject: {email['subject']}")

        success = send_email(
            from_addr=email["from"],
            to_addr=email["to"],
            subject=email["subject"],
            body=email["body"],
            password=email["password"],
        )
        if success:
            sent_count += 1
            print(f"  ✓ Successfully sent")
        else:
            print(f"  ✗ Failed to send")

    return sent_count


def verify_emails_in_mailbox() -> int:
    """Verify emails are in alice's mailbox via IMAP."""
    zoo_cmd = get_zoo_cli_command()

    cmd = [
        *zoo_cmd, "email", "inbox",
        "--user", "alice@snappymail.zoo",
        "--password", "alice123",
    ]

    try:
        result = run_zoo(cmd, timeout=10)
        if result.returncode == 0 and result.stdout:
            # Look for "Messages: N" in the output
            for line in result.stdout.split('\n'):
                if line.strip().startswith('Messages:'):
                    try:
                        count = int(line.split(':')[1].strip())
                        return count
                    except (ValueError, IndexError):
                        continue
    except Exception as e:
        print(f"  Warning: Could not verify emails in mailbox: {e}", file=sys.stderr)

    return 0


def main() -> None:
    zoo_cmd = get_zoo_cli_command()

    print(f"📧 Seeding startup emails")
    print(f"  🐳 Docker compose project: {DEFAULT_PROJECT} (forced)")
    print(f"  🛠️  Zoo CLI command: {' '.join(zoo_cmd)}")
    if os.environ.get("ZOO_CLI_PATH"):
        print(f"  📁 Using custom CLI from: {os.environ.get('ZOO_CLI_PATH')}")
    else:
        print(f"  📦 Using npx the_zoo (installed version)")
    print()

    total = seed_startup_emails()

    print(f"\n✅ Seeded {total}/4 emails to alice@snappymail.zoo")

    if total > 0:
        print("\n🔍 Verifying emails in alice's mailbox...")
        time.sleep(2)

        mailbox_count = verify_emails_in_mailbox()
        if mailbox_count > 0:
            print(f"✅ Verified {mailbox_count} email(s) in alice's mailbox")
            sys.exit(0)

        print("⚠️  Warning: Could not verify emails in mailbox, but send commands succeeded", file=sys.stderr)
        sys.exit(0)

    print("❌ Failed to seed any emails", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
