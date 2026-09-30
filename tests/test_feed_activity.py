from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from accounts.groups import new_group
from accounts.models import Profile
from listings.collab import set_status
from listings.models import FeedEvent, Status
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db
_n = iter(range(1000))


def listing(**fields):
    base = dict(address_key=f"a{next(_n)}", street=f"{next(_n)} Activity St", price=3000, beds=2, baths=Decimal("2"),
                property_type="condo")
    base.update(fields)
    return make_listing(**base)


def event(home, kind, summary="something"):
    now = timezone.now()
    return FeedEvent.objects.create(listing=home, kind=kind, summary=summary, happened_at=now, created_at=now)


def test_a_members_status_change_shows_in_the_group_feed(client, member_client):
    home = listing(street="1 Shared St")
    member_client.post(f"/listing/{home.pk}/status/", {"status": "toured"}, HTTP_HX_REQUEST="true")
    content = client.get("/feed/").content.decode()
    assert "Alex marked it Toured" in content
    assert '<span class="feed-kind kind-status">Status</span>' in content


def test_another_groups_activity_and_tracking_stay_private(client):
    pat = make_user("pat@example.com", "Pat", group=new_group("Pat's search"))
    home = listing(street="2 Private St")
    set_status(home, pat.profile.group, pat, Status.INTERESTED)
    event(home, "price_change", summary="Zillow: $3,200 → $3,000")
    content = client.get("/feed/").content.decode()
    assert "Pat marked it" not in content and "Zillow: $3,200 → $3,000" not in content


def test_own_activity_is_never_unread(client, owner):
    set_status(listing(), home_group(), owner, Status.TOURED)
    assert 'class="nav-badge"' not in client.get("/").content.decode()


def test_unread_state_is_per_person_and_follows_them_across_devices(client, owner, member_client):
    event(listing(), "new_listing")
    client.get("/feed/")
    phone = Client()
    phone.force_login(owner)
    assert 'class="nav-badge"' not in phone.get("/").content.decode()
    assert '<span class="nav-badge">1</span>' in member_client.get("/").content.decode()


def test_activity_tab_shows_only_the_groups_own_activity(client, member_client):
    home = listing(street="3 Tab St")
    event(listing(street="4 New St"), "new_listing")
    member_client.post(f"/listing/{home.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    content = client.get("/feed/?tab=activity").content.decode()
    assert "Alex marked it Interested" in content and "4 New St" not in content
    assert '<a href="?tab=activity" class="active">Activity</a>' in content


def test_apartment_filter_does_not_hide_our_own_activity(client, member_client):
    home = listing(street="5 Complex Ave", property_type="apartment")
    member_client.post(f"/listing/{home.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    assert "Alex marked it Interested" in client.get("/feed/").content.decode()


def test_nav_badge_polls_every_30_seconds(client):
    content = client.get("/").content.decode()
    assert '<span id="feed-badge" hx-get="/feed/badge/" hx-trigger="every 30s" hx-swap="outerHTML">' in content


def test_badge_endpoint_counts_without_marking_seen(client, owner):
    event(listing(), "new_listing")
    assert '<span class="nav-badge">1</span>' in client.get("/feed/badge/").content.decode()
    assert Profile.objects.get(user=owner).feed_seen_at is None
