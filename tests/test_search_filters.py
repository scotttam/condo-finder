import re
from decimal import Decimal

import pytest

from listings.filters import apply_filters
from listings.forms import PRICE_SLIDER_MAX, ListingFilterForm
from listings.models import Listing, PropertyType
from listings.specials import effective_rent
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


def test_size_ranges_exclude_unknowns():
    listing("small", beds=1, baths=Decimal("1"), sqft=600)
    listing("mid", beds=2, baths=Decimal("2"), sqft=1100)
    listing("big", beds=4, baths=Decimal("3"), sqft=2400)
    listing("no-sqft", sqft=None)
    assert found(min_beds=2, max_beds=3) == {"mid", "no-sqft"}
    assert found(max_baths="1.5") == {"small"}
    assert found(min_sqft=800, max_sqft=2000) == {"mid"}


def test_parking_range_with_and_without_unknown():
    listing("one", parking_spaces=1)
    listing("two", parking_spaces=2)
    listing("three", parking_spaces=3)
    listing("unknown", parking_spaces=None)
    assert found(min_parking=1, max_parking=2) == {"one", "two"}
    assert found(max_parking=1, parking_unknown="on") == {"one", "unknown"}


def test_price_per_sqft_range():
    listing("cheap", price=2000, sqft=1000)   # $2.00
    listing("dear", price=4000, sqft=1000)    # $4.00
    listing("no-sqft", price=3000, sqft=None)
    assert found(min_ppsf="2.5") == {"dear"}
    assert found(max_ppsf="2.5") == {"cheap"}


def test_typed_max_price_above_the_slider_top_filters():
    listing("ok", price=8500)
    listing("too-dear", price=9500)
    assert found(max_price=9000) == {"ok"}
    assert found(max_price=PRICE_SLIDER_MAX) == {"ok", "too-dear"}  # the home slider's top still means no max


def test_effective_price_follows_the_special_and_the_price():
    offer = "Get 4 weeks free on a 12-month lease."
    special = listing("special", price=3000, special_offer=offer)
    plain = listing("plain", price=3000)
    assert special.effective_price == effective_rent(3000, offer) < 3000
    assert plain.effective_price == 3000
    special.price = 3200
    special.save(update_fields=["price", "updated_at"])  # how ingest saves a new price
    special.refresh_from_db()
    assert special.effective_price == effective_rent(3200, offer)
    special.special_offer = ""
    special.save(update_fields=["special_offer", "updated_at"])
    special.refresh_from_db()
    assert special.effective_price == 3200


def test_effective_rent_range():
    listing("special", price=3000, special_offer="Get 4 weeks free on a 12-month lease.")
    listing("plain", price=3000)
    assert found(max_effective=2900) == {"special"}
    assert found(min_effective=2900) == {"plain"}


@pytest.mark.django_db(transaction=True)
def test_migration_fills_in_effective_price():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    def migrate(target):
        MigrationExecutor(connection).migrate(target)
        return MigrationExecutor(connection).loader.project_state(target).apps

    apps = migrate([("listings", "0021_trendreport_discoveries")])
    Old = apps.get_model("listings", "Listing")
    old = Old.objects.create(address_key="k", address="1 A St", street="1 A St", city="Portland", price=3000,
                             special_offer="Get 4 weeks free on a 12-month lease.")
    try:
        apps = migrate([("listings", "0022_listing_effective_price")])
        assert apps.get_model("listings", "Listing").objects.get(pk=old.pk).effective_price == effective_rent(
            3000, "Get 4 weeks free on a 12-month lease.")
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
