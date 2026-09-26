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

    @property
    def full_text(self):
        return "\n".join(part for part in (self.title, self.description, self.amenities) if part)


class Fetcher:
    """Polite HTTP GET: waits `delay` seconds between requests."""

    def __init__(self, delay=None, client=None):
        self.delay = settings.REQUEST_DELAY_SECONDS if delay is None else delay
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
        )
        self._last_request = 0.0

    def get(self, url):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.get(url)
        finally:
            self._last_request = time.monotonic()
        response.raise_for_status()
        return response.text


class Scraper:
    platform = ""

    def __init__(self, key, name, fetcher=None, **options):
        self.key = key
        self.name = name
        self.fetcher = fetcher or Fetcher()
        self.options = options

    def scrape(self):
        raise NotImplementedError


def is_candidate(item):
    """Worth a detail-page fetch and storing: target city and 2+ beds (or beds unknown)."""
    parsed = parse_address(item.address)
    return parsed is not None and is_target_city(parsed.city) and (item.beds is None or item.beds >= 2)
