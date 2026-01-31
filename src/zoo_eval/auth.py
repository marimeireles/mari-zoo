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


def get_credential(site: str, agent: str) -> Credential:
    """Get credential for an agent on a site.

    Args:
        site: Site name (e.g., "gitea.zoo" or "gitea")
        agent: Agent name (e.g., "bob")

    Returns:
        Credential object with username, password, etc.

    Raises:
        KeyError: If agent not found for site

    Example:
        >>> cred = get_credential("gitea", "bob")
        >>> cred.password
        'bob123'
    """
    # Normalize site name
    if not site.endswith(".zoo"):
        site = f"{site}.zoo"

    creds = load_credentials()
    site_creds = creds.get(site)
    if not site_creds:
        raise KeyError(f"Site '{site}' not found in credentials")

    for cred in site_creds.users:
        if cred.agent == agent:
            return cred

    raise KeyError(f"Agent '{agent}' not found for site '{site}'")


def get_credentials_for_agent(agent_name: str, allowed_sites: list[str]) -> str:
    """Get credentials as plain text for an agent prompt.

    Args:
        agent_name: Agent name (e.g., "alice")
        allowed_sites: Sites to include (e.g., ["gitea.zoo", "snappymail.zoo"])

    Returns:
        Human-readable credential string for agent prompts
    """
    lines = []
    for site in allowed_sites:
        try:
            cred = get_credential(site, agent_name)
            lines.append(f"- {site}: username '{cred.username}', password '{cred.password}'")
        except KeyError:
            continue

    if lines:
        return "Your login credentials:\n" + "\n".join(lines)
    return ""
