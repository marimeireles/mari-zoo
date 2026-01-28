#!/usr/bin/env python3
"""Create a test repo for alice to use in poll trigger test."""

from zoo_eval.zoo_cli import gitea_create_repo, SeedTracker


def main() -> None:
    tracker = SeedTracker()

    with tracker.track("gitea", "repos"):
        gitea_create_repo(
            username="alice",
            password="alice123",
            name="test-repo",
            description="Test repository for poll trigger",
            auto_init=True,
        )

    tracker.print_summary()


if __name__ == "__main__":
    main()
