from decimal import Decimal

from listings.scrapers.base import is_candidate
from listings.scrapers.craigslist import CraigslistScraper, parse_detail, parse_search
from tests.helpers import FakeFetcher, load_fixture

SEARCH_URL = "https://www.craigslist.org/search/area/portland?cat=apa&min_bedrooms=2&min_bathrooms=2"
FIRST = "bU7Ug1JzHJCR7gB5ESiHyM"


def test_parse_search_pairs_cards_with_structured_data():
    items = parse_search(load_fixture("craigslist_search.html"))
    assert len(items) == 12
    first = items[0]
    assert first.external_id == FIRST
    assert first.url == f"https://www.craigslist.org/view/d/portland-walk-in-closets-pet-friendly/{FIRST}"
    assert (first.price, first.beds, first.baths, first.city) == (2339, 2, Decimal("2"), "Portland")
    assert first.address == ""
    assert first.title == "Walk-in Closets, Pet-friendly, Wood Style Plank Flooring"


def test_zero_price_means_unknown():
    items = {i.external_id: i for i in parse_search(load_fixture("craigslist_search.html"))}
    assert items["wwzucJoGEbv4zNomuBVi2c"].price is None


def test_candidates_are_target_cities_only():
    items = parse_search(load_fixture("craigslist_search.html"))
    assert sum(is_candidate(i) for i in items) == 6
    assert {i.city for i in items if is_candidate(i)} == {"Portland"}


def test_parse_detail_apartment():
    detail = parse_detail(load_fixture("craigslist_detail_0.html"))
    assert detail["title"] == "Walk-in Closets, Pet-friendly, Wood Style Plank Flooring"
    assert detail["price"] == 2339
    assert detail["address"] == "1314 N Skidmore St, Portland, OR 97217"
    assert (detail["beds"], detail["baths"], detail["sqft"]) == (2, Decimal("2"), 961)
    assert detail["housing_type"] == "apartment"
    assert "Laundry: w/d in unit" in detail["amenities"]
    assert "Parking: carport" in detail["amenities"]
    assert "2 Bedroom, 2 Bath" in detail["description"]
    assert "QR Code" not in detail["description"]
    assert detail["photo_url"] == "https://images.craigslist.org/00H0H_9O33tAoZ4YI_0bT07V_600x450.jpg"


def test_parse_detail_house():
    detail = parse_detail(load_fixture("craigslist_detail_1.html"))
    assert detail["housing_type"] == "house"
    assert (detail["beds"], detail["sqft"]) == (3, 800)
    assert "Parking: off-street parking" in detail["amenities"]
    assert "Laundry: laundry in bldg" in detail["amenities"]


def test_scraper_fetches_details_for_new_candidates_only():
    fake = FakeFetcher({SEARCH_URL: load_fixture("craigslist_search.html")}, default=load_fixture("craigslist_detail_0.html"))
    scraper = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=fake, search_url=SEARCH_URL)
    scraper.known_ids = {FIRST}
    items = {i.external_id: i for i in scraper.scrape()}
    assert len(items) == 12
    assert len(fake.requested) == 1 + 5
    assert items[FIRST].address == ""  # known: refreshed by id during ingest, no detail fetch
    fetched = [i for i in items.values() if i.address]
    assert len(fetched) == 5
    assert all(i.property_type_hint == "apartment" and "w/d in unit" in i.amenities for i in fetched)


def test_coordinates_come_from_structured_data():
    first = parse_search(load_fixture("craigslist_search.html"))[0]
    assert (first.latitude, first.longitude) == (45.5546401373104, -122.679978430326)


def test_fetched_details_are_stamped_with_the_parser_version():
    fake = FakeFetcher({SEARCH_URL: load_fixture("craigslist_search.html")}, default=load_fixture("craigslist_detail_0.html"))
    items = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=fake, search_url=SEARCH_URL).scrape()
    assert sum(i.details_version == CraigslistScraper.details_version for i in items) == 6
    assert all(i.details_version == 0 for i in items if not i.address)
