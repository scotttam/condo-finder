import httpx
import pytest

from listings import runner
from listings.ingest import ingest
from listings.models import Listing, PriceChange
from listings.scrapers.base import Fetcher, ScrapedListing, Scraper, is_candidate
from tests.helpers import make_source, scraped


def test_fetcher_request_supports_methods_and_json():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.params.get("q"), request.content))
        return httpx.Response(200, json={"ok": True})

    fetcher = Fetcher(delay=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert fetcher.get_json("https://x.example/api", params={"q": "1"}) == {"ok": True}
    fetcher.request("PUT", "https://x.example/api", json={"a": 1})
    assert seen[0][:2] == ("GET", "1")
    assert seen[1][0] == "PUT" and seen[1][2] == b'{"a":1}'


def test_fetcher_raises_on_http_error():
    fetcher = Fetcher(delay=0, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get("https://x.example/")


def test_is_candidate_falls_back_to_city_when_no_address():
    assert is_candidate(ScrapedListing(external_id="1", url="u", address="", city="Portland", beds=2))
    assert not is_candidate(ScrapedListing(external_id="2", url="u", address="", city="Vancouver", beds=2))
    assert not is_candidate(ScrapedListing(external_id="3", url="u", address="", city="", beds=2))


def test_should_fetch_detail_respects_known_ids_and_budget():
    scraper = Scraper(key="k", name="K", fetcher=object(), max_detail_fetches=2)
    scraper.known_ids = {"old"}
    new = ScrapedListing(external_id="new", url="u", address="")
    assert scraper.should_fetch_detail(new, 0)
    assert not scraper.should_fetch_detail(new, 2)
    assert not scraper.should_fetch_detail(ScrapedListing(external_id="old", url="u", address=""), 0)


def test_scraper_passes_request_delay_to_default_fetcher():
    scraper = Scraper(key="k", name="K", request_delay=3)
    assert scraper.fetcher.delay == 3


@pytest.mark.django_db
def test_ingest_refreshes_known_listing_without_address():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1", price=2500)])
    result = ingest(source, [ScrapedListing(external_id="cl1", url="https://example.com/cl1", address="", price=2400, beds=2)])
    listing = Listing.objects.get()
    assert result.seen == 1 and result.skipped == 0
    assert listing.price == 2400
    assert [p.price for p in PriceChange.objects.order_by("seen_at")] == [2500, 2400]


@pytest.mark.django_db
def test_ingest_skips_unknown_listing_without_address():
    result = ingest(make_source("craigslist"), [ScrapedListing(external_id="new", url="u", address="", beds=2)])
    assert result.skipped == 1 and Listing.objects.count() == 0


@pytest.mark.django_db
def test_refreshed_listing_is_not_marked_missing():
    source = make_source("craigslist")
    other = scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204")
    ingest(source, [scraped(external_id="cl1"), other])
    bare = ScrapedListing(external_id="cl1", url="u", address="", beds=2)
    for _ in range(3):
        ingest(source, [bare, other])
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True
