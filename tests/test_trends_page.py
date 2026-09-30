import re
from decimal import Decimal

import pytest

from listings import analyst
from listings.models import SearchPriorities, Status, TrendReport
from tests.helpers import make_listing, status_of

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


_seq = iter(range(1, 10_000))


def listing(**extra):
    n = next(_seq)
    fields = dict(address_key=f"{n} test||", address=f"{n} NW Test St, Portland", street=f"{n} NW Test St", unit="",
                  price=3000, beds=2, baths=Decimal("2"), parking_spaces=2)
    fields.update(extra)
    return make_listing(**fields)


def pick_for(item, rank, **extra):
    fields = dict(listing_id=item.pk, rank=rank, headline=f"Headline {rank}", why=f"Why {rank}", concerns=[f"Concern {rank}"],
                  questions=[f"Question {rank}"], leverage=f"Leverage {rank}", offer_low=2800, offer_high=2900,
                  price_at_pick=item.price, address=item.street, photo_url="")
    fields.update(extra)
    return fields


def done_report(picks, **extra):
    fields = dict(status=TrendReport.Status.DONE, picks=picks, market_read="Rents are softening.\n\nCuts are common.",
                  summary="Two strong options this week.", cost_usd=Decimal("0.4212"),
                  stats={"now": {"active_count": 12, "median_rent": 3100, "median_rent_by_city": {"Portland": 3100},
                                 "median_ppsf": 2.1, "cut_share": 0.25, "median_dom": 18},
                         "weekly": {"weeks": ["2026-09-22", "2026-09-29"], "tracking_since": "2026-09-20",
                                    "median_rent_by_city": {"Portland": [3200, 3100]}, "cut_share": [0.2, 0.25], "median_dom": [15, 18]}})
    fields.update(extra)
    return TrendReport.objects.create(**fields)


def page(client, url="/trends/"):
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


def test_nav_links_to_trends(client):
    assert '<a href="/trends/">Trends</a>' in page(client, "/")


def test_empty_page_invites_a_first_run(client):
    content = page(client)
    assert "No report yet" in content
    assert re.search(r'<button type="submit"[^>]*>Run the analysis</button>', content)


def test_unconfigured_explains_the_key_and_disables_the_button(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    content = page(client)
    assert "ANTHROPIC_API_KEY" in content
    assert re.search(r'<button type="submit"[^>]*disabled', content)


def test_report_renders_ranked_pick_cards(client):
    items = [listing(price=3000 + i) for i in range(5)]
    done_report([pick_for(item, rank) for rank, item in enumerate(items, 1)])
    content = page(client)
    assert "Two strong options this week." in content
    positions = [content.index(f"Headline {rank}") for rank in range(1, 6)]
    assert positions == sorted(positions)
    assert content.count('<article class="pick"') == 5
    assert "Leverage 1" in content and "Concern 1" in content and "Question 1" in content
    assert "Offer $2,800–$2,900" in content
    assert f'href="/listing/{items[0].pk}/"' in content
    assert "Rents are softening.</p>" in content and "<p>Cuts are common.</p>" in content


def test_pick_for_a_deleted_or_off_market_listing_still_renders(client):
    gone = listing(is_active=False)
    deleted = listing()
    report = done_report([pick_for(gone, 1), pick_for(deleted, 2, address="12 Vanished Ave")])
    deleted.delete()
    content = page(client)
    assert "12 Vanished Ave" in content
    assert re.search(r'<span class="offmarket-pill">Off market</span>', content)
    assert report.pk


def test_pick_cards_have_status_pills_that_post_and_swap(client):
    item = listing(status=Status.INTERESTED)
    done_report([pick_for(item, 1)])
    content = page(client)
    assert re.search(rf'<form id="pills-{item.pk}"[^>]*hx-post="/listing/{item.pk}/status/"', content)
    assert re.search(r'name="status" value="interested" checked', content)
    response = client.post(f"/listing/{item.pk}/status/", {"status": "toured", "variant": "pills"}, HTTP_HX_REQUEST="true")
    swapped = response.content.decode()
    assert swapped.lstrip().startswith(f'<form id="pills-{item.pk}"')
    assert re.search(r'name="status" value="toured" checked', swapped)
    assert status_of(item) == Status.TOURED


def test_market_section_shows_snapshot_and_charts(client):
    done_report([])
    content = page(client)
    assert "$3,100" in content and "25%" in content and "18 days" in content
    assert content.count('<svg class="trend-chart"') == 3
    assert "Tracking since Sep 20" in content


def test_charts_show_a_placeholder_without_data(client):
    content = page(client)
    assert "Not enough data yet" in content


def test_priorities_box_saves(client):
    SearchPriorities.objects.create(pk=1, text="Near a park")
    content = page(client)
    assert re.search(r'<textarea name="text"[^>]*>Near a park</textarea>', content)
    response = client.post("/trends/priorities/", {"text": "Quiet street, walkable"}, HTTP_HX_REQUEST="true")
    assert "Saved ✓" in response.content.decode()
    assert SearchPriorities.get().text == "Quiet street, walkable"


def test_rerun_starts_a_report(client, monkeypatch):
    started = []
    monkeypatch.setattr(analyst, "start_report", lambda trigger: started.append(trigger) or True)
    response = client.post("/trends/run/")
    assert response.status_code == 302 and response.url == "/trends/"
    assert started == ["manual"]


def test_rerun_at_the_daily_cap_does_not_start(client, monkeypatch, settings):
    settings.TRENDS_MANUAL_RUNS_PER_DAY = 1
    TrendReport.objects.create(status=TrendReport.Status.DONE)
    monkeypatch.setattr(analyst, "start_report", lambda trigger: pytest.fail("should not start"))
    content = client.post("/trends/run/", follow=True).content.decode()
    assert "used all 1 re-runs" in content
    assert re.search(r'<button type="submit"[^>]*disabled', content)


def test_rerun_without_a_key_does_not_start(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(analyst, "start_report", lambda trigger: pytest.fail("should not start"))
    client.post("/trends/run/")


def test_running_report_shows_a_polling_banner(client, monkeypatch):
    monkeypatch.setattr(analyst, "is_running", lambda: True)
    content = page(client)
    assert re.search(r'<div id="trend-status"[^>]*hx-get="/trends/status/"[^>]*hx-trigger="every 4s"', content)
    assert client.get("/trends/status/").content.decode().count('id="trend-status"') == 1


def test_status_endpoint_refreshes_the_page_when_done(client, monkeypatch):
    monkeypatch.setattr(analyst, "is_running", lambda: False)
    response = client.get("/trends/status/")
    assert response.headers["HX-Refresh"] == "true"


def test_failed_latest_report_shows_its_error(client):
    done_report([])
    TrendReport.objects.create(status=TrendReport.Status.FAILED, error="Claude declined this request.")
    content = page(client)
    assert "The last run failed" in content and "Claude declined this request." in content


def test_older_reports_open_from_the_dropdown(client):
    item = listing()
    old = done_report([pick_for(item, 1, headline="Old headline")], summary="Old summary")
    done_report([pick_for(item, 1, headline="New headline")], summary="New summary")
    content = page(client)
    assert "New summary" in content and "Old summary" not in content
    assert re.search(rf'<option value="{old.pk}"[^>]*>', content)
    content = page(client, f"/trends/?report={old.pk}")
    assert "Old summary" in content and "Old headline" in content
    assert "You're viewing an older report" in content


def test_unknown_report_id_falls_back_to_the_latest(client):
    done_report([], summary="Latest summary")
    assert "Latest summary" in page(client, "/trends/?report=9999")
    assert "Latest summary" in page(client, "/trends/?report=abc")


def test_what_changed_panel(client):
    kept, added = listing(), listing()
    done_report(
        [pick_for(kept, 1), pick_for(added, 2)],
        changes={"added": [added.pk],
                 "dropped": [{"id": 999, "headline": "Gone one", "address": "5 Old Rd", "why": "you rejected it"}],
                 "price_moves": [{"id": kept.pk, "address": kept.street, "from": 3200, "to": 3000}]},
    )
    content = page(client)
    panel = content[content.index('<section class="changes"'):content.index("</section>", content.index('<section class="changes"'))]
    assert f"New pick: <a href=\"/listing/{added.pk}/\">" in panel
    assert "Dropped: 5 Old Rd (you rejected it)" in panel
    assert "$3,200 → $3,000" in panel


def test_no_changes_panel_without_changes(client):
    done_report([])
    assert '<section class="changes"' not in page(client)
