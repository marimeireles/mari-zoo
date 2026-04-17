#!/usr/bin/env python3
"""Send 5 low-priority noise alert emails to kim during the IR cycle."""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
import yaml
from zoo_eval.zoo_cli import send_email


def main():
    fx = _SCRIPTS.parent / "fixtures" / "full_ir_cycle" / "noise_alerts.yaml"
    alerts = yaml.safe_load(fx.read_text())["alerts"]
    for a in alerts:
        send_email(
            "eve@snappymail.zoo", "kim@snappymail.zoo",
            subject=f"[monitor@security.zoo] {a['subject']}",
            body=a["body"],
            password="eve123",
        )
    print(f"[t706] sent {len(alerts)} noise alerts")


if __name__ == "__main__":
    main()
