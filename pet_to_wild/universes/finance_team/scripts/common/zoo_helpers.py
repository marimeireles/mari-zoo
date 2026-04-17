"""Shim: re-exports zoo_eval.scene_helpers for this universe + convenience ensure-user."""
import time
from zoo_eval.scene_helpers import *  # noqa: F401,F403
from zoo_eval.scene_helpers import (
    gitea_admin_create_user,
    gitea_user_exists,
)
from zoo_eval.zoo_cli import send_email as _send_email


def send_email_retry(from_addr: str, to_addr: str, subject: str, body: str,
                     password: str, retries: int = 12, delay: float = 5.0) -> None:
    """send_email wrapper that retries on rate-limit (Stalwart 452).

    Stalwart's per-recipient rate limit can block bursts for tens of seconds.
    Defaults give ~2 minutes of retry budget which is enough for typical scene seeding.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            _send_email(from_addr, to_addr, subject, body, password)
            return
        except Exception as e:
            last_err = e
            time.sleep(delay)
    if last_err:
        raise last_err


FINANCE_GITEA_USERS = [
    ("robert", "robertPass1!", "robert@gitea.zoo"),
    ("priya", "priyaPass1!", "priya@gitea.zoo"),
    ("tom", "tomPass1!", "tom@gitea.zoo"),
]


def ensure_finance_gitea_users(admin_user: str = "admin", admin_pass: str = "admin123") -> None:
    """Create robert/priya/tom on gitea via admin API (idempotent)."""
    for name, pw, email in FINANCE_GITEA_USERS:
        try:
            if gitea_user_exists(admin_user, admin_pass, name):
                continue
        except Exception:
            pass
        try:
            gitea_admin_create_user(admin_user, admin_pass, name, pw, email, full_name=name.title())
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg:
                continue
            print(f"[ensure_finance_gitea_users] {name}: {e}")
