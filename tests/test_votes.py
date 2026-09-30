from decimal import Decimal

import pytest
from django.test import Client

from accounts.groups import move_to_group, new_group
from listings.collab import set_vote
from listings.merge import merge
from listings.models import Vote
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db
UP, DOWN = Vote.Value.UP, Vote.Value.DOWN


def good_listing(key="good", **extra):
    return make_listing(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo",
                        latitude=45.52, longitude=-122.68, **extra)


def vote(browser, listing, value):
    return browser.post(f"/listing/{listing.pk}/vote/", {"value": value}, HTTP_HX_REQUEST="true").content.decode()


def test_voting_and_clicking_again_to_clear(client):
    listing = good_listing()
    html = vote(client, listing, "up")
    assert '<button type="submit" name="value" value="up" class="vote mine" aria-pressed="true"' in html
    assert Vote.objects.get().value == UP
    vote(client, listing, "up")
    assert not Vote.objects.exists()


def test_switching_keeps_one_vote(client):
    listing = good_listing()
    vote(client, listing, "up")
    vote(client, listing, "down")
    assert list(Vote.objects.values_list("value", flat=True)) == [DOWN]


def test_invalid_vote_is_refused(client):
    assert client.post(f"/listing/{good_listing().pk}/vote/", {"value": "meh"}).status_code == 400


def test_each_members_vote_shows_on_cards_table_and_listing_page(client, member_client):
    listing = good_listing()
    vote(client, listing, "up")
    vote(member_client, listing, "down")
    for url in ("/", "/?view=list", f"/listing/{listing.pk}/"):
        assert '<span class="muted vote-who">Sam 👍 · Alex 👎</span>' in client.get(url).content.decode(), url


def test_pins_show_how_the_group_voted(client, member_client):
    listing = good_listing()
    vote(client, listing, "up")
    vote(member_client, listing, "up")
    assert client.get("/").context["map_points"][0]["label"] == "👍 $3k"
    vote(member_client, listing, "down")
    assert client.get("/").context["map_points"][0]["label"] == "👍👎 $3k"


def test_other_groups_do_not_see_our_votes(client):
    listing = good_listing()
    vote(client, listing, "up")
    pat = Client()
    pat.force_login(make_user("pat@example.com", "Pat", group=new_group("Pat's search")))
    assert "Sam 👍" not in pat.get(f"/listing/{listing.pk}/").content.decode()


def test_a_vote_shows_in_the_group_feed(client, member_client):
    vote(member_client, good_listing(), "up")
    assert "Alex voted 👍" in client.get("/feed/").content.decode()


def test_leaving_a_group_removes_your_votes(member):
    set_vote(good_listing(), home_group(), member, UP)
    move_to_group(member, new_group("Alex's search"))
    assert not Vote.objects.exists()


def test_merge_keeps_one_vote_per_person(owner, member):
    keep, drop = good_listing("keep"), good_listing("drop")
    set_vote(keep, home_group(), owner, UP)
    set_vote(drop, home_group(), owner, DOWN)
    set_vote(drop, home_group(), member, UP)
    merge(keep, drop)
    assert sorted(Vote.objects.values_list("user__email", "value", "listing")) == [
        ("alex@example.com", UP, keep.pk), ("sam@example.com", UP, keep.pk)]
