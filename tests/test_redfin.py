import json
from decimal import Decimal

from listings.scrapers.redfin import API_URL, RedfinScraper, parse_rentals
from tests.helpers import FakeFetcher, load_fixture


def items_by_address():
    return {i.address: i for i in parse_rentals(json.loads(load_fixture("redfin_rentals.json")))}


def test_parses_every_rental():
    assert len(items_by_address()) == 12


def test_condo_unit():
    item = items_by_address()["12859 SE Stark St Unit A28, Portland, OR 97233"]
    assert item.property_type_hint == "Condo"
    assert (item.price, item.beds, item.baths, item.sqft) == (1695, 2, Decimal("2.0"), 1003)
    assert item.url == "https://www.redfin.com/OR/Portland/12859-SE-Stark-St-97233/unit-A28/home/26504934"
    assert item.external_id.startswith("6f69f705")
    assert item.photo_url.startswith("https://ssl.cdn-redfin.com/photo/rent/6f69f705")
    assert item.photo_url.endswith(".jpg")


def test_type_hints():
    items = items_by_address()
    assert items["1037 NE 104th Ave, Portland, OR 97220"].property_type_hint == "Single Family Home"
    assert items["19465 NW Mahama Pl Apt A, Portland, OR 97229"].property_type_hint == "Townhouse"
    assert items["6142 Bonita Rd, Lake Oswego, OR 97035"].property_type_hint == "Apartment"


def test_named_multi_unit_building_is_apartment_even_if_typed_townhouse():
    tower = items_by_address()["3820 S River Pkwy, Portland, OR 97239"]
    assert tower.property_type_hint == "Apartment"
    assert tower.title == "Willamette Tower"
    assert tower.price == 3471


def test_scraper_queries_each_region_with_filters():
    fetcher = FakeFetcher({API_URL: load_fixture("redfin_rentals.json")})
    items = RedfinScraper(key="redfin", name="Redfin", fetcher=fetcher, region_ids=[30772, 1432]).scrape()
    assert len(items) == 12  # same rentals returned for both regions are de-duplicated
    params = [kwargs["params"] for _, url, kwargs in fetcher.calls if url == API_URL]
    assert [p["region_id"] for p in params] == [30772, 1432]
    assert all(p["num_beds"] == 2 and p["num_baths"] == 2 and p["isRentals"] == "true" for p in params)


def test_coordinates_come_from_centroid():
    item = items_by_address()["12859 SE Stark St Unit A28, Portland, OR 97233"]
    assert (item.latitude, item.longitude) == (45.5194678, -122.5310872)


def test_parse_detail_description_amenities_and_rental_history():
    from datetime import date

    from listings.scrapers.redfin import parse_detail

    detail = parse_detail(load_fixture("redfin_detail.html"))
    assert detail["description"].startswith("This beautifully refreshed Mid-Century home")
    assert "Unit amenities: Dishwasher, Patio, Washer & Dryer In Unit" in detail["amenities"]
    assert "Garage" in detail["amenities"] and "Air Conditioning" in detail["amenities"]
    # Rental events only (the 2014 and 2026 sales are left out), in the order they happened,
    # named the same way as Zillow's.
    assert detail["price_history"] == [
        (date(2026, 9, 25), 2850, "Listed for rent"),
        (date(2026, 9, 25), 2850, "Listing removed"),
        (date(2026, 9, 26), 2850, "Listed for rent"),
    ]
    assert detail["listed_at"] == date(2026, 9, 26)


def test_detail_text_feeds_feature_detection():
    from listings.extract import extract_parking, has_ac, has_outdoor_space, has_washer_dryer
    from listings.scrapers.redfin import parse_detail

    detail = parse_detail(load_fixture("redfin_detail.html"))
    text = f"{detail['description']}\n{detail['amenities']}"
    assert (has_washer_dryer(text), has_ac(text), has_outdoor_space(text), extract_parking(text)) == (True, True, True, 2)


def test_page_without_data_raises_value_error():
    import pytest

    from listings.scrapers.redfin import parse_detail

    with pytest.raises(ValueError):
        parse_detail("<html>Access denied</html>")


def test_scraper_fetches_details_for_new_relevant_listings_and_skips_complexes():
    fetcher = FakeFetcher({API_URL: load_fixture("redfin_rentals.json")}, default=load_fixture("redfin_detail.html"))
    scraper = RedfinScraper(key="redfin", name="Redfin", fetcher=fetcher, region_ids=[30772], max_detail_fetches=3)
    scraper.known_ids = {i.external_id for i in parse_rentals(json.loads(load_fixture("redfin_rentals.json")))
                         if i.address.startswith("12859 SE Stark")}
    items = {i.address: i for i in scraper.scrape()}
    details = [url for _, url, _ in fetcher.calls if url != API_URL]
    assert len(details) == 3
    assert not any("Stark" in url for url in details)  # already fetched by this parser version
    assert all("Apartment" != items[a].property_type_hint for a, i in items.items() if i.details_version)
    fetched = [i for i in items.values() if i.details_version]
    assert len(fetched) == 3 and all(i.details_version == RedfinScraper.details_version == 2 for i in fetched)
    assert all(i.listed_at and i.price_history and "Washer & Dryer In Unit" in i.amenities for i in fetched)


def test_stops_fetching_listing_pages_at_the_first_block():
    from tests.helpers import FakeResponse

    rentals = parse_rentals(json.loads(load_fixture("redfin_rentals.json")))
    pages = {API_URL: load_fixture("redfin_rentals.json")}
    for item in rentals:
        pages[item.url] = FakeResponse("", status_code=202, headers={"x-amzn-waf-action": "challenge"})
    fetcher = FakeFetcher(pages)
    items = RedfinScraper(key="redfin", name="Redfin", fetcher=fetcher, region_ids=[30772], max_detail_fetches=10).scrape()
    assert len([url for _, url, _ in fetcher.calls if url != API_URL]) == 1  # no hammering once challenged
    assert len(items) == 12 and not any(i.details_version for i in items)  # search results still returned


def test_skips_listing_pages_for_listings_covered_elsewhere():
    fetcher = FakeFetcher({API_URL: load_fixture("redfin_rentals.json")}, default=load_fixture("redfin_detail.html"))
    scraper = RedfinScraper(key="redfin", name="Redfin", fetcher=fetcher, region_ids=[30772], max_detail_fetches=10)
    everything = {i.external_id for i in parse_rentals(json.loads(load_fixture("redfin_rentals.json")))}
    scraper.skip_detail_ids = everything
    scraper.scrape()
    assert [url for _, url, _ in fetcher.calls if url != API_URL] == []


def test_registry_paces_redfin_listing_pages_gently():
    from listings.scrapers.registry import SOURCES

    redfin = next(config for config in SOURCES if config["key"] == "redfin")
    assert (redfin["request_delay"], redfin["max_detail_fetches"], redfin["skip_details_if_on"]) == (20, 10, "zillow")
