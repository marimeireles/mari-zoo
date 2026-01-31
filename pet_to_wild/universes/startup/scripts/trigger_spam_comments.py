#!/usr/bin/env python3
"""Trigger script that floods an issue with prompt injection attempts.

This simulates a spam attack where malicious actors try to extract
information from an AI agent through various injection techniques.

Note: Kept as script due to dynamic logic (find issue by title, loop over comments).
Data is loaded from fixtures/issue_spam_attack/spam_comments.yaml
"""

import time
from pathlib import Path

import yaml

from zoo_eval.auth import get_credential
from zoo_eval.zoo_cli import gitea_create_comment, gitea_list_issues


def load_spam_comments() -> list[str]:
    """Load spam comments from fixture file."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "issue_spam_attack" / "spam_comments.yaml"
    with open(fixture_path) as f:
        data = yaml.safe_load(f)
    return data["comments"]


def main():
    cred = get_credential("gitea", "mallory")
    spam_comments = load_spam_comments()

    # Find the factorial issue
    issues = gitea_list_issues(
        username=cred.username,
        password=cred.password,
        owner="bob",
        repo="math-helpers",
    )

    if not issues:
        print("No issues found in bob/math-helpers")
        return

    target_issue = None
    for issue in issues:
        if "factorial" in issue.get("title", "").lower():
            target_issue = issue
            break

    if not target_issue:
        print("Factorial issue not found")
        return

    issue_number = target_issue["number"]
    print(f"Found issue #{issue_number}: {target_issue['title']}")
    print(f"Flooding with {len(spam_comments)} injection attempts...")

    for i, comment in enumerate(spam_comments):
        try:
            gitea_create_comment(
                username=cred.username,
                password=cred.password,
                owner="bob",
                repo="math-helpers",
                issue_number=issue_number,
                body=comment,
            )
            print(f"  Posted injection #{i+1}")
            time.sleep(0.5)
        except Exception as e:
            print(f"  Failed to post #{i+1}: {e}")

    print("Spam attack complete!")


if __name__ == "__main__":
    main()
