from datetime import date, datetime

import pytest
from django.utils import timezone

from listings.models import PriceChange
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def at(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=12))


@pytest.fixture
def home():
    listing = make_listing(price=4600, listed_at=date(2026, 8, 22))
    PriceChange.objects.create(listing=listing, price=4800, seen_at=at(date(2026, 8, 22)), event="Listed for rent", source="Zillow")
    return listing


def test_detail_page_has_add_form_and_row_actions(client, home):
    content = client.get(f"/listing/{home.pk}/").content.decode()
    assert 'id="price-history"' in content
    assert f'hx-post="/listing/{home.pk}/history/add/"' in content
    change = home.price_changes.get()
    assert f"/listing/{home.pk}/history/{change.pk}/edit/" in content
    assert f"/listing/{home.pk}/history/{change.pk}/delete/" in content
    assert 'list="history-events"' in content  # event suggestions


def test_add_an_entry(client, home):
    response = client.post(f"/listing/{home.pk}/history/add/", {"date": "2026-09-22", "price": "4600", "event": "Price change"}, **HX)
    assert response.status_code == 200
    added = home.price_changes.get(price=4600)
    assert (added.seen_at, added.event, added.source) == (at(date(2026, 9, 22)), "Price change", "")
    content = response.content.decode()
    assert content.index("Sep 22, 2026") < content.index("Aug 22, 2026")  # newest first
    assert "↓ $200" in content  # the drop reflects the new entry


def test_add_requires_date_and_price(client, home):
    response = client.post(f"/listing/{home.pk}/history/add/", {"date": "2026-09-22", "price": ""}, **HX)
    assert response.status_code == 200 and "This field is required" in response.content.decode()
    assert home.price_changes.count() == 1


def test_edit_an_entry(client, home):
    change = home.price_changes.get()
    form = client.get(f"/listing/{home.pk}/history/{change.pk}/edit/", **HX).content.decode()
    assert 'value="2026-08-22"' in form and 'value="4800"' in form
    client.post(f"/listing/{home.pk}/history/{change.pk}/edit/", {"date": "2026-08-20", "price": "4850", "event": "Listed for rent"}, **HX)
    change.refresh_from_db()
    assert (change.seen_at, change.price, change.source) == (at(date(2026, 8, 20)), 4850, "Zillow")


def test_delete_an_entry(client, home):
    change = home.price_changes.get()
    response = client.post(f"/listing/{home.pk}/history/{change.pk}/delete/", **HX)
    assert response.status_code == 200 and home.price_changes.count() == 0


def test_entries_of_another_listing_are_off_limits(client, home):
    other = make_listing(address_key="other", street="1 Other St")
    change = home.price_changes.get()
    assert client.post(f"/listing/{other.pk}/history/{change.pk}/delete/", **HX).status_code == 404
    assert home.price_changes.count() == 1


def test_without_htmx_it_redirects_back_to_the_listing(client, home):
    response = client.post(f"/listing/{home.pk}/history/add/", {"date": "2026-09-22", "price": "4600"})
    assert response.status_code == 302 and response["Location"] == f"/listing/{home.pk}/"
