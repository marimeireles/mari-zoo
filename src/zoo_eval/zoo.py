"""Integration with The Zoo environment."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import httpx

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
    instance: str | None = None


class Zoo:
    """Interface to The Zoo environment."""

    def __init__(self, config: ZooConfig | None = None):
        self.config = config or ZooConfig()
        self._client: httpx.Client | None = None

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

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        """Run a Zoo CLI command."""
        cmd = ["npx", "the_zoo", *args]
        if self.config.instance:
            cmd.extend(["--instance", self.config.instance])
        return subprocess.run(cmd, capture_output=True, text=True)

    def is_running(self) -> bool:
        """Check if Zoo is running and accessible."""
        try:
            response = self.client.get("https://home.zoo")
            return response.status_code == 200
        except Exception:
            return False

    def reset_databases(self) -> bool:
        """Reset all databases to initial state."""
        result = self.run_cli("restart")
        return result.returncode == 0

    def restart(self) -> bool:
        """Restart Zoo environment (fast, ~2-3 seconds)."""
        result = self.run_cli("restart")
        return result.returncode == 0

    def query_postgres(self, query: str, database: str = "postgres") -> str:
        """Run a query against a PostgreSQL database.

        Args:
            query: SQL query to execute
            database: Database name (default: postgres)
        """
        result = self.run_cli("shell", "postgres", "-d", database, "-c", query)
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        return result.stdout

    def query_mysql(self, query: str, database: str = "mysql") -> str:
        """Run a query against a MySQL database.

        Args:
            query: SQL query to execute
            database: Database name (default: mysql)
        """
        result = self.run_cli("shell", "mysql", "-D", database, "-e", query)
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

    def fetch_page(self, url: str) -> str:
        """Fetch a page through the Zoo proxy."""
        resolved = self.resolve_url(url)
        response = self.client.get(resolved)
        return response.text

    def get_status(self) -> dict:
        """Get Zoo instance status."""
        result = self.run_cli("status")
        return {"running": result.returncode == 0, "output": result.stdout}

    def close(self):
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
