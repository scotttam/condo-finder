from decimal import Decimal

from listings.scrapers.appfolio import AppFolioScraper, parse_detail, parse_list
from listings.scrapers.base import ScrapedListing, is_candidate
from tests.helpers import FakeFetcher, load_fixture

BASE = "https://pearlpropertymanagement.appfolio.com"
FIRST_ID = "320665de-4759-4508-afa2-bb7567932ef4"


def test_parse_list_extracts_cards():
    items = parse_list(load_fixture("appfolio_list.html"), BASE)
    assert len(items) == 7
    first = items[0]
    assert first.external_id == FIRST_ID
    assert first.url == f"{BASE}/listings/detail/{FIRST_ID}"
    assert first.address == "937 NW Glisan Street #435, Portland, OR 97209"
    assert first.price == 2800
    assert first.beds == 2
    assert first.baths == Decimal("2")
    assert first.sqft == 1105
    assert first.available == "NOW"
    assert "937 Condos" in first.title
    assert first.photo_url.startswith("https://images.cdn.appfolio.com/")


def test_parse_detail_gets_full_description_and_amenities():
    detail = parse_detail(load_fixture("appfolio_detail.html"))
    assert "south facing 2 bedroom, 2 bath condo" in detail["description"]
    assert "1 Reserved Parking Space" in detail["amenities"]
    assert "Washer/Dryer" in detail["amenities"]


def test_is_candidate():
    ok = ScrapedListing(external_id="1", url="u", address="1 Main St, Portland, OR 97201", beds=2)
    assert is_candidate(ok)
    assert not is_candidate(ScrapedListing(external_id="2", url="u", address="1 Main St, Portland, OR 97201", beds=1))
    assert not is_candidate(ScrapedListing(external_id="3", url="u", address="1 Main St, Gresham, OR 97030", beds=3))


def test_scraper_fetches_details_only_for_candidates():
    fetcher = FakeFetcher({f"{BASE}/listings": load_fixture("appfolio_list.html")}, default=load_fixture("appfolio_detail.html"))
    scraper = AppFolioScraper(key="pearl", name="Pearl", fetcher=fetcher, subdomain="pearlpropertymanagement")
    items = scraper.scrape()
    assert len(items) == 7
    candidates = [i for i in items if is_candidate(i)]
    assert len(fetcher.requested) == 1 + len(candidates)
    assert all("Amenities" in i.amenities for i in candidates)
