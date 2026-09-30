import pytest

from listings.models import PriceChange
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def listing_with_history():
    listing = make_listing(price=3000)
    return listing, PriceChange.objects.create(listing=listing, price=3100)


def test_members_cannot_change_shared_data(member_client):
    listing, change = listing_with_history()
    posts = [
        f"/listing/{listing.pk}/refresh/",
        f"/listing/{listing.pk}/history/add/",
        f"/listing/{listing.pk}/history/{change.pk}/edit/",
        f"/listing/{listing.pk}/history/{change.pk}/delete/",
        "/sources/scrape/",
    ]
    for url in posts:
        assert member_client.post(url, {"date": "2026-09-01", "price": "1", "event": "x"}).status_code == 403, url
    assert member_client.get(f"/listing/{listing.pk}/history/{change.pk}/edit/").status_code == 403
    assert member_client.get("/sources/").status_code == 403
    assert list(PriceChange.objects.values_list("price", flat=True)) == [3100]


def test_members_see_price_history_read_only(member_client):
    listing, _ = listing_with_history()
    content = member_client.get(f"/listing/{listing.pk}/").content.decode()
    assert '<div class="panel" id="price-history">' in content and "$3,100" in content
    assert f'hx-post="/listing/{listing.pk}/history/add/"' not in content
    assert f'hx-get="/listing/{listing.pk}/history/' not in content
    assert f'href="/admin/listings/listing/{listing.pk}/change/"' not in content
    assert '<a href="/sources/">' not in content and '<a href="/admin/">' not in content


def test_staff_keeps_every_control(client):
    listing, change = listing_with_history()
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert f'hx-post="/listing/{listing.pk}/history/add/"' in content
    assert f'hx-get="/listing/{listing.pk}/history/{change.pk}/edit/"' in content
    assert f'href="/admin/listings/listing/{listing.pk}/change/"' in content
    assert '<a href="/sources/">' in content and '<a href="/admin/">' in content
    assert client.get("/sources/").status_code == 200
