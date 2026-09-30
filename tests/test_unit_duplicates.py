from io import StringIO

import pytest
from django.core.management import call_command

from listings.ingest import ingest
from listings.merge import merge_unit_duplicates
from listings.models import FeedEvent, Listing, PriceChange, SourceListing, Status, TrendReport
from tests.helpers import make_source, scraped

pytestmark = pytest.mark.django_db

BARE = "821 NW 11th Ave, Portland, OR 97209"
UNIT = "821 NW 11th Ave #105, Portland, OR 97209"


def _home(**overrides):
    return scraped(**{"price": 3990, "sqft": 1425, **overrides})


def _duplicates():
    """The pair as it exists from before the fix: separate listings from Redfin and Zillow."""
    ingest(make_source("redfin"), [_home(external_id="r1", address=BARE)])
    bare = Listing.objects.get()
    Listing.objects.filter(pk=bare.pk).update(address_key="old-bare")  # hide it from ingest's matching
    ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    Listing.objects.filter(pk=bare.pk).update(address_key="821 nw 11th ave||97209")
    return Listing.objects.get(pk=bare.pk), Listing.objects.exclude(pk=bare.pk).get()


def test_unit_listing_joins_the_same_home_without_its_unit():
    ingest(make_source("redfin"), [_home(external_id="r1", address=BARE)])
    ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    listing = Listing.objects.get()
    assert listing.source_listings.count() == 2
    assert (listing.unit, listing.address_key) == ("105", "821 nw 11th ave|105|97209")
    assert FeedEvent.objects.filter(kind=FeedEvent.Kind.NEW_LISTING).count() == 1


def test_bare_listing_joins_the_unit_listing_and_keeps_its_unit():
    ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    for _ in range(2):
        ingest(make_source("redfin"), [_home(external_id="r1", address=BARE)])
        ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    listing = Listing.objects.get()
    assert listing.address == UNIT and listing.source_listings.count() == 2


def test_different_units_do_not_merge():
    ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    ingest(make_source("redfin"), [_home(external_id="r1", address=BARE, sqft=900, price=2500)])
    assert Listing.objects.count() == 2


def test_size_unknown_matches_on_price():
    ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    ingest(make_source("redfin"), [_home(external_id="r1", address=BARE, sqft=None)])
    ingest(make_source("craigslist"), [_home(external_id="c1", address=BARE.replace("821", "823"), sqft=None, price=1)])
    assert Listing.objects.filter(street="821 NW 11th Ave").count() == 1


def test_two_lookalike_units_are_ambiguous():
    zillow = make_source("zillow")
    ingest(zillow, [_home(external_id="z1", address=UNIT), _home(external_id="z2", address=UNIT.replace("105", "205"))])
    ingest(make_source("redfin"), [_home(external_id="r1", address=BARE)])
    assert Listing.objects.count() == 3


def test_same_site_never_matches_its_own_listing():
    redfin = make_source("redfin")
    ingest(redfin, [_home(external_id="r1", address=UNIT), _home(external_id="r2", address=BARE)])
    assert Listing.objects.count() == 2


def test_sweep_keeps_the_listing_with_notes_and_takes_the_unit_address():
    bare, unit = _duplicates()
    bare.notes, bare.status = "High ceilings.", Status.INTERESTED
    bare.save()
    PriceChange.objects.create(listing=unit, price=4100, event="Listed for rent", source="Zillow")
    report = TrendReport.objects.create(shortlist=[unit.pk], picks=[{"listing_id": unit.pk, "rank": 1}])

    merged = merge_unit_duplicates()

    assert merged == [(bare.pk, unit.pk, UNIT)]
    listing = Listing.objects.get()
    assert listing.pk == bare.pk and listing.notes == "High ceilings." and listing.status == Status.INTERESTED
    assert listing.address == UNIT and listing.address_key == "821 nw 11th ave|105|97209"
    assert sorted(SourceListing.objects.values_list("external_id", flat=True)) == ["r1", "z1"]
    assert listing.price_changes.filter(price=4100).exists()
    assert listing.price_changes.filter(event="First seen", price=3990).count() == 1  # same day, same price: one entry
    assert FeedEvent.objects.filter(kind=FeedEvent.Kind.NEW_LISTING).count() == 1
    report.refresh_from_db()
    assert report.shortlist == [bare.pk] and report.picks[0]["listing_id"] == bare.pk

    # Both sites scrape again without splitting it.
    ingest(make_source("redfin"), [_home(external_id="r1", address=BARE)])
    ingest(make_source("zillow"), [_home(external_id="z1", address=UNIT)])
    assert Listing.objects.get().address == UNIT


def test_sweep_keeps_the_unit_listing_when_only_it_was_touched():
    bare, unit = _duplicates()
    unit.overrides = {"parking_spaces": 2}
    unit.save()
    merge_unit_duplicates()
    assert Listing.objects.get().pk == unit.pk


def test_sweep_merges_notes_and_status_when_both_were_touched():
    bare, unit = _duplicates()
    Listing.objects.filter(pk=bare.pk).update(notes="High ceilings.", status=Status.INTERESTED)
    Listing.objects.filter(pk=unit.pk).update(notes="Toured Tuesday.", status=Status.TOURED, overrides={"has_ac": True})
    merge_unit_duplicates()
    listing = Listing.objects.get()
    assert listing.notes == "Toured Tuesday.\n\nHigh ceilings."
    assert listing.status == Status.TOURED and listing.overrides == {"has_ac": True}


def test_merge_duplicates_command_dry_run_changes_nothing():
    _duplicates()
    out = StringIO()
    call_command("merge_duplicates", "--dry-run", stdout=out)
    assert "Would merge 1 duplicate listings." in out.getvalue()
    assert Listing.objects.count() == 2
    call_command("merge_duplicates", stdout=StringIO())
    assert Listing.objects.count() == 1
