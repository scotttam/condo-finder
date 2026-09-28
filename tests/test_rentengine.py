import json
from decimal import Decimal

from listings.extract import extract_parking, has_washer_dryer
from listings.scrapers.base import is_candidate
from listings.scrapers.rentengine import RentEngineScraper, RentEngineSession, parse_detail, parse_listings
from tests.helpers import load_fixture

ACCOUNT = "abae6b5b-da14-4292-b081-389f7dfcefb7"  # Chroma Property Management


def items():
    data = json.loads(load_fixture("rentengine_listings.json"))
    return {item.external_id: item for item in parse_listings(data, ACCOUNT)}


def test_parses_every_listing():
    assert len(items()) == 15


def test_house_fields():
    item = items()["64401"]
    assert item.address == "6933 North Interstate Avenue, Portland, OR 97217"
    assert (item.price, item.beds, item.baths, item.sqft) == (3095, 3, Decimal("2"), 3640)
    assert item.property_type_hint == "Single Family Residence"
    assert (item.latitude, item.longitude) == (45.573228, -122.6824532)
    assert item.available == "2026-06-05"
    assert item.url == f"https://www.rentengine.io/listings/64401?accounts={ACCOUNT}"
    assert item.photo_url == "https://cdn.public-photos.rentengine.io/images/d6939d8d-77d1-49e0-adf0-25155183c7b4.jpg"


def test_unit_number_and_condo_type():
    item = items()["85944"]
    assert item.address == "1133 Northwest 11th Avenue #511, Portland, OR 97209"
    assert item.property_type_hint == "Condo"
    assert items()["80825"].baths == Decimal("1.5")


def test_candidates_are_target_city_two_plus_beds():
    candidates = sorted(i.external_id for i in items().values() if is_candidate(i))
    assert candidates == ["64401", "81084", "82898", "84431", "90316", "90950", "91593", "92369"]


def test_parse_detail():
    detail = parse_detail(load_fixture("rentengine_detail.html"))
    assert detail["description"].startswith("Colorful Portland Foursquare with Huge Attic & Double Garage")
    assert "Move In Special" in detail["description"]
    assert "2 parking spaces" in detail["amenities"]
    assert "Parking: Driveway, Private Garage" in detail["amenities"]
    assert "Laundry: In Unit" in detail["amenities"]
    assert "Amenities: Washer, Dryer" in detail["amenities"]
    assert "Top features: Charming Portland Foursquare" in detail["amenities"]


def test_detail_text_feeds_feature_detection():
    detail = parse_detail(load_fixture("rentengine_detail.html"))
    text = f"{detail['description']}\n{detail['amenities']}"
    assert extract_parking(text) == 2
    assert has_washer_dryer(text) is True


class FakeSession:
    def __init__(self):
        self.slug = None
        self.opened = []
        self.closed = False

    def listings(self, slug):
        self.slug = slug
        return ACCOUNT, json.loads(load_fixture("rentengine_listings.json"))

    def detail_html(self, url):
        self.opened.append(url)
        return load_fixture("rentengine_detail.html")

    def close(self):
        self.closed = True


def test_scraper_fetches_details_for_new_relevant_candidates_within_budget():
    session = FakeSession()
    scraper = RentEngineScraper(key="chroma", name="Chroma", fetcher=session, slug="chromapm", max_detail_fetches=3)
    scraper.known_ids = {"64401"}
    result = {item.external_id: item for item in scraper.scrape()}
    assert session.slug == "chromapm"
    assert len(result) == 15
    opened = [url.split("/listings/")[1].split("?")[0] for url in session.opened]
    assert opened == ["81084", "82898", "84431"]  # known 64401 skipped; in-budget first, search order kept
    described = [item for item in result.values() if item.description]
    assert len(described) == 3 and all("Laundry: In Unit" in item.amenities for item in described)
    assert session.closed


def test_default_fetcher_is_a_lazy_browser_session():
    scraper = RentEngineScraper(key="chroma", name="Chroma", slug="chromapm", request_delay=2)
    assert isinstance(scraper.fetcher, RentEngineSession)
    assert scraper.fetcher.delay == 2
    assert scraper.fetcher._browser is None  # Chromium only starts when a scrape runs


def test_fetched_details_are_stamped_with_the_parser_version():
    scraper = RentEngineScraper(key="chroma", name="Chroma", fetcher=FakeSession(), slug="chromapm", max_detail_fetches=3)
    items = scraper.scrape()
    assert sum(i.details_version == RentEngineScraper.details_version for i in items) == 3
