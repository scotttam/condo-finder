import httpx
import pytest

from listings.geocode import geocode_address, geocode_pending
from tests.helpers import make_listing

NOMINATIM_HIT = [{
    "lat": "45.5268", "lon": "-122.6795",
    "address": {"neighbourhood": "Pearl District", "suburb": "Northwest", "city": "Portland"},
}]


def client_returning(payload, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_geocode_address_parses_result():
    seen = []
    result = geocode_address("937 NW Glisan Street, Portland, OR 97209", client_returning(NOMINATIM_HIT, seen=seen))
    assert result == {"lat": 45.5268, "lng": -122.6795, "neighborhood": "Pearl District"}
    assert seen[0].url.params["q"] == "937 NW Glisan Street, Portland, OR 97209"
    assert "condo-finder" in seen[0].headers["User-Agent"]


def test_geocode_address_no_match():
    assert geocode_address("nowhere", client_returning([])) is None


@pytest.mark.django_db
def test_geocode_pending_updates_listings():
    listing = make_listing()
    kept = make_listing(address_key="k", neighborhood="Custom")
    count = geocode_pending(client=client_returning(NOMINATIM_HIT), sleep=lambda s: None)
    assert count == 2
    listing.refresh_from_db()
    kept.refresh_from_db()
    assert (listing.latitude, listing.longitude, listing.neighborhood) == (45.5268, -122.6795, "Pearl District")
    assert listing.geocoded_at is not None
    assert kept.neighborhood == "Custom"
    assert geocode_pending(client=client_returning(NOMINATIM_HIT), sleep=lambda s: None) == 0


@pytest.mark.django_db
def test_geocode_pending_marks_misses_attempted():
    listing = make_listing()
    geocode_pending(client=client_returning([]), sleep=lambda s: None)
    listing.refresh_from_db()
    assert listing.latitude is None and listing.geocoded_at is not None


@pytest.mark.django_db
def test_geocode_pending_http_error_retries_later():
    listing = make_listing()
    assert geocode_pending(client=client_returning({}, status=503), sleep=lambda s: None) == 0
    listing.refresh_from_db()
    assert listing.geocoded_at is None
