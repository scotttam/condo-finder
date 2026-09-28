import importlib
from datetime import date, datetime, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from listings import runner
from listings.ingest import ingest
from listings.models import Listing, PriceChange, SourceListing
from listings.scrapers.base import ScrapedListing, Scraper
from tests.helpers import make_listing, make_source, scraped

pytestmark = pytest.mark.django_db

# Zillow's rental history for 10805 NW Cornell Rd (listing 924), 2026-09-28.
CORNELL_HISTORY = [(date(2026, 8, 22), 4800, "Listed for rent"), (date(2026, 9, 22), 4600, "Price change")]


def history(listing):
    return [(change.seen_at.date().isoformat(), change.price, change.event, change.source)
            for change in listing.price_changes.all()]


def local_noon(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=12))


def test_own_observations_are_labelled():
    source = make_source("pearl")
    now = timezone.now()
    ingest(source, [scraped(price=3000)], now=now)
    ingest(source, [scraped(price=2900)], now=now + timedelta(days=1))
    assert [(c.price, c.event, c.source) for c in Listing.objects.get().price_changes.all()] == [
        (3000, "First seen", "Pearl"),
        (2900, "Price change", "Pearl"),
    ]


def test_site_history_is_imported_with_listed_date():
    ingest(make_source("zillow"), [scraped(price=4600, price_history=CORNELL_HISTORY, listed_at=date(2026, 8, 22))])
    listing = Listing.objects.get()
    assert history(listing) == [
        ("2026-08-22", 4800, "Listed for rent", "Zillow"),
        ("2026-09-22", 4600, "Price change", "Zillow"),
    ]  # our own "First seen" at $4,600 is redundant with Zillow's Sep 22 entry and is dropped
    assert listing.listed_at == date(2026, 8, 22)


def test_history_import_is_idempotent_and_keeps_manual_entries():
    listing = make_listing(price=4600)
    PriceChange.objects.create(listing=listing, price=4800, seen_at=local_noon(date(2026, 8, 22)))  # entered by hand
    source = make_source("zillow")
    for _ in range(2):
        ingest(source, [scraped(price=4600, price_history=CORNELL_HISTORY)])
    assert history(listing) == [
        ("2026-08-22", 4800, "Listed for rent", "Zillow"),  # manual row kept, labelled from Zillow
        ("2026-09-22", 4600, "Price change", "Zillow"),
    ]


def test_first_seen_kept_when_history_does_not_explain_the_price():
    ingest(make_source("zillow"), [scraped(price=4500, price_history=CORNELL_HISTORY)])
    events = [event for _, _, event, _ in history(Listing.objects.get())]
    assert events == ["Listed for rent", "Price change", "First seen"]


def test_days_on_market_counts_from_the_listed_date():
    listing = make_listing(first_seen_at=timezone.now() - timedelta(days=2), listed_at=timezone.localdate() - timedelta(days=36))
    assert listing.days_on_market == 36
    assert make_listing(address_key="k2", first_seen_at=timezone.now() - timedelta(days=2)).days_on_market == 2


def test_ingest_records_details_version():
    source = make_source("zillow")
    ingest(source, [scraped(details_version=2)])
    ingest(source, [scraped()])  # a later run without detail fetch never lowers it
    assert SourceListing.objects.get().details_version == 2


def test_runner_refetches_details_when_the_parser_version_rises(monkeypatch):
    source = make_source("pearl")
    ingest(source, [scraped(external_id="old", details_version=1),
                    scraped(external_id="new", details_version=2, address="100 SW Main St, Portland, OR 97204")])
    captured = {}

    class Spy(Scraper):
        details_version = 2

        def scrape(self):
            captured["known"] = set(self.known_ids)
            return []

    monkeypatch.setattr(runner, "build_scraper", lambda config, fetcher=None: Spy(key="pearl", name="Pearl", fetcher=object()))
    runner.run_source({"key": "pearl", "name": "Pearl", "platform": "appfolio"})
    assert captured["known"] == {"new"}


def test_migration_marks_already_described_listings_as_detail_version_1():
    migration = importlib.import_module("listings.migrations.0002_price_history_and_details_version")
    source = make_source("zillow")
    ingest(source, [scraped(external_id="described"),
                    scraped(external_id="bare", description="", title="", address="100 SW Main St, Portland, OR 97204")])
    SourceListing.objects.update(details_version=0)
    migration.mark_described_as_version_1(apps, None)
    assert dict(SourceListing.objects.values_list("external_id", "details_version")) == {"described": 1, "bare": 0}


def test_scraped_listing_defaults():
    item = ScrapedListing(external_id="1", url="u", address="")
    assert (item.price_history, item.listed_at, item.details_version) == ([], None, 0)
