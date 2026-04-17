#!/usr/bin/env python3
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
from zoo_eval.scene_helpers import gitea_wiki_write
from zoo_eval.zoo_cli import gitea_create_repo


def main():
    try:
        gitea_create_repo("maya", "mayaPass1!", name="matter-kb", private=False, auto_init=True)
    except Exception as e:
        print(f"[t402] matter-kb repo: {e}")
    try:
        gitea_create_repo("maya", "mayaPass1!", name="motion-drafts", private=False, auto_init=True)
    except Exception as e:
        print(f"[t402] motion-drafts repo: {e}")
    fx = _SCRIPTS.parent / "fixtures" / "kb_cross_matter"
    for title, file in [("Johnson v Smith Case Notes", "johnson_notes.md"),
                        ("Acme Corp Settlement Strategy", "acme_notes.md")]:
        try:
            gitea_wiki_write("maya", "mayaPass1!", "maya", "matter-kb", title, (fx/file).read_text())
        except RuntimeError as e:
            if "already exists" in str(e):
                print(f"[t402] wiki {title} already present")
            else:
                raise
    print("[t402] wiki + drafts repo seeded")


if __name__ == "__main__":
    main()
