"""Integration with The Zoo environment."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


# Sites that can be reset via postgres restart (restores golden tar)
# All Zoo sites have pre-seeded content, so TRUNCATE doesn't work
RESETABLE_SITES = {"gitea.zoo", "snappymail.zoo", "focalboard.zoo", "postmill.zoo"}


def _get_compose_project() -> str:
    """Auto-detect running Zoo docker compose project."""
    if env_project := os.environ.get("ZOO_COMPOSE_PROJECT_NAME"):
        return env_project

    try:
        # Filter for stalwart specifically - it has a simple name format: {project}-stalwart-{n}
        # Other containers like snappymail-zoo have compound service names that break parsing
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=stalwart"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            # Container name format: {project}-stalwart-{replica}
            # e.g., "the_zoo-stalwart-1" -> "the_zoo"
            container = result.stdout.strip().split("\n")[0]
            parts = container.rsplit("-", 2)
            if len(parts) >= 3:
                return parts[0]
    except Exception:
        pass

    return "the_zoo"


def _get_zoo_path() -> str | None:
    """Get path to the_zoo directory for docker compose commands."""
    # Check environment variable first
    if zoo_path := os.environ.get("THE_ZOO_PATH"):
        return zoo_path

    # Try to find as sibling of zoo-eval
    from pathlib import Path
    this_file = Path(__file__).resolve()
    zoo_eval_root = this_file.parent.parent.parent
    sibling_path = zoo_eval_root.parent / "the_zoo"
    if sibling_path.exists() and (sibling_path / "docker-compose.yml").exists():
        return str(sibling_path)

    return None


# URL mappings for WebArena-style placeholders
URL_MAPPINGS = {
    "__SHOPPING__": "https://onestopshop.zoo",
    "__SHOPPING_ADMIN__": "https://onestopshop.zoo/admin",
    "__REDDIT__": "https://postmill.zoo",
    "__GITLAB__": "https://gitea.zoo",
    "__MAP__": "https://map.zoo",  # Note: may need OSM setup
    "__WIKIPEDIA__": "https://wiki.zoo",
}


@dataclass
class ZooConfig:
    """Configuration for Zoo connection."""

    proxy_url: str = "http://localhost:3128"


class Zoo:
    """Interface to The Zoo environment."""

    def __init__(self, config: ZooConfig | None = None):
        self.config = config or ZooConfig()
        self._client: httpx.Client | None = None
        self._project: str | None = None

    @property
    def project(self) -> str:
        """Get the compose project name."""
        if self._project is None:
            self._project = _get_compose_project()
        return self._project

    @property
    def client(self) -> httpx.Client:
        """Lazy-loaded HTTP client with proxy."""
        if self._client is None:
            self._client = httpx.Client(
                proxy=self.config.proxy_url,
                verify=False,  # Zoo uses self-signed certs
                timeout=30.0,
            )
        return self._client

    def resolve_url(self, url: str) -> str:
        """Resolve WebArena-style URL placeholders."""
        for placeholder, real_url in URL_MAPPINGS.items():
            url = url.replace(placeholder, real_url)
        return url

    def _docker_compose(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        """Run a docker compose command."""
        cmd = ["docker", "compose", "-p", self.project] + list(args)
        # Run from the_zoo directory if available (required for compose commands)
        cwd = _get_zoo_path()
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)

    def _docker_compose_exec(
        self, service: str, command: list[str], timeout: int = 30
    ) -> subprocess.CompletedProcess:
        """Run a command inside a docker compose service."""
        cmd = ["docker", "compose", "-p", self.project, "exec", "-T", service] + command
        cwd = _get_zoo_path()
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)

    def is_running(self) -> bool:
        """Check if Zoo is running and accessible."""
        try:
            response = self.client.get("https://home.zoo")
            return response.status_code == 200
        except Exception:
            return False

    def reset_databases(self) -> bool:
        """Reset all databases to initial state."""
        result = self._docker_compose("restart")
        return result.returncode == 0

    def reset_sites(self, sites: list[str], verbose: bool = True) -> bool:
        """Reset sites to golden state by restarting postgres.

        Postgres restores from golden tar on restart, which resets all databases
        to their initial state (preserving user accounts and pre-seeded content).

        Args:
            sites: List of site domains to reset (e.g., ["gitea.zoo", "snappymail.zoo"])
            verbose: Print progress messages

        Returns:
            True if reset succeeded, False otherwise
        """
        # Check if any requested site needs reset
        if not any(site in RESETABLE_SITES for site in sites):
            return True

        if verbose:
            print("  Restarting postgres (restoring golden state)...", end="", flush=True)

        result = self._docker_compose("restart", "postgres", timeout=60)
        if result.returncode != 0:
            if verbose:
                print(" FAILED")
            return False

        # Wait for postgres to be ready
        time.sleep(10)
        if verbose:
            print(" OK")
        return True

    def restart(self, services: list[str] | None = None) -> bool:
        """Restart Zoo environment in correct dependency order.

        Args:
            services: Optional list of services to restart. If None, restarts all.
        """
        # Core infrastructure must start first
        core = ["coredns", "caddy", "postgres", "mysql", "redis", "proxy"]
        # Auth layer depends on core
        auth = ["hydra", "stalwart"]
        # Apps depend on core + auth
        apps = ["auth-zoo", "gitea-zoo", "focalboard-zoo", "snappymail-zoo", "wiki-zoo", "analytics-zoo"]

        if services:
            # Filter to only requested services, but maintain order
            core = [s for s in core if s in services]
            auth = [s for s in auth if s in services]
            apps = [s for s in apps if s in services]

        # Restart in stages, waiting for health checks between
        for stage_name, stage_services in [("core", core), ("auth", auth), ("apps", apps)]:
            if not stage_services:
                continue
            result = self._docker_compose("restart", *stage_services)
            if result.returncode != 0:
                print(f"Warning: Failed to restart {stage_name} services")
            # Wait for this stage to be healthy before next
            self.wait_for_services(stage_services, timeout=60)

        return True

    def wait_for_services(self, services: list[str], timeout: int = 60, verbose: bool = False) -> bool:
        """Wait for services to be healthy (or just 'Up' if no health check).

        Args:
            services: List of service names to wait for
            timeout: Maximum seconds to wait
            verbose: Print progress dots
        """
        if verbose:
            print(f"Waiting for services: {', '.join(services)}...", end="", flush=True)

        start = time.time()
        while time.time() - start < timeout:
            all_ready = True
            for service in services:
                result = self._docker_compose("ps", service, "--format", "{{.Status}}")
                if result.returncode != 0:
                    all_ready = False
                    break
                status = result.stdout.strip().lower()
                if not status or "unhealthy" in status or "starting" in status or "exited" in status:
                    all_ready = False
                    break
            if all_ready:
                if verbose:
                    print(" ready!")
                return True
            if verbose:
                print(".", end="", flush=True)
            time.sleep(2)

        if verbose:
            print(" timeout!")
        return False

    def query_postgres(self, query: str, database: str = "postgres") -> str:
        """Run a query against a PostgreSQL database.

        Args:
            query: SQL query to execute
            database: Database name (default: postgres)
        """
        result = self._docker_compose_exec(
            "postgres",
            ["psql", "-U", "postgres", "-d", database, "-c", query],
        )
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        return result.stdout

    def query_mysql(self, query: str, database: str = "mysql") -> str:
        """Run a query against a MySQL database.

        Args:
            query: SQL query to execute
            database: Database name (default: mysql)
        """
        result = self._docker_compose_exec(
            "mysql",
            ["mysql", "-u", "root", "-D", database, "-e", query],
        )
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        return result.stdout

    def list_postgres_databases(self) -> str:
        """List all PostgreSQL databases."""
        return self.query_postgres("\\l")

    def list_postgres_tables(self, database: str = "postgres") -> str:
        """List tables in a PostgreSQL database."""
        return self.query_postgres("\\dt", database)

    def list_mysql_databases(self) -> str:
        """List all MySQL databases."""
        return self.query_mysql("SHOW DATABASES;")

    def list_mysql_tables(self, database: str) -> str:
        """List tables in a MySQL database."""
        return self.query_mysql("SHOW TABLES;", database)

    def get_status(self) -> dict:
        """Get Zoo instance status."""
        result = self._docker_compose("ps", "--format", "json")
        return {
            "running": result.returncode == 0,
            "output": result.stdout,
        }

    def close(self):
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None


# Singleton instance
_zoo: Zoo | None = None


def get_zoo() -> Zoo:
    """Get or create the Zoo client singleton.

    Use this instead of Zoo() directly to avoid creating multiple instances,
    which is wasteful since Zoo includes HTTP clients and docker compose detection.
    """
    global _zoo
    if _zoo is None:
        _zoo = Zoo()
    return _zoo
