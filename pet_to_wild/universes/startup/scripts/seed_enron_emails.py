#!/usr/bin/env python3
"""Seed Enron email dataset into snappymail for realistic email tasks.

Downloads the full Enron email dataset from Kaggle and seeds it into the mail server.
"""

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

import kagglehub


def get_zoo_cli_command() -> list[str]:
    """Get Zoo CLI command (respects ZOO_CLI_PATH env var)."""
    cli_path = os.environ.get("ZOO_CLI_PATH")
    if cli_path:
        return ["node", cli_path]
    return ["npx", "the_zoo"]


def download_enron_dataset() -> Path:
    """Download Enron email dataset from Kaggle.

    Returns:
        Path to the downloaded dataset directory
    """
    print("📥 Downloading Enron email dataset from Kaggle...")

    # Download latest version
    path = kagglehub.dataset_download("oanannv/enron-email-reply-dataset")

    print(f"✓ Dataset downloaded to: {path}")
    return Path(path)


def find_csv_files(dataset_path: Path) -> list[Path]:
    """Find all CSV files in the dataset directory."""
    csv_files = list(dataset_path.glob("**/*.csv"))
    print(f"📁 Found {len(csv_files)} CSV file(s)")
    for f in csv_files:
        print(f"  - {f.name}")
    return csv_files


def send_email(from_addr: str, to_addr: str, subject: str, body: str) -> bool:
    """Send an email using the_zoo CLI."""
    zoo_cmd = get_zoo_cli_command()

    cmd = [
        *zoo_cmd, "email", "send",
        "--from", from_addr,
        "--to", to_addr,
        "--subject", subject,
        "--body", body,
    ]

    try:
        # If using dev CLI, set ZOO_DEV=1 to use main dev instance
        env = os.environ.copy()
        if os.environ.get("ZOO_CLI_PATH"):
            env["ZOO_DEV"] = "1"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return result.returncode == 0
    except Exception:
        return False


def seed_emails_from_csv(csv_path: Path, recipient: str, limit: int | None = None) -> int:
    """Seed emails from a CSV file into the mail server.

    Args:
        csv_path: Path to CSV file
        recipient: Email address to send to
        limit: Maximum number of emails to send (None = all)

    Returns:
        Number of emails successfully sent
    """
    sent_count = 0

    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)

        # Get column names to understand the CSV structure
        fieldnames = reader.fieldnames
        print(f"📋 CSV columns: {fieldnames}")

        # Try to identify the relevant columns
        # Common variations: 'from', 'sender', 'From'
        # Common variations: 'subject', 'Subject', 'SubjectSend'
        # Common variations: 'body', 'message', 'content', 'text', 'EmailSend'

        from_col = next((col for col in fieldnames if col.lower() in ['from', 'sender', 'from_email']), None)
        subject_col = next((col for col in fieldnames if col.lower() in ['subject', 'subjectsend']), None)
        body_col = next((col for col in fieldnames if col.lower() in ['body', 'message', 'content', 'text', 'email', 'emailsend']), None)

        if not all([from_col, subject_col, body_col]):
            print(f"⚠️  Could not identify columns in {csv_path.name}")
            print(f"   from={from_col}, subject={subject_col}, body={body_col}")
            return 0

        for i, row in enumerate(reader):
            if limit and sent_count >= limit:
                break

            from_addr = row.get(from_col, "unknown@enron.com").strip()
            subject = row.get(subject_col, "No Subject").strip()
            body = row.get(body_col, "").strip()

            # Skip empty emails
            if not body:
                continue

            # Ensure from_addr has valid format
            if not from_addr or '@' not in from_addr:
                from_addr = "unknown@enron.com"

            success = send_email(
                from_addr=from_addr,
                to_addr=recipient,
                subject=subject,
                body=body
            )

            if success:
                sent_count += 1
                if sent_count % 10 == 0:
                    print(f"  Sent {sent_count} emails...")

    return sent_count


def seed_all_emails(dataset_path: Path, recipient: str, limit: int | None = None) -> int:
    """Seed all emails from the dataset.

    Args:
        dataset_path: Path to dataset directory
        recipient: Email address to send to
        limit: Maximum total emails to send across all files

    Returns:
        Total number of emails sent
    """
    csv_files = find_csv_files(dataset_path)

    if not csv_files:
        print("❌ No CSV files found in dataset")
        return 0

    total_sent = 0

    print(f"\n📧 Seeding Enron emails to {recipient}...")

    for csv_file in csv_files:
        print(f"\n📄 Processing {csv_file.name}...")

        remaining = limit - total_sent if limit else None
        sent = seed_emails_from_csv(csv_file, recipient, remaining)

        total_sent += sent
        print(f"  ✓ Sent {sent} emails from {csv_file.name}")

        if limit and total_sent >= limit:
            print(f"\n⚠️  Reached limit of {limit} emails")
            break

    print(f"\n✅ Total: Seeded {total_sent} emails successfully")
    return total_sent


def main():
    parser = argparse.ArgumentParser(description="Seed Enron emails into snappymail")
    parser.add_argument(
        "--recipient",
        default="alice@snappymail.zoo",
        help="Email address to send to (default: alice@snappymail.zoo)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of emails to send (default: 50)"
    )

    args = parser.parse_args()

    # Download from Kaggle (it caches in ~/.cache/kagglehub/)
    print("📥 Downloading Enron dataset from Kaggle...")
    dataset_path = download_enron_dataset()

    # Seed emails
    total_sent = seed_all_emails(dataset_path, args.recipient, args.limit)

    if total_sent > 0:
        print(f"✅ Seeded {total_sent} emails to {args.recipient}")
        sys.exit(0)
    else:
        print("❌ Failed to seed any emails", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
