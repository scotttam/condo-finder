import logging

import httpx
from django.conf import settings

from .models import PropertyType, Status

log = logging.getLogger(__name__)

MAX_INDIVIDUAL_ALERTS = 5


def send_push(title, message, url="", tags=None):
    if not settings.NTFY_TOPIC:
        log.info("Push (ntfy disabled): %s | %s", title, message)
        return False
    payload = {"topic": settings.NTFY_TOPIC, "title": title, "message": message}
    if url:
        payload["click"] = url
    if tags:
        payload["tags"] = tags
    try:
        httpx.post(settings.NTFY_SERVER, json=payload, timeout=10).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("ntfy push failed: %s", exc)
        return False
    return True


def matches_alert_criteria(listing):
    """Known failures disqualify; unknowns pass."""
    if listing.beds is None or listing.beds < 2:
        return False
    if listing.baths is None or listing.baths < 2:
        return False
    if listing.price is None or listing.price > settings.ALERT_MAX_PRICE:
        return False
    if listing.property_type == PropertyType.APARTMENT:
        return False
    if listing.parking_spaces is not None and listing.parking_spaces < 2:
        return False
    return all(value is not False for value in (listing.has_washer_dryer, listing.has_ac, listing.has_outdoor_space))


def summarize(listing):
    baths = "?" if listing.baths is None else f"{listing.baths.normalize():f}"
    parts = [f"${listing.price:,}" if listing.price else "price ?", f"{listing.beds}bd/{baths}ba"]
    if listing.sqft:
        parts.append(f"{listing.sqft:,} sqft")
    parts.append(f"parking {'?' if listing.parking_spaces is None else listing.parking_spaces}")
    parts.append(listing.city)
    return " · ".join(parts)


def listing_url(listing):
    return f"{settings.SITE_URL}/listing/{listing.pk}/"


def alert_new_listings(listings):
    matches = [listing for listing in listings if matches_alert_criteria(listing)]
    for listing in matches[:MAX_INDIVIDUAL_ALERTS]:
        send_push(f"New: {listing.street}", summarize(listing), url=listing_url(listing), tags=["house"])
    extra = len(matches) - MAX_INDIVIDUAL_ALERTS
    if extra > 0:
        send_push(f"{extra} more new matches", "Open Condo Finder to see them.", url=f"{settings.SITE_URL}/")
    return len(matches)


def alert_price_drops(drops):
    sent = 0
    for listing, old_price, new_price in drops:
        if listing.status != Status.INTERESTED:
            continue
        send_push(
            f"Price drop: {listing.street}",
            f"${old_price:,} → ${new_price:,} · {summarize(listing)}",
            url=listing_url(listing),
            tags=["chart_with_downwards_trend"],
        )
        sent += 1
    return sent
