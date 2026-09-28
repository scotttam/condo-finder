import importlib

import pytest
from django.apps import apps

from listings.ingest import ingest
from listings.models import Listing, PriceChange, SourceListing
from tests.helpers import make_source, scraped

pytestmark = pytest.mark.django_db

BUILDING = "1818 SW 4th Ave, Portland, OR 97201"
HIDDEN = "(undisclosed Address), Portland, OR 97225"


def test_units_from_one_site_at_the_same_address_stay_separate():
    source = make_source("craigslist")
    units = [scraped(external_id="u1", address=BUILDING, price=1899), scraped(external_id="u2", address=BUILDING, price=3457)]
    for _ in range(3):
        ingest(source, units)
    assert sorted(Listing.objects.values_list("price", flat=True)) == [1899, 3457]
    assert PriceChange.objects.count() == 2  # one "First seen" each; no phantom price changes


def test_hidden_addresses_never_merge():
    source = make_source("zillow")
    ingest(source, [scraped(external_id="z1", address=HIDDEN, price=2890), scraped(external_id="z2", address=HIDDEN, price=7193)])
    ingest(make_source("redfin"), [scraped(external_id="r1", address=HIDDEN, price=2890)])
    assert Listing.objects.count() == 3


def test_same_address_from_different_sites_still_merges():
    ingest(make_source("craigslist"), [scraped(external_id="c1", address=BUILDING, price=1899)])
    ingest(make_source("redfin"), [scraped(external_id="r1", address="1818 Southwest 4th Avenue, Portland, OR 97201", price=1899)])
    assert Listing.objects.count() == 1 and SourceListing.objects.count() == 2


def test_migration_splits_existing_merged_units():
    migration = importlib.import_module("listings.migrations.0003_fix_phantom_price_changes")
    craigslist, redfin = make_source("craigslist"), make_source("redfin")
    ingest(craigslist, [scraped(external_id="u1", address=BUILDING, price=1899)])
    base = Listing.objects.get()
    SourceListing.objects.create(listing=base, source=craigslist, external_id="u2", url="https://x.example/u2")  # old merge bug
    SourceListing.objects.create(listing=base, source=redfin, external_id="r1", url="https://x.example/r1")
    PriceChange.objects.create(listing=base, price=3457)  # the bogus flip
    hidden = Listing.objects.create(address_key="(undisclosed address)||97225", address=HIDDEN, street="(undisclosed Address)",
                                    city="Portland", zip_code="97225", price=7193)
    zillow = make_source("zillow")
    for ext in ("z1", "z2"):
        SourceListing.objects.create(listing=hidden, source=zillow, external_id=ext, url=f"https://x.example/{ext}")

    migration.split_same_source_units(apps, None)

    base.refresh_from_db()
    assert sorted(base.source_listings.values_list("external_id", flat=True)) == ["r1", "u1"]
    assert base.price is None and base.price_changes.count() == 0  # re-recorded on the next scrape
    moved = SourceListing.objects.get(external_id="u2").listing
    assert moved.pk != base.pk and moved.address_key == f"{base.address_key}|craigslist:u2"
    assert (moved.city, moved.street, moved.price) == ("Portland", base.street, None)
    hidden_keys = sorted(SourceListing.objects.filter(source=zillow).values_list("listing__address_key", flat=True))
    assert hidden_keys == ["(undisclosed address)||97225|zillow:z1", "(undisclosed address)||97225|zillow:z2"]
    hidden.refresh_from_db()
    assert hidden.is_active is False  # left with no sources


def test_split_listing_is_found_again_on_the_next_scrape():
    migration = importlib.import_module("listings.migrations.0003_fix_phantom_price_changes")
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="u1", address=BUILDING, price=1899)])
    base = Listing.objects.get()
    SourceListing.objects.create(listing=base, source=source, external_id="u2", url="https://x.example/u2")
    migration.split_same_source_units(apps, None)
    ingest(source, [scraped(external_id="u1", address=BUILDING, price=1899), scraped(external_id="u2", address=BUILDING, price=3457)])
    assert Listing.objects.count() == 2
    assert sorted(Listing.objects.values_list("price", flat=True)) == [1899, 3457]


PARK = "15 NW Park Ave, Portland, OR 97209"


def test_sites_disagreeing_on_price_is_not_a_price_change():
    redfin, craigslist = make_source("redfin"), make_source("craigslist")
    for _ in range(3):
        ingest(redfin, [scraped(external_id="r1", address=PARK, price=2929)])
        ingest(craigslist, [scraped(external_id="c1", address=PARK, price=2261)])
    listing = Listing.objects.get()
    assert listing.price == 2261  # lowest current price among the sites
    assert [(c.price, c.event) for c in listing.price_changes.all()] == [(2929, "First seen")]


def test_each_sites_own_change_is_recorded():
    redfin, craigslist = make_source("redfin"), make_source("craigslist")
    ingest(redfin, [scraped(external_id="r1", address=PARK, price=2929)])
    ingest(craigslist, [scraped(external_id="c1", address=PARK, price=2379)])
    ingest(craigslist, [scraped(external_id="c1", address=PARK, price=2261)])
    listing = Listing.objects.get()
    assert [(c.price, c.event, c.source) for c in listing.price_changes.all()] == [
        (2929, "First seen", "Redfin"),
        (2261, "Price change", "Craigslist"),
    ]
    assert listing.price == 2261 and listing.price_drop == 668


def test_price_override_still_wins():
    source = make_source("redfin")
    ingest(source, [scraped(external_id="r1", address=PARK, price=2929)])
    Listing.objects.update(overrides={"price": 2800})
    ingest(source, [scraped(external_id="r1", address=PARK, price=2929)])
    assert Listing.objects.get().price == 2800


def test_migration_clears_flip_flops_on_multi_site_listings_but_keeps_hand_entries():
    from datetime import datetime

    from django.utils import timezone

    migration = importlib.import_module("listings.migrations.0003_fix_phantom_price_changes")
    ingest(make_source("redfin"), [scraped(external_id="r1", address=PARK, price=2929)])
    ingest(make_source("craigslist"), [scraped(external_id="c1", address=PARK, price=2261)])
    listing = Listing.objects.get()
    PriceChange.objects.all().delete()
    first = listing.first_seen_at
    PriceChange.objects.create(listing=listing, price=2929, seen_at=first)  # old unlabeled observations (flip-flop)
    PriceChange.objects.create(listing=listing, price=2261, seen_at=first)
    typed = timezone.make_aware(datetime(2026, 8, 22, 12))
    PriceChange.objects.create(listing=listing, price=3100, seen_at=typed)  # entered by hand, before we saw it
    single = Listing.objects.create(address_key="single", address="1 Main St", street="1 Main St", city="Portland", price=2000)
    SourceListing.objects.create(listing=single, source=make_source("pearl"), external_id="p1", url="https://x.example/p1")
    PriceChange.objects.create(listing=single, price=2100, seen_at=single.first_seen_at)  # one site's real change: kept

    migration.split_same_source_units(apps, None)
    migration.clear_cross_site_flip_flops(apps, None)

    assert list(listing.price_changes.values_list("price", flat=True)) == [3100]
    assert single.price_changes.count() == 1


def test_migration_labels_old_observations_and_drops_repeats():
    from datetime import datetime, timedelta

    from django.utils import timezone

    migration = importlib.import_module("listings.migrations.0003_fix_phantom_price_changes")
    ingest(make_source("zillow"), [scraped(external_id="z1", price=4400)])
    listing = Listing.objects.get()
    PriceChange.objects.all().delete()
    first = listing.first_seen_at
    typed = timezone.make_aware(datetime(2026, 7, 4, 12))
    PriceChange.objects.create(listing=listing, price=4800, seen_at=typed)  # entered by hand: stays unlabeled
    PriceChange.objects.create(listing=listing, price=4400, seen_at=first - timedelta(days=6), event="Price change", source="Zillow")
    PriceChange.objects.create(listing=listing, price=4400, seen_at=first)  # old observation repeating the price
    PriceChange.objects.create(listing=listing, price=4300, seen_at=first + timedelta(days=1))  # old observed change

    migration.label_old_observations(apps, None)

    assert [(c.price, c.event, c.source) for c in listing.price_changes.all()] == [
        (4800, "", ""),
        (4400, "Price change", "Zillow"),
        (4300, "Price change", "Zillow"),
    ]
