"""
Centralized interface to The Zoo CLI.

Automatically detects and uses:
- Dev version if ZOO_CLI_PATH is set
- Published version via npx otherwise

Handles all environment setup automatically.
"""

import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class EmailMessage:
    """Email message specification."""
    from_addr: str
    to_addr: str
    subject: str
    body: str
    password: str


class ZooCLI:
    """Interface to The Zoo CLI with automatic environment detection."""

    def __init__(self):
        """Initialize Zoo CLI interface."""
        self.cli_path = os.environ.get("ZOO_CLI_PATH")
        self.compose_project = self._detect_compose_project()

    def _detect_compose_project(self) -> str:
        """Auto-detect running Zoo docker compose project."""
        # Check env var first
        if env_project := os.environ.get("ZOO_COMPOSE_PROJECT_NAME"):
            return env_project

        # Try to detect from running containers
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=zoo"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                # Extract project name from container name
                # e.g., "thezoo-cli-instance-default-v0-7-0-proxy-1" -> "thezoo-cli-instance-default-v0-7-0"
                first_container = result.stdout.strip().split("\n")[0]
                parts = first_container.rsplit("-", 2)
                if len(parts) >= 2:
                    return "-".join(parts[:-2])
        except Exception:
            pass

        # Fallback
        return "the_zoo"

    def _get_command(self) -> List[str]:
        """Get CLI command based on environment."""
        if self.cli_path:
            return ["node", self.cli_path]
        return ["npx", "the_zoo"]

    def _build_env(self) -> dict:
        """Build environment for subprocess."""
        env = os.environ.copy()
        env["COMPOSE_PROJECT_NAME"] = self.compose_project

        # Automatically set ZOO_DEV=1 when using dev CLI
        if self.cli_path:
            env["ZOO_DEV"] = "1"

        return env

    def _run(self, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a Zoo CLI command."""
        cmd = self._get_command() + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._build_env(),
        )

    # === Email Commands ===

    def send_email(self, email: EmailMessage) -> bool:
        """
        Send an email via Zoo CLI.

        Args:
            email: EmailMessage with from_addr, to_addr, subject, body, password

        Returns:
            True if email sent successfully, False otherwise
        """
        result = self._run([
            "email", "send",
            "--from", email.from_addr,
            "--to", email.to_addr,
            "--subject", email.subject,
            "--body", email.body,
            "--password", email.password,
        ])
        return result.returncode == 0

    def get_send_email_result(self, email: EmailMessage) -> subprocess.CompletedProcess:
        """
        Send an email and return full result (for debugging).

        Args:
            email: EmailMessage with from_addr, to_addr, subject, body, password

        Returns:
            CompletedProcess with returncode, stdout, stderr
        """
        return self._run([
            "email", "send",
            "--from", email.from_addr,
            "--to", email.to_addr,
            "--subject", email.subject,
            "--body", email.body,
            "--password", email.password,
        ])

    def check_inbox(self, user: str, password: str) -> Optional[int]:
        """
        Check inbox message count.

        Args:
            user: Email address
            password: Email password

        Returns:
            Number of messages in inbox, or None if check failed
        """
        result = self._run([
            "email", "inbox",
            "--user", user,
            "--password", password,
        ])

        if result.returncode == 0 and result.stdout:
            # Parse "Messages: N" from output
            for line in result.stdout.split('\n'):
                if line.strip().startswith('Messages:'):
                    try:
                        return int(line.split(':')[1].strip())
                    except (ValueError, IndexError):
                        continue
        return None

    # === Gitea Commands (placeholder for future) ===

    def gitea_create_repo(self, name: str, owner: str, password: str) -> bool:
        """
        Create a Gitea repository.

        Args:
            name: Repository name
            owner: Repository owner username
            password: Owner's password

        Returns:
            True if repo created successfully, False otherwise
        """
        result = self._run([
            "gitea", "create-repo",
            "--name", name,
            "--owner", owner,
            "--password", password,
        ])
        return result.returncode == 0


# Singleton instance
_zoo_cli: Optional[ZooCLI] = None


def get_zoo_cli() -> ZooCLI:
    """Get or create Zoo CLI singleton."""
    global _zoo_cli
    if _zoo_cli is None:
        _zoo_cli = ZooCLI()
    return _zoo_cli


# === Convenience Functions ===

def send_email(from_addr: str, to_addr: str, subject: str, body: str, password: str) -> bool:
    """
    Send an email (convenience function).

    Args:
        from_addr: Sender email address
        to_addr: Recipient email address
        subject: Email subject
        body: Email body text
        password: Sender's password

    Returns:
        True if email sent successfully, False otherwise
    """
    cli = get_zoo_cli()
    email = EmailMessage(from_addr, to_addr, subject, body, password)
    return cli.send_email(email)


def send_email_with_result(from_addr: str, to_addr: str, subject: str, body: str, password: str) -> subprocess.CompletedProcess:
    """
    Send an email and return full result (for debugging).

    Args:
        from_addr: Sender email address
        to_addr: Recipient email address
        subject: Email subject
        body: Email body text
        password: Sender's password

    Returns:
        CompletedProcess with returncode, stdout, stderr
    """
    cli = get_zoo_cli()
    email = EmailMessage(from_addr, to_addr, subject, body, password)
    return cli.get_send_email_result(email)


def check_inbox(user: str, password: str) -> Optional[int]:
    """
    Check inbox message count (convenience function).

    Args:
        user: Email address
        password: Email password

    Returns:
        Number of messages in inbox, or None if check failed
    """
    cli = get_zoo_cli()
    return cli.check_inbox(user, password)
