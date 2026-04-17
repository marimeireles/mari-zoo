#!/usr/bin/env python3
"""T155: deliver 20 seed emails to emma."""
import time
from pathlib import Path
import yaml

from zoo_eval.zoo_cli import send_email, auth_create_user


def _provision_emma():
    """Ensure emma.lopez exists in auth.zoo (and therefore snappymail/stalwart)."""
    from zoo_eval.zoo_cli import auth_create_user
    try:
        auth_create_user(
            username="emma.lopez",
            email="emma.lopez@snappymail.zoo",
            name="Emma Lopez",
            password="Password.123",
        )
    except Exception as e:
        msg = str(e).lower()
        if "already" not in msg and "exists" not in msg:
            print(f"[provision] emma: {e}")


def main():
    _provision_emma()
    fx = Path(__file__).parent.parent / "fixtures" / "inbox_clutter" / "emails.yaml"
    emails = yaml.safe_load(fx.read_text())["emails"]
    for i, e in enumerate(emails):
        subj = f"[{e['from']}] {e['subject']}"
        try:
            send_email(
                "eve@snappymail.zoo", "emma.lopez@snappymail.zoo",
                subject=subj, body=e["body"], password="eve123",
            )
            print(f"[t155] {i+1}/20 ({e['from']})")
            time.sleep(0.2)
        except Exception as ex:
            print(f"[t155] {i+1} failed: {ex}")


if __name__ == "__main__":
    main()
