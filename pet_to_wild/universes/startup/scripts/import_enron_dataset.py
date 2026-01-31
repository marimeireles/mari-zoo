#!/usr/bin/env python3
"""Seed Enron email dataset into snappymail for realistic email tasks.

Downloads the full Enron email dataset from Kaggle and seeds it into the mail server.
"""

import argparse
import csv
import sys
from pathlib import Path

import kagglehub

from zoo_eval.auth import get_credential
from zoo_eval.zoo_cli import SeedTracker, send_email


def download_enron_dataset() -> Path:
    """Download Enron email dataset from Kaggle.

    Returns:
        Path to the downloaded dataset directory
    """
    path = kagglehub.dataset_download("oanannv/enron-email-reply-dataset")
    return Path(path)


def find_csv_files(dataset_path: Path) -> list[Path]:
    """Find all CSV files in the dataset directory."""
    csv_files = list(dataset_path.glob("**/*.csv"))
    print(f"Found {len(csv_files)} CSV file(s)")
    for f in csv_files:
        print(f"  - {f.name}")
    return csv_files


def seed_emails_from_csv(
    csv_path: Path, recipient: str, tracker: SeedTracker, limit: int | None = None
) -> int:
    """Seed emails from a CSV file into the mail server.

    Args:
        csv_path: Path to CSV file
        recipient: Email address to send to
        tracker: SeedTracker instance
        limit: Maximum number of emails to send (None = all)

    Returns:
        Number of emails successfully sent
    """
    sent_count = 0
    cred = get_credential("snappymail", "blake.sullivan")

    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        print(f"CSV columns: {fieldnames}")

        from_col = next((col for col in fieldnames if col.lower() in ['from', 'sender', 'from_email']), None)
        subject_col = next((col for col in fieldnames if col.lower() in ['subject', 'subjectsend']), None)
        body_col = next((col for col in fieldnames if col.lower() in ['body', 'message', 'content', 'text', 'email', 'emailsend']), None)

        if not all([from_col, subject_col, body_col]):
            print(f"Could not identify columns in {csv_path.name}")
            print(f"  from={from_col}, subject={subject_col}, body={body_col}")
            return 0

        for i, row in enumerate(reader):
            if limit and sent_count >= limit:
                break

            from_addr = row.get(from_col, "unknown@enron.com").strip()
            subject = row.get(subject_col, "No Subject").strip()
            body = row.get(body_col, "").strip()

            if not body:
                continue

            if not from_addr or '@' not in from_addr:
                from_addr = "unknown@enron.com"

            with tracker.track("email", "emails"):
                send_email(
                    from_addr=cred.username,
                    to_addr=recipient,
                    subject=f"[Enron Archive] {subject}",
                    body=f"Original sender: {from_addr}\n\n{body}",
                    password=cred.password,
                )
                sent_count += 1

            if sent_count % 10 == 0:
                print(f"  Sent {sent_count} emails...")

    return sent_count


def seed_all_emails(
    dataset_path: Path, recipient: str, tracker: SeedTracker, limit: int | None = None
) -> int:
    """Seed all emails from the dataset.

    Args:
        dataset_path: Path to dataset directory
        recipient: Email address to send to
        tracker: SeedTracker instance
        limit: Maximum total emails to send across all files

    Returns:
        Total number of emails sent
    """
    csv_files = find_csv_files(dataset_path)

    if not csv_files:
        print("No CSV files found in dataset")
        return 0

    total_sent = 0

    print(f"\nSeeding Enron emails to {recipient}...")

    for csv_file in csv_files:
        print(f"\nProcessing {csv_file.name}...")

        remaining = limit - total_sent if limit else None
        sent = seed_emails_from_csv(csv_file, recipient, tracker, remaining)

        total_sent += sent
        print(f"  Sent {sent} emails from {csv_file.name}")

        if limit and total_sent >= limit:
            print(f"\nReached limit of {limit} emails")
            break

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
    tracker = SeedTracker()

    print("Downloading Enron dataset from Kaggle...")
    dataset_path = download_enron_dataset()

    seed_all_emails(dataset_path, args.recipient, tracker, args.limit)
    tracker.print_summary()


if __name__ == "__main__":
    main()
