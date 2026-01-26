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


def get_credentials_for_agent(
    agent_name: str,
    allowed_sites: list[str]
) -> str:
    """Get credentials as plain text for an agent to use.

    Args:
        agent_name: Universe agent name (e.g., "alice")
        allowed_sites: List of site domains the agent can access

    Returns:
        Human-readable credential instructions string
    """
    creds = load_credentials()
    credential_lines = []

    for site in allowed_sites:
        domain = SITE_TO_DOMAIN.get(site, site)
        site_creds = creds.get(domain)
        if not site_creds:
            continue

        for cred in site_creds.users:
            if cred.agent == agent_name:
                credential_lines.append(
                    f"- {domain}: username '{cred.username}', password '{cred.password}'"
                )
                break

    if credential_lines:
        return "Your login credentials:\n" + "\n".join(credential_lines)
    return ""
