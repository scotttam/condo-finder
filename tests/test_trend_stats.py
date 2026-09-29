from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.utils import timezone

from listings import trend_stats
from listings.models import PriceChange, PropertyType
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db

TODAY = date(2026, 9, 29)


def at(day):
    return timezone.make_aware(datetime.combine(day, time(12)))


_seq = iter(range(1, 10_000))


def listing(city="Portland", price=3000, first_seen=date(2026, 8, 1), **extra):
    n = next(_seq)
    fields = dict(
        address_key=f"{n} test st||97209",
        address=f"{n} Test St, {city}, OR",
        street=f"{n} Test St",
        unit="",
        city=city,
        price=price,
        beds=2,
        baths=Decimal("2"),
        property_type=PropertyType.CONDO,
        first_seen_at=at(first_seen),
        last_seen_at=at(TODAY),
    )
    fields.update(extra)
    return make_listing(**fields)


def history(item, *entries):
    for day, price in entries:
        PriceChange.objects.create(listing=item, price=price, seen_at=at(day), event="Price change")


def test_comparable_listings_exclude_apartments_small_units_and_implausible_rents():
    keep = listing()
    listing(property_type=PropertyType.APARTMENT)
    listing(beds=1)
    listing(baths=Decimal("1"))
    listing(price=1_000_000)
    listing(price=None)
    assert list(trend_stats.comparable_listings()) == [keep]


def test_weekly_median_rent_follows_price_history():
    first = listing(price=2900)
    history(first, (date(2026, 8, 1), 3100), (date(2026, 9, 20), 2900))
    listing(price=3000)
    listing(price=3200)
    series = trend_stats.weekly_series(weeks=3, today=TODAY)
    assert series["weeks"] == ["2026-09-15", "2026-09-22", "2026-09-29"]
    # Sep 15: 3100, 3000, 3200 → 3100; after the cut: 2900, 3000, 3200 → 3000
    assert series["median_rent_by_city"]["Portland"] == [3100, 3000, 3000]


def test_weeks_with_too_few_listings_are_none():
    listing(city="Beaverton")
    listing(city="Beaverton")
    for _ in range(3):
        listing(city="Portland")
    series = trend_stats.weekly_series(weeks=2, today=TODAY)
    assert series["median_rent_by_city"]["Beaverton"] == [None, None]
    assert series["median_rent_by_city"]["Portland"] == [3000, 3000]


def test_listing_not_yet_seen_or_already_gone_is_left_out_of_a_week():
    for _ in range(3):
        listing(price=3000)
    listing(price=9000, first_seen=date(2026, 9, 25))  # not on the market Sep 22 yet
    listing(price=9000, is_active=False, last_seen_at=at(date(2026, 9, 10)))  # gone before Sep 22
    series = trend_stats.weekly_series(weeks=2, today=TODAY)
    assert series["median_rent_by_city"]["Portland"][0] == 3000


def test_cut_share_counts_listings_after_their_drop():
    cut = listing(price=2800)
    history(cut, (date(2026, 8, 1), 3000), (date(2026, 9, 25), 2800))
    listing()
    listing()
    series = trend_stats.weekly_series(weeks=2, today=TODAY)
    assert series["cut_share"] == [0.0, pytest.approx(1 / 3)]


def test_days_on_market_uses_listed_date_when_earlier():
    for _ in range(3):
        listing(first_seen=date(2026, 9, 19), listed_at=date(2026, 9, 9))
    series = trend_stats.weekly_series(weeks=1, today=TODAY)
    assert series["median_dom"] == [20]


def test_market_snapshot_medians():
    cut = listing(price=2800, sqft=1000)
    history(cut, (date(2026, 8, 1), 3000))
    listing(price=3000, sqft=1500)
    listing(price=4000, city="Lake Oswego")
    listing(price=9999, is_active=False)
    snap = trend_stats.market_snapshot(today=TODAY)
    assert snap["active_count"] == 3
    assert snap["median_rent"] == 3000
    assert snap["median_rent_by_city"] == {"Portland": 2900, "Lake Oswego": 4000}
    assert snap["median_ppsf"] == 2.4  # 2.80 and 2.00
    assert snap["cut_share"] == pytest.approx(1 / 3)
    assert snap["median_dom"] == 59


def test_empty_database():
    series = trend_stats.weekly_series(weeks=2, today=TODAY)
    assert series["cut_share"] == [None, None]
    assert trend_stats.market_snapshot(today=TODAY)["median_rent"] is None
