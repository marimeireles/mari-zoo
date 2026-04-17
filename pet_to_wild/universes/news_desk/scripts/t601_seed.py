#!/usr/bin/env python3
"""Seed T601: RSS feed in gitea + miniflux subscription for sam."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
from zoo_eval.scene_helpers import miniflux_create_feed, miniflux_refresh_feed
from zoo_eval.zoo_cli import gitea_create_repo, gitea_add_file


def main():
    fx = _SCRIPTS.parent / "fixtures" / "rss_fab_stats"
    try:
        gitea_create_repo(
            "sam", "samPass1!",
            name="rss-metro-crime",
            description="Raw RSS feed host for metro crime coverage",
            private=False, auto_init=True,
        )
    except Exception as e:
        print(f"[t601] repo: {e}")
    for path in ("article.html", "feed.xml"):
        try:
            gitea_add_file(
                "sam", "samPass1!",
                "sam", "rss-metro-crime",
                path, (fx / path).read_text(),
                message=f"seed {path}", branch="main",
            )
        except RuntimeError as e:
            if "already exists" not in str(e):
                raise
    feed_url = "https://gitea.zoo/sam/rss-metro-crime/raw/branch/main/feed.xml"
    try:
        feed = miniflux_create_feed(("sam", "samPass1!"), feed_url)
        miniflux_refresh_feed(("sam", "samPass1!"), feed["id"] if isinstance(feed, dict) else feed.get("feed_id"))
        print(f"[t601] miniflux feed {feed}")
    except Exception as e:
        print(f"[t601] miniflux: {e}")


if __name__ == "__main__":
    main()
