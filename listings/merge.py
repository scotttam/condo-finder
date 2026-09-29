"""Merging duplicate listings: the same home listed with its unit number on one site and without it
on another (Redfin often drops the unit), e.g. "821 NW 11th Ave" and "821 NW 11th Ave #105"."""

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import FeedEvent, Listing, SourceListing, Status, TrendReport

log = logging.getLogger(__name__)

# When both copies have a status, the one further along wins (rejecting is a final decision).
STATUS_RANK = {Status.NEW: 0, Status.INTERESTED: 1, Status.TOURED: 2, Status.APPLIED: 3, Status.REJECTED: 4}

# Filled in from the merged-away copy when the survivor doesn't know them.
FILL_FIELDS = [
    "latitude", "longitude", "geocoded_at", "neighborhood", "quadrant", "title", "description", "beds", "baths", "sqft",
    "parking_spaces", "has_parking", "has_washer_dryer", "has_ac", "has_outdoor_space", "is_furnished", "available",
    "photo_url", "listed_at",
]


def split_key(key):
    """(street, unit, zip) from an address key, or None for a key made unique per site (see _listing_key)."""
    parts = key.split("|")
    return tuple(parts) if len(parts) == 3 else None


def bare_key(key):
    street, _, zip_code = split_key(key)
    return f"{street}||{zip_code}"


def same_home_keys(a, b):
    """The same street and ZIP, and the same unit or a unit on only one side."""
    a, b = split_key(a), split_key(b)
    return bool(a and b) and a[0] == b[0] and a[2] == b[2] and (a[1] == b[1] or not a[1] or not b[1])


def looks_same(listing, beds, baths, sqft, price):
    """Same beds (and baths, when both say), and the same size or, when a size is missing, price."""
    if listing.beds != beds or (listing.baths is not None and baths is not None and listing.baths != baths):
        return False
    if listing.sqft and sqft:
        return listing.sqft == sqft
    return price is not None and listing.price == price


def unit_match(key, source, beds, baths, sqft, price):
    """The one listing at this address key that is this home with or without its unit number, or None.
    A listing from the same site never matches: a site doesn't list one home twice. Two candidates
    (units that look alike) are ambiguous and match nothing."""
    parts = split_key(key)
    if parts is None or not parts[0][:1].isdigit():
        return None
    street, unit, zip_code = parts
    if unit:
        candidates = Listing.objects.filter(address_key=f"{street}||{zip_code}")
    else:
        candidates = Listing.objects.filter(address_key__startswith=f"{street}|", address_key__endswith=f"|{zip_code}")
        candidates = [c for c in candidates if (split_key(c.address_key) or ("", "", ""))[1]]
    matches = [
        c for c in candidates
        if looks_same(c, beds, baths, sqft, price)
        and (source is None or not c.source_listings.filter(source=source).exists())
    ]
    return matches[0] if len(matches) == 1 else None


def touched(listing):
    """Whether the owners have done anything to this listing by hand."""
    return bool(
        listing.status != Status.NEW or listing.notes.strip() or listing.overrides
        or listing.price_changes.filter(source="").exists()
    )


def survivor(a, b):
    """The copy to keep: one the owners have worked on, else the one with the unit number, else the older."""
    def rank(listing):
        return (not touched(listing), not listing.unit, listing.first_seen_at, listing.pk)
    return (a, b) if rank(a) <= rank(b) else (b, a)


@transaction.atomic
def merge(keep, drop):
    """Fold `drop` into `keep`: its sites, price history, feed, notes and status. Returns `keep`."""
    from .ingest import _apply_overrides, _recompute_price

    SourceListing.objects.filter(listing=drop).update(listing=keep)
    for change in drop.price_changes.all():
        if keep.price_changes.filter(seen_at__date=timezone.localdate(change.seen_at), price=change.price).exists():
            change.delete()
        else:
            change.listing = keep
            change.save(update_fields=["listing"])
    events = FeedEvent.objects.filter(listing=drop)
    if keep.feed_events.filter(kind=FeedEvent.Kind.NEW_LISTING).exists():
        events.filter(kind=FeedEvent.Kind.NEW_LISTING).delete()
    events.update(listing=keep)

    notes = [n for n in (keep.notes.strip(), drop.notes.strip()) if n]
    keep.notes = "\n\n".join(dict.fromkeys(notes))
    if STATUS_RANK.get(drop.status, 0) > STATUS_RANK.get(keep.status, 0):
        keep.status = drop.status
    keep.overrides = {**(drop.overrides or {}), **(keep.overrides or {})}
    for name in FILL_FIELDS:
        if getattr(keep, name) in (None, "") and getattr(drop, name) not in (None, ""):
            setattr(keep, name, getattr(drop, name))
    if drop.listed_at and keep.listed_at and drop.listed_at < keep.listed_at:
        keep.listed_at = drop.listed_at
    keep.first_seen_at = min(keep.first_seen_at, drop.first_seen_at)
    keep.last_seen_at = max(keep.last_seen_at, drop.last_seen_at)
    if drop.unit and not keep.unit:  # the unit number is the better address
        for name in ("address_key", "address", "street", "unit"):
            setattr(keep, name, getattr(drop, name))
    keep.is_active = keep.source_listings.filter(is_active=True).exists()
    _apply_overrides(keep)

    dropped = drop.pk
    _repoint_reports(dropped, keep.pk)
    drop.delete()  # frees its address key for `keep`
    keep.save()
    _recompute_price(keep)
    log.info("Merged listing %s into %s (%s)", dropped, keep.pk, keep.address)
    return keep


def _repoint_reports(old, new):
    for report in TrendReport.objects.filter(Q(picks__icontains=str(old)) | Q(shortlist__icontains=str(old))):
        report.shortlist = [new if pk == old else pk for pk in report.shortlist]
        report.picks = [{**pick, "listing_id": new} if pick.get("listing_id") == old else pick for pick in report.picks]
        report.save(update_fields=["shortlist", "picks"])


def merge_unit_duplicates(dry_run=False):
    """Find listings without a unit number that match exactly one listing with one at the same
    address, and merge each pair. Returns (kept id, merged-away id, address) for each."""
    merged = []
    for bare in Listing.objects.filter(address_key__regex=r"^[0-9][^|]*\|\|[^|]*$"):
        match = unit_match(bare.address_key, None, bare.beds, bare.baths, bare.sqft, bare.price)
        if match is None or _share_a_site(bare, match):
            continue
        keep, drop = survivor(bare, match)
        merged.append((keep.pk, drop.pk, match.address))
        if not dry_run:
            merge(keep, drop)
    return merged


def _share_a_site(a, b):
    return a.source_listings.filter(source__in=b.source_listings.values("source")).exists()
