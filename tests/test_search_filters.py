import re
from decimal import Decimal

import pytest

from listings.filters import apply_filters
from listings.forms import ListingFilterForm
from listings.models import Listing, PropertyType
from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


def listing(key, **fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), sqft=1000, parking_spaces=2, property_type=PropertyType.CONDO)
    base.update(fields)
    return make_listing(address_key=key, **base)


def found(**data):
    """Keys of the listings a search finds. Starts from no filters at all (Search's "Clear all")."""
    form = ListingFilterForm(data)
    assert form.is_valid(), form.errors
    return set(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True))


@pytest.mark.parametrize("choice, expected", [
    ("any", {"yes", "no", "unknown"}),
    ("yes", {"yes"}),
    ("no", {"no"}),
    ("unknown", {"unknown"}),
    ("yes_or_unknown", {"yes", "unknown"}),
])
@pytest.mark.parametrize("name, field", [("wd", "has_washer_dryer"), ("ac", "has_ac"), ("outdoor", "has_outdoor_space"),
                                         ("furnished", "is_furnished")])
def test_feature_filters_are_tri_state(name, field, choice, expected):
    listing("yes", **{field: True})
    listing("no", **{field: False})
    listing("unknown", **{field: None})
    assert found(**{name: choice}) == expected


def test_furnished_keeps_its_older_hide_and_only_values():
    listing("yes", is_furnished=True)
    listing("no", is_furnished=False)
    listing("unknown", is_furnished=None)
    assert found(furnished="hide") == {"no", "unknown"}
    assert found(furnished="only") == {"yes"}


@pytest.mark.parametrize("choice, expected", [
    ("yes", {"spaces", "has-parking"}),
    ("no", {"zero", "no-parking"}),
    ("unknown", {"unknown"}),
    ("yes_or_unknown", {"spaces", "has-parking", "unknown"}),
])
def test_parking_known_is_tri_state(choice, expected):
    listing("spaces", parking_spaces=2)
    listing("has-parking", parking_spaces=None, has_parking=True)
    listing("zero", parking_spaces=0)
    listing("no-parking", parking_spaces=None, has_parking=False)
    listing("unknown", parking_spaces=None, has_parking=None)
    assert found(parking=choice) == expected


def test_home_menus_keep_the_short_lists_but_show_a_search_value():
    menus = ListingFilterForm({"wd": "no"}).home_menus
    assert [option["value"] for option in menus["ac"]] == ["any", "yes_or_unknown", "yes"]
    assert [option["value"] for option in menus["furnished"]] == ["any", "hide", "only"]
    assert [option["value"] for option in menus["wd"]] == ["any", "yes_or_unknown", "yes", "no"]
    assert [option["value"] for option in menus["wd"] if option["selected"]] == ["no"]


def test_search_menus_offer_every_choice_but_furnisheds_alias():
    menus = ListingFilterForm({}).search_menus
    assert [option["value"] for option in menus["wd"]] == ["any", "yes", "no", "unknown", "yes_or_unknown"]
    assert "only" not in [option["value"] for option in menus["furnished"]]
    assert "hide" in [option["value"] for option in menus["furnished"]]


def test_home_drawer_selects_show_a_search_only_value(client):
    content = client.get("/?wd=no").content.decode()
    select = re.search(r'<select name="wd".*?</select>', content, re.S).group(0)
    assert '<option value="no" selected>No</option>' in select
    assert '<option value="unknown"' not in select
