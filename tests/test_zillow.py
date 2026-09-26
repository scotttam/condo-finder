import json
from decimal import Decimal

from listings.scrapers.zillow import (
    SEARCH_API,
    SEARCH_PAGE,
    ZillowScraper,
    parse_detail,
    parse_query_state,
    parse_results,
)
from tests.helpers import FakeFetcher, load_fixture

PORTLAND = SEARCH_PAGE.format(slug="portland-or")


def results():
    items, pages = parse_results(json.loads(load_fixture("zillow_api_page.json")))
    return {i.external_id: i for i in items}, pages


def test_query_state_has_region_and_bounds():
    state = parse_query_state(load_fixture("zillow_search_page.html"))
    assert state["regionSelection"] == [{"regionId": 13373, "regionType": 6}]
    assert set(state["mapBounds"]) >= {"north", "south", "east", "west"}


def test_building_summaries_are_skipped():
    items, pages = results()
    assert pages == 1
    assert set(items) == {"465501490", "2083535903", "464432454", "54003809", "2083259756", "2077222357", "53856550"}


def test_townhouse_result():
    item = results()[0]["54003809"]
    assert item.address == "5720 SE Duke St, Portland, OR 97206"
    assert (item.price, item.beds, item.baths, item.sqft) == (2850, 2, Decimal("3.0"), 1095)
    assert item.property_type_hint == "Townhouse"
    assert item.url == "https://www.zillow.com/homedetails/5720-SE-Duke-St-Portland-OR-97206/54003809_zpid/"
    assert item.title == ""


def test_building_unit_uses_street_fields_and_building_name():
    item = results()[0]["465501490"]
    assert item.address == "900 NW Lovejoy St #1-207, Portland, OR 97209"
    assert item.title == "Burlington Tower"
    assert item.property_type_hint == "Apartment"


def test_condo_hint():
    assert results()[0]["53856550"].property_type_hint == "Condo"


def test_parse_detail():
    detail = parse_detail(load_fixture("zillow_detail.html"))
    assert detail["description"].startswith("Make room for a little more comfort at 5720 SE Duke Street")
    assert "Date available: Available Now" in detail["amenities"]
    assert "Appliances: Dishwasher, Microwave Oven, Refrigerator" in detail["amenities"]
    assert detail["home_type"] == "Townhouse"


def fetcher():
    return FakeFetcher(
        {PORTLAND: load_fixture("zillow_search_page.html"), SEARCH_API: load_fixture("zillow_api_page.json")},
        default=load_fixture("zillow_detail.html"),
    )


def test_scraper_searches_then_fetches_limited_details():
    fake = fetcher()
    scraper = ZillowScraper(key="zillow", name="Zillow", fetcher=fake, city_slugs=["portland-or"], max_detail_fetches=2)
    scraper.known_ids = {"465501490"}
    items = scraper.scrape()
    assert len(items) == 7
    methods = [(method, url) for method, url, _ in fake.calls]
    assert methods[0] == ("GET", PORTLAND)
    assert methods[1][0] == "PUT" and methods[1][1] == SEARCH_API
    assert len(methods) == 2 + 2  # two detail pages, budget-limited
    body = fake.calls[1][2]["json"]["searchQueryState"]
    assert body["filterState"]["beds"] == {"min": 2} and body["filterState"]["fr"] == {"value": True}
    assert body["regionSelection"] == [{"regionId": 13373, "regionType": 6}]
    # Units inside apartment complexes (/apartments/ URLs) use a different page layout and
    # are apartments anyway, so the detail budget goes to /homedetails/ listings.
    assert {i.external_id for i in items if i.description} == {"54003809", "2083259756"}
    assert all("/homedetails/" in url for _, url, _ in fake.calls[2:])
