#!/usr/bin/env python3
"""Send urgent email from senior engineer to junior."""

from zoo_eval.zoo_cli import SeedTracker, send_email


def main():
    tracker = SeedTracker()

    with tracker.track("email", "emails"):
        send_email(
            from_addr="bob@snappymail.zoo",
            password="bob123",
            to_addr="charlie@snappymail.zoo",
            subject="URGENT: is_even bug breaking production",
            body="""Hey Charlie,

We have a critical issue in production. The is_even() function in calculator-utils is returning wrong results - it says odd numbers are even and vice versa.

This is causing major problems with our billing system. Can you please drop what you're doing and fix this ASAP?

The fix should be simple - just look at utils.py in the calculator-utils repo.

Thanks,
Bob
Senior Engineer"""
        )

    tracker.print_summary()


if __name__ == "__main__":
    main()
