#!/usr/bin/env python3
"""Seed T709: host an RSS feed on gitea and subscribe miniflux to it."""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
import yaml
from zoo_eval.scene_helpers import miniflux_create_feed, miniflux_refresh_feed
from zoo_eval.zoo_cli import gitea_add_file, gitea_create_repo


FEED_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Security Advisories</title>
<link>https://gitea.zoo/jo/security-advisories</link>
<description>Curated security advisories feed.</description>
{items}
</channel></rss>"""


def build_feed(articles):
    items = []
    for i, a in enumerate(articles, start=1):
        items.append(
            "<item>"
            f"<title>{escape(a['title'])}</title>"
            f"<link>{escape(a['link'])}</link>"
            f"<guid isPermaLink=\"false\">advisory-{i}</guid>"
            f"<description>{escape(a['description'])}</description>"
            "</item>"
        )
    return FEED_TEMPLATE.format(items="\n".join(items))


def main():
    fx = _SCRIPTS.parent / "fixtures" / "miniflux_ti_compromise" / "articles.yaml"
    articles = yaml.safe_load(fx.read_text())["articles"]
    feed = build_feed(articles)
    try:
        gitea_create_repo("jo", "joPass1!", name="security-advisories",
                          description="Security advisories RSS feed",
                          private=False, auto_init=True)
    except Exception as e:
        print(f"[t709] repo: {e}")
    try:
        gitea_add_file("jo", "joPass1!", "jo", "security-advisories",
                       "feed.xml", feed, message="update feed", branch="main")
    except RuntimeError as e:
        if "already exists" in str(e):
            # Overwrite via update path by passing sha — but our helper only
            # supports create. Accept idempotent "already exists" here and
            # leave the existing feed.xml in place.
            print("[t709] feed.xml already exists — leaving it")
        else:
            raise
    feed_url = "https://gitea.zoo/jo/security-advisories/raw/branch/main/feed.xml"
    try:
        f = miniflux_create_feed(("admin", "zoopassword"), feed_url)
        print(f"[t709] miniflux feed id={f.get('feed_id') or f.get('id')}")
        fid = f.get("feed_id") or f.get("id")
        if fid:
            try:
                miniflux_refresh_feed(("admin", "zoopassword"), int(fid))
            except Exception as e:
                print(f"[t709] refresh: {e}")
    except Exception as e:
        print(f"[t709] miniflux subscribe: {e}")


if __name__ == "__main__":
    main()
