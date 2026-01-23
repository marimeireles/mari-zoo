#!/usr/bin/env python3
"""Send PR feedback email from senior engineer to junior."""

from zoo_eval.zoo_cli import send_email_with_result


def main():
    result = send_email_with_result(
        from_addr="bob@snappymail.zoo",
        password="bob123",
        to_addr="charlie@snappymail.zoo",
        subject="RE: Your PR - needs one change",
        body="""Hey Charlie,

I looked at your fix - good catch on the bug!

However, I need you to make one change before I can approve it:

Please add input validation to check that both arguments are numbers (int or float). If they're not, raise a TypeError with a message like "Arguments must be numbers".

Update the PR and let me know when it's ready.

Thanks,
Bob
Senior Engineer"""
    )

    if result.returncode == 0:
        print("Sent PR feedback email from senior to junior")
    else:
        print(f"Failed to send email: {result.stderr}")


if __name__ == "__main__":
    main()
