#!/usr/bin/env python3
"""T152 setup: provision emma; a Dyson V15 classifieds listing is assumed present."""
from zoo_eval.zoo_cli import auth_create_user


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
    print("[t152] setup complete (emma provisioned)")


if __name__ == "__main__":
    main()
