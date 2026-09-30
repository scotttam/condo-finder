import json
import re
from decimal import Decimal

import pytest

from listings import analyst
from listings.ingest import ingest
from listings.models import Listing, PropertyType, Status
from tests.helpers import home_group, make_listing, make_source, scraped

pytestmark = pytest.mark.django_db

OFFER = "4 WEEKS FREE on a 12-month lease!"


def special_listing(**extra):
    fields = dict(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type=PropertyType.CONDO,
                  special_offer=OFFER, latitude=45.52, longitude=-122.68)
    fields.update(extra)
    return make_listing(**fields)


def pill(content):
    return re.search(r'<span class="special-pill" title="([^"]*)">★ ([^<]*)</span>', content)


def test_card_shows_the_special(client):
    special_listing()
    content = client.get("/?view=map").content.decode()
    match = pill(content)
    assert match and match.groups() == (OFFER, "4 wks free")


def test_table_shows_the_special(client):
    special_listing()
    assert pill(client.get("/?view=list").content.decode())


def test_map_pin_is_marked(client):
    special_listing()
    content = client.get("/?view=map").content.decode()
    points = json.loads(re.search(r'<script id="map-points" type="application/json">(.*?)</script>', content, re.S).group(1))
    assert points[0]["label"] == "★$3k"
    assert "pin-special" in points[0]["classes"].split()


def test_listing_page_quotes_the_offer_and_effective_rent(client):
    listing = special_listing()
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert pill(content)
    assert f"“{OFFER}”" in content
    assert f"≈${listing.effective_rent:,}/mo over a 12-month lease" in content


def test_no_special_no_pill(client):
    listing = make_listing(price=3000)
    assert not pill(client.get(f"/listing/{listing.pk}/").content.decode())


def test_specials_only_filter(client):
    special_listing()
    make_listing(address_key="other", street="1 Other St", price=3000, beds=2, baths=Decimal("2"), parking_spaces=2,
                 property_type=PropertyType.CONDO)
    content = client.get("/?view=list&specials=on").content.decode()
    assert "937 NW Glisan Street" in content and "1 Other St" not in content
    drawer = re.search(r'<details class="chip[^"]*" data-chip="more".*?</details>', client.get("/").content.decode(), re.S).group(0)
    assert re.search(r'<input type="checkbox" name="specials"[^>]*> Move-in specials only', drawer)


def test_feed_new_listing_row_shows_the_special(client):
    ingest(make_source(), [scraped(description="Nice condo. 4 WEEKS FREE on a 12-month lease!")])
    assert pill(client.get("/feed/").content.decode())


def test_trends_facts_include_the_special():
    listing = special_listing()
    facts = analyst.compact_facts(analyst._prepare([listing], home_group())[0])
    assert facts["special_offer"] == OFFER
    assert facts["effective_rent_12mo"] == listing.effective_rent
