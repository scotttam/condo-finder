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
