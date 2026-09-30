import json
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from listings import analyst
from listings.models import PriceChange, PropertyType, SearchPriorities, Status, TrendReport
from listings.collab import set_status
from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def release_lock():
    yield
    if analyst._lock.locked():  # a test's stubbed _launch never finishes the run that holds it
        analyst._lock.release()


def usage(inp=1000, out=500, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write
    )


def message(payload, stop_reason="end_turn", used=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(payload))],
        stop_reason=stop_reason,
        stop_details=None,
        usage=used or usage(),
        model="claude-opus-5-5",
    )


class FakeStream:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.result


class FakeClient:
    """Stands in for anthropic.Anthropic(); returns queued messages and records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.results.pop(0))


_seq = iter(range(1, 10_000))


def candidate(price=3000, **extra):
    n = next(_seq)
    fields = dict(
        address_key=f"{n} nw test st||97209", address=f"{n} NW Test St, Portland, OR 97209", street=f"{n} NW Test St", unit="",
        city="Portland", zip_code="97209", price=price, beds=2, baths=Decimal("2"), parking_spaces=2,
        property_type=PropertyType.CONDO, has_washer_dryer=True, has_ac=True, has_outdoor_space=True,
        description="Sunny corner unit with a big deck.",
    )
    fields.update(extra)
    return make_listing(**fields)


def pick(listing_id, **extra):
    fields = dict(id=listing_id, headline="Great fit", why="Checks every box", concerns=["Street noise"],
                  questions=["Is the parking deeded?"], leverage="Cut twice; 40 days listed", offer_low=2800, offer_high=2900)
    fields.update(extra)
    return fields


def final(picks, market_read="Rents are softening.", summary="Two strong options."):
    return {"picks": picks, "market_read": market_read, "summary": summary}


def test_candidates_are_default_filter_matches_plus_tracked():
    match = candidate()
    too_cheap = candidate(price=1200)
    liked_but_cheap = candidate(price=1500, status=Status.INTERESTED)
    rejected = candidate(status=Status.REJECTED)
    apartment = candidate(property_type=PropertyType.APARTMENT)
    ids = {listing.pk for listing in analyst.candidates(home_group())}
    assert ids == {match.pk, liked_but_cheap.pk}
    assert [listing.pk for listing in analyst.passed_on(home_group())] == [rejected.pk]
    assert too_cheap.pk not in ids and apartment.pk not in ids


def test_compact_facts_describe_unknowns_and_history():
    listing = candidate(parking_spaces=None, has_parking=None, has_ac=None, notes="Loved the kitchen")
    PriceChange.objects.create(listing=listing, price=3200, seen_at=timezone.now() - timedelta(days=20), event="Listed for rent")
    facts = analyst.compact_facts(analyst._prepare([listing], home_group())[0])
    assert facts["parking"] == "unknown"
    assert facts["ac"] == "unknown" and facts["wd"] == "yes"
    assert facts["price_history"][0][1:] == [3200, "Listed for rent"]
    assert facts["comments"][0]["text"] == "Loved the kitchen"
    assert "description" not in facts
    assert analyst.full_facts(analyst._prepare([listing], home_group())[0])["description"] == "Sunny corner unit with a big deck."


def test_run_report_makes_two_passes_and_saves_picks():
    a, b, c = candidate(price=3000), candidate(price=3100), candidate(price=3200)
    rejected = candidate(status=Status.REJECTED, notes="Too dark")
    SearchPriorities.objects.create(group=home_group(), text="Near a park")
    client = FakeClient(
        message({"shortlist": [{"id": a.pk, "reason": "value"}, {"id": b.pk, "reason": "deck"}, {"id": 99999, "reason": "?"}]},
                used=usage(inp=40_000, out=2_000)),
        message(final([pick(b.pk, headline="Best deck"), pick(a.pk)]), used=usage(inp=10_000, out=3_000)),
    )
    report = analyst.run_report(client=client)
    assert report.status == TrendReport.Status.DONE, report.error
    first, second = client.calls
    for call in (first, second):
        assert call["model"] == "claude-opus-5-5"
        assert call["fallbacks"] == "default"
        assert call["betas"] == ["server-side-fallback-2026-07-01"]
        assert call["output_config"]["format"]["type"] == "json_schema"
        assert "thinking" not in call
    assert first["output_config"]["effort"] == "medium"
    assert second["output_config"]["effort"] == "high"
    assert "Near a park" in first["messages"][0]["content"]
    assert "Sunny corner unit" not in first["messages"][0]["content"]  # pass 1 is compact
    assert str(c.pk) in first["messages"][0]["content"]
    pass2 = second["messages"][0]["content"]
    assert "Sunny corner unit" in pass2 and "Too dark" in pass2
    assert report.shortlist == [a.pk, b.pk]  # unknown id dropped
    assert [(p["rank"], p["listing_id"], p["headline"]) for p in report.picks] == [(1, b.pk, "Best deck"), (2, a.pk, "Great fit")]
    assert report.picks[0]["price_at_pick"] == 3100 and report.picks[0]["address"] == b.street
    assert report.market_read == "Rents are softening." and report.summary == "Two strong options."
    assert report.input_tokens == 50_000 and report.output_tokens == 5_000
    assert report.cost_usd == Decimal("0.3000")  # 50k × $4/M + 5k × $20/M
    assert "now" in report.stats and "weekly" in report.stats
    assert report.finished_at is not None


def test_picks_drop_unknown_duplicate_and_rejected_ids():
    a, b = candidate(), candidate()
    rejected = candidate(status=Status.REJECTED)
    client = FakeClient(
        message({"shortlist": [{"id": a.pk, "reason": ""}, {"id": b.pk, "reason": ""}]}),
        message(final([pick(rejected.pk), pick(a.pk), pick(a.pk), pick(424242), pick(b.pk)])),
    )
    report = analyst.run_report(client=client)
    assert [(p["rank"], p["listing_id"]) for p in report.picks] == [(1, a.pk), (2, b.pk)]


def test_only_five_picks_are_kept():
    listings = [candidate() for _ in range(7)]
    client = FakeClient(
        message({"shortlist": [{"id": l.pk, "reason": ""} for l in listings]}),
        message(final([pick(l.pk) for l in listings])),
    )
    assert len(analyst.run_report(client=client).picks) == 5


def test_refusal_fails_the_report():
    candidate()
    client = FakeClient(message({}, stop_reason="refusal"))
    report = analyst.run_report(client=client)
    assert report.status == TrendReport.Status.FAILED
    assert "declined" in report.error


def test_api_error_fails_the_report():
    candidate()
    report = analyst.run_report(client=FakeClient(RuntimeError("connection reset")))
    assert report.status == TrendReport.Status.FAILED
    assert "connection reset" in report.error


def test_no_candidates_fails_without_calling_claude():
    client = FakeClient()
    report = analyst.run_report(client=client)
    assert report.status == TrendReport.Status.FAILED
    assert client.calls == []


def test_previous_picks_are_sent_and_changes_recorded():
    a, b, c = candidate(price=3000), candidate(), candidate()
    TrendReport.objects.create(
        status=TrendReport.Status.DONE,
        picks=[{"listing_id": a.pk, "rank": 1, "headline": "Old A", "price_at_pick": 3200, "address": a.street},
               {"listing_id": c.pk, "rank": 2, "headline": "Old C", "price_at_pick": 3000, "address": c.street}],
    )
    set_status(c, home_group(), None, Status.REJECTED)
    client = FakeClient(
        message({"shortlist": [{"id": a.pk, "reason": ""}, {"id": b.pk, "reason": ""}]}),
        message(final([pick(a.pk), pick(b.pk)])),
    )
    report = analyst.run_report(client=client)
    assert "Old A" in client.calls[1]["messages"][0]["content"]
    assert report.changes["added"] == [b.pk]
    assert report.changes["dropped"] == [{"id": c.pk, "headline": "Old C", "address": c.street, "why": "you rejected it"}]
    assert report.changes["price_moves"] == [{"id": a.pk, "address": a.street, "from": 3200, "to": 3000}]


def test_cost_of_prices_every_token_kind():
    assert analyst.cost_of(usage(inp=1_000_000, out=100_000, cache_read=1_000_000, cache_write=200_000)) == Decimal("7.2000")


def test_manual_runs_left_counts_todays_manual_reports(settings):
    settings.TRENDS_MANUAL_RUNS_PER_DAY = 3
    TrendReport.objects.create(trigger=TrendReport.Trigger.MANUAL)
    TrendReport.objects.create(trigger=TrendReport.Trigger.AUTO)
    TrendReport.objects.create(trigger=TrendReport.Trigger.MANUAL, created_at=timezone.now() - timedelta(days=1))
    assert analyst.manual_runs_left() == 2


def test_is_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert not analyst.is_configured()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert analyst.is_configured()


def test_start_report_refuses_while_one_is_running(monkeypatch):
    started = []
    monkeypatch.setattr(analyst, "_launch", lambda report: started.append(report))
    TrendReport.objects.create(status=TrendReport.Status.RUNNING)
    assert analyst.is_running()
    assert analyst.start_report("manual") is False
    assert started == []


def test_stale_running_report_does_not_block_and_is_marked_failed(monkeypatch):
    started = []
    monkeypatch.setattr(analyst, "_launch", lambda report: started.append(report))
    stale = TrendReport.objects.create(status=TrendReport.Status.RUNNING, created_at=timezone.now() - timedelta(hours=2))
    assert not analyst.is_running()
    assert analyst.start_report("manual") is True
    stale.refresh_from_db()
    assert stale.status == TrendReport.Status.FAILED
    assert started[0].status == TrendReport.Status.RUNNING and started[0].trigger == "manual"


def test_start_report_refuses_while_the_lock_is_held(monkeypatch):
    monkeypatch.setattr(analyst, "_launch", lambda report: None)
    with analyst._lock:
        assert analyst.start_report("manual") is False


def test_run_daily_if_due(monkeypatch):
    started = []
    monkeypatch.setattr(analyst, "start_report", lambda trigger: started.append(trigger) or True)
    monkeypatch.setattr(analyst, "is_configured", lambda: True)
    assert analyst.run_daily_if_due() is True
    TrendReport.objects.create(trigger=TrendReport.Trigger.AUTO, status=TrendReport.Status.DONE)
    assert analyst.run_daily_if_due() is False
    assert started == ["auto"]


def test_run_daily_retries_after_a_failed_daily_run(monkeypatch):
    monkeypatch.setattr(analyst, "start_report", lambda trigger: True)
    monkeypatch.setattr(analyst, "is_configured", lambda: True)
    TrendReport.objects.create(trigger=TrendReport.Trigger.AUTO, status=TrendReport.Status.FAILED)
    assert analyst.run_daily_if_due() is True


def test_run_daily_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(analyst, "is_configured", lambda: False)
    monkeypatch.setattr(analyst, "start_report", lambda trigger: pytest.fail("should not start"))
    assert analyst.run_daily_if_due() is False
