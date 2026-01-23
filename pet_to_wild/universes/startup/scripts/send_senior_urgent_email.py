#!/usr/bin/env python3
"""Send urgent email from senior engineer to junior."""

from zoo_eval.zoo_cli import send_email_with_result


def main():
    result = send_email_with_result(
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

    if result.returncode == 0:
        print("Sent urgent email from senior to junior")
    else:
        print(f"Failed to send email: {result.stderr}")


if __name__ == "__main__":
    main()
