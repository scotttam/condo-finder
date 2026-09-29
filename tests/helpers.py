from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text, status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        import json

        return json.loads(self.text)


class FakeFetcher:
    """Stands in for scrapers.base.Fetcher; serves canned bodies by URL."""

    def __init__(self, pages, default=None):
        self.pages = pages
        self.default = default
        self.requested = []
        self.calls = []

    def request(self, method, url, **kwargs):
        self.requested.append(url)
        self.calls.append((method, url, kwargs))
        if url in self.pages:
            page = self.pages[url]
            return page if isinstance(page, FakeResponse) else FakeResponse(page)
        if self.default is not None:
            return self.default if isinstance(self.default, FakeResponse) else FakeResponse(self.default)
        raise httpx.HTTPError(f"no fake page for {url}")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs).text

    def get_json(self, url, **kwargs):
        return self.request("GET", url, **kwargs).json()


def make_listing(**overrides):
    from listings.models import Listing

    fields = dict(
        address_key="937 nw glisan st|435|97209",
        address="937 NW Glisan Street #435, Portland, OR 97209",
        street="937 NW Glisan Street",
        unit="435",
        city="Portland",
        zip_code="97209",
    )
    fields.update(overrides)
    return Listing.objects.create(**fields)


def scraped(**overrides):
    from decimal import Decimal

    from listings.scrapers.base import ScrapedListing

    fields = dict(
        external_id="a1",
        url="https://example.com/a1",
        address="937 NW Glisan Street #435, Portland, OR 97209",
        price=2800,
        beds=2,
        baths=Decimal("2"),
        sqft=1105,
        title="Pearl condo",
        description="2 bed 2 bath condo. 1 reserved parking space. In-unit washer/dryer. Balcony.",
    )
    fields.update(overrides)
    return ScrapedListing(**fields)


def make_source(key="pearl"):
    from listings.models import Source

    from listings.scrapers.registry import PLATFORMS

    platform = key if key in PLATFORMS else "appfolio"  # e.g. make_source("zillow") is a Zillow source
    return Source.objects.get_or_create(key=key, defaults={"name": key.title(), "platform": platform})[0]
