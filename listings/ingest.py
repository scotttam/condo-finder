from dataclasses import dataclass, field

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
            listing, created = _upsert_listing(address, item, now)
            source_listing = _upsert_source_listing(source, listing, item, now)
        seen_ids.add(source_listing.pk)
        result.seen += 1
        if created:
            result.new_listings.append(listing)
    if items:
        _mark_missing(source, seen_ids)
    return result


def _upsert_listing(address, item, now):
    listing = Listing.objects.filter(address_key=address.key).first()
    created = listing is None
    if created:
        listing = Listing(address_key=address.key, first_seen_at=now)
    old_price = listing.price
    _apply_scraped(listing, address, item)
    _apply_overrides(listing)
    listing.is_active = True
    listing.last_seen_at = now
    listing.save()
    if listing.price is not None and listing.price != old_price:
        PriceChange.objects.create(listing=listing, price=listing.price, seen_at=now)
    return listing, created


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
    if item.latitude is not None and item.longitude is not None:
        # The listing site's own pin beats a geocoded guess from the street address.
        listing.latitude = item.latitude
        listing.longitude = item.longitude
    for name in ("price", "beds", "baths", "sqft"):
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
        source_listing.save()
    return source_listing


def _refresh_known(source, item, now, result, seen_ids):
    """A listing we already stored, seen again without its address (detail page skipped)."""
    source_listing = (
        SourceListing.objects.select_related("listing").filter(source=source, external_id=item.external_id).first()
    )
    if source_listing is None:
        return False
    listing = source_listing.listing
    old_price = listing.price
    with transaction.atomic():
        if item.price is not None and "price" not in (listing.overrides or {}):
            listing.price = item.price
        listing.is_active = True
        listing.last_seen_at = now
        listing.save()
        if listing.price is not None and listing.price != old_price:
            PriceChange.objects.create(listing=listing, price=listing.price, seen_at=now)
        _upsert_source_listing(source, listing, item, now)
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
        if not listing.source_listings.filter(is_active=True).exists():
            listing.is_active = False
            listing.save(update_fields=["is_active", "updated_at"])
