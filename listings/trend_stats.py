"""Market statistics for the Trends page, computed from stored listings and their price history.

"Comparable" listings are the kind we're shopping for (2+ bed, 2+ bath, not an apartment complex).
Weekly series are snapshots taken on the same weekday for the last N weeks, ending today.
"""

from datetime import timedelta
from statistics import median

from django.conf import settings
from django.utils import timezone

from .ingest import MAX_PLAUSIBLE_RENT
from .models import Listing, PropertyType

MIN_SAMPLE = 3  # fewer listings than this in a week says nothing; the chart leaves a gap


def comparable_listings():
    return (
        Listing.objects.filter(beds__gte=2, baths__gte=2, price__gte=1, price__lte=MAX_PLAUSIBLE_RENT)
        .exclude(property_type=PropertyType.APARTMENT)
        .prefetch_related("price_changes")
    )


def _start(listing):
    start = timezone.localdate(listing.first_seen_at)
    return min(start, listing.listed_at) if listing.listed_at else start


def _on_market(listing, day):
    return _start(listing) <= day and (listing.is_active or timezone.localdate(listing.last_seen_at) >= day)


def _history(listing):
    """(date, price) pairs from the current rental period, oldest first."""
    return [
        (timezone.localdate(change.seen_at), change.price)
        for change in listing.price_changes.all()
        if listing.listed_at is None or timezone.localdate(change.seen_at) >= listing.listed_at
    ]


def _price_on(listing, day, history):
    earlier = [price for when, price in history if when <= day]
    return earlier[-1] if earlier else listing.price


def _cut_by(day, price, history):
    return any(earlier > price for when, earlier in history if when <= day)


def _median(values):
    return round(median(values)) if len(values) >= MIN_SAMPLE else None


def weekly_series(weeks=8, today=None):
    today = today or timezone.localdate()
    days = [today - timedelta(days=7 * back) for back in range(weeks - 1, -1, -1)]
    listings = [(listing, _history(listing)) for listing in comparable_listings()]
    cities = settings.TARGET_CITIES
    rent_by_city = {city: [] for city in cities}
    cut_share, median_dom = [], []
    for day in days:
        on_market = [(listing, history) for listing, history in listings if _on_market(listing, day)]
        prices = {listing.pk: _price_on(listing, day, history) for listing, history in on_market}
        for city in cities:
            rent_by_city[city].append(_median([prices[l.pk] for l, _ in on_market if l.city == city]))
        cut = [_cut_by(day, prices[l.pk], history) for l, history in on_market]
        cut_share.append(sum(cut) / len(cut) if len(cut) >= MIN_SAMPLE else None)
        median_dom.append(_median([(day - _start(l)).days for l, _ in on_market]))
    return {
        "weeks": [day.isoformat() for day in days],
        "median_rent_by_city": rent_by_city,
        "cut_share": cut_share,
        "median_dom": median_dom,
    }


def market_snapshot(today=None):
    """Where the market stands right now, over active comparable listings."""
    today = today or timezone.localdate()
    active = [listing for listing in comparable_listings() if listing.is_active]
    by_city = {}
    for listing in active:
        by_city.setdefault(listing.city, []).append(listing.price)
    per_sqft = [listing.price / listing.sqft for listing in active if listing.sqft]
    return {
        "active_count": len(active),
        "median_rent": round(median(l.price for l in active)) if active else None,
        "median_rent_by_city": {city: round(median(prices)) for city, prices in by_city.items()},
        "median_ppsf": round(median(per_sqft), 2) if per_sqft else None,
        "cut_share": sum(1 for l in active if l.price_drop) / len(active) if active else None,
        "median_dom": round(median((today - _start(l)).days for l in active)) if active else None,
    }
