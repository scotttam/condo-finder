"""Feed events: recorded by ingest when something worth knowing happens to a listing, and the
queries behind the Feed page."""

from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from .models import FeedEvent, ListingState, PropertyType, Status

SEEN_COOKIE = "feed_seen_at"  # per browser, so each person has their own unread state
FIRST_VISIT_UNREAD = timedelta(days=7)

# Fields whose changes are worth telling you about, with the label used in summaries.
DETAIL_FIELDS = {
    "parking": "Parking",
    "has_washer_dryer": "W/D",
    "has_ac": "AC",
    "has_outdoor_space": "Outdoor space",
    "is_furnished": "Furnished",
    "available": "Available",
    "special": "Special",
}


def record(listing, kind, summary, when, source="", happened_at=None, old_price=None, new_price=None):
    return FeedEvent.objects.create(
        listing=listing, kind=kind, summary=summary[:300], source=source, created_at=when,
        happened_at=happened_at or when, old_price=old_price, new_price=new_price,
    )


def listing_summary(listing):
    parts = [f"${listing.price:,}" if listing.price else "price ?", f"{listing.beds} bd"]
    if listing.baths is not None:
        parts.append(f"{listing.baths.normalize():f} ba")
    parts.append(listing.get_property_type_display())
    return " · ".join(parts)


def _parking(listing):
    if listing.parking_spaces is not None:
        return str(listing.parking_spaces)
    return {True: "yes", False: "none"}.get(listing.has_parking, "?")


def snapshot(listing):
    return {
        "parking": _parking(listing),
        "has_washer_dryer": listing.has_washer_dryer,
        "has_ac": listing.has_ac,
        "has_outdoor_space": listing.has_outdoor_space,
        "is_furnished": listing.is_furnished,
        "available": listing.available or "?",
        "special": listing.special_label or "none",
    }


def _shown(value):
    return {True: "✓", False: "✗", None: "?"}.get(value, value) if not isinstance(value, str) else value


def record_detail_changes(listing, before, when, source=""):
    after = snapshot(listing)
    changes = [f"{label}: {_shown(before[name])} → {_shown(after[name])}"
               for name, label in DETAIL_FIELDS.items() if before[name] != after[name]]
    if changes:
        record(listing, FeedEvent.Kind.DETAILS_CHANGED, " · ".join(changes), when, source)


def events(group, tab="all", show_apartments=False):
    """New listings, plus updates to listings the group has given a status (anything but New)."""
    tracked = Q(Exists(ListingState.objects.filter(group=group, listing=OuterRef("listing")).exclude(status=Status.NEW)))
    queryset = FeedEvent.objects.select_related("listing")
    if tab == "new":
        queryset = queryset.filter(kind=FeedEvent.Kind.NEW_LISTING)
    elif tab == "updates":
        queryset = queryset.exclude(kind=FeedEvent.Kind.NEW_LISTING).filter(tracked)
    else:
        queryset = queryset.filter(Q(kind=FeedEvent.Kind.NEW_LISTING) | tracked)
    if not show_apartments:
        queryset = queryset.exclude(listing__property_type=PropertyType.APARTMENT)
    return queryset.order_by("-created_at", "-pk")


def seen_at(request):
    try:
        return datetime.fromisoformat(request.COOKIES[SEEN_COOKIE])
    except (KeyError, ValueError):
        return timezone.now() - FIRST_VISIT_UNREAD


def unread_count(request):
    return events(request.group).filter(created_at__gt=seen_at(request)).count()


def label(event):
    if event.kind == FeedEvent.Kind.PRICE_CHANGE and event.old_price and event.new_price:
        return "↓ Price drop" if event.new_price < event.old_price else "↑ Price increase"
    return {
        FeedEvent.Kind.NEW_LISTING: "New",
        FeedEvent.Kind.PRICE_CHANGE: "Price change",
        FeedEvent.Kind.OFF_MARKET: "Off market",
        FeedEvent.Kind.BACK_ON_MARKET: "Back on market",
        FeedEvent.Kind.NEW_SITE: "New site",
        FeedEvent.Kind.DETAILS_CHANGED: "Details",
    }[event.kind]
