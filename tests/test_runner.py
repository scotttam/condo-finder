import httpx
import pytest
from django.core.management import call_command

from listings import runner
from listings.models import Listing, Source, SourceRun
from tests.helpers import FakeFetcher, load_fixture

pytestmark = pytest.mark.django_db

PEARL = {"key": "pearl", "name": "Pearl", "platform": "appfolio", "subdomain": "pearlpropertymanagement"}
LIST_URL = "https://pearlpropertymanagement.appfolio.com/listings"


class BrokenFetcher:
    def get(self, url):
        raise httpx.ConnectError("blocked")


def pearl_fetcher():
    return FakeFetcher({LIST_URL: load_fixture("appfolio_list.html")}, default=load_fixture("appfolio_detail.html"))


def test_successful_run_ingests_and_records():
    run = runner.run_source(PEARL, fetcher=pearl_fetcher())
    assert run.ok and run.count == 7 and run.finished_at is not None
    assert run.new_count == Listing.objects.count() > 0
    source = Source.objects.get(key="pearl")
    assert source.last_count == 7 and source.consecutive_failures == 0 and source.last_success_at


def test_failures_are_recorded_for_the_sources_page():
    for _ in range(3):
        run = runner.run_source(PEARL, fetcher=BrokenFetcher())
        assert not run.ok and "ConnectError" in run.error
    source = Source.objects.get(key="pearl")
    assert source.consecutive_failures == 3
    assert "ConnectError" in source.last_error and source.last_error_at


def test_success_resets_failures():
    runner.run_source(PEARL, fetcher=BrokenFetcher())
    runner.run_source(PEARL, fetcher=pearl_fetcher())
    assert Source.objects.get(key="pearl").consecutive_failures == 0


def test_empty_result_is_a_failure_and_keeps_listings_active():
    runner.run_source(PEARL, fetcher=pearl_fetcher())
    run = runner.run_source(PEARL, fetcher=FakeFetcher({LIST_URL: "<html></html>"}))
    assert not run.ok and "0 listings" in run.error
    assert Source.objects.get(key="pearl").consecutive_failures == 1
    assert Listing.objects.filter(is_active=True).count() > 0


def test_run_all_filters_keys_then_redetects_and_geocodes(monkeypatch):
    called = []
    monkeypatch.setattr(runner, "run_source", lambda config: called.append(config["key"]) or config["key"])
    monkeypatch.setattr(runner, "reextract_all", lambda: called.append("reextract") or 0)
    monkeypatch.setattr(runner, "geocode_pending", lambda: called.append("geocode"))
    assert runner.run_all(keys=["uptown", "pearl"]) == ["pearl", "uptown"]
    assert called == ["pearl", "uptown", "reextract", "geocode"]


def test_run_all_survives_redetection_errors(monkeypatch):
    monkeypatch.setattr(runner, "run_source", lambda config: config["key"])
    monkeypatch.setattr(runner, "reextract_all", lambda: 1 / 0)
    monkeypatch.setattr(runner, "geocode_pending", lambda: None)
    assert runner.run_all(keys=["pearl"]) == ["pearl"]


def test_run_all_skips_when_already_running(monkeypatch):
    monkeypatch.setattr(runner, "run_source", lambda config: pytest.fail("should not run"))
    runner._run_lock.acquire()
    try:
        assert runner.is_running()
        assert runner.run_all() == []
    finally:
        runner._run_lock.release()


def test_scrape_command(monkeypatch, capsys):
    source = Source.objects.create(key="pearl", name="Pearl", platform="appfolio")
    fake_run = SourceRun(source=source, ok=True, count=7, new_count=2)
    monkeypatch.setattr("listings.management.commands.scrape.run_all", lambda keys, geocode: [fake_run])
    call_command("scrape", "--source", "pearl", "--no-geocode")
    assert "pearl: ok — 7 listings, 2 new" in capsys.readouterr().out
