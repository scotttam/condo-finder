import logging
import time
from dataclasses import dataclass
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


class Scraper:
    platform = ""

    def __init__(self, key, name, fetcher=None, request_delay=None, max_detail_fetches=None, **options):
        self.key = key
        self.name = name
        self.fetcher = fetcher or Fetcher(delay=request_delay)
        self.max_detail_fetches = max_detail_fetches
        self.known_ids = set()  # external ids whose listing already has a description (set by the runner)
        self.options = options

    def scrape(self):
        raise NotImplementedError

    def should_fetch_detail(self, item, fetched_so_far):
        if item.external_id in self.known_ids:
            return False
        return self.max_detail_fetches is None or fetched_so_far < self.max_detail_fetches


def is_candidate(item):
    """Worth a detail-page fetch and storing: target city and 2+ beds (or beds unknown)."""
    parsed = parse_address(item.address)
    city = parsed.city if parsed else item.city
    return bool(city) and is_target_city(city) and (item.beds is None or item.beds >= 2)
