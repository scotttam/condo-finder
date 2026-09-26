from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Stands in for scrapers.base.Fetcher; serves canned HTML by URL."""

    def __init__(self, pages, default=None):
        self.pages = pages
        self.default = default
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url in self.pages:
            return self.pages[url]
        if self.default is not None:
            return self.default
        raise httpx.HTTPError(f"no fake page for {url}")


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

    return Source.objects.get_or_create(key=key, defaults={"name": key.title(), "platform": "appfolio"})[0]
