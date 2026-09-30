from decimal import Decimal

import pytest
from django.test import Client

from accounts.groups import new_group
from listings.models import ListingState, Status
from tests.helpers import make_listing, make_user, status_of

pytestmark = pytest.mark.django_db


def good_listing(**extra):
    return make_listing(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo", **extra)


def shown(browser):
    return [listing.pk for listing in browser.get("/").context["listings"]]


def test_each_group_has_its_own_status(client):
    pat = make_user("pat@example.com", "Pat", group=new_group("Pat's search"))
    listing = good_listing()
    client.post(f"/listing/{listing.pk}/status/", {"status": "rejected"}, HTTP_HX_REQUEST="true")
    assert status_of(listing) == Status.REJECTED
    assert status_of(listing, pat.profile.group) == Status.NEW
    pat_browser = Client()
    pat_browser.force_login(pat)
    assert listing.pk not in shown(client)  # the default filters hide rejected listings
    assert listing.pk in shown(pat_browser)


def test_setting_a_status_records_who_and_when(client, owner):
    listing = good_listing()
    client.post(f"/listing/{listing.pk}/status/", {"status": "toured", "variant": "pills"}, HTTP_HX_REQUEST="true")
    state = ListingState.objects.get(listing=listing)
    assert state.status_by == owner and state.status_at is not None
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert '<p class="muted small status-by">Set by Sam · ' in content


def test_setting_the_same_status_again_keeps_who_set_it(client, member_client, owner):
    listing = good_listing()
    client.post(f"/listing/{listing.pk}/status/", {"status": "toured"}, HTTP_HX_REQUEST="true")
    member_client.post(f"/listing/{listing.pk}/status/", {"status": "toured"}, HTTP_HX_REQUEST="true")
    assert ListingState.objects.get().status_by == owner


def test_cards_and_pins_show_our_status(client):
    listing = good_listing(status=Status.INTERESTED, latitude=45.52, longitude=-122.68)
    response = client.get("/")
    content = response.content.decode()
    assert '<span class="status status-interested">Interested</span>' in content
    assert response.context["map_points"][0]["label"].startswith("♥ ")
