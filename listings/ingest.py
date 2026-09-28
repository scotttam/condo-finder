from dataclasses import dataclass, field
from datetime import datetime, time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .address import is_target_city, parse_address, portland_quadrant
from .extract import (
    classify_property_type,
    extract_parking,
    has_ac,
    has_outdoor_space,
    has_parking,
    has_washer_dryer,
)
from .models import Listing, PriceChange, PropertyType, SourceListing

OVERRIDABLE_FIELDS = {
    "price", "beds", "baths", "sqft", "parking_spaces", "has_parking", "has_washer_dryer", "has_ac",
    "has_outdoor_space", "property_type", "neighborhood", "quadrant", "available", "title",
    "latitude", "longitude",
}


@dataclass
class IngestResult:
    seen: int = 0
    skipped: int = 0
    new_listings: list = field(default_factory=list)


def ingest(source, items, now=None):
    now = now or timezone.now()
    result = IngestResult()
    seen_ids = set()
    for item in items:
        address = parse_address(item.address)
        if address is None and _refresh_known(source, item, now, result, seen_ids):
            continue
        if address is None or not is_target_city(address.city) or item.beds is None or item.beds < 2:
            result.skipped += 1
            continue
        with transaction.atomic():
            listing, created = _upsert_listing(address, item, now, source)
            source_listing, previous_price = _upsert_source_listing(source, listing, item, now)
            _update_price(listing, previous_price, item, now, source.name, created)
            _import_history(listing, item.price_history, source.name)
        seen_ids.add(source_listing.pk)
        result.seen += 1
        if created:
            result.new_listings.append(listing)
    if items:
        _mark_missing(source, seen_ids)
    return result


def _listing_key(source, address, item):
    """The same address from different sites is one listing, but a site never lists one unit twice:
    another listing from the same site at a taken address is a different unit (a building without
    unit numbers), and hidden addresses have nothing real to match on. Those get their own key."""
    own = f"{address.key}|{source.key}:{item.external_id}"
    if not address.street[:1].isdigit():
        return own
    current = (
        SourceListing.objects.filter(source=source, external_id=item.external_id)
        .values_list("listing__address_key", flat=True)
        .first()
    )
    if current in (address.key, own):
        return current
    taken = (
        SourceListing.objects.filter(source=source, listing__address_key=address.key)
        .exclude(external_id=item.external_id)
        .exists()
    )
    return own if taken else address.key


def _upsert_listing(address, item, now, source):
    key = _listing_key(source, address, item)
    listing = Listing.objects.filter(address_key=key).first()
    created = listing is None
    if created:
        listing = Listing(address_key=key, first_seen_at=now)
    _apply_scraped(listing, address, item)
    _apply_overrides(listing)
    listing.is_active = True
    listing.last_seen_at = now
    listing.save()
    return listing, created


def _update_price(listing, previous_price, item, now, source_name, created):
    """The listing shows the lowest current price among the sites listing it. A price change is
    recorded only when one site changes its own price: sites disagreeing (a building's "from" price
    vs one unit, say) isn't a change."""
    if "price" in (listing.overrides or {}):
        listing.price = listing.overrides["price"]
    else:
        prices = listing.source_listings.filter(is_active=True, last_price__isnull=False).values_list("last_price", flat=True)
        listing.price = min(prices, default=listing.price)
    listing.save(update_fields=["price", "updated_at"])
    if item.price is None:
        return
    if created:
        PriceChange.objects.create(listing=listing, price=listing.price, seen_at=now, event="First seen", source=source_name)
    elif previous_price is not None and item.price != previous_price:
        PriceChange.objects.create(listing=listing, price=item.price, seen_at=now, event="Price change", source=source_name)


def _history_time(day):
    return timezone.make_aware(datetime.combine(day, time(12)))


def _import_history(listing, entries, source_name):
    """Add a listing site's own rental history. Entries already present (same day and price, e.g.
    typed in by hand) are labelled rather than duplicated."""
    if not entries:
        return
    imported = []
    for day, price, event in entries:
        existing = listing.price_changes.filter(seen_at__date=day, price=price).first()
        if existing is None:
            existing = PriceChange.objects.create(
                listing=listing, price=price, seen_at=_history_time(day), event=event, source=source_name
            )
        elif not existing.event:
            existing.event, existing.source = event, source_name
            existing.save(update_fields=["event", "source"])
        imported.append(existing)
    # Our own "First seen" is redundant when the site's history already shows that price by then.
    for observed in listing.price_changes.filter(event="First seen"):
        earlier = [entry for entry in imported if entry.seen_at <= observed.seen_at]
        if earlier and max(earlier, key=lambda entry: entry.seen_at).price == observed.price:
            observed.delete()


def _apply_scraped(listing, address, item):
    text = item.full_text
    listing.address = address.display
    listing.street = address.street
    listing.unit = address.unit
    listing.city = address.city
    listing.zip_code = address.zip_code
    listing.quadrant = portland_quadrant(address.street, address.city)
    listing.title = (item.title or listing.title)[:300]
    listing.description = "\n\n".join(p for p in (item.description, item.amenities) if p) or listing.description
    listing.available = (item.available or listing.available)[:100]
    listing.photo_url = item.photo_url or listing.photo_url
    if item.listed_at and (listing.listed_at is None or item.listed_at < listing.listed_at):
        listing.listed_at = item.listed_at  # sites can disagree; keep the earliest start
    if item.latitude is not None and item.longitude is not None:
        # The listing site's own pin beats a geocoded guess from the street address.
        listing.latitude = item.latitude
        listing.longitude = item.longitude
    for name in ("beds", "baths", "sqft"):  # price: see _update_price
        value = getattr(item, name)
        if value is not None:
            setattr(listing, name, value)
    _apply_extracted(listing, text, item.property_type_hint)


def _apply_extracted(listing, text, hint=""):
    """Set features detected in text; a source that doesn't mention a feature never erases it."""
    extracted = {
        "parking_spaces": extract_parking(text),
        "has_parking": has_parking(text),
        "has_washer_dryer": has_washer_dryer(text),
        "has_ac": has_ac(text),
        "has_outdoor_space": has_outdoor_space(text),
    }
    for name, value in extracted.items():
        if value is not None:
            setattr(listing, name, value)
    property_type = classify_property_type(hint, text)
    if property_type != PropertyType.UNKNOWN:
        listing.property_type = property_type


def _apply_overrides(listing):
    for name, value in (listing.overrides or {}).items():
        if name in OVERRIDABLE_FIELDS:
            setattr(listing, name, value)


REEXTRACTED_FIELDS = ["parking_spaces", "has_parking", "has_washer_dryer", "has_ac", "has_outdoor_space", "property_type"]


def reextract_all():
    """Re-run feature detection on stored text (after the rules improve). Returns listings changed."""
    changed = 0
    for listing in Listing.objects.exclude(description=""):
        before = [getattr(listing, name) for name in REEXTRACTED_FIELDS]
        _apply_extracted(listing, f"{listing.title}\n{listing.description}")
        _apply_overrides(listing)
        if [getattr(listing, name) for name in REEXTRACTED_FIELDS] != before:
            listing.save(update_fields=[*REEXTRACTED_FIELDS, "updated_at"])
            changed += 1
    return changed


def _upsert_source_listing(source, listing, item, now):
    source_listing, created = SourceListing.objects.get_or_create(
        source=source,
        external_id=item.external_id,
        defaults={"listing": listing, "url": item.url, "first_seen_at": now, "last_seen_at": now},
    )
    if not created:
        source_listing.listing = listing
        source_listing.url = item.url
        source_listing.is_active = True
        source_listing.missed_runs = 0
        source_listing.last_seen_at = now
    source_listing.details_version = max(source_listing.details_version, item.details_version)
    previous_price = source_listing.last_price
    if item.price is not None:
        source_listing.last_price = item.price
    source_listing.save()
    return source_listing, previous_price


def _refresh_known(source, item, now, result, seen_ids):
    """A listing we already stored, seen again without its address (detail page skipped)."""
    source_listing = (
        SourceListing.objects.select_related("listing").filter(source=source, external_id=item.external_id).first()
    )
    if source_listing is None:
        return False
    listing = source_listing.listing
    with transaction.atomic():
        listing.is_active = True
        listing.last_seen_at = now
        listing.save()
        _, previous_price = _upsert_source_listing(source, listing, item, now)
        _update_price(listing, previous_price, item, now, source.name, created=False)
    seen_ids.add(source_listing.pk)
    result.seen += 1
    return True


def _mark_missing(source, seen_ids):
    affected = set()
    for source_listing in SourceListing.objects.filter(source=source, is_active=True).exclude(pk__in=seen_ids):
        source_listing.missed_runs += 1
        if source_listing.missed_runs >= settings.OFF_MARKET_AFTER_MISSES:
            source_listing.is_active = False
            affected.add(source_listing.listing_id)
        source_listing.save(update_fields=["missed_runs", "is_active"])
    for listing in Listing.objects.filter(pk__in=affected, is_active=True):
        active = listing.source_listings.filter(is_active=True)
        if not active.exists():
            listing.is_active = False
            listing.save(update_fields=["is_active", "updated_at"])
        elif "price" not in (listing.overrides or {}):
            # Another site still lists it: show the lowest price among the sites that remain.
            prices = active.filter(last_price__isnull=False).values_list("last_price", flat=True)
            listing.price = min(prices, default=listing.price)
            listing.save(update_fields=["price", "updated_at"])
