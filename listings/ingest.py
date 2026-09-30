import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from types import SimpleNamespace

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
    is_furnished,
    has_washer_dryer,
)
from . import feed, merge
from .specials import extract_special
from .models import FeedEvent, Listing, PriceChange, PropertyType, SourceListing

log = logging.getLogger(__name__)

MAX_PLAUSIBLE_RENT = 25_000  # anything higher is a sale price or value estimate, not rent
LISTING_CHECKS_PER_RUN = 25  # direct listing-page checks before calling a listing gone (see _mark_missing)
RECHECK_DROPPED_WITHIN = timedelta(days=14)

OVERRIDABLE_FIELDS = {
    "price", "beds", "baths", "sqft", "parking_spaces", "has_parking", "has_washer_dryer", "has_ac",
    "has_outdoor_space", "is_furnished", "property_type", "neighborhood", "quadrant", "available", "title",
    "latitude", "longitude", "special_offer",
}


@dataclass
class IngestResult:
    seen: int = 0
    skipped: int = 0
    new_listings: list = field(default_factory=list)


def ingest(source, items, now=None, verify=None):
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
            listing, created, was_active, before = _upsert_listing(address, item, now, source)
            source_listing, previous_price, joined = _upsert_source_listing(source, listing, item, now)
            _update_price(listing, previous_price, item, now, source.name, created)
            # A new listing's own history isn't news; history revealing changes on a known one is.
            _import_history(listing, item.price_history, source.name, announce_at=None if created else now)
            if created:
                feed.record(listing, FeedEvent.Kind.NEW_LISTING, feed.listing_summary(listing), now, source.name)
            else:
                if not was_active:
                    feed.record(listing, FeedEvent.Kind.BACK_ON_MARKET, f"Listed again on {source.name}", now, source.name)
                if joined:
                    feed.record(listing, FeedEvent.Kind.NEW_SITE, f"Now also on {source.name}", now, source.name)
                feed.record_detail_changes(listing, before, now, source.name)
        seen_ids.add(source_listing.pk)
        result.seen += 1
        if created:
            result.new_listings.append(listing)
    if items:
        _mark_missing(source, seen_ids, now, verify)
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
    if current == own or (current and merge.same_home_keys(current, address.key)):
        return current  # including a listing already matched with or without its unit number
    taken = (
        SourceListing.objects.filter(source=source, listing__address_key=address.key)
        .exclude(external_id=item.external_id)
        .exists()
    )
    key = own if taken else address.key
    if not Listing.objects.filter(address_key=key).exists():
        # Redfin often leaves out the unit number that other sites give: the same home, not a new one.
        match = merge.unit_match(address.key, source, item.beds, item.baths, item.sqft, _plausible_rent(item.price))
        if match is not None:
            return match.address_key
    return key


def _upsert_listing(address, item, now, source):
    key = _listing_key(source, address, item)
    listing = Listing.objects.filter(address_key=key).first()
    created = listing is None
    if created:
        listing = Listing(address_key=key, first_seen_at=now)
    was_active = created or listing.is_active
    before = None if created else feed.snapshot(listing)
    if address.unit and listing.address_key == merge.bare_key(address.key) and not Listing.objects.filter(
        address_key=address.key
    ).exists():
        listing.address_key = address.key  # now we know its unit number
    _apply_scraped(listing, address, item)
    _apply_overrides(listing)
    listing.is_active = True
    listing.last_seen_at = now
    listing.save()
    return listing, created, was_active, before


def _plausible_rent(price, source=None):
    if price is not None and price > MAX_PLAUSIBLE_RENT:
        log.warning("Ignoring implausible rent $%s from %s", f"{price:,}", getattr(source, "name", source))
        return None
    return price


def _recompute_price(listing):
    """The lowest current price among the sites still listing it (unless overridden)."""
    if "price" in (listing.overrides or {}):
        return
    prices = listing.source_listings.filter(is_active=True, last_price__isnull=False).values_list("last_price", flat=True)
    listing.price = min(prices, default=listing.price)
    listing.save(update_fields=["price", "updated_at"])


def _update_price(listing, previous_price, item, now, source_name, created):
    """The listing shows the lowest current price among the sites listing it. A price change is
    recorded only when one site changes its own price: sites disagreeing (a building's "from" price
    vs one unit, say) isn't a change."""
    if "price" in (listing.overrides or {}):
        listing.price = listing.overrides["price"]
        listing.save(update_fields=["price", "updated_at"])
    else:
        _recompute_price(listing)
    if _plausible_rent(item.price) is None:
        return
    if created:
        PriceChange.objects.create(listing=listing, price=listing.price, seen_at=now, event="First seen", source=source_name)
    elif previous_price is not None and item.price != previous_price:
        PriceChange.objects.create(listing=listing, price=item.price, seen_at=now, event="Price change", source=source_name)
        feed.record(listing, FeedEvent.Kind.PRICE_CHANGE, f"{source_name}: ${previous_price:,} → ${item.price:,}", now,
                    source_name, old_price=previous_price, new_price=item.price)


def _history_time(day):
    return timezone.make_aware(datetime.combine(day, time(12)))


def _import_history(listing, entries, source_name, announce_at=None):
    """Add a listing site's own rental history. Entries already present (same day and price, e.g.
    typed in by hand) are labelled rather than duplicated. With announce_at, newly found price
    changes go to the feed (dated when they happened, announced now)."""
    if not entries:
        return
    imported = []
    for day, price, event in entries:
        existing = listing.price_changes.filter(seen_at__date=day, price=price).first()
        if existing is None:
            existing = PriceChange.objects.create(
                listing=listing, price=price, seen_at=_history_time(day), event=event, source=source_name
            )
            if announce_at and event == "Price change":
                earlier = listing.price_changes.filter(seen_at__lt=existing.seen_at).order_by("-seen_at").first()
                old = earlier.price if earlier else None
                summary = f"{source_name}: " + (f"${old:,} → ${price:,}" if old else f"${price:,}") + f" on {day:%b} {day.day}"
                feed.record(listing, FeedEvent.Kind.PRICE_CHANGE, summary, announce_at, source_name,
                            happened_at=existing.seen_at, old_price=old, new_price=price)
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
    if address.unit or not listing.unit:  # a site that leaves out the unit number doesn't erase it
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
        "is_furnished": is_furnished(text),
    }
    for name, value in extracted.items():
        if value is not None:
            setattr(listing, name, value)
    property_type = classify_property_type(hint, text)
    if property_type != PropertyType.UNKNOWN:
        listing.property_type = property_type
    # Unlike features, a special ends: read it from the listing's current text, so it clears when
    # the site drops it (and one site's text without it doesn't erase another's).
    listing.special_offer = extract_special(f"{listing.title}\n{listing.description}") or ""


def _apply_overrides(listing):
    for name, value in (listing.overrides or {}).items():
        if name in OVERRIDABLE_FIELDS:
            setattr(listing, name, value)


REEXTRACTED_FIELDS = [
    "parking_spaces", "has_parking", "has_washer_dryer", "has_ac", "has_outdoor_space", "is_furnished", "property_type",
    "special_offer",
]


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
    if _plausible_rent(item.price, source) is not None:
        source_listing.last_price = item.price
    source_listing.save()
    return source_listing, previous_price, created and source_listing.listing.source_listings.count() > 1


def _refresh_known(source, item, now, result, seen_ids):
    """A listing we already stored, seen again without its address (detail page skipped)."""
    source_listing = (
        SourceListing.objects.select_related("listing").filter(source=source, external_id=item.external_id).first()
    )
    if source_listing is None:
        return False
    listing = source_listing.listing
    with transaction.atomic():
        if not listing.is_active:
            feed.record(listing, FeedEvent.Kind.BACK_ON_MARKET, f"Listed again on {source.name}", now, source.name)
        listing.is_active = True
        listing.last_seen_at = now
        listing.save()
        _, previous_price, _ = _upsert_source_listing(source, listing, item, now)
        _update_price(listing, previous_price, item, now, source.name, created=False)
    seen_ids.add(source_listing.pk)
    result.seen += 1
    return True


def _mark_missing(source, seen_ids, now, verify=None):
    """Listings this source didn't return count a miss; at OFF_MARKET_AFTER_MISSES they're gone.
    When the source can check a listing directly (verify(url) -> (listed?, price)), a listing about to
    be called gone is checked first, and recently dropped ones are re-checked."""
    checks_left = LISTING_CHECKS_PER_RUN if verify else 0
    affected, checked = set(), set()
    outcomes = {"still up": 0, "confirmed gone": 0, "unknown": 0}
    missing = SourceListing.objects.filter(source=source, is_active=True).exclude(pk__in=seen_ids).select_related("listing")
    for source_listing in missing:
        if checks_left and source_listing.missed_runs + 1 >= settings.OFF_MARKET_AFTER_MISSES:
            checks_left -= 1
            checked.add(source_listing.pk)
            listed, price = verify(source_listing.url)
            outcomes["still up" if listed else "confirmed gone" if listed is False else "unknown"] += 1
            if listed:
                _still_listed(source_listing, price, now, source.name)
                continue
            if listed is False:
                source_listing.missed_runs = settings.OFF_MARKET_AFTER_MISSES - 1  # confirmed gone
        source_listing.missed_runs += 1
        if source_listing.missed_runs >= settings.OFF_MARKET_AFTER_MISSES:
            source_listing.is_active = False
            affected.add(source_listing.listing_id)
        source_listing.save(update_fields=["missed_runs", "is_active"])
    if checks_left:
        recently_dropped = (
            SourceListing.objects.filter(source=source, is_active=False, last_seen_at__gte=now - RECHECK_DROPPED_WITHIN)
            .exclude(pk__in=seen_ids | checked)
            .select_related("listing")
            .order_by("-last_seen_at")[:checks_left]
        )
        for source_listing in recently_dropped:
            listed, price = verify(source_listing.url)
            outcomes["still up" if listed else "confirmed gone" if listed is False else "unknown"] += 1
            if listed:
                _still_listed(source_listing, price, now, source.name)
    if verify and any(outcomes.values()):
        log.info("%s listing checks: %s", source.name, ", ".join(f"{count} {label}" for label, count in outcomes.items()))
    for listing in Listing.objects.filter(pk__in=affected, is_active=True):
        active = listing.source_listings.filter(is_active=True)
        if not active.exists():
            listing.is_active = False
            listing.save(update_fields=["is_active", "updated_at"])
            feed.record(listing, FeedEvent.Kind.OFF_MARKET, "No longer listed on any site", now, source.name)
        else:
            _recompute_price(listing)  # another site still lists it


def refresh_source_listing(source_listing, details, parser_version, now=None):
    """Apply one listing page fetched on demand (Scraper.refresh_listing). Returns a summary:
    {"new_entries": price-history entries added, "price": that site's current price, "removed": bool}."""
    now = now or timezone.now()
    source = source_listing.source
    listing = source_listing.listing
    if details.get("removed"):
        source_listing.is_active = False
        source_listing.save(update_fields=["is_active"])
        if listing.source_listings.filter(is_active=True).exists():
            _recompute_price(listing)
        else:
            listing.is_active = False
            listing.save(update_fields=["is_active", "updated_at"])
            feed.record(listing, FeedEvent.Kind.OFF_MARKET, "No longer listed on any site", now, source.name)
        return {"new_entries": 0, "price": None, "removed": True}

    entries_before = listing.price_changes.count()
    before = feed.snapshot(listing)
    with transaction.atomic():
        if details.get("description") or details.get("amenities"):
            listing.description = "\n\n".join(p for p in (details.get("description"), details.get("amenities")) if p)
            _apply_extracted(listing, f"{listing.title}\n{listing.description}", details.get("home_type", ""))
        if details.get("baths") is not None:
            listing.baths = details["baths"]
        if details.get("listed_at") and (listing.listed_at is None or details["listed_at"] < listing.listed_at):
            listing.listed_at = details["listed_at"]
        _apply_overrides(listing)
        listing.save()
        feed.record_detail_changes(listing, before, now, source.name)
        _import_history(listing, details.get("price_history") or [], source.name, announce_at=now)
        # The page proves it's still listed, and carries this site's current price.
        _still_listed(source_listing, details.get("price"), now, source.name)
        source_listing.details_version = max(source_listing.details_version, parser_version)
        source_listing.save(update_fields=["details_version"])
    return {"new_entries": listing.price_changes.count() - entries_before, "price": _plausible_rent(details.get("price")),
            "removed": False}


def _still_listed(source_listing, price, now, source_name):
    """A direct check found the listing still up: keep (or bring back) it and note its price."""
    previous_price = source_listing.last_price
    price = _plausible_rent(price, source_name)
    source_listing.is_active = True
    source_listing.missed_runs = 0
    source_listing.last_seen_at = now
    if price is not None:
        source_listing.last_price = price
    source_listing.save(update_fields=["is_active", "missed_runs", "last_seen_at", "last_price"])
    listing = source_listing.listing
    if not listing.is_active:
        feed.record(listing, FeedEvent.Kind.BACK_ON_MARKET, f"Still listed on {source_name}", now, source_name)
    listing.is_active = True
    listing.last_seen_at = now
    listing.save(update_fields=["is_active", "last_seen_at", "updated_at"])
    _update_price(listing, previous_price, SimpleNamespace(price=price), now, source_name, created=False)
