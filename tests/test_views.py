from decimal import Decimal

import pytest

from listings.models import Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def good_listing(**fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, latitude=45.52, longitude=-122.68,
                title="Pearl condo", property_type="condo")
    base.update(fields)
    return make_listing(**base)


def test_list_page_shows_matching_listing_and_map_data(client):
    listing = good_listing()
    response = client.get("/")
    assert response.status_code == 200
    assert b"937 NW Glisan Street" in response.content
    assert response.context["map_points"][0]["id"] == listing.pk


def test_list_page_respects_query_filters(client):
    good_listing()
    response = client.get("/?min_beds=3")
    assert b"937 NW Glisan Street" not in response.content


def test_detail_page(client):
    listing = good_listing()
    response = client.get(f"/listing/{listing.pk}/")
    assert response.status_code == 200
    assert b"Pearl condo" in response.content
    assert listing.get_absolute_url() == f"/listing/{listing.pk}/"


def test_update_tracking_htmx_returns_partial(client):
    listing = good_listing()
    response = client.post(f"/listing/{listing.pk}/tracking/", {"status": "toured", "notes": "Great light"},
                           HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b"Saved" in response.content
    listing.refresh_from_db()
    assert (listing.status, listing.notes) == (Status.TOURED, "Great light")


def test_set_status_keeps_notes(client):
    listing = good_listing(notes="keep me")
    response = client.post(f"/listing/{listing.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    listing.refresh_from_db()
    assert (listing.status, listing.notes) == (Status.INTERESTED, "keep me")


def test_set_status_rejects_invalid(client):
    listing = good_listing()
    assert client.post(f"/listing/{listing.pk}/status/", {"status": "bogus"}).status_code == 400


def test_pages_send_referrer_to_map_tile_server(client):
    # OpenStreetMap blocks tile requests that arrive without a Referer header.
    response = client.get("/")
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert b"https://tile.openstreetmap.org/{z}/{x}/{y}.png" in response.content


def with_source(listing, key="zillow", name="Zillow"):
    from listings.models import Source, SourceListing

    source = Source.objects.get_or_create(key=key, defaults={"name": name, "platform": key})[0]
    SourceListing.objects.create(listing=listing, source=source, external_id=f"{key}-{listing.pk}", url="https://x.example/")
    return listing


def test_map_view_is_default_and_cards_show_source_badges(client):
    with_source(good_listing())
    content = client.get("/").content.decode()
    assert 'id="map"' in content
    assert 'class="source-badge">Zillow<' in content
    assert 'class="listing-table"' not in content


def test_list_view_uses_default_filters_and_renders_table(client):
    with_source(good_listing())
    make_listing(address_key="one-bed", street="1 One Bed St", beds=1, price=2000)
    response = client.get("/?view=list")
    content = response.content.decode()
    assert response.context["view"] == "list"
    assert 'class="listing-table"' in content
    assert 'id="map"' not in content
    assert "937 NW Glisan Street" in content and "1 One Bed St" not in content
    assert 'class="source-badge">Zillow<' in content


def test_view_toggle_links_keep_filters(client):
    good_listing()
    response = client.get("/?min_beds=3&sort=newest")
    assert "min_beds=3" in response.context["list_url"] and "view=list" in response.context["list_url"]
    assert 'name="view" value="map"' in response.content.decode()


def test_filter_by_source_from_query(client):
    with_source(good_listing(), key="pearl", name="Pearl")
    other = with_source(make_listing(address_key="z", street="2 Zillow Way", price=3000, beds=2, baths=Decimal("2"),
                                     parking_spaces=2, property_type="condo"))
    content = client.get("/?view=list&sources=zillow&min_beds=2").content.decode()
    assert "2 Zillow Way" in content and "937 NW Glisan Street" not in content
    assert other.pk
