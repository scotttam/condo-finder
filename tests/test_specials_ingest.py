import pytest

from listings.ingest import ingest, reextract_all
from listings.models import FeedEvent, Listing
from tests.helpers import make_source, scraped

pytestmark = pytest.mark.django_db


def glisan():
    return Listing.objects.get(street="937 NW Glisan Street")


def test_scrape_records_a_special_and_clears_it_when_it_ends():
    source = make_source()
    ingest(source, [scraped(description="Lovely condo. 4 WEEKS FREE on a 12-month lease! Pets ok.")])
    listing = glisan()
    assert listing.special_offer == "4 WEEKS FREE on a 12-month lease!"
    assert listing.special_label == "4 wks free"
    assert listing.effective_rent == round((2800 * 12 - 2800 * 28 / 30.4) / 12)
    ingest(source, [scraped(description="Lovely condo. Pets ok.")])
    assert glisan().special_offer == ""


def test_special_in_the_title_counts():
    ingest(make_source(), [scraped(title="$500 OFF first month! Pearl condo", description="Nice place.")])
    assert glisan().special_label == "$500 off"


def test_override_can_clear_a_false_special():
    source = make_source()
    ingest(source, [scraped(description="Move-in special!")])
    Listing.objects.update(overrides={"special_offer": ""})
    ingest(source, [scraped(description="Move-in special!")])
    assert glisan().special_offer == ""


def test_reextract_backfills_specials_on_stored_listings():
    ingest(make_source(), [scraped(description="Nice home.")])
    Listing.objects.update(description="Nice home. 6 weeks free!")
    assert reextract_all() == 1
    assert glisan().special_label == "6 wks free"


def test_no_special_means_no_label_or_effective_rent():
    ingest(make_source(), [scraped(description="Nice home.")])
    listing = glisan()
    assert listing.special_label == "" and listing.effective_rent is None


def test_a_new_special_shows_in_the_feed():
    source = make_source("zillow")
    ingest(source, [scraped(description="Nice place.", title="")])
    ingest(source, [scraped(description="Nice place. 1 month free!", title="")])
    event = FeedEvent.objects.get(kind="details_changed")
    assert event.summary == "Special: none → 1 mo free"
