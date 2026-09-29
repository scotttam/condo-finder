import json
from datetime import date
from decimal import Decimal

import pytest

from listings import views
from listings.ingest import ingest, refresh_source_listing
from listings.models import Listing, PriceChange
from listings.scrapers.base import RefreshBlocked, Scraper
from listings.scrapers.craigslist import CraigslistScraper
from listings.scrapers.redfin import RedfinScraper
from listings.scrapers.zillow import ZillowScraper
from tests.helpers import FakeFetcher, FakeResponse, load_fixture, make_source, scraped
from tests.test_zillow import CORNELL_PRICE_HISTORY, detail_html

pytestmark = pytest.mark.django_db
ZILLOW_URL = "https://www.zillow.com/homedetails/10805-NW-Cornell-Rd/186247313_zpid/"
CL_URL = "https://www.craigslist.org/view/d/portland-walk-in-closets-pet-friendly/bU7Ug1JzHJCR7gB5ESiHyM"


def zillow_page(price=4600):
    return detail_html({"homeStatus": "FOR_RENT", "price": price, "priceHistory": CORNELL_PRICE_HISTORY, "description": "Cozy home with a 2-car garage.",
                        "resoFacts": {"bathroomsFull": 2, "bathroomsHalf": 1, "atAGlanceFacts": [{"factLabel": "Laundry", "factValue": "In Unit"}]}})


# --- per-site refresh ---------------------------------------------------------------------

def test_zillow_refresh_returns_price_history_and_details():
    scraper = ZillowScraper(key="zillow", name="Zillow", fetcher=FakeFetcher({ZILLOW_URL: zillow_page()}), city_slugs=[])
    details = scraper.refresh_listing(ZILLOW_URL)
    assert details["price"] == 4600 and details["baths"] == Decimal("2.5")
    assert details["listed_at"] == date(2026, 8, 22) and len(details["price_history"]) == 4
    assert "Laundry: In Unit" in details["amenities"]


def test_craigslist_refresh_live_and_removed():
    live = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=FakeFetcher({CL_URL: load_fixture("craigslist_detail_0.html")}), search_url="x")
    assert live.refresh_listing(CL_URL)["price"] == 2339
    gone = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=FakeFetcher({CL_URL: "<h2>This posting has been deleted by its author.</h2>"}), search_url="x")
    assert gone.refresh_listing(CL_URL) == {"removed": True}


def test_redfin_refresh_reports_blocking():
    url = "https://www.redfin.com/OR/Portland/x/home/1"
    blocked = RedfinScraper(key="redfin", name="Redfin", region_ids=[],
                            fetcher=FakeFetcher({url: FakeResponse("", status_code=202, headers={"x-amzn-waf-action": "challenge"})}))
    with pytest.raises(RefreshBlocked):
        blocked.refresh_listing(url)
    ok = RedfinScraper(key="redfin", name="Redfin", region_ids=[], fetcher=FakeFetcher({url: load_fixture("redfin_detail.html")}))
    assert len(ok.refresh_listing(url)["price_history"]) == 3


def test_sites_without_history_cannot_refresh():
    assert Scraper.refresh_listing is not ZillowScraper.refresh_listing
    with pytest.raises(NotImplementedError):
        Scraper(key="k", name="K", fetcher=object()).refresh_listing("u")


# --- applying a refresh ---------------------------------------------------------------------

def test_refresh_applies_price_history_and_details():
    source = make_source("zillow")
    ingest(source, [scraped(external_id="z1", price=4800, description="Nice.")])
    source_listing = source.source_listings.get()
    scraper = ZillowScraper(key="zillow", name="Zillow", fetcher=FakeFetcher({ZILLOW_URL: zillow_page()}), city_slugs=[])
    summary = refresh_source_listing(source_listing, scraper.refresh_listing(ZILLOW_URL), parser_version=ZillowScraper.details_version)
    listing = Listing.objects.get()
    assert summary == {"new_entries": 5, "price": 4600, "removed": False}  # 4 history + the $4,800 -> $4,600 change
    assert listing.price == 4600 and listing.baths == Decimal("2.5") and listing.has_washer_dryer is True
    assert listing.listed_at == date(2026, 8, 22) and listing.parking_spaces == 2
    source_listing.refresh_from_db()
    assert source_listing.details_version == 2 and source_listing.last_price == 4600


def test_refresh_again_adds_nothing_new():
    source = make_source("zillow")
    ingest(source, [scraped(external_id="z1", price=4600)])
    source_listing = source.source_listings.get()
    details = ZillowScraper(key="zillow", name="Zillow", fetcher=FakeFetcher({ZILLOW_URL: zillow_page()}), city_slugs=[]).refresh_listing(ZILLOW_URL)
    refresh_source_listing(source_listing, details, parser_version=2)
    assert refresh_source_listing(source_listing, details, parser_version=2)["new_entries"] == 0


def test_refresh_of_a_removed_post_marks_it_gone():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="c1")])
    summary = refresh_source_listing(source.source_listings.get(), {"removed": True}, parser_version=1)
    assert summary["removed"] and Listing.objects.get().is_active is False


# --- the button ------------------------------------------------------------------------------

def test_detail_page_shows_refresh_button_only_for_refreshable_sites(client):
    ingest(make_source("zillow"), [scraped(external_id="z1")])
    listing = Listing.objects.get()
    assert f'hx-post="/listing/{listing.pk}/refresh/"' in client.get(f"/listing/{listing.pk}/").content.decode()
    pearl_only = Listing.objects.create(address_key="p", address="1 Pearl St", street="1 Pearl St", city="Portland")
    assert "/refresh/" not in client.get(f"/listing/{pearl_only.pk}/").content.decode()


def test_refresh_button_reports_each_site(client, monkeypatch):
    ingest(make_source("zillow"), [scraped(external_id="z1", price=4800, url=ZILLOW_URL)])
    ingest(make_source("redfin"), [scraped(external_id="r1", price=4800)])
    listing = Listing.objects.get()

    def fake_build(config, fetcher=None):
        if config["key"] == "zillow":
            return ZillowScraper(key="zillow", name="Zillow", fetcher=FakeFetcher({ZILLOW_URL: zillow_page()}), city_slugs=[])
        return RedfinScraper(key="redfin", name="Redfin", region_ids=[], fetcher=FakeFetcher({}, default=FakeResponse("", status_code=202, headers={"x-amzn-waf-action": "challenge"})))

    monkeypatch.setattr(views, "build_scraper", fake_build)
    response = client.post(f"/listing/{listing.pk}/refresh/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and response["HX-Refresh"] == "true"
    page = client.get(f"/listing/{listing.pk}/").content.decode()
    assert "Zillow: 5 new history entries, price $4,600" in page
    assert "Redfin: blocking requests right now" in page
    assert Listing.objects.get().price == 4600


def test_zillow_page_no_longer_for_rent_counts_as_removed():
    # 10805 NW Cornell Rd on 2026-09-29: homeStatus OTHER, "price" is the $1,027,800 home value.
    page = detail_html({"homeStatus": "OTHER", "price": 1027800, "zestimate": 1027800, "rentZestimate": 4594, "resoFacts": {}})
    scraper = ZillowScraper(key="zillow", name="Zillow", fetcher=FakeFetcher({ZILLOW_URL: page}), city_slugs=[])
    assert scraper.refresh_listing(ZILLOW_URL) == {"removed": True}


def test_zillow_page_for_rent_is_refreshed():
    page = detail_html({"homeStatus": "FOR_RENT", "price": 4600, "resoFacts": {}})
    scraper = ZillowScraper(key="zillow", name="Zillow", fetcher=FakeFetcher({ZILLOW_URL: page}), city_slugs=[])
    assert scraper.refresh_listing(ZILLOW_URL)["price"] == 4600


def test_implausible_rent_is_ignored():
    source = make_source("zillow")
    ingest(source, [scraped(external_id="z1", price=4600)])
    ingest(source, [scraped(external_id="z1", price=1027800)])
    listing = Listing.objects.get()
    assert listing.price == 4600 and source.source_listings.get().last_price == 4600
    assert not listing.price_changes.filter(price=1027800).exists()


def test_site_dropping_a_listing_reprices_from_the_remaining_sites():
    ingest(make_source("zillow"), [scraped(external_id="z1", price=4500)])
    ingest(make_source("rentengine"), [scraped(external_id="c1", price=4600)])
    zillow_copy = Listing.objects.get().source_listings.get(source__key="zillow")
    assert Listing.objects.get().price == 4500
    refresh_source_listing(zillow_copy, {"removed": True}, parser_version=2)
    assert Listing.objects.get().price == 4600
