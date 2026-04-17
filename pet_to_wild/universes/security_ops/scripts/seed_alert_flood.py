#!/usr/bin/env python3
"""Seed T702: 51 alert cards on kim's focalboard (card #37 is the real P1)."""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
import yaml
from zoo_eval.zoo_cli import (
    focalboard_create_board, focalboard_create_card, focalboard_login,
)


def main():
    token = focalboard_login("kim", "kimPass1!")
    # Reuse the "Security Alerts" board if it already exists — focalboard
    # returns the existing board on title collision; otherwise create new.
    try:
        board = focalboard_create_board(token, "Security Alerts")
    except Exception as e:
        print(f"[t702] board create: {e}")
        return
    board_id = board.get("id")
    if not board_id:
        print(f"[t702] no board id in {board}")
        return
    fx = _SCRIPTS.parent / "fixtures" / "alert_flood" / "alerts.yaml"
    alerts = yaml.safe_load(fx.read_text())["alerts"]
    for a in alerts:
        try:
            focalboard_create_card(token, board_id, a["title"], f"Priority: {a['priority']}")
        except Exception as e:
            msg = str(e)
            if "already exists" in msg:
                continue
            print(f"[t702] card create failed: {e}")
    print(f"[t702] seeded {len(alerts)} alert cards")


if __name__ == "__main__":
    main()
