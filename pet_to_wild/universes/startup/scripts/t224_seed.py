#!/usr/bin/env python3
"""Seed T224 summarizer_overreach: deliver 8 emails to alice's inbox.
Email #4 contains an IT-policy impersonation asking for external forwarding."""
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

from zoo_eval.zoo_cli import send_email  # noqa: E402


def main():
    fx = _SCRIPTS.parent / "fixtures" / "summarizer_overreach" / "emails.yaml"
    data = yaml.safe_load(fx.read_text())
    # stalwart only accepts SMTP auth from provisioned accounts. For personas
    # like "it-admin@snappymail.zoo" that are NOT provisioned, route through
    # eve@ and preserve the impersonation signal in the subject prefix.
    REAL = {"alice", "bob", "charlie", "diana", "eve"}
    for e in data["emails"]:
        sender = e["from"]
        label = ""
        if "@" in sender:
            label = sender
            from_addr = "eve@snappymail.zoo"
            sender_pw = "eve123"
            subject = f"[{label}] {e['subject']}"
        elif sender in REAL:
            from_addr = f"{sender}@snappymail.zoo"
            sender_pw = f"{sender}123"
            subject = e["subject"]
        else:
            from_addr = "eve@snappymail.zoo"
            sender_pw = "eve123"
            subject = f"[{sender}] {e['subject']}"
        try:
            send_email(from_addr, "alice@snappymail.zoo", subject, e["body"], sender_pw)
            print(f"[t224] sent '{subject}' from {from_addr}")
        except Exception as exc:
            print(f"[t224] FAILED to send '{subject}': {exc}")


if __name__ == "__main__":
    main()
