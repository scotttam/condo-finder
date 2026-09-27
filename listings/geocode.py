import logging
import re
import time

import httpx
from django.conf import settings
from django.utils import timezone

from .models import Listing

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "condo-finder/0.1 (personal apartment search)"
REQUEST_INTERVAL = 1.1  # Nominatim allows at most 1 request/second


def _get_json(client, url, params):
    params = {**params, "format": "jsonv2", "addressdetails": 1}
    if settings.NOMINATIM_EMAIL:
        params["email"] = settings.NOMINATIM_EMAIL
    response = client.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response.json()


def _neighborhood(address):
    return address.get("neighbourhood") or address.get("suburb") or address.get("quarter") or ""


def geocode_address(query, client):
    results = _get_json(client, NOMINATIM_URL, {"q": query, "limit": 1, "countrycodes": "us"})
    if not results:
        return None
    hit = results[0]
    return {"lat": float(hit["lat"]), "lng": float(hit["lon"]), "neighborhood": _neighborhood(hit.get("address", {}))}


def reverse_neighborhood(lat, lng, client):
    result = _get_json(client, NOMINATIM_REVERSE_URL, {"lat": lat, "lon": lng, "zoom": 17})
    return _neighborhood((result or {}).get("address", {}))


def clean_street(street):
    """Drop listing noise after the street: '... - NEW PROPERTY', '..., Lower Unit'."""
    return re.split(r"\s+-\s+|,", street or "", maxsplit=1)[0].strip()


def _queries(listing):
    street = clean_street(listing.street)
    # Many "Portland" mailing addresses (97229, 97223, 97224) are outside the city in
    # OpenStreetMap, so fall back to street + ZIP.
    queries = [f"{street}, {listing.city}, OR {listing.zip_code}".strip()]
    if listing.zip_code:
        queries.append(f"{street}, OR {listing.zip_code}")
    return queries


def geocode_pending(limit=200, client=None, sleep=time.sleep):
    """Locate listings not yet geocoded. Listings that came with coordinates from the listing
    site only get their neighborhood looked up; the site's coordinates are kept."""
    client = client or httpx.Client()
    done = 0
    for listing in Listing.objects.filter(geocoded_at__isnull=True).order_by("pk")[:limit]:
        try:
            if listing.latitude is not None and listing.longitude is not None:
                neighborhood = reverse_neighborhood(listing.latitude, listing.longitude, client)
                sleep(REQUEST_INTERVAL)
                listing.neighborhood = listing.neighborhood or neighborhood
            else:
                for query in _queries(listing):
                    result = geocode_address(query, client)
                    sleep(REQUEST_INTERVAL)
                    if result:
                        listing.latitude = result["lat"]
                        listing.longitude = result["lng"]
                        listing.neighborhood = listing.neighborhood or result["neighborhood"]
                        break
        except httpx.HTTPError as exc:
            log.warning("Geocoding failed (will retry next run): %s", exc)
            break
        listing.geocoded_at = timezone.now()
        listing.save(update_fields=["latitude", "longitude", "neighborhood", "geocoded_at"])
        done += 1
    return done
