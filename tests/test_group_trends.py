from decimal import Decimal

import pytest

from accounts.groups import new_group
from listings import analyst
from listings.models import PropertyType, SearchPriorities, TrendReport
from tests.helpers import home_group, make_listing, make_user
from tests.test_analyst import FakeClient, final, message, pick

pytestmark = pytest.mark.django_db
DONE, AUTO = TrendReport.Status.DONE, TrendReport.Trigger.AUTO


def candidate(key, **extra):
    fields = dict(address_key=key, address=f"{key} St", street=f"{key} St", city="Portland", price=3000, beds=2,
                  baths=Decimal("2"), parking_spaces=2, property_type=PropertyType.CONDO, has_washer_dryer=True,
                  has_ac=True, has_outdoor_space=True)
    fields.update(extra)
    return make_listing(**fields)


def test_each_group_gets_its_own_report_prompt_and_history():
    pat_group = new_group("Pat's search")
    SearchPriorities.objects.create(group=home_group(), text="Near a park")
    SearchPriorities.objects.create(group=pat_group, text="Quiet street")
    listing = candidate("a")
    client = FakeClient(message({"shortlist": [{"id": listing.pk, "reason": ""}]}), message(final([pick(listing.pk)])))
    report = analyst.run_report(pat_group, client=client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert report.group == pat_group and report.status == DONE, report.error
    assert "Quiet street" in prompt and "Near a park" not in prompt
    assert "<their_default_filters>" in prompt


def test_another_groups_report_is_not_shown(client):
    pat_group = new_group("Pat's search")
    theirs = TrendReport.objects.create(group=pat_group, status=DONE, summary="Pat's secret summary")
    content = client.get(f"/trends/?report={theirs.pk}").content.decode()
    assert "Pat's secret summary" not in content and "Pat&#x27;s secret summary" not in content


def test_trends_page_uses_our_priorities(client):
    SearchPriorities.objects.create(group=new_group("Pat's search"), text="Their words")
    client.post("/trends/priorities/", {"text": "Our words"}, HTTP_HX_REQUEST="true")
    assert SearchPriorities.get(home_group()).text == "Our words"
    content = client.get("/trends/").content.decode()
    assert "Our words" in content and "Their words" not in content


def test_manual_runs_are_counted_per_group(settings):
    settings.TRENDS_MANUAL_RUNS_PER_DAY = 2
    TrendReport.objects.create(group=new_group("Pat's search"), trigger=TrendReport.Trigger.MANUAL)
    assert analyst.manual_runs_left(home_group()) == 2


def test_daily_runs_each_group_with_members_once(monkeypatch, owner):
    pat_group = make_user("pat@example.com", "Pat", group=new_group("Pat's search")).profile.group
    new_group("Nobody's search")
    started = []
    monkeypatch.setattr(analyst, "start_reports", lambda groups, trigger: started.append(([g.pk for g in groups], trigger)) or True)
    monkeypatch.setattr(analyst, "is_configured", lambda: True)
    assert analyst.run_daily_if_due() is True
    assert started == [([home_group().pk, pat_group.pk], AUTO)]
    TrendReport.objects.create(group=home_group(), trigger=AUTO, status=DONE)
    TrendReport.objects.create(trigger=AUTO, status=DONE)  # a report with no group must not hide everyone
    started.clear()
    assert analyst.run_daily_if_due() is True
    assert started == [([pat_group.pk], AUTO)]


def test_reports_run_one_after_another(monkeypatch):
    groups = [home_group(), new_group("Pat's search")]
    ran = []
    monkeypatch.setattr(analyst, "run_report", lambda group, trigger, report=None: ran.append((group.pk, report is not None)))
    monkeypatch.setattr(analyst.threading, "Thread", lambda target, **kw: type("T", (), {"start": staticmethod(target)})())
    assert analyst.start_reports(groups, AUTO) is True
    assert ran == [(groups[0].pk, True), (groups[1].pk, False)]
    assert not analyst._lock.locked()


def test_a_run_for_another_group_blocks_with_a_clear_message(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    TrendReport.objects.create(group=new_group("Pat's search"), status=TrendReport.Status.RUNNING)
    response = client.post("/trends/run/", follow=True)
    assert "Another household" in response.content.decode()
