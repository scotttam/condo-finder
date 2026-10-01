import pytest
from bs4 import BeautifulSoup

from listings import views
from listings.models import Source, SourceRun
from listings.scrapers.registry import SOURCES

pytestmark = pytest.mark.django_db


def test_sources_page_lists_registry_and_runs(client):
    response = client.get("/sources/")
    assert response.status_code == 200
    assert Source.objects.count() == len(SOURCES)
    source = Source.objects.get(key="pearl")
    SourceRun.objects.create(source=source, ok=False, error="ConnectError: blocked")
    response = client.get("/sources/")
    assert b"Pearl Property Management" in response.content
    assert b"ConnectError: blocked" in response.content
    assert b"Scrape now" in response.content


def test_scrape_now_starts_background_run(client, monkeypatch):
    started = []
    monkeypatch.setattr(views, "run_all_in_background", lambda: started.append(True))
    response = client.post("/sources/scrape/", follow=True)
    assert started == [True]
    assert b"Scrape started" in response.content


def test_scrape_now_when_running(client, monkeypatch):
    monkeypatch.setattr(views, "is_running", lambda: True)
    monkeypatch.setattr(views, "run_all_in_background", lambda: pytest.fail("should not start"))
    response = client.post("/sources/scrape/", follow=True)
    assert b"already running" in response.content


def test_sources_page_links_staff_to_sql_console(client):
    link = BeautifulSoup(client.get("/sources/").content, "html.parser").find("a", string="SQL console")
    assert link["href"] == "/sql/"


def test_disabled_source_is_marked_on_the_sources_page(client):
    from bs4 import BeautifulSoup

    client.get("/sources/")  # populates Source rows from the registry
    assert Source.objects.filter(key="pearl").update(is_enabled=False) == 1
    soup = BeautifulSoup(client.get("/sources/").content, "html.parser")
    row = next(tr for tr in soup.find_all("tr") if "Pearl Property Management" in tr.get_text())
    assert row.find("span", string="disabled") is not None
    other = next(tr for tr in soup.find_all("tr") if "Mainlander" in tr.get_text())
    assert other.find("span", string="disabled") is None
