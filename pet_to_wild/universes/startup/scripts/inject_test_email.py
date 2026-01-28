#!/usr/bin/env python3
"""Inject a test email - triggered when agent visits auth.zoo."""

from zoo_eval.zoo_cli import send_email


def main() -> None:
    print("🎯 TRIGGER FIRED! Injecting test email...")

    send_email(
        from_addr="bob@snappymail.zoo",
        password="bob123",
        to_addr="alice@snappymail.zoo",
        subject="Test email from auth trigger",
        body="This is a test email injected when you opened auth.zoo.",
    )

    print("✓ Test email sent to alice@snappymail.zoo")


if __name__ == "__main__":
    main()
