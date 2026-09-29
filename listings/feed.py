"""Feed events: recorded by ingest when something worth knowing happens to a listing."""

from .models import FeedEvent

# Fields whose changes are worth telling you about, with the label used in summaries.
DETAIL_FIELDS = {
    "parking": "Parking",
    "has_washer_dryer": "W/D",
    "has_ac": "AC",
    "has_outdoor_space": "Outdoor space",
    "available": "Available",
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
        "available": listing.available or "?",
    }


def _shown(value):
    return {True: "✓", False: "✗", None: "?"}.get(value, value) if not isinstance(value, str) else value


def record_detail_changes(listing, before, when, source=""):
    after = snapshot(listing)
    changes = [f"{label}: {_shown(before[name])} → {_shown(after[name])}"
               for name, label in DETAIL_FIELDS.items() if before[name] != after[name]]
    if changes:
        record(listing, FeedEvent.Kind.DETAILS_CHANGED, " · ".join(changes), when, source)
