from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from listings import runner
from listings.ingest import LISTING_CHECKS_PER_RUN, ingest
from listings.models import Listing, PriceChange, SourceListing
from listings.scrapers.base import Scraper
from listings.scrapers.craigslist import CraigslistScraper
from tests.helpers import FakeFetcher, FakeResponse, load_fixture, make_source, scraped

pytestmark = pytest.mark.django_db

POST = "https://www.craigslist.org/view/d/portland-walk-in-closets-pet-friendly/bU7Ug1JzHJCR7gB5ESiHyM"
OTHER = scraped(external_id="other", address="100 SW Main St, Portland, OR 97204")


def run_misses(source, times, verify=None):
    for _ in range(times):
        ingest(source, [OTHER], verify=verify)


# --- Craigslist posting check -------------------------------------------------------------

def test_live_posting_is_listed_with_its_current_price():
    scraper = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=FakeFetcher({POST: load_fixture("craigslist_detail_0.html")}), search_url="x")
    assert scraper.check_listing(POST) == (True, 2339)


@pytest.mark.parametrize("response", [
    FakeResponse("<html><body><h2>This posting has been deleted by its author.</h2></body></html>"),
    FakeResponse("<html><body><h2>This posting has expired.</h2></body></html>"),
])
def test_deleted_or_expired_posting_is_not_listed(response):
    scraper = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=FakeFetcher({POST: response}), search_url="x")
    assert scraper.check_listing(POST) == (False, None)


def test_missing_posting_page_is_not_listed():
    import httpx

    class Gone:
        def get(self, url):
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request))

    scraper = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=Gone(), search_url="x")
    assert scraper.check_listing(POST) == (False, None)


def test_unreadable_page_is_unknown():
    scraper = CraigslistScraper(key="craigslist", name="Craigslist", fetcher=FakeFetcher({POST: "<html>busy</html>"}), search_url="x")
    assert scraper.check_listing(POST) == (None, None)


def test_sources_without_a_check_report_unknown():
    assert Scraper(key="k", name="K", fetcher=object()).check_listing("u") == (None, None)


# --- Ingest uses the check before calling a listing gone -----------------------------------

def test_live_post_missing_from_search_stays_active_with_price_update():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1", price=2500), OTHER])
    checked = []
    run_misses(source, 6, verify=lambda url: checked.append(url) or (True, 2935))
    listing = Listing.objects.get(street="937 NW Glisan Street")
    sl = listing.source_listings.get()
    assert listing.is_active and sl.is_active and sl.missed_runs == 0
    assert listing.price == 2935
    assert [(c.price, c.event) for c in listing.price_changes.all()] == [(2500, "First seen"), (2935, "Price change")]
    assert len(checked) == 2  # only checked when about to be called gone (every 3rd consecutive miss)


def test_deleted_post_is_confirmed_gone_when_checked():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1"), OTHER])
    checked = []
    run_misses(source, 2, verify=lambda url: checked.append(url) or (False, None))
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True and checked == []
    run_misses(source, 1, verify=lambda url: checked.append(url) or (False, None))
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is False and len(checked) == 1


def test_unknown_check_falls_back_to_counting_misses():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1"), OTHER])
    run_misses(source, 3, verify=lambda url: (None, None))
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is False


def test_recently_dropped_posts_are_rechecked_and_reactivated():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1"), OTHER])
    run_misses(source, 3)  # wrongly called gone before checks existed
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is False
    run_misses(source, 1, verify=lambda url: (True, None))
    listing = Listing.objects.get(street="937 NW Glisan Street")
    assert listing.is_active and listing.source_listings.get().is_active


def test_long_gone_posts_are_not_rechecked():
    source = make_source("craigslist")
    ingest(source, [scraped(external_id="cl1"), OTHER])
    run_misses(source, 3)
    SourceListing.objects.filter(external_id="cl1").update(last_seen_at=timezone.now() - timedelta(days=30))
    checked = []
    run_misses(source, 1, verify=lambda url: checked.append(url) or (True, None))
    assert checked == []


def test_checks_are_capped_per_run():
    source = make_source("craigslist")
    posts = [scraped(external_id=f"p{i}", address=f"{i + 1} NE Main St, Portland, OR 97211") for i in range(LISTING_CHECKS_PER_RUN + 5)]
    ingest(source, posts + [OTHER])
    run_misses(source, 2)
    checked = []
    run_misses(source, 1, verify=lambda url: checked.append(url) or (True, None))
    assert len(checked) == LISTING_CHECKS_PER_RUN


def test_runner_hands_the_scrapers_check_to_ingest(monkeypatch):
    captured = {}
    def fake_ingest(source, items, verify=None):
        captured["verify"] = verify
        return SimpleNamespace(new_listings=[], seen=len(items))

    monkeypatch.setattr(runner, "ingest", fake_ingest)

    class WithCheck(Scraper):
        def scrape(self):
            return [scraped()]

        def check_listing(self, url):
            return True, None

    monkeypatch.setattr(runner, "build_scraper", lambda config, fetcher=None: WithCheck(key="craigslist", name="Craigslist", fetcher=object()))
    runner.run_source({"key": "craigslist", "name": "Craigslist", "platform": "craigslist"})
    assert captured["verify"]("u") == (True, None)
