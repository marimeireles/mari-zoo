"""Authentication credentials for Zoo sites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Credential:
    """Login credential for a site."""
    username: str
    password: str
    agent: str = ""  # Maps to universe agent name (e.g., "alice")
    note: str = ""


# Site name mapping from task config to Zoo domain
SITE_TO_DOMAIN = {
    "shopping": "onestopshop.zoo",
    "shopping_admin": "onestopshop.zoo",
    "reddit": "postmill.zoo",
    "gitlab": "gitea.zoo",
    "wikipedia": "wiki.zoo",
    "mail": "snappymail.zoo",
}

@dataclass
class SiteCredentials:
    """All credentials for a site."""
    users: list[Credential]
    admin: list[Credential]


_credentials_cache: dict[str, SiteCredentials] = {}


def load_credentials(credentials_dir: Path | None = None) -> dict[str, SiteCredentials]:
    """Load all credentials from YAML files."""
    global _credentials_cache

    if _credentials_cache:
        return _credentials_cache

    if credentials_dir is None:
        # Default to credentials/ relative to project root
        credentials_dir = Path(__file__).parent.parent.parent / "credentials"

    if not credentials_dir.exists():
        return {}

    for yaml_file in credentials_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        site = data.get("site", yaml_file.stem)

        def parse_creds(cred_data):
            if not cred_data:
                return []
            # Handle both list and single dict formats
            if isinstance(cred_data, dict):
                cred_data = [cred_data]
            return [
                Credential(
                    username=u["username"],
                    password=u["password"],
                    agent=u.get("agent", ""),
                    note=u.get("note", ""),
                )
                for u in cred_data
            ]

        _credentials_cache[site] = SiteCredentials(
            users=parse_creds(data.get("users")),
            admin=parse_creds(data.get("admin")),
        )

    return _credentials_cache


def get_credential_for_site(site: str) -> Credential | None:
    """Get the appropriate credential for a site.

    Args:
        site: Site name from task config (e.g., 'shopping_admin')

    Returns:
        Credential or None if not found
    """
    creds = load_credentials()

    # Map task site name to Zoo domain
    domain = SITE_TO_DOMAIN.get(site, site)
    is_admin = site.endswith("_admin")

    site_creds = creds.get(domain)
    if not site_creds:
        return None

    # Use admin creds for admin sites, otherwise regular users
    if is_admin and site_creds.admin:
        return site_creds.admin[0]
    elif site_creds.users:
        return site_creds.users[0]

    return None


def get_login_hint(sites: list[str]) -> str:
    """Generate login hint text for the agent.

    Args:
        sites: List of site names from task config

    Returns:
        Login instruction string or empty string
    """
    hints = []
    for site in sites:
        cred = get_credential_for_site(site)
        if cred:
            hints.append(f"Login with username '{cred.username}' and password '{cred.password}'")

    if hints:
        return ". ".join(hints) + ". "
    return ""


def get_sensitive_data_for_agent(
    agent_name: str,
    allowed_sites: list[str]
) -> dict[str, dict[str, str]]:
    """Build browser-use sensitive_data dict for an agent.

    Returns credentials scoped by domain. The agent will see placeholders
    like ['username', 'password'] and can use <secret>username</secret> to
    fill in the actual values.

    Args:
        agent_name: Universe agent name (e.g., "alice")
        allowed_sites: List of site domains the agent can access

    Returns:
        Dict in format: {"snappymail.zoo": {"username": "...", "password": "..."}}
    """
    creds = load_credentials()
    sensitive_data: dict[str, dict[str, str]] = {}

    for site in allowed_sites:
        domain = SITE_TO_DOMAIN.get(site, site)
        site_creds = creds.get(domain)
        if not site_creds:
            continue

        for cred in site_creds.users:
            if cred.agent == agent_name:
                sensitive_data[domain] = {
                    "username": cred.username,
                    "password": cred.password,
                }
                break

    return sensitive_data
