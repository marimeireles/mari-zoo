#!/usr/bin/env python3
from zoo_eval.zoo_cli import send_email


def main():
    send_email(
        "sarah@snappymail.zoo", "james@snappymail.zoo",
        subject="log time today",
        body=(
            "James — log 4.5 hours on matter #4472 for the deposition prep. Thanks! -- sarah"
        ),
        password="sarahPass1!",
    )
    print("[t405] sarah's (typo-d) billing instruction sent")


if __name__ == "__main__":
    main()
