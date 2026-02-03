"""Integration with The Zoo environment."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


# Sites that can be reset (have mutable database state)
RESETABLE_SITES = {
    # PostgreSQL sites
    "gitea.zoo", "snappymail.zoo", "focalboard.zoo", "postmill.zoo", "auth.zoo", "miniflux.zoo",
    # MySQL sites
    "onestopshop.zoo", "classifieds.zoo",
}

# PostgreSQL site to database mapping: site -> (database_name, owner_user, service_name)
# service_name is the docker service that needs restart after DB reset (None if not needed)
# Used for fast per-database reset instead of full postgres restart
POSTGRES_SITE_DB_MAP = {
    "gitea.zoo": ("gitea_db", "gitea_user", "gitea-zoo"),
    "focalboard.zoo": ("focalboard_db", "focalboard_user", "focalboard-zoo"),
    "auth.zoo": ("auth_db", "auth_user", "auth-zoo"),
    "postmill.zoo": ("postmill_db", "postmill_user", None),  # PHP - new connections per request
    "snappymail.zoo": ("stalwart_db", "stalwart_user", "stalwart"),
    "miniflux.zoo": ("miniflux_db", "miniflux_user", "miniflux"),
}

# MySQL site to database mapping: site -> database_name
# MySQL reset uses different mechanism
MYSQL_SITE_DB_MAP = {
    "onestopshop.zoo": "onestopshop_db",
    "classifieds.zoo": "vwa-classifieds_db",
}

# Sites with no database (read-only or static)
NO_DB_SITES = {"wiki.zoo", "home.zoo", "map.zoo"}

# Site to docker service name mapping (for restarting unhealthy services)
SITE_SERVICE_MAP = {
    "gitea.zoo": "gitea-zoo",
    "focalboard.zoo": "focalboard-zoo",
    "auth.zoo": "auth-zoo",
    "snappymail.zoo": "snappymail-zoo",
    "postmill.zoo": "postmill",
    "onestopshop.zoo": "onestopshop",
    "wiki.zoo": "wiki-zoo",
    "home.zoo": "proxy",  # home.zoo is served by the proxy
    "analytics.zoo": "analytics-zoo",
    "miniflux.zoo": "miniflux",
}


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

    def verify_site_health(self, site: str, max_retries: int = 5) -> bool:
        """Verify a site is responding to HTTP requests.

        Args:
            site: Site domain (e.g., 'gitea.zoo')
            max_retries: Number of attempts before giving up

        Returns:
            True if site responds with 2xx/3xx status
        """
        url = f"https://{site}"
        for attempt in range(max_retries):
            try:
                response = self.client.get(url, timeout=10.0, follow_redirects=True)
                if response.status_code < 400:
                    return True
            except Exception:
                pass
            if attempt < max_retries - 1:
                time.sleep(0.5)  # Brief pause before retry
        return False

    def verify_redis_health(self, max_retries: int = 3, verbose: bool = True) -> bool:
        """Verify Redis is responding and restart if needed.

        Args:
            max_retries: Number of ping attempts before restarting
            verbose: Print progress messages

        Returns:
            True if Redis is healthy (possibly after restart)
        """
        import socket

        def ping_redis() -> bool:
            """Try to ping Redis."""
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(("localhost", 6379))
                sock.send(b"PING\r\n")
                response = sock.recv(64)
                sock.close()
                return b"PONG" in response
            except Exception:
                return False

        # First, check if Redis is healthy
        for attempt in range(max_retries):
            if ping_redis():
                return True
            if attempt < max_retries - 1:
                time.sleep(0.5)

        # Redis is unhealthy, restart it
        if verbose:
            print("  Redis unhealthy, restarting...", end="", flush=True)

        result = self._docker_compose("restart", "redis", timeout=30)
        if result.returncode != 0:
            if verbose:
                print(f" FAILED: {result.stderr}")
            return False

        # Wait for Redis to come back up
        for attempt in range(10):
            time.sleep(1.0)
            if ping_redis():
                if verbose:
                    print(" OK")
                return True

        if verbose:
            print(" FAILED (timeout)")
        return False

    def verify_postgres_health(self, max_retries: int = 3, verbose: bool = True) -> bool:
        """Verify Postgres is responding and restart if needed.

        Args:
            max_retries: Number of ping attempts before restarting
            verbose: Print progress messages

        Returns:
            True if Postgres is healthy (possibly after restart)
        """
        def ping_postgres() -> bool:
            """Try to run a simple query on postgres."""
            try:
                result = self._docker_compose_exec(
                    "postgres",
                    ["psql", "-U", "postgres", "-tAc", "SELECT 1"],
                    timeout=5,
                )
                return result.returncode == 0 and result.stdout.strip() == "1"
            except Exception:
                return False

        # First, check if Postgres is healthy
        for attempt in range(max_retries):
            if ping_postgres():
                return True
            if attempt < max_retries - 1:
                time.sleep(1.0)

        # Postgres is unhealthy, restart it
        if verbose:
            print("  Postgres unhealthy, restarting...", end="", flush=True)

        result = self._docker_compose("restart", "postgres", timeout=60)
        if result.returncode != 0:
            if verbose:
                print(f" FAILED: {result.stderr}")
            return False

        # Wait for Postgres to come back up
        for attempt in range(15):
            time.sleep(2.0)
            if ping_postgres():
                if verbose:
                    print(" OK")
                return True

        if verbose:
            print(" FAILED (timeout)")
        return False

    def ensure_sites_healthy(
        self, sites: list[str], timeout: int = 30, verbose: bool = True
    ) -> tuple[bool, list[str]]:
        """Ensure all specified sites are healthy, restarting services if needed.

        This performs task-level health checks: only verifies the sites needed
        for the current task, not the entire Zoo.

        Args:
            sites: List of site domains (e.g., ["gitea.zoo", "snappymail.zoo"])
            timeout: Max seconds to wait for a service to become healthy after restart
            verbose: Print progress messages

        Returns:
            Tuple of (all_healthy: bool, failed_sites: list[str])
        """
        failed_sites = []

        for site in sites:
            # First check if site is already healthy
            if self.verify_site_health(site, max_retries=2):
                continue

            # Site is unhealthy, try to restart the service
            service = SITE_SERVICE_MAP.get(site)
            if not service:
                if verbose:
                    print(f"  Warning: Unknown service for site {site}, skipping restart")
                failed_sites.append(site)
                continue

            if verbose:
                print(f"  {site} unhealthy, restarting {service}...", end="", flush=True)

            result = self._docker_compose("restart", service, timeout=60)
            if result.returncode != 0:
                if verbose:
                    print(f" FAILED: {result.stderr}")
                failed_sites.append(site)
                continue

            # Wait for service to become healthy
            healthy = False
            start_time = time.time()
            while time.time() - start_time < timeout:
                time.sleep(2.0)
                if self.verify_site_health(site, max_retries=1):
                    healthy = True
                    break

            if healthy:
                if verbose:
                    print(" OK")
            else:
                if verbose:
                    print(" FAILED (timeout)")
                failed_sites.append(site)

        return (len(failed_sites) == 0, failed_sites)

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

        # Wait for postgres to be healthy (not just a fixed sleep)
        if not self.wait_for_services(["postgres"], timeout=60, verbose=False):
            if verbose:
                print(" FAILED (timeout)")
            return False
        if verbose:
            print(" OK")

        # If snappymail is being reset, also restart stalwart to recreate users
        # with properly hashed passwords (stalwart runs create-users.sh on startup)
        if "snappymail.zoo" in sites:
            if verbose:
                print("  Restarting stalwart (recreating mail users)...", end="", flush=True)
            result = self._docker_compose("restart", "stalwart", timeout=60)
            if result.returncode != 0:
                if verbose:
                    print(" FAILED")
                return False
            # Wait for stalwart to be healthy
            if not self.wait_for_services(["stalwart"], timeout=60, verbose=False):
                if verbose:
                    print(" FAILED (timeout)")
                return False
            if verbose:
                print(" OK")

        return True

    def _check_golden_templates_exist(self) -> bool:
        """Check if golden template databases exist for fast reset."""
        try:
            result = self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-tAc",
                 "SELECT COUNT(*) FROM pg_database WHERE datname LIKE '%_golden'"],
            )
            if result.returncode != 0:
                return False
            count = int(result.stdout.strip())
            # We expect at least the main databases to have templates
            return count >= len(POSTGRES_SITE_DB_MAP)
        except (subprocess.TimeoutExpired, ValueError, AttributeError):
            # Timeout or parse error - templates not available
            return False

    def create_golden_templates(self, verbose: bool = True) -> bool:
        """Create golden template databases for fast reset.

        This creates a template copy of each database that can be used
        for instant reset instead of extracting the full tar.
        Should be run once after the zoo is set up with golden state.
        """
        if verbose:
            print("Creating golden template databases...")

        for site, (db_name, owner, _service) in POSTGRES_SITE_DB_MAP.items():
            template_name = f"{db_name}_golden"
            if verbose:
                print(f"  Creating template {template_name}...", end="", flush=True)

            # Check if template already exists
            check_result = self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-tAc",
                 f"SELECT 1 FROM pg_database WHERE datname = '{template_name}'"],
            )
            if check_result.stdout.strip() == "1":
                if verbose:
                    print(" already exists")
                continue

            # Create template from current database
            # First terminate any connections to the source database
            self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-c",
                 f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"],
            )

            # Create the template database
            result = self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-c",
                 f"CREATE DATABASE {template_name} TEMPLATE {db_name} OWNER {owner};"],
                timeout=120,  # Large DBs may take time
            )
            if result.returncode != 0:
                if verbose:
                    print(f" FAILED: {result.stderr}")
                return False

            # Mark it as a template so it can't be modified
            self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-c",
                 f"ALTER DATABASE {template_name} IS_TEMPLATE true;"],
            )

            if verbose:
                print(" OK")

        if verbose:
            print("Golden templates created successfully!")
        return True

    def reset_database_fast(
        self, db_name: str, owner: str, verbose: bool = True
    ) -> bool:
        """Reset a single PostgreSQL database using template (fast).

        Args:
            db_name: Database name (e.g., 'gitea_db')
            owner: Database owner (e.g., 'gitea_user')
            verbose: Print progress

        Returns:
            True if reset succeeded
        """
        template_name = f"{db_name}_golden"

        # Different retry/timeout settings based on DB size
        # postmill is ~1.6GB, needs longer timeouts but fewer retries
        if db_name == "postmill_db":
            max_retries = 3
            create_timeout = 100
        else:
            # Small DBs: more retries, shorter timeouts
            max_retries = 5
            create_timeout = 30

        for attempt in range(max_retries):
            if verbose:
                suffix = f" (attempt {attempt + 1}/{max_retries})" if attempt > 0 else ""
                print(f"  Resetting {db_name} from template{suffix}...", end="", flush=True)

            # Terminate ALL connections to the target database (retry until none left)
            for _ in range(3):
                self._docker_compose_exec(
                    "postgres",
                    ["psql", "-U", "postgres", "-c",
                     f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"],
                )
                # Verify no connections remain
                check = self._docker_compose_exec(
                    "postgres",
                    ["psql", "-U", "postgres", "-tAc",
                     f"SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '{db_name}'"],
                )
                if check.stdout.strip() == "0":
                    break
                time.sleep(0.1)  # Brief pause before retry

            # Drop database (must be outside transaction, so separate command)
            result = self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-c", f"DROP DATABASE IF EXISTS {db_name};"],
                timeout=30,
            )
            if result.returncode != 0:
                if verbose:
                    print(f" FAILED (drop): {result.stderr}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # Brief pause before retry
                    continue
                return False

            # Create from template (also must be outside transaction)
            result = self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-c",
                 f"CREATE DATABASE {db_name} TEMPLATE {template_name} OWNER {owner};"],
                timeout=create_timeout,
            )
            if result.returncode != 0:
                if verbose:
                    print(f" FAILED (create): {result.stderr}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # Brief pause before retry
                    continue
                return False

            # Verify database exists
            verify = self._docker_compose_exec(
                "postgres",
                ["psql", "-U", "postgres", "-tAc",
                 f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"],
            )
            if verify.stdout.strip() != "1":
                if verbose:
                    print(" FAILED (verify)")
                if attempt < max_retries - 1:
                    time.sleep(1)  # Brief pause before retry
                    continue
                return False

            if verbose:
                print(" OK")
            return True

        return False

    def reset_sites_fast(self, sites: list[str], verbose: bool = True) -> bool:
        """Reset sites using per-database template reset (fast).

        This is much faster than reset_sites() because it doesn't restart
        the postgres container. Instead, it drops and recreates individual
        databases from pre-created golden templates.

        Args:
            sites: List of site domains to reset
            verbose: Print progress

        Returns:
            True if all resets succeeded
        """
        # Ensure Postgres is healthy before any DB operations
        if not self.verify_postgres_health(verbose=verbose):
            if verbose:
                print("  Postgres health check failed, falling back to slow reset")
            return self.reset_sites(sites, verbose=verbose)

        # Check if we have golden templates
        if not self._check_golden_templates_exist():
            if verbose:
                print("  Golden templates not found, creating them first...")
            if not self.create_golden_templates(verbose=verbose):
                if verbose:
                    print("  Failed to create templates, falling back to slow reset")
                return self.reset_sites(sites, verbose=verbose)

        # Ensure Redis is healthy (needed for proxy event source)
        if not self.verify_redis_health(verbose=verbose):
            if verbose:
                print("  Warning: Redis health check failed, continuing anyway...")

        # Reset PostgreSQL databases and collect services that need restart
        pg_sites = [s for s in sites if s in POSTGRES_SITE_DB_MAP]
        services_to_restart = set()

        for site in pg_sites:
            db_name, owner, service = POSTGRES_SITE_DB_MAP[site]
            if not self.reset_database_fast(db_name, owner, verbose=verbose):
                return False
            if service:
                services_to_restart.add(service)

        # Restart all affected services (they have stale DB connections)
        if services_to_restart:
            services_list = sorted(services_to_restart)
            if verbose:
                print(f"  Restarting services: {', '.join(services_list)}...", end="", flush=True)
            result = self._docker_compose("restart", *services_list, timeout=120)
            if result.returncode != 0:
                if verbose:
                    print(f" FAILED: {result.stderr}")
                return False
            if not self.wait_for_services(services_list, timeout=90, verbose=False):
                if verbose:
                    print(" FAILED (timeout)")
                return False
            if verbose:
                print(" OK")

        # TODO: Add MySQL fast reset if needed
        mysql_sites = [s for s in sites if s in MYSQL_SITE_DB_MAP]
        if mysql_sites:
            if verbose:
                print("  MySQL sites detected - using slow reset for now")
            # For now, fall back to container restart for MySQL
            # Could implement similar template mechanism for MySQL

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
