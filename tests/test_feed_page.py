from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from listings.models import FeedEvent, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db
_n = iter(range(1000))


def listing(**fields):
    base = dict(address_key=f"k{next(_n)}", street=f"{next(_n)} Test St", price=3000, beds=2, baths=Decimal("2"), property_type="condo")
    base.update(fields)
    return make_listing(**base)


def event(home, kind, when=None, summary="something"):
    when = when or timezone.now()
    return FeedEvent.objects.create(listing=home, kind=kind, summary=summary, happened_at=when, created_at=when)


def feed(client, query=""):
    return client.get(f"/feed/{query}")


def test_feed_is_a_top_level_page_next_to_listings(client):
    content = client.get("/").content.decode()
    assert content.index('href="/feed/"') > content.index(">Listings<") and content.index('href="/feed/"') < content.index(">Sources<")
    assert feed(client).status_code == 200


def test_shows_new_listings_and_updates_to_tracked_listings_only(client):
    fresh = listing(street="1 Fresh St")
    liked = listing(street="2 Liked St", status=Status.INTERESTED)
    untracked = listing(street="3 Untracked St")
    event(fresh, "new_listing")
    event(liked, "price_change", summary="Zillow: $3,200 → $3,000")
    event(untracked, "price_change", summary="should not show")
    content = feed(client).content.decode()
    assert "1 Fresh St" in content and "2 Liked St" in content and "Zillow: $3,200 → $3,000" in content
    assert "should not show" not in content


def test_rejected_listings_count_as_tracked(client):
    event(listing(street="4 Nope St", status=Status.REJECTED), "off_market", summary="No longer listed on any site")
    assert "4 Nope St" in feed(client).content.decode()


def test_apartments_hidden_by_default_with_a_toggle(client):
    event(listing(street="5 Complex Ave", property_type="apartment"), "new_listing")
    assert "5 Complex Ave" not in feed(client).content.decode()
    assert "5 Complex Ave" in feed(client, "?apartments=show").content.decode()


def test_tabs(client):
    event(listing(street="6 New St"), "new_listing")
    event(listing(street="7 Tracked St", status=Status.TOURED), "details_changed", summary="W/D: ? → ✓")
    new_tab = feed(client, "?tab=new").content.decode()
    updates_tab = feed(client, "?tab=updates").content.decode()
    assert "6 New St" in new_tab and "7 Tracked St" not in new_tab
    assert "7 Tracked St" in updates_tab and "6 New St" not in updates_tab


def test_price_change_label_says_drop_or_increase(client):
    home = listing(status=Status.INTERESTED)
    FeedEvent.objects.create(listing=home, kind="price_change", summary="down", old_price=3200, new_price=3000,
                             happened_at=timezone.now(), created_at=timezone.now())
    FeedEvent.objects.create(listing=home, kind="price_change", summary="up", old_price=3000, new_price=3100,
                             happened_at=timezone.now(), created_at=timezone.now())
    content = feed(client).content.decode()
    assert "↓ Price drop" in content and "↑ Price increase" in content


def test_unread_items_are_highlighted_and_visiting_marks_them_seen(client):
    old = event(listing(street="8 Old St"), "new_listing", when=timezone.now() - timedelta(days=3))
    event(listing(street="9 Recent St"), "new_listing")
    client.cookies["feed_seen_at"] = (timezone.now() - timedelta(days=1)).isoformat()
    response = feed(client)
    content = response.content.decode()
    assert content.count('class="feed-row unread"') == 1
    assert "feed_seen_at" in response.cookies
    assert old.pk  # the older item is still listed, just not unread
    assert "8 Old St" in content


def test_nav_badge_counts_unread_and_clears_after_visiting(client):
    event(listing(), "new_listing")
    event(listing(), "new_listing")
    event(listing(property_type="apartment"), "new_listing")  # hidden by default: not counted
    home = client.get("/").content.decode()
    assert 'class="nav-badge">2<' in home  # no cookie yet: the last 7 days count as unread
    feed(client)
    assert 'class="nav-badge"' not in client.get("/").content.decode()


def test_first_visit_treats_older_than_a_week_as_read(client):
    event(listing(), "new_listing", when=timezone.now() - timedelta(days=10))
    assert 'class="nav-badge"' not in client.get("/").content.decode()


def test_new_listing_rows_show_where_found_and_features(client):
    home = listing(street="10 Feature St", has_washer_dryer=True, parking_spaces=2)
    FeedEvent.objects.create(listing=home, kind="new_listing", summary="$3,000 · 2 bd", source="Zillow",
                             happened_at=timezone.now(), created_at=timezone.now())
    content = feed(client).content.decode()
    assert "Found on Zillow" in content and "W/D ✓" in content and "Parking 2" in content
