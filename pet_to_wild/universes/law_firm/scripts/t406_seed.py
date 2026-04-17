#!/usr/bin/env python3
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
from zoo_eval.scene_helpers import gitea_wiki_write
from zoo_eval.zoo_cli import gitea_create_repo


def main():
    try:
        gitea_create_repo("james", "jamesPass1!", name="firm-wiki", private=False, auto_init=True)
    except Exception as e:
        print(f"[t406] repo: {e}")
    body = (_SCRIPTS.parent / "fixtures" / "filing_procedure_poison" / "procedures.md").read_text()
    try:
        res = gitea_wiki_write("james", "jamesPass1!", "james", "firm-wiki", "Filing Procedures", body)
        print(f"[t406] wiki at {res.get('html_url')}")
    except RuntimeError as e:
        if "already exists" in str(e):
            print("[t406] wiki already present")
        else:
            raise


if __name__ == "__main__":
    main()
