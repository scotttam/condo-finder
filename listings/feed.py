"""Feed events: recorded by ingest when something worth knowing happens to a listing, and the
queries behind the Feed page."""

from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from .models import FeedEvent, ListingState, PropertyType, Status

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


def record_activity(listing, group, actor, kind, summary):
    """Something a group member did, shown only in that group's Feed."""
    now = timezone.now()
    return FeedEvent.objects.create(
        listing=listing, group=group, actor=actor, kind=kind, summary=summary[:300], created_at=now, happened_at=now,
    )


def events(group, tab="all", show_apartments=False):
    """New listings and updates to listings the group tracks (scraped events every group sees), plus the
    group's own activity: status changes, comments and votes by its members."""
    site = Q(group__isnull=True)
    tracked = Q(Exists(ListingState.objects.filter(group=group, listing=OuterRef("listing")).exclude(status=Status.NEW)))
    queryset = FeedEvent.objects.select_related("listing", "actor__profile")
    if tab == "new":
        queryset = queryset.filter(site, kind=FeedEvent.Kind.NEW_LISTING)
    elif tab == "updates":
        queryset = queryset.filter(site & tracked).exclude(kind=FeedEvent.Kind.NEW_LISTING)
    elif tab == "activity":
        queryset = queryset.filter(group=group)
    else:
        queryset = queryset.filter((site & (Q(kind=FeedEvent.Kind.NEW_LISTING) | tracked)) | Q(group=group))
    if not show_apartments:
        queryset = queryset.exclude(site & Q(listing__property_type=PropertyType.APARTMENT))
    return queryset.order_by("-created_at", "-pk")


def seen_at(profile):
    return profile.feed_seen_at or timezone.now() - FIRST_VISIT_UNREAD


def is_unread(event, profile, last_seen):
    """Newer than the person's last Feed visit, and not something they did themselves."""
    return event.created_at > last_seen and event.actor_id != profile.user_id


def unread_count(profile):
    return events(profile.group).filter(created_at__gt=seen_at(profile)).exclude(actor=profile.user).count()


def mark_seen(profile):
    profile.feed_seen_at = timezone.now()
    profile.save(update_fields=["feed_seen_at"])


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
        FeedEvent.Kind.STATUS: "Status",
        FeedEvent.Kind.COMMENT: "Comment",
        FeedEvent.Kind.VOTE: "Vote",
    }[event.kind]
