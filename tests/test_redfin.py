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
    params = [kwargs["params"] for _, _, kwargs in fetcher.calls]
    assert [p["region_id"] for p in params] == [30772, 1432]
    assert all(p["num_beds"] == 2 and p["num_baths"] == 2 and p["isRentals"] == "true" for p in params)


def test_coordinates_come_from_centroid():
    item = items_by_address()["12859 SE Stark St Unit A28, Portland, OR 97233"]
    assert (item.latitude, item.longitude) == (45.5194678, -122.5310872)
