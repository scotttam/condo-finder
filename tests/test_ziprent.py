from decimal import Decimal

from listings.scrapers.registry import SOURCES, build_scraper
from listings.scrapers.ziprent import LISTING_URL, SEARCH_URL, parse_detail, parse_listings
from tests.helpers import FakeFetcher, FakeResponse, load_fixture

SAVIER = "60700"


def search_records():
    import json

    return json.loads(load_fixture("ziprent_search.json"))["response"]


def test_parse_listings_reads_listing_fields():
    items = parse_listings(search_records())
    savier = next(item for item in items if item.external_id == SAVIER)
    assert savier.url == "https://listings.ziprent.com/show/60700"
    assert savier.address == "2478 NW Savier St #5, Portland, OR 97210"
    assert (savier.price, savier.beds, savier.baths) == (2100, 2, Decimal("1"))
    assert savier.latitude and savier.longitude
    assert savier.photo_url.startswith("https://cdn.ziprent.com/property_photos/60700/")


def test_parse_listings_skips_empty_and_test_records():
    ids = [item.external_id for item in parse_listings(search_records())]
    assert ids == ["60700", "63427", "33730", "64725"]


def test_address_without_unit():
    sheffield = next(item for item in parse_listings(search_records()) if item.external_id == "33730")
    assert sheffield.address.startswith("2285 Northeast Sheffield Ave, Beaverton, OR 97006")
    assert "#" not in sheffield.address


def test_parse_detail_gets_description_facts_and_size():
    detail = parse_detail(load_fixture("ziprent_show.html"))
    assert detail["description"].startswith("Discover urban living")
    assert "Parking: Off Street, 1 spaces" in detail["description"]
    assert "Laundry: Shared" in detail["amenities"]
    assert detail["sqft"] == 600
    assert detail["available"] == "NOW"


def test_scrape_posts_one_search_and_fetches_details_for_candidates_only():
    config = next(config for config in SOURCES if config["key"] == "ziprent")
    fetcher = FakeFetcher({SEARCH_URL: FakeResponse(load_fixture("ziprent_search.json"))}, default=load_fixture("ziprent_show.html"))
    items = build_scraper(config, fetcher=fetcher).scrape()
    method, url, kwargs = fetcher.calls[0]
    assert (method, url, kwargs.get("json")) == ("POST", SEARCH_URL, {})
    details = [url for method, url, _ in fetcher.calls[1:]]
    # Savier (Portland, 2 bd) and Sheffield (Beaverton, 3 bd); not the 1-bed or the California listing.
    assert details == [LISTING_URL.format(id=SAVIER), LISTING_URL.format(id="33730")]
    savier = next(item for item in items if item.external_id == SAVIER)
    assert savier.sqft == 600
    assert savier.available == "NOW"
    assert savier.description.startswith("Discover urban living")
