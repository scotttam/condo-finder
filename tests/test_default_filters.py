import json
from decimal import Decimal

import pytest
from django.conf import settings
from django.test import Client

from accounts.groups import new_group
from listings import analyst
from listings.forms import app_default_filters, default_filter_data
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db


def good(key, **extra):
    fields = dict(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    fields.update(extra)
    return make_listing(**fields)


def keys(browser, url="/"):
    return {listing.address_key for listing in browser.get(url).context["listings"]}


def test_new_groups_start_from_the_app_defaults():
    assert default_filter_data(new_group("Fresh")) == app_default_filters()


def test_the_owners_group_starts_from_the_old_hard_coded_defaults():
    saved = home_group().default_filters
    assert (saved["min_beds"], saved["min_baths"], saved["min_parking"]) == ("2", "2", "2")
    assert saved["min_price"] == str(settings.DEFAULT_MIN_PRICE) and "apartment" not in saved["types"]
    assert "rejected" not in saved["statuses"]


def test_save_as_our_defaults_stores_the_filter_bar(client):
    response = client.post("/filters/defaults/", {
        "min_beds": "3", "min_baths": "", "min_price": "2500", "max_price": "8000", "types": ["condo", "townhome"],
        "statuses": ["new", "interested"], "wd": "yes", "ac": "any", "outdoor": "any", "furnished": "any",
        "votes": "any", "sort": "newest", "north": "45.6", "south": "45.5", "east": "-122.6", "west": "-122.7",
    }, HTTP_HX_REQUEST="true")
    assert '<button type="button" id="save-defaults"' in response.content.decode()
    assert "Saved as our defaults ✓" in response.content.decode()
    saved = home_group().default_filters
    assert saved["min_beds"] == "3" and saved["types"] == ["condo", "townhome"] and saved["sort"] == "newest"
    assert saved["parking_unknown"] == "" and "north" not in saved


def test_the_list_page_starts_from_the_groups_defaults(client):
    good("two")
    good("three", beds=3)
    group = home_group()
    group.default_filters = app_default_filters() | {"min_beds": "3"}
    group.save()
    assert keys(client) == {"three"}
    defaults = json.loads(client.get("/").content.decode().split('id="filter-defaults" type="application/json">')[1].split("</script>")[0])
    assert defaults["min_beds"] == "3"


def test_each_group_keeps_its_own_defaults(client):
    good("two")
    good("three", beds=3)
    group = home_group()
    group.default_filters = app_default_filters() | {"min_beds": "3"}
    group.save()
    pat = Client()
    pat.force_login(make_user("pat@example.com", "Pat", group=new_group("Pat's search")))
    assert keys(pat) == {"two", "three"}


def test_the_filter_bar_has_the_button(member_client):
    assert '<button type="button" id="save-defaults"' in member_client.get("/").content.decode()


def test_trends_candidates_use_the_groups_defaults():
    cheap = good("cheap", price=1500)
    group = home_group()
    group.default_filters = app_default_filters() | {"min_price": "1000"}
    group.save()
    assert cheap.pk in {listing.pk for listing in analyst.candidates(group)}
