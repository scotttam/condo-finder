import pytest

from listings import analyst, runner, scheduler

pytestmark = pytest.mark.django_db


def test_scheduled_run_starts_the_daily_report_after_scraping(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run_all", lambda: calls.append("scrape"))
    monkeypatch.setattr(analyst, "run_daily_if_due", lambda: calls.append("trends"))
    scheduler._scheduled_run()
    assert calls == ["scrape", "trends"]


def test_daily_report_still_runs_when_the_scrape_raised(monkeypatch):
    calls = []

    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "run_all", broken)
    monkeypatch.setattr(analyst, "run_daily_if_due", lambda: calls.append("trends"))
    with pytest.raises(RuntimeError):
        scheduler._scheduled_run()
    assert calls == ["trends"]


def test_a_trends_failure_does_not_break_the_scheduler(monkeypatch):
    monkeypatch.setattr(runner, "run_all", lambda: None)

    def broken():
        raise RuntimeError("db locked")

    monkeypatch.setattr(analyst, "run_daily_if_due", broken)
    scheduler._scheduled_run()  # logged, not raised
