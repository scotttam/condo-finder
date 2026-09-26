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
