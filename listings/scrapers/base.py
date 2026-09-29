import logging
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx
from django.conf import settings

from ..address import is_target_city, parse_address

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


@dataclass
class ScrapedListing:
    external_id: str
    url: str
    address: str
    price: int | None = None
    beds: int | None = None
    baths: Decimal | None = None
    sqft: int | None = None
    title: str = ""
    description: str = ""
    amenities: str = ""
    property_type_hint: str = ""
    available: str = ""
    photo_url: str = ""
    city: str = ""  # used when search results give a city but no street address (Craigslist)
    latitude: float | None = None  # coordinates published by the listing site, when available
    longitude: float | None = None
    # From detail pages: [(date, price, event)] rental history, when the current listing started,
    # and which parser version produced the details (0 = details not fetched this run).
    price_history: list = field(default_factory=list)
    listed_at: date | None = None
    details_version: int = 0

    @property
    def full_text(self):
        return "\n".join(part for part in (self.title, self.description, self.amenities) if part)


class Fetcher:
    """Polite HTTP: waits `delay` seconds between requests and raises on HTTP errors."""

    def __init__(self, delay=None, client=None):
        self.delay = settings.REQUEST_DELAY_SECONDS if delay is None else delay
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=30,
        )
        self._last_request = 0.0

    def request(self, method, url, **kwargs):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.request(method, url, **kwargs)
        finally:
            self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs).text

    def get_json(self, url, **kwargs):
        return self.request("GET", url, **kwargs).json()


class RefreshBlocked(Exception):
    """The site is blocking requests (bot protection); try again later."""


class Scraper:
    platform = ""
    details_version = 1  # bump when detail parsing gains data, to re-fetch stored listings once

    def __init__(self, key, name, fetcher=None, request_delay=None, max_detail_fetches=None, **options):
        self.key = key
        self.name = name
        self.fetcher = fetcher if fetcher is not None else self.default_fetcher(request_delay)
        self.max_detail_fetches = max_detail_fetches
        self.known_ids = set()  # external ids already fetched by the current parser version (set by the runner)
        self.skip_detail_ids = set()  # external ids whose details come from another site (set by the runner)
        self.options = options

    def default_fetcher(self, request_delay):
        return Fetcher(delay=request_delay)

    def scrape(self):
        raise NotImplementedError

    def refresh_listing(self, url):
        """Fetch one listing's page now: {"price", "price_history", "listed_at", "description",
        "amenities", "baths"} (missing keys = not provided), or {"removed": True}. Raises
        RefreshBlocked when the site is blocking us. Sources without listing history don't implement it."""
        raise NotImplementedError

    def check_listing(self, url):
        """(still listed?, current price) for one listing page: True/False, or None when unknown.
        Sources that can confirm a listing directly override this; see ingest._mark_missing."""
        return None, None

    def should_fetch_detail(self, item, fetched_so_far):
        if item.external_id in self.known_ids or item.external_id in self.skip_detail_ids:
            return False
        return self.max_detail_fetches is None or fetched_so_far < self.max_detail_fetches


def detail_priority(item):
    """Sort key: listings the default filters would show get their detail pages fetched first."""
    looks_like_apartment = "apartment" in (item.property_type_hint or "").lower()
    in_budget = item.price is None or settings.DEFAULT_MIN_PRICE <= item.price <= settings.DEFAULT_MAX_PRICE
    return (looks_like_apartment, not in_budget)


def is_candidate(item):
    """Worth a detail-page fetch and storing: target city and 2+ beds (or beds unknown)."""
    parsed = parse_address(item.address)
    city = parsed.city if parsed else item.city
    return bool(city) and is_target_city(city) and (item.beds is None or item.beds >= 2)
