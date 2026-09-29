import importlib
from datetime import date, datetime, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from listings.ingest import ingest, refresh_source_listing
from listings.models import FeedEvent, Listing, PriceChange
from tests.helpers import make_listing, make_source, scraped

pytestmark = pytest.mark.django_db
OTHER = scraped(external_id="other", address="100 SW Main St, Portland, OR 97204")


def kinds(listing=None):
    events = FeedEvent.objects.filter(listing=listing) if listing else FeedEvent.objects.all()
    return [event.kind for event in events.order_by("created_at", "pk")]


def glisan():
    return Listing.objects.get(street="937 NW Glisan Street")


def test_new_listing():
    ingest(make_source("zillow"), [scraped(price=2800, beds=2)])
    event = FeedEvent.objects.get()
    assert event.kind == "new_listing" and event.source == "Zillow"
    assert event.summary == "$2,800 · 2 bd · 2 ba · Condo"


def test_a_sites_own_price_change():
    source = make_source("zillow")
    ingest(source, [scraped(price=3000)])
    ingest(source, [scraped(price=2850)])
    event = FeedEvent.objects.get(kind="price_change")
    assert (event.old_price, event.new_price, event.summary) == (3000, 2850, "Zillow: $3,000 → $2,850")


def test_sites_disagreeing_is_not_a_price_change():
    ingest(make_source("redfin"), [scraped(external_id="r1", price=2929)])
    ingest(make_source("craigslist"), [scraped(external_id="c1", price=2261)])
    assert "price_change" not in kinds()


def test_history_revealing_a_change_on_a_known_listing_keeps_its_date():
    source = make_source("zillow")
    ingest(source, [scraped(price=4600)])
    ingest(source, [scraped(price=4600, price_history=[(date(2026, 8, 22), 4800, "Listed for rent"), (date(2026, 9, 22), 4600, "Price change")])])
    event = FeedEvent.objects.get(kind="price_change")
    assert event.happened_at.date() == date(2026, 9, 22) and event.created_at.date() == timezone.localdate()
    assert (event.old_price, event.new_price) == (4800, 4600)


def test_a_new_listings_own_history_is_not_announced_as_updates():
    ingest(make_source("zillow"), [scraped(price=4600, price_history=[(date(2026, 8, 22), 4800, "Listed for rent"), (date(2026, 9, 22), 4600, "Price change")])])
    assert kinds() == ["new_listing"]


def test_off_market_and_back():
    source = make_source("zillow")
    ingest(source, [scraped(), OTHER])
    for _ in range(3):
        ingest(source, [OTHER])
    ingest(source, [scraped(), OTHER])
    assert kinds(glisan()) == ["new_listing", "off_market", "back_on_market"]


def test_listed_on_another_site():
    ingest(make_source("zillow"), [scraped(external_id="z1")])
    ingest(make_source("redfin"), [scraped(external_id="r1")])
    event = FeedEvent.objects.get(kind="new_site")
    assert event.summary == "Now also on Redfin" and event.source == "Redfin"


def test_details_changed():
    source = make_source("zillow")
    ingest(source, [scraped(description="Nice place.", title="")])
    ingest(source, [scraped(description="Nice place with in-unit washer/dryer and central air.", title="")])
    event = FeedEvent.objects.get(kind="details_changed")
    assert event.summary == "W/D: ? → ✓ · AC: ? → ✓"


def test_refresh_that_finds_it_gone_is_off_market():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="c1")])
    refresh_source_listing(source.source_listings.get(), {"removed": True}, parser_version=1)
    assert kinds() == ["new_listing", "off_market"]


def test_backfill_seeds_price_changes_and_skips_the_initial_import():
    migration = importlib.import_module("listings.migrations.0004_feedevent")
    start = timezone.now() - timedelta(days=5)
    first = make_listing(address_key="first", street="1 First St", first_seen_at=start)  # part of the initial import
    later = make_listing(address_key="later", street="2 Later St", first_seen_at=start + timedelta(days=3), price=2500)
    at = lambda day: start + timedelta(days=day)
    PriceChange.objects.create(listing=first, price=3000, seen_at=at(0), event="First seen", source="Zillow")
    PriceChange.objects.create(listing=first, price=2900, seen_at=at(2), event="Price change", source="Zillow")
    FeedEvent.objects.all().delete()
    migration.seed_feed(apps, None)
    from listings.models import SourceListing

    SourceListing.objects.create(listing=later, source=make_source("redfin"), external_id="r9", url="https://x.example/r9",
                                 first_seen_at=later.first_seen_at)
    FeedEvent.objects.all().delete()
    migration.seed_feed(apps, None)
    new = FeedEvent.objects.get(kind="new_listing")
    assert new.listing_id == later.pk and new.created_at == later.first_seen_at and new.source == "Redfin"
    change = FeedEvent.objects.get(kind="price_change")
    assert (change.listing_id, change.old_price, change.new_price, change.created_at) == (first.pk, 3000, 2900, at(2))
