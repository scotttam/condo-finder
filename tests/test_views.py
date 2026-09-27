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


def many_listings(count):
    for i in range(count):
        make_listing(address_key=f"k{i}", street=f"{i} Test St", price=2000 + i, beds=2, baths=Decimal("2"),
                     parking_spaces=2, property_type="condo", latitude=45.5, longitude=-122.6)


def test_results_are_paginated_with_links_that_keep_filters(client):
    many_listings(60)
    response = client.get("/?view=list&sort=price&min_beds=2")
    page = response.context["page_obj"]
    assert page.paginator.count == 60 and len(page.object_list) == 50
    assert "60 listings" in response.content.decode()
    next_url = response.context["next_url"]
    assert "page=2" in next_url and "view=list" in next_url and "min_beds=2" in next_url
    assert response.context["prev_url"] == ""
    second = client.get("/" + next_url)
    assert [listing.street for listing in second.context["listings"]][:1] == ["50 Test St"]
    assert len(second.context["listings"]) == 10


def test_page_only_query_still_uses_default_filters(client):
    many_listings(55)
    make_listing(address_key="one-bed", street="1 One Bed St", beds=1, price=1000)
    response = client.get("/?page=2")
    assert response.context["page_obj"].number == 2
    assert response.context["page_obj"].paginator.count == 55


def test_out_of_range_page_shows_last_page(client):
    many_listings(60)
    assert client.get("/?view=list&page=99").context["page_obj"].number == 2


def test_map_shows_every_match_not_just_the_page(client):
    many_listings(60)
    response = client.get("/")
    assert len(response.context["map_points"]) == 60
    assert response.content.decode().count('class="card"') == 50


def test_filters_apply_on_change_without_button(client):
    content = client.get("/").content.decode()
    assert 'hx-get="/"' in content and 'hx-target="#results"' in content and 'hx-push-url="true"' in content
    assert 'id="results"' in content
    assert "Apply filters" not in content.replace("<noscript>", "\0").split("\0")[0]


def test_quadrant_shown_on_card_table_and_detail(client):
    listing = good_listing(quadrant="NW", neighborhood="Pearl District")
    assert "Portland · NW · Pearl District" in client.get("/").content.decode()
    assert "Portland · NW · Pearl District" in client.get(f"/listing/{listing.pk}/").content.decode()


def test_quadrant_filter_in_sidebar(client):
    content = client.get("/").content.decode()
    for value in ("NW", "NE", "SE", "SW", "N", "S"):
        assert f'name="quadrants" value="{value}"' in content


def test_list_view_has_quadrant_column(client):
    good_listing(quadrant="NW", neighborhood="Pearl District")
    content = client.get("/?view=list").content.decode()
    assert "<th>Quadrant</th>" in content
    assert '<td class="quadrant">NW</td>' in content
    assert "Portland · Pearl District" in content  # quadrant has its own column, so not repeated here


def test_back_link_returns_to_last_view_filters_and_page(client):
    listing = good_listing()
    client.get("/?view=list&min_beds=2&sort=newest&page=1")
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert 'href="/?view=list&amp;min_beds=2&amp;sort=newest&amp;page=1">← Back to listings' in content
    assert 'href="/?view=list&amp;min_beds=2&amp;sort=newest&amp;page=1">Listings</a>' in content


def test_bare_url_reopens_last_used_view(client):
    good_listing()
    assert client.get("/").context["view"] == "map"
    client.get("/?view=list")
    assert client.get("/").context["view"] == "list"
    client.get("/?view=map")
    assert client.get("/").context["view"] == "map"


def test_back_link_defaults_to_listings_home(client):
    listing = good_listing()
    assert 'href="/">← Back to listings' in client.get(f"/listing/{listing.pk}/").content.decode()


def test_parking_present_without_count_is_labeled(client):
    listing = good_listing(parking_spaces=None, has_parking=True)
    assert "parking (spaces ?)" in client.get("/").content.decode()
    assert "Yes (spaces ?)" in client.get("/?view=list").content.decode()
    assert "Yes, number of spaces not stated" in client.get(f"/listing/{listing.pk}/").content.decode()


def test_reextract_command(capsys):
    from django.core.management import call_command

    call_command("reextract")
    assert "Updated 0 listings" in capsys.readouterr().out
