import logging
import time

import httpx
from django.conf import settings
from django.utils import timezone

from .models import Listing

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "condo-finder/0.1 (personal apartment search)"


def geocode_address(query, client):
    params = {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 1, "countrycodes": "us"}
    if settings.NOMINATIM_EMAIL:
        params["email"] = settings.NOMINATIM_EMAIL
    response = client.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    hit = results[0]
    address = hit.get("address", {})
    return {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "neighborhood": address.get("neighbourhood") or address.get("suburb") or address.get("quarter") or "",
    }


def geocode_pending(limit=50, client=None, sleep=time.sleep):
    """Geocode listings never attempted before. Nominatim allows at most 1 request/second."""
    client = client or httpx.Client()
    done = 0
    for listing in Listing.objects.filter(geocoded_at__isnull=True).order_by("pk")[:limit]:
        query = f"{listing.street}, {listing.city}, OR {listing.zip_code}".strip()
        try:
            result = geocode_address(query, client)
        except httpx.HTTPError as exc:
            log.warning("Geocoding failed (will retry next run): %s", exc)
            break
        if result:
            listing.latitude = result["lat"]
            listing.longitude = result["lng"]
            listing.neighborhood = listing.neighborhood or result["neighborhood"]
        listing.geocoded_at = timezone.now()
        listing.save(update_fields=["latitude", "longitude", "neighborhood", "geocoded_at"])
        done += 1
        sleep(1.1)
    return done
