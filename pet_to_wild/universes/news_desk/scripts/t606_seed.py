#!/usr/bin/env python3
"""Seed T606: 5 sources (email + miniflux + postmill + paste + outdated wiki)."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
import yaml
from zoo_eval.scene_helpers import (
    gitea_wiki_write, microbin_create_paste,
    miniflux_create_feed, miniflux_refresh_feed,
)
from zoo_eval.zoo_cli import (
    gitea_create_repo, gitea_add_file, send_email,
    postmill_login, postmill_create_forum, postmill_create_submission,
    postmill_create_comment,
)


def main():
    fx = _SCRIPTS.parent / "fixtures" / "big_investigation" / "sources.yaml"
    src = yaml.safe_load(fx.read_text())

    # 1. Email tip to alex_reporter
    send_email(
        "eve@snappymail.zoo", "alex_reporter@snappymail.zoo",
        subject=src["email_tip"]["subject"],
        body=src["email_tip"]["body"],
        password="eve123",
    )
    print("[t606] email tip delivered")

    # 2. Miniflux-hosted article (host as RSS in gitea, then subscribe)
    try:
        gitea_create_repo(
            "alex_reporter", "alex_reporterPass1!",
            name="rss-local-news",
            description="Local news RSS host",
            private=False, auto_init=True,
        )
    except Exception as e:
        print(f"[t606] repo: {e}")
    article_html = f"<h1>{src['miniflux_article']['title']}</h1>\n<p>{src['miniflux_article']['body']}</p>"
    feed_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
<channel>
<title>Local News</title>
<link>https://gitea.zoo/alex_reporter/rss-local-news</link>
<description>Local news feed</description>
<item>
<title>{src['miniflux_article']['title']}</title>
<link>https://gitea.zoo/alex_reporter/rss-local-news/raw/branch/main/riverbend.html</link>
<guid isPermaLink='false'>riverbend-plant3-2026</guid>
<pubDate>Tue, 14 Apr 2026 12:00:00 GMT</pubDate>
<description><![CDATA[{src['miniflux_article']['body']}]]></description>
</item>
</channel>
</rss>
"""
    for path, body in [("riverbend.html", article_html), ("feed.xml", feed_xml)]:
        try:
            gitea_add_file(
                "alex_reporter", "alex_reporterPass1!",
                "alex_reporter", "rss-local-news",
                path, body, message=f"seed {path}", branch="main",
            )
        except RuntimeError as e:
            if "already exists" not in str(e):
                raise
    feed_url = "https://gitea.zoo/alex_reporter/rss-local-news/raw/branch/main/feed.xml"
    try:
        feed = miniflux_create_feed(("alex_reporter", "alex_reporterPass1!"), feed_url)
        miniflux_refresh_feed(("alex_reporter", "alex_reporterPass1!"), feed.get("feed_id") or feed.get("id"))
        print(f"[t606] miniflux feed {feed}")
    except Exception as e:
        print(f"[t606] miniflux: {e}")

    # 3. Paste distractor
    paste_url = None
    try:
        paste_url = microbin_create_paste(
            f"TITLE: {src['paste_distractor']['title']}\n\n{src['paste_distractor']['body']}"
        )
        print(f"[t606] paste distractor at {paste_url}")
    except Exception as e:
        print(f"[t606] paste: {e}")

    # 4. Postmill thread
    host = postmill_login("alice", "alice123")
    try:
        postmill_create_forum(host, src["postmill_thread"]["forum"], "Local News", "Neighborhood tips and rumors")
    except Exception as e:
        print(f"[t606] forum: {e}")
    try:
        sub = postmill_create_submission(
            host, src["postmill_thread"]["forum"],
            src["postmill_thread"]["title"],
            src["postmill_thread"]["body"],
        )
        sub_id = sub.get("id")
    except Exception as e:
        print(f"[t606] submission: {e}")
        sub_id = None
    if not sub_id:
        subs = host.get_submissions(src["postmill_thread"]["forum"], limit=25)
        for s in subs:
            if s["title"] == src["postmill_thread"]["title"]:
                sub_id = s["id"]
                break
    users = ["bob", "charlie", "diana", "frank", "grace", "mallory"]
    if sub_id:
        for reply, user in zip(src["postmill_thread"]["replies"], users):
            body = reply
            if "paste" in reply.lower() and paste_url:
                body = f"{reply}\n\n{paste_url}"
            try:
                sess = postmill_login(user, f"{user}123")
                postmill_create_comment(sess, sub_id, body)
                print(f"[t606] reply by {user}")
            except Exception as e:
                print(f"[t606] reply {user}: {e}")

    # 5. Outdated wiki
    try:
        gitea_create_repo(
            "alex_reporter", "alex_reporterPass1!",
            name="newsroom-wiki",
            description="Newsroom background reference",
            private=False, auto_init=True,
        )
    except Exception as e:
        print(f"[t606] wiki repo: {e}")
    try:
        gitea_wiki_write(
            "alex_reporter", "alex_reporterPass1!",
            "alex_reporter", "newsroom-wiki",
            src["wiki_outdated"]["title"],
            src["wiki_outdated"]["body"],
        )
        print("[t606] outdated wiki seeded")
    except RuntimeError as e:
        if "already exists" in str(e):
            print("[t606] wiki already present")
        else:
            raise


if __name__ == "__main__":
    main()
