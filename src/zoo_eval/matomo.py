"""
Matomo Analytics integration for The Zoo.

Provides access to tracked events from all Zoo sites via Matomo's API.
Events are tracked automatically by shared.js injected into all Zoo pages.

Tracked event types:
- Button: Click events with button text
- Form: Submit events with form ID and action
- Link: Click events with href
- AJAX: Success/Error with status code and URL
- Search: Query events
- Error: JavaScript errors
- Engagement: Scroll depth, time on page
"""

import os
import warnings
import requests
from dataclasses import dataclass
from typing import Optional


# Site ID mapping - must match shared.js in The Zoo
SITE_IDS = {
    "snappymail.zoo": 1,
    "gitea.zoo": 4,
    "auth.zoo": 5,
    "classifieds.zoo": 6,
    "excalidraw.zoo": 7,
    "focalboard.zoo": 8,
    "miniflux.zoo": 10,
    "northwind.zoo": 11,
    "wiki.zoo": 15,
    "onestopshop.zoo": 16,
    "postmill.zoo": 17,
    "example.zoo": 18,
    "home.zoo": 19,
    "misc.zoo": 20,
    "paste.zoo": 21,
}

# Event categories tracked by shared.js
EVENT_CATEGORIES = {
    "Button": "Button click events - name contains button text",
    "Form": "Form submit events - name format: formId|formAction",
    "Link": "Link click events - name contains href",
    "Click": "General click events - name format: elementId|class|text",
    "AJAX": "Fetch/XHR events - name format: statusCode|url",
    "Search": "Site search events",
    "Error": "JavaScript and Promise errors",
    "Engagement": "Scroll depth and time on page",
    "Performance": "Page load and DOM timing",
}


@dataclass
class MatomoEvent:
    """A tracked event from Matomo."""
    timestamp: str
    category: str
    action: str
    name: str

    def matches(self, category: Optional[str] = None, name_contains: Optional[str] = None) -> bool:
        """Check if event matches the given criteria."""
        if category and self.category != category:
            return False
        if name_contains and name_contains.lower() not in (self.name or "").lower():
            return False
        return True


class MatomoClient:
    """Client for querying Matomo analytics."""

    def __init__(self, proxy_url: Optional[str] = None, token: Optional[str] = None):
        self.proxy_url = proxy_url or os.environ.get("ZOO_PROXY_URL", "http://localhost:3128")
        self.matomo_url = "http://analytics.zoo/index.php"

        # Token resolution: explicit param > env var > default dev token
        if token:
            self.token = token
        elif os.environ.get("MATOMO_TOKEN"):
            self.token = os.environ["MATOMO_TOKEN"]
        else:
            # Default token matches the permanent token seeded in The Zoo's analytics_seed.sql
            # This is for local development only - do not use in production
            self.token = "zooeval_matomo_token_permanent"
            warnings.warn(
                "Using default Matomo dev token. Set MATOMO_TOKEN env var for production.",
                stacklevel=2,
            )

    def _request(self, params: dict) -> dict:
        """Make a request to Matomo API."""
        if self.token:
            params = {**params, "token_auth": self.token}
        try:
            response = requests.get(
                self.matomo_url,
                params={**params, "format": "json"},
                proxies={"http": self.proxy_url, "https": self.proxy_url},
                timeout=30,
                verify=False,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Matomo API error: {e}")
            return {}

    def get_events(self, site: str) -> list[MatomoEvent]:
        """
        Get all events from a site.

        Args:
            site: Site domain (e.g., 'gitea.zoo')

        Returns:
            List of MatomoEvent objects
        """
        site_id = SITE_IDS.get(site)
        if not site_id:
            print(f"Unknown site: {site}. Available: {list(SITE_IDS.keys())}")
            return []

        data = self._request({
            "module": "API",
            "method": "Live.getLastVisitsDetails",
            "idSite": site_id,
            "period": "day",
            "date": "today",
            "filter_limit": 500,
        })

        events = []
        for visit in data if isinstance(data, list) else []:
            for action in visit.get("actionDetails", []):
                if action.get("type") == "event":
                    events.append(MatomoEvent(
                        timestamp=action.get("timestamp", ""),
                        category=action.get("eventCategory", ""),
                        action=action.get("eventAction", ""),
                        name=action.get("eventName", ""),
                    ))
        return events

    def find_event(
        self,
        site: str,
        category: Optional[str] = None,
        name_contains: Optional[str] = None,
    ) -> Optional[MatomoEvent]:
        """
        Find first event matching criteria.

        Args:
            site: Site domain (e.g., 'gitea.zoo')
            category: Event category (e.g., 'Button', 'AJAX', 'Form')
            name_contains: Text to search for in event name (case-insensitive)

        Returns:
            First matching MatomoEvent or None

        Examples:
            # Find PR creation (AJAX success to pulls endpoint)
            find_event('gitea.zoo', category='AJAX', name_contains='/pulls')

            # Find button click
            find_event('gitea.zoo', category='Button', name_contains='Create Pull Request')

            # Find form submission
            find_event('gitea.zoo', category='Form', name_contains='compare')
        """
        for event in self.get_events(site):
            if event.matches(category, name_contains):
                return event
        return None

    def has_event(
        self,
        site: str,
        category: Optional[str] = None,
        name_contains: Optional[str] = None,
    ) -> bool:
        """Check if an event matching criteria exists."""
        return self.find_event(site, category, name_contains) is not None

    def get_page_views(self, site: str) -> list[dict]:
        """Get all page views from a site."""
        site_id = SITE_IDS.get(site)
        if not site_id:
            return []

        data = self._request({
            "module": "API",
            "method": "Live.getLastVisitsDetails",
            "idSite": site_id,
            "period": "day",
            "date": "today",
            "filter_limit": 500,
        })

        pages = []
        for visit in data if isinstance(data, list) else []:
            for action in visit.get("actionDetails", []):
                if action.get("type") == "action":
                    pages.append({
                        "timestamp": action.get("timestamp"),
                        "url": action.get("url"),
                        "title": action.get("pageTitle"),
                    })
        return pages

    def has_visited_url(self, site: str, url_contains: str) -> bool:
        """Check if a URL matching the pattern was visited."""
        for page in self.get_page_views(site):
            if url_contains.lower() in (page.get("url", "") or "").lower():
                return True
        return False


# Singleton instance
_client: Optional[MatomoClient] = None


def get_matomo_client() -> MatomoClient:
    """Get or create the Matomo client singleton."""
    global _client
    if _client is None:
        _client = MatomoClient()
    return _client


# Convenience functions
def get_events(site: str) -> list[MatomoEvent]:
    """Get all events from a site."""
    return get_matomo_client().get_events(site)


def find_event(site: str, category: Optional[str] = None, name_contains: Optional[str] = None) -> Optional[MatomoEvent]:
    """Find first event matching criteria."""
    return get_matomo_client().find_event(site, category, name_contains)


def has_event(site: str, category: Optional[str] = None, name_contains: Optional[str] = None) -> bool:
    """Check if an event matching criteria exists."""
    return get_matomo_client().has_event(site, category, name_contains)


def has_visited_url(site: str, url_contains: str) -> bool:
    """Check if a URL was visited."""
    return get_matomo_client().has_visited_url(site, url_contains)
