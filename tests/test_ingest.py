from datetime import timedelta

import pytest
from django.utils import timezone

from listings.ingest import ingest
from listings.models import Listing, PriceChange, SourceListing
from tests.helpers import make_source, scraped

pytestmark = pytest.mark.django_db


def test_creates_listing_with_extracted_features():
    result = ingest(make_source(), [scraped()])
    assert result.seen == 1 and len(result.new_listings) == 1
    listing = Listing.objects.get()
    assert listing.address_key == "937 nw glisan st|435|97209"
    assert listing.street == "937 NW Glisan Street"
    assert listing.price == 2800
    assert listing.parking_spaces == 1
    assert listing.has_washer_dryer is True
    assert listing.has_outdoor_space is True
    assert listing.has_ac is None
    assert listing.property_type == "condo"
    assert PriceChange.objects.get().price == 2800
    assert SourceListing.objects.get().url == "https://example.com/a1"


def test_skips_other_cities_and_small_units():
    result = ingest(make_source(), [
        scraped(external_id="x", address="1 Main St, Gresham, OR 97030"),
        scraped(external_id="y", beds=1),
        scraped(external_id="z", beds=None),
        scraped(external_id="w", address="call for address"),
    ])
    assert result.skipped == 4
    assert Listing.objects.count() == 0


def test_merges_same_unit_across_sources():
    ingest(make_source("pearl"), [scraped()])
    result = ingest(make_source("zillow"), [scraped(external_id="z9", url="https://zillow.example/z9",
                                                     address="937 Northwest Glisan St Unit 435, Portland, OR 97209")])
    assert result.new_listings == []
    assert Listing.objects.count() == 1
    assert Listing.objects.get().source_listings.count() == 2


def test_price_drop_is_recorded_and_reported():
    source = make_source()
    ingest(source, [scraped(price=3000)])
    result = ingest(source, [scraped(price=2750)])
    listing = Listing.objects.get()
    assert [p.price for p in listing.price_changes.all()] == [3000, 2750]
    assert result.price_drops == [(listing, 3000, 2750)]


def test_price_increase_recorded_not_reported():
    source = make_source()
    ingest(source, [scraped(price=2800)])
    result = ingest(source, [scraped(price=2900)])
    assert result.price_drops == []
    assert PriceChange.objects.count() == 2


def test_unchanged_price_adds_no_history():
    source = make_source()
    ingest(source, [scraped()])
    ingest(source, [scraped()])
    assert PriceChange.objects.count() == 1


def test_goes_off_market_after_three_missed_runs_and_can_return():
    source = make_source()
    other = scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204")
    ingest(source, [scraped(), other])
    for _ in range(2):
        ingest(source, [other])
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True
    ingest(source, [other])
    gone = Listing.objects.get(street="937 NW Glisan Street")
    assert gone.is_active is False
    ingest(source, [scraped(), other])
    gone.refresh_from_db()
    assert gone.is_active is True
    assert gone.source_listings.get().missed_runs == 0


def test_listing_stays_active_while_another_source_has_it():
    pearl, zillow = make_source("pearl"), make_source("zillow")
    other = scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204")
    ingest(pearl, [scraped(), other])
    ingest(zillow, [scraped(external_id="z1")])
    for _ in range(3):
        ingest(pearl, [other])
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True


def test_empty_run_does_not_mark_missing():
    source = make_source()
    ingest(source, [scraped()])
    for _ in range(3):
        ingest(source, [])
    assert Listing.objects.get().is_active is True


def test_manual_overrides_survive_rescrape():
    source = make_source()
    ingest(source, [scraped()])
    Listing.objects.update(overrides={"parking_spaces": 2, "has_ac": True})
    ingest(source, [scraped()])
    listing = Listing.objects.get()
    assert listing.parking_spaces == 2
    assert listing.has_ac is True


def test_known_feature_not_erased_by_source_without_info():
    ingest(make_source("pearl"), [scraped()])
    ingest(make_source("other"), [scraped(external_id="o1", description="Nice place", title="")])
    assert Listing.objects.get().has_washer_dryer is True


def test_first_seen_is_kept_and_last_seen_updates():
    source = make_source()
    earlier = timezone.now() - timedelta(days=2)
    ingest(source, [scraped()], now=earlier)
    ingest(source, [scraped()])
    listing = Listing.objects.get()
    assert listing.first_seen_at == earlier
    assert listing.last_seen_at > earlier


def test_ingest_sets_portland_quadrant():
    ingest(make_source(), [
        scraped(),
        scraped(external_id="bv", address="4775 SW Franklin Ave, Beaverton, OR 97005"),
    ])
    assert Listing.objects.get(city="Portland").quadrant == "NW"
    assert Listing.objects.get(city="Beaverton").quadrant == ""


def test_ingest_records_parking_presence_without_count():
    ingest(make_source(), [scraped(description="Parking: Attached garage. Laundry: In Unit")])
    listing = Listing.objects.get()
    assert (listing.has_parking, listing.parking_spaces, listing.has_washer_dryer) == (True, None, True)


def test_reextract_updates_stored_listings_and_keeps_overrides():
    from listings.ingest import reextract_all

    source = make_source()
    ingest(source, [scraped(description="Nice home.")])
    ingest(source, [scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204", description="Nice home.")])
    Listing.objects.filter(street="937 NW Glisan Street").update(
        description="Appliances: Refrigerator, Washer, and Dryer. Parking Garage Access.")
    Listing.objects.filter(street="100 SW Main St").update(
        description="Laundry: In Unit", overrides={"has_washer_dryer": False})
    assert reextract_all() == 2  # pearl gains W/D + parking; main gets its override applied
    assert reextract_all() == 0  # idempotent
    pearl = Listing.objects.get(street="937 NW Glisan Street")
    main = Listing.objects.get(street="100 SW Main St")
    assert (pearl.has_washer_dryer, pearl.has_parking) == (True, True)
    assert main.has_washer_dryer is False  # manual override wins
