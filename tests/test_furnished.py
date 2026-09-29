import re
from decimal import Decimal

import pytest

from listings import analyst
from listings.extract import is_furnished
from listings.ingest import ingest, reextract_all
from listings.models import Listing, PropertyType
from tests.helpers import make_listing, make_source, scraped

PILL = '<span class="furnished-pill">Furnished</span>'


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Welcome to The Connie, a newly built, fully furnished townhouse in Portland's Reed neighborhood.", True),
        ("FURNISHED 3 bed 1 bath + short term options", True),
        ("Stunning 4 bedroom 3 bathroom furnished corporate housing.", True),
        ("Monthly Furnished Rentals For 30 Nights Or More", True),
        ("The home comes furnished with a queen bed, sofa and desk.", True),
        ("Beautifully furnished 3-bedroom, 2.5-bath home.", True),
        ("Furnished. 31-night minimum lease.", True),
        ("This condo is unfurnished.", False),
        ("Pet Friendly, Unfurnished, Off Street Parking", False),
        ("No smoking. Not furnished.", False),
        ("*Some photos are virtually staged, furnishings are not included*", False),
        # Offered either way, or said of the building rather than the unit: not labeled.
        ("Available furnished or unfurnished.", None),
        ("$3,395 per month unfurnished, $3,795 per month fully furnished", None),
        ("Garage and two washers/dryers, and it comes fully furnished if desired.", None),
        ("Min one month, fully furnished option available for additional rent.", None),
        ("➢ Covered private balcony ➢ Furnished apartments available ➢ Kitchen island", None),
        ("✩ Dog washing station ✩ Furnished Apartment Homes ✩ Flex rent payment", None),
        ("The listing photos are unfurnished to protect the tenant's privacy; it is fully furnished as rented.", True),
        ("Office furnished with a functional work desk.", None),
        ("Ample room for furnishings and storage.", None),
        ("Granite counters", None),
    ],
)
def test_is_furnished(text, expected):
    assert is_furnished(text) is expected


def test_building_amenity_doesnt_hide_a_furnished_unit():
    text = "A fully furnished townhouse.\nCommunity amenities: Pet Friendly, Furnished Available"
    assert is_furnished(text) is True


@pytest.mark.django_db
def test_ingest_sets_furnished_and_override_wins():
    ingest(make_source(), [scraped(description="Fully furnished condo, utilities included.")])
    listing = Listing.objects.get()
    assert listing.is_furnished is True
    Listing.objects.update(overrides={"is_furnished": False})
    assert reextract_all() == 1
    listing.refresh_from_db()
    assert listing.is_furnished is False


@pytest.mark.django_db
def test_reextract_backfills_stored_listings():
    make_listing(description="A beautifully furnished 2-bed condo.")
    assert reextract_all() == 1
    assert Listing.objects.get().is_furnished is True


def listing(key, **fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type=PropertyType.CONDO,
                latitude=45.52, longitude=-122.68)
    base.update(fields)
    return make_listing(address_key=key, street=f"{key.title()} St", **base)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "choice,shown",
    [("any", {"Furnished St", "Empty St", "Unknown St"}), ("hide", {"Empty St", "Unknown St"}), ("only", {"Furnished St"})],
)
def test_furnished_filter(client, choice, shown):
    listing("furnished", is_furnished=True)
    listing("empty", is_furnished=False)
    listing("unknown", is_furnished=None)
    content = client.get(f"/?view=list&furnished={choice}").content.decode()
    assert {street for street in ("Furnished St", "Empty St", "Unknown St") if street in content} == shown


@pytest.mark.django_db
def test_filter_drawer_has_furnished_select(client):
    drawer = re.search(r'<details class="chip[^"]*" data-chip="more".*?</details>', client.get("/").content.decode(), re.S).group(0)
    assert re.search(r'Furnished <select name="furnished"[^>]*>', drawer)
    assert '<option value="hide">Hide furnished</option>' in drawer


@pytest.mark.django_db
@pytest.mark.parametrize("view", ["map", "list"])
def test_cards_and_table_label_furnished(client, view):
    listing("furnished", is_furnished=True)
    listing("empty", is_furnished=False)
    assert client.get(f"/?view={view}").content.decode().count(PILL) == 1


@pytest.mark.django_db
def test_listing_page_labels_furnished(client):
    furnished = listing("furnished", is_furnished=True)
    unknown = listing("unknown")
    assert PILL in client.get(f"/listing/{furnished.pk}/").content.decode()
    assert PILL not in client.get(f"/listing/{unknown.pk}/").content.decode()


@pytest.mark.django_db
def test_feed_new_listing_row_labels_furnished(client):
    ingest(make_source(), [scraped(description="Fully furnished condo.")])
    assert PILL in client.get("/feed/").content.decode()


@pytest.mark.django_db
def test_analyst_facts_include_furnished():
    assert analyst.compact_facts(listing("furnished", is_furnished=True))["furnished"] == "yes"
