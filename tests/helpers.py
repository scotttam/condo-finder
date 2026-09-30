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

    status = overrides.pop("status", None)
    notes = overrides.pop("notes", "")
    fields = dict(
        address_key="937 nw glisan st|435|97209",
        address="937 NW Glisan Street #435, Portland, OR 97209",
        street="937 NW Glisan Street",
        unit="435",
        city="Portland",
        zip_code="97209",
    )
    fields.update(overrides)
    listing = Listing.objects.create(**fields)
    if status:
        from listings.collab import set_status

        set_status(listing, home_group(), None, status)
    if notes:
        from listings.models import Comment

        Comment.objects.create(listing=listing, group=home_group(), author_name="Sam", body=notes)
    return listing


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


def home_group():
    """The owners' group: the oldest group, made by accounts' migration (re-made if a test flushed it)."""
    from accounts.groups import owners_group

    return owners_group()


def make_user(email, name, group=None, staff=False):
    from django.contrib.auth import get_user_model

    from accounts.models import Profile

    user = get_user_model().objects.create_user(username=email, email=email, password="pw", is_staff=staff)
    Profile.objects.create(user=user, group=group or home_group(), display_name=name)
    return user


def status_of(listing, group=None):
    from listings.collab import decorate

    return decorate([listing], group or home_group())[0].group_status
