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


@pytest.mark.parametrize(
    "street,expected",
    [
        ("9038 NE Humboldt Street - NEW PROPERTY", "9038 NE Humboldt Street"),
        ("2725 SE Stark Avenue, Lower Unit", "2725 SE Stark Avenue"),
        ("937 NW Glisan Street", "937 NW Glisan Street"),
    ],
)
def test_clean_street(street, expected):
    from listings.geocode import clean_street

    assert clean_street(street) == expected


def routed_client(routes, seen):
    """routes: list of (predicate(request) -> bool, payload); first match wins, else []."""
    def handler(request):
        seen.append(request)
        for predicate, payload in routes:
            if predicate(request):
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json=[])
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.django_db
def test_geocode_retries_without_city_for_unincorporated_portland_addresses():
    listing = make_listing(street="4300 NW Chanticleer Dr - NEW PROPERTY", zip_code="97229")
    seen, sleeps = [], []
    client = routed_client([(lambda r: "Portland" not in r.url.params.get("q", ""), NOMINATIM_HIT)], seen)
    geocode_pending(client=client, sleep=sleeps.append)
    listing.refresh_from_db()
    assert [r.url.params["q"] for r in seen] == [
        "4300 NW Chanticleer Dr, Portland, OR 97229",
        "4300 NW Chanticleer Dr, OR 97229",
    ]
    assert (listing.latitude, listing.longitude) == (45.5268, -122.6795)
    assert len(sleeps) == 2  # one pause per Nominatim request


@pytest.mark.django_db
def test_listing_with_site_coordinates_only_looks_up_neighborhood():
    listing = make_listing(latitude=45.49, longitude=-122.67)
    seen = []
    client = routed_client([(lambda r: r.url.path == "/reverse", {"address": {"neighbourhood": "Hillsdale"}})], seen)
    assert geocode_pending(client=client, sleep=lambda s: None) == 1
    listing.refresh_from_db()
    assert [r.url.path for r in seen] == ["/reverse"]
    assert seen[0].url.params["lat"] == "45.49" and seen[0].url.params["lon"] == "-122.67"
    assert (listing.latitude, listing.longitude, listing.neighborhood) == (45.49, -122.67, "Hillsdale")
    assert listing.geocoded_at is not None


@pytest.mark.django_db
def test_geocode_batch_is_200_per_run():
    import inspect

    assert inspect.signature(geocode_pending).parameters["limit"].default == 200
