from decimal import Decimal

from listings.scrapers.nesthub import NesthubScraper, parse_detail, parse_list
from listings.scrapers.registry import SOURCES, build_scraper
from tests.helpers import FakeFetcher, load_fixture

BASE = "https://www.uptownpm.com"
LIST_URL = f"{BASE}/portland-homes-for-rent"


def test_parse_list_extracts_cards():
    items = parse_list(load_fixture("nesthub_list.html"), BASE)
    assert len(items) == 19
    item = next(i for i in items if i.external_id == "13")
    assert item.url == f"{BASE}/_system/listings/13/4775-SW-FRANKLIN-AVE-APT-321-Beaverton-OR-97005-2943-US"
    assert item.address == "4775 SW FRANKLIN AVE APT 321, Beaverton, OR 97005"
    assert item.price == 1625
    assert item.beds == 2
    assert item.baths == Decimal("1")
    assert item.property_type_hint == "Apartment"
    assert item.available == "Immediately"
    assert item.title.startswith("Spacious NEW Construction")
    assert item.photo_url.startswith(f"{BASE}/_system/listings/images/")


def test_parse_detail():
    detail = parse_detail(load_fixture("nesthub_detail.html"))
    assert detail["sqft"] == 925
    assert detail["property_type_hint"] == "Apartment"
    assert detail["description"].startswith("Modern new construction")
    assert "Amenities:" not in detail["description"]
    assert "washer/dryer (included)" in detail["amenities"]
    assert detail["available"] == "Immediately"


def test_scraper_enriches_candidates():
    fetcher = FakeFetcher({LIST_URL: load_fixture("nesthub_list.html")}, default=load_fixture("nesthub_detail.html"))
    scraper = NesthubScraper(key="uptown", name="Uptown", fetcher=fetcher, list_url=LIST_URL)
    items = scraper.scrape()
    assert len(items) == 19
    item = next(i for i in items if i.external_id == "13")
    assert item.sqft == 925
    assert "washer/dryer" in item.amenities


def test_registry_builds_every_source():
    keys = [config["key"] for config in SOURCES]
    assert len(keys) == len(set(keys))
    for config in SOURCES:
        scraper = build_scraper(config, fetcher=FakeFetcher({}))
        assert scraper.key == config["key"]
        assert scraper.platform == config["platform"]
