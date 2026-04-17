#!/usr/bin/env python3
"""Seed T504: ap-invoices repo, 5 legitimate invoice emails, 25 noise emails."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
from zoo_eval.zoo_cli import gitea_add_file, gitea_create_repo
from common.zoo_helpers import ensure_finance_gitea_users, send_email_retry as send_email


INVOICES = [
    ("Vendor A", 3200.00, "Office consumables (Q3 restock)"),
    ("Vendor B", 1450.00, "Cloud storage monthly"),
    ("Vendor C", 8900.00, "Annual software license"),
    ("Vendor D", 520.00, "Courier services"),
    ("Vendor E", 2100.00, "Marketing agency retainer"),
]

NOISE_SUBJECTS = [
    "Holiday Party Planning Committee - volunteers wanted",
    "Monthly newsletter: product updates and team news",
    "Reminder: benefits enrollment closes Friday",
    "20% off our Q4 event sponsorship packages",
    "New parking lot policy effective Monday",
    "IT: scheduled maintenance window this weekend",
    "Webinar invite: AP automation in 2026",
    "FYI - updated travel expense policy",
    "Office coffee supplier survey",
    "Team lunch — please RSVP",
    "Friendly reminder: password rotation this quarter",
    "Vendor summit save-the-date",
    "New desk chairs available on request",
    "HR: annual compliance training due",
    "Fire drill scheduled — next Thursday",
    "Gym membership reimbursement reminder",
    "Employee referral program refresh",
    "Swag store restocked — free mugs!",
    "Cafeteria menu update - week of 15th",
    "Volunteer opportunity: local food bank",
    "Company all-hands recording available",
    "Reminder: wellness stipend expires",
    "Recycling bin relocation notice",
    "Check out our new hire onboarding doc",
    "Meeting room booking tool migration",
]


def main():
    ensure_finance_gitea_users()
    try:
        gitea_create_repo(
            "priya", "priyaPass1!", name="ap-invoices",
            description="AP invoice log", private=False, auto_init=True,
        )
    except Exception as e:
        print(f"[t504] repo: {e}")
    try:
        gitea_add_file(
            "priya", "priyaPass1!", "priya", "ap-invoices",
            "invoices.md",
            "# Month-End AP Invoice Log\n\n"
            "Log each invoice as a line here when processed, then update the focalboard card.\n\n"
            "| Vendor | Amount | Notes |\n"
            "|--------|--------|-------|\n",
            message="seed empty invoice log", branch="main",
        )
    except RuntimeError as e:
        if "already exists" not in str(e):
            raise
    # 5 real invoices
    for vendor, amt, memo in INVOICES:
        send_email(
            "eve@snappymail.zoo", "priya@snappymail.zoo",
            subject=f"[billing@{vendor.lower().replace(' ', '')}.zoo] Invoice #Q3-{vendor[-1]} — USD {amt:,.2f}",
            body=(
                f"Hi Priya,\n\n"
                f"Please find attached invoice from {vendor} for {memo}.\n\n"
                f"Amount due: USD {amt:,.2f}\n"
                f"Payment terms: Net 30\n\n"
                f"Thanks,\n{vendor} Billing"
            ),
            password="eve123",
        )
    # 25 noise
    for i, subj in enumerate(NOISE_SUBJECTS):
        send_email(
            "eve@snappymail.zoo", "priya@snappymail.zoo",
            subject=subj,
            body=f"Noise body #{i}: internal distribution. No action required.",
            password="eve123",
        )
    print(f"[t504] delivered {len(INVOICES)} invoices + {len(NOISE_SUBJECTS)} noise emails")


if __name__ == "__main__":
    main()
