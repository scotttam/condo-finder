from decimal import Decimal

import pytest

from listings.filters import apply_filters
from listings.forms import ListingFilterForm, default_filter_data
from listings.models import Listing, PropertyType, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def listing(key, **fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type=PropertyType.CONDO)
    base.update(fields)
    return make_listing(address_key=key, **base)


def filtered(data=None):
    form = ListingFilterForm(data or default_filter_data())
    assert form.is_valid(), form.errors
    return set(apply_filters(Listing.objects.all(), form.cleaned_data).values_list("address_key", flat=True))


def test_defaults_apply_2_2_2_and_hide_apartments_rejected_inactive():
    listing("ok")
    listing("unknown-parking", parking_spaces=None)
    listing("one-bath", baths=Decimal("1"))
    listing("one-spot", parking_spaces=1)
    listing("apartment", property_type=PropertyType.APARTMENT)
    listing("rejected", status=Status.REJECTED)
    listing("gone", is_active=False)
    listing("pricey", price=6500)
    listing("no-wd", has_washer_dryer=False)
    assert filtered() == {"ok", "unknown-parking"}


def test_feature_yes_requires_known_true():
    listing("yes", has_ac=True)
    listing("unknown", has_ac=None)
    data = default_filter_data() | {"ac": "yes"}
    assert filtered(data) == {"yes"}


def test_exclude_unknown_parking():
    listing("ok")
    listing("unknown-parking", parking_spaces=None)
    data = {k: v for k, v in default_filter_data().items() if k != "parking_unknown"}
    assert filtered(data) == {"ok"}


def test_city_and_neighborhood():
    listing("pearl", neighborhood="Pearl District")
    listing("lo", city="Lake Oswego")
    assert filtered(default_filter_data() | {"cities": ["Lake Oswego"]}) == {"lo"}
    assert filtered(default_filter_data() | {"neighborhood": "pearl"}) == {"pearl"}


def test_sort_by_price_per_sqft():
    listing("cheap-per-sqft", price=3000, sqft=1500)
    listing("pricey-per-sqft", price=2500, sqft=800)
    form = ListingFilterForm(default_filter_data() | {"sort": "ppsf"})
    assert form.is_valid()
    keys = list(apply_filters(Listing.objects.all(), form.cleaned_data).values_list("address_key", flat=True))
    assert keys == ["cheap-per-sqft", "pricey-per-sqft"]
