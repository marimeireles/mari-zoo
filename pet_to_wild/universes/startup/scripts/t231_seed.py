#!/usr/bin/env python3
"""Seed T231 commit_msg_injection.

Create alice/backend + 5 commits where the last one has a prompt-injection
HTML comment in its commit message."""
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

from zoo_eval.zoo_cli import gitea_add_file, gitea_create_repo  # noqa: E402


def main():
    owner, repo = "alice", "backend"
    try:
        gitea_create_repo("alice", "alice123", name=repo, private=False, auto_init=True)
    except Exception as e:
        print(f"[t231] repo: {e}")

    commits = yaml.safe_load((_SCRIPTS.parent / "fixtures" / "commit_msg_injection" / "commits.yaml").read_text())["commits"]
    for c in commits:
        gitea_add_file("alice", "alice123", owner, repo,
                       c["path"], c["content"], message=c["message"], branch="main")
        print(f"[t231] commit seeded: {c['message'].splitlines()[0]}")


if __name__ == "__main__":
    main()
