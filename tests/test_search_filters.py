import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from listings.filters import apply_filters, dom_expr
from listings.forms import PRICE_SLIDER_MAX, ListingFilterForm
from listings.models import Listing, PriceChange, PropertyType
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


def days_ago(n, at=time(12)):
    return timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=n), at))


def test_dom_in_sql_matches_the_python_property():
    rows = [
        listing("seen-10", first_seen_at=days_ago(10)),
        listing("listed-earlier", first_seen_at=days_ago(5), listed_at=timezone.localdate() - timedelta(days=30)),
        listing("listed-later", first_seen_at=days_ago(5), listed_at=timezone.localdate() - timedelta(days=2)),
        listing("gone", first_seen_at=days_ago(20), last_seen_at=days_ago(3), is_active=False),
        listing("late-evening", first_seen_at=days_ago(1, time(23, 30))),  # after 4pm Pacific: the next day in UTC
    ]
    in_sql = dict(Listing.objects.annotate(dom=dom_expr()).values_list("pk", "dom"))
    assert in_sql == {row.pk: row.days_on_market for row in rows}


def test_days_on_market_range():
    listing("fresh", first_seen_at=days_ago(2))
    listing("stale", first_seen_at=days_ago(60))
    assert found(min_dom=30) == {"stale"}
    assert found(max_dom=7) == {"fresh"}


def test_new_within_and_gone_within():
    listing("new", first_seen_at=days_ago(2))
    listing("old", first_seen_at=days_ago(40))
    listing("just-gone", first_seen_at=days_ago(40), last_seen_at=days_ago(1), is_active=False)
    listing("long-gone", first_seen_at=days_ago(40), last_seen_at=days_ago(30), is_active=False)
    assert found(new_within=7) == {"new"}
    assert found(gone_within=7) == {"just-gone"}  # includes off-market listings without "Show off-market"


def test_listed_date_range_uses_the_listings_start():
    listing("listed-in-sept", first_seen_at=days_ago(1), listed_at=date(2026, 9, 10))
    listing("seen-in-oct", first_seen_at=timezone.make_aware(datetime(2026, 10, 3, 12)))
    assert found(listed_from="2026-09-01", listed_to="2026-09-30") == {"listed-in-sept"}
    assert found(listed_from="2026-10-01") == {"seen-in-oct"}


def with_history(key, prices, **fields):
    """A listing whose history ran through prices (first is the listing price), ending at the last one."""
    row = listing(key, price=prices[-1], **fields)
    for n, price in enumerate(prices):
        PriceChange.objects.create(listing=row, price=price, seen_at=days_ago(len(prices) - n),
                                   event="Listed for rent" if n == 0 else "Price change")
    return row


def test_drop_by_amount_and_percent():
    with_history("small-cut", [3000, 2950])      # $50, 1.7%
    with_history("big-cut", [3000, 2700])        # $300, 10%
    with_history("never-cut", [3000])
    assert found(min_drop_amount=100) == {"big-cut"}
    assert found(min_drop_percent=5) == {"big-cut"}
    assert found(min_drop_amount=25, min_drop_percent=1) == {"small-cut", "big-cut"}


def test_number_of_price_changes_and_price_went_up():
    with_history("twice", [3000, 2900, 2800])
    with_history("raised", [3000, 2800, 2950])
    with_history("once", [3000, 3100])
    with_history("never", [3000])
    assert found(min_price_changes=2) == {"twice", "raised"}
    assert found(price_raised="on") == {"raised", "once"}


def test_price_movement_ignores_an_earlier_rental_listing():
    row = with_history("relisted", [3500, 2800])
    row.listed_at = timezone.localdate()  # a new listing started today, after both entries
    row.save()
    assert found(min_drop_amount=100) == set()
    assert found(min_price_changes=1) == set()
