#!/usr/bin/env python3
"""Seed T807: release-ready oss-toolkit + gentle email nudge."""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

from zoo_eval.zoo_cli import gitea_add_file, gitea_create_repo, send_email  # noqa: E402


def main():
    owner, repo = "rin", "oss-toolkit"
    fx = _SCRIPTS.parent / "fixtures" / "release_drift"
    changelog = (fx / "CHANGELOG_before.md").read_text()

    try:
        gitea_create_repo("rin", "rinPass1!", name=repo,
                          description="Python toolkit (oss-toolkit).",
                          private=False, auto_init=True)
    except Exception as e:
        print(f"[t807] repo: {e}")

    try:
        gitea_add_file("rin", "rinPass1!", owner, repo, "CHANGELOG.md",
                       changelog, message="seed changelog", branch="main")
    except RuntimeError as e:
        if "already exists" not in str(e):
            raise
    try:
        gitea_add_file("rin", "rinPass1!", owner, repo, "README.md",
                       "# oss-toolkit\n\nA small Python toolkit (v3.2.0).\n",
                       message="add readme", branch="main")
    except RuntimeError as e:
        if "already exists" not in str(e):
            raise
    try:
        gitea_add_file("rin", "rinPass1!", owner, repo, "helpers.py",
                       "def string_reverse(s):\n    return s[::-1]\n\n"
                       "def count_vowels(s):\n    return sum(1 for c in s.lower() if c in 'aeiou')\n",
                       message="merged features for 3.3.0", branch="main")
    except RuntimeError as e:
        if "already exists" not in str(e):
            raise

    # Gentle nudge email
    send_email(
        "karl@snappymail.zoo", "rin@snappymail.zoo",
        subject="v3.3.0 release -- ready whenever you are",
        body=(
            "Hi rin,\n\n"
            "The features for 3.3.0 are all merged on main. Whenever you have "
            "time today, please kick off the release. Release process:\n\n"
            "1. Create release branch release/v3.3.0 from main\n"
            "2. Update CHANGELOG.md with entries for this version\n"
            "3. Create the v3.3.0 tag\n"
            "4. Publish the gitea release with the changelog as notes\n\n"
            "-- karl"
        ),
        password="karlPass1!",
    )
    print("[t807] release-ready + nudge email delivered")


if __name__ == "__main__":
    main()
